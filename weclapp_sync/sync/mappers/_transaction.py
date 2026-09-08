"""Gemeinsame Bausteine für Belegs-Mapper (Angebot / Auftrag / Rechnung / Bestellung ...).

Portiert aus reference/.../base_migration.py (`_map_net_rate`, `_add_tax`, `_map_taxes`,
`_header_adjustment_percentage`, `_map_header_discount_amount`).

**Steuer-Prinzip (aus dem Vorgängerprojekt, bewusst beibehalten):** Pro Belegzeile wird der
EXAKTE Steuerbetrag (`grossAmount - netAmount`) je WeClapp-taxId aufsummiert und später als
ERPNext-`charge_type = "Actual"`-Zeile gebucht - nicht über Prozent-Anwendung neu berechnet
(das driftet um Cents und scheitert bei gemischten Sätzen).
"""

from __future__ import annotations

from typing import Any

import frappe

from weclapp_sync import erpnext_helpers as h
from weclapp_sync.sync.mappers.base import Mapper
from weclapp_sync.sync.settings import get_settings, tax_mapping


class TransactionMapper(Mapper):
	"""Basis für Belegs-Mapper. Unterklassen setzen `target_doctype`, `items_field`
	(WeClapp-Feldname der Positionsliste) und implementieren `header_fields()`."""

	items_field: str = ""

	def __init__(self) -> None:
		super().__init__()
		self._tax_map: dict | None = None

	# ------------------------------------------------------------------ Steuer-Map
	def taxes(self) -> dict:
		if self._tax_map is None:
			self._tax_map = tax_mapping()
		return self._tax_map

	def tax_info(self, wc_tax_id: Any) -> dict | None:
		return self.taxes().get(str(wc_tax_id)) if wc_tax_id is not None else None

	# ------------------------------------------------------------------ Positionen
	@staticmethod
	def net_rate(item: dict) -> float:
		"""Echter Netto-Einzelpreis aus dem autoritativen `netAmount` (nicht `unitPrice` -
		das ist brutto/vor Rabatt). Vorzeichenerhaltend (Rabattzeilen bleiben negativ)."""
		qty = float(item.get("quantity", 1) or 1) or 1.0
		return float(item.get("netAmount", 0) or 0) / qty

	@staticmethod
	def item_qty(item: dict) -> float:
		qty = float(item.get("quantity", 0) or 0)
		return qty if qty else 1.0

	def build_lines(
		self, record: dict, *, is_selling: bool, account_field: str
	) -> tuple[list[dict], dict]:
		"""Baut die ERPNext-Positionsliste + akkumuliert die Steuern.
		`account_field`: "income_account" (Verkauf) oder "expense_account" (Einkauf).
		Rückgabe: (items, tax_accumulator) - tax_accumulator: {tax_id: (discountable, fixed)}.
		"""
		settings = get_settings()
		cost_center = settings.default_cost_center or None
		default_acc = (
			settings.default_income_account if is_selling else settings.default_expense_account
		) or None
		default_uom = h.default_uom()

		items: list[dict] = []
		acc_taxes: dict = {}

		def _add_line(wc_item: dict, *, title: str, header_discountable: bool):
			info = self.tax_info(wc_item.get("taxId"))
			account = (info or {}).get(account_field) or default_acc
			items.append(
				{
					"item_code": wc_item.get("articleNumber") or None,
					"item_name": title[:140],
					"description": title,
					"qty": self.item_qty(wc_item),
					"rate": self.net_rate(wc_item),
					"uom": h.ensure_uom(wc_item.get("unitName")) if wc_item.get("unitName") else default_uom,
					"cost_center": cost_center,
					account_field: account,
				}
			)
			self._accumulate_tax(acc_taxes, wc_item, header_discountable=header_discountable)

		for wc_item in record.get(self.items_field) or []:
			_add_line(wc_item, title=_line_title(wc_item), header_discountable=True)
		for wc_item in record.get("shippingCostItems") or []:
			_add_line(wc_item, title="Versandkosten", header_discountable=False)

		return items, acc_taxes

	def _accumulate_tax(self, acc: dict, item: dict, *, header_discountable: bool) -> None:
		info = self.tax_info(item.get("taxId"))
		if not info or not info.get("tax_account"):
			return
		tax_id = str(item.get("taxId"))
		delta = float(item.get("grossAmount", 0) or 0) - float(item.get("netAmount", 0) or 0)
		discountable, fixed = acc.get(tax_id, (0.0, 0.0))
		if header_discountable:
			discountable += delta
		else:
			fixed += delta
		acc[tax_id] = (discountable, fixed)

	def build_tax_rows(self, record: dict, acc_taxes: dict, *, negate: bool = False) -> list[dict]:
		"""Akkumulierte Steuern -> ERPNext "Actual"-Steuerzeilen."""
		scale = 1.0 - self.header_adjustment_percentage(record) / 100.0
		cost_center = get_settings().default_cost_center or None
		rows: list[dict] = []
		for tax_id, (discountable, fixed) in acc_taxes.items():
			info = self.tax_info(tax_id)
			if not info or not info.get("tax_account"):
				continue
			amount = round(discountable * scale + fixed, 2)
			if negate:
				amount = -amount
			rows.append(
				{
					"charge_type": "Actual",
					"account_head": info["tax_account"],
					"description": info.get("name") or f"WeClapp Steuer {tax_id}",
					"tax_amount": amount,
					"cost_center": cost_center,
				}
			)
		return rows

	# ------------------------------------------------------------------ Kopf-Rabatt
	@staticmethod
	def header_adjustment_percentage(record: dict) -> float:
		return float(record.get("headerDiscount", 0) or 0) - float(record.get("headerSurcharge", 0) or 0)

	def header_discount_amount(self, record: dict, *, negate: bool = False) -> float:
		percentage = self.header_adjustment_percentage(record)
		if not percentage:
			return 0.0
		net_sum = sum(float(i.get("netAmount", 0) or 0) for i in record.get(self.items_field) or [])
		amount = round(net_sum * percentage / 100.0, 2)
		return -amount if negate else amount

	# ------------------------------------------------------------------ Party-Guard
	@staticmethod
	def ensure_customer(number: str, record: dict) -> None:
		"""Legt einen Minimal-Kunden an, falls die referenzierte Nummer in ERPNext fehlt
		(ein paar Altbelege verweisen auf in WeClapp gelöschte Parteien)."""
		if not number or frappe.db.exists("Customer", number):
			return
		ra = record.get("recordAddress") or {}
		name = ra.get("company") or f"{ra.get('firstName') or ''} {ra.get('lastName') or ''}".strip() or number
		settings = get_settings()
		doc = frappe.new_doc("Customer")
		doc.name = number
		doc.customer_name = name
		doc.customer_type = "Company" if ra.get("company") else "Individual"
		doc.customer_group = (
			settings.default_customer_group_company if ra.get("company") else settings.default_customer_group_individual
		) or None
		doc.territory = settings.default_territory or None
		doc.flags.ignore_permissions = True
		doc.insert(set_name=number)


def _line_title(item: dict) -> str:
	title = item.get("title") or item.get("name") or item.get("articleName")
	return (title or "(Kein Titel)")[:140]
