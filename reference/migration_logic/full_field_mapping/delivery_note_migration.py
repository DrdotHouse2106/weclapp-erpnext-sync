import config
from .base_migration import BaseMigration
from erpnext import ERPNextAPI, ERPNextDocType, ERPNextHelper
from weclapp import WeClappDocType

class DeliveryNoteMigration(BaseMigration):
    """Migration wrapper for a shipment (Lieferung) object from WeClapp to an ERPNext Delivery
    Note. Created as Draft (docstatus=0) deliberately - it's a pure delivery/tracking record
    here, not the source of truth for the stock ledger. warehouseStockMovement already contains
    the exact same goods-out events (OUT_SALES_ORDER, OUT_SHIPMENT, ...) that shipments represent
    (see stock_entry_migration.py), so letting the Delivery Note also move stock would double
    the deduction.

    NOTE: an earlier version submitted this doctype directly with "update_stock": 0 in the
    payload, assuming that suppresses the stock ledger update like it does on Sales Invoice.
    It doesn't - "update_stock" isn't even a real Delivery Note field (confirmed live: the
    ERPNext API rejects it outright as "Field not permitted in query"). A submitted Delivery
    Note ALWAYS posts to the stock ledger on its own, unconditionally - there is no supported
    way to submit one without moving stock. Every previously submitted Delivery Note from that
    version double-deducted stock (once via the Stock Entry replay, once via the Delivery Note
    itself) - see CLAUDE.md for the live cleanup status. Draft avoids the on_submit hook
    entirely, which is the only way to keep this purely informational as intended.
    """

    def __init__(self, en_api: ERPNextAPI, wc_data: dict, wc_custom_attribute_definitions: dict,
                 wc_storage_places: dict = None):
        """Initializes the migration wrapper.

        Args:
            en_api (ERPNextAPI): ERPNext-API-Object
            wc_data (dict): WeClapp-API-Object (a single shipment)
            wc_custom_attribute_definitions (dict): WeClapp custom attribute definitions
            wc_storage_places (dict, optional): WeClapp storage places keyed by id
        """
        super().__init__(en_api, wc_data, wc_custom_attribute_definitions)
        self.wc_storage_places = wc_storage_places or {}

    def get_doctype(self) -> ERPNextDocType:
        return ERPNextDocType.DELIVERY_NOTE

    def get_wc_doctype(self) -> WeClappDocType:
        return WeClappDocType.SHIPMENT

    def validate(self) -> bool:
        """
        Validates the given data.
        Returns: True if valid, False if not
        """
        # Only actually shipped deliveries represent a real goods movement - CANCELLED/NEW/
        # DELIVERY_NOTE_PRINTED shipments never left the warehouse
        return bool(self.wc_data.get("shipmentNumber")) and \
            bool(self.wc_data.get("recipientCustomerNumber")) and \
            self.wc_data.get("status") == "SHIPPED" and \
            len(self.wc_data.get("shipmentItems", [])) > 0

    def migrate(self) -> dict:
        """Migrates a given WeClapp-Object and creates it in ERPNext.

        Returns:
            dict: Created ERPNext-Object, or None if skipped
        """
        if not self.validate():
            return None
        en_data = self._transform()
        if self._skip_if_exists(en_data.get("name")):
            return None
        en_note = self._create_with_link_fallback(ERPNextDocType.DELIVERY_NOTE, en_data, ["wc_auftrag"])
        self.upload_weclapp_documents(en_note.get("name", str()))
        return en_note

    def _transform(self) -> dict:
        """Transforms the data from WeClapp to ERPNext.

        Returns:
            dict: Transformed data
        """
        transformed_data = {
            "name"                     : f"LS-{self.wc_data['shipmentNumber']}",
            # Always Draft, independent of config.EN_DEFAULT_INVOICE_STATE - see class docstring:
            # a submitted Delivery Note unconditionally moves stock, which would double-count
            # against the Stock Entry replay that already represents this exact movement.
            "docstatus"                : 0,
            "set_posting_time"         : 1,
            "company"                  : config.EN_COMPANY,
            "customer"                 : self.wc_data.get("recipientCustomerNumber"),
            "posting_date"             : self._map_posting_date(),
            "items"                    : self._map_items(),
            # Belegkette: zugehöriger Auftrag (see setup.setup_link_fields) - optional,
            # ~44 shipments have no linked Sales Order
            "wc_auftrag"               : f"SO-{self.wc_data['salesOrderNumber']}" if self.wc_data.get("salesOrderNumber") else None,
            # Versanddaten (see setup.setup_shipment_tracking_fields)
            "wc_tracking_nummer"       : self.wc_data.get("packageTrackingNumber") or None,
            "wc_versanddienstleister"  : self.wc_data.get("shippingCarrierName") or None,
            # Interne Notiz (see setup.setup_internal_note_fields)
            "wc_interne_notiz"         : self._map_wc_notes() or None,
        }

        # Custom Attributes (Zusatzfelder) - e.g. "Kundenkommentar"
        transformed_data.update(self._map_custom_attributes())

        return transformed_data

    def _map_posting_date(self) -> str:
        """Maps the shipping date, falling back to the shipment's creation date if missing."""
        ts = self.wc_data.get("shippingDate") or self.wc_data.get("createdDate")
        return ERPNextHelper.get_date_from_weclapp_ts(ts)

    def _map_items(self) -> list[dict]:
        """Maps the shipment items from WeClapp to ERPNext. rate/price_list_rate are explicitly
        pinned to 0 - the financial side is already covered by the migrated Sales Invoice; this
        is a delivery record, not a billing document. Both fields are needed: ERPNext re-derives
        "rate" from "price_list_rate" (auto-fetched from the Item's own Price List) during
        validate() even when "rate" was already sent explicitly - confirmed live, an explicit
        "rate": 0 alone was NOT enough to stop this. For a handful of generic discount/rebate
        pseudo-articles that default price list rate is negative, which pushed the whole
        document's base_grand_total below 0 and got rejected outright (confirmed live, ~11
        cases, e.g. item 920011).
        """
        en_items = []
        for item in self.wc_data.get("shipmentItems", []):
            en_items.append({
                "item_code"        : item.get("articleNumber") or config.EN_FREE_TEXT_ITEM,
                "item_name"        : self._map_item_title(item),
                "description"      : self._map_item_title(item),
                "qty"              : float(item.get("quantity", 0) or 0) or 1.0,
                "rate"             : 0,
                "price_list_rate"  : 0,
                "uom"              : ERPNextHelper.get_uom_string(item.get("unitName")),
                "warehouse"        : self._map_item_warehouse(item),
            })
        return en_items

    def _map_item_title(self, item: dict) -> str:
        """Maps the title of the shipment item."""
        title = item.get("title", None)
        if title and len(title) > 140:
            title = title[:140]
        return title if title else "(Kein Titel)"

    def _map_item_warehouse(self, item: dict) -> str:
        """Resolves the storage place of the item's first pick to the full ERPNext Warehouse
        name created by setup.setup_warehouses() (informational only, since update_stock=0
        doesn't require it).
        """
        picks = item.get("picks") or []
        if not picks:
            return None
        place = self.wc_storage_places.get(picks[0].get("storagePlaceId"))
        if not place:
            return None
        base_name = ERPNextHelper.get_wc_warehouse_name(place["name"], place["id"])
        return f"{base_name} - {config.EN_COMPANY_ABBR}"
