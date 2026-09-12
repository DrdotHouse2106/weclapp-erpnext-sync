"""Löst: "Woher weiß ERPNext bei künftigen, von Hand erfassten Belegen den Steuersatz?"

Hintergrund (CLAUDE.md Increment 12/18 - Item-Steuer-Template-Konflikt): das native
`Item.taxes` (Item Tax Template) muss für den Sync leer bleiben, weil ERPNext sonst bei jedem
Speichern den vom Template erwarteten Steuerbetrag gegen unsere Actual-Steuerzeilen prüft und
Belege ablehnt, deren Artikel historisch zu einem anderen Satz verkauft wurde (live bestätigte
Regression, siehe article.py). Das ist keine Migrations-Übergangslösung, sondern dauerhaft, da
das Actual-Zeilen-Buchen permanent bleibt.

Lösung: das native Feld bleibt leer; stattdessen liest ein **Client Script** beim manuellen
Anlegen einer Belegzeile im Browser das rein informative Custom Field
`Item.custom_default_item_tax_template` (siehe custom_fields.py) aus und trägt es NUR in die
gerade neu angelegte Zeile ein. Ein Client Script läuft ausschließlich im Browser - der Sync
(Python, `frappe.new_doc(...).insert()`/`.save()`) triggert nie eins. Importierte/synctierte
Belege sind dadurch von Konstruktion her unberührt; nur wer künftig von Hand eine Position in
der ERPNext-Oberfläche erfasst, bekommt den Steuersatz vorgeschlagen (überschreibt nichts, wenn
die Zeile schon einen `item_tax_template` trägt).
"""

from __future__ import annotations

import frappe

_SCRIPT = """
frappe.ui.form.on('{child_doctype}', {{
	item_code: function(frm, cdt, cdn) {{
		var row = locals[cdt][cdn];
		if (!row.item_code || row.item_tax_template) return;
		frappe.db.get_value('Item', row.item_code, 'custom_default_item_tax_template', function(r) {{
			if (r && r.custom_default_item_tax_template) {{
				frappe.model.set_value(cdt, cdn, 'item_tax_template', r.custom_default_item_tax_template);
			}}
		}});
	}}
}});
""".strip()

# Belegarten, in denen von Hand neue Positionen mit Steuerbezug angelegt werden. Delivery Note/
# Stock Entry bewusst ausgelassen (keine Steuerzeilen).
_TARGETS = {
	"Quotation": "Quotation Item",
	"Sales Order": "Sales Order Item",
	"Sales Invoice": "Sales Invoice Item",
	"Purchase Order": "Purchase Order Item",
	"Purchase Invoice": "Purchase Invoice Item",
}

# Marker im Script-Text, um unser eigenes Client Script wiederzufinden (Client Script hat
# Hash-Naming, kein deterministischer `name` möglich - analog zum Property-Setter-Abgleich in
# naming.py).
_MARKER = "custom_default_item_tax_template"


def apply_item_tax_hint_client_scripts() -> None:
	for parent_doctype, child_doctype in _TARGETS.items():
		script = _SCRIPT.format(child_doctype=child_doctype)
		existing = frappe.db.get_value(
			"Client Script",
			{"dt": parent_doctype, "script": ["like", f"%{_MARKER}%"]},
			"name",
		)
		if existing:
			doc = frappe.get_doc("Client Script", existing)
			if doc.script != script or not doc.enabled:
				doc.script = script
				doc.enabled = 1
				doc.save(ignore_permissions=True)
			continue
		frappe.get_doc(
			{
				"doctype": "Client Script",
				"dt": parent_doctype,
				"view": "Form",
				"enabled": 1,
				"script": script,
			}
		).insert(ignore_permissions=True)
