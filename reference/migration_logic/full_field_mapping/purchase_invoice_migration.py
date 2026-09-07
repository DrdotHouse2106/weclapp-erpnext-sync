from .base_migration import BaseMigration
from erpnext import ERPNextAPI, ERPNextDocType, ERPNextHelper, PurchaseTaxInfo
from weclapp import WeClappDocType
from datetime import datetime
from pathlib import Path
import json
import config

class PurchaseInvoiceMigration(BaseMigration):

    # Built from the actual taxId distribution across all 7335 real purchaseInvoiceItems in the
    # WeClapp cache (weclapp/cache/tax.json), giving 100% coverage. Note the earlier version of
    # this table had a "3430" entry that never occurs anywhere in the real data - the ID actually
    # used for intra-community acquisitions is "3433"/"3434".
    # There is only one generic "Wareneingang" expense account in this ERPNext chart of accounts
    # (no split by VAT rate) - the tax accounts below are the actual input-VAT accounts per rate.
    # Reverse-charge entries (3433/3434/foreign Vorsteuer) are approximated as a single Vorsteuer
    # line - a real reverse charge needs a matching Umsatzsteuer credit line too, which this
    # simple model doesn't create.
    WC_EN_PURCHASE_TAX_MAPPING = {
        "3428"   : PurchaseTaxInfo("3200 - Wareneingang - FT", "1576 - Abziehbare Vorsteuer 19 % - FT", "DE Vorsteuer 19 %", 19.0),
        "3429"   : PurchaseTaxInfo("3200 - Wareneingang - FT", "1571 - Abziehbare Vorsteuer 7 % - FT", "DE Vorsteuer 7 %", 7.0),
        "3433"   : PurchaseTaxInfo("3200 - Wareneingang - FT", "1574 - Abziehbare Vorsteuer aus innergemeinschaftlichem Erwerb 19 % - FT", "DE Innergemeinschaftlicher Erwerb 19 %", 19.0),
        "3434"   : PurchaseTaxInfo("3200 - Wareneingang - FT", "1572 - Abziehbare Vorsteuer aus innergemeinschaftlichem Erwerb - FT", "DE Innergemeinschaftlicher Erwerb ermäßigt 7 %", 7.0),
        "3441"   : PurchaseTaxInfo("3200 - Wareneingang - FT", None, "DE Steuerfrei (EK)", 0.0),
        "3442"   : PurchaseTaxInfo("3200 - Wareneingang - FT", None, "DE Steuerfrei Drittland (EK)", 0.0),
        "878402" : PurchaseTaxInfo("3200 - Wareneingang - FT", "1572 - Abziehbare Vorsteuer aus innergemeinschaftlichem Erwerb - FT", "BE Vorsteuer 21 %", 21.0),
        "1136990": PurchaseTaxInfo("3200 - Wareneingang - FT", "1572 - Abziehbare Vorsteuer aus innergemeinschaftlichem Erwerb - FT", "NL Vorsteuer 21 %", 21.0),
        "683928" : PurchaseTaxInfo("3200 - Wareneingang - FT", "1572 - Abziehbare Vorsteuer aus innergemeinschaftlichem Erwerb - FT", "FR Vorsteuer 20 %", 20.0),
        "683941" : PurchaseTaxInfo("3200 - Wareneingang - FT", None, "FR Steuerfrei Drittland (EK)", 0.0),
    }

    def __init__(self, en_api: ERPNextAPI, wc_data: dict, wc_custom_attribute_definitions: dict):
        """Initializes the migration wrapper.

        Args:
            en_api (ERPNextAPI): ERPNext-API-Object
            wc_data (dict): WeClapp-API-Object
        """
        super().__init__(en_api, wc_data, wc_custom_attribute_definitions)
        self.taxes = {}

    def get_doctype(self) -> ERPNextDocType:
        return ERPNextDocType.PURCHASE_INVOICE

    def get_wc_doctype(self) -> WeClappDocType:
        return WeClappDocType.PURCHASE_INVOICE

    def validate(self) -> bool:
        """
        Validates the given data.
        Purchase invoices without a supplier are unverified OCR drafts in WeClapp
        (status OCR_VERIFICATION) - not real booked invoices, so they are skipped.

        Returns:
            bool: True if valid, False if not
        """
        if float(self.wc_data.get("netAmount", 0) or 0) <= 0.0:
            return False

        if not self.wc_data.get("supplierNumber", None):
            return False

        return True

    def _transform(self) -> dict:
        """Transforms the data from WeClapp to ERPNext.

        Returns:
            dict: Transformed data
        """
        return {
            "name"              : f"EK-{self.wc_data.get('internalInvoiceNumber', str())}",
            "docstatus"         : config.EN_DEFAULT_INVOICE_STATE,
            "set_posting_time"  : 1,
            "posting_date"      : self._map_invoice_date(),
            "due_date"          : self._map_due_date(),
            # Dummy 100-year template (config.EN_MIGRATION_PAYMENT_TERMS_TEMPLATE), not None -
            # sending None doesn't prevent ERPNext from auto-filling payment_terms_template from
            # Supplier.payment_terms on insert (confirmed live, no fetch_from involved, plain
            # server-side set_missing_values() logic). See invoice_migration.py/setup.py for the
            # sales-side equivalent of this bug, found live with 861 Sales Invoice failures.
            "payment_terms_template": config.EN_MIGRATION_PAYMENT_TERMS_TEMPLATE,
            "bill_no"           : self.wc_data.get("invoiceNumber", str()),
            "bill_date"         : self._map_invoice_date(),
            "supplier"          : self.wc_data.get("supplierNumber", str()),
            # Explicit instead of relying on the company's default_payable_account - that default
            # is currently misconfigured on the live FranceTec instance (points at a payroll
            # liabilities account, not a payables account); flagged separately, fix independent of it.
            "credit_to"         : config.EN_PURCHASE_PAID_TO_ACCOUNT,
            "taxes_and_charges" : config.EN_DEFAULT_PURCHASE_TAXES_AND_CHARGES,
            "items"             : self._map_items(),
            "taxes"             : self._map_taxes(self.WC_EN_PURCHASE_TAX_MAPPING, negate=self._is_credit_note())
                                  + self._map_import_sales_tax(),
            "apply_discount_on" : "Net Total",
            "discount_amount"   : self._map_header_discount_amount("purchaseInvoiceItems", negate=self._is_credit_note()),
            "is_return"         : self._is_credit_note(),
            # Belegkette: zugehörige Bestellung (see setup.setup_link_fields)
            "wc_bestellung"     : self._map_purchase_order_link(),
            # Interne Notiz (see setup.setup_internal_note_fields)
            "wc_interne_notiz"  : self._map_wc_notes() or None,
        }

    def migrate(self) -> dict:
        """Migrates a given WeClapp-Object and creates it in ERPNext.

        Returns:
            dict: Created ERPNext-Object
        """
        # Base data
        en_data = self._transform()

        if self.validate():
            if self._skip_if_exists(en_data.get("name")):
                return None
            en_invoice = self._create_with_link_fallback(ERPNextDocType.PURCHASE_INVOICE, en_data, ["wc_bestellung"])

            try:
                # After validation (is gross amount correct?)
                self._post_validation(en_invoice)
            except Exception as e:
                print(e)

            # Upload WeClapp documents
            self.upload_weclapp_documents(en_invoice.get("name", str()))

            # Payments are now migrated separately from WeClapp's real payment data (see
            # payment_entry_migration.py / main.migrate_wc_en_purchase_payments()), not as a
            # lump sum here anymore.

            return en_invoice
        else:
            return None

    def _is_credit_note(self) -> bool:
        """Checks if the purchase invoice is a credit note.

        Returns:
            bool: True if credit note, False if not
        """
        return self.wc_data.get("purchaseInvoiceType", str()) == "CREDIT_NOTE"

    # Lazy class-level lookup WeClapp purchaseOrder id -> purchaseOrderNumber, since the
    # purchase invoice's "purchaseOrders" list only carries IDs.
    _PO_NUMBER_BY_ID = None

    def _map_purchase_order_link(self) -> str:
        """Maps the first linked WeClapp purchase order to the ERPNext document name
        ("PO-<number>"). A handful of invoices reference two orders - only the first is
        linked (single Link field).
        """
        po_refs = self.wc_data.get("purchaseOrders") or []
        if not po_refs:
            return None
        if PurchaseInvoiceMigration._PO_NUMBER_BY_ID is None:
            db_path = Path(config.WC_CACHE_BASE).joinpath("purchaseOrder.json")
            with open(db_path, "r") as f:
                raw = json.load(f)["data"]
            PurchaseInvoiceMigration._PO_NUMBER_BY_ID = \
                {v["id"]: v.get("purchaseOrderNumber") for v in raw.values()}
        number = PurchaseInvoiceMigration._PO_NUMBER_BY_ID.get(po_refs[0].get("id"))
        return f"PO-{number}" if number else None

    def _map_import_sales_tax(self) -> list[dict]:
        """Maps WeClapp's importSalesTaxAmount (Einfuhrumsatzsteuer, e.g. customs on
        third-country imports) to an additional "Actual" tax row. Only a handful of purchase
        invoices carry it, but without this row their gross total is significantly off.

        Returns:
            list[dict]: Zero or one tax row
        """
        amount = float(self.wc_data.get("importSalesTaxAmount", 0) or 0)
        if not amount:
            return []
        if self._is_credit_note():
            amount = -amount
        return [{
            "docstatus"     : config.EN_DEFAULT_INVOICE_STATE,
            "charge_type"   : "Actual",
            "account_head"  : config.EN_PURCHASE_IMPORT_VAT_ACCOUNT,
            "description"   : "Einfuhrumsatzsteuer",
            "tax_amount"    : round(amount, 2),
            "cost_center"   : config.EN_DEFAULT_COST_CENTER
        }]

    def _map_items(self) -> list[dict]:
        """Maps the items from WeClapp to ERPNext.
        Includes shippingCostItems as extra line items - WeClapp's invoice-level
        netAmount/grossAmount already includes them.

        Returns:
            list[dict]: Mapped items
        """
        en_items = list()
        for item in self.wc_data.get("purchaseInvoiceItems", list()):
            tax_info = self.WC_EN_PURCHASE_TAX_MAPPING.get(item.get("taxId", str()), None)
            net_rate = self._map_net_rate(item)
            en_item = {
                "docstatus"             : config.EN_DEFAULT_INVOICE_STATE,
                "item_code"             : item.get("articleNumber", None),
                "item_name"             : self._map_item_title(item),
                "description"           : self._map_item_description(item),
                "price_list_rate"       : net_rate,
                "rate"                  : net_rate,
                "qty"                   : self._map_item_quantity(item),
                "uom"                   : self._map_item_uom(item),
                "cost_center"           : config.EN_DEFAULT_COST_CENTER,
                "expense_account"       : tax_info.expense_account if tax_info else None
            }
            en_items.append(en_item)
            self._add_tax(self.WC_EN_PURCHASE_TAX_MAPPING, item)

        for item in self.wc_data.get("shippingCostItems", list()):
            tax_info = self.WC_EN_PURCHASE_TAX_MAPPING.get(item.get("taxId", str()), None)
            en_item = {
                "docstatus"             : config.EN_DEFAULT_INVOICE_STATE,
                "item_code"             : item.get("articleNumber", None),
                "item_name"             : "Versandkosten",
                "description"           : "Versandkosten",
                "price_list_rate"       : self._map_net_rate(item),
                "rate"                  : self._map_net_rate(item),
                "qty"                   : -1 if self._is_credit_note() else 1,
                "uom"                   : config.EN_DEFAULT_UOM,
                "cost_center"           : config.EN_DEFAULT_COST_CENTER,
                "expense_account"       : tax_info.expense_account if tax_info else None
            }
            en_items.append(en_item)
            self._add_tax(self.WC_EN_PURCHASE_TAX_MAPPING, item, header_discountable=False)
        return en_items

    def _map_item_quantity(self, item: dict) -> float:
        """Maps the item quantity (zero-quantity lines become 1, see _map_item_qty).
        """
        quantity = self._map_item_qty(item)

        # Reverse quantity if credit note
        if self._is_credit_note():
            quantity = quantity * -1

        return quantity

    def _map_item_uom(self, item: dict) -> str:
        """Maps the unit of measurement of the purchase invoice item.
        """
        return ERPNextHelper.get_uom_string(item.get("unitName", None))

    def _map_item_title(self, item: dict) -> str:
        """Maps the title of the purchase invoice item.
        """
        title = item.get("title", None)
        # Limit title to 140 characters
        if title and len(title) > 140:
            title = title[:140]
        return title if title else "(Kein Titel)"

    def _map_item_description(self, item: dict) -> str:
        """Maps the purchase invoice item description.
        Returns the title if no description is given.
        """
        description = item.get("description", None)
        return description if description else self._map_item_title(item)

    def _map_invoice_date(self) -> str:
        """Maps the invoice date of the purchase invoice.
        If invoice date is empty, return current date.
        """
        inv_date = self.wc_data.get("invoiceDate", None)
        if inv_date and isinstance(inv_date, int) and inv_date > 0:
            return ERPNextHelper.get_date_from_weclapp_ts(inv_date)
        else:
            return datetime.now().strftime("%Y-%m-%d")

    def _map_due_date(self) -> str:
        """Maps the due date of the purchase invoice.
        If no due date is given - or it lies before the invoice date (rare WeClapp data
        anomaly, rejected by ERPNext) - the invoice date is used instead.
        """
        due_date = self.wc_data.get("dueDate", None)
        if due_date and isinstance(due_date, int) and due_date > 0:
            return max(ERPNextHelper.get_date_from_weclapp_ts(due_date), self._map_invoice_date())
        else:
            return self._map_invoice_date()

    def _post_validation(self, en_invoice: dict):
        """Validates the purchase invoice after creation.

        Args:
            en_invoice (dict): Created ERPNext invoice
        """
        en_total = en_invoice.get("grand_total", None)
        wc_total = self.wc_data.get("grossAmount", None)

        if en_total and wc_total:
            en_total = float(en_total)
            wc_total = float(wc_total)

            if self._is_credit_note():
                wc_total = wc_total * -1

            # Cent-exact, but tolerant of float representation noise
            if round(en_total - wc_total, 2) != 0:
                raise Exception(f"Gross amount of purchase invoice {en_invoice.get('name', str())} is not correct! (ERPNext: {en_total}, WeClapp: {wc_total})")

