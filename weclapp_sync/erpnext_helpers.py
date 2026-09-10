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
	return frappe.db.get_value("Country", {"code": country_code.strip().lower()}, "name")


def default_uom() -> str:
	return _settings().default_uom or "Nos"


def default_item_group() -> str:
	return _settings().default_item_group or "All Item Groups"


# WeClapp unitName (lowercased, punktbereinigt) -> ERPNext-UOM. Nur eindeutige Fälle;
# alles andere wird on-demand als UOM angelegt.
_UOM_ALIASES = {
	"stk": "Nos",
	"stck": "Nos",
	"stück": "Nos",
	"stueck": "Nos",
	"st": "Nos",
	"": "Nos",
}


def ensure_uom(unit_name: str | None) -> str:
	"""Mappt eine WeClapp-Mengeneinheit auf eine ERPNext-UOM. Bekannter Alias -> Standard-UOM;
	sonst: existierende UOM gleichen Namens nutzen oder neu anlegen; leer -> default_uom."""
	raw = (unit_name or "").strip()
	if not raw:
		return default_uom()
	key = raw.lower().replace(".", "").replace(" ", "")
	if key in _UOM_ALIASES:
		return _UOM_ALIASES[key]
	if frappe.db.exists("UOM", raw):
		return raw
	doc = frappe.new_doc("UOM")
	doc.uom_name = raw
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def ensure_manufacturer(name: str | None) -> str | None:
	name = (name or "").strip()
	if not name:
		return None
	if frappe.db.exists("Manufacturer", name):
		return name
	doc = frappe.new_doc("Manufacturer")
	doc.short_name = name
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def ensure_item_group(name: str | None) -> str:
	name = (name or "").strip()
	if not name:
		return default_item_group()
	if frappe.db.exists("Item Group", name):
		return name
	parent = default_item_group()
	doc = frappe.new_doc("Item Group")
	doc.item_group_name = name
	doc.parent_item_group = parent if frappe.db.exists("Item Group", parent) else "All Item Groups"
	doc.is_group = 0
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def default_currency() -> str:
	return _settings().default_currency or "EUR"


def clamp_posting_date(date_str: str | None) -> str | None:
	"""Schützt vor kaputten WeClapp-Datumsangaben (Tippfehler „23" -> Jahr 0023): liegt das
	Jahr außerhalb 2000..2100, wird auf den Beginn des frühesten aktiven Geschäftsjahres
	geklemmt (sonst FiscalYearError)."""
	if not date_str:
		return date_str
	try:
		year = int(str(date_str)[:4])
	except ValueError:
		return date_str
	if 2000 <= year <= 2100:
		return date_str
	fy = frappe.db.get_value(
		"Fiscal Year", {"disabled": 0}, "year_start_date", order_by="year_start_date asc"
	)
	return str(fy) if fy else frappe.utils.nowdate()


def default_warehouse() -> str | None:
	"""Fallback-Lager: Settings-Feld -> Company-Standardlager -> irgendein aktives
	Nicht-Gruppen-Lager. So scheitert ein Beleg ohne WeClapp-Lager nicht hart."""
	s = _settings()
	wh = s.get("default_warehouse")
	if wh:
		return wh
	if s.company:
		cwh = frappe.db.get_value("Company", s.company, "default_warehouse")
		if cwh:
			return cwh
	return frappe.db.get_value("Warehouse", {"is_group": 0, "disabled": 0}, "name")


def ensure_warehouse(wc_name: str | None) -> str | None:
	"""WeClapp-Lagername -> ERPNext-Warehouse (on-demand angelegt). Fällt auf das in den
	Settings hinterlegte Standardlager zurück, wenn kein Name kommt."""
	name = (wc_name or "").strip()
	if not name:
		return default_warehouse()
	abbr = company_abbr()
	full = f"{name} - {abbr}" if abbr else name
	if frappe.db.exists("Warehouse", full):
		return full
	if frappe.db.exists("Warehouse", name):
		return name
	hit = frappe.db.get_value("Warehouse", {"warehouse_name": name}, "name")
	if hit:
		return hit
	doc = frappe.new_doc("Warehouse")
	doc.warehouse_name = name
	doc.company = _settings().company or None
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def company_abbr() -> str | None:
	company = _settings().company
	return frappe.db.get_value("Company", company, "abbr") if company else None


def ensure_personal_account(
	*, number: str, label: str, account_type: str, currency: str | None
) -> str | None:
	"""Legt ein individuelles Personenkonto (Debitor/Kreditor) an, falls noch nicht vorhanden,
	und gibt den vollen ERPNext-Account-Namen zurück (`<nr> - <label> - <abbr>`).

	`account_type`: "Receivable" (Debitor) oder "Payable" (Kreditor).
	Parent-Gruppe kommt aus den WeClapp Settings; fehlt sie, wird None zurückgegeben
	(Kunde/Lieferant nutzt dann das Sammelkonto).
	Portiert aus reference/setup.py setup_personal_accounts().
	"""
	if not number:
		return None
	settings = _settings()
	parent = settings.debtor_parent_account if account_type == "Receivable" else settings.creditor_parent_account
	if not parent:
		return None

	company = settings.company
	abbr = frappe.db.get_value("Company", company, "abbr")
	label = (label or "").strip() or number
	full_name = f"{number} - {label} - {abbr}"

	if frappe.db.exists("Account", full_name):
		return full_name

	doc = frappe.new_doc("Account")
	doc.account_name = label
	doc.account_number = number
	doc.company = company
	doc.parent_account = parent
	doc.account_type = account_type
	# account_currency nur setzen, wenn abweichend - sonst lehnt ERPNext die Verknüpfung
	# eines Kunden ab, dessen Währung weder Firmen- noch Kontowährung entspricht.
	if currency and currency != default_currency():
		doc.account_currency = currency
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def link_or_none(doctype: str, value: str | None) -> str | None:
	"""Gibt `value` zurück, wenn ein Dokument dieses Namens existiert, sonst None.
	Verhindert LinkValidationError bei noch nicht angelegten Stammdaten (z.B. Payment Terms
	Template) - ein fehlendes Nebenfeld soll den Datensatz nicht blockieren."""
	if not value:
		return None
	value = value.strip()
	return value if frappe.db.exists(doctype, value) else None
