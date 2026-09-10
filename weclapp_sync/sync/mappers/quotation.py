"""Angebots-Mapper: WeClapp `quotation` -> ERPNext `Quotation`.

Portiert aus reference/.../quotation_migration.py.
"""

from __future__ import annotations

from typing import Any

import frappe

from weclapp_sync import erpnext_helpers as h
from weclapp_sync.sync.mappers import _custom_attributes as ca
from weclapp_sync.sync.mappers._transaction import TransactionMapper
from weclapp_sync.sync.settings import get_settings


class QuotationMapper(TransactionMapper):
	target_doctype = "Quotation"
	items_field = "quotationItems"

	def should_skip(self, record: dict) -> bool:
		return not (
			record.get("quotationNumber")
			and record.get("customerNumber")
			and record.get("quotationItems")
		)

	def target_name(self, record: dict) -> str | None:
		num = record.get("quotationNumber")
		return f"AN-{num}" if num else None

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
		doc = frappe.get_doc("Quotation", existing_name) if existing_name else frappe.new_doc("Quotation")
		if existing_name and doc.docstatus == 1:
			# Bereits gebucht -> nicht anfassen (Re-Run).
			return existing_name

		doc.update(
			{
				"quotation_to": "Customer",
				"party_name": record.get("customerNumber"),
				"transaction_date": h.date_from_ts(record.get("quotationDate")) or frappe.utils.nowdate(),
				"valid_till": h.date_from_ts(record.get("validTo")),
				"order_type": "Sales",
				"ignore_pricing_rule": 1,
				"apply_discount_on": "Net Total",
				"discount_amount": self.header_discount_amount(record),
				"wc_id": str(record.get("id") or "") or None,
				"wc_last_modified": str(record.get("lastModifiedDate") or "") or None,
			}
		)
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

		if settings.submit_documents and doc.docstatus == 0:
			doc.submit()

		return doc.name
