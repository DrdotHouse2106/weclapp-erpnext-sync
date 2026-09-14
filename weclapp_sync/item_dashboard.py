"""Ergänzt den Item-"Verknüpfungen"-Reiter um Product Bundle.

Nutzer-Fund (2026-09-15): Set-/Bundle-Artikel (`articleType == "SALES_BILL_OF_MATERIAL"`, siehe
`sync/mappers/article.py` `_sync_product_bundle()`) legen ein ERPNext "Product Bundle" an, aber
ERPNext zeigt dessen Inhalt NIRGENDS direkt am Artikel - Product Bundle ist ein eigener Doctype,
im Item-Formular unsichtbar. Über `override_doctype_dashboards` (hooks.py) wird die Standard-
Verknüpfungen-Ansicht des Items um Product Bundle ergänzt, mit `new_item_code` als Link-Feld
(Product Bundles Feldname weicht vom Standard `item_code` ab).
"""

from __future__ import annotations


def get_dashboard_data(data):
	data.setdefault("non_standard_fieldnames", {})["Product Bundle"] = "new_item_code"
	data.setdefault("transactions", []).append({"label": "WeClapp", "items": ["Product Bundle"]})
	return data
