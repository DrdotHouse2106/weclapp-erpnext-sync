"""Scheduler-Anbindung: der Cron-Tick enqueued nur einen Background-Job, er synct nicht selbst."""

from __future__ import annotations

import frappe
from frappe.utils import add_to_date, now_datetime

from weclapp_sync.sync.engine import run_delta_sync
from weclapp_sync.sync.settings import get_settings

_QUEUE = "long"
_JOB_ID = "weclapp_sync_delta"
_STALE_HOURS = 1


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

	frappe.enqueue(
		run_delta_sync,
		queue=_QUEUE,
		job_id=_JOB_ID,
		timeout=settings.delta_job_timeout or 3600,
		enqueue_after_commit=True,
	)


def recover_stale_runs() -> None:
	"""Sicherheitsnetz (stündlich): Runs, die seit > _STALE_HOURS "Running" sind, aber deren
	Worker weg ist, als abgebrochen markieren - sonst blockiert _has_running_run() für immer."""
	cutoff = add_to_date(now_datetime(), hours=-_STALE_HOURS)
	for name in frappe.get_all(
		"WeClapp Sync Run",
		filters={"status": "Running", "modified": ("<", cutoff)},
		pluck="name",
	):
		doc = frappe.get_doc("WeClapp Sync Run", name)
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
