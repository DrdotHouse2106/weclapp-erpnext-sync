"""WeClapp-Zusatzfelder (customAttributes) -> ERPNext Custom Fields, **UI-gesteuert**.

Statt einer im Code kuratierten Liste (so machte es der Vorgänger-Importer, `setup.py`
`setup_custom_fields`) pflegt der Nutzer die Zuordnung in der Tabelle „Zusatzfeld-Mapping"
in den WeClapp Settings:

- Button „Zusatzfelder aus WeClapp laden" (`weclapp_settings.populate_custom_attribute_mapping`)
  holt alle `customAttributeDefinition` und legt je (Attribut, WeClapp-Objekt) eine Zeile an -
  mit lesbarer Bezeichnung, WeClapp-Typ, Zielfeldname (vorbelegt) und Feld-Status.
- Der Nutzer hakt an, welche importiert werden sollen, passt Feldname/Feldtyp an oder zeigt
  auf ein bestehendes Feld.
- Button „Ausgewählte Felder anlegen" ruft `apply_custom_attribute_fields()` - legt die
  fehlenden Custom Fields an (unter einer eigenen Sektion „WeClapp Zusatzfelder") und
  aktualisiert den Feld-Status.

`sync/mappers/_custom_attributes.resolve()` liest dieselbe Tabelle: nur aktivierte Zeilen
werden beim Sync übertragen.
"""

from __future__ import annotations

import re

import frappe

from weclapp_sync import erpnext_helpers as h

# Umlaute / Akzente -> ASCII, damit der Feldname aus der Bezeichnung lesbar bleibt.
_TRANSLIT = str.maketrans(
	{
		"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
		"Ä": "ae", "Ö": "oe", "Ü": "ue",
		"á": "a", "à": "a", "â": "a", "ã": "a", "å": "a",
		"é": "e", "è": "e", "ê": "e", "ë": "e",
		"í": "i", "ì": "i", "î": "i", "ï": "i",
		"ó": "o", "ò": "o", "ô": "o", "õ": "o",
		"ú": "u", "ù": "u", "û": "u",
		"ç": "c", "ñ": "n",
	}
)


def suggested_fieldname(label: str | None, attribute_key: str) -> str:
	"""ERPNext-Feldname aus der lesbaren WeClapp-Bezeichnung (z.B. „Citroën Originalnummer"
	-> `citroen_originalnummer`). Nur wenn daraus nichts Brauchbares wird, Fallback auf den
	technischen attributeKey."""
	slug = re.sub(r"[^a-z0-9]+", "_", (label or "").translate(_TRANSLIT).lower()).strip("_")[:120]
	if slug and not slug[0].isdigit():
		return slug
	return h.custom_fieldname(attribute_key)

# WeClapp-Entity (customAttributeDefinition.entities[]) -> ERPNext-Zieldoctype(s).
WC_ENTITY_DOCTYPES: dict[str, list[str]] = {
	"article": ["Item"],
	"party": ["Customer", "Supplier", "Contact"],
	"customer": ["Customer"],
	"supplier": ["Supplier"],
	"salesOrder": ["Sales Order"],
	"salesOrderItem": ["Sales Order Item"],
	"salesInvoice": ["Sales Invoice"],
	"salesInvoiceItem": ["Sales Invoice Item"],
	"quotation": ["Quotation"],
	"quotationItem": ["Quotation Item"],
	"shipment": ["Delivery Note"],
	"purchaseOrder": ["Purchase Order"],
	"purchaseInvoice": ["Purchase Invoice"],
	"crmEvent": ["Event"],
}

# WeClapp attributeType -> ERPNext-Feldtyp (Vorbelegung; im Mapping änderbar).
ATTR_TYPE_TO_FIELDTYPE: dict[str, str] = {
	"BOOLEAN": "Check",
	"DECIMAL": "Float",
	"STRING": "Data",
	"LARGE_TEXT": "Small Text",
	"URL": "Data",
	"LIST": "Select",
	"MULTISELECT_LIST": "Small Text",
	"DATE": "Date",
}

_SECTION_FIELDNAME = "wc_zusatzfelder_sektion"
_SECTION_LABEL = "WeClapp Zusatzfelder"


def entity_doctypes(entity: str | None) -> list[str]:
	return WC_ENTITY_DOCTYPES.get(entity or "", [])


def default_fieldtype(attr_type: str | None) -> str:
	return ATTR_TYPE_TO_FIELDTYPE.get(attr_type or "", "Data")


def _selectable_values(attr_def: dict) -> str:
	vals = [sv.get("value") for sv in attr_def.get("selectableValues") or [] if sv.get("value")]
	return "\n".join(vals)


# --------------------------------------------------------------------------- Mapping-Tabelle füllen
def rebuild_mapping_rows(settings, definitions: list[dict]) -> tuple[int, int]:
	"""Baut die Tabelle `custom_attribute_mappings` aus den WeClapp-Definitionen neu auf.
	Bestehende Nutzer-Auswahl (enabled / target_fieldname / fieldtype / field_options) bleibt
	erhalten. Rückgabe: (gesamt, davon neu)."""
	existing = {
		(r.wc_attribute_key, r.wc_entity): r for r in settings.get("custom_attribute_mappings") or []
	}
	rows: list[dict] = []
	new_count = 0

	for d in definitions:
		key = d.get("attributeKey")
		if not key:
			continue
		label = (d.get("label") or key)[:200]
		atype = d.get("attributeType")
		group = d.get("groupName")
		options = _selectable_values(d)
		for entity in d.get("entities") or []:
			targets = entity_doctypes(entity)
			prev = existing.get((key, entity))
			fieldname = (
				prev.target_fieldname if prev and prev.target_fieldname else suggested_fieldname(label, key)
			)
			rows.append(
				{
					"wc_attribute_key": key,
					"wc_label": label,
					"wc_entity": entity,
					"wc_attribute_type": atype,
					"wc_group": group,
					"target_doctype": ", ".join(targets) or "(unbekanntes Objekt)",
					"enabled": prev.enabled if prev else 0,
					"target_fieldname": fieldname,
					"fieldtype": (prev.fieldtype if prev and prev.fieldtype else default_fieldtype(atype)),
					"field_options": (prev.field_options if prev and prev.field_options else options),
					"field_status": _field_status(targets, fieldname),
				}
			)
			if not prev:
				new_count += 1

	rows.sort(key=lambda r: (r["wc_entity"], r["wc_group"] or "~", r["wc_label"].lower()))
	settings.set("custom_attribute_mappings", rows)
	return len(rows), new_count


def _field_status(target_doctypes: list[str], fieldname: str) -> str:
	if not target_doctypes:
		return "kein Ziel-Doctype"
	present = [dt for dt in target_doctypes if _has_field(dt, fieldname)]
	if not present:
		return "fehlt"
	if len(present) == len(target_doctypes):
		return "vorhanden"
	return f"teilweise ({', '.join(present)})"


def _has_field(doctype: str, fieldname: str) -> bool:
	try:
		return bool(frappe.get_meta(doctype).get_field(fieldname))
	except Exception:
		return False


# --------------------------------------------------------------------------- Felder anlegen
def apply_custom_attribute_fields() -> dict:
	"""Legt für alle aktivierten Mapping-Zeilen die fehlenden Custom Fields an und schreibt
	den Feld-Status zurück. Idempotent."""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	settings = frappe.get_single("WeClapp Settings")
	rows_all = settings.get("custom_attribute_mappings") or []
	if not rows_all:
		return {"created": 0, "enabled_rows": 0, "doctypes": []}

	per_doctype: dict[str, list[dict]] = {}
	touched_rows: list = []

	for row in settings.get("custom_attribute_mappings") or []:
		if not row.enabled:
			continue
		fieldname = (row.target_fieldname or "").strip()
		if not fieldname:
			continue
		targets = entity_doctypes(row.wc_entity)
		for doctype in targets:
			if _has_field(doctype, fieldname):
				continue
			per_doctype.setdefault(doctype, [])
			# eigene Sammel-Sektion je Doctype (einmal)
			if not any(f["fieldname"] == _SECTION_FIELDNAME for f in per_doctype[doctype]) and not _has_field(
				doctype, _SECTION_FIELDNAME
			):
				per_doctype[doctype].append(
					{
						"fieldname": _SECTION_FIELDNAME,
						"label": _SECTION_LABEL,
						"fieldtype": "Section Break",
						"collapsible": 1,
						"insert_after": _last_field(doctype),
					}
				)
			per_doctype[doctype].append(_field_def(row, fieldname))
		touched_rows.append(row)

	created = 0
	if per_doctype:
		create_custom_fields(per_doctype, ignore_validate=True)
		created = sum(len(v) for v in per_doctype.values())

	# Status aktualisieren (alle Zeilen, nicht nur die angefassten)
	for row in settings.get("custom_attribute_mappings") or []:
		row.field_status = _field_status(
			entity_doctypes(row.wc_entity), (row.target_fieldname or "").strip()
		)
	settings.flags.ignore_permissions = True
	settings.save()
	frappe.clear_cache()

	enabled = sum(1 for r in settings.get("custom_attribute_mappings") or [] if r.enabled)
	return {"created": created, "enabled_rows": enabled, "doctypes": sorted(per_doctype)}


def _field_def(row, fieldname: str) -> dict:
	fd = {
		"fieldname": fieldname,
		"label": (row.wc_label or fieldname)[:140],
		"fieldtype": row.fieldtype or "Data",
		"insert_after": _SECTION_FIELDNAME,
		"description": f"WeClapp-Zusatzfeld: {row.wc_attribute_key}",
		"translatable": 0,
	}
	if row.fieldtype == "Select" and row.field_options:
		fd["options"] = "\n" + row.field_options.strip()
	return fd


def _last_field(doctype: str) -> str:
	meta = frappe.get_meta(doctype)
	fields = [f.fieldname for f in meta.fields]
	return fields[-1] if fields else ""


# --------------------------------------------------------------------------- fürs Sync lesen
def field_map(target_doctype: str) -> dict[str, dict]:
	"""{attributeKey: {"fieldname":..., "fieldtype":...}} für alle aktivierten Mapping-Zeilen,
	deren Ziel-Doctype `target_doctype` enthält. Vom Mapper pro Lauf einmal geladen."""
	rows = frappe.get_all(
		"WeClapp Custom Attribute Mapping",
		filters={"parenttype": "WeClapp Settings", "enabled": 1},
		fields=["wc_attribute_key", "wc_entity", "target_fieldname", "fieldtype"],
	)
	out: dict[str, dict] = {}
	for r in rows:
		if target_doctype not in entity_doctypes(r.wc_entity):
			continue
		fn = (r.target_fieldname or "").strip()
		if fn:
			out[r.wc_attribute_key] = {"fieldname": fn, "fieldtype": r.fieldtype or "Data"}
	return out
