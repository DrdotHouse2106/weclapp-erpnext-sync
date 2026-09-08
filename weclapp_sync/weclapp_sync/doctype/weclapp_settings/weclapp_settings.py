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
	def populate_tax_mapping(self):
		"""Holt die WeClapp-`tax`-Liste (read-only) und legt/aktualisiert je eine Zeile an.
		Konten werden über die WeClapp-Kontonummern (`defaultNominalAccountNumber` = Erlös,
		`accountNumber` = USt/VSt) automatisch aufgelöst, sofern im ERPNext-Kontenplan
		vorhanden - sonst bleibt das Feld leer und muss geprüft werden."""
		from weclapp_sync.sync.settings import get_client

		client = get_client()
		client.open()
		try:
			taxes = list(client.iter_all("tax"))
		finally:
			client.close()

		by_id = {row.wc_tax_id: row for row in self.tax_mappings}
		company = self.company

		def _acc(number: str | None, root_type: str | None = None) -> str | None:
			if not number:
				return None
			filters = {"account_number": number, "company": company} if company else {"account_number": number}
			return frappe.db.get_value("Account", filters, "name")

		added = 0
		for t in taxes:
			tid = str(t.get("id"))
			row = by_id.get(tid)
			if row is None:
				row = self.append("tax_mappings", {})
				row.wc_tax_id = tid
				added += 1
			row.wc_tax_name = t.get("name")
			try:
				row.wc_rate = float(t.get("taxValue") or 0)
			except (TypeError, ValueError):
				row.wc_rate = 0
			if not row.income_account:
				row.income_account = _acc(t.get("defaultNominalAccountNumber"))
			if not row.tax_account:
				row.tax_account = _acc(t.get("accountNumber"))

		self.save()
		return f"{len(taxes)} WeClapp-Steuern verarbeitet, {added} neue Zeilen."

	@frappe.whitelist()
	def populate_price_list_mappings(self):
		"""Sammelt die distinct salesChannels aus WeClapp `articlePrice`, legt je Kanal eine
		ERPNext-Preisliste an (falls noch nicht vorhanden) und trägt sie hier ein.
		NET* = netto, GROSS* = brutto (nur Info-Flag)."""
		from weclapp_sync.sync.settings import get_client

		client = get_client()
		client.open()
		try:
			channels = sorted(
				{
					row.get("salesChannel")
					for row in client.iter_all("articlePrice", properties="id,salesChannel")
					if row.get("salesChannel")
				}
			)
		finally:
			client.close()

		by_channel = {row.sales_channel: row for row in self.price_list_mappings}
		added = 0
		for channel in channels:
			is_gross = channel.upper().startswith("GROSS")
			list_name = f"WeClapp {channel}"
			if not frappe.db.exists("Price List", list_name):
				pl = frappe.new_doc("Price List")
				pl.price_list_name = list_name
				pl.selling = 1
				pl.currency = self.default_currency or "EUR"
				pl.flags.ignore_permissions = True
				pl.insert()

			row = by_channel.get(channel)
			if row is None:
				row = self.append("price_list_mappings", {})
				row.sales_channel = channel
				row.price_list = list_name
				added += 1
			row.prices_include_tax = 1 if is_gross else 0

		self.save()
		return f"{len(channels)} Preiskanäle, {added} neue Zeilen."

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
