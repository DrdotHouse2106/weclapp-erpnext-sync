"""Lieferanten-Mapper: WeClapp `supplier` -> ERPNext `Supplier` (+ Adressen, Kontakte, Bankkonten).

Weitgehend analog zu customer.py (siehe dort). Unterschiede:
- kein Kunden-/Privatkunden-Split, eine `default_supplier_group`
- keine `wc_opt_in_*` (WeClapp-supplier hat diese Felder nicht)
- kein Territory
- Kreditorenkonto (Payable) statt Debitorenkonto; `purchase_email` statt der 5 Verkaufs-Purposes
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

_PARTY_DOCTYPE = "Supplier"


def _guarded(child_doctype: str, party_name: str, wc_obj: dict, fn: Callable[[], Any]) -> Any:
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


class SupplierMapper(Mapper):
	target_doctype = "Supplier"

	def __init__(self) -> None:
		self._party_cache: tuple[str, dict] | None = None

	def should_skip(self, record: dict) -> bool:
		return not (record.get("partyType") and record.get("supplierNumber") and pc.display_name(record))

	def target_name(self, record: dict) -> str | None:
		return record.get("supplierNumber") or None

	def _party(self, record: dict) -> dict:
		wc_id = str(record.get("id") or "")
		if self._party_cache and self._party_cache[0] == wc_id:
			return self._party_cache[1]
		party: dict = {}
		if wc_id and self.client is not None:
			try:
				party = self.client.get("party", wc_id) or {}
			except Exception:
				party = {}
		self._party_cache = (wc_id, party)
		return party

	def to_doc_fields(self, record: dict, *, existing: Any = None) -> dict[str, Any]:
		settings = get_settings()
		party = self._party(record)
		is_company = record.get("partyType") != "PERSON"
		return {
			"supplier_name": pc.display_name(record),
			"supplier_type": "Company" if is_company else "Individual",
			"supplier_group": settings.default_supplier_group or None,
			"website": record.get("website") or None,
			"tax_id": record.get("vatRegistrationNumber") or None,
			"default_currency": h.link_or_none("Currency", record.get("currencyName")),
			"disabled": 0,
			"supplier_details": h.join_notes(
				party.get("supplierInternalNote"),
				pc.block_notice(record.get("blockNotice")),
				record.get("description"),
			)
			or None,
			"purchase_email": pc.purpose_email(party, "purchaseEmailAddressesId"),
			"payment_terms": h.link_or_none("Payment Terms Template", record.get("termOfPaymentName")),
			"wc_zahlungsart": record.get("paymentMethodName") or None,
		}

	def upsert(self, record: dict) -> str | None:
		if self.should_skip(record):
			return None
		number = record.get("supplierNumber")
		is_company = record.get("partyType") != "PERSON"
		display = pc.display_name(record)

		name = super().upsert(record)
		if not name:
			return None

		party = self._party(record)
		purpose_emails = {"invoice": pc.purpose_email(party, "purchaseEmailAddressesId")}

		primary_address = None
		primary_contact = None
		first_contact = None

		# Adressen
		for wc_addr in record.get("addresses") or []:
			res = _guarded("Address", name, wc_addr, lambda a=wc_addr: pc.upsert_address(
				a,
				party_doctype=_PARTY_DOCTYPE,
				party_name=name,
				party_number=number,
				purpose_emails=purpose_emails,
			))
			if res and res["is_primary"]:
				primary_address = res

		# Kontakte
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

		if primary_contact is None:
			self_data = pc.build_self_contact(record, display, is_company)
			if self_data:
				primary_contact = _guarded("Contact", name, self_data, lambda: pc.upsert_contact(
					self_data,
					party_doctype=_PARTY_DOCTYPE,
					party_name=name,
					is_primary=True,
					name_suffix=number,
				))

		# Bankkonten
		for wc_ba in record.get("bankAccounts") or []:
			_guarded("Bank Account", name, wc_ba, lambda b=wc_ba: pc.upsert_bank_account(
				b, party_doctype=_PARTY_DOCTYPE, party_name=name, account_type="Lieferanten-Bankkonto"
			))

		# Kreditorenkonto (Personenkonto)
		creditor_number = party.get("supplierCreditorAccountNumber")
		if creditor_number:
			label = (party.get("company") or display).strip()
			account_name = _guarded("Account", name, {"id": creditor_number}, lambda: h.ensure_personal_account(
				number=creditor_number,
				label=label,
				account_type="Payable",
				currency=record.get("currencyName"),
			))
			if account_name:
				sup = frappe.get_doc("Supplier", name)
				if not any(r.account == account_name for r in sup.get("accounts", [])):
					sup.append("accounts", {"company": get_settings().company, "account": account_name})
					sup.flags.ignore_permissions = True
					sup.save()

		# Primär-Verknüpfungen
		updates: dict[str, Any] = {}
		if primary_address:
			updates["supplier_primary_address"] = primary_address["name"]
		if primary_contact:
			updates["supplier_primary_contact"] = primary_contact["name"]
			if not frappe.db.get_value("Contact", primary_contact["name"], "is_primary_contact"):
				frappe.db.set_value(
					"Contact", primary_contact["name"], "is_primary_contact", 1, update_modified=False
				)
		if updates:
			frappe.db.set_value("Supplier", name, updates, update_modified=False)

		return name
