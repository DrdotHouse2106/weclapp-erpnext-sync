"""Stammdaten-/Struktur-Anlage für den Vollimport (`run_setup(full=True)`).

Portiert aus reference/setup.py. Läuft gegen die WeClapp-API (read-only) statt gegen einen
lokalen Cache. Idempotent - vorhandene Datensätze werden übersprungen.

Noch NICHT portiert (instanzspezifisch / bereits vorhanden auf der Zielinstanz):
setup_warehouses, setup_accounts, setup_bank_accounts, Kostenstellen, Steuer-Templates.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import frappe
from frappe.utils import now_datetime

from weclapp_sync.sync.settings import get_client

MIGRATION_PAYMENT_TERMS_TEMPLATE = "Migration - unbegrenzt"

# Epoch-ms für 2000-01-01 UTC - als Server-seitiger Mindestfilter beim Ermitteln des frühesten
# Belegdatums, damit WeClapp-Datumstippfehler (z.B. Jahr "0022" statt "2022", live gesehen bei
# salesInvoice) gar nicht erst als "früheste Zeile" zurückkommen (siehe setup_fiscal_years()).
_EPOCH_2000_MS = 946_684_800_000


# --------------------------------------------------------------------------- Payment Terms
def _parse_wc_payment_term(name: str) -> dict:
	"""WeClapp-Zahlungsziel-Kürzel -> eine Payment Terms Template Detail-Zeile.
	Portiert aus reference/setup.py `_parse_wc_payment_term`."""
	stripped = name.strip()
	m = re.match(r"^(\d+)/(\d+),?\s*net\s+(\d+)$", stripped, re.IGNORECASE)
	if m:
		discount, validity, credit_days = int(m.group(1)), int(m.group(2)), int(m.group(3))
		return {
			"invoice_portion": 100,
			"due_date_based_on": "Day(s) after invoice date",
			"credit_days": credit_days,
			"discount_type": "Percentage",
			"discount": discount,
			"discount_validity_based_on": "Day(s) after invoice date",
			"discount_validity": validity,
			"description": stripped,
		}
	m = re.match(r"^net\s+(\d+)$", stripped, re.IGNORECASE)
	if m:
		return {
			"invoice_portion": 100,
			"due_date_based_on": "Day(s) after invoice date",
			"credit_days": int(m.group(1)),
			"description": stripped,
		}
	# "net sofort" und alles Unbekannte -> sofort fällig, Rohtext als Beschreibung.
	return {
		"invoice_portion": 100,
		"due_date_based_on": "Day(s) after invoice date",
		"credit_days": 0,
		"description": stripped,
	}


def setup_payment_terms() -> None:
	client = get_client()
	client.open()
	try:
		names: set[str] = set()
		for entity in ("customer", "supplier"):
			for row in client.iter_all(entity, properties="id,termOfPaymentName"):
				if row.get("termOfPaymentName"):
					names.add(row["termOfPaymentName"].strip())
	finally:
		client.close()

	for name in sorted(names):
		if frappe.db.exists("Payment Terms Template", name):
			continue
		try:
			doc = frappe.new_doc("Payment Terms Template")
			doc.template_name = name
			doc.append("terms", _parse_wc_payment_term(name))
			doc.flags.ignore_permissions = True
			doc.insert()
		except Exception:
			frappe.log_error(title=f"WeClapp Setup: Payment Terms Template '{name}'", message=frappe.get_traceback())

	# Dummy-Template mit sehr hoher Kreditzeit - wird auf jede migrierte Rechnung gesetzt,
	# damit ERPNexts set_missing_values() nicht das echte Kundentemplate zieht und historische
	# Fälligkeitsdaten ablehnt (siehe reference/setup.py setup_migration_payment_terms_template).
	if not frappe.db.exists("Payment Terms Template", MIGRATION_PAYMENT_TERMS_TEMPLATE):
		doc = frappe.new_doc("Payment Terms Template")
		doc.template_name = MIGRATION_PAYMENT_TERMS_TEMPLATE
		doc.append(
			"terms",
			{"invoice_portion": 100, "due_date_based_on": "Day(s) after invoice date", "credit_days": 36500},
		)
		doc.flags.ignore_permissions = True
		doc.insert()


# --------------------------------------------------------------------------- Fiscal Years
def setup_fiscal_years() -> None:
	"""Legt Geschäftsjahre vom frühesten WeClapp-Belegdatum bis nächstes Jahr an - ERPNext
	lehnt Belege außerhalb eines Fiscal Year ab (FiscalYearError).

	**Bugfix 2026-09-15:** fehlende `purchaseInvoice`/`purchaseOrder` - Einkaufsbelege können
	deutlich älter sein als das früheste Verkaufsdokument (live: Eingangsrechnungen von 2020 und
	2022, während das früheste Verkaufsdatum jünger war). Ohne die beiden hier blieben 2020/2022
	ohne Fiscal-Year-Datensatz -> `FiscalYearError` beim Import dieser Eingangsrechnungen (8
	Fehlschläge im ersten vollständigen Lauf mit diesem Zeitrahmen).

	**Bugfix 2026-09-16:** die "früheste Zeile" (page_size=1, sortiert) kann selbst ein
	WeClapp-Datumstippfehler sein - live: `salesInvoice` sortiert nach `invoiceDate` liefert als
	erste Zeile einen Beleg mit Jahr **0022** (`clamp_posting_date()` fängt sowas beim Sync ab,
	hier lief das ungefiltert rein und lieferte für die ganze Entität `None`). Jetzt serverseitig
	mit `{feld}-ge=<2000-01-01>` gefiltert (WeClapp `-ge` bestätigt nutzbar) - Tippfehler-Zeilen
	fallen dadurch schon auf WeClapp-Seite raus, keine Nachbearbeitung nötig. Zusätzlich
	`shipment`/`warehouseStockMovement` aufgenommen (auch Belegdaten mit potenziell älteren
	Zeiträumen)."""
	client = get_client()
	client.open()
	earliest = None
	try:
		for entity, field in (
			("salesInvoice", "invoiceDate"),
			("salesOrder", "orderDate"),
			("quotation", "quotationDate"),
			("purchaseInvoice", "invoiceDate"),
			("purchaseOrder", "orderDate"),
			("shipment", "shippingDate"),
			("warehouseStockMovement", "postingDate"),
		):
			try:
				rows = next(
					client.iter_pages(
						entity,
						sort=field,
						properties=f"id,{field}",
						page_size=1,
						filters={f"{field}-ge": _EPOCH_2000_MS},
					),
					[],
				)
			except Exception:
				rows = []
			if rows and rows[0].get(field):
				year = _year_from_ms(rows[0][field])
				if year and (earliest is None or year < earliest):
					earliest = year
	finally:
		client.close()

	start = earliest or (now_datetime().year - 1)
	end = now_datetime().year + 1
	for year in range(start, end + 1):
		if frappe.db.exists("Fiscal Year", str(year)):
			continue
		try:
			doc = frappe.new_doc("Fiscal Year")
			doc.year = str(year)
			doc.year_start_date = f"{year}-01-01"
			doc.year_end_date = f"{year}-12-31"
			doc.flags.ignore_permissions = True
			doc.insert()
		except Exception:
			frappe.log_error(title=f"WeClapp Setup: Fiscal Year {year}", message=frappe.get_traceback())


def _year_from_ms(ms) -> int | None:
	"""**Bugfix 2026-09-16:** die alte Näherung (`1970 + sekunden/31557600`) rundet nahe
	Jahresgrenzen falsch (2020-01-01 wurde zu 2019) - harmlos (ein Geschäftsjahr zu viel), aber
	unnötig ungenau. `datetime.fromtimestamp` mit UTC ist exakt und genauso billig."""
	try:
		year = datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).year
		return year if 2000 <= year <= 2100 else None
	except (TypeError, ValueError, OverflowError, OSError):
		return None


# --------------------------------------------------------------------------- UOM
def setup_uom_settings() -> None:
	""""Nos" darf gebrochene Mengen haben - WeClapp erzwingt keine ganzzahligen Stückzahlen."""
	if frappe.db.exists("UOM", "Nos"):
		frappe.db.set_value("UOM", "Nos", "must_be_whole_number", 0)


def setup_pricing_settings() -> None:
	"""WeClapp ist die Preis-Autorität. ERPNext soll aus importierten Belegen KEINE Item Prices
	auto-anlegen (`auto_insert_price_list_rate_if_missing`) - sonst legt jede Belegzeile ohne
	vorhandene Item Price eine in der Beleg-Preisliste an, die beim nächsten Lauf den aus
	WeClapp übergebenen Zeilenpreis überschreibt."""
	stock_settings = frappe.get_single("Stock Settings")
	changed = False
	for field, value in (
		("auto_insert_price_list_rate_if_missing", 0),
		("update_existing_price_list_rate", 0),
	):
		if stock_settings.get(field) != value:
			stock_settings.set(field, value)
			changed = True
	if changed:
		stock_settings.flags.ignore_permissions = True
		stock_settings.save()

	# WeClapp-Belege haben legitim negative Zeilen (Reduktions-/Ausgleichspositionen,
	# Gutschriften). ERPNext lehnt negative Einzelpreise sonst ab.
	for dt in ("Selling Settings", "Buying Settings"):
		doc = frappe.get_single(dt)
		if doc.meta.has_field("allow_negative_rates_for_items") and not doc.get(
			"allow_negative_rates_for_items"
		):
			doc.allow_negative_rates_for_items = 1
			doc.flags.ignore_permissions = True
			doc.save()
