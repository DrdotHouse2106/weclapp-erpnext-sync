"""CRM-Ereignis-Mapper: WeClapp `crmEvent` -> ERPNext `Communication`.

Portiert aus reference/.../crm_event_migration.py. In den echten Daten kommen nur Telefonanrufe
vor (`type` = `INCOMING_CALL`/`OUTGOING_CALL`, ~3900 Events, keine Meetings/E-Mails/Sonstiges) -
andere Typen werden übersprungen.

`partyId` löst direkt auf einen Customer/Supplier auf: WeClapp `party`, `customer` und `supplier`
teilen sich denselben id-Raum (live bestätigt: `party.id` == das, was unsere Kunden-/Lieferanten-
Mapper als `wc_id` speichern) - kein zusätzlicher WeClapp-Aufruf pro Event nötig, reiner
DB-Lookup. Events, die auf keinen der beiden auflösen (Leads, außerhalb des Migrationsumfangs),
werden übersprungen.
"""

from __future__ import annotations

import frappe

from weclapp_sync import erpnext_helpers as h
from weclapp_sync.sync.mappers.base import Mapper

_CALL_DIRECTION = {"OUTGOING_CALL": "Sent", "INCOMING_CALL": "Received"}


class CrmEventMapper(Mapper):
	target_doctype = "Communication"

	def should_skip(self, record: dict) -> bool:
		return record.get("type") not in _CALL_DIRECTION

	def target_name(self, record: dict) -> str | None:
		wc_id = record.get("id")
		return f"CRM-{wc_id}" if wc_id else None

	@staticmethod
	def _reference(party_id) -> tuple[str, str] | tuple[None, None]:
		if not party_id:
			return None, None
		name = frappe.db.get_value("Customer", {"wc_id": str(party_id)}, "name")
		if name:
			return "Customer", name
		name = frappe.db.get_value("Supplier", {"wc_id": str(party_id)}, "name")
		if name:
			return "Supplier", name
		return None, None

	def upsert(self, record: dict) -> str | None:
		if self.should_skip(record):
			return None
		name = self.target_name(record)
		if not name:
			return None
		reference_doctype, reference_name = self._reference(record.get("partyId"))
		if not reference_doctype:
			return None

		existing_name = self.find_existing(record, name)
		if existing_name:
			# Anrufhistorie ändert sich nachträglich nicht - einmal angelegt reicht, Re-Runs
			# überspringen (kein docstatus-Workflow wie bei Belegen).
			return existing_name

		start_ts = record.get("startDate") or record.get("createdDate")
		doc = frappe.new_doc("Communication")
		doc.update(
			{
				"communication_type": "Communication",
				"communication_medium": "Phone",
				"sent_or_received": _CALL_DIRECTION[record["type"]],
				"subject": (record.get("subject") or "")[:140],
				"content": record.get("description") or "",
				"communication_date": h.date_from_ts(start_ts) if start_ts else None,
				"reference_doctype": reference_doctype,
				"reference_name": reference_name,
				"wc_id": str(record.get("id") or "") or None,
				"wc_last_modified": str(record.get("lastModifiedDate") or "") or None,
			}
		)
		doc.flags.ignore_permissions = True
		doc.insert(set_name=name)
		return doc.name
