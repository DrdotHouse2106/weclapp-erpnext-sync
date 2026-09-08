"""WeClapp customAttributes (Zusatzfelder / Freifelder) -> ERPNext Custom Fields.

Portiert aus reference/.../base_migration.py `_map_custom_attributes`.

**Bewusst nur bestehende Felder:** Es werden nur Werte für ERPNext-Felder gesetzt, die schon
existieren (`meta.has_field`). Das dynamische Anlegen der Felder aus
`customAttributeDefinition` (reference/setup.py `setup_custom_fields` /
`setup_multiselect_fields` / `setup_item_freifelder_tab`) ist noch nicht portiert - siehe
CLAUDE.md. Fehlende Felder werden übersprungen (kein stiller Datenverlust: der Sync-Log-
Eintrag zeigt nichts, aber `resolve()` gibt die übersprungenen Keys zurück, wenn der Aufrufer
sie protokollieren will).
"""

from __future__ import annotations

import frappe

from weclapp_sync import erpnext_helpers as h


def _raw_value(ca: dict, attr_def: dict):
	atype = attr_def.get("attributeType")
	if atype == "BOOLEAN":
		return 1 if ca.get("booleanValue") else 0
	if atype == "DECIMAL":
		return ca.get("numberValue")
	if atype in ("STRING", "LARGE_TEXT", "URL"):
		return ca.get("stringValue")
	if atype == "LIST":
		value_id = ca.get("selectedValueId")
		if value_id:
			for sv in attr_def.get("selectableValues") or []:
				if sv.get("id") == value_id:
					return sv.get("value")
		return None
	if atype == "MULTISELECT_LIST":
		ids = {v.get("id") for v in ca.get("selectedValues") or []}
		vals = [sv.get("value") for sv in attr_def.get("selectableValues") or [] if sv.get("id") in ids]
		return vals or None
	return None


def resolve(wc_record: dict, definitions: dict, target_doctype: str) -> dict:
	"""Gibt {fieldname: value} für alle customAttributes zurück, deren ERPNext-Feld existiert.

	`definitions`: id -> customAttributeDefinition (siehe Mapper.custom_attribute_definitions()).
	MULTISELECT auf `Table MultiSelect`-Feldern wird noch übersprungen (Child-Table-Handling TODO),
	auf einfachen Feldern als ", "-Liste geschrieben.
	"""
	if not wc_record.get("customAttributes"):
		return {}
	meta = frappe.get_meta(target_doctype)
	out: dict = {}
	for ca in wc_record.get("customAttributes") or []:
		attr_def = definitions.get(ca.get("attributeDefinitionId"))
		if not attr_def or not attr_def.get("attributeKey"):
			continue
		fieldname = h.custom_fieldname(attr_def["attributeKey"])
		df = meta.get_field(fieldname)
		if not df:
			continue

		value = _raw_value(ca, attr_def)
		if value is None:
			continue

		if isinstance(value, list):
			if df.fieldtype == "Table MultiSelect":
				continue  # TODO: Child-Table-Zeilen
			value = ", ".join(v for v in value if v)
			if not value:
				continue

		out[fieldname] = value
	return out
