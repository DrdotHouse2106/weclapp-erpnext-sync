"""Gemeinsame Bausteine für Parteien (Kunde/Lieferant): Adressen, Kontakte, Dynamic Links.

Portiert aus reference/migration_logic/full_field_mapping/{address,contact}_migration.py.
WeClapp ist Quelle der Wahrheit - bestehende Adressen/Kontakte werden über ihr `wc_id`-
Custom-Field gefunden und aktualisiert (inkl. Neuaufbau der E-Mail-/Telefon-Child-Tabellen),
nicht gedoppelt.
"""

from __future__ import annotations

from typing import Any

import frappe

from weclapp_sync import erpnext_helpers as h

# WeClapp salutation -> ERPNext Salutation. Nur MR/MRS haben eine saubere Entsprechung
# (siehe reference/contact_migration.py); alles andere bleibt bewusst None.
_SALUTATION_MAP = {"MR": "Mr", "MRS": "Mrs"}


def display_name(record: dict) -> str:
	"""WeClapp-Anzeigename: Firma bei ORGANIZATION, sonst Vor-/Nachname."""
	if record.get("partyType") != "PERSON":
		return (record.get("company") or "").strip()
	return f"{record.get('firstName') or ''} {record.get('lastName') or ''}".strip()


def block_notice(value: str | None) -> str | None:
	value = (value or "").strip()
	return f"Sperrgrund: {value}" if value else None


def purpose_email(party: dict, purpose_field: str) -> str | None:
	"""Löst eine belegart-spezifische E-Mail-Adresse auf (party.<purpose>EmailAddressesId ->
	partyEmailAddresses[].toAddresses). WeClapp führt getrennte Adressen für Rechnung,
	Auftragsbestätigung, Lieferschein, Mahnung, Angebot, Bestellung - selten gesetzt,
	aber wenn, dann maßgeblich."""
	target_id = party.get(purpose_field)
	if not target_id:
		return None
	for entry in party.get("partyEmailAddresses") or []:
		if entry.get("id") == target_id:
			return entry.get("toAddresses") or None
	return None


# --------------------------------------------------------------------------- Dynamic Link
def ensure_dynamic_link(doc, link_doctype: str, link_name: str) -> None:
	"""Fügt dem `links`-Child (Dynamic Link) eine Verknüpfung hinzu, falls noch nicht vorhanden."""
	for row in doc.get("links", []):
		if row.link_doctype == link_doctype and row.link_name == link_name:
			return
	doc.append("links", {"link_doctype": link_doctype, "link_name": link_name})


# --------------------------------------------------------------------------- Address
def address_is_valid(wc_addr: dict) -> bool:
	return bool(
		wc_addr.get("street1")
		and wc_addr.get("city")
		and wc_addr.get("zipcode")
		and wc_addr.get("countryCode")
	)


def _address_type(wc_addr: dict) -> str:
	if wc_addr.get("invoiceAddress"):
		return "Billing"
	if wc_addr.get("deliveryAddress"):
		return "Shipping"
	return "Postal"


def upsert_address(
	wc_addr: dict,
	*,
	party_doctype: str,
	party_name: str,
	party_number: str,
	purpose_emails: dict | None = None,
) -> dict | None:
	"""Legt/aktualisiert eine ERPNext-Address für eine WeClapp-Adresse an und verknüpft sie mit
	der Partei. Rückgabe: {"name":..., "is_primary":bool, "country":...} oder None (ungültig).

	`purpose_emails`: {"invoice": ..., "delivery": ...} - die Rechnungs-/Lieferschein-E-Mail
	wird zusätzlich auf `Address.email_id` der Rechnungs- bzw. Lieferadresse geschrieben
	(Standardfeld)."""
	if not address_is_valid(wc_addr):
		return None

	wc_id = str(wc_addr.get("id") or "")
	country = h.country_name(wc_addr.get("countryCode"))
	purpose_emails = purpose_emails or {}
	email_id = None
	if wc_addr.get("invoiceAddress"):
		email_id = purpose_emails.get("invoice")
	elif wc_addr.get("deliveryAddress"):
		email_id = purpose_emails.get("delivery")

	fields = {
		"address_title": party_number or wc_id,
		"address_type": _address_type(wc_addr),
		"address_line1": wc_addr.get("street1") or "",
		"address_line2": wc_addr.get("street2") or None,
		"city": wc_addr.get("city") or "",
		"state": wc_addr.get("state") or None,
		"country": country,
		"pincode": wc_addr.get("zipcode") or "",
		"phone": h.standardize_phone_number(wc_addr.get("phoneNumber")),
		"email_id": email_id or None,
		"is_shipping_address": 1 if wc_addr.get("deliveryAddress") else 0,
		"is_primary_address": 1 if wc_addr.get("primeAddress") else 0,
		"wc_id": wc_id or None,
	}

	name = frappe.db.exists("Address", {"wc_id": wc_id}) if wc_id else None
	doc = frappe.get_doc("Address", name) if name else frappe.new_doc("Address")
	doc.update(fields)
	ensure_dynamic_link(doc, party_doctype, party_name)
	doc.flags.ignore_permissions = True
	doc.save() if name else doc.insert()

	return {"name": doc.name, "is_primary": bool(wc_addr.get("primeAddress")), "country": country}


# --------------------------------------------------------------------------- Contact
def contact_is_valid(wc_contact: dict) -> bool:
	return bool(wc_contact.get("firstName") and wc_contact.get("lastName"))


def _contact_emails(wc_contact: dict) -> list[dict]:
	out: list[dict] = []
	primary = wc_contact.get("email")
	if primary:
		out.append({"email_id": primary, "is_primary": 1})
	home = wc_contact.get("emailHome")
	if home and home != primary:
		out.append({"email_id": home, "is_primary": 0})
	return out


def _contact_phones(wc_contact: dict) -> list[dict]:
	out: list[dict] = []
	phone = h.standardize_phone_number(wc_contact.get("phone"))
	if phone:
		out.append({"phone": phone, "is_primary_phone": 1})
	mobile = h.standardize_phone_number(wc_contact.get("mobilePhone1"))
	if mobile:
		out.append({"phone": mobile, "is_primary_mobile_no": 1})
	return out


def upsert_contact(
	wc_contact: dict,
	*,
	party_doctype: str,
	party_name: str,
	is_primary: bool,
	name_suffix: str = "",
) -> dict | None:
	"""Legt/aktualisiert einen ERPNext-Contact an und verknüpft ihn mit der Partei.
	`name_suffix` nur für den "self"-Kontakt ohne eigene WeClapp-ID (Deduplizierung über den
	Namen statt wc_id). Rückgabe: {"name":..., "is_primary":bool} oder None."""
	if not contact_is_valid(wc_contact):
		return None

	wc_id = str(wc_contact.get("id") or "")
	fields = {
		"first_name": wc_contact.get("firstName") or "",
		"last_name": wc_contact.get("lastName") or "",
		"status": "Passive",
		"is_primary_contact": 1 if is_primary else 0,
		"salutation": _SALUTATION_MAP.get(wc_contact.get("salutation")),
		"designation": wc_contact.get("title") or None,
		"wc_fax": wc_contact.get("fax") or None,
		"wc_id": wc_id or None,
	}

	name = None
	if wc_id:
		name = frappe.db.exists("Contact", {"wc_id": wc_id})
	elif name_suffix:
		# "self"-Kontakt: deterministischer Name, damit Re-Runs ihn wiederfinden.
		candidate = f"{fields['first_name']} {fields['last_name']}-{name_suffix}".strip()
		name = frappe.db.exists("Contact", candidate)

	doc = frappe.get_doc("Contact", name) if name else frappe.new_doc("Contact")
	doc.update(fields)

	# WeClapp ist maßgeblich: Child-Tabellen neu aufbauen.
	doc.set("email_ids", _contact_emails(wc_contact))
	doc.set("phone_nos", _contact_phones(wc_contact))
	ensure_dynamic_link(doc, party_doctype, party_name)

	doc.flags.ignore_permissions = True
	doc.save() if name else doc.insert()

	return {"name": doc.name, "is_primary": is_primary}


# --------------------------------------------------------------------------- Bank / Bank Account
def ensure_bank(credit_institute: str, bank_code: str) -> str | None:
	"""Findet/legt eine ERPNext-Bank an. Dedup zuerst über die BIC (swift_number), dann über
	den Namen (bei Namenskollision mit anderer BIC wird ` (n)` angehängt).
	Portiert aus reference bank_migration.py."""
	credit_institute = (credit_institute or "").strip()
	bank_code = (bank_code or "").strip()
	if not (credit_institute and bank_code):
		return None

	by_swift = frappe.db.get_value("Bank", {"swift_number": bank_code}, "name")
	if by_swift:
		return by_swift

	name = credit_institute
	if not frappe.db.exists("Bank", name):
		doc = frappe.new_doc("Bank")
		doc.bank_name = name
		doc.swift_number = bank_code
		doc.flags.ignore_permissions = True
		doc.insert()
		return doc.name

	# Name vergeben, aber andere BIC -> nummerierten Namen suchen.
	i = 1
	while frappe.db.exists("Bank", f"{name} ({i})"):
		i += 1
	doc = frappe.new_doc("Bank")
	doc.bank_name = f"{name} ({i})"
	doc.swift_number = bank_code
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def bank_account_is_valid(wc_ba: dict) -> bool:
	return bool(
		wc_ba.get("accountHolder")
		and wc_ba.get("accountNumber")
		and wc_ba.get("bankCode")
		and wc_ba.get("creditInstitute")
	)


def upsert_bank_account(
	wc_ba: dict, *, party_doctype: str, party_name: str, account_type: str | None = None
) -> str | None:
	"""Legt/aktualisiert ein ERPNext Bank Account für ein WeClapp-Bankkonto an, verknüpft mit
	der Partei. Idempotent über `wc_id`. Portiert aus reference bank_account_migration.py."""
	if not bank_account_is_valid(wc_ba):
		return None

	bank = ensure_bank(wc_ba.get("creditInstitute"), wc_ba.get("bankCode"))
	if not bank:
		return None

	wc_id = str(wc_ba.get("id") or "")
	fields = {
		"account_name": party_name,
		"bank": bank,
		"iban": (wc_ba.get("accountNumber") or "").replace(" ", ""),
		"is_default": 1 if wc_ba.get("primary") else 0,
		"party_type": party_doctype,
		"party": party_name,
		"wc_id": wc_id or None,
	}
	# Bank Account Type ist optional - nur setzen, wenn im System vorhanden.
	if account_type and frappe.db.exists("Bank Account Type", account_type):
		fields["account_type"] = account_type

	name = frappe.db.exists("Bank Account", {"wc_id": wc_id}) if wc_id else None
	doc = frappe.get_doc("Bank Account", name) if name else frappe.new_doc("Bank Account")
	doc.update(fields)
	doc.flags.ignore_permissions = True
	doc.save() if name else doc.insert()
	return doc.name


def build_self_contact(wc_party: dict, display_name: str, is_company: bool) -> dict | None:
	""""self"-Kontakt aus den Kontaktdaten der Partei selbst (PERSON-Kunden haben keinen
	separaten contacts[]-Eintrag; manche Firmen ebenfalls nicht). Siehe
	reference/customer_migration.py _map_self_contact(). Rückgabe: WeClapp-artiges dict für
	upsert_contact(), oder None wenn kein brauchbarer Kontakt herleitbar."""
	first = wc_party.get("firstName") or ""
	last = wc_party.get("lastName") or ""
	if not (first or last):
		if not is_company:
			return None
		first, last = "Hauptkontakt", display_name

	if not (
		wc_party.get("email")
		or wc_party.get("emailHome")
		or wc_party.get("phone")
		or wc_party.get("mobilePhone1")
	):
		return None

	return {
		"firstName": first,
		"lastName": last,
		"salutation": wc_party.get("salutation"),
		"title": wc_party.get("title"),
		"fax": wc_party.get("fax"),
		"email": wc_party.get("email"),
		"emailHome": wc_party.get("emailHome"),
		"phone": wc_party.get("phone"),
		"mobilePhone1": wc_party.get("mobilePhone1"),
	}
