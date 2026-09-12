"""Auftrags-Mapper: WeClapp `salesOrder` -> ERPNext `Sales Order`.

Portiert aus reference/.../sales_order_migration.py. Gleiche Positions-/Steuerlogik wie das
Angebot (`_transaction`), zusätzlich Liefertermin und der Belegketten-Verweis auf das Angebot
(`wc_quotation`, read-only Link). Dokumentname = WeClapp-`orderNumber` (kein Präfix).
"""

from __future__ import annotations

import frappe

from weclapp_sync import erpnext_helpers as h
from weclapp_sync.sync.mappers import _custom_attributes as ca
from weclapp_sync.sync.mappers._attachments import attach_weclapp_documents
from weclapp_sync.sync.mappers._transaction import TransactionMapper
from weclapp_sync.sync.settings import get_settings
from weclapp_sync.weclapp import WeClappDocType


class SalesOrderMapper(TransactionMapper):
	target_doctype = "Sales Order"
	items_field = "orderItems"

	def should_skip(self, record: dict) -> bool:
		if not (record.get("orderNumber") and record.get("customerNumber") and record.get("orderItems")):
			return True
		# Negativ-Aufträge (Retouren/Gutschriften in WeClapp) kann ERPNext als Sales Order
		# nicht abbilden (Grand Total muss >= 0 sein) -> überspringen.
		try:
			return float(record.get("netAmount") or 0) < 0
		except (TypeError, ValueError):
			return False

	def target_name(self, record: dict) -> str | None:
		# ERPNext-Dokumentname = WeClapp-Auftragsnummer (kein Präfix); autoname=Prompt ist
		# per Property Setter gesetzt (setup/naming.py).
		return record.get("orderNumber") or None

	def upsert(self, record: dict) -> str | None:
		if self.should_skip(record):
			return None
		name = self.target_name(record)
		settings = get_settings()

		self.ensure_customer(record.get("customerNumber"), record)

		items, acc_taxes = self.build_lines(record, is_selling=True, account_field="income_account")
		if not items:
			return None
		tax_rows = self.build_tax_rows(record, acc_taxes)

		existing_name = self.find_existing(record, name)
		doc = (
			frappe.get_doc("Sales Order", existing_name)
			if existing_name
			else frappe.new_doc("Sales Order")
		)
		if existing_name and doc.docstatus == 1:
			return existing_name

		order_date = h.clamp_posting_date(h.date_from_ts(record.get("orderDate"))) or frappe.utils.nowdate()
		# WeClapp lässt `plannedShippingDate` vor dem Auftragsdatum zu, ERPNext nicht.
		delivery_date = max(h.date_from_ts(record.get("plannedShippingDate")) or order_date, order_date)
		warehouse = h.ensure_warehouse(record.get("warehouseName"))
		for it in items:
			it["delivery_date"] = delivery_date
			if warehouse:
				it["warehouse"] = warehouse

		doc.update(
			{
				"customer": record.get("customerNumber"),
				"transaction_date": order_date,
				"delivery_date": delivery_date,
				"order_type": "Sales",
				"ignore_pricing_rule": 1,
				"apply_discount_on": "Net Total",
				"discount_amount": self.header_discount_amount(record),
				"wc_id": str(record.get("id") or "") or None,
				"wc_last_modified": str(record.get("lastModifiedDate") or "") or None,
			}
		)

		qn = record.get("quotationNumber")
		if qn and frappe.db.exists("Quotation", qn):
			doc.wc_quotation = qn

		if settings.default_sales_taxes_template and frappe.db.exists(
			"Sales Taxes and Charges Template", settings.default_sales_taxes_template
		):
			doc.taxes_and_charges = settings.default_sales_taxes_template

		doc.set("items", items)
		doc.set("taxes", tax_rows)
		doc.update(ca.resolve(record, self.custom_attribute_definitions(), self.custom_attribute_field_map()))

		doc.flags.ignore_permissions = True
		if existing_name:
			doc.save()
		else:
			doc.insert(set_name=name)

		self.check_gross_total(doc, record, label="Auftrag")

		if settings.submit_documents and doc.docstatus == 0:
			doc.submit()

		attach_weclapp_documents(self.client, WeClappDocType.SALES_ORDER, record.get("id"), "Sales Order", doc.name)
		return doc.name
