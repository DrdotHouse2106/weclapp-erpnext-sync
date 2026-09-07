import config
import re
from datetime import datetime

class ERPNextHelper:
    """Helper class for ERPNext API.
    """
    @staticmethod
    def get_country_string(country : str) -> str:
        """Returns the ERPnext territory by a string

        Args:
            country (str): Country string

        Returns:
            str: ERPnext territory
        """
        if not country:
            return None
        return config.EN_COUNTRY_MAP.get(country.lower(), country)

    @staticmethod
    def get_territory_string(country: str) -> str:
        """Returns the ERPNext territory for a given (already mapped) country name.
        Only "Germany" and "Rest Of The World" currently exist as Territory records in ERPNext.

        Args:
            country (str): Country string (as returned by get_country_string)

        Returns:
            str: ERPNext territory
        """
        if country == config.EN_TERRITORY_GERMANY:
            return config.EN_TERRITORY_GERMANY
        return config.EN_TERRITORY_DEFAULT

    @staticmethod
    def get_uom_string(unit_name: str) -> str:
        """Maps a WeClapp unitName to an existing ERPNext UOM name via config.EN_UOM_MAP.
        Falls back to config.EN_DEFAULT_UOM if the unit is unknown or not given.

        Args:
            unit_name (str): WeClapp unitName

        Returns:
            str: ERPNext UOM name
        """
        if not unit_name:
            return config.EN_DEFAULT_UOM
        return config.EN_UOM_MAP.get(unit_name.strip().lower(), config.EN_DEFAULT_UOM)

    @staticmethod
    def standardize_phone_number(number: str, default_country_code: str = config.EN_DEFAULT_PHONE_COUNTRY_CODE) -> str:
        """Standardizes a phone number.
        WeClapp often stores an explicit null for missing phone numbers (not just a missing key),
        so callers may pass None here even when using dict.get(key, default).

        Args:
            number (str): Phone number to standardize
            default_country_code (str, optional): Default country code (without leading +) to use if none is given. Defaults to config.EN_DEFAULT_PHONE_COUNTRY_CODE.

        Returns:
            str: Standardized phone number
        """
        if not number:
            return str()

        # Remove all non-numeric characters except the + sign
        cleaned_number = re.sub(r'\D', '', number)

        # Check if there is already a country code
        # If not, add the default one
        if cleaned_number.startswith('00'):
            cleaned_number = f"+{cleaned_number[2:]}"
        elif cleaned_number.startswith('0'):
            cleaned_number = f"+{default_country_code}{cleaned_number[1:]}"
        elif cleaned_number:
            cleaned_number = f"+{cleaned_number}"

        return cleaned_number
    
    @staticmethod
    def get_custom_fieldname(attribute_key: str) -> str:
        """Derives a valid Frappe fieldname from a WeClapp custom attribute key.
        Frappe fieldnames must start with a letter/underscore - WeClapp attribute keys
        are sometimes auto-generated IDs starting with a digit (e.g. "4437i966dkk84h9lkb").

        Args:
            attribute_key (str): WeClapp attributeKey

        Returns:
            str: Valid Frappe fieldname
        """
        key = re.sub(r'[^a-z0-9_]', '_', attribute_key.lower())
        if not key or not (key[0].isalpha() or key[0] == '_'):
            key = f"cf_{key}"
        return key

    @staticmethod
    def get_wc_warehouse_name(wc_name: str, wc_id: str) -> str:
        """Derives the ERPNext Warehouse base name (before ERPNext's automatic company-abbr
        suffix) for a WeClapp warehouse/storageLocation/storagePlace. The WeClapp id is
        appended so the name stays unique and deterministic even where WeClapp names collide
        across different parents (e.g. storage places from different locations) - this lets
        setup.setup_warehouses() (which creates the warehouses) and the Stock Entry/Delivery
        Note migrations (which only reference them) compute the identical name independently,
        without needing to persist an id->name mapping across separate script runs.

        Args:
            wc_name (str): WeClapp name (warehouse.name / storageLocation.name / storagePlace.name)
            wc_id (str): WeClapp id of the same record

        Returns:
            str: Deterministic ERPNext warehouse base name, e.g. "BR001 (3777)"
        """
        return f"{wc_name} ({wc_id})"

    # Two SKR03 accounts (bank/cash) already exist in ERPNext under the generic template label
    # instead of WeClapp's specific one - setup.setup_bank_accounts() finds them already present
    # (same account_number) and skips creating a duplicate, but renaming an existing Account's
    # label would require Frappe's dedicated document-rename API (not available in this
    # project's thin REST wrapper - a plain field update does not rename the derived `name`).
    # Functionally irrelevant: booking is keyed by account NUMBER, not by this cosmetic label.
    _EXISTING_ACCOUNT_LABELS = {
        "1200": "Bankkonto",
        "1000": "Kasse",
    }

    @staticmethod
    def get_wc_account_label(account_number: str, description: str) -> str:
        """Derives the ERPNext Account's "account_name" field value for a WeClapp bank/cash
        account - i.e. what setup.setup_bank_accounts() passes on creation.

        Args:
            account_number (str): WeClapp/SKR03 account number (ledgerAccount.accountNumber)
            description (str): WeClapp account description (bankAccount.creditInstitute /
                cashAccount.description)

        Returns:
            str: Account label, e.g. "PayPal" (or "Bankkonto"/"Kasse" for the two accounts that
                already existed in ERPNext under the generic SKR03 template label - see
                _EXISTING_ACCOUNT_LABELS)
        """
        return ERPNextHelper._EXISTING_ACCOUNT_LABELS.get(account_number, description)

    @staticmethod
    def get_wc_account_name(account_number: str, description: str) -> str:
        """Derives the full ERPNext Account name (before ERPNext's automatic company-abbr
        suffix, which it appends itself when account_number is set) for a WeClapp bank/cash
        account. Used by payment_entry_migration.py to reference the account
        setup.setup_bank_accounts() created - both compute the identical name independently
        from the same WeClapp data, without persisting an id->name mapping across script runs,
        same pattern as get_wc_warehouse_name().

        Args:
            account_number (str): WeClapp/SKR03 account number (ledgerAccount.accountNumber)
            description (str): WeClapp account description (bankAccount.creditInstitute /
                cashAccount.description)

        Returns:
            str: Deterministic ERPNext account base name, e.g. "1210 - PayPal"
        """
        return f"{account_number} - {ERPNextHelper.get_wc_account_label(account_number, description)}"

    @staticmethod
    def strip_html(html: str) -> str:
        """Converts WeClapp's rich-text HTML (as found in e.g. customer/supplier "description")
        into plain text, for target fields that render as-is instead of interpreting HTML (e.g.
        ERPNext's native Customer.customer_details/Supplier.supplier_details, both plain "Text"
        fieldtype, not "Text Editor" - raw tags would otherwise show up literally).

        Args:
            html (str): WeClapp rich-text HTML

        Returns:
            str: Plain text, or an empty string if html is falsy
        """
        if not html:
            return str()
        import html as html_module
        # WeClapp's "description" field is observed double-HTML-encoded in practice (confirmed
        # live: raw cache values contain literal strings like "&amp;Uuml;" and "&lt;br /&gt;" -
        # real markup/entities hidden behind an extra layer of escaping). Unescape repeatedly
        # until stable (bounded, to avoid looping forever on adversarial input) BEFORE handling
        # tags, so real "<br />"/"Ü" etc. are exposed first rather than left as literal text.
        text = html
        for _ in range(5):
            unescaped = html_module.unescape(text)
            if unescaped == text:
                break
            text = unescaped
        text = re.sub(r"(?i)<br\s*/?>", "\n", text)
        text = re.sub(r"(?i)</p>", "\n", text)
        text = re.sub(r"<[^>]+>", "", text)
        # Collapse runs of blank lines left behind by stripped block tags
        return re.sub(r"\n{2,}", "\n", text).strip()

    @staticmethod
    def get_date_from_weclapp_ts(timestamp: int) -> str:
        """Returns a date string from a WeClapp timestamp.

        Args:
            timestamp (int): WeClapp timestamp

        Returns:
            str: Date string
        """
        return datetime.fromtimestamp(timestamp / 1000).strftime("%Y-%m-%d")

    @staticmethod
    def get_time_from_weclapp_ts(timestamp: int) -> str:
        """Returns a time-of-day string from a WeClapp timestamp (for posting_time on documents
        that also need set_posting_time, e.g. Stock Entry).

        Args:
            timestamp (int): WeClapp timestamp

        Returns:
            str: Time string (HH:MM:SS)
        """
        return datetime.fromtimestamp(timestamp / 1000).strftime("%H:%M:%S")