"""Zugriff auf die Single-"WeClapp Settings" + Fabrik für den WeClapp-Client."""

from __future__ import annotations

import frappe

from weclapp_sync.weclapp import WeClappClient


def get_settings():
	return frappe.get_cached_doc("WeClapp Settings")


def get_client() -> WeClappClient:
	"""Baut einen read-only WeClapp-Client aus den Settings. Token wird als Password-Feld
	gespeichert und über get_password() entschlüsselt."""
	settings = get_settings()
	base_url = (settings.weclapp_base_url or "").strip()
	token = settings.get_password("weclapp_api_token", raise_exception=False) or ""
	page_size = int(settings.page_size or 100)
	return WeClappClient(base_url, token, page_size=page_size)


def is_object_type_enabled(key: str) -> bool:
	settings = get_settings()
	for row in settings.object_types:
		if row.object_type == key:
			return bool(row.enabled)
	return False


def get_object_type_row(key: str):
	settings = get_settings()
	for row in settings.object_types:
		if row.object_type == key:
			return row
	return None


def price_list_mapping() -> dict:
	"""{sales_channel: price_list_name} für aktivierte Preiskanäle."""
	return {
		row.sales_channel: row.price_list
		for row in get_settings().price_list_mappings
		if row.enabled and row.price_list
	}


def tax_mapping() -> dict:
	"""{wc_tax_id: {income_account, expense_account, tax_account, rate, name}} aus den Settings."""
	out: dict = {}
	for row in get_settings().tax_mappings:
		out[str(row.wc_tax_id)] = {
			"income_account": row.income_account or None,
			"expense_account": row.expense_account or None,
			"tax_account": row.tax_account or None,
			"rate": float(row.wc_rate or 0),
			"name": row.wc_tax_name or "",
		}
	return out
