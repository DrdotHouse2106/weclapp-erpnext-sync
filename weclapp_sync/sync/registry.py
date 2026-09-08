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
	"article_price",
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
