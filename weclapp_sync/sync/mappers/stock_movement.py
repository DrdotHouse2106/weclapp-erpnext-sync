"""Lagerbewegungs-Mapper: WeClapp `warehouseStockMovement` -> ERPNext `Stock Entry`.

Portiert aus reference/.../stock_entry_migration.py.

**Bleibt IMMER Entwurf (docstatus 0) - anders als der Vorgänger.** Der hat damit einmalig den
kompletten WeClapp-Lagerbestand nachgebaut (bewusst der EINZIGE Schritt, der dort den ERPNext-
Lagerbestand real bewegt hat - Lieferscheine liefen dort bereits mit `update_stock=0`, siehe
`shipment.py`). Für den laufenden Sync hier ist das echte Submitten zu riskant, solange nicht
final geklärt ist, wie/wann der Lagerbestand in ERPNext tatsächlich aufgebaut werden soll - ein
versehentlich falsch gebuchter Bestand ist schwer rückgängig zu machen. Reine Dokumentation der
historischen Bewegung; ein echter 1:1-Nachbau des Lagerbestands ist ein bewusster, einmaliger
Extra-Schritt (gezieltes Submitten in der richtigen Reihenfolge), nicht Teil des laufenden Syncs.

Auflösung: `articleId` -> `Item.wc_id` (Datenbank-Lookup, kein WeClapp-Aufruf), `storagePlaceId`
-> `storagePlace.warehouseId` -> `warehouse.name` -> `h.ensure_warehouse()` (zwei kleine,
einmalig pro Lauf gecachte WeClapp-Listen: `storagePlace` ~1350, `warehouse` <20 Einträge).
"""

from __future__ import annotations

import frappe

from weclapp_sync import erpnext_helpers as h
from weclapp_sync.sync.mappers.base import Mapper
from weclapp_sync.sync.settings import get_settings


class StockMovementMapper(Mapper):
	target_doctype = "Stock Entry"

	def __init__(self) -> None:
		super().__init__()
		self._storage_places: dict | None = None
		self._warehouse_names: dict | None = None

	def should_skip(self, record: dict) -> bool:
		return not (
			record.get("id")
			and record.get("articleId")
			and record.get("storagePlaceId")
			and record.get("quantity") is not None
		)

	def target_name(self, record: dict) -> str | None:
		wc_id = record.get("id")
		return f"LB-{wc_id}" if wc_id else None

	def _storage_places_map(self) -> dict:
		if self._storage_places is None:
			self._storage_places = {}
			if self.client is not None:
				try:
					self._storage_places = {p["id"]: p for p in self.client.iter_all("storagePlace")}
				except Exception:
					self._storage_places = {}
		return self._storage_places

	def _warehouse_names_map(self) -> dict:
		if self._warehouse_names is None:
			self._warehouse_names = {}
			if self.client is not None:
				try:
					self._warehouse_names = {w["id"]: w.get("name") for w in self.client.iter_all("warehouse")}
				except Exception:
					self._warehouse_names = {}
		return self._warehouse_names

	def _resolve_warehouse(self, storage_place_id) -> str | None:
		place = self._storage_places_map().get(storage_place_id)
		if not place:
			return None
		wh_name = self._warehouse_names_map().get(place.get("warehouseId"))
		return h.ensure_warehouse(wh_name) if wh_name else None

	def upsert(self, record: dict) -> str | None:
		if self.should_skip(record):
			return None
		name = self.target_name(record)

		item_code = frappe.db.get_value("Item", {"wc_id": str(record.get("articleId"))}, "name")
		warehouse = self._resolve_warehouse(record.get("storagePlaceId"))
		if not item_code or not warehouse:
			return None

		existing_name = self.find_existing(record, name)
		doc = frappe.get_doc("Stock Entry", existing_name) if existing_name else frappe.new_doc("Stock Entry")
		if existing_name and doc.docstatus == 1:
			# Sollte nie vorkommen (dieser Mapper submittet nie) - Sicherheitsnetz für Re-Runs.
			return existing_name

		is_receipt = str(record.get("stockMovementType") or "").startswith("IN")
		qty = abs(float(record.get("quantity") or 0))
		posting_date = (
			h.clamp_posting_date(h.date_from_ts(record.get("postingDate"))) or frappe.utils.nowdate()
		)
		uom = frappe.db.get_value("Item", item_code, "stock_uom") or h.default_uom()

		item = {"item_code": item_code, "qty": qty, "uom": uom}
		if is_receipt:
			item["t_warehouse"] = warehouse
			valuation_price = record.get("valuationPrice")
			if valuation_price not in (None, ""):
				try:
					item["basic_rate"] = float(valuation_price)
				except (TypeError, ValueError):
					pass
		else:
			item["s_warehouse"] = warehouse

		remarks = f"WeClapp Lagerbewegung {record.get('movementNumber')} ({record.get('stockMovementType')})"
		note = record.get("movementNote")
		if note:
			remarks += f" - {note}"

		doc.update(
			{
				"company": get_settings().company or None,
				"stock_entry_type": "Material Receipt" if is_receipt else "Material Issue",
				"set_posting_time": 1,
				"posting_date": posting_date,
				"remarks": remarks,
				"wc_id": str(record.get("id") or "") or None,
				"wc_last_modified": str(record.get("lastModifiedDate") or "") or None,
			}
		)
		doc.set("items", [item])

		doc.flags.ignore_permissions = True
		if existing_name:
			doc.save()
		else:
			doc.insert(set_name=name)

		# Bewusst KEIN doc.submit() - siehe Moduldocstring.
		return doc.name
