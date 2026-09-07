from abc import ABC, abstractmethod
from erpnext import ERPNextAPI, ERPNextDocType, ERPNextHelper
from pathlib import Path
import config
from weclapp import WeClappDocType

class BaseMigration(ABC):
    """Base class for all migration classes.
    Used to migrate a single dataset from WeClapp to ERPNext.
    Using a existing dict-Object from WeClapp-API.
    """

    def __init__(self, en_api: ERPNextAPI, wc_data: dict, wc_custom_attribute_definitions: dict):
        """Initializes the migration wrapper.

        Args:
            en_api (ERPNextAPI): ERPNext-API-Object
            wc_data (dict): WeClapp-API-Object
            wc_custom_attribute_definitions (dict): WeClapp custom attribute definitions
        """
        self._en_api = en_api
        self.wc_data = wc_data
        self.wc_custom_attribute_definitions = wc_custom_attribute_definitions
        self._is_primary = False

    def migrate(self) -> dict:
        """Migrates a given WeClapp-Object and creates it in ERPNext.

        Returns:
            dict: Data of the created entity
        """
        return self._en_api.create(self.get_doctype(), self._transform())

    def is_primary(self) -> bool:
        """Returns if the contact is the primary contact of the customer.
        """
        return self._is_primary

    def _map_custom_attributes(self, wc_custom_attributes: list = None) -> dict:
        """Maps WeClapp custom attributes (Zusatzfelder) to a dict of ERPNext custom fieldnames.
        The ERPNext custom field must exist with fieldname ERPNextHelper.get_custom_fieldname(attributeKey)
        (see create_custom_fields.py), since Frappe silently drops unknown fields on insert.

        Args:
            wc_custom_attributes (list, optional): List of WeClapp customAttributes entries.
            Defaults to self.wc_data.get("customAttributes", []).

        Returns:
            dict: Mapped custom field values, keyed by attributeKey
        """
        if wc_custom_attributes is None:
            # "or []": WeClapp contacts store an explicit null instead of an empty list
            wc_custom_attributes = self.wc_data.get("customAttributes") or []

        mapped = {}
        for ca in wc_custom_attributes:
            attr_def = (self.wc_custom_attribute_definitions or {}).get(ca.get("attributeDefinitionId"))
            if not attr_def:
                continue

            key = attr_def.get("attributeKey")
            if key in config.EN_CUSTOM_ATTRIBUTE_EXCLUDE:
                continue
            value = None

            attr_type = attr_def.get("attributeType")
            if attr_type == "BOOLEAN":
                value = ca.get("booleanValue")
            elif attr_type == "DECIMAL":
                value = ca.get("numberValue")
            elif attr_type in ["STRING", "LARGE_TEXT", "URL"]:
                value = ca.get("stringValue")
            elif attr_type == "LIST":
                value_id = ca.get("selectedValueId")
                if value_id:
                    for selectable_value in attr_def.get("selectableValues", []):
                        if selectable_value.get("id") == value_id:
                            value = selectable_value.get("value")
                            break
            elif attr_type == "MULTISELECT_LIST":
                value_ids = [v.get("id") for v in ca.get("selectedValues", [])]
                values = []
                if value_ids:
                    for selectable_value in attr_def.get("selectableValues", []):
                        if selectable_value.get("id") in value_ids:
                            values.append(selectable_value.get("value"))
                if key in config.EN_MULTISELECT_TABLE_FIELDS:
                    # Real multi-select dropdown (Table MultiSelect, see setup.py):
                    # child rows linking to the option records instead of a joined string
                    value = [{"wert": v} for v in values] if values else None
                elif values:
                    value = ", ".join(values)

            if key and value is not None:
                mapped[ERPNextHelper.get_custom_fieldname(key)] = value

        return mapped

    def _map_wc_notes(self, fields: tuple = ("recordFreeText", "recordOpening", "note")) -> str:
        """Maps WeClapp's internal note/free-text fields to a single joined string. These are
        purely internal (visible only inside WeClapp, not on printed documents) - present as
        recordFreeText/recordOpening/note on most transactional WeClapp doctypes (Sales/Purchase
        Order/Invoice, Quotation, Shipment). Customer/Supplier don't have these fields at all,
        only "description" - callers there pass fields=("description",) instead.

        Args:
            fields (tuple, optional): WeClapp field names to check, in order. Defaults to the
                transactional-document fields.

        Returns:
            str: Joined non-empty note values, or an empty string if none are set
        """
        values = [self.wc_data.get(f) for f in fields]
        return "\n".join(v for v in values if v)

    def _map_wc_comments(self, comments: list) -> str:
        """Formats WeClapp's linked comments ("Kommentare") as plain-text lines, each prefixed
        with its date and author. This is WeClapp's general-purpose internal-note feature -
        attached to an entity via a separate API endpoint (entityName/entityId, no bulk listing),
        entirely distinct from description/recordFreeText/note (_map_wc_notes()). Customer and
        Supplier share the same underlying WeClapp "party" id, so a single comment can show up
        for both - see WcCacheApi.get_comments()/WcCacheWrapper._cache_comments().

        Plain text, not HTML: the target fields (ERPNext's native Customer.customer_details/
        Supplier.supplier_details) are plain "Text" fieldtype, which renders content as-is rather
        than interpreting it - HTML markup would show up as literal tags. WeClapp's own
        "comment" field is itself already plain text in practice (confirmed live: "htmlComment"
        is null on every cached comment), strip_html() here is just defensive.

        Args:
            comments (list): List of WeClapp comment dicts (id, comment, authorUserUsername,
                createdDate, ...), typically looked up by party id from WcCacheApi.get_comments()

        Returns:
            str: Joined plain-text lines, or an empty string if there are none
        """
        parts = []
        for c in sorted(comments, key=lambda c: c.get("createdDate") or 0):
            text = ERPNextHelper.strip_html(c.get("comment"))
            if not text:
                continue
            date = ERPNextHelper.get_date_from_weclapp_ts(c["createdDate"]) if c.get("createdDate") else "?"
            author = c.get("authorUserUsername") or "?"
            parts.append(f"{date} ({author}): {text}")
        return "\n".join(parts)

    def _map_net_rate(self, item: dict) -> float:
        """Computes the true net unit rate of a WeClapp line item from its authoritative netAmount.
        WeClapp's "unitPrice" is the gross (tax-inclusive), pre-discount list price - feeding it
        directly into ERPNext's rate/price_list_rate (which ERPNext treats as net) causes ERPNext
        to add tax on top of an already tax-inclusive figure, inflating totals by roughly the tax
        rate. netAmount is always the final, authoritative net line total (after any discount),
        so netAmount/quantity is used instead regardless of unitPrice's exact semantics.

        Args:
            item (dict): WeClapp line item (invoice/order/quotation item)

        Returns:
            float: Net unit rate
        """
        # Signed on purpose: discount/reduction lines inside a normal invoice carry a negative
        # netAmount and must keep their negative rate (requires "Allow negative rates for items"
        # in ERPNext's Selling/Buying Settings). shippingCostItems have no "quantity" key at all
        # (always a single charge) and zero-quantity free-text lines exist too - both default to 1.
        quantity = float(item.get("quantity", 1) or 1)
        if quantity == 0:
            quantity = 1.0
        net_amount = float(item.get("netAmount", 0) or 0)
        return net_amount / quantity

    def _map_item_qty(self, item: dict) -> float:
        """Maps the quantity of a WeClapp line item.
        Zero-quantity lines (free-text/zero lines in WeClapp) are mapped to quantity 1, since
        ERPNext rejects documents with zero-quantity items (InvalidQtyError) - _map_net_rate
        uses the same fallback, so amount stays exactly netAmount.

        Args:
            item (dict): WeClapp line item

        Returns:
            float: Quantity (at least 1)
        """
        qty = float(item.get("quantity", 0) or 0)
        return qty if qty else 1.0

    def _header_adjustment_percentage(self) -> float:
        """Returns the document-level discount percentage (headerDiscount minus headerSurcharge).
        Mapped to ERPNext's additional_discount_percentage on Net Total - a surcharge becomes
        a negative discount.
        """
        discount = float(self.wc_data.get("headerDiscount", 0) or 0)
        surcharge = float(self.wc_data.get("headerSurcharge", 0) or 0)
        return discount - surcharge

    def _map_header_discount_amount(self, items_field: str, negate: bool = False) -> float:
        """Returns the document-level discount as an absolute amount on Net Total.
        WeClapp applies headerDiscount/headerSurcharge only to the regular item lines, NOT to
        shippingCostItems (verified against all cached documents) - ERPNext's percentage
        discount would hit the whole net total including the shipping lines, so an exact
        amount is used instead.

        Args:
            items_field (str): Name of the WeClapp line-item field (e.g. "salesInvoiceItems")
            negate (bool): Negate the amount (credit notes / returns)

        Returns:
            float: Discount amount (positive = discount, negative = surcharge)
        """
        percentage = self._header_adjustment_percentage()
        if not percentage:
            return 0.0
        net_sum = sum(float(i.get("netAmount", 0) or 0) for i in self.wc_data.get(items_field, []))
        amount = round(net_sum * percentage / 100.0, 2)
        return -amount if negate else amount

    def _add_tax(self, tax_mapping: dict, item: dict, header_discountable: bool = True) -> None:
        """Accumulates the exact tax amount (grossAmount - netAmount) of a WeClapp line item
        per tax ID in self.taxes. Booked later via _map_taxes as charge_type "Actual" rows, so
        document totals match WeClapp to the cent instead of re-deriving the tax via percentage
        application and rounding (which drifts by cents and breaks on mixed-rate documents).

        Args:
            tax_mapping (dict): WC_EN tax mapping table of the concrete migration
            item (dict): WeClapp line item
            header_discountable (bool): False for shipping lines - WeClapp's header
                discount/surcharge (and thus its tax scaling) does not apply to them
        """
        tax_info = tax_mapping.get(item.get("taxId", str()), None)
        if tax_info and tax_info.tax_account:
            tax_id = item.get("taxId", str())
            # Signed: discount/reduction lines (negative amounts) reduce the tax accordingly
            delta = float(item.get("grossAmount", 0) or 0) - float(item.get("netAmount", 0) or 0)
            discountable, fixed = self.taxes.get(tax_id, (0.0, 0.0))
            if header_discountable:
                discountable += delta
            else:
                fixed += delta
            self.taxes[tax_id] = (discountable, fixed)

    def _map_taxes(self, tax_mapping: dict, negate: bool = False) -> list[dict]:
        """Maps the accumulated taxes (see _add_tax) to ERPNext "Actual" tax rows.
        The per-item tax deltas don't include the header discount/surcharge yet (WeClapp applies
        it on top of the item sums, but not on shipping lines), so the discountable part is
        scaled accordingly - ERPNext leaves Actual tax rows untouched by discounts.

        Args:
            tax_mapping (dict): WC_EN tax mapping table of the concrete migration
            negate (bool): Negate amounts (credit notes / returns)

        Returns:
            list[dict]: Mapped taxes
        """
        scale = 1.0 - self._header_adjustment_percentage() / 100.0
        en_taxes = list()
        for tax_id, (discountable, fixed) in self.taxes.items():
            tax_info = tax_mapping.get(tax_id, None)
            tax_amount = round(discountable * scale + fixed, 2)
            if negate:
                tax_amount = -tax_amount
            en_taxes.append({
                "docstatus"     : config.EN_DEFAULT_INVOICE_STATE,
                "charge_type"   : "Actual",
                "account_head"  : tax_info.tax_account,
                "description"   : tax_info.description,
                "tax_amount"    : tax_amount,
                "cost_center"   : config.EN_DEFAULT_COST_CENTER
            })
        return en_taxes

    def _create_with_link_fallback(self, doctype: ERPNextDocType, en_data: dict, link_fields: list) -> dict:
        """Creates the document; if that fails on a LinkValidationError while document-chain
        link fields (Belegkette, see setup.py) are set, retries once without them - a missing
        link target (e.g. a WeClapp quotation that was never imported) shouldn't block the
        document itself.

        Args:
            doctype (ERPNextDocType): Target DocType
            en_data (dict): Transformed document data
            link_fields (list): Names of the optional link fields to strip on failure

        Returns:
            dict: Created ERPNext document
        """
        try:
            return self._en_api.create(doctype, en_data)
        except Exception as e:
            if "LinkValidationError" in str(e) and any(en_data.get(f) for f in link_fields):
                for f in link_fields:
                    en_data.pop(f, None)
                return self._en_api.create(doctype, en_data)
            raise

    def _skip_if_exists(self, name: str) -> bool:
        """Returns True if the ERPNext document with the given name already exists.
        Makes re-runs idempotent: transactional documents keep their WeClapp-derived names
        (autoname=Prompt, see setup.py), so an existing document means it was already imported.

        Args:
            name (str): Deterministic document name

        Returns:
            bool: True if the document exists (caller should skip), False otherwise
        """
        if name and name in self._en_api.get_all_names(self.get_doctype()):
            print(f"Skipped existing {self.get_doctype()} {name}")
            return True
        return False

    def upload_weclapp_documents(self, name: str):
        """Uploads and assigns the original WeClapp documents.

        Args:
            name (str): Name of the entity to upload the documents to
        """
        id = self.wc_data.get("id", None)
        if not id:
            return
        
        # Get WeClapp document-root by invoice ID
        wc_doc_base = Path(f"{config.WC_CACHE_DOCUMENTS_BASE}{self.get_wc_doctype().value}/{id}/")

        # Check if base path exists
        if not wc_doc_base.exists():
            return
        
        # Get all files in directory, skipping ignored patterns (e.g. auto-generated
        # "Bestandsbewertung" inventory valuation exports - see config.EN_UPLOAD_IGNORE_PATTERNS)
        files = [f for f in wc_doc_base.iterdir() if f.is_file() and
                 not any(p.lower() in f.name.lower() for p in config.EN_UPLOAD_IGNORE_PATTERNS)]

        # Upload all files. Upload failures must not fail the record: the document itself is
        # already created at this point, so a re-run would skip it via _skip_if_exists - the
        # attachment would then be missing for good instead of just this once.
        for file in files:
            try:
                self._en_api.upload_file(self.get_doctype(), name, str(file))
                print(f"Uploaded file {file.name}")
            except Exception as e:
                print(f"FAILED upload {file.name} to {self.get_doctype().value} {name}: {type(e).__name__}: {e}")

    @abstractmethod
    def _transform(self) -> dict:
        """Transforms the data from WeClapp to ERPNext.

        Returns:
            dict: Transformed data
        """
        pass

    @abstractmethod
    def get_doctype(self) -> ERPNextDocType:
        """Returns the ERPNext DocType of the object.

        Returns:
            ERPNextDocTypes: ERPNext DocType
        """
        pass

    @abstractmethod
    def get_wc_doctype(self) -> WeClappDocType:
        """Returns the WeClapp DocType of the object.

        Returns:
            WeClappDocTypes: WeClapp DocType
        """
        pass

    @abstractmethod
    def validate(self) -> bool:
        """
        Validates the given data.

        Returns:
            bool: True if valid, False if not
        """
        pass