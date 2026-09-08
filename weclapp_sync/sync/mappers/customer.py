"""Kunden-Mapper: WeClapp `customer` -> ERPNext `Customer` (+ Adressen, Kontakte).

Portiert aus reference/migration_logic/full_field_mapping/customer_migration.py, REST -> native
Document-API. Idempotent über das `wc_id`-Custom-Field (setzt auf dem Bestand des alten
Importers auf).

Noch NICHT portiert (jeweils eigener Folge-Schritt, siehe CLAUDE.md):
- Bankkonten (BankAccountMigration)
- Personenkonto / Debitorenkonto (party.customerDebtorAccountNumber -> Customer.accounts) -
  braucht das setup_personal_accounts-Äquivalent
- Custom Attributes (Zusatzfelder) - braucht customAttributeDefinition-Abruf
- WeClapp-Dokumente (Anhänge) hochladen
- Interne Notiz aus dem `party`-Objekt + `blockNotice` + Kommentare (nur `description` ist
  ohne Zusatz-API-Aufrufe verfügbar)
- Rechnungs-E-Mail-Override (party.salesInvoiceEmailAddressesId)
"""

from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any

import frappe

from weclapp_sync import erpnext_helpers as h
from weclapp_sync.sync.mappers import _party_common as pc
from weclapp_sync.sync.mappers.base import Mapper
from weclapp_sync.sync.settings import get_settings

_PARTY_DOCTYPE = "Customer"


def _guarded(child_doctype: str, party_name: str, wc_obj: dict, fn: Callable[[], Any]) -> Any:
	"""Führt eine Sub-Entitäts-Upsert-Funktion in einem eigenen Savepoint aus. Bei Fehler:
	Rollback nur dieses Teils + Log, Rückgabe None - der Kunde selbst bleibt erhalten."""
	sp = f"wcsub_{abs(hash((child_doctype, str(wc_obj.get('id')))))}"
	frappe.db.savepoint(sp)
	try:
		return fn()
	except Exception:
		frappe.db.rollback(save_point=sp)
		frappe.log_error(
			title=f"WeClapp Sync: {child_doctype} für {party_name} fehlgeschlagen",
			message=f"WeClapp {child_doctype} id={wc_obj.get('id')}\n\n{traceback.format_exc()}",
		)
		return None


class CustomerMapper(Mapper):
	target_doctype = "Customer"

	# ------------------------------------------------------------------ Basis
	def should_skip(self, record: dict) -> bool:
		return not (record.get("partyType") and record.get("customerNumber") and _display_name(record))

	def target_name(self, record: dict) -> str | None:
		return record.get("customerNumber") or None

	def to_doc_fields(self, record: dict, *, existing: Any = None) -> dict[str, Any]:
		settings = get_settings()
		is_company = record.get("partyType") != "PERSON"
		return {
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
			"default_currency": h.link_or_none("Currency", record.get("currencyName")),
			"disabled": 0,
			"is_frozen": 0,
			"customer_details": h.join_notes(record.get("description")) or None,
			# Payment Terms Template muss existieren (setup_payment_terms-Äquivalent noch TODO) -
			# fehlt es, Feld leer lassen statt den Kunden scheitern zu lassen.
			"payment_terms": h.link_or_none("Payment Terms Template", record.get("termOfPaymentName")),
			"wc_zahlungsart": record.get("paymentMethodName") or None,
			"wc_opt_in_email": 1 if record.get("optIn") else 0,
			"wc_opt_in_letter": 1 if record.get("optInLetter") else 0,
			"wc_opt_in_phone": 1 if record.get("optInPhone") else 0,
			"wc_opt_in_sms": 1 if record.get("optInSms") else 0,
		}

	# ------------------------------------------------------------------ voller Graph
	def upsert(self, record: dict) -> str | None:
		if self.should_skip(record):
			return None
		number = record.get("customerNumber")
		is_company = record.get("partyType") != "PERSON"
		display_name = _display_name(record)

		# 1) Customer-Kerndokument (nutzt die Basis-Logik: wc_id-Abgleich, Namenszwang).
		name = super().upsert(record)
		if not name:
			return None

		primary_address = None
		primary_contact = None
		first_contact = None

		# 2) Adressen - ein Fehler bei einer Adresse darf den Kunden nicht scheitern lassen
		#    (eigener Savepoint, damit ein Teil-Write sauber zurückgerollt wird).
		for wc_addr in record.get("addresses") or []:
			res = _guarded("Address", name, wc_addr, lambda a=wc_addr: pc.upsert_address(
				a, party_doctype=_PARTY_DOCTYPE, party_name=name, party_number=number
			))
			if res and res["is_primary"]:
				primary_address = res

		# 3) Kontakte
		for wc_contact in record.get("contacts") or []:
			is_primary = record.get("primaryContactId") == wc_contact.get("id")
			res = _guarded("Contact", name, wc_contact, lambda c=wc_contact, p=is_primary: pc.upsert_contact(
				c, party_doctype=_PARTY_DOCTYPE, party_name=name, is_primary=p
			))
			if not res:
				continue
			first_contact = first_contact or res
			if res["is_primary"]:
				primary_contact = res
		primary_contact = primary_contact or first_contact

		# 4) "self"-Kontakt-Fallback (E-Mail/Telefon der Partei selbst) - nur wenn oben nichts
		#    Primäres kam. Im Altbestand für ~4200/5700 Kunden der einzige Weg, wie E-Mail/
		#    Telefon überhaupt am Customer landen (email_id/mobile_no sind read-only, fetched
		#    from customer_primary_contact).
		if primary_contact is None:
			self_data = pc.build_self_contact(record, display_name, is_company)
			if self_data:
				primary_contact = _guarded("Contact", name, self_data, lambda: pc.upsert_contact(
					self_data,
					party_doctype=_PARTY_DOCTYPE,
					party_name=name,
					is_primary=True,
					name_suffix=number,
				))

		# 5) Primär-Verknüpfungen + Territory aus Primäradresse
		updates: dict[str, Any] = {}
		if primary_address:
			updates["customer_primary_address"] = primary_address["name"]
			territory = h.territory_for_country(primary_address["country"])
			if territory:
				updates["territory"] = territory
		if primary_contact:
			updates["customer_primary_contact"] = primary_contact["name"]
			# Flag am gewählten Primärkontakt setzen (kam er über den first_contact-Fallback,
			# ist is_primary_contact dort noch 0).
			if not frappe.db.get_value("Contact", primary_contact["name"], "is_primary_contact"):
				frappe.db.set_value(
					"Contact", primary_contact["name"], "is_primary_contact", 1, update_modified=False
				)
		if updates:
			frappe.db.set_value("Customer", name, updates, update_modified=False)

		return name


def _display_name(record: dict) -> str:
	if record.get("partyType") != "PERSON":
		return (record.get("company") or "").strip()
	return f"{record.get('firstName') or ''} {record.get('lastName') or ''}".strip()
