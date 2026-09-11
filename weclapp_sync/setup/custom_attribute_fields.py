"""WeClapp-Zusatzfelder (customAttributes) -> ERPNext Custom Fields, **UI-gesteuert**.

Statt einer im Code kuratierten Liste (so machte es der Vorgänger-Importer, `setup.py`
`setup_custom_fields` / `setup_multiselect_fields`) pflegt der Nutzer die Zuordnung in der
Tabelle „Zusatzfeld-Mapping" (Reiter „Zusatzfelder" der WeClapp Settings):

- Button „Zusatzfelder aus WeClapp laden" (`populate_custom_attribute_mapping`): holt alle
  `customAttributeDefinition` (read-only) und legt je (Attribut, WeClapp-Objekt) eine Zeile an -
  lesbare Bezeichnung, WeClapp-Typ, Gruppe, Ziel-Doctype(s), vorbelegter Feldname/Feldtyp,
  Feld-Status. Nutzer-Auswahl bleibt bei erneutem Laden erhalten.
- Button „Ausgewählte Felder anlegen" (`apply_custom_attribute_fields`): legt je aktivierter
  Zeile das fehlende Custom Field an - gruppiert in Sektionen nach der WeClapp-Gruppe, unter
  einem Reiter „WeClapp Zusatzfelder". MULTISELECT_LIST -> echtes „Table MultiSelect" (mit
  automatisch angelegtem Werte-Doctype). Schreibt den Feld-Status zurück. Läuft auch in
  `run_setup()` (idempotent).

`sync/mappers/_custom_attributes.resolve()` liest dieselbe Tabelle: nur aktivierte Zeilen
werden beim Sync übertragen.
"""

from __future__ import annotations

import re

import frappe

from weclapp_sync import erpnext_helpers as h

# Umlaute / Akzente -> ASCII, damit Feld-/Doctype-Namen aus der Bezeichnung lesbar bleiben.
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

# WeClapp-Entity (customAttributeDefinition.entities[]) -> ERPNext-Zieldoctype(s).
WC_ENTITY_DOCTYPES: dict[str, list[str]] = {
	"article": ["Item"],
	"party": ["Customer", "Supplier"],
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
	"DATE": "Date",
	"LIST": "Select",
	"MULTISELECT_LIST": "Table MultiSelect",
}

_TAB_FIELDNAME = "wc_zusatzfelder_tab"
_TAB_LABEL = "WeClapp Zusatzfelder"
_NO_GROUP = "Weitere"


def suggested_fieldname(label: str | None, attribute_key: str) -> str:
	"""ERPNext-Feldname aus der lesbaren WeClapp-Bezeichnung („Citroën Originalnummer"
	-> `citroen_originalnummer`). Fallback auf den technischen attributeKey, wenn daraus
	nichts Brauchbares wird."""
	slug = re.sub(r"[^a-z0-9]+", "_", (label or "").translate(_TRANSLIT).lower()).strip("_")[:120]
	if slug and not slug[0].isdigit():
		return slug
	return h.custom_fieldname(attribute_key)


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
	Nutzer-Auswahl (enabled / target_fieldname / fieldtype) bleibt erhalten; `field_options`
	wird immer frisch aus WeClapp übernommen (Auswahlwerte sind WeClapp-Daten, keine Auswahl).
	Rückgabe: (gesamt, davon neu)."""
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
		suggested = suggested_fieldname(label, key)
		for entity in d.get("entities") or []:
			targets = entity_doctypes(entity)
			prev = existing.get((key, entity))
			prev_fn = (prev.target_fieldname or "").strip() if prev else ""
			# Nutzer-Feldname behalten - außer es ist noch eine Auto-Vorbelegung.
			fieldname = prev_fn if prev_fn and prev_fn not in (suggested, h.custom_fieldname(key)) else suggested
			prev_label = (prev.target_label or "").strip() if prev else ""
			rows.append(
				{
					"wc_attribute_key": key,
					"wc_label": label,
					"wc_entity": entity,
					"wc_attribute_type": atype,
					"wc_group": group,
					"target_doctype": ", ".join(targets) or "(unbekanntes Objekt)",
					"enabled": prev.enabled if prev else 0,
					"target_label": prev_label if (prev_label and prev_label != label) else label,
					"target_fieldname": fieldname,
					"fieldtype": (prev.fieldtype if prev and prev.fieldtype else default_fieldtype(atype)),
					"field_options": options,
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
	if not fieldname:
		return "kein Feldname"
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


# --------------------------------------------------------------------------- MULTISELECT-Doctypes
def _ms_value_doctype(label: str, key: str) -> tuple[str, str]:
	"""(Master-Doctype, Child-Doctype) für ein MULTISELECT_LIST-Zusatzfeld."""
	base = re.sub(r"[^A-Za-z0-9 ()/_-]", "", (label or key).translate(_TRANSLIT)).strip()
	base = re.sub(r"\s+", " ", base)[:44].strip() or h.custom_fieldname(key)
	master = f"WC ZF {base}"
	return master, f"{master} Eintrag"


def _ensure_ms_doctypes(master: str, child: str) -> None:
	if not frappe.db.exists("DocType", master):
		frappe.get_doc(
			{
				"doctype": "DocType",
				"name": master,
				"module": "WeClapp Sync",
				"custom": 1,
				"naming_rule": "By fieldname",
				"autoname": "field:wert",
				"fields": [
					{"fieldname": "wert", "fieldtype": "Data", "label": "Wert", "reqd": 1, "unique": 1, "in_list_view": 1}
				],
				"permissions": [
					{"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1}
				],
			}
		).insert(ignore_permissions=True)
	if not frappe.db.exists("DocType", child):
		frappe.get_doc(
			{
				"doctype": "DocType",
				"name": child,
				"module": "WeClapp Sync",
				"custom": 1,
				"istable": 1,
				"fields": [
					{"fieldname": "wert", "fieldtype": "Link", "options": master, "label": "Wert", "reqd": 1, "in_list_view": 1}
				],
				"permissions": [],
			}
		).insert(ignore_permissions=True)


def _sync_ms_values(master: str, values: list[str]) -> None:
	for v in values:
		v = (v or "").strip()
		if v and not frappe.db.exists(master, v):
			frappe.get_doc({"doctype": master, "wert": v}).insert(ignore_permissions=True)


# --------------------------------------------------------------------------- Felder anlegen
def apply_custom_attribute_fields() -> dict:
	"""Legt für alle aktivierten Mapping-Zeilen die fehlenden Custom Fields an (in Gruppen-
	Sektionen unter einem Reiter „WeClapp Zusatzfelder"), MULTISELECT als „Table MultiSelect"
	mit eigenem Werte-Doctype. **Selbstheilend:** die komplette Soll-Kette (Tab -> je Gruppe
	eine Sektion -> Felder) wird bei jedem Lauf neu berechnet und bereits vorhandene Felder bei
	Abweichung umgekettet - so repariert ein erneuter Lauf auch verirrte `insert_after`-Ketten
	aus früheren Versionen (die konnten Felder außerhalb unseres Tabs landen lassen, sichtbar
	als zweiter "Details"-Bereich - Nutzer-Fund 2026-09-11). Schreibt den Feld-Status zurück."""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	settings = frappe.get_single("WeClapp Settings")
	rows_all = settings.get("custom_attribute_mappings") or []
	if not rows_all:
		return {"created": 0, "enabled_rows": 0, "doctypes": []}

	# je Doctype: {gruppe: [Feld-Definitionen]} - ALLE aktivierten Zeilen, nicht nur fehlende.
	by_doctype: dict[str, dict[str, list[dict]]] = {}

	for row in rows_all:
		if not row.enabled:
			continue
		fieldname = (row.target_fieldname or "").strip()
		if not fieldname:
			continue

		options = None
		if row.fieldtype == "Table MultiSelect":
			master, child = _ms_value_doctype(row.wc_label, row.wc_attribute_key)
			_ensure_ms_doctypes(master, child)
			_sync_ms_values(master, (row.field_options or "").splitlines())
			options = child
		elif row.fieldtype == "Select" and row.field_options:
			options = "\n" + row.field_options.strip()

		group = (row.wc_group or "").strip() or _NO_GROUP
		for doctype in entity_doctypes(row.wc_entity):
			by_doctype.setdefault(doctype, {}).setdefault(group, []).append(
				_field_def(row, fieldname, options)
			)

	created = 0
	repaired = 0
	for doctype, groups in by_doctype.items():
		to_create, positions = _layout(doctype, groups)
		if to_create:
			create_custom_fields({doctype: to_create}, ignore_validate=True)
			created += len(to_create)
		for fieldname, insert_after in positions:
			current = frappe.db.get_value("Custom Field", {"dt": doctype, "fieldname": fieldname}, "insert_after")
			if current is not None and current != insert_after:
				frappe.db.set_value(
					"Custom Field", {"dt": doctype, "fieldname": fieldname}, "insert_after", insert_after,
					update_modified=False,
				)
				repaired += 1

	if created or repaired:
		frappe.clear_cache()

	# Feld-Status aller Zeilen aktualisieren
	for row in rows_all:
		row.field_status = _field_status(entity_doctypes(row.wc_entity), (row.target_fieldname or "").strip())
	settings.flags.ignore_permissions = True
	settings.save()

	enabled = sum(1 for r in rows_all if r.enabled)
	return {
		"created": created,
		"repaired": repaired,
		"enabled_rows": enabled,
		"doctypes": sorted(by_doctype),
	}


def _layout(doctype: str, groups: dict[str, list[dict]]) -> tuple[list[dict], list[tuple[str, str]]]:
	"""Baut die vollständige Soll-Kette für diesen Doctype: Tab „WeClapp Zusatzfelder" -> je
	WeClapp-Gruppe eine Sektion -> Felder, deterministisch sortiert. Läuft bei jedem Aufruf über
	ALLE aktivierten Felder (nicht nur neue), damit sich eine frühere Fehlkettung selbst heilt.

	Rückgabe: (neu anzulegende Feld-Definitionen, [(fieldname, Soll-insert_after), ...] für die
	Umkettung bereits vorhandener Felder). Die Position des Tab Breaks selbst wird NIE
	nachträglich verändert - andere Apps könnten seither eigene Felder dahinter eingefügt haben,
	das wäre Fremdterrain."""
	to_create: list[dict] = []
	positions: list[tuple[str, str]] = []

	if not _has_field(doctype, _TAB_FIELDNAME):
		to_create.append(
			{
				"fieldname": _TAB_FIELDNAME,
				"label": _TAB_LABEL,
				"fieldtype": "Tab Break",
				"insert_after": _last_field(doctype),
			}
		)

	anchor = _TAB_FIELDNAME
	ordered = sorted(groups, key=lambda g: (g == _NO_GROUP, g.lower()))
	for group in ordered:
		sec = f"wc_zf_sec_{_slug(group)}"
		if not _has_field(doctype, sec):
			to_create.append(
				{"fieldname": sec, "label": group, "fieldtype": "Section Break", "insert_after": anchor}
			)
		positions.append((sec, anchor))
		anchor = sec
		for fd in groups[group]:
			fieldname = fd["fieldname"]
			if not _has_field(doctype, fieldname):
				fd["insert_after"] = anchor
				to_create.append(fd)
			positions.append((fieldname, anchor))
			anchor = fieldname
	return to_create, positions


def _slug(text: str) -> str:
	return re.sub(r"[^a-z0-9]+", "_", (text or "").translate(_TRANSLIT).lower()).strip("_")[:60] or "x"


def _field_def(row, fieldname: str, options: str | None) -> dict:
	fd = {
		"fieldname": fieldname,
		"label": ((row.target_label or "").strip() or row.wc_label or fieldname)[:140],
		"fieldtype": row.fieldtype or "Data",
		"description": "",  # bewusst leer - Herkunft steht im Zusatzfeld-Mapping, nicht am Feld
		"translatable": 0,
	}
	if options is not None:
		fd["options"] = options
	return fd


def _last_field(doctype: str) -> str:
	fields = [f.fieldname for f in frappe.get_meta(doctype).fields]
	return fields[-1] if fields else ""


# --------------------------------------------------------------------------- fürs Sync lesen
def field_map(target_doctype: str) -> dict[str, dict]:
	"""{attributeKey: {"fieldname", "fieldtype"}} für alle aktivierten Mapping-Zeilen, deren
	Ziel-Doctype `target_doctype` enthält. Vom Mapper pro Lauf einmal geladen."""
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
