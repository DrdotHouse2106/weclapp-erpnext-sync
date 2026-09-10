"""WeClapp customAttributes (Zusatzfelder / Freifelder) -> ERPNext Custom Fields.

Welche Attribute übertragen werden und in welches ERPNext-Feld, steht in der UI-Tabelle
„Zusatzfeld-Mapping" der WeClapp Settings (siehe setup/custom_attribute_fields.py). `resolve()`
bekommt daraus die `field_map` (nur aktivierte Zeilen für den jeweiligen Ziel-Doctype).

Das Anlegen der Felder macht `apply_custom_attribute_fields()` (Button / run_setup).
"""

from __future__ import annotations

from weclapp_sync import erpnext_helpers as h


def _raw_value(ca: dict, attr_def: dict):
	atype = attr_def.get("attributeType")
	if atype == "BOOLEAN":
		return 1 if ca.get("booleanValue") else 0
	if atype == "DECIMAL":
		val = ca.get("numberValue")
		try:
			return float(val) if val is not None else None
		except (TypeError, ValueError):
			return None
	if atype in ("STRING", "LARGE_TEXT", "URL"):
		return ca.get("stringValue")
	if atype == "DATE":
		return h.date_from_ts(ca.get("dateValue") or ca.get("dateTimeValue"))
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
	"""{fieldname: value} für alle im „Zusatzfeld-Mapping" aktivierten customAttributes.

	`definitions`: id -> customAttributeDefinition.
	`field_map`: attributeKey -> {"fieldname": str, "fieldtype": str}.
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
			clean = [v for v in value if v]
			if not clean:
				continue
			if mapping["fieldtype"] == "Table MultiSelect":
				out[mapping["fieldname"]] = [{"wert": v} for v in clean]
			else:
				out[mapping["fieldname"]] = ", ".join(clean)
			continue

		out[mapping["fieldname"]] = value
	return out
