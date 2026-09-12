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
- Mengenstaffeln (`priceScaleValue` > 1): ERPNext "Item Price" hat kein `min_qty` (Staffeln
  laufen über Pricing Rules). Fehlt das Feld, werden nur Basispreise übernommen.
- Bezugsquellen (`supplySources` -> Item Supplier / item_defaults.default_supplier / Einkaufspreis)
  - `articleSupplySource` hat 87k Einträge, muss pro Artikel gefiltert nachgeladen werden.
- Artikelbilder (WeClapp-Cache, hier nicht vorhanden)

Item Tax Template: das NATIVE `Item.taxes` bleibt bewusst IMMER leer (explizit `[]`
geschrieben). Steuer wird pro Belegzeile exakt aus WeClapp als "Actual"-Zeile gebucht,
unabhängig vom Artikel-Default.
**2026-09-11: kurzzeitig aus `taxRateType` in `Item.taxes` gesetzt (für künftige, von Hand
angelegte Belege nach Live-Umstellung), aber SOFORT zurückgerollt** - reproduziert exakt den vom
Vorgänger dokumentierten "Item-Steuer-Template-Konflikt": ERPNext vergleicht bei jedem Speichern
den vom Template erwarteten Steuerbetrag mit unseren Actual-Zeilen und lehnt jeden Beleg ab,
dessen Artikel historisch zu einem anderen Satz verkauft wurde (46 Angebote + 506 Aufträge live
gescheitert). Das ist KEIN migrationsspezifisches Problem, sondern dauerhaft (das
Actual-Zeilen-Buchen bleibt permanent), daher auch keine "erst nach Live-Umstellung wieder
gesetzt"-Lösung möglich.
**2026-09-12: sauber gelöst über ein GETRENNTES, rein informatives Custom Field**
(`custom_default_item_tax_template`, siehe setup/custom_fields.py) statt des nativen
`Item.taxes`. `_default_item_tax_template()` befüllt nur dieses Feld aus `taxRateType`. Ein
Client Script (`setup/item_tax_hint.py`) liest es beim manuellen Anlegen einer Belegzeile im
Browser aus und schlägt den Zeilen-Steuersatz vor. Der Sync selbst läuft serverseitig in Python
und triggert nie ein Client Script - importierte/synctierte Belege bleiben unberührt.

**Set-/Bundle-Artikel** (`articleType == "SALES_BILL_OF_MATERIAL"`, WeClapps "Stückliste" im
Verkaufssinn - keine Fertigungs-Stückliste, kein Lagerabgang der Komponenten): 69 Stück live.
`_sync_product_bundle()` bildet `salesBillOfMaterialItems` auf ERPNexts **Product Bundle** ab
(genau das ERPNext-Äquivalent: nicht-lagerhaltiger Verkaufsartikel, der beim Beleg-Erfassen zu
seinen Bestandteilen "explodiert" - keine eigene Buchung). Komponenten über `resolve_line_item()`
aufgelöst (Stub-Anlage, falls eine Komponente in der Iterationsreihenfolge des Artikel-Vollimports
noch nicht drankam - wie bei Belegzeilen, ein späterer Durchlauf/Re-Run vervollständigt sie).
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import add_days

from weclapp_sync.sync.mappers._transaction import _line_title, resolve_line_item

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
			"barcodes": self._barcodes(record),
			# Explizit LEER, nicht weggelassen - räumt das Item Tax Template wieder ab, das der
			# kurzzeitige Fix vom 2026-09-11 gesetzt hatte (Regression, siehe Moduldocstring).
			# Ohne das explizite [] bliebe ein einmal gesetztes Template stehen, weil ein
			# fehlender Dict-Key beim Sync die bestehende Kindtabelle nicht anfasst.
			"taxes": [],
			# Rein informativ, siehe Moduldocstring 2026-09-12 - beeinflusst den Sync nicht.
			"custom_default_item_tax_template": self._default_item_tax_template(record),
		}
		# description/item_group nur bei Neuanlage - können später von anderen Integrationen
		# (Shopware) mitgepflegt werden (siehe reference article_migration.py).
		if is_new:
			fields["description"] = record.get("description") or record.get("name")
			fields["item_group"] = h.ensure_item_group(self._category_name(record))

		fields.update(ca.resolve(record, self.custom_attribute_definitions(), self.custom_attribute_field_map()))
		return fields

	# WeClapp article.taxRateType -> Basis-Name des passenden ERPNext Item Tax Template
	# (Company-Abbr wird angehängt: "19 % - FT").
	_TAX_RATE_TEMPLATES = {"STANDARD": "19 %", "REDUCED": "7 %"}

	@classmethod
	def _default_item_tax_template(cls, record: dict) -> str | None:
		"""Nur ein UI-Vorschlag (Custom Field `custom_default_item_tax_template`, siehe
		setup/custom_fields.py + setup/item_tax_hint.py) für künftige, von Hand angelegte Belege -
		NICHT das native `Item.taxes`, das für den Sync leer bleiben muss (siehe Moduldocstring)."""
		base = cls._TAX_RATE_TEMPLATES.get(record.get("taxRateType"))
		if not base:
			return None
		abbr = h.company_abbr()
		name = f"{base} - {abbr}" if abbr else base
		return name if frappe.db.exists("Item Tax Template", name) else None

	@staticmethod
	def _barcodes(record: dict) -> list[dict]:
		"""EAN als Item Barcode - aber nur, wenn er nicht schon einem ANDEREN Artikel gehört.
		ERPNext erzwingt Barcode-Eindeutigkeit; in WeClapp teilen sich vereinzelt mehrere
		Artikel eine EAN (Varianten/Sets). Der erste Artikel bekommt den Barcode, die anderen
		laufen ohne - besser als der Abbruch des ganzen Artikel-Upserts."""
		ean = record.get("ean")
		if not ean:
			return []
		owner = frappe.db.get_value("Item Barcode", {"barcode": ean}, "parent")
		if owner and owner != record.get("articleNumber"):
			return []
		return [{"barcode": ean}]

	def _channel_lists(self) -> dict:
		if self._price_lists is None:
			self._price_lists = price_list_mapping()
		return self._price_lists

	def upsert(self, record: dict) -> str | None:
		name = super().upsert(record)
		if not name:
			return None
		self._sync_prices(name, record)
		self._sync_product_bundle(name, record)
		return name

	def _sync_product_bundle(self, item_code: str, record: dict) -> None:
		"""WeClapp "Sales Bill of Material" (Set-/Bundle-Artikel) -> ERPNext "Product Bundle".
		Siehe Moduldocstring. No-op für alle anderen Artikeltypen."""
		sub_items = record.get("salesBillOfMaterialItems") or []
		if record.get("articleType") != "SALES_BILL_OF_MATERIAL" or not sub_items:
			return

		rows: list[dict] = []
		for sub in sorted(sub_items, key=lambda s: s.get("positionNumber") or 0):
			component = resolve_line_item(sub, _line_title(sub))
			if component == item_code:
				continue  # Sicherheitsnetz gegen Ringschluss (Artikel als eigene Komponente)
			rows.append({"item_code": component, "qty": float(sub.get("quantity") or 0) or 1.0})
		if not rows:
			return

		exists = frappe.db.exists("Product Bundle", item_code)
		doc = frappe.get_doc("Product Bundle", item_code) if exists else frappe.new_doc("Product Bundle")
		if not exists:
			doc.new_item_code = item_code
		doc.set("items", rows)
		doc.flags.ignore_permissions = True
		if exists:
			doc.save()
		else:
			doc.insert()

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

		# ERPNext "Item Price" hat je nach Version kein `min_qty` (Mengenstaffeln laufen dort
		# über Pricing Rules). Wenn das Feld fehlt: nur Basispreise (priceScaleValue <= 1)
		# übernehmen - Staffelpreise sind ein Folge-Schritt (wie im Vorgänger-Importer).
		has_min_qty = frappe.get_meta("Item Price").has_field("min_qty")

		groups: dict[tuple, list[dict]] = {}
		for p in record.get("articlePrices") or []:
			ch = p.get("salesChannel")
			if ch not in channels or p.get("price") is None:
				continue
			scale = _to_float(p.get("priceScaleValue"), 1.0) or 1.0
			if not has_min_qty and scale > 1:
				continue
			key = (ch, scale, p.get("customerId") or None)
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
			seen_from: set[str] = set()

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
				# WeClapp lässt `startDate` oft leer ("schon immer gültig"). ERPNext behandelt
				# ein leeres `valid_from` bei gesetztem `valid_upto` als HEUTE -> InvalidDates.
				# Deshalb auf einen frühen Stichtag setzen.
				if valid_upto and not valid_from:
					valid_from = "2000-01-01"
				# Vom Folgepreis (fast) vollständig verdeckt -> überspringen. ERPNext verlangt
				# valid_upto STRIKT nach valid_from, daher auch Gleichstand auslassen.
				if valid_from and valid_upto and valid_upto <= valid_from:
					continue
				# Doppelte Gültigkeit im selben Kanal/Kunde -> ItemPriceDuplicateItem vermeiden.
				if (valid_from or "") in seen_from:
					continue
				seen_from.add(valid_from or "")

				fields = {
					"item_code": item_code,
					"price_list": price_list,
					"currency": currency,
					"selling": 1,
					"customer": customer,
					"price_list_rate": float(p["price"]),
					"valid_from": valid_from,
					"valid_upto": valid_upto,
				}
				if has_min_qty:
					fields["min_qty"] = min_qty
				doc = frappe.new_doc("Item Price")
				doc.update(fields)
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
