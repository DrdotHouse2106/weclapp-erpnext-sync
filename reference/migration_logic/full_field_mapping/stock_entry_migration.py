import config
from .base_migration import BaseMigration
from erpnext import ERPNextAPI, ERPNextDocType, ERPNextHelper
from weclapp import WeClappDocType

class StockEntryMigration(BaseMigration):
    """Migration wrapper for a warehouse stock movement (Lagerbewegung) object from WeClapp to
    an ERPNext Stock Entry. Replays the full WeClapp stock ledger 1:1 - every movement is booked
    as a single-sided Stock Entry (Material Receipt for IN_* types, Material Issue for OUT_*
    types) against the WeClapp storage place it occurred at (see setup.setup_warehouses(), which
    creates the matching "Lager_old" Warehouse tree beforehand).

    This is deliberately the ONLY thing that moves ERPNext's stock ledger for the historical
    import - Delivery Notes (see delivery_note_migration.py) are created with update_stock=0
    precisely because warehouseStockMovement already contains the exact same goods-out events
    (OUT_SALES_ORDER, OUT_SHIPMENT, ...) that shipments represent; booking both would double the
    stock deduction.
    """

    def __init__(self, en_api: ERPNextAPI, wc_data: dict, wc_custom_attribute_definitions: dict,
                 wc_articles: dict = None, wc_storage_places: dict = None):
        """Initializes the migration wrapper.

        Args:
            en_api (ERPNextAPI): ERPNext-API-Object
            wc_data (dict): WeClapp-API-Object (a single warehouseStockMovement)
            wc_custom_attribute_definitions (dict): WeClapp custom attribute definitions
            wc_articles (dict, optional): WeClapp articles keyed by id (for articleId -> articleNumber)
            wc_storage_places (dict, optional): WeClapp storage places keyed by id
        """
        super().__init__(en_api, wc_data, wc_custom_attribute_definitions)
        self.wc_articles = wc_articles or {}
        self.wc_storage_places = wc_storage_places or {}

    def get_doctype(self) -> ERPNextDocType:
        return ERPNextDocType.STOCK_ENTRY

    def get_wc_doctype(self) -> WeClappDocType:
        return WeClappDocType.WAREHOUSE_STOCK_MOVEMENT

    def validate(self) -> bool:
        """
        Validates the given data.
        Returns: True if valid, False if not
        """
        if not (self.wc_data.get("id") and self.wc_data.get("articleId") and
                self.wc_data.get("storagePlaceId") and self.wc_data.get("quantity") is not None):
            return False
        # Both sides must resolve to something bookable in ERPNext (item_code / warehouse)
        return bool(self._get_item_code()) and bool(self._get_warehouse_name())

    def _get_item_code(self) -> str:
        """Resolves the WeClapp articleId to the ERPNext item_code (articleNumber)."""
        article = self.wc_articles.get(self.wc_data.get("articleId"))
        return article.get("articleNumber") if article else None

    def _get_warehouse_name(self) -> str:
        """Resolves the WeClapp storagePlaceId to the full ERPNext Warehouse name created by
        setup.setup_warehouses() (see ERPNextHelper.get_wc_warehouse_name).
        """
        place = self.wc_storage_places.get(self.wc_data.get("storagePlaceId"))
        if not place:
            return None
        base_name = ERPNextHelper.get_wc_warehouse_name(place["name"], place["id"])
        return f"{base_name} - {config.EN_COMPANY_ABBR}"

    def _is_receipt(self) -> bool:
        """True for incoming movements (IN_*), False for outgoing (OUT_*)."""
        return str(self.wc_data.get("stockMovementType", "")).startswith("IN")

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
        return self._en_api.create(ERPNextDocType.STOCK_ENTRY, en_data)

    def _transform(self) -> dict:
        """Transforms the data from WeClapp to ERPNext.

        Returns:
            dict: Transformed data
        """
        article = self.wc_articles.get(self.wc_data.get("articleId")) or {}
        is_receipt = self._is_receipt()
        posting_ts = self.wc_data.get("postingDate")
        # WeClapp signs quantity negative for every OUT_* type and positive for every IN_* type -
        # ERPNext Stock Entry wants a plain positive magnitude, direction is already encoded via
        # s_warehouse/t_warehouse below
        qty = abs(float(self.wc_data.get("quantity", 0) or 0))
        warehouse = self._get_warehouse_name()

        item = {
            "item_code": self._get_item_code(),
            "qty": qty,
            "uom": ERPNextHelper.get_uom_string(article.get("unitName")),
        }
        if is_receipt:
            item["t_warehouse"] = warehouse
            valuation_price = self.wc_data.get("valuationPrice")
            if valuation_price is not None:
                item["basic_rate"] = float(valuation_price)
        else:
            item["s_warehouse"] = warehouse

        return {
            "name": f"LB-{self.wc_data['id']}",
            "docstatus": config.EN_DEFAULT_INVOICE_STATE,
            "company": config.EN_COMPANY,
            "stock_entry_type": "Material Receipt" if is_receipt else "Material Issue",
            "set_posting_time": 1,
            "posting_date": ERPNextHelper.get_date_from_weclapp_ts(posting_ts),
            "posting_time": ERPNextHelper.get_time_from_weclapp_ts(posting_ts),
            "remarks": self._map_remarks(),
            "items": [item],
        }

    def _map_remarks(self) -> str:
        """Builds a traceability remark from the original WeClapp movement."""
        parts = [
            f"WeClapp Lagerbewegung {self.wc_data.get('movementNumber')}",
            f"({self.wc_data.get('stockMovementType')})",
        ]
        note = self.wc_data.get("movementNote")
        if note:
            parts.append(f"- {note}")
        return " ".join(parts)
