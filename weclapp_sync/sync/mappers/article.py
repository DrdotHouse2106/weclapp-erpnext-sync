"""Artikel-Mapper: WeClapp `article` -> ERPNext `Item`.

Portiert aus reference/.../article_migration.py. Kern-Item + Barcode + Hersteller + Artikelgruppe
+ Zusatzfelder + volle Preishistorie.

Preise: WeClapp hat Preiskanäle (NET1-9 netto, GROSS1-8 brutto). Über die
"WeClapp Price List Mapping"-Tabelle in den Settings wird je aktiviertem Kanal eine
ERPNext-Preisliste bespielt. Die komplette WeClapp-Preishistorie je (Kanal, Mengenstaffel,
Kunde) wird als Item Prices angelegt; WeClapp lässt alte Preise oft mit `endDate=NULL` stehen,
daher wird die Zeitleiste rekonstruiert (valid_upto = nächstes startDate - 1 Tag), sonst
lehnt ERPNext überlappende offene Preise ab. Idempotent inkl. Löschen entfernter Preise.
Kundenspezifische Preise (`customerId`) -> Item Price mit `customer` (wc_id-Lookup).

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
from frappe.utils import add_days

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
		"""Volle WeClapp-Preishistorie je (Preiskanal, Mengenstaffel, Kunde) -> ERPNext Item Prices.

		WeClapp lässt ältere Preise oft mit `endDate = NULL` stehen. ERPNext verbietet zwei
		offene Preise für denselben Schlüssel -> deshalb wird die Zeitleiste rekonstruiert:
		je Gruppe nach `startDate` sortieren, `valid_upto` = min(eigenes endDate, nächstes
		startDate - 1 Tag). Der jüngste Preis bleibt offen (falls kein endDate).

		Idempotent durch **vollständigen Neuaufbau**: alle bestehenden Item Prices dieses
		Artikels in den verwalteten Preislisten werden gelöscht und aus der aktuellen
		WeClapp-Historie neu angelegt. So kann es keine Kollision mit Altbeständen geben
		(z.B. Preise ohne Gültigkeitsdatum aus früheren Läufen -> ItemPriceDuplicateItem).
		Läuft im Datensatz-Savepoint der Engine, ein Fehler rollt nur diesen Artikel zurück.
		"""
		channels = self._channel_lists()
		if not channels:
			return

		groups: dict[tuple, list[dict]] = {}
		for p in record.get("articlePrices") or []:
			ch = p.get("salesChannel")
			if ch not in channels or p.get("price") is None:
				continue
			key = (ch, _to_float(p.get("priceScaleValue"), 0.0), p.get("customerId") or None)
			groups.setdefault(key, []).append(p)

		managed_lists = [pl for pl in set(channels.values()) if pl]

		# Altbestand für diesen Artikel in den verwalteten Listen komplett entfernen.
		for old in frappe.get_all(
			"Item Price",
			filters={"item_code": item_code, "price_list": ["in", managed_lists]},
			pluck="name",
		):
			frappe.delete_doc("Item Price", old, ignore_permissions=True, force=True)

		for (ch, min_qty, cust_id), prices in groups.items():
			price_list = channels[ch]
			if not frappe.db.exists("Price List", price_list):
				continue
			customer = (
				frappe.db.get_value("Customer", {"wc_id": str(cust_id)}, "name") if cust_id else None
			)
			prices.sort(key=lambda p: p.get("startDate") or 0)

			for i, p in enumerate(prices):
				currency = h.link_or_none("Currency", p.get("currencyName")) or h.default_currency()
				valid_from = h.date_from_ts(p.get("startDate"))
				valid_upto = h.date_from_ts(p.get("endDate"))
				# Ende an den Beginn des Folgepreises anschließen (überlappungsfrei).
				if i + 1 < len(prices):
					next_from = h.date_from_ts(prices[i + 1].get("startDate"))
					if next_from:
						cap = _d(add_days(next_from, -1))
						valid_upto = min(valid_upto, cap) if valid_upto else cap
				# Vollständig vom Folgepreis verdeckt -> überspringen.
				if valid_from and valid_upto and valid_upto < valid_from:
					continue

				doc = frappe.new_doc("Item Price")
				doc.update(
					{
						"item_code": item_code,
						"price_list": price_list,
						"currency": currency,
						"selling": 1,
						"min_qty": min_qty,
						"customer": customer,
						"price_list_rate": float(p["price"]),
						"valid_from": valid_from,
						"valid_upto": valid_upto,
					}
				)
				doc.flags.ignore_permissions = True
				doc.insert()


def _to_float(v, default: float) -> float:
	try:
		return float(v)
	except (TypeError, ValueError):
		return default


def _d(v) -> str:
	"""Datum (date/datetime/str/None) -> 'YYYY-MM-DD' bzw. '' - für stabilen Vergleich."""
	if not v:
		return ""
	return str(v)[:10]
