"""Artikel-Mapper: WeClapp `article` -> ERPNext `Item`.

Portiert aus reference/.../article_migration.py. Kern-Item + Barcode + Hersteller + Artikelgruppe
+ Zusatzfelder + ein Verkaufspreis (erster allgemeiner WeClapp-Preis).

Preise: WeClapp hat 15 Preiskanäle (NET1-8 netto, GROSS1-7 brutto). Über die
"WeClapp Price List Mapping"-Tabelle in den Settings wird je aktiviertem Kanal eine
ERPNext-Preisliste bespielt - jeder Kanal-Preis inkl. Mengenstaffel (`priceScaleValue` ->
min_qty) und Gültigkeit. Kundenspezifische Preise (`customerId`) -> Item Price mit `customer`.

Noch NICHT portiert (Folge-Schritt):
- Bezugsquellen (`supplySources` -> Item Supplier / item_defaults.default_supplier / Einkaufspreis)
  - `articleSupplySource` hat 87k Einträge, muss pro Artikel gefiltert nachgeladen werden.
- Artikelbilder (WeClapp-Cache, hier nicht vorhanden)
- Item Tax Template - bewusst NICHT (siehe reference _map_item_taxes: Steuer wird pro Belegzeile
  als "Actual" gebucht)
"""

from __future__ import annotations

from typing import Any

import frappe

from weclapp_sync import erpnext_helpers as h
from weclapp_sync.sync.mappers import _custom_attributes as ca
from weclapp_sync.sync.mappers.base import Mapper
from weclapp_sync.sync.settings import get_settings, price_list_mapping


class ArticleMapper(Mapper):
	target_doctype = "Item"

	def __init__(self) -> None:
		super().__init__()
		self._categories: dict | None = None
		self._price_lists: dict | None = None

	def should_skip(self, record: dict) -> bool:
		return not (record.get("articleNumber") and record.get("name"))

	def target_name(self, record: dict) -> str | None:
		return record.get("articleNumber") or None

	def _category_name(self, record: dict) -> str | None:
		if self._categories is None:
			self._categories = {}
			if self.client is not None:
				try:
					self._categories = {
						c["id"]: c.get("name") for c in self.client.iter_all("articleCategory")
					}
				except Exception:
					self._categories = {}
		return self._categories.get(record.get("articleCategoryId"))

	def to_doc_fields(self, record: dict, *, existing: Any = None) -> dict[str, Any]:
		is_new = existing is None
		fields: dict[str, Any] = {
			"item_code": record.get("articleNumber"),
			"item_name": (record.get("name") or "")[:140],
			"stock_uom": h.ensure_uom(record.get("unitName")),
			"is_stock_item": 1 if record.get("articleType") == "STORABLE" else 0,
			"weight_per_unit": record.get("articleGrossWeight") or 0,
			"disabled": 0,
			"manufacturer": h.ensure_manufacturer(record.get("manufacturerName")),
			"manufacturer_part_no": record.get("manufacturerPartNumber") or None,
			"country_of_origin": h.country_name(record.get("countryOfOriginCode")),
			"barcodes": [{"barcode": record["ean"]}] if record.get("ean") else [],
		}
		# description/item_group nur bei Neuanlage - können später von anderen Integrationen
		# (Shopware) mitgepflegt werden (siehe reference article_migration.py).
		if is_new:
			fields["description"] = record.get("description") or record.get("name")
			fields["item_group"] = h.ensure_item_group(self._category_name(record))

		fields.update(ca.resolve(record, self.custom_attribute_definitions(), self.target_doctype))
		return fields

	def _channel_lists(self) -> dict:
		if self._price_lists is None:
			self._price_lists = price_list_mapping()
		return self._price_lists

	def upsert(self, record: dict) -> str | None:
		name = super().upsert(record)
		if not name:
			return None
		self._sync_prices(name, record)
		return name

	def _sync_prices(self, item_code: str, record: dict) -> None:
		"""Aktueller WeClapp-Preis je (Preiskanal, Mengenstaffel, Kunde) -> ERPNext Item Price.

		WeClapp führt eine Preishistorie (mehrere Preise pro Kanal/Staffel mit `startDate`) -
		davon wird nur der jüngste übernommen, ohne Gültigkeitsdaten (sonst ItemPriceDuplicateItem
		wegen überlappender Zeiträume). Idempotent: bestehender Item Price wird in Python
		gematcht (item/price_list/selling + currency/min_qty/customer)."""
		channels = self._channel_lists()
		if not channels:
			return

		# Pro (Kanal, Staffel, Kunde) den Preis mit dem jüngsten startDate behalten.
		best: dict[tuple, dict] = {}
		for p in record.get("articlePrices") or []:
			ch = p.get("salesChannel")
			if ch not in channels or p.get("price") is None:
				continue
			key = (ch, _to_float(p.get("priceScaleValue"), 0.0), p.get("customerId") or None)
			cur = best.get(key)
			if cur is None or (p.get("startDate") or 0) > (cur.get("startDate") or 0):
				best[key] = p

		if not best:
			return

		existing_prices = frappe.get_all(
			"Item Price",
			filters={"item_code": item_code, "selling": 1},
			fields=["name", "price_list", "currency", "min_qty", "customer"],
		)

		for (ch, min_qty, cust_id), p in best.items():
			price_list = channels[ch]
			if not frappe.db.exists("Price List", price_list):
				continue
			currency = h.link_or_none("Currency", p.get("currencyName")) or h.default_currency()
			customer = (
				frappe.db.get_value("Customer", {"wc_id": str(cust_id)}, "name") if cust_id else None
			)

			match = next(
				(
					ip.name
					for ip in existing_prices
					if ip.price_list == price_list
					and ip.currency == currency
					and float(ip.min_qty or 0) == min_qty
					and (ip.customer or None) == (customer or None)
				),
				None,
			)

			doc = frappe.get_doc("Item Price", match) if match else frappe.new_doc("Item Price")
			doc.update(
				{
					"item_code": item_code,
					"price_list": price_list,
					"currency": currency,
					"selling": 1,
					"min_qty": min_qty,
					"customer": customer,
					"price_list_rate": float(p["price"]),
					"valid_from": None,
					"valid_upto": None,
				}
			)
			doc.flags.ignore_permissions = True
			doc.save() if match else doc.insert()


def _to_float(v, default: float) -> float:
	try:
		return float(v)
	except (TypeError, ValueError):
		return default
