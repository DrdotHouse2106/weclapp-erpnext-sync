import frappe
from frappe.model.document import Document

from weclapp_sync.sync import registry


class WeClappSettings(Document):
	def validate(self):
		self.ensure_object_type_rows()

	# ------------------------------------------------------------------ Objekttyp-Zeilen
	def ensure_object_type_rows(self):
		"""Sorgt dafür, dass für jeden Schlüssel aus registry.SYNC_ORDER genau eine Zeile
		existiert - in der richtigen Reihenfolge, mit aktuellem Label/Mapper-Status."""
		existing = {row.object_type: row for row in self.object_types}
		self.object_types = []
		for key in registry.SYNC_ORDER:
			spec = registry.get_spec(key)
			old = existing.get(key)
			self.append(
				"object_types",
				{
					"object_type": key,
					"label": (spec.label if spec else _fallback_label(key))
					+ ("" if spec else "  (Mapper fehlt)"),
					"enabled": old.enabled if old else 0,
					"last_sync_ms": old.last_sync_ms if old else 0,
					"last_sync_at": old.last_sync_at if old else None,
					"progress_run": old.progress_run if old else None,
					"progress_page": old.progress_page if old else 0,
				},
			)

	# ------------------------------------------------------------------ Buttons (JS -> hier)
	@frappe.whitelist()
	def test_weclapp_connection(self):
		"""Read-only Verbindungstest: ruft EINEN GET /customer/count auf."""
		from weclapp_sync.sync.settings import get_client

		try:
			client = get_client()
			client.open()
			try:
				count = client.count("customer")
			finally:
				client.close()
			msg = f"OK – Verbindung steht. customer/count = {count}"
		except Exception as e:
			msg = f"FEHLER: {type(e).__name__}: {e}"

		self.db_set("connection_result", msg)
		return msg

	@frappe.whitelist()
	def refresh_object_type_list(self):
		self.ensure_object_type_rows()
		self.save()
		return "Objekttyp-Liste aktualisiert."

	@frappe.whitelist()
	def start_full_import(self):
		"""Enqueued den Vollimport als langlaufenden Background-Job."""
		if not self.enabled:
			frappe.throw("WeClapp Sync ist deaktiviert.")

		if frappe.get_all(
			"WeClapp Sync Run", filters={"mode": "Full Import", "status": "Running"}, limit=1
		):
			frappe.throw("Es läuft bereits ein Vollimport.")

		frappe.enqueue(
			"weclapp_sync.sync.engine.run_full_import",
			queue="long",
			job_id="weclapp_sync_full_import",
			timeout=self.delta_job_timeout or 3600,
		)
		return "Vollimport wurde gestartet – Fortschritt unter „WeClapp Sync Run“."


def _fallback_label(key: str) -> str:
	return key.replace("_", " ").title()
