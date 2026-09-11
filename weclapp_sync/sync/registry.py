"""Registry der synchronisierbaren Objekttypen + deren feste Reihenfolge.

Die Reihenfolge (SYNC_ORDER) stammt aus reference/main.py und ergibt sich aus den
Fremdschlüssel-Abhängigkeiten: Kunden vor Aufträgen vor Rechnungen vor Zahlungen usw.
Sowohl der Vollimport als auch der Delta-Sync laufen die Typen in dieser Reihenfolge durch.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from weclapp_sync.weclapp import WeClappDocType

if TYPE_CHECKING:
	from weclapp_sync.sync.mappers.base import Mapper


@dataclass(frozen=True)
class ObjectTypeSpec:
	"""Beschreibt einen synchronisierbaren Objekttyp.

	key:              stabiler Schlüssel für Settings/Log/Progress (z.B. "sales_invoice").
	label:            Anzeigename im Settings-Formular.
	weclapp_doctype:  WeClapp-REST-Entität, aus der gelesen wird.
	target_doctype:   ERPNext-Ziel-Doctype (nur informativ / fürs UI).
	mapper_path:      Importpfad "modul:ClassName" des Mappers (lazy geladen, siehe get_mapper()).
	sort:             optionaler WeClapp-sort-Parameter (z.B. Stock Movements chronologisch).
	depends_on:       keys anderer Specs, die vorher gelaufen sein müssen (nur Doku/Validierung).
	setup_only_full:  wenn True, wird dieser Typ nur beim Vollimport angefasst, nicht im Delta.
	"""

	key: str
	label: str
	weclapp_doctype: WeClappDocType
	target_doctype: str
	mapper_path: str
	sort: str | None = None
	depends_on: tuple[str, ...] = ()
	setup_only_full: bool = False

	def get_mapper(self) -> "Mapper":
		"""Lädt die Mapper-Klasse lazy (erst zur Laufzeit, damit die Registry ohne alle
		Mapper-Module importierbar bleibt) und instanziiert sie."""
		module_path, _, class_name = self.mapper_path.partition(":")
		module = __import__(module_path, fromlist=[class_name])
		return getattr(module, class_name)()


_REGISTRY: dict[str, ObjectTypeSpec] = {}

# Feste Abarbeitungsreihenfolge (siehe reference/main.py). Nur Schlüssel, die auch in
# _REGISTRY stehen, werden tatsächlich gesynct - der Rest ist "geplant, Mapper fehlt noch".
SYNC_ORDER: list[str] = [
	"customer",
	"supplier",
	"crm_event",
	"article",
	"stock_movement",
	"quotation",
	"sales_order",
	"sales_invoice",
	"sales_payment",
	"shipment",
	"purchase_order",
	"purchase_invoice",
	"purchase_payment",
]


def register(spec: ObjectTypeSpec) -> ObjectTypeSpec:
	if spec.key in _REGISTRY:
		raise ValueError(f"ObjectTypeSpec '{spec.key}' ist bereits registriert")
	if spec.key not in SYNC_ORDER:
		raise ValueError(f"ObjectTypeSpec '{spec.key}' fehlt in SYNC_ORDER")
	_REGISTRY[spec.key] = spec
	return spec


def get_spec(key: str) -> ObjectTypeSpec | None:
	return _REGISTRY.get(key)


def iter_specs() -> Iterator[ObjectTypeSpec]:
	"""Alle registrierten Specs in SYNC_ORDER-Reihenfolge."""
	for key in SYNC_ORDER:
		spec = _REGISTRY.get(key)
		if spec is not None:
			yield spec


# ---------------------------------------------------------------------------
# Registrierung der konkreten Objekttypen.
#
# TODO(mapper): Sobald ein Mapper unter weclapp_sync/sync/mappers/ existiert und lauffähig ist
# (portiert aus reference/migration_logic/full_field_mapping/<typ>_migration.py), hier
# register(ObjectTypeSpec(...)) ergänzen. Bis dahin bleibt der Typ "geplant" und wird beim
# Sync übersprungen (mit Hinweis im Log).
# ---------------------------------------------------------------------------
register(
	ObjectTypeSpec(
		key="customer",
		label="Kunden",
		weclapp_doctype=WeClappDocType.CUSTOMER,
		target_doctype="Customer",
		mapper_path="weclapp_sync.sync.mappers.customer:CustomerMapper",
	)
)

register(
	ObjectTypeSpec(
		key="supplier",
		label="Lieferanten",
		weclapp_doctype=WeClappDocType.SUPPLIER,
		target_doctype="Supplier",
		mapper_path="weclapp_sync.sync.mappers.supplier:SupplierMapper",
	)
)

register(
	ObjectTypeSpec(
		key="article",
		label="Artikel",
		weclapp_doctype=WeClappDocType.ARTICLE,
		target_doctype="Item",
		mapper_path="weclapp_sync.sync.mappers.article:ArticleMapper",
	)
)

register(
	ObjectTypeSpec(
		key="crm_event",
		label="CRM-Ereignisse",
		weclapp_doctype=WeClappDocType.CRM_EVENT,
		target_doctype="Communication",
		mapper_path="weclapp_sync.sync.mappers.crm_event:CrmEventMapper",
		depends_on=("customer", "supplier"),
	)
)

register(
	ObjectTypeSpec(
		key="stock_movement",
		label="Lagerbewegungen",
		weclapp_doctype=WeClappDocType.WAREHOUSE_STOCK_MOVEMENT,
		target_doctype="Stock Entry",
		mapper_path="weclapp_sync.sync.mappers.stock_movement:StockMovementMapper",
		depends_on=("article",),
	)
)

register(
	ObjectTypeSpec(
		key="quotation",
		label="Angebote",
		weclapp_doctype=WeClappDocType.QUOTATION,
		target_doctype="Quotation",
		mapper_path="weclapp_sync.sync.mappers.quotation:QuotationMapper",
		depends_on=("customer", "article"),
	)
)

register(
	ObjectTypeSpec(
		key="sales_order",
		label="Aufträge",
		weclapp_doctype=WeClappDocType.SALES_ORDER,
		target_doctype="Sales Order",
		mapper_path="weclapp_sync.sync.mappers.sales_order:SalesOrderMapper",
		depends_on=("customer", "article", "quotation"),
	)
)

register(
	ObjectTypeSpec(
		key="sales_invoice",
		label="Rechnungen",
		weclapp_doctype=WeClappDocType.SALES_INVOICE,
		target_doctype="Sales Invoice",
		mapper_path="weclapp_sync.sync.mappers.sales_invoice:SalesInvoiceMapper",
		depends_on=("customer", "article", "sales_order"),
	)
)

register(
	ObjectTypeSpec(
		key="shipment",
		label="Lieferscheine",
		weclapp_doctype=WeClappDocType.SHIPMENT,
		target_doctype="Delivery Note",
		mapper_path="weclapp_sync.sync.mappers.shipment:ShipmentMapper",
		depends_on=("customer", "article", "sales_order"),
	)
)

register(
	ObjectTypeSpec(
		key="purchase_order",
		label="Bestellungen",
		weclapp_doctype=WeClappDocType.PURCHASE_ORDER,
		target_doctype="Purchase Order",
		mapper_path="weclapp_sync.sync.mappers.purchase_order:PurchaseOrderMapper",
		depends_on=("supplier", "article", "sales_order"),
	)
)

register(
	ObjectTypeSpec(
		key="purchase_invoice",
		label="Eingangsrechnungen",
		weclapp_doctype=WeClappDocType.PURCHASE_INVOICE,
		target_doctype="Purchase Invoice",
		mapper_path="weclapp_sync.sync.mappers.purchase_invoice:PurchaseInvoiceMapper",
		depends_on=("supplier", "article", "purchase_order"),
	)
)
