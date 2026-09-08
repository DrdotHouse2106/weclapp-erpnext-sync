"""Custom Fields, die der Sync auf ERPNext-Standard-Doctypes braucht.

Portiert aus reference/setup.py (setup_customer_supplier_extra_fields u.a.), plus für jeden
Sync-Zieltyp ein `wc_id`/`wc_last_modified`-Feldpaar zur Abgleich-/Debug-Unterstützung.

Programmatisch angelegt (nicht als Fixture), damit `bench migrate` / Installation die Felder
idempotent nachzieht - siehe weclapp_sync/setup/runner.py.
"""

from __future__ import annotations

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

# Zieltypen, die einen WeClapp-Herkunftsnachweis bekommen.
_WC_ID_DOCTYPES = [
	"Customer",
	"Supplier",
	"Item",
	"Address",
	"Contact",
	"Sales Invoice",
	"Sales Order",
	"Quotation",
	"Purchase Invoice",
	"Purchase Order",
	"Delivery Note",
	"Stock Entry",
	"Payment Entry",
	"Communication",
]


def _wc_id_fields() -> dict[str, list[dict]]:
	fields: dict[str, list[dict]] = {}
	for dt in _WC_ID_DOCTYPES:
		fields[dt] = [
			{
				"fieldname": "wc_sync_section",
				"label": "WeClapp Sync",
				"fieldtype": "Section Break",
				"collapsible": 1,
			},
			{
				"fieldname": "wc_id",
				"label": "WeClapp ID",
				"fieldtype": "Data",
				"read_only": 1,
				"unique": 1,
				"no_copy": 1,
				"in_standard_filter": 1,
				"insert_after": "wc_sync_section",
				"translatable": 0,
			},
			{
				"fieldname": "wc_last_modified",
				"label": "WeClapp lastModifiedDate (epoch ms)",
				"fieldtype": "Data",
				"read_only": 1,
				"no_copy": 1,
				"insert_after": "wc_id",
				"translatable": 0,
			},
		]
	return fields


def _extra_fields() -> dict[str, list[dict]]:
	fields: dict[str, list[dict]] = {
		"Contact": [
			{
				"fieldname": "wc_fax",
				"label": "Fax (WeClapp)",
				"fieldtype": "Data",
				"insert_after": "phone_nos",
			}
		],
		"Customer": [
			{
				"fieldname": "invoice_email",
				"label": "Invoice Email",
				"fieldtype": "Data",
				"insert_after": "email_id",
				"options": "Email",
			}
		],
	}
	for dt in ("Customer", "Supplier"):
		fields.setdefault(dt, []).extend([
			{
				"fieldname": "wc_zahlungsart",
				"label": "Zahlungsart (WeClapp)",
				"fieldtype": "Data",
				"insert_after": "payment_terms",
			},
			{
				"fieldname": "wc_opt_in_sektion",
				"label": "Marketing-Einwilligungen (WeClapp)",
				"fieldtype": "Section Break",
				"collapsible": 1,
				"insert_after": "wc_zahlungsart",
			},
			{"fieldname": "wc_opt_in_email", "label": "Opt-In E-Mail", "fieldtype": "Check", "insert_after": "wc_opt_in_sektion"},
			{"fieldname": "wc_opt_in_letter", "label": "Opt-In Brief", "fieldtype": "Check", "insert_after": "wc_opt_in_email"},
			{"fieldname": "wc_opt_in_phone", "label": "Opt-In Telefon", "fieldtype": "Check", "insert_after": "wc_opt_in_letter"},
			{"fieldname": "wc_opt_in_sms", "label": "Opt-In SMS", "fieldtype": "Check", "insert_after": "wc_opt_in_phone"},
		])
	return fields


def _merge(*parts: dict[str, list[dict]]) -> dict[str, list[dict]]:
	out: dict[str, list[dict]] = {}
	for part in parts:
		for dt, flds in part.items():
			out.setdefault(dt, []).extend(flds)
	return out


def apply_custom_fields() -> None:
	"""Idempotent - create_custom_fields aktualisiert vorhandene Felder statt zu doppeln."""
	create_custom_fields(_merge(_wc_id_fields(), _extra_fields()), ignore_validate=True)
