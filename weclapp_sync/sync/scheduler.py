"""Scheduler-Anbindung: der Cron-Tick enqueued nur einen Background-Job, er synct nicht selbst."""

from __future__ import annotations

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime

from weclapp_sync.sync.engine import MODE_DELTA, create_run, run_delta_sync
from weclapp_sync.sync.settings import get_settings

_QUEUE = "long"
_JOB_ID = "weclapp_sync_delta"
# Zusätzlicher Puffer über das jeweilige Job-Timeout hinaus, bevor recover_stale_runs zuschlägt -
# RQ braucht nach Ablauf des Timeouts selbst noch einen Moment, um den Job wirklich zu beenden.
_STALE_BUFFER_HOURS = 0.5


def enqueue_due_delta_sync() -> None:
	"""Läuft jede Minute (siehe hooks.py). Prüft, ob laut Settings ein Delta-Sync fällig ist,
	und enqueued dann genau einen langlaufenden Job. Kein Doppel-Enqueue dank fester job_id."""
	settings = get_settings()
	if not settings.enabled or not settings.enable_scheduled_delta:
		return

	if _has_running_run():
		return

	if not _is_due(settings):
		return

	if frappe.get_all("RQ Job", filters={"job_name": _JOB_ID, "status": ("in", ("queued", "started"))}, limit=1):
		return

	# Run-Doc synchron VOR dem Enqueue auf "Running" setzen (nicht erst im Job selbst) - sonst
	# kann in der Lücke zwischen Enqueue und tatsächlichem Job-Start ein manueller Vollimport-
	# Start `_has_running_run()` ebenfalls leer vorfinden und parallel loslegen (Bugfix
	# 2026-09-16 - symmetrisches Gegenstück zum selben Fix in
	# weclapp_settings.start_full_import()).
	run = create_run(MODE_DELTA)

	frappe.enqueue(
		run_delta_sync,
		queue=_QUEUE,
		job_id=_JOB_ID,
		timeout=settings.delta_job_timeout or 3600,
		enqueue_after_commit=True,
		run_name=run.name,
	)


def recover_stale_runs() -> None:
	"""Sicherheitsnetz (stündlich): Runs, die deutlich länger "Running" sind, als ihr eigenes
	Job-Timeout erlaubt, aber deren Worker weg ist, als abgebrochen markieren - sonst blockiert
	_has_running_run() für immer.

	**Bugfix 2026-09-16:** vorher ein fester `_STALE_HOURS = 1`-Cutoff für ALLE Läufe - ein
	Vollimport mit aktiviertem Bild-/Dokument-Sync kann aber legitim mehrere Stunden dauern
	(`full_import_job_timeout`, Default 6h). Der Cutoff richtet sich jetzt nach dem Timeout des
	jeweiligen Laufmodus, damit ein gesunder Langläufer nicht mittendrin faelschlich als "stale"
	markiert wird (engine._save_progress() setzt inzwischen ohnehin einen Heartbeat auf
	`modified`, das hier ist nur noch das Netz für einen wirklich toten Worker)."""
	settings = get_settings()
	timeouts_s = {
		"Full Import": int(settings.full_import_job_timeout or 21600),
		"Delta Sync": int(settings.delta_job_timeout or 3600),
	}
	for run in frappe.get_all(
		"WeClapp Sync Run", filters={"status": "Running"}, fields=["name", "mode", "modified"]
	):
		timeout_h = timeouts_s.get(run.mode, 3600) / 3600.0
		cutoff = add_to_date(now_datetime(), hours=-(timeout_h + _STALE_BUFFER_HOURS))
		if get_datetime(run.modified) >= cutoff:
			continue
		doc = frappe.get_doc("WeClapp Sync Run", run.name)
		doc.status = "Aborted (stale)"
		doc.finished_at = now_datetime()
		doc.flags.ignore_permissions = True
		doc.save()
	frappe.db.commit()


def _has_running_run() -> bool:
	"""Irgendein Lauf (Vollimport ODER Delta) noch "Running"? **Bugfix 2026-09-12:** prüfte
	bisher nur denselben Modus (`mode == "Delta Sync"`) - der Scheduler-Tick hat dadurch einen
	Delta-Sync (WC-SYNC-00032) parallel zu einem noch laufenden Vollimport (WC-SYNC-00031)
	enqueued. Beide liefen gleichzeitig gegen dieselbe WeClapp-Instanz/ERPNext-DB - Rate-Limit-
	Konkurrenz und ein Race beim Upsert (Existenzprüfung + Insert sind zwischen zwei Prozessen
	nicht atomar, Gefahr doppelt angelegter Datensätze). Live beobachtet: der Vollimport blieb
    danach auf `purchase_order`/`purchase_invoice` stehen, obwohl `abort_requested=1` gesetzt war."""
	return bool(frappe.get_all("WeClapp Sync Run", filters={"status": "Running"}, limit=1))


def _is_due(settings) -> bool:
	interval_min = int(settings.delta_interval_minutes or 15)
	last = frappe.db.get_value(
		"WeClapp Sync Run",
		filters={"mode": "Delta Sync", "status": ("like", "Completed%")},
		fieldname="started_at",
		order_by="started_at desc",
	)
	if not last:
		return True
	return now_datetime() >= add_to_date(last, minutes=interval_min)
