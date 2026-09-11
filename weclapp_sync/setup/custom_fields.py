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
	"Bank Account",
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
				"fieldname": "wc_email_section",
				"label": "E-Mail-Adressen je Belegart (WeClapp)",
				"fieldtype": "Section Break",
				"collapsible": 1,
				"insert_after": "email_id",
			},
			{"fieldname": "invoice_email", "label": "Rechnung", "fieldtype": "Data", "options": "Email", "insert_after": "wc_email_section"},
			{"fieldname": "order_email", "label": "Auftragsbestätigung", "fieldtype": "Data", "options": "Email", "insert_after": "invoice_email"},
			{"fieldname": "delivery_email", "label": "Lieferschein", "fieldtype": "Data", "options": "Email", "insert_after": "order_email"},
			{"fieldname": "dunning_email", "label": "Mahnung", "fieldtype": "Data", "options": "Email", "insert_after": "delivery_email"},
			{"fieldname": "quotation_email", "label": "Angebot", "fieldtype": "Data", "options": "Email", "insert_after": "dunning_email"},
		],
		"Supplier": [
			{"fieldname": "purchase_email", "label": "Bestell-E-Mail (WeClapp)", "fieldtype": "Data", "options": "Email", "insert_after": "email_id"},
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


# Belegart -> Customer-Feld, aus dem die E-Mail per fetch_from auf den Beleg gezogen wird.
# So kann der Nutzer später mit einer Standard-"Notification" pro Belegart den Autoversand
# aktivieren, ohne dass hier Code nötig ist.
_DOC_EMAIL_SOURCES = {
	"Sales Invoice": ("customer", "invoice_email"),
	"Sales Order": ("customer", "order_email"),
	"Delivery Note": ("customer", "delivery_email"),
	"Quotation": ("party_name", "quotation_email"),
	"Dunning": ("customer", "dunning_email"),
}


def _doc_email_fields() -> dict[str, list[dict]]:
	fields: dict[str, list[dict]] = {}
	for dt, (link_field, customer_field) in _DOC_EMAIL_SOURCES.items():
		fields[dt] = [
			{
				"fieldname": "wc_belegart_email",
				"label": "E-Mail (WeClapp Belegart)",
				"fieldtype": "Data",
				"options": "Email",
				"read_only": 1,
				"no_copy": 1,
				"fetch_from": f"{link_field}.{customer_field}",
				"fetch_if_empty": 0,
				"insert_after": "contact_email",
				"translatable": 0,
			}
		]
	return fields


def _doc_link_fields() -> dict[str, list[dict]]:
	"""Belegketten-Verweise (WeClapp-Herkunftsbeleg). Read-only, rein informativ - die echte
	ERPNext-Verknüpfung (against_sales_order o.ä.) wird beim Migrationsimport nicht gesetzt."""
	return {
		"Sales Order": [
			{
				"fieldname": "wc_quotation",
				"label": "Angebot (WeClapp)",
				"fieldtype": "Link",
				"options": "Quotation",
				"read_only": 1,
				"no_copy": 1,
				"insert_after": "wc_last_modified",
				"translatable": 0,
			}
		],
		"Sales Invoice": [
			{
				"fieldname": "wc_sales_order",
				"label": "Auftrag (WeClapp)",
				"fieldtype": "Link",
				"options": "Sales Order",
				"read_only": 1,
				"no_copy": 1,
				"insert_after": "wc_last_modified",
				"translatable": 0,
			},
			{
				"fieldname": "wc_paid",
				"label": "Bezahlt (WeClapp)",
				"fieldtype": "Check",
				"read_only": 1,
				"no_copy": 1,
				"insert_after": "wc_sales_order",
				"description": "Rein informativ aus WeClapp `paid`/`paymentStatus` - kein Zahlungsabgleich, keine Buchung. Echte Payment Entries erst für laufende Zahlungen nach Live-Umstellung.",
			},
			{
				"fieldname": "wc_payment_status",
				"label": "Zahlstatus (WeClapp)",
				"fieldtype": "Data",
				"read_only": 1,
				"no_copy": 1,
				"insert_after": "wc_paid",
				"translatable": 0,
			},
		],
		"Purchase Order": [
			{
				"fieldname": "wc_sales_order",
				"label": "Verkaufsauftrag (WeClapp, Streckengeschäft)",
				"fieldtype": "Link",
				"options": "Sales Order",
				"read_only": 1,
				"no_copy": 1,
				"insert_after": "wc_last_modified",
				"translatable": 0,
			}
		],
		"Purchase Invoice": [
			{
				"fieldname": "wc_purchase_order",
				"label": "Bestellung (WeClapp)",
				"fieldtype": "Link",
				"options": "Purchase Order",
				"read_only": 1,
				"no_copy": 1,
				"insert_after": "wc_last_modified",
				"translatable": 0,
			},
			{
				"fieldname": "wc_paid",
				"label": "Bezahlt (WeClapp)",
				"fieldtype": "Check",
				"read_only": 1,
				"no_copy": 1,
				"insert_after": "wc_purchase_order",
				"description": "Rein informativ aus WeClapp `paid`/`paymentStatus` - kein Zahlungsabgleich, keine Buchung. Siehe CLAUDE.md \"Zahlungsabgleich\".",
			},
			{
				"fieldname": "wc_payment_status",
				"label": "Zahlstatus (WeClapp)",
				"fieldtype": "Data",
				"read_only": 1,
				"no_copy": 1,
				"insert_after": "wc_paid",
				"translatable": 0,
			},
		],
		"Delivery Note": [
			{
				"fieldname": "wc_sales_order",
				"label": "Auftrag (WeClapp)",
				"fieldtype": "Link",
				"options": "Sales Order",
				"read_only": 1,
				"no_copy": 1,
				"insert_after": "wc_last_modified",
				"translatable": 0,
			},
			{
				"fieldname": "wc_tracking_nummer",
				"label": "Tracking-Nummer (WeClapp)",
				"fieldtype": "Data",
				"read_only": 1,
				"no_copy": 1,
				"insert_after": "wc_sales_order",
				"translatable": 0,
			},
			{
				"fieldname": "wc_versanddienstleister",
				"label": "Versanddienstleister (WeClapp)",
				"fieldtype": "Data",
				"read_only": 1,
				"no_copy": 1,
				"insert_after": "wc_tracking_nummer",
				"translatable": 0,
			},
		],
	}


def _merge(*parts: dict[str, list[dict]]) -> dict[str, list[dict]]:
	out: dict[str, list[dict]] = {}
	for part in parts:
		for dt, flds in part.items():
			out.setdefault(dt, []).extend(flds)
	return out


def apply_custom_fields() -> None:
	"""Idempotent - create_custom_fields aktualisiert vorhandene Felder statt zu doppeln."""
	create_custom_fields(
		_merge(_wc_id_fields(), _extra_fields(), _doc_email_fields(), _doc_link_fields()),
		ignore_validate=True,
	)
