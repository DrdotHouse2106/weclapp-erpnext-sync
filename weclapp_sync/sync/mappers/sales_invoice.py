"""Rechnungs-Mapper: WeClapp `salesInvoice` -> ERPNext `Sales Invoice`.

Portiert aus reference/.../invoice_migration.py. Gleiche Positions-/Steuerlogik wie Angebot/
Auftrag (`_transaction`). Dokumentname = WeClapp-`invoiceNumber` (kein Präfix).

Gutschriften (`salesInvoiceType == "CREDIT_NOTE"`): WeClapp führt Betrag/Menge positiv;
ERPNext bekommt `is_return = 1` mit negierten Mengen, Steuern und Kopfrabatt.

`update_stock = 0` - der Lagerabgang läuft über Lieferscheine / Stock Movements, nicht über
die Rechnung (sonst doppelte Buchung, siehe Vorgänger-CLAUDE.md).

Zahlungsziel: WeClapps echtes `dueDate` steht im `payment_schedule`; als Rahmen wird das
100-Jahre-Template „Migration - unbegrenzt" gesetzt, sonst füllt ERPNext das Template aus
`Customer.payment_terms` und lehnt unser `due_date` ab.
"""

from __future__ import annotations

import frappe

from weclapp_sync import erpnext_helpers as h
from weclapp_sync.setup import masters
from weclapp_sync.sync.mappers import _custom_attributes as ca
from weclapp_sync.sync.mappers._transaction import TransactionMapper
from weclapp_sync.sync.settings import get_settings


class SalesInvoiceMapper(TransactionMapper):
	target_doctype = "Sales Invoice"
	items_field = "salesInvoiceItems"

	def should_skip(self, record: dict) -> bool:
		if not (
			record.get("invoiceNumber")
			and record.get("customerNumber")
			and record.get("salesInvoiceItems")
		):
			return True
		# Gutschriften haben in WeClapp positiven Betrag + Typ CREDIT_NOTE. netAmount <= 0
		# ist eine Datenanomalie (Null-/Negativrechnung) -> überspringen.
		try:
			return float(record.get("netAmount") or 0) <= 0
		except (TypeError, ValueError):
			return False

	def target_name(self, record: dict) -> str | None:
		return record.get("invoiceNumber") or None

	@staticmethod
	def _is_credit_note(record: dict) -> bool:
		return record.get("salesInvoiceType") == "CREDIT_NOTE"

	def upsert(self, record: dict) -> str | None:
		if self.should_skip(record):
			return None
		name = self.target_name(record)
		settings = get_settings()
		is_return = self._is_credit_note(record)

		self.ensure_customer(record.get("customerNumber"), record)

		items, acc_taxes = self.build_lines(record, is_selling=True, account_field="income_account")
		if not items:
			return None
		if is_return:
			for it in items:
				it["qty"] = -abs(it["qty"])
		tax_rows = self.build_tax_rows(record, acc_taxes, negate=is_return)

		existing_name = self.find_existing(record, name)
		doc = (
			frappe.get_doc("Sales Invoice", existing_name)
			if existing_name
			else frappe.new_doc("Sales Invoice")
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
				"customer": record.get("customerNumber"),
				"set_posting_time": 1,
				"posting_date": posting_date,
				"due_date": due_date,
				"is_return": 1 if is_return else 0,
				"update_stock": 0,
				"ignore_pricing_rule": 1,
				"apply_discount_on": "Net Total",
				"discount_amount": self.header_discount_amount(record, negate=is_return),
				"payment_terms_template": None if is_return else migration_terms,
				"title": (record.get("commission") or "")[:140] or None,
				"wc_id": str(record.get("id") or "") or None,
				"wc_last_modified": str(record.get("lastModifiedDate") or "") or None,
				# Rein informativ - kein Zahlungsabgleich/Payment Entry für Altbestand (der ist
				# in WeClapp/beim Steuerberater schon real gebucht; ein Entwurfsbeleg hier würde
				# nichts Echtes buchen). Siehe CLAUDE.md "Zahlungsabgleich".
				"wc_paid": 1 if (record.get("paid") or record.get("paymentStatus") == "PAID") else 0,
				"wc_payment_status": record.get("paymentStatus") or None,
			}
		)

		son = record.get("salesOrderNumber")
		if son and frappe.db.exists("Sales Order", son):
			doc.wc_sales_order = son

		if settings.default_sales_taxes_template and frappe.db.exists(
			"Sales Taxes and Charges Template", settings.default_sales_taxes_template
		):
			doc.taxes_and_charges = settings.default_sales_taxes_template

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

		self.check_gross_total(doc, record, label="Rechnung", negate=is_return)

		if settings.submit_documents and doc.docstatus == 0:
			doc.submit()

		return doc.name
