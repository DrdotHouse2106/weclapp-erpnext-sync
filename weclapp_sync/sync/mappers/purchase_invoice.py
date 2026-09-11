"""Eingangsrechnungs-Mapper: WeClapp `purchaseInvoice` -> ERPNext `Purchase Invoice`.

Portiert aus reference/.../purchase_invoice_migration.py. Spiegelbildlich zu
`sales_invoice.py` (gleiche `_transaction`-Basis, `update_stock=0`, 100-Jahre-Zahlungsziel-
Template gegen die `Supplier.payment_terms`-Falle, Gutschriften negiert).

Dokumentname = WeClapp-**`internalInvoiceNumber`** (FranceTecs eigene Nummer) - **nicht**
`invoiceNumber` (das ist die Rechnungsnummer des Lieferanten, landet stattdessen in `bill_no`).

`OCR_VERIFICATION`/`CANCELLED` werden übersprungen: unverifizierte OCR-Entwürfe bzw. stornierte
Belege sind keine echten gebuchten Rechnungen (live geprüft - `OCR_VERIFICATION`-Belege haben
teils schon eine `supplierNumber`, der reine Lieferanten-Check aus dem Vorgänger reicht hier
nicht mehr).
"""

from __future__ import annotations

import frappe

from weclapp_sync import erpnext_helpers as h
from weclapp_sync.setup import masters
from weclapp_sync.sync.mappers import _custom_attributes as ca
from weclapp_sync.sync.mappers._transaction import TransactionMapper
from weclapp_sync.sync.settings import get_settings

_SKIP_STATUS = {"OCR_VERIFICATION", "CANCELLED"}


class PurchaseInvoiceMapper(TransactionMapper):
	target_doctype = "Purchase Invoice"
	items_field = "purchaseInvoiceItems"

	def should_skip(self, record: dict) -> bool:
		if not (
			record.get("internalInvoiceNumber")
			and record.get("supplierNumber")
			and record.get("purchaseInvoiceItems")
		):
			return True
		if record.get("status") in _SKIP_STATUS:
			return True
		try:
			return float(record.get("netAmount") or 0) <= 0
		except (TypeError, ValueError):
			return False

	def target_name(self, record: dict) -> str | None:
		return record.get("internalInvoiceNumber") or None

	@staticmethod
	def _is_credit_note(record: dict) -> bool:
		return record.get("purchaseInvoiceType") == "CREDIT_NOTE"

	def upsert(self, record: dict) -> str | None:
		if self.should_skip(record):
			return None
		name = self.target_name(record)
		settings = get_settings()
		is_return = self._is_credit_note(record)

		items, acc_taxes = self.build_lines(record, is_selling=False, account_field="expense_account")
		if not items:
			return None
		if is_return:
			for it in items:
				it["qty"] = -abs(it["qty"])
		tax_rows = self.build_tax_rows(record, acc_taxes, negate=is_return)
		tax_rows += self._import_sales_tax_row(record, negate=is_return)

		existing_name = self.find_existing(record, name)
		doc = (
			frappe.get_doc("Purchase Invoice", existing_name)
			if existing_name
			else frappe.new_doc("Purchase Invoice")
		)
		if existing_name and doc.docstatus == 1:
			return existing_name

		posting_date = h.clamp_posting_date(h.date_from_ts(record.get("invoiceDate"))) or frappe.utils.nowdate()
		due_date = max(
			h.clamp_posting_date(h.date_from_ts(record.get("dueDate"))) or posting_date, posting_date
		)

		migration_terms = (
			masters.MIGRATION_PAYMENT_TERMS_TEMPLATE
			if frappe.db.exists("Payment Terms Template", masters.MIGRATION_PAYMENT_TERMS_TEMPLATE)
			else None
		)

		doc.update(
			{
				"supplier": record.get("supplierNumber"),
				"set_posting_time": 1,
				"posting_date": posting_date,
				"due_date": due_date,
				"bill_no": record.get("invoiceNumber") or None,
				"bill_date": posting_date,
				"is_return": 1 if is_return else 0,
				"update_stock": 0,
				"ignore_pricing_rule": 1,
				"apply_discount_on": "Net Total",
				"discount_amount": self.header_discount_amount(record, negate=is_return),
				"payment_terms_template": None if is_return else migration_terms,
				"wc_id": str(record.get("id") or "") or None,
				"wc_last_modified": str(record.get("lastModifiedDate") or "") or None,
				# Rein informativ - kein Zahlungsabgleich für Altbestand, siehe CLAUDE.md.
				"wc_paid": 1 if (record.get("paid") or record.get("paymentStatus") == "PAID") else 0,
				"wc_payment_status": record.get("paymentStatus") or None,
			}
		)

		po_refs = record.get("purchaseOrders") or []
		if po_refs:
			po_name = frappe.db.get_value("Purchase Order", {"wc_id": str(po_refs[0].get("id"))}, "name")
			if po_name:
				doc.wc_purchase_order = po_name

		if settings.default_purchase_taxes_template and frappe.db.exists(
			"Purchase Taxes and Charges Template", settings.default_purchase_taxes_template
		):
			doc.taxes_and_charges = settings.default_purchase_taxes_template

		doc.set("items", items)
		doc.set("taxes", tax_rows)
		if migration_terms and not is_return:
			doc.set("payment_schedule", [{"due_date": due_date, "invoice_portion": 100}])
		doc.update(ca.resolve(record, self.custom_attribute_definitions(), self.custom_attribute_field_map()))

		doc.flags.ignore_permissions = True
		if existing_name:
			doc.save()
		else:
			doc.insert(set_name=name)

		self.check_gross_total(doc, record, label="Eingangsrechnung", negate=is_return)

		if settings.submit_documents and doc.docstatus == 0:
			doc.submit()

		return doc.name

	def _import_sales_tax_row(self, record: dict, *, negate: bool) -> list[dict]:
		"""WeClapps `importSalesTaxAmount` (Einfuhrumsatzsteuer bei Drittland-Importen) als
		zusätzliche "Actual"-Steuerzeile - sonst weicht die Bruttosumme dieser wenigen Belege
		spürbar ab. Kein eigenes WeClapp-Steuer-Mapping dafür (ist kein `taxId`) -> Fallback-
		Einkaufssteuerkonto."""
		try:
			amount = float(record.get("importSalesTaxAmount") or 0)
		except (TypeError, ValueError):
			amount = 0.0
		if not amount:
			return []
		account = self._fallback_tax_account()
		if not account:
			return []
		if negate:
			amount = -amount
		return [
			{
				"charge_type": "Actual",
				"account_head": account,
				"description": "Einfuhrumsatzsteuer",
				"tax_amount": round(amount, 2),
				"cost_center": get_settings().default_cost_center or None,
			}
		]
