from .base_migration import BaseMigration
from erpnext import ERPNextAPI, ERPNextDocType, ERPNextHelper, TaxInfo
from weclapp import WeClappDocType
from datetime import datetime
import config

class InvoiceMigration(BaseMigration):

    # Built from the actual taxId distribution across all 13930 real salesInvoiceItems in the
    # WeClapp cache (weclapp/cache/tax.json), giving 100% coverage - the previous table's IDs
    # ("2691", "2699", "2680", "179484") never occurred anywhere in the real data at all.
    # DE 19%/7% (IDs 3381/3382, ~94% of all line items) use real ERPNext income/tax accounts.
    # All non-German EU VAT (AT/IT/NL/LU/FR/GR/DK/BE/HU/PL/ES/PT/IE/CZ/SE/FI/HR, ~2% combined)
    # is booked to the generic income account plus the dedicated OSS VAT liability account
    # (created by setup.py) - tax amounts are taken 1:1 from WeClapp (charge_type "Actual"),
    # so no per-country rate math is needed and totals match exactly.
    OSS_ACCOUNT = "1767 - Umsatzsteuer OSS (EU-Ausland) - FT"

    WC_EN_TAX_MAPPPING = {
        "3381"  : TaxInfo("8400 - Erlöse USt. 19 % - FT", "1776 - Umsatzsteuer 19 % - FT", "DE Umsatzsteuer 19 %", 19.0),
        "3382"  : TaxInfo("8300 - Erlöse USt. 7 % - FT", "1771 - Umsatzsteuer 7 % - FT", "DE Umsatzsteuer 7 %", 7.0),
        "3385"  : TaxInfo("8200 - Erlöse - FT", None, "DE Steuerfrei (VK)", 0.0),
        "3386"  : TaxInfo("8200 - Erlöse - FT", None, "DE Steuerfreie EG-Warenlieferung (VK)", 0.0),
        "3387"  : TaxInfo("8200 - Erlöse - FT", None, "DE Steuerfrei Drittland (VK)", 0.0),
        # Non-German EU VAT - generic income account + OSS VAT liability account (see note above)
        "708418": TaxInfo("8200 - Erlöse - FT", OSS_ACCOUNT, "AT Umsatzsteuer 20 %", 20.0),
        "708419": TaxInfo("8200 - Erlöse - FT", OSS_ACCOUNT, "AT Umsatzsteuer ermäßigt 10 %", 10.0),
        "1407275": TaxInfo("8200 - Erlöse - FT", OSS_ACCOUNT, "IT IVA 22 %", 22.0),
        "708190": TaxInfo("8200 - Erlöse - FT", OSS_ACCOUNT, "NL Umsatzsteuer 21 %", 21.0),
        "708135": TaxInfo("8200 - Erlöse - FT", OSS_ACCOUNT, "LU Umsatzsteuer 17 %", 17.0),
        "708139": TaxInfo("8200 - Erlöse - FT", OSS_ACCOUNT, "LU Umsatzsteuer ermäßigt 8 %", 8.0),
        "707998": TaxInfo("8200 - Erlöse - FT", OSS_ACCOUNT, "FR Umsatzsteuer 20 %", 20.0),
        "707999": TaxInfo("8200 - Erlöse - FT", OSS_ACCOUNT, "FR Umsatzsteuer ermäßigt 5.5 %", 5.5),
        "708018": TaxInfo("8200 - Erlöse - FT", OSS_ACCOUNT, "GR Umsatzsteuer 24 %", 24.0),
        "707941": TaxInfo("8200 - Erlöse - FT", OSS_ACCOUNT, "DK Umsatzsteuer 25 %", 25.0),
        "707904": TaxInfo("8200 - Erlöse - FT", OSS_ACCOUNT, "BE Umsatzsteuer 21 %", 21.0),
        "708380": TaxInfo("8200 - Erlöse - FT", OSS_ACCOUNT, "HU Umsatzsteuer 27 %", 27.0),
        "708226": TaxInfo("8200 - Erlöse - FT", OSS_ACCOUNT, "PL Umsatzsteuer 23 %", 23.0),
        "708338": TaxInfo("8200 - Erlöse - FT", OSS_ACCOUNT, "ES Umsatzsteuer 21 %", 21.0),
        "708245": TaxInfo("8200 - Erlöse - FT", OSS_ACCOUNT, "PT Umsatzsteuer 23 %", 23.0),
        "708037": TaxInfo("8200 - Erlöse - FT", OSS_ACCOUNT, "IE Umsatzsteuer 23 %", 23.0),
        "708357": TaxInfo("8200 - Erlöse - FT", OSS_ACCOUNT, "CZ Umsatzsteuer 21 %", 21.0),
        "708283": TaxInfo("8200 - Erlöse - FT", OSS_ACCOUNT, "SE Umsatzsteuer 25 %", 25.0),
        "815241": TaxInfo("8200 - Erlöse - FT", OSS_ACCOUNT, "FI Umsatzsteuer 25.5 %", 25.5),
        "708078": TaxInfo("8200 - Erlöse - FT", OSS_ACCOUNT, "HR Umsatzsteuer 25 %", 25.0),
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
        return ERPNextDocType.SALES_INVOICE
    
    def get_wc_doctype(self) -> WeClappDocType:
        return WeClappDocType.SALES_INVOICE
    
    def validate(self) -> bool:
        """
        Validates the given data.

        Returns:
            bool: True if valid, False if not
        """
        if float(self.wc_data.get("netAmount", 0)) <= 0.0:
            return False
        
        return True

    def _transform(self) -> dict:
        """Transforms the data from WeClapp to ERPNext.

        Returns:
            dict: Transformed data
        """
        return {
            "name"              : f"RE-{self.wc_data.get('invoiceNumber', str())}",
            "docstatus"         : config.EN_DEFAULT_INVOICE_STATE,
            "set_posting_time"  : 1,
            "posting_date"      : self._map_invoice_date(),
            "due_date"          : self._map_due_date(),
            # Dummy 100-year template (config.EN_MIGRATION_PAYMENT_TERMS_TEMPLATE), not None -
            # sending None doesn't prevent ERPNext from auto-filling payment_terms_template from
            # Customer.payment_terms on insert (confirmed live, no fetch_from involved, plain
            # server-side set_missing_values() logic), which then rejects our explicit due_date
            # (WeClapp's real due date) whenever it doesn't match that template's credit_days -
            # "Das Fälligkeitsdatum darf nicht nach ... liegen". See setup.py for details. The
            # per-invoice payment_schedule below is the actual source of truth for the due date.
            "payment_terms_template": config.EN_MIGRATION_PAYMENT_TERMS_TEMPLATE,
            "customer"          : self.wc_data.get("customerNumber", str()),
            "title"             : self.wc_data.get("commission", str()),
            "payment_schedule"  : self._map_payment_schedule() if not self._is_credit_note() else None,
            # Explicit instead of relying on the company's default_receivable_account, so this
            # doesn't silently break if that default is ever changed.
            "debit_to"          : config.EN_INVOICE_PAID_FROM_ACCOUNT,
            "taxes_and_charges" : config.EN_DEFAULT_TAXES_AND_CHARGES,
            "items"             : self._map_items(),
            "taxes"             : self._map_taxes(self.WC_EN_TAX_MAPPPING, negate=self._is_credit_note()),
            "apply_discount_on" : "Net Total",
            "discount_amount"   : self._map_header_discount_amount("salesInvoiceItems", negate=self._is_credit_note()),
            "is_return"         : self._is_credit_note(),
            # Belegkette: zugehöriger Auftrag (see setup.setup_link_fields)
            "wc_auftrag"        : f"SO-{self.wc_data['salesOrderNumber']}" if self.wc_data.get("salesOrderNumber") else None,
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

        # Create customer in ERPNext (if not anonymous customer)
        if self.validate():
            if self._skip_if_exists(en_data.get("name")):
                return None
            en_invoice = self._create_with_link_fallback(ERPNextDocType.SALES_INVOICE, en_data, ["wc_auftrag"])

            try:
                # After validation (is gross amount correct?)
                self._post_validation(en_invoice)
            except Exception as e:
                print(e)

            # Upload WeClapp documents
            self.upload_weclapp_documents(en_invoice.get("name", str()))

            # Payments are now migrated separately from WeClapp's real payment data (see
            # payment_entry_migration.py / main.migrate_wc_en_sales_payments()), not as a
            # lump sum here anymore.

            return en_invoice
        else:
            return None
        
    def _is_credit_note(self) -> bool:
        """Checks if the invoice is a credit note.

        Returns:
            bool: True if credit note, False if not
        """
        return self.wc_data.get("salesInvoiceType", str()) == "CREDIT_NOTE"

    def _map_payment_schedule(self) -> list[dict]:
        """Maps the payment schedule from WeClapp to ERPNext.
        NOTE: no "payment_term" link is set here - the Payment Term master is empty in ERPNext,
        so referencing a name would fail; due_date/invoice_portion are enough for ERPNext to compute
        the schedule without a named term.

        Returns:
            list[dict]: Mapped payment schedule
        """
        return [{
                "docstatus"         : config.EN_DEFAULT_INVOICE_STATE,
                "due_date"          : self._map_due_date(),
                "invoice_portion"   : 100.0
        }]

    def _map_items(self) -> list[dict]:
        """Maps the items from WeClapp to ERPNext.
        Includes shippingCostItems (present on ~63% of invoices) as extra line items -
        WeClapp's invoice-level netAmount/grossAmount already includes them.

        Returns:
            list[dict]: Mapped items
        """
        en_items = list()
        for item in self.wc_data.get("salesInvoiceItems", list()):
            tax_info = self.WC_EN_TAX_MAPPPING.get(item.get("taxId", str()), None)
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
                "income_account"        : tax_info.income_account if tax_info else None
            }
            en_items.append(en_item)
            self._add_tax(self.WC_EN_TAX_MAPPPING, item)

        for item in self.wc_data.get("shippingCostItems", list()):
            tax_info = self.WC_EN_TAX_MAPPPING.get(item.get("taxId", str()), None)
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
                "income_account"        : tax_info.income_account if tax_info else None
            }
            en_items.append(en_item)
            self._add_tax(self.WC_EN_TAX_MAPPPING, item, header_discountable=False)
        return en_items

    def _map_item_quantity(self, item: dict) -> float:
        """Maps the item quantity (zero-quantity lines become 1, see _map_item_qty).
        """
        quantity = self._map_item_qty(item)

        # Reverse Quantity if credit note
        if self._is_credit_note():
            quantity = quantity * -1

        return quantity

    def _map_item_uom(self, item: dict) -> str:
        """Maps the unit of measurement of the invoice item.
        """
        return ERPNextHelper.get_uom_string(item.get("unitName", None))

    def _map_item_title(self, item: dict) -> str:
        """Maps the title of the invoice.
        """
        title = item.get("title", None)
        # Limit title to 140 characters
        if title and len(title) > 140:
            title = title[:140]
        return title if title else "(Kein Titel)"
    
    def _map_item_description(self, item: dict) -> str:
        """Maps the invoice description.
        Returns the title if no description is given.
        """
        description = item.get("description", None)
        return description if description else self._map_item_title(item)

    def _map_invoice_date(self) -> str:
        """Maps the invoice date of the invoice.
        If invoice date is empty, return current date.
        """
        inv_date = self.wc_data.get("invoiceDate", None)
        if inv_date and isinstance(inv_date, int) and inv_date > 0:
            return ERPNextHelper.get_date_from_weclapp_ts(inv_date)
        else:
            return datetime.now().strftime("%Y-%m-%d")

    def _map_due_date(self) -> str:
        """Maps the due date of the invoice.
        If no due date is given - or it lies before the invoice date (rare WeClapp data
        anomaly, rejected by ERPNext) - the invoice date is used instead.
        """
        due_date = self.wc_data.get("dueDate", None)
        if due_date and isinstance(due_date, int) and due_date > 0:
            return max(ERPNextHelper.get_date_from_weclapp_ts(due_date), self._map_invoice_date())
        else:
            return self._map_invoice_date()

    def _post_validation(self, en_invoice: dict):
        """Validates the invoice after creation.

        Args:
            en_invoice (dict): Created ERPNext invoice
        """
        # Check if gross amount is correct
        en_total = en_invoice.get("grand_total", None)
        wc_total = self.wc_data.get("grossAmount", None)

        if en_total and wc_total:
            en_total = float(en_total)
            wc_total = float(wc_total)

            # If credit note, reverse gross amount
            if self._is_credit_note():
                wc_total = wc_total * -1
            
            # Cent-exact, but tolerant of float representation noise (749.7000000001 == 749.70)
            if round(en_total - wc_total, 2) != 0:
                raise Exception(f"Gross amount of invoice {en_invoice.get('name', str())} is not correct! (ERPNext: {en_total}, WeClapp: {wc_total})")

