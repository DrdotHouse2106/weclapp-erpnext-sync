from .base_migration import BaseMigration
from .purchase_invoice_migration import PurchaseInvoiceMigration
from erpnext import ERPNextAPI, ERPNextDocType, ERPNextHelper
from weclapp import WeClappDocType
from datetime import datetime
import config

class PurchaseOrderMigration(BaseMigration):
    """Migration wrapper for a purchase order (Bestellung) object from WeClapp to ERPNext.
    Reuses PurchaseInvoiceMigration.WC_EN_PURCHASE_TAX_MAPPING since purchase orders use the same
    expense accounts as purchase invoices.
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
        return ERPNextDocType.PURCHASE_ORDER

    def get_wc_doctype(self) -> WeClappDocType:
        return WeClappDocType.PURCHASE_ORDER

    def validate(self) -> bool:
        """
        Validates the given data.

        Returns:
            bool: True if valid, False if not
        """
        return bool(self.wc_data.get("purchaseOrderNumber", None)) and \
            bool(self.wc_data.get("supplierNumber", None)) and \
            len(self.wc_data.get("purchaseOrderItems", [])) > 0

    def _transform(self) -> dict:
        """Transforms the data from WeClapp to ERPNext.

        Returns:
            dict: Transformed data
        """
        transformed_data = {
            "name"              : f"PO-{self.wc_data.get('purchaseOrderNumber', str())}",
            "docstatus"         : config.EN_DEFAULT_INVOICE_STATE,
            "transaction_date"  : self._map_order_date(),
            "schedule_date"     : self._map_order_date(),
            "supplier"          : self.wc_data.get("supplierNumber", str()),
            "taxes_and_charges" : config.EN_DEFAULT_PURCHASE_TAXES_AND_CHARGES,
            "items"             : self._map_items(),
            "taxes"             : self._map_taxes(PurchaseInvoiceMigration.WC_EN_PURCHASE_TAX_MAPPING),
            "apply_discount_on" : "Net Total",
            "discount_amount"   : self._map_header_discount_amount("purchaseOrderItems"),
            # Belegkette: zugehöriger Verkaufsauftrag bei Streckengeschäft (see setup.setup_link_fields)
            "wc_auftrag"        : f"SO-{self.wc_data['salesOrderNumber']}" if self.wc_data.get("salesOrderNumber") else None,
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
            en_order = self._create_with_link_fallback(ERPNextDocType.PURCHASE_ORDER, en_data, ["wc_auftrag"])

            try:
                self._post_validation(en_order)
            except Exception as e:
                print(e)

            self.upload_weclapp_documents(en_order.get("name", str()))
            return en_order
        else:
            return None

    def _post_validation(self, en_order: dict):
        """Validates the purchase order after creation (is gross amount correct?).

        Args:
            en_order (dict): Created ERPNext purchase order
        """
        en_total = en_order.get("grand_total", None)
        wc_total = self.wc_data.get("grossAmount", None)

        if en_total and wc_total:
            en_total = float(en_total)
            wc_total = float(wc_total)

            if en_total != wc_total:
                raise Exception(f"Gross amount of purchase order {en_order.get('name', str())} is not correct! (ERPNext: {en_total}, WeClapp: {wc_total})")

    def _map_items(self) -> list[dict]:
        """Maps the order items from WeClapp to ERPNext.

        Returns:
            list[dict]: Mapped items
        """
        en_items = list()
        for item in self.wc_data.get("purchaseOrderItems", list()):
            tax_info = PurchaseInvoiceMigration.WC_EN_PURCHASE_TAX_MAPPING.get(item.get("taxId", str()), None)
            en_item = {
                "docstatus"             : config.EN_DEFAULT_INVOICE_STATE,
                "item_code"             : item.get("articleNumber", None) or config.EN_FREE_TEXT_ITEM,
                "item_name"             : self._map_item_title(item),
                "description"           : self._map_item_title(item),
                "rate"                  : self._map_net_rate(item),
                "qty"                   : self._map_item_qty(item),
                "uom"                   : self._map_item_uom(item),
                "schedule_date"         : self._map_order_date(),
                "cost_center"           : config.EN_DEFAULT_COST_CENTER,
                "warehouse"             : config.EN_DEFAULT_WAREHOUSE,
                "expense_account"       : tax_info.expense_account if tax_info else None
            }
            en_items.append(en_item)
            self._add_tax(PurchaseInvoiceMigration.WC_EN_PURCHASE_TAX_MAPPING, item)

        for item in self.wc_data.get("shippingCostItems", list()):
            tax_info = PurchaseInvoiceMigration.WC_EN_PURCHASE_TAX_MAPPING.get(item.get("taxId", str()), None)
            en_item = {
                "docstatus"             : config.EN_DEFAULT_INVOICE_STATE,
                "item_code"             : item.get("articleNumber", None) or config.EN_FREE_TEXT_ITEM,
                "item_name"             : "Versandkosten",
                "description"           : "Versandkosten",
                "rate"                  : self._map_net_rate(item),
                "qty"                   : 1,
                "uom"                   : config.EN_DEFAULT_UOM,
                "schedule_date"         : self._map_order_date(),
                "cost_center"           : config.EN_DEFAULT_COST_CENTER,
                "warehouse"             : config.EN_DEFAULT_WAREHOUSE,
                "expense_account"       : tax_info.expense_account if tax_info else None
            }
            en_items.append(en_item)
            self._add_tax(PurchaseInvoiceMigration.WC_EN_PURCHASE_TAX_MAPPING, item, header_discountable=False)
        return en_items

    def _map_item_uom(self, item: dict) -> str:
        """Maps the unit of measurement of the order item.
        """
        return ERPNextHelper.get_uom_string(item.get("unitName", None))

    def _map_item_title(self, item: dict) -> str:
        """Maps the title of the order item.
        """
        title = item.get("title", None)
        if title and len(title) > 140:
            title = title[:140]
        return title if title else "(Kein Titel)"

    def _map_order_date(self) -> str:
        """Maps the order date of the purchase order.
        If order date is empty, return current date.
        """
        order_date = self.wc_data.get("orderDate", None)
        if order_date and isinstance(order_date, int) and order_date > 0:
            return ERPNextHelper.get_date_from_weclapp_ts(order_date)
        else:
            return datetime.now().strftime("%Y-%m-%d")

