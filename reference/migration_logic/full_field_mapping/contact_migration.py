from .base_migration import BaseMigration
from erpnext import ERPNextAPI, ERPNextHelper, ERPNextDocType
from weclapp import WeClappDocType

class ContactMigration(BaseMigration):
    """Migration wrapper for address objects from WeClapp to ERPNext.
    """

    # WeClapp salutation -> ERPNext Salutation doctype name. ERPNext ships a fixed default set
    # (Mr, Ms, Mx, Dr, Mrs, Madam, Miss, Master, Prof - confirmed live) - only MR/MRS occur often
    # enough in this instance's data to have an obvious match (~1145/152 occurrences across
    # customer/supplier/contact.json); NO_SALUTATION/COMPANY/FAMILY/missing have no clean
    # equivalent and are deliberately left unmapped (None) rather than guessed.
    _SALUTATION_MAP = {
        "MR": "Mr",
        "MRS": "Mrs",
    }

    def __init__(self, en_api: ERPNextAPI, wc_data: dict, wc_customer_data: dict = None, wc_custom_attribute_definitions: dict = None):
        """Initializes the contact migration.

        Args:
            en_api (ERPNextAPI): ERPNext-API-Object
            wc_data (dict): WeClapp-API-Object
            wc_customer_data (dict, optional): WeClapp-API-Object of the customer (parent). Defaults to None.
        """
        super().__init__(en_api, wc_data, wc_custom_attribute_definitions)
        self.wc_customer_data = wc_customer_data
        if self.wc_customer_data:
            self._is_primary = self.wc_customer_data.get("primaryContactId", False) == \
                self.wc_data.get("id", None)
    
    def get_doctype(self) -> ERPNextDocType:
        return ERPNextDocType.CONTACT

    def get_wc_doctype(self) -> WeClappDocType:
        return WeClappDocType.CONTACT

    def validate(self) -> bool:
        """
        Validates the given data.

        Returns:
            bool: True if valid, False if not
        """
        return self.wc_data.get("firstName", None) and \
            self.wc_data.get("lastName", None)

    def _transform(self) -> dict:
        """Transforms the data from WeClapp to ERPNext.

        Returns:
            dict: Transformed data
        """
        transformed_data = {
            "first_name"            : self.wc_data.get("firstName", str()),
            "last_name"             : self.wc_data.get("lastName", str()),
            "is_primary_contact"    : self.is_primary(),
            "status"                : "Passive",
            "salutation"            : self._SALUTATION_MAP.get(self.wc_data.get("salutation")),
            "designation"           : self.wc_data.get("title") or None,
            "wc_fax"                : self.wc_data.get("fax") or None,
            "email_ids"             : self._map_emails(),
            "phone_nos"             : self._map_phone_nos()
        }

        # Custom Attributes (Zusatzfelder, e.g. Fahrzeugdaten/eBay/Opt-Out)
        transformed_data.update(self._map_custom_attributes())

        return transformed_data
    
    def _map_emails(self) -> list:
        """Maps the email addresses from WeClapp to ERPNext. "emailHome" is a distinct secondary
        address WeClapp carries alongside the primary "email" - added as a non-primary entry,
        skipped if identical to the primary (some WeClapp records duplicate the same address into
        both fields).

        Returns:
            list: List of email addresses
        """
        emails = list()
        primary = self.wc_data.get("email", None)
        if primary:
            emails.append({
                "email_id"  : primary,
                "is_primary": True
            })
        home = self.wc_data.get("emailHome", None)
        if home and home != primary:
            emails.append({
                "email_id"  : home,
                "is_primary": False
            })
        return emails
    
    def _map_phone_nos(self) -> list:
        """Maps the phone numbers from WeClapp to ERPNext.

        Returns:
            list: List of phone numbers
        """
        phone_nos = list()

        # Office number
        phone_no = ERPNextHelper.standardize_phone_number(self.wc_data.get("phone", str()))
        if phone_no:
            phone_nos.append({
                "phone"             : phone_no,
                "is_primary_phone"  : True
            })

        # Mobile number
        mobile_no = ERPNextHelper.standardize_phone_number(self.wc_data.get("mobilePhone1", str()))
        if mobile_no:
            phone_nos.append({
                "phone"                 : mobile_no,
                "is_primary_mobile_no"  : True
            })

        return phone_nos