import config
from .base_migration import BaseMigration
from erpnext import ERPNextAPI, ERPNextDocType, ERPNextHelper
from weclapp import WeClappDocType

class _PaymentEntryMigrationBase(BaseMigration):
    """Shared logic for migrating a WeClapp Sales-/Purchase-OpenItem (offener Posten) to
    ERPNext Payment Entries - or, where no real payment happened, a write-off Journal Entry.

    Replaces the old lump-sum "fully paid on the invoice date, against a single cash account"
    shortcut in InvoiceMigration/PurchaseInvoiceMigration with WeClapp's real payment data.

    Resolving a payment to its real bank/cash account and date turned out to require WeClapp's
    accounting journal (accountingTransaction), not the paymentApplication's own
    bankTransactionId/cashTransactionId fields - those don't reliably indicate a real payment
    even happened (verified against real examples: WeClapp write-offs/payment differences that
    were never real bank movements still carry a bankTransactionId or cashTransactionId). The
    only reliable signal is a matching journal entry, found via invoice number + settled amount
    (accountingTransaction.externalRecordNumber + the bank/cash-side transactionDetail amount -
    NOT amount+date, which doesn't correlate closely enough to be unique/reliable). Empirically:
    ~81% of sales and ~71% of purchase payments resolve this way, essentially without ambiguity.

    One open item can carry several paymentApplications (split/partial payments, or a mix of a
    real payment and a write-off on the same invoice) - each becomes its own Payment Entry or
    Journal Entry, so migrate() loops internally instead of the usual 1:1
    BaseMigration.migrate()/_transform() contract (_transform() is intentionally unused here).
    """

    NAME_PREFIX = None    # "ZE" (Zahlungseingang) / "ZA" (Zahlungsausgang) - set by subclass
    WRITEOFF_PREFIX = None  # "AB" (Abschreibung) - same for both subclasses
    PAYMENT_TYPE = None   # "Receive" / "Pay" - set by subclass
    PARTY_TYPE = None     # "Customer" / "Supplier" - set by subclass
    TX_TYPE = None        # "INCOMING_PAYMENT" / "OUTGOING_PAYMENT" - set by subclass

    def __init__(self, en_api: ERPNextAPI, wc_data: dict, wc_custom_attribute_definitions: dict,
                 wc_invoices: dict = None, wc_ledger_accounts: dict = None,
                 wc_accounting_tx_index: dict = None):
        """Initializes the migration wrapper.

        Args:
            en_api (ERPNextAPI): ERPNext-API-Object
            wc_data (dict): WeClapp-API-Object (a single sales/purchaseOpenItem)
            wc_custom_attribute_definitions (dict): WeClapp custom attribute definitions
            wc_invoices (dict, optional): WeClapp sales/purchase invoices keyed by id (for
                resolving the openItem's invoiceId to the invoice's customer/supplier number)
            wc_ledger_accounts (dict, optional): WeClapp ledger accounts keyed by id (see
                WcCacheApi.get_ledger_accounts())
            wc_accounting_tx_index (dict, optional): WeClapp accounting-journal payment index
                (see WcCacheApi.get_accounting_transaction_payment_index())
        """
        super().__init__(en_api, wc_data, wc_custom_attribute_definitions)
        self.wc_invoices = wc_invoices or {}
        self.wc_ledger_accounts = wc_ledger_accounts or {}
        self.wc_accounting_tx_index = wc_accounting_tx_index or {}

    def get_doctype(self) -> ERPNextDocType:
        return ERPNextDocType.PAYMENT_ENTRY

    def _get_wc_invoice(self) -> dict:
        """Resolves the openItem's WeClapp invoice (raw WeClapp data, not the ERPNext doc)."""
        raise NotImplementedError

    def _get_reference_doctype(self) -> ERPNextDocType:
        raise NotImplementedError

    def _get_reference_name(self, wc_invoice: dict) -> str:
        """Returns the already-migrated ERPNext invoice's deterministic name."""
        raise NotImplementedError

    def _get_journal_invoice_number(self, wc_invoice: dict) -> str:
        """Returns the invoice number as it appears in the bank statement / accounting journal
        (accountingTransaction.externalRecordNumber) - NOT necessarily the same field as the
        ERPNext reference name. For purchases this is the supplier's own invoiceNumber, not
        FranceTec's internalInvoiceNumber (which is what _get_reference_name() uses) - the bank
        obviously only knows the supplier's number.
        """
        raise NotImplementedError

    def _get_party(self, wc_invoice: dict) -> str:
        raise NotImplementedError

    def _get_receivable_account(self) -> tuple[str, str]:
        """Returns (account, account_type) for the receivable/payable side of the booking -
        used both for Payment Entry (paid_from/paid_to) and the write-off Journal Entry."""
        raise NotImplementedError

    def validate(self) -> bool:
        """
        Validates the given data.
        Returns: True if valid, False if not
        """
        wc_invoice = self._get_wc_invoice()
        if not wc_invoice or not self._get_party(wc_invoice):
            return False
        reference_name = self._get_reference_name(wc_invoice)
        if not reference_name:
            return False
        # The referenced invoice may not exist in ERPNext (InvoiceMigration/
        # PurchaseInvoiceMigration skip zero-amount or supplier-less invoices) - skip silently
        # rather than failing, same as any other missing link elsewhere in the migration.
        # Cached for migrate(), which needs the same document right after.
        self._en_invoice = self._en_api.get(self._get_reference_doctype(), reference_name)
        return bool(self._en_invoice)

    def migrate(self) -> dict:
        """Migrates a given WeClapp open item's payment applications, creating one ERPNext
        Payment Entry (real payment found) or Journal Entry (no real payment found - write-off/
        payment difference) per application.

        Returns:
            dict: The last created ERPNext document, or None if none were created
        """
        if not self.validate():
            return None

        wc_invoice = self._get_wc_invoice()
        en_invoice = self._en_invoice

        last_created = None
        for application in self.wc_data.get("paymentApplications", []) or []:
            amount = round(float(application.get("amountApplied", 0) or 0), 2)
            if amount <= 0:
                continue

            # Resolve BEFORE the exists-check: resolution consumes the matched journal entry
            # (see _resolve_real_payment), and that consumption must happen for skipped
            # applications too, so later same-key applications pair with the right entries
            real_payment = self._resolve_real_payment(application, wc_invoice, amount)

            # Check BOTH possible names regardless of the current classification - if the
            # classification of an application changes between runs (e.g. after a cache refresh
            # brings new journal entries), the same application must never be booked a second
            # time under the other doctype
            if self._skip_if_exists_as(ERPNextDocType.PAYMENT_ENTRY, f"{self.NAME_PREFIX}-{application['id']}") or \
               self._skip_if_exists_as(ERPNextDocType.JOURNAL_ENTRY, f"{self.WRITEOFF_PREFIX}-{application['id']}"):
                continue

            if real_payment:
                en_data = self._transform_payment(application, wc_invoice, en_invoice, amount, real_payment)
                doctype = ERPNextDocType.PAYMENT_ENTRY
            else:
                en_data = self._transform_writeoff(application, wc_invoice, en_invoice, amount)
                doctype = ERPNextDocType.JOURNAL_ENTRY

            last_created = self._en_api.create(doctype, en_data)
            print(f"Created {doctype.value} {last_created['name']}")
        return last_created

    def _skip_if_exists_as(self, doctype: ERPNextDocType, name: str) -> bool:
        """Like BaseMigration._skip_if_exists(), but for an explicit doctype - migrate() here
        creates two different doctypes depending on the application, so the doctype can't be
        inferred from self.get_doctype() alone."""
        if name and self._en_api.get(doctype, name):
            print(f"Skipped existing {doctype.value} {name}")
            return True
        return False

    def _resolve_real_payment(self, application: dict, wc_invoice: dict, amount: float) -> dict:
        """Looks up the real bank/cash accounting-journal entry for this payment application.

        Matched journal entries are CONSUMED (popped from the shared index, which lives for the
        whole migration run): several applications with the identical (invoice number, amount)
        key - equal-amount split payments, or a real payment plus a same-amount write-off on one
        invoice - would otherwise all resolve to the same single journal entry and book one real
        payment several times. With consumption each journal entry is handed out exactly once,
        in transactionDate order where several candidates share a key (the applications of one
        key are indistinguishable from each other anyway, so the pairing order only decides
        which date/account goes on which of the identical bookings), and applications beyond
        the number of real journal entries correctly fall through to the write-off path.

        Returns:
            dict: {"account": ..., "posting_date": ..., "reference_no": ...}, or None if no
                matching journal entry was (or is still) available (see class docstring - this
                does NOT mean the payment is unresolved, it usually means there was no real
                payment at all, e.g. a write-off booked as "paid" in WeClapp).
        """
        number = self._get_journal_invoice_number(wc_invoice)
        if not number:
            return None
        candidates = self.wc_accounting_tx_index.get((self.TX_TYPE, str(number), amount))
        if not candidates:
            return None
        if len(candidates) > 1:
            print(f"AMBIGUOUS journal match for invoice {number} / {amount}: "
                  f"{len(candidates)} candidates, pairing in transactionDate order")
            candidates.sort(key=lambda c: c[0].get("transactionDate") or 0)
        tx, ledger_account_id = candidates.pop(0)
        ledger = self.wc_ledger_accounts.get(ledger_account_id)
        if not ledger or not ledger.get("accountNumber"):
            return None
        account_name = ERPNextHelper.get_wc_account_name(ledger["accountNumber"], ledger.get("description"))
        return {
            "account": f"{account_name} - {config.EN_COMPANY_ABBR}",
            "posting_date": ERPNextHelper.get_date_from_weclapp_ts(tx.get("transactionDate")),
            "reference_no": str(tx.get("transactionNumber") or tx.get("id")),
        }

    def _transform(self) -> dict:
        """Unused - see migrate()/_transform_payment()/_transform_writeoff() (one open item can
        produce several ERPNext documents, so there is no single "the" transformed dict).
        """
        raise NotImplementedError("Use _transform_payment()/_transform_writeoff() instead")

    def _transform_payment(self, application: dict, wc_invoice: dict, en_invoice: dict,
                            amount: float, real_payment: dict) -> dict:
        """Transforms a resolved (real bank/cash movement found) paymentApplication into an
        ERPNext Payment Entry, booked against the actual account it was settled with.
        """
        receivable_account, receivable_account_type = self._get_receivable_account()
        accounts = self._map_accounts(receivable_account, receivable_account_type, real_payment["account"])

        # Credit notes (is_return=1) carry a negative outstanding_amount/grand_total - applying
        # a positive amount against that is rejected outright ("payment cannot be greater than
        # outstanding amount", since e.g. 39.95 > -39.95). Confirmed live: 120 of 196 invoices
        # behind the "Zahlung ... kann nicht größer als ausstehender Betrag" failures were credit
        # notes. Negating the amount here matches how ERPNext itself pre-fills allocated_amount
        # when you pick a return invoice in the Payment Entry UI.
        if en_invoice.get("is_return"):
            amount = -amount

        data = {
            "name"              : f"{self.NAME_PREFIX}-{application['id']}",
            "docstatus"         : config.EN_DEFAULT_INVOICE_STATE,
            "company"           : config.EN_COMPANY,
            "set_posting_time"  : 1,
            "posting_date"      : real_payment["posting_date"],
            "payment_type"      : self.PAYMENT_TYPE,
            "party_type"        : self.PARTY_TYPE,
            "party"             : self._get_party(wc_invoice),
            "paid_amount"       : amount,
            "received_amount"   : amount,
            # ERPNext makes reference_no/reference_date mandatory as soon as paid_from/paid_to
            # is a Bank-type account - the WeClapp journal transactionNumber doubles as the
            # traceability link back to the source booking
            "reference_no"      : real_payment["reference_no"],
            "reference_date"    : real_payment["posting_date"],
            "references"        : [{
                "docstatus"         : config.EN_DEFAULT_INVOICE_STATE,
                "reference_doctype" : self._get_reference_doctype().value,
                "reference_name"    : en_invoice.get("name"),
                "total_amount"      : en_invoice.get("grand_total", 0),
                "allocated_amount"  : amount,
            }],
        }
        data.update(accounts)
        return data

    def _map_accounts(self, receivable_account: str, receivable_account_type: str, bank_account: str) -> dict:
        """Returns the direction-specific paid_from/paid_to fields - which side is the
        receivable/payable and which is the resolved bank/cash account depends on payment
        direction (Receive vs. Pay), set by subclass."""
        raise NotImplementedError

    def _transform_writeoff(self, application: dict, wc_invoice: dict, en_invoice: dict, amount: float) -> dict:
        """Transforms a paymentApplication with no real bank/cash movement into a write-off
        Journal Entry: clears the amount off the receivable/payable, booked against
        config.EN_RECEIVABLE_WRITEOFF_ACCOUNT instead of fabricating a bank receipt that never
        happened (see class docstring).
        """
        receivable_account, receivable_account_type = self._get_receivable_account()
        is_receivable = receivable_account_type == "Receivable"
        # Credit notes (is_return=1) carry an already-negative outstanding balance - clearing it
        # moves the receivable/payable the opposite direction of a normal invoice's write-off, so
        # the debit/credit sides flip too (same reasoning as _transform_payment(), same live
        # failure: "Zahlung ... kann nicht größer als ausstehender Betrag" on Journal Entry).
        if en_invoice.get("is_return"):
            is_receivable = not is_receivable

        receivable_line = {
            "account": receivable_account,
            "party_type": self.PARTY_TYPE,
            "party": self._get_party(wc_invoice),
            "reference_type": self._get_reference_doctype().value,
            "reference_name": en_invoice.get("name"),
        }
        writeoff_line = {"account": config.EN_RECEIVABLE_WRITEOFF_ACCOUNT}
        if is_receivable:
            # Sales: receivable balance goes down (credit), write-off expense goes up (debit)
            receivable_line["credit_in_account_currency"] = amount
            writeoff_line["debit_in_account_currency"] = amount
        else:
            # Purchase: payable balance goes down (debit), counter-booked as a reduction of the
            # write-off account (credit) - see module docstring: unverified whether this is the
            # right account for the purchase side, only confirmed for sales write-offs so far
            receivable_line["debit_in_account_currency"] = amount
            writeoff_line["credit_in_account_currency"] = amount

        return {
            "name"             : f"{self.WRITEOFF_PREFIX}-{application['id']}",
            "docstatus"        : config.EN_DEFAULT_INVOICE_STATE,
            "company"          : config.EN_COMPANY,
            "voucher_type"     : "Journal Entry",
            "posting_date"     : ERPNextHelper.get_date_from_weclapp_ts(application.get("createdDate")),
            "accounts"         : [receivable_line, writeoff_line],
        }


class SalesPaymentEntryMigration(_PaymentEntryMigrationBase):
    """Migration wrapper for a WeClapp salesOpenItem (Zahlungseingang/incoming payment)."""

    NAME_PREFIX = "ZE"
    WRITEOFF_PREFIX = "AB"
    PAYMENT_TYPE = "Receive"
    PARTY_TYPE = "Customer"
    TX_TYPE = "INCOMING_PAYMENT"

    def get_wc_doctype(self) -> WeClappDocType:
        return WeClappDocType.SALES_OPEN_ITEM

    def _get_wc_invoice(self) -> dict:
        return self.wc_invoices.get(self.wc_data.get("salesInvoiceId"))

    def _get_reference_doctype(self) -> ERPNextDocType:
        return ERPNextDocType.SALES_INVOICE

    def _get_reference_name(self, wc_invoice: dict) -> str:
        number = wc_invoice.get("invoiceNumber") if wc_invoice else None
        return f"RE-{number}" if number else None

    def _get_journal_invoice_number(self, wc_invoice: dict) -> str:
        return wc_invoice.get("invoiceNumber") if wc_invoice else None

    def _get_party(self, wc_invoice: dict) -> str:
        return wc_invoice.get("customerNumber") if wc_invoice else None

    def _get_receivable_account(self) -> tuple[str, str]:
        return config.EN_INVOICE_PAID_FROM_ACCOUNT, "Receivable"

    def _map_accounts(self, receivable_account: str, receivable_account_type: str, bank_account: str) -> dict:
        return {
            "paid_from"                 : receivable_account,
            "paid_from_account_type"    : receivable_account_type,
            "paid_from_account_currency": config.EN_DEFAULT_CURRENCY,
            "paid_to"                   : bank_account,
            "paid_to_account_currency"  : config.EN_DEFAULT_CURRENCY,
        }


class PurchasePaymentEntryMigration(_PaymentEntryMigrationBase):
    """Migration wrapper for a WeClapp purchaseOpenItem (Zahlungsausgang/outgoing payment)."""

    NAME_PREFIX = "ZA"
    WRITEOFF_PREFIX = "AB"
    PAYMENT_TYPE = "Pay"
    PARTY_TYPE = "Supplier"
    TX_TYPE = "OUTGOING_PAYMENT"

    def get_wc_doctype(self) -> WeClappDocType:
        return WeClappDocType.PURCHASE_OPEN_ITEM

    def _get_wc_invoice(self) -> dict:
        return self.wc_invoices.get(self.wc_data.get("purchaseInvoiceId"))

    def _get_reference_doctype(self) -> ERPNextDocType:
        return ERPNextDocType.PURCHASE_INVOICE

    def _get_reference_name(self, wc_invoice: dict) -> str:
        number = wc_invoice.get("internalInvoiceNumber") if wc_invoice else None
        return f"EK-{number}" if number else None

    def _get_journal_invoice_number(self, wc_invoice: dict) -> str:
        # The supplier's own invoice number (what a bank statement references), NOT FranceTec's
        # internalInvoiceNumber used for _get_reference_name() above - see class docstring.
        return wc_invoice.get("invoiceNumber") if wc_invoice else None

    def _get_party(self, wc_invoice: dict) -> str:
        return wc_invoice.get("supplierNumber") if wc_invoice else None

    def _get_receivable_account(self) -> tuple[str, str]:
        return config.EN_PURCHASE_PAID_TO_ACCOUNT, config.EN_PURCHASE_PAID_TO_ACCOUNT_TYPE

    def _map_accounts(self, receivable_account: str, receivable_account_type: str, bank_account: str) -> dict:
        return {
            "paid_from"                 : bank_account,
            "paid_from_account_currency": config.EN_DEFAULT_CURRENCY,
            "paid_to"                   : receivable_account,
            "paid_to_account_type"      : receivable_account_type,
            "paid_to_account_currency"  : config.EN_DEFAULT_CURRENCY,
        }
