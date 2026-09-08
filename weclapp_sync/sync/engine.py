"""Sync-Engine: gemeinsamer Unterbau für Vollimport und Delta-Sync.

Beide Modi laufen durch dieselbe `sync_object_type()`-Funktion und denselben Mapper pro
Objekttyp. Unterschied ist nur der WeClapp-Filter:
  - Vollimport: kein Filter (alles).
  - Delta-Sync: `lastModifiedDate-gt = <letzter erfolgreicher Lauf des Typs>`.

Speicher: pro Objekttyp wird **seitenweise** iteriert (WeClappClient.iter_pages ist ein
Generator). Nach jeder Seite: `frappe.db.commit()` und die Seite wird verworfen. Es liegt nie
die volle Liste eines Objekttyps im RAM.

Resumierbarkeit: nach jeder committeten Seite wird `progress_page` in der Objekttyp-Zeile der
Settings gespeichert. Bricht der Job ab (OOM/Neustart) und wird derselbe Run fortgesetzt,
startet der Typ bei `progress_page + 1`.

Fehlertoleranz: ein Fehler bei einem einzelnen Datensatz bricht den Lauf nie ab - er wird
gezählt, in "WeClapp Sync Log" protokolliert, dann geht es weiter.
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field

import frappe
from frappe.utils import now_datetime

from weclapp_sync.sync import registry
from weclapp_sync.sync.settings import get_client, get_object_type_row, get_settings

MODE_FULL = "Full Import"
MODE_DELTA = "Delta Sync"


@dataclass
class TypeResult:
	key: str
	processed: int = 0
	failed: int = 0
	skipped: int = 0
	status: str = "ok"  # ok | skipped_no_mapper | disabled | error
	message: str = ""


@dataclass
class RunResult:
	mode: str
	run_name: str
	types: list[TypeResult] = field(default_factory=list)

	@property
	def total_processed(self) -> int:
		return sum(t.processed for t in self.types)

	@property
	def total_failed(self) -> int:
		return sum(t.failed for t in self.types)


# ---------------------------------------------------------------------------
# Ein Objekttyp
# ---------------------------------------------------------------------------
def sync_object_type(
	spec: registry.ObjectTypeSpec,
	*,
	mode: str,
	run_name: str,
	client=None,
) -> TypeResult:
	result = TypeResult(key=spec.key)

	row = get_object_type_row(spec.key)
	if row is None or not row.enabled:
		result.status = "disabled"
		return result

	try:
		mapper = spec.get_mapper()
	except (ImportError, AttributeError, NotImplementedError) as e:
		result.status = "skipped_no_mapper"
		result.message = f"Kein lauffähiger Mapper: {e}"
		return result

	own_client = client is None
	client = client or get_client()
	if own_client:
		client.open()
	mapper.client = client

	# Delta-Watermark: Zeitpunkt VOR dem Lauf merken, aber erst bei Erfolg persistieren.
	run_start_ms = client.now_ms()
	since_ms = int(row.last_sync_ms or 0) if mode == MODE_DELTA else 0
	filters = client.modified_since_filter(since_ms) if mode == MODE_DELTA else {}

	# Resume: nur fortsetzen, wenn dieselbe Run diesen Typ schon angefangen hatte.
	start_page = 1
	if row.progress_run == run_name and (row.progress_page or 0) > 0:
		start_page = int(row.progress_page) + 1

	max_pages = int(get_settings().debug_max_pages_per_type or 0)
	truncated = False

	try:
		page_no = 0
		for page in client.iter_pages(spec.weclapp_doctype, filters=filters, sort=spec.sort):
			page_no += 1
			if page_no < start_page:
				continue
			if max_pages and page_no > max_pages:
				truncated = True
				break

			for idx, record in enumerate(page):
				# Savepoint pro Datensatz: schlägt einer fehl, wird nur SEIN Teil
				# zurückgerollt, die schon verarbeiteten Datensätze der Seite bleiben.
				savepoint = f"wcrec_{idx}"
				frappe.db.savepoint(savepoint)
				try:
					name = mapper.upsert(record)
					if name is None:
						result.skipped += 1
					else:
						result.processed += 1
				except Exception:
					tb = frappe.get_traceback()
					frappe.db.rollback(save_point=savepoint)
					result.failed += 1
					_log_record_failure(run_name, spec, record, tb)

			frappe.db.commit()
			_save_progress(spec.key, run_name, page_no)

		if truncated:
			# Test-Lauf mit Seitenbegrenzung: KEIN Watermark setzen (Typ ist nicht
			# vollständig), Fortschritt aber behalten, damit ein Folgelauf weitermacht.
			result.status = "truncated"
			result.message = f"nach {max_pages} Seite(n) abgeschnitten (debug_max_pages_per_type)"
			return result

		mapper.post_run()
		frappe.db.commit()

		# Erfolg: Watermark setzen, Fortschritt zurücksetzen.
		_finish_type(spec.key, run_start_ms)
		frappe.db.commit()
	except Exception as e:
		result.status = "error"
		result.message = f"{type(e).__name__}: {e}"
		frappe.db.rollback()
		_log_type_failure(run_name, spec, e)
	finally:
		if own_client:
			client.close()

	return result


# ---------------------------------------------------------------------------
# Ganzer Lauf
# ---------------------------------------------------------------------------
def run_sync(mode: str, *, run_name: str | None = None) -> RunResult:
	settings = get_settings()
	if not settings.enabled:
		frappe.throw("WeClapp Sync ist in den Einstellungen deaktiviert.")

	run = _create_run(mode) if run_name is None else frappe.get_doc("WeClapp Sync Run", run_name)
	res = RunResult(mode=mode, run_name=run.name)

	client = get_client()
	client.open()
	try:
		for spec in registry.iter_specs():
			tr = sync_object_type(spec, mode=mode, run_name=run.name, client=client)
			res.types.append(tr)
			_append_run_type_summary(run, tr)
	finally:
		client.close()

	_finish_run(run, res)
	return res


def run_full_import(run_name: str | None = None) -> dict:
	"""Entry point für den "Vollimport"-Button / Background-Job."""
	from weclapp_sync.setup.runner import run_setup

	# Struktur/Stammdaten vor den Objekttyp-Mappern (Custom Fields, Naming; die
	# datenintensiven setup_*()-Äquivalente sind noch TODO, siehe runner.py).
	run_setup(full=True)
	res = run_sync(MODE_FULL, run_name=run_name)
	return _result_payload(res)


def run_delta_sync(run_name: str | None = None) -> dict:
	"""Entry point für den Scheduler-Background-Job."""
	res = run_sync(MODE_DELTA, run_name=run_name)
	return _result_payload(res)


# ---------------------------------------------------------------------------
# Log-/Run-Doctype-Helfer
# ---------------------------------------------------------------------------
def _create_run(mode: str):
	doc = frappe.new_doc("WeClapp Sync Run")
	doc.mode = mode
	doc.status = "Running"
	doc.started_at = now_datetime()
	doc.flags.ignore_permissions = True
	doc.insert()
	frappe.db.commit()
	return doc


def _finish_run(run, res: RunResult) -> None:
	run.reload()
	run.status = "Completed" if res.total_failed == 0 else "Completed with errors"
	run.finished_at = now_datetime()
	run.records_processed = res.total_processed
	run.records_failed = res.total_failed
	run.flags.ignore_permissions = True
	run.save()
	frappe.db.commit()


def _append_run_type_summary(run, tr: TypeResult) -> None:
	run.reload()
	run.append(
		"type_results",
		{
			"object_type": tr.key,
			"status": tr.status,
			"processed": tr.processed,
			"failed": tr.failed,
			"skipped": tr.skipped,
			"message": tr.message[:500],
		},
	)
	run.flags.ignore_permissions = True
	run.save()
	frappe.db.commit()


def _log_record_failure(run_name: str, spec: registry.ObjectTypeSpec, record: dict, tb: str) -> None:
	"""Protokolliert einen fehlgeschlagenen Datensatz. Wird nach rollback(save_point=...)
	aufgerufen - die Transaktion ist wieder sauber, der Log-Eintrag committet mit der Seite."""
	try:
		doc = frappe.new_doc("WeClapp Sync Log")
		doc.sync_run = run_name
		doc.object_type = spec.key
		doc.weclapp_doctype = str(spec.weclapp_doctype)
		doc.weclapp_id = str(record.get("id") or "")
		doc.reference = _record_ref(spec, record)
		doc.error = (tb or "")[:5000]
		doc.flags.ignore_permissions = True
		doc.insert()
	except Exception:
		frappe.log_error(title="WeClapp Sync: Log-Eintrag fehlgeschlagen", message=traceback.format_exc())


def _log_type_failure(run_name: str, spec: registry.ObjectTypeSpec, exc: Exception) -> None:
	try:
		doc = frappe.new_doc("WeClapp Sync Log")
		doc.sync_run = run_name
		doc.object_type = spec.key
		doc.weclapp_doctype = str(spec.weclapp_doctype)
		doc.reference = "(ganzer Objekttyp-Lauf abgebrochen)"
		doc.error = f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}"[:5000]
		doc.flags.ignore_permissions = True
		doc.insert()
		frappe.db.commit()
	except Exception:
		frappe.log_error(title="WeClapp Sync: Typ-Fehler-Log fehlgeschlagen", message=traceback.format_exc())


def _record_ref(spec: registry.ObjectTypeSpec, record: dict) -> str:
	for k in ("invoiceNumber", "orderNumber", "quotationNumber", "customerNumber", "supplierNumber", "articleNumber", "number"):
		if record.get(k):
			return str(record[k])
	return str(record.get("id") or "?")


# ---------------------------------------------------------------------------
# Fortschritt / Watermark in der Objekttyp-Zeile der Settings
# ---------------------------------------------------------------------------
def _save_progress(key: str, run_name: str, page_no: int) -> None:
	frappe.db.set_value(
		"WeClapp Sync Object Type",
		{"parent": "WeClapp Settings", "object_type": key},
		{"progress_run": run_name, "progress_page": page_no},
		update_modified=False,
	)


def _finish_type(key: str, watermark_ms: int) -> None:
	frappe.db.set_value(
		"WeClapp Sync Object Type",
		{"parent": "WeClapp Settings", "object_type": key},
		{
			"last_sync_ms": str(int(watermark_ms)),  # Data-Feld (Epoch ms sprengt MySQL-INT)
			"last_sync_at": now_datetime(),
			"progress_run": None,
			"progress_page": 0,
		},
		update_modified=False,
	)


def _result_payload(res: RunResult) -> dict:
	return {
		"run": res.run_name,
		"mode": res.mode,
		"processed": res.total_processed,
		"failed": res.total_failed,
		"types": [
			{"key": t.key, "status": t.status, "processed": t.processed, "failed": t.failed, "skipped": t.skipped}
			for t in res.types
		],
	}
