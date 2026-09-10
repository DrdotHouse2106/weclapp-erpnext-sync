"""WeClapp customAttributes (Zusatzfelder / Freifelder) -> ERPNext Custom Fields.

Welche Attribute übertragen werden und in welches ERPNext-Feld, steht in der **UI-Tabelle**
„Zusatzfeld-Mapping" der WeClapp Settings (siehe setup/custom_attribute_fields.py). `resolve()`
bekommt daraus die `field_map` (nur aktivierte Zeilen für den jeweiligen Ziel-Doctype) - kein
im Code kuratierter Feldkatalog mehr.

Nicht (mehr) hier: das Anlegen der Felder - das macht `apply_custom_attribute_fields()` über
den Button in den Settings bzw. `run_setup()`.
"""

from __future__ import annotations


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


def resolve(wc_record: dict, definitions: dict, field_map: dict) -> dict:
	"""Gibt {fieldname: value} für alle customAttributes zurück, die im „Zusatzfeld-Mapping"
	aktiviert sind.

	`definitions`: id -> customAttributeDefinition (siehe Mapper.custom_attribute_definitions()).
	`field_map`: attributeKey -> {"fieldname": str, "fieldtype": str} (siehe
	setup/custom_attribute_fields.field_map()).
	"""
	if not wc_record.get("customAttributes") or not field_map:
		return {}
	out: dict = {}
	for ca in wc_record.get("customAttributes") or []:
		attr_def = definitions.get(ca.get("attributeDefinitionId"))
		if not attr_def:
			continue
		mapping = field_map.get(attr_def.get("attributeKey"))
		if not mapping:
			continue

		value = _raw_value(ca, attr_def)
		if value is None:
			continue

		if isinstance(value, list):
			if mapping["fieldtype"] == "Table MultiSelect":
				continue  # TODO: Child-Table-Zeilen
			value = ", ".join(v for v in value if v)
			if not value:
				continue

		out[mapping["fieldname"]] = value
	return out
