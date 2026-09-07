import config
from .base_migration import BaseMigration
from .customer_migration import CustomerMigration
from .supplier_migration import SupplierMigration
from .address_migration import AddressMigration
from .invoice_migration import InvoiceMigration
from .purchase_invoice_migration import PurchaseInvoiceMigration
from .sales_order_migration import SalesOrderMigration
from .purchase_order_migration import PurchaseOrderMigration
from .quotation_migration import QuotationMigration
from .article_migration import ArticleMigration
from .stock_entry_migration import StockEntryMigration
from .delivery_note_migration import DeliveryNoteMigration
from .payment_entry_migration import SalesPaymentEntryMigration, PurchasePaymentEntryMigration
from .crm_event_migration import CrmEventMigration
from weclapp import WeClappAPI, WeClappDocType, WcCacheApi
from erpnext import ERPNextAPI, ERPNextDocType

class MigrationWrapper:
    """Generic migration wrapper from WeClapp to ERPNext.
    """

    def __init__(self, wc_doctype: WeClappDocType, en_doctype: ERPNextDocType):
        """Initializes the migration wrapper.

        Args:
            wc_doctype (WeClappDocTypes): WeClapp document type
            en_doctype (ERPNextDocTypes): ERPNext document type
        """
        self.wc_doctype = wc_doctype
        self.en_doctype = en_doctype
        #self.wc_api = WeClappAPI(config.WC_API_TOKEN, config.WC_API_BASE)
        self.wc_api = WcCacheApi(config.WC_CACHE_BASE)
        self.en_api = ERPNextAPI(config.EN_API_KEY, config.EN_API_SECRET, config.EN_API_BASE)
        self.wc_custom_attribute_definitions = self.wc_api.get_custom_attribute_definitions()
        self.wc_article_categories = self.wc_api.get_article_categories()
        self.wc_article_supply_sources = self.wc_api.get_article_supply_sources()
        self.wc_articles = self.wc_api.get_articles()
        self.wc_storage_places = self.wc_api.get_storage_places()
        self.wc_sales_invoices = self.wc_api.get_sales_invoices()
        self.wc_purchase_invoices = self.wc_api.get_purchase_invoices()
        self.wc_ledger_accounts = self.wc_api.get_ledger_accounts()
        self.wc_accounting_tx_index = self.wc_api.get_accounting_transaction_payment_index()
        self.wc_parties = self.wc_api.get_parties()
        self.wc_comments = self.wc_api.get_comments()


    def __enter__(self):
        """Setup function for the migration wrapper.
        """
        self.wc_api.open()
        self.en_api.open()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Cleanup function for the migration wrapper.
        """
        self.wc_api.close()
        self.en_api.close()

    def migrate_all(self, sort_key=None):
        """Migrates all documents from WeClapp to ERPNext of the given DocType.
        A failure on a single record is logged and skipped rather than aborting the whole batch,
        since a single bad/duplicate record shouldn't block migrating the rest.

        Args:
            sort_key (callable, optional): If given, documents are sorted by this key before
                migrating (e.g. chronologically by posting date for Stock Entries - ERPNext's
                stock ledger triggers expensive future-entry reposting on out-of-order postings).
        """
        wc_data = self.wc_api.get_all(self.wc_doctype)
        if sort_key is not None:
            wc_data = sorted(wc_data, key=sort_key)
        created, failed = 0, 0
        for wc_obj in wc_data:
            try:
                migration = self._get_migration(wc_obj)
                en_obj = migration.migrate()
                if en_obj:
                    created += 1
                    print(f"Created {self.en_doctype} {en_obj['name']}")
            except Exception as e:
                failed += 1
                print(f"FAILED {self.en_doctype} (WeClapp id {wc_obj.get('id', '?')}): {type(e).__name__}: {e}")
        print(f"--- {self.en_doctype}: {created} created, {failed} failed, {len(wc_data)} total ---")

    def _get_migration(self, wc_obj: dict) -> BaseMigration:
        """Returns the migration object for the given WeClapp-Object.

        Returns:
            BaseMigration: Migration object
        """
        match self.en_doctype:
            case ERPNextDocType.CUSTOMER:
                return CustomerMigration(self.en_api, wc_obj, self.wc_custom_attribute_definitions,
                                          self.wc_parties, self.wc_comments)
            case ERPNextDocType.SUPPLIER:
                return SupplierMigration(self.en_api, wc_obj, self.wc_custom_attribute_definitions,
                                          self.wc_parties, self.wc_comments)
            case ERPNextDocType.ADDRESS:
                return AddressMigration(self.en_api, wc_obj, self.wc_custom_attribute_definitions)
            case ERPNextDocType.SALES_INVOICE:
                return InvoiceMigration(self.en_api, wc_obj, self.wc_custom_attribute_definitions)
            case ERPNextDocType.PURCHASE_INVOICE:
                return PurchaseInvoiceMigration(self.en_api, wc_obj, self.wc_custom_attribute_definitions)
            case ERPNextDocType.SALES_ORDER:
                return SalesOrderMigration(self.en_api, wc_obj, self.wc_custom_attribute_definitions)
            case ERPNextDocType.PURCHASE_ORDER:
                return PurchaseOrderMigration(self.en_api, wc_obj, self.wc_custom_attribute_definitions)
            case ERPNextDocType.QUOTATION:
                return QuotationMigration(self.en_api, wc_obj, self.wc_custom_attribute_definitions)
            case ERPNextDocType.ITEM:
                return ArticleMigration(self.en_api, wc_obj, self.wc_custom_attribute_definitions,
                                         self.wc_article_categories, self.wc_article_supply_sources)
            case ERPNextDocType.STOCK_ENTRY:
                return StockEntryMigration(self.en_api, wc_obj, self.wc_custom_attribute_definitions,
                                            self.wc_articles, self.wc_storage_places)
            case ERPNextDocType.DELIVERY_NOTE:
                return DeliveryNoteMigration(self.en_api, wc_obj, self.wc_custom_attribute_definitions,
                                              self.wc_storage_places)
            case ERPNextDocType.PAYMENT_ENTRY:
                # Two distinct WeClapp sources (salesOpenItem/purchaseOpenItem) map onto the
                # same ERPNext doctype - disambiguate via self.wc_doctype
                if self.wc_doctype == WeClappDocType.SALES_OPEN_ITEM:
                    return SalesPaymentEntryMigration(self.en_api, wc_obj, self.wc_custom_attribute_definitions,
                                                       self.wc_sales_invoices, self.wc_ledger_accounts,
                                                       self.wc_accounting_tx_index)
                else:
                    return PurchasePaymentEntryMigration(self.en_api, wc_obj, self.wc_custom_attribute_definitions,
                                                          self.wc_purchase_invoices, self.wc_ledger_accounts,
                                                          self.wc_accounting_tx_index)
            case ERPNextDocType.COMMUNICATION:
                return CrmEventMigration(self.en_api, wc_obj, self.wc_custom_attribute_definitions,
                                          self.wc_parties)
            case _:
                raise Exception("No migration found for given doctype!")