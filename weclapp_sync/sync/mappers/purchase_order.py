"""Bestell-Mapper: WeClapp `purchaseOrder` -> ERPNext `Purchase Order`.

Portiert aus reference/.../purchase_order_migration.py. Spiegelbildlich zu `sales_order.py`
(gleiche `_transaction`-Basis, `is_selling=False` -> `expense_account`/Einkaufssteuer-Fallback).
Dokumentname = WeClapp-`purchaseOrderNumber` (kein Präfix).
"""

from __future__ import annotations

import frappe

from weclapp_sync import erpnext_helpers as h
from weclapp_sync.sync.mappers import _custom_attributes as ca
from weclapp_sync.sync.mappers._transaction import TransactionMapper
from weclapp_sync.sync.settings import get_settings


class PurchaseOrderMapper(TransactionMapper):
	target_doctype = "Purchase Order"
	items_field = "purchaseOrderItems"

	def should_skip(self, record: dict) -> bool:
		return not (
			record.get("purchaseOrderNumber")
			and record.get("supplierNumber")
			and record.get("purchaseOrderItems")
		)

	def target_name(self, record: dict) -> str | None:
		return record.get("purchaseOrderNumber") or None

	def upsert(self, record: dict) -> str | None:
		if self.should_skip(record):
			return None
		name = self.target_name(record)
		settings = get_settings()

		items, acc_taxes = self.build_lines(record, is_selling=False, account_field="expense_account")
		if not items:
			return None
		tax_rows = self.build_tax_rows(record, acc_taxes)

		existing_name = self.find_existing(record, name)
		doc = (
			frappe.get_doc("Purchase Order", existing_name)
			if existing_name
			else frappe.new_doc("Purchase Order")
		)
		if existing_name and doc.docstatus == 1:
			return existing_name

		order_date = h.clamp_posting_date(h.date_from_ts(record.get("orderDate"))) or frappe.utils.nowdate()
		schedule_date = max(
			h.date_from_ts(record.get("plannedDeliveryDate")) or order_date, order_date
		)
		warehouse = h.ensure_warehouse(record.get("warehouseName"))
		for it in items:
			it["schedule_date"] = schedule_date
			if warehouse:
				it["warehouse"] = warehouse

		doc.update(
			{
				"supplier": record.get("supplierNumber"),
				"transaction_date": order_date,
				"schedule_date": schedule_date,
				"ignore_pricing_rule": 1,
				"apply_discount_on": "Net Total",
				"discount_amount": self.header_discount_amount(record),
				"wc_id": str(record.get("id") or "") or None,
				"wc_last_modified": str(record.get("lastModifiedDate") or "") or None,
			}
		)

		# Streckengeschäft: der Verkaufsauftrag, für den direkt beim Lieferanten bestellt wurde.
		son = record.get("salesOrderNumber")
		if son and frappe.db.exists("Sales Order", son):
			doc.wc_sales_order = son

		if settings.default_purchase_taxes_template and frappe.db.exists(
			"Purchase Taxes and Charges Template", settings.default_purchase_taxes_template
		):
			doc.taxes_and_charges = settings.default_purchase_taxes_template

		doc.set("items", items)
		doc.set("taxes", tax_rows)
		doc.update(ca.resolve(record, self.custom_attribute_definitions(), self.custom_attribute_field_map()))

		doc.flags.ignore_permissions = True
		if existing_name:
			doc.save()
		else:
			doc.insert(set_name=name)

		self.check_gross_total(doc, record, label="Bestellung")

		if settings.submit_documents and doc.docstatus == 0:
			doc.submit()

		return doc.name
