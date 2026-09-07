import config
from .base_migration import BaseMigration
from erpnext import ERPNextAPI, ERPNextDocType
from weclapp import WeClappDocType

class ItemPriceMigration(BaseMigration):
    """Migration wrapper for article price objects from WeClapp to ERPNext.
    """

    def __init__(self, en_api: ERPNextAPI, wc_data: dict, en_item_data: dict = None, wc_custom_attribute_definitions: dict = None):
        """Initializes the item price migration.

        Args:
            en_api (ERPNextAPI): ERPNext-API-Object
            wc_data (dict): WeClapp-API-Object (a single entry of an article's articlePrices)
            en_item_data (dict, optional): ERPNext-API-Object of the item (parent). Defaults to None.
        """
        super().__init__(en_api, wc_data, wc_custom_attribute_definitions)
        self.en_item_data = en_item_data

    def get_doctype(self) -> ERPNextDocType:
        return ERPNextDocType.ITEM_PRICE

    def get_wc_doctype(self) -> WeClappDocType:
        return WeClappDocType.ARTICLE_PRICE

    def validate(self) -> bool:
        """
        Validates the given data.

        Returns:
            bool: True if valid, False if not
        """
        return float(self.wc_data.get("price", 0) or 0) > 0 and \
            self.en_item_data and self.en_item_data.get("item_code", None)

    def _transform(self) -> dict:
        """Transforms the data from WeClapp to ERPNext.

        Returns:
            dict: Transformed data
        """
        transformed_data = {
            "item_code"        : self.en_item_data.get("item_code", None),
            "price_list"       : config.EN_DEFAULT_PRICE_LIST,
            "price_list_rate"  : float(self.wc_data.get("price", 0)),
            "currency"         : self.wc_data.get("currencyName") or config.EN_DEFAULT_CURRENCY
        }
        return transformed_data
