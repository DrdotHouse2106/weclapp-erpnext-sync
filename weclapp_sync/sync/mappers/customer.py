"""Kunden-Mapper: WeClapp `customer` -> ERPNext `Customer`.

Portiert aus reference/migration_logic/full_field_mapping/customer_migration.py, REST -> native
Document-API. **Bewusst noch reduziert auf das Kern-Customer-Dokument.**

Noch NICHT portiert (jeweils eigener Folge-Schritt, siehe CLAUDE.md):
- Adressen (AddressMigration) + customer_primary_address + territory aus Primäradresse
- Kontakte (ContactMigration) + customer_primary_contact + "self"-Kontakt-Fallback für
  E-Mail/Telefon (betrifft im Altbestand ~4200 von ~5700 Kunden!)
- Bankkonten (BankAccountMigration)
- Personenkonto / Debitorenkonto (party.customerDebtorAccountNumber -> Customer.accounts) -
  braucht setup_personal_accounts-Äquivalent
- Custom Attributes (Zusatzfelder) - braucht customAttributeDefinition-Abruf
- WeClapp-Dokumente (Anhänge) hochladen
- Interne Notiz aus dem `party`-Objekt + `blockNotice` + Kommentare (nur `description` ist hier
  ohne Zusatz-API-Aufrufe verfügbar)
"""

from __future__ import annotations

from typing import Any

from weclapp_sync import erpnext_helpers as h
from weclapp_sync.sync.mappers.base import Mapper
from weclapp_sync.sync.settings import get_settings


class CustomerMapper(Mapper):
	target_doctype = "Customer"

	def should_skip(self, record: dict) -> bool:
		# PERSON-Parteien haben kein "company"; irgendein brauchbarer Name reicht.
		return not (record.get("partyType") and record.get("customerNumber") and _display_name(record))

	def target_name(self, record: dict) -> str | None:
		return record.get("customerNumber") or None

	def to_doc_fields(self, record: dict, *, existing: Any = None) -> dict[str, Any]:
		settings = get_settings()
		is_company = record.get("partyType") != "PERSON"

		fields: dict[str, Any] = {
			"customer_name": _display_name(record),
			"customer_type": "Company" if is_company else "Individual",
			"customer_group": (
				settings.default_customer_group_company
				if is_company
				else settings.default_customer_group_individual
			)
			or None,
			"website": record.get("website") or None,
			"tax_id": record.get("vatRegistrationNumber") or None,
			"default_currency": record.get("currencyName") or None,
			# Immer aktiviert importieren - ERPNext lehnt Belege für deaktivierte Parteien ab.
			# WeClapps blocked/insolvent-Flags werden separat in einer Schlussphase angewandt (TODO).
			"disabled": 0,
			"is_frozen": 0,
			# ERPNexts natives Klartext-Feld. Ohne Zusatz-API-Aufrufe nur die "description".
			"customer_details": h.join_notes(record.get("description")) or None,
			"payment_terms": (record.get("termOfPaymentName") or "").strip() or None,
			"wc_zahlungsart": record.get("paymentMethodName") or None,
			"wc_opt_in_email": 1 if record.get("optIn") else 0,
			"wc_opt_in_letter": 1 if record.get("optInLetter") else 0,
			"wc_opt_in_phone": 1 if record.get("optInPhone") else 0,
			"wc_opt_in_sms": 1 if record.get("optInSms") else 0,
		}
		return fields


def _display_name(record: dict) -> str:
	if record.get("partyType") != "PERSON":
		return (record.get("company") or "").strip()
	return f"{record.get('firstName') or ''} {record.get('lastName') or ''}".strip()
