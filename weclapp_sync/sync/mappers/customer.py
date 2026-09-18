"""Kunden-Mapper: WeClapp `customer` -> ERPNext `Customer` (+ Adressen, Kontakte).

Portiert aus reference/migration_logic/full_field_mapping/customer_migration.py, REST -> native
Document-API. Idempotent über das `wc_id`-Custom-Field (setzt auf dem Bestand des alten
Importers auf).

Das `party`-Objekt (customer.id == party.id) wird pro Kunde einmal nachgeladen - es trägt
Felder, die `customer` selbst nicht hat: `customerDebtorAccountNumber` (Personenkonto),
`customerInternalNote`, `salesInvoiceEmailAddressesId`.

Belegart-spezifische E-Mails (Rechnung/Auftrag/Lieferschein/Mahnung/Angebot) aus
`party.partyEmailAddresses`:
- gespeichert in Customer-Feldern `invoice_/order_/delivery_/dunning_/quotation_email`
- Rechnung/Lieferschein zusätzlich auf `Address.email_id` der Rechnungs-/Lieferadresse (Standardfeld)
- auf Sales Invoice/Order, Delivery Note, Quotation, Dunning zieht ein `fetch_from`-Feld
  `wc_belegart_email` die passende Adresse auf den Beleg -> Autoversand per Standard-"Notification"
  möglich, ohne Code (siehe setup/custom_fields.py).
Bankkonten -> ERPNext Bank Account. Personenkonto (Debitorenkonto) je Kunde -> Customer.accounts
(eigenes DATEV-Konto pro Kunde; ~9 von 5838 Kunden haben in WeClapp keine Debitor-Nr. und
landen auf dem Sammelkonto).

Noch NICHT portiert (jeweils eigener Folge-Schritt, siehe CLAUDE.md):
- Dateianhänge AM Kunden/der Partei selbst (WeClapp `document`-Entität für `party`/`customer`) -
  nicht zu verwechseln mit den längst gebauten Beleg-/Artikel-Anhängen (_attachments.py)
- WeClapp-Kommentare ("Kommentare", separater Endpunkt pro party-id) - live geprüft, in den
  echten Daten praktisch ungenutzt (0 von 30 Stichproben), daher niedrige Priorität
- blocked/insolvent -> disabled/is_frozen (Schlussphase apply_wc_blocks)

(Custom Attributes/Zusatzfelder sind entgegen einer älteren Version dieses Docstrings längst
angebunden, siehe `ca.resolve()` unten und `setup/custom_attribute_fields.py`.)
"""

from __future__ import annotations

from typing import Any

import frappe

from weclapp_sync import erpnext_helpers as h
from weclapp_sync.sync.mappers import _custom_attributes as ca
from weclapp_sync.sync.mappers import _party_common as pc
from weclapp_sync.sync.mappers.base import Mapper, guarded_step
from weclapp_sync.sync.settings import get_settings

_PARTY_DOCTYPE = "Customer"


class CustomerMapper(pc.PartyCacheMixin, Mapper):
	target_doctype = "Customer"

	# ------------------------------------------------------------------ Basis
	def should_skip(self, record: dict) -> bool:
		return not (record.get("partyType") and record.get("customerNumber") and _display_name(record))

	def target_name(self, record: dict) -> str | None:
		return record.get("customerNumber") or None

	# `_party()`/`prepare_page()` kommen aus pc.PartyCacheMixin (Bugfix 2026-09-16: gebündelter
	# Sammel-Abruf je Seite statt einem WeClapp-GET pro Kunde, siehe dort).

	def to_doc_fields(self, record: dict, *, existing: Any = None) -> dict[str, Any]:
		settings = get_settings()
		party = self._party(record)
		is_company = record.get("partyType") != "PERSON"
		fields = {
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
			"customer_details": h.join_notes(
				party.get("customerInternalNote"),
				_block_notice(record.get("blockNotice")),
				record.get("description"),
			)
			or None,
			"invoice_email": _purpose_email(party, "salesInvoiceEmailAddressesId"),
			"order_email": _purpose_email(party, "salesOrderEmailAddressesId"),
			"delivery_email": _purpose_email(party, "deliveryEmailAddressesId"),
			"dunning_email": _purpose_email(party, "dunningEmailAddressesId"),
			"quotation_email": _purpose_email(party, "quotationEmailAddressesId"),
			# Payment Terms Template muss existieren (setup_payment_terms-Äquivalent noch TODO) -
			# fehlt es, Feld leer lassen statt den Kunden scheitern zu lassen.
			"payment_terms": h.link_or_none("Payment Terms Template", record.get("termOfPaymentName")),
			"wc_zahlungsart": record.get("paymentMethodName") or None,
			"wc_opt_in_email": 1 if record.get("optIn") else 0,
			"wc_opt_in_letter": 1 if record.get("optInLetter") else 0,
			"wc_opt_in_phone": 1 if record.get("optInPhone") else 0,
			"wc_opt_in_sms": 1 if record.get("optInSms") else 0,
		}
		fields.update(ca.resolve(record, self.custom_attribute_definitions(), self.custom_attribute_field_map()))
		# vi_versandabsender gehört der "ERPNext Versand"-App (Custom Field, steuert Kopfbogen +
		# Absenderadresse auf Versandlabels) - nur befüllen, wenn dort noch nichts steht, damit
		# eine manuelle Korrektur dort nicht bei jedem Sync wieder überschrieben wird. Nutzer-
		# Wunsch 2026-09-18, Herleitung aus WeClapps salesChannel über price_list_mappings.
		if not (existing and existing.get("vi_versandabsender")):
			versandabsender = h.versandabsender_for_channel(record.get("salesChannel"))
			if versandabsender:
				fields["vi_versandabsender"] = versandabsender
		return fields

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

		party = self._party(record)
		purpose_emails = {
			"invoice": _purpose_email(party, "salesInvoiceEmailAddressesId"),
			"delivery": _purpose_email(party, "deliveryEmailAddressesId"),
		}

		# 2) Adressen - ein Fehler bei einer Adresse darf den Kunden nicht scheitern lassen
		#    (eigener Savepoint, damit ein Teil-Write sauber zurückgerollt wird).
		for wc_addr in record.get("addresses") or []:
			res = guarded_step("Address", f"{name}:{wc_addr.get('id')}", lambda a=wc_addr: pc.upsert_address(
				a,
				party_doctype=_PARTY_DOCTYPE,
				party_name=name,
				party_number=number,
				purpose_emails=purpose_emails,
			))
			if res and res["is_primary"]:
				primary_address = res

		# 3) Kontakte
		for wc_contact in record.get("contacts") or []:
			is_primary = record.get("primaryContactId") == wc_contact.get("id")
			res = guarded_step("Contact", f"{name}:{wc_contact.get('id')}", lambda c=wc_contact, p=is_primary: pc.upsert_contact(
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
				primary_contact = guarded_step("Contact", f"{name}:self", lambda: pc.upsert_contact(
					self_data,
					party_doctype=_PARTY_DOCTYPE,
					party_name=name,
					is_primary=True,
					name_suffix=number,
				))

		# 5) Bankkonten
		for wc_ba in record.get("bankAccounts") or []:
			guarded_step("Bank Account", f"{name}:{wc_ba.get('id')}", lambda b=wc_ba: pc.upsert_bank_account(
				b, party_doctype=_PARTY_DOCTYPE, party_name=name, account_type="Kunden-Bankkonto"
			))

		# 6) Personenkonto (Debitorenkonto) - party.customerDebtorAccountNumber
		party = self._party(record)
		debtor_number = party.get("customerDebtorAccountNumber")
		if debtor_number:
			label = (party.get("company") or display_name).strip()
			account_name = guarded_step("Account", f"{name}:{debtor_number}", lambda: h.ensure_personal_account(
				number=debtor_number,
				label=label,
				account_type="Receivable",
				currency=record.get("currencyName"),
			))
			if account_name:
				cust = frappe.get_doc("Customer", name)
				if not any(r.account == account_name for r in cust.get("accounts", [])):
					cust.append("accounts", {"company": get_settings().company, "account": account_name})
					cust.flags.ignore_permissions = True
					cust.save()

		# 7) Primär-Verknüpfungen + Territory aus Primäradresse
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


_display_name = pc.display_name
_block_notice = pc.block_notice
_purpose_email = pc.purpose_email
