from .base_migration import BaseMigration
from erpnext import ERPNextAPI, ERPNextHelper, ERPNextDocType
from weclapp import WeClappDocType

class AddressMigration(BaseMigration):
    """Migration wrapper for address objects from WeClapp to ERPNext.
    """

    def __init__(self, en_api: ERPNextAPI, wc_data: dict, wc_customer_data: dict = None, wc_custom_attribute_definitions: dict = None):
        """Initializes the migration wrapper.

        Args:
            en_api (ERPNextAPI): ERPNext-API-Object
            wc_data (dict): WeClapp-API-Object
            wc_customer_data (dict, optional): WeClapp-API-Object of the parent (customer or supplier). Defaults to None.
        """
        super().__init__(en_api, wc_data, wc_custom_attribute_definitions)
        self.wc_customer_data = wc_customer_data
        self._is_primary = self.wc_data.get("primeAddress", False)

    def get_doctype(self) -> ERPNextDocType:
        return ERPNextDocType.ADDRESS

    def get_wc_doctype(self) -> WeClappDocType:
        return WeClappDocType.CUSTOMER

    def validate(self) -> bool:
        """
        Validates the given data.

        Returns:
            bool: True if valid, False if not
        """
        return self.wc_data.get("street1", None) and \
            self.wc_data.get("city", None) and \
            self.wc_data.get("zipcode", None) and \
            self.wc_data.get("countryCode", None)

    def _transform(self) -> dict:
        """Transforms the data from WeClapp to ERPNext.

        Returns:
            dict: Transformed data
        """
        transformed_data = {
            "address_title"         : self._map_address_title(),
            "address_type"          : self._map_address_type(),
            "address_line1"         : self.wc_data.get("street1", str()),
            "address_line2"         : self.wc_data.get("street2", None),
            "city"                  : self.wc_data.get("city", str()),
            "state"                 : self.wc_data.get("state", None),
            "country"               : self._map_country(),
            "pincode"               : self.wc_data.get("zipcode", str()),
            "phone"                 : ERPNextHelper.standardize_phone_number(self.wc_data.get("phoneNumber", str())),
            "is_shipping_address"   : bool(self.wc_data.get("deliveryAddress", False)),
            "is_primary_address"    : bool(self.wc_data.get("primeAddress", False))
        }
        return transformed_data

    def _map_address_title(self) -> str:
        """
        Maps the address title with the provided customer/supplier number (if given) or the address id from WeClapp.
        """
        if self.wc_customer_data:
            number = self.wc_customer_data.get("customerNumber", None) or self.wc_customer_data.get("supplierNumber", None)
            if number:
                return number
        return str(self.wc_data.get("id", None))

    def _map_address_type(self) -> str:
        """
        Maps the address type (billing or shipping)
        """
        if self.wc_data.get("invoiceAddress", None):
            return "Billing"
        elif self.wc_data.get("deliveryAddress", None):
            return "Shipping"
        else:
            return None
        
    def _map_country(self) -> str:
        """
        Maps the country with the provided country code from WeClapp.
        """
        if self.wc_data.get("countryCode", None):
            return ERPNextHelper.get_country_string(self.wc_data["countryCode"])
        else:
            return None