from .base_migration import BaseMigration
from .invoice_migration import InvoiceMigration
from erpnext import ERPNextAPI, ERPNextDocType, ERPNextHelper
from weclapp import WeClappDocType
from datetime import datetime
import config

class QuotationMigration(BaseMigration):
    """Migration wrapper for a quotation (Angebot) object from WeClapp to ERPNext.
    Reuses InvoiceMigration.WC_EN_TAX_MAPPPING since quotations use the same income accounts as sales invoices.
    """

    def __init__(self, en_api: ERPNextAPI, wc_data: dict, wc_custom_attribute_definitions: dict):
        """Initializes the migration wrapper.

        Args:
            en_api (ERPNextAPI): ERPNext-API-Object
            wc_data (dict): WeClapp-API-Object
        """
        super().__init__(en_api, wc_data, wc_custom_attribute_definitions)
        self.taxes = {}

    def get_doctype(self) -> ERPNextDocType:
        return ERPNextDocType.QUOTATION

    def get_wc_doctype(self) -> WeClappDocType:
        return WeClappDocType.QUOTATION

    def validate(self) -> bool:
        """
        Validates the given data.

        Returns:
            bool: True if valid, False if not
        """
        return bool(self.wc_data.get("quotationNumber", None)) and \
            bool(self.wc_data.get("customerNumber", None)) and \
            len(self.wc_data.get("quotationItems", [])) > 0

    def _transform(self) -> dict:
        """Transforms the data from WeClapp to ERPNext.

        Returns:
            dict: Transformed data
        """
        transformed_data = {
            "name"              : f"AN-{self.wc_data.get('quotationNumber', str())}",
            "docstatus"         : config.EN_DEFAULT_INVOICE_STATE,
            "quotation_to"      : "Customer",
            "party_name"        : self.wc_data.get("customerNumber", str()),
            "transaction_date"  : self._map_quotation_date(),
            "valid_till"        : self._map_valid_till(),
            "taxes_and_charges" : config.EN_DEFAULT_TAXES_AND_CHARGES,
            "items"             : self._map_items(),
            "taxes"             : self._map_taxes(InvoiceMigration.WC_EN_TAX_MAPPPING),
            "apply_discount_on" : "Net Total",
            "discount_amount"   : self._map_header_discount_amount("quotationItems"),
            # Interne Notiz (see setup.setup_internal_note_fields)
            "wc_interne_notiz"  : self._map_wc_notes() or None,
        }

        # Custom Attributes (Zusatzfelder)
        transformed_data.update(self._map_custom_attributes())

        return transformed_data

    def migrate(self) -> dict:
        """Migrates a given WeClapp-Object and creates it in ERPNext.

        Returns:
            dict: Created ERPNext-Object
        """
        en_data = self._transform()

        if self.validate():
            if self._skip_if_exists(en_data.get("name")):
                return None
            self._ensure_customer_exists()
            en_quotation = self._en_api.create(ERPNextDocType.QUOTATION, en_data)

            try:
                self._post_validation(en_quotation)
            except Exception as e:
                print(e)

            self.upload_weclapp_documents(en_quotation.get("name", str()))
            return en_quotation
        else:
            return None

    def _ensure_customer_exists(self) -> None:
        """Creates a minimal customer record if the referenced customer number doesn't exist
        in ERPNext. A handful of old quotations reference parties that were deleted in WeClapp
        (present in no cache file at all) - without this, those quotations fail with a
        LinkValidationError. Name/company are taken from the quotation's own record address.
        """
        number = self.wc_data.get("customerNumber", str())
        if not number or self._en_api.get(ERPNextDocType.CUSTOMER, number):
            return

        record_address = self.wc_data.get("recordAddress", {}) or {}
        customer_name = record_address.get("company") or \
            f"{record_address.get('firstName') or ''} {record_address.get('lastName') or ''}".strip() or number
        self._en_api.create(ERPNextDocType.CUSTOMER, {
            "name"           : number,
            "customer_name"  : customer_name,
            "customer_group" : config.EN_CUSTOMER_GROUP_INDIVIDUAL,
            "customer_type"  : "Company" if record_address.get("company") else "Individual",
            "territory"      : config.EN_TERRITORY_DEFAULT
        })
        print(f"Created minimal customer {number} ('{customer_name}') for quotation with deleted WeClapp party")

    def _post_validation(self, en_quotation: dict):
        """Validates the quotation after creation (is gross amount correct?).

        Args:
            en_quotation (dict): Created ERPNext quotation
        """
        en_total = en_quotation.get("grand_total", None)
        wc_total = self.wc_data.get("grossAmount", None)

        if en_total and wc_total:
            en_total = float(en_total)
            wc_total = float(wc_total)

            # Cent-exact, but tolerant of float representation noise
            if round(en_total - wc_total, 2) != 0:
                raise Exception(f"Gross amount of quotation {en_quotation.get('name', str())} is not correct! (ERPNext: {en_total}, WeClapp: {wc_total})")

    def _map_items(self) -> list[dict]:
        """Maps the quotation items from WeClapp to ERPNext.
        Includes shippingCostItems as extra line items.

        Returns:
            list[dict]: Mapped items
        """
        en_items = list()
        for item in self.wc_data.get("quotationItems", list()):
            tax_info = InvoiceMigration.WC_EN_TAX_MAPPPING.get(item.get("taxId", str()), None)
            en_item = {
                "docstatus"             : config.EN_DEFAULT_INVOICE_STATE,
                "item_code"             : item.get("articleNumber", None) or config.EN_FREE_TEXT_ITEM,
                "item_name"             : self._map_item_title(item),
                "description"           : self._map_item_title(item),
                "rate"                  : self._map_net_rate(item),
                "qty"                   : self._map_item_qty(item),
                "uom"                   : self._map_item_uom(item),
                "cost_center"           : config.EN_DEFAULT_COST_CENTER,
                "income_account"        : tax_info.income_account if tax_info else None
            }
            en_items.append(en_item)
            self._add_tax(InvoiceMigration.WC_EN_TAX_MAPPPING, item)

        for item in self.wc_data.get("shippingCostItems", list()):
            tax_info = InvoiceMigration.WC_EN_TAX_MAPPPING.get(item.get("taxId", str()), None)
            en_item = {
                "docstatus"             : config.EN_DEFAULT_INVOICE_STATE,
                "item_code"             : item.get("articleNumber", None) or config.EN_FREE_TEXT_ITEM,
                "item_name"             : "Versandkosten",
                "description"           : "Versandkosten",
                "rate"                  : self._map_net_rate(item),
                "qty"                   : 1,
                "uom"                   : config.EN_DEFAULT_UOM,
                "cost_center"           : config.EN_DEFAULT_COST_CENTER,
                "income_account"        : tax_info.income_account if tax_info else None
            }
            en_items.append(en_item)
            self._add_tax(InvoiceMigration.WC_EN_TAX_MAPPPING, item, header_discountable=False)
        return en_items

    def _map_item_uom(self, item: dict) -> str:
        """Maps the unit of measurement of the quotation item.
        """
        return ERPNextHelper.get_uom_string(item.get("unitName", None))

    def _map_item_title(self, item: dict) -> str:
        """Maps the title of the quotation item.
        """
        title = item.get("title", None)
        if title and len(title) > 140:
            title = title[:140]
        return title if title else "(Kein Titel)"

    def _map_quotation_date(self) -> str:
        """Maps the quotation date.
        If empty, returns the current date.
        """
        quot_date = self.wc_data.get("quotationDate", None)
        if quot_date and isinstance(quot_date, int) and quot_date > 0:
            return ERPNextHelper.get_date_from_weclapp_ts(quot_date)
        else:
            return datetime.now().strftime("%Y-%m-%d")

    def _map_valid_till(self) -> str:
        """Maps the validity end date of the quotation.
        If empty, returns the quotation date.
        """
        valid_to = self.wc_data.get("validTo", None)
        if valid_to and isinstance(valid_to, int) and valid_to > 0:
            return ERPNextHelper.get_date_from_weclapp_ts(valid_to)
        else:
            return self._map_quotation_date()
