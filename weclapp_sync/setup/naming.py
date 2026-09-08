"""Setzt autoname="Prompt" (Property Setter) für alle Doctypes, für die der Sync einen
deterministischen, aus WeClapp abgeleiteten Dokumentnamen vergibt (WeClapp-Nummer = ERPNext-
Dokument-ID). Ohne das ignoriert ERPNext den übergebenen Namen und vergibt seine eigene
Nummernkreis-ID. Portiert aus reference/setup.py setup_naming().
"""

from __future__ import annotations

import frappe

_PROMPT_DOCTYPES = [
	"Customer",
	"Supplier",
	"Sales Invoice",
	"Sales Order",
	"Purchase Invoice",
	"Purchase Order",
	"Quotation",
	"Stock Entry",
	"Delivery Note",
	"Payment Entry",
	"Communication",
]


def apply_naming() -> None:
	for doctype in _PROMPT_DOCTYPES:
		existing = frappe.db.get_value(
			"Property Setter",
			{"doc_type": doctype, "property": "autoname", "doctype_or_field": "DocType"},
			"name",
		)
		if existing:
			if frappe.db.get_value("Property Setter", existing, "value") != "Prompt":
				frappe.db.set_value("Property Setter", existing, "value", "Prompt")
			continue

		frappe.get_doc(
			{
				"doctype": "Property Setter",
				"doctype_or_field": "DocType",
				"doc_type": doctype,
				"property": "autoname",
				"property_type": "Data",
				"value": "Prompt",
			}
		).insert(ignore_permissions=True)

	frappe.clear_cache()
