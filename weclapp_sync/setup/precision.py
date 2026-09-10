"""Erhöht die Nachkommastellen-Präzision der Einzelpreis-Felder auf den Belegzeilen.

WeClapp liefert pro Position einen `netAmount` (Zeilensumme). ERPNext arbeitet mit einem
Einzelpreis `rate` und rechnet `Betrag = rate * Menge`. Bei rabattierten Mengenpositionen ist
`netAmount / Menge` krumm (z.B. 7,98 / 10 = 0,798); mit der Standard-Präzision 2 rundet ERPNext
`rate` auf 0,80 -> Zeilenbetrag 8,00 statt 7,98 -> der Beleg driftet um Cents gegen WeClapp.

Property Setter `precision = 6` auf `rate`/`price_list_rate`/`net_rate` (+ Company-Currency-
Pendants) lässt ERPNext den Einzelpreis exakt speichern; die Betrags-/Summenfelder bleiben bei
Währungs-Präzision 2. Druckformate formatieren Beträge weiterhin 2-stellig.
"""

from __future__ import annotations

import frappe

_ITEM_DOCTYPES = [
	"Quotation Item",
	"Sales Order Item",
	"Sales Invoice Item",
	"Delivery Note Item",
	"Purchase Order Item",
	"Purchase Invoice Item",
	"Purchase Receipt Item",
]

_RATE_FIELDS = [
	"rate",
	"price_list_rate",
	"net_rate",
	"base_rate",
	"base_price_list_rate",
	"base_net_rate",
	"discount_amount",
	"base_discount_amount",
	"stock_uom_rate",
]

_PRECISION = "6"


def apply_precision() -> None:
	for doctype in _ITEM_DOCTYPES:
		meta = frappe.get_meta(doctype)
		for fieldname in _RATE_FIELDS:
			if not meta.get_field(fieldname):
				continue
			existing = frappe.db.get_value(
				"Property Setter",
				{
					"doc_type": doctype,
					"field_name": fieldname,
					"property": "precision",
					"doctype_or_field": "DocField",
				},
				"name",
			)
			if existing:
				if frappe.db.get_value("Property Setter", existing, "value") != _PRECISION:
					frappe.db.set_value("Property Setter", existing, "value", _PRECISION)
				continue

			frappe.get_doc(
				{
					"doctype": "Property Setter",
					"doctype_or_field": "DocField",
					"doc_type": doctype,
					"field_name": fieldname,
					"property": "precision",
					"property_type": "Select",
					"value": _PRECISION,
				}
			).insert(ignore_permissions=True)

	frappe.clear_cache()
