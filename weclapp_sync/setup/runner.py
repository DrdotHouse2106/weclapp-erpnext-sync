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


def run_setup(*, full: bool = False) -> None:
	"""`full=False`: nur das, was für jede Installation/Migration nötig ist (Felder, Naming).
	`full=True`: zusätzlich die Stammdaten-/Struktur-Anlage für den Vollimport (noch TODO)."""
	apply_custom_fields()
	apply_naming()

	if full:
		# TODO(setup): setup_item_groups, setup_warehouses, setup_fiscal_years,
		# setup_payment_terms, setup_personal_accounts, setup_bank_accounts, setup_accounts,
		# setup_manufacturers, setup_free_text_item, setup_negative_rate_settings,
		# setup_uom_settings  (aus reference/setup.py).
		pass

	frappe.db.commit()
