from enum import Enum


class WeClappDocType(str, Enum):
	"""WeClapp-REST-Entitäten (Endpunkt-Namen). Nur die für den Sync relevanten Typen -
	die vollständige Liste steht in reference/weclapp/wc_doctypes.py, falls mehr gebraucht wird.
	`str`-Mixin, damit `WeClappDocType.CUSTOMER == "customer"` gilt und der Wert direkt in URLs
	und Query-Parametern verwendbar ist."""

	# --- Stammdaten / Parteien ---
	CUSTOMER = "customer"
	SUPPLIER = "supplier"
	PARTY = "party"
	CONTACT = "contact"
	LEAD = "lead"

	# --- Artikel / Preise / Lager ---
	ARTICLE = "article"
	ARTICLE_PRICE = "articlePrice"
	ARTICLE_SUPPLY_SOURCE = "articleSupplySource"
	WAREHOUSE = "warehouse"
	WAREHOUSE_STOCK = "warehouseStock"
	WAREHOUSE_STOCK_MOVEMENT = "warehouseStockMovement"

	# --- Verkauf ---
	QUOTATION = "quotation"
	SALES_ORDER = "salesOrder"
	SALES_INVOICE = "salesInvoice"
	SALES_OPEN_ITEM = "salesOpenItem"
	SHIPMENT = "shipment"

	# --- Einkauf ---
	PURCHASE_ORDER = "purchaseOrder"
	PURCHASE_INVOICE = "purchaseInvoice"
	PURCHASE_OPEN_ITEM = "purchaseOpenItem"

	# --- CRM ---
	CRM_EVENT = "crmEvent"

	def __str__(self) -> str:  # pragma: no cover - Komfort
		return self.value
