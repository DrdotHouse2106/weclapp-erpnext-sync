"""Stammdaten-/Struktur-Anlage für den Vollimport (`run_setup(full=True)`).

Portiert aus reference/setup.py. Läuft gegen die WeClapp-API (read-only) statt gegen einen
lokalen Cache. Idempotent - vorhandene Datensätze werden übersprungen.

Noch NICHT portiert (instanzspezifisch / bereits vorhanden auf der Zielinstanz):
setup_warehouses, setup_accounts, setup_bank_accounts, Kostenstellen, Steuer-Templates.
"""

from __future__ import annotations

import re

import frappe
from frappe.utils import now_datetime

from weclapp_sync.sync.settings import get_client

MIGRATION_PAYMENT_TERMS_TEMPLATE = "Migration - unbegrenzt"


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
	lehnt Belege außerhalb eines Fiscal Year ab (FiscalYearError)."""
	client = get_client()
	client.open()
	earliest = None
	try:
		for entity, field in (("salesInvoice", "invoiceDate"), ("salesOrder", "orderDate"), ("quotation", "quotationDate")):
			try:
				rows = next(
					client.iter_pages(entity, sort=field, properties=f"id,{field}", page_size=1), []
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
	try:
		year = 1970 + int(int(ms) / 1000 / 31_557_600)
		return year if 2000 <= year <= 2100 else None
	except (TypeError, ValueError):
		return None


# --------------------------------------------------------------------------- UOM
def setup_uom_settings() -> None:
	""""Nos" darf gebrochene Mengen haben - WeClapp erzwingt keine ganzzahligen Stückzahlen."""
	if frappe.db.exists("UOM", "Nos"):
		frappe.db.set_value("UOM", "Nos", "must_be_whole_number", 0)
