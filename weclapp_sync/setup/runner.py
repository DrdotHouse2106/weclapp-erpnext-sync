"""Idempotenter Setup-Vorlauf: Struktur/Stammdaten, die vor der eigentlichen Datensatz-
Synchronisation existieren müssen.

Aufgerufen von:
- weclapp_sync/install.py (after_install)
- hooks.after_migrate
- engine.run_full_import() als Vorlauf

Portierung des relevanten Teils von reference/setup.py. **Noch unvollständig** - bisher nur
Custom Fields + Naming. Es fehlen die datenintensiveren setup_*()-Äquivalente (Konten, Lager,
Geschäftsjahre, Zahlungsbedingungen, Personenkonten, Artikelgruppen, ...) - siehe CLAUDE.md.
"""

from __future__ import annotations

import frappe

from weclapp_sync.setup.custom_fields import apply_custom_fields
from weclapp_sync.setup.naming import apply_naming
from weclapp_sync.setup.precision import apply_precision


def run_setup(*, full: bool = False) -> None:
	"""`full=False`: nur das, was für jede Installation/Migration nötig ist (Felder, Naming).
	`full=True`: zusätzlich die Stammdaten-/Struktur-Anlage für den Vollimport (noch TODO)."""
	apply_custom_fields()
	apply_naming()
	apply_precision()

	from weclapp_sync.setup import masters

	# Immer (auch ohne Vollimport): ERPNext darf aus Belegen keine Item Prices auto-anlegen.
	try:
		masters.setup_pricing_settings()
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		frappe.log_error(title="WeClapp Setup: setup_pricing_settings", message=frappe.get_traceback())

	if full:
		for step in (masters.setup_uom_settings, masters.setup_payment_terms, masters.setup_fiscal_years):
			try:
				step()
				frappe.db.commit()
			except Exception:
				frappe.db.rollback()
				frappe.log_error(title=f"WeClapp Setup: {step.__name__}", message=frappe.get_traceback())
		# TODO(setup): setup_warehouses, setup_accounts, setup_bank_accounts, Kostenstellen,
		# Steuer-Templates (instanzspezifisch - auf der Zielinstanz meist schon vorhanden).

	frappe.db.commit()
