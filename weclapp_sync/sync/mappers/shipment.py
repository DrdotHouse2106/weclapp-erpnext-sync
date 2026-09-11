"""Lieferschein-Mapper: WeClapp `shipment` -> ERPNext `Delivery Note`.

Portiert aus reference/.../delivery_note_migration.py.

**Bleibt IMMER Entwurf (docstatus 0) - unabhängig von `submit_documents`.** Ein submitteter
Delivery Note bucht in ERPNext UNBEDINGT auf den Lagerbestand; anders als Sales Invoice gibt es
dafür kein `update_stock`-Opt-out-Feld (live im Vorgänger bestätigt: die ERPNext-API lehnt das
Feld auf Delivery Note als unbekannt ab). Sobald `stock_movement` (aus WeClapps
`warehouseStockMovement`) gebaut ist, bildet der exakt dieselbe Wareneinbewegung schon ab - ein
submitteter Lieferschein würde doppelt abziehen. Der Lieferschein ist hier reine Liefer-/
Tracking-Dokumentation, keine Finanzdaten (die stehen auf der Rechnung: `rate`/`price_list_rate`
bewusst 0, `is_free_item=1` - sonst zieht ERPNext einen Preislisten-Preis).

Nur `status == "SHIPPED"` Sendungen sind eine echte Warenbewegung (NEW/DELIVERY_NOTE_PRINTED
haben das Lager noch nicht verlassen).
"""

from __future__ import annotations

import frappe

from weclapp_sync import erpnext_helpers as h
from weclapp_sync.sync.mappers import _custom_attributes as ca
from weclapp_sync.sync.mappers._transaction import TransactionMapper, _line_title, resolve_line_item
from weclapp_sync.sync.mappers.base import Mapper
from weclapp_sync.sync.settings import get_settings


class ShipmentMapper(Mapper):
	target_doctype = "Delivery Note"

	def should_skip(self, record: dict) -> bool:
		return not (
			record.get("shipmentNumber")
			and record.get("recipientCustomerNumber")
			and record.get("status") == "SHIPPED"
			and record.get("shipmentItems")
		)

	def target_name(self, record: dict) -> str | None:
		return record.get("shipmentNumber") or None

	def upsert(self, record: dict) -> str | None:
		if self.should_skip(record):
			return None
		name = self.target_name(record)
		settings = get_settings()

		TransactionMapper.ensure_customer(record.get("recipientCustomerNumber"), record)

		warehouse = h.ensure_warehouse(record.get("warehouseName"))
		default_uom = h.default_uom()
		items: list[dict] = []
		for wc_item in record.get("shipmentItems") or []:
			title = _line_title(wc_item)
			items.append(
				{
					"item_code": resolve_line_item(wc_item, title),
					"item_name": title[:140],
					"description": title,
					"qty": float(wc_item.get("quantity") or 0) or 1.0,
					"rate": 0,
					"price_list_rate": 0,
					"is_free_item": 1,
					"uom": h.ensure_uom(wc_item.get("unitName")) if wc_item.get("unitName") else default_uom,
					"warehouse": warehouse,
				}
			)
		if not items:
			return None

		existing_name = self.find_existing(record, name)
		doc = (
			frappe.get_doc("Delivery Note", existing_name)
			if existing_name
			else frappe.new_doc("Delivery Note")
		)
		if existing_name and doc.docstatus == 1:
			# Sollte nie vorkommen (dieser Mapper submittet nie) - Sicherheitsnetz für Re-Runs,
			# falls der Beleg manuell gebucht wurde.
			return existing_name

		posting_date = (
			h.clamp_posting_date(h.date_from_ts(record.get("shippingDate") or record.get("createdDate")))
			or frappe.utils.nowdate()
		)

		doc.update(
			{
				"company": settings.company or None,
				"customer": record.get("recipientCustomerNumber"),
				"set_posting_time": 1,
				"posting_date": posting_date,
				"ignore_pricing_rule": 1,
				"wc_id": str(record.get("id") or "") or None,
				"wc_last_modified": str(record.get("lastModifiedDate") or "") or None,
				"wc_tracking_nummer": record.get("packageTrackingNumber") or None,
				"wc_versanddienstleister": record.get("shippingCarrierName") or None,
			}
		)

		son = record.get("salesOrderNumber")
		if son and frappe.db.exists("Sales Order", son):
			doc.wc_sales_order = son

		doc.set("items", items)
		doc.update(ca.resolve(record, self.custom_attribute_definitions(), self.custom_attribute_field_map()))

		doc.flags.ignore_permissions = True
		if existing_name:
			doc.save()
		else:
			doc.insert(set_name=name)

		# Bewusst KEIN doc.submit() hier - siehe Modul-Docstring.
		return doc.name
