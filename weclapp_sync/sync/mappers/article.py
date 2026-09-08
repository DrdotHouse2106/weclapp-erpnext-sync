"""Artikel-Mapper: WeClapp `article` -> ERPNext `Item`.

Portiert aus reference/.../article_migration.py. Kern-Item + Barcode + Hersteller + Artikelgruppe
+ Zusatzfelder + ein Verkaufspreis (erster allgemeiner WeClapp-Preis).

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
from weclapp_sync.sync.settings import get_settings


class ArticleMapper(Mapper):
	target_doctype = "Item"

	def __init__(self) -> None:
		super().__init__()
		self._categories: dict | None = None

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

	def upsert(self, record: dict) -> str | None:
		name = super().upsert(record)
		if not name:
			return None
		self._sync_selling_price(name, record)
		return name

	def _sync_selling_price(self, item_code: str, record: dict) -> None:
		"""Erster allgemeiner (nicht kundenspezifischer) WeClapp-Preis -> ERPNext Item Price
		in der Standard-Verkaufspreisliste. Idempotent über (item, price_list, currency, selling)."""
		general = [p for p in record.get("articlePrices") or [] if p.get("customerId") is None]
		if not general:
			return
		p = general[0]
		rate = p.get("price")
		if rate is None:
			return
		price_list = get_settings().default_selling_price_list or "Standard Selling"
		currency = h.link_or_none("Currency", p.get("currencyName")) or h.default_currency()
		if not frappe.db.exists("Price List", price_list):
			return

		existing = frappe.db.exists(
			"Item Price",
			{"item_code": item_code, "price_list": price_list, "currency": currency, "selling": 1},
		)
		doc = frappe.get_doc("Item Price", existing) if existing else frappe.new_doc("Item Price")
		doc.update(
			{
				"item_code": item_code,
				"price_list": price_list,
				"currency": currency,
				"selling": 1,
				"price_list_rate": float(rate),
			}
		)
		doc.flags.ignore_permissions = True
		doc.save() if existing else doc.insert()
