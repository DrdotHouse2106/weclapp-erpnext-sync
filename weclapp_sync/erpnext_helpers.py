"""Übersetzungs-/Formatierungshelfer WeClapp -> ERPNext.

Portiert aus reference/erpnext/en_helper.py. Statische Formatierer bleiben statisch; alles, was
früher aus config.* kam, liest hier aus der Single-"WeClapp Settings".
"""

from __future__ import annotations

import html as _html
import re
from datetime import datetime

import frappe

_DEFAULT_PHONE_CC = "49"


# --------------------------------------------------------------------------- Zeit
def date_from_ts(ts: int | None) -> str | None:
	if not ts:
		return None
	return datetime.fromtimestamp(int(ts) / 1000).strftime("%Y-%m-%d")


def time_from_ts(ts: int | None) -> str | None:
	if not ts:
		return None
	return datetime.fromtimestamp(int(ts) / 1000).strftime("%H:%M:%S")


def datetime_from_ts(ts: int | None) -> str | None:
	if not ts:
		return None
	return datetime.fromtimestamp(int(ts) / 1000).strftime("%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------------------------- Text
def standardize_phone_number(number: str | None, default_country_code: str = _DEFAULT_PHONE_CC) -> str:
	"""WeClapp speichert oft explizit null statt einer fehlenden Nummer."""
	if not number:
		return ""
	cleaned = re.sub(r"\D", "", number)
	if cleaned.startswith("00"):
		return f"+{cleaned[2:]}"
	if cleaned.startswith("0"):
		return f"+{default_country_code}{cleaned[1:]}"
	if cleaned:
		return f"+{cleaned}"
	return ""


def strip_html(value: str | None) -> str:
	"""WeClapp-Rich-Text -> Klartext. WeClapp-'description' ist in der Praxis doppelt
	HTML-escaped (live bestätigt im Vorgängerprojekt), daher mehrfach unescapen."""
	if not value:
		return ""
	text = value
	for _ in range(5):
		unescaped = _html.unescape(text)
		if unescaped == text:
			break
		text = unescaped
	text = re.sub(r"(?i)<br\s*/?>", "\n", text)
	text = re.sub(r"(?i)</p>", "\n", text)
	text = re.sub(r"<[^>]+>", "", text)
	return re.sub(r"\n{2,}", "\n", text).strip()


def custom_fieldname(attribute_key: str) -> str:
	"""Frappe-Fieldname aus einem WeClapp-attributeKey (der mit einer Ziffer beginnen kann)."""
	key = re.sub(r"[^a-z0-9_]", "_", (attribute_key or "").lower())
	if not key or not (key[0].isalpha() or key[0] == "_"):
		key = f"cf_{key}"
	return key


def join_notes(*values: str | None) -> str:
	return "\n".join(strip_html(v) for v in values if v).strip()


# --------------------------------------------------------------------------- deterministische Namen
def wc_warehouse_name(wc_name: str, wc_id: str) -> str:
	return f"{wc_name} ({wc_id})"


def wc_account_name(account_number: str, description: str) -> str:
	label = {"1200": "Bankkonto", "1000": "Kasse"}.get(account_number, description)
	return f"{account_number} - {label}"


# --------------------------------------------------------------------------- settings-abhängig
def _settings():
	return frappe.get_cached_doc("WeClapp Settings")


def territory_for_country(country: str | None) -> str | None:
	s = _settings()
	germany = s.default_territory_germany or "Germany"
	default = s.default_territory or "Rest Of The World"
	if country and country.strip().lower() in ("germany", "deutschland", "de"):
		return germany
	return default


def country_name(country_code: str | None) -> str | None:
	"""WeClapp countryCode (ISO 3166-1 alpha-2) -> ERPNext-Country-Name."""
	if not country_code:
		return None
	name = frappe.db.get_value("Country", {"code": country_code.strip().lower()}, "name")
	return name or country_code


def default_uom() -> str:
	return _settings().default_uom or "Nos"


def default_currency() -> str:
	return _settings().default_currency or "EUR"
