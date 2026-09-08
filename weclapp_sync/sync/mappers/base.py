"""Basisklasse für alle Objekttyp-Mapper.

Ein Mapper übersetzt **einen** WeClapp-Datensatz (dict aus der REST-API) in ein ERPNext-Dokument
und upsertet es. Er kennt keine Paginierung, keine Reihenfolge, kein Logging - das macht die
Engine (weclapp_sync/sync/engine.py). Der Mapper ist die 1:1-Entsprechung zu je einem Modul aus
reference/migration_logic/full_field_mapping/, nur mit nativer Frappe-Document-API statt REST.

Idempotenz-Prinzip (aus dem Vorgängerprojekt, unbedingt beibehalten):
- `target_name(record)` ist deterministisch aus WeClapp-Daten ableitbar (siehe
  reference/erpnext/en_helper.py) - kein persistiertes ID->Name-Mapping nötig.
- `upsert()` prüft, ob das Zieldokument existiert: ja -> laden, Felder aktualisieren, speichern;
  nein -> neu anlegen. Nie blind neu anlegen.
- Ein Fehler bei einem Datensatz bricht nie den ganzen Lauf ab (das fängt die Engine ab).
"""

from __future__ import annotations

from typing import Any

import frappe


class Mapper:
	# Von Unterklassen zu setzen:
	target_doctype: str = ""

	# Vom Engine vor dem Lauf gesetzt: der read-only WeClapp-Client, falls ein Mapper
	# Zusatzdaten braucht (z.B. das party-Objekt für Personenkonten).
	client = None

	def __init__(self) -> None:
		self._ca_definitions: dict | None = None

	# --------------------------------------------------------------- Zusatzfelder (customAttributes)
	def custom_attribute_definitions(self) -> dict:
		"""WeClapp customAttributeDefinition, keyed by id. Einmal pro Mapper-Lauf geladen
		(~99 Einträge, klein). Leeres dict, wenn kein Client."""
		if self._ca_definitions is None:
			self._ca_definitions = {}
			if self.client is not None:
				try:
					self._ca_definitions = {
						d["id"]: d for d in self.client.iter_all("customAttributeDefinition")
					}
				except Exception:
					self._ca_definitions = {}
		return self._ca_definitions

	# True, wenn für target_doctype autoname="Prompt" gesetzt ist (siehe
	# weclapp_sync/setup/naming.py) und target_name() als Dokument-ID verwendet werden soll.
	forces_name: bool = True

	# --------------------------------------------------------------- zu implementieren
	def target_name(self, record: dict) -> str | None:
		"""Deterministischer ERPNext-Dokumentname für diesen WeClapp-Datensatz.
		`None` -> Datensatz soll übersprungen werden (z.B. Lead statt Kunde)."""
		raise NotImplementedError

	def to_doc_fields(self, record: dict, *, existing: "frappe.model.document.Document | None") -> dict[str, Any]:
		"""Feld-Mapping WeClapp -> ERPNext. Gibt die zu setzenden Felder zurück.
		`existing` ist das bereits vorhandene Dokument (bei Update) bzw. None (bei Neuanlage) -
		nützlich, um bestimmte Felder bei Updates nicht zu überschreiben."""
		raise NotImplementedError

	# --------------------------------------------------------------- gemeinsame Logik
	def should_skip(self, record: dict) -> bool:
		"""Optionaler Vorfilter (z.B. Null-Rechnungen). Standard: nichts überspringen."""
		return False

	def upsert(self, record: dict) -> str | None:
		"""Legt das Zieldokument an oder aktualisiert es. Gibt den Dokumentnamen zurück,
		oder None wenn übersprungen. Exceptions werden bewusst nicht hier gefangen -
		die Engine zählt und protokolliert sie pro Datensatz."""
		if self.should_skip(record):
			return None

		name = self.target_name(record)
		if name is None:
			return None

		wc_id = str(record.get("id") or "")

		# Bestehendes Dokument finden: zuerst über das wc_id-Custom-Field (überlebt auch
		# umbenannte ERPNext-Dokumente), dann über den deterministischen Namen.
		existing_name = None
		if wc_id:
			existing_name = frappe.db.exists(self.target_doctype, {"wc_id": wc_id})
		if not existing_name and name:
			existing_name = frappe.db.exists(self.target_doctype, name)

		existing = frappe.get_doc(self.target_doctype, existing_name) if existing_name else None
		fields = dict(self.to_doc_fields(record, existing=existing))
		if wc_id:
			fields.setdefault("wc_id", wc_id)
		if record.get("lastModifiedDate"):
			fields.setdefault("wc_last_modified", str(record["lastModifiedDate"]))

		if existing is None:
			doc = frappe.new_doc(self.target_doctype)
			doc.update(fields)
			if self.forces_name and name:
				doc.name = name
			doc.flags.ignore_permissions = True
			doc.insert(set_name=name if (self.forces_name and name) else None)
			return doc.name

		existing.update(fields)
		existing.flags.ignore_permissions = True
		existing.save()
		return existing.name

	# --------------------------------------------------------------- Nachlauf
	def post_run(self) -> None:
		"""Wird einmal am Ende eines Objekttyp-Laufs aufgerufen (nach allen Seiten).
		Für Sachen, die erst gehen, wenn alle Datensätze da sind - z.B. Belegketten-
		Rückwärtsverknüpfungen (siehe reference/main.py apply_document_links). Standard: nichts."""
