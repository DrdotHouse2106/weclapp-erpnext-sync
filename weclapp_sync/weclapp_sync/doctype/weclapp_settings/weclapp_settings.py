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

		WeClapp führt pro Steuer: `accountNumber` (USt/VSt-Konto), `defaultNominalAccountNumber`
		(Buchungskonto = Erlös bzw. Aufwand/Wareneingang). `taxType == "INPUT_VAT"` ->
		Einkauf (Aufwandskonto), sonst Verkauf (Erlöskonto). Konten werden über die
		Nummer im ERPNext-Kontenplan aufgelöst - fehlt sie, bleibt das Feld leer und die
		Nummer landet in der Rückmeldung ("fehlende Konten")."""
		from weclapp_sync.sync.settings import get_client

		client = get_client()
		client.open()
		try:
			taxes = list(client.iter_all("tax"))
		finally:
			client.close()

		by_id = {row.wc_tax_id: row for row in self.tax_mappings}
		company = self.company
		missing: dict[str, str] = {}

		def _acc(number: str | None) -> str | None:
			if not number:
				return None
			filters = {"account_number": number, "company": company} if company else {"account_number": number}
			name = frappe.db.get_value("Account", filters, "name")
			return name

		added = 0
		used_numbers: dict[str, str] = {}
		for t in taxes:
			tid = str(t.get("id"))
			is_purchase = t.get("taxType") == "INPUT_VAT"
			nominal = t.get("defaultNominalAccountNumber")
			vat = t.get("accountNumber")
			for num in (nominal, vat):
				if num:
					used_numbers[num] = t.get("name") or ""

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

			nominal_acc = _acc(nominal)
			vat_acc = _acc(vat)
			if is_purchase:
				if not row.expense_account:
					row.expense_account = nominal_acc
			else:
				if not row.income_account:
					row.income_account = nominal_acc
			if not row.tax_account:
				row.tax_account = vat_acc

			if nominal and not nominal_acc:
				missing[nominal] = used_numbers.get(nominal, "")
			if vat and not vat_acc:
				missing[vat] = used_numbers.get(vat, "")

		self.save()
		msg = f"{len(taxes)} WeClapp-Steuern verarbeitet, {added} neue Zeilen."
		if missing:
			lst = ", ".join(f"{n} ({d})" for n, d in sorted(missing.items()))
			msg += (
				f"\n\n{len(missing)} Konten fehlen im ERPNext-Kontenplan (in WeClapp referenziert, "
				f"hier nicht vorhanden). Nummer (Bezeichnung):\n{lst}\n\n"
				"Diese Konten im Kontenplan anlegen (SKR03) und den Button erneut klicken - "
				"dann füllen sich die leeren Zeilen automatisch."
			)
		return msg

	@frappe.whitelist()
	def create_missing_tax_accounts(self):
		"""Legt die von WeClapp-Steuern referenzierten, im ERPNext-Kontenplan fehlenden Konten
		an (SKR03). Nature aus dem WeClapp-taxType:
		- Buchungskonto (defaultNominalAccountNumber): VALUE_ADDED_TAX -> Erlöskonto (Income),
		  INPUT_VAT -> Aufwand (Expense)
		- Steuerkonto (accountNumber): VALUE_ADDED_TAX -> USt (Liability, Tax),
		  INPUT_VAT -> VSt (Asset, Tax)
		Parent + genaue Kontoart werden von einem vorhandenen Geschwisterkonto übernommen."""
		from weclapp_sync.sync.settings import get_client

		if not self.company:
			frappe.throw("Bitte zuerst die Company setzen.")

		client = get_client()
		client.open()
		try:
			taxes = list(client.iter_all("tax"))
		finally:
			client.close()

		# number -> (root_type, account_type, name)
		want: dict[str, tuple[str, str, str]] = {}
		for t in taxes:
			is_purchase = t.get("taxType") == "INPUT_VAT"
			nm = t.get("name") or ""
			nominal = t.get("defaultNominalAccountNumber")
			vat = t.get("accountNumber")
			if nominal:
				want.setdefault(
					nominal,
					("Expense", "Expense Account", nm) if is_purchase else ("Income", "Income Account", nm),
				)
			if vat:
				want.setdefault(vat, ("Asset", "Tax", nm) if is_purchase else ("Liability", "Tax", nm))

		def _acc(num):
			return frappe.db.get_value("Account", {"account_number": num, "company": self.company}, "name")

		# Geschwister-Parent je root_type (ein vorhandenes Nicht-Gruppen-Konto)
		def _sibling_parent(root_type: str) -> str | None:
			name = frappe.db.get_value(
				"Account",
				{"company": self.company, "root_type": root_type, "is_group": 0},
				"parent_account",
			)
			return name

		# SKR03-Standardbezeichnungen für die typischen fehlenden Konten (die WeClapp-API
		# liefert nur den Steuernamen, nicht den Kontonamen).
		skr03_names = {
			"1767": "USt im anderen EG-Land stpfl. Lieferung",
			"1775": "Umsatzsteuer nach § 13b UStG 16 %",
			"3123": "Innergemeinschaftlicher Erwerb ohne Vorsteuerabzug",
			"3300": "Abziehbare Vorsteuer 7 %",
			"3400": "Abziehbare Vorsteuer 19 %",
			"3420": "Abziehbare Vorsteuer aus innergemeinschaftlichem Erwerb 7 %",
			"3425": "Abziehbare Vorsteuer aus innergemeinschaftlichem Erwerb 19 %",
			"8100": "Steuerfreie Umsätze § 4 Nr. 8 ff. UStG",
			"8120": "Steuerfreie Umsätze Drittland",
			"8125": "Steuerfreie innergemeinschaftliche Lieferung § 4 Nr. 1b UStG",
			"8320": "Im anderen EG-Land stpfl. Lieferungen",
			"8339": "Nicht steuerbare Umsätze (EG-Land / Drittland)",
		}

		created, skipped = [], []
		for num, (root_type, acc_type, nm) in sorted(want.items()):
			if _acc(num):
				continue
			parent = _sibling_parent(root_type)
			if not parent:
				skipped.append(f"{num} (kein Parent für {root_type})")
				continue
			try:
				label = skr03_names.get(num) or nm or num
				doc = frappe.new_doc("Account")
				doc.account_number = num
				doc.account_name = label[:140]
				doc.company = self.company
				doc.parent_account = parent
				doc.root_type = root_type
				doc.account_type = acc_type
				doc.flags.ignore_permissions = True
				doc.insert()
				created.append(doc.name)
			except Exception as e:
				skipped.append(f"{num}: {e}")

		frappe.db.commit()
		out = f"{len(created)} Konten angelegt."
		if created:
			out += "\n" + "\n".join(created)
		if skipped:
			out += f"\n\nÜbersprungen ({len(skipped)}):\n" + "\n".join(skipped)
		out += "\n\nJetzt 'Steuer-Mapping aus WeClapp befuellen' erneut klicken."
		return out

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
			row = by_channel.get(channel)
			if row is None:
				row = self.append("price_list_mappings", {})
				row.sales_channel = channel
				added += 1
			row.prices_include_tax = 1 if is_gross else 0

			# Preisliste nur anlegen, wenn die Zeile noch keine hat. Name = Bezeichnung (falls
			# gesetzt) sonst "WeClapp <Code>". Eine schon eingetragene Preisliste bleibt unangetastet.
			if not row.price_list:
				list_name = (row.channel_label or "").strip() or f"WeClapp {channel}"
				if not frappe.db.exists("Price List", list_name):
					pl = frappe.new_doc("Price List")
					pl.price_list_name = list_name
					pl.selling = 1
					pl.currency = self.default_currency or "EUR"
					pl.flags.ignore_permissions = True
					pl.insert()
				row.price_list = list_name

		self.save()
		return (
			f"{len(channels)} Preiskanäle, {added} neue Zeilen. "
			"Tipp: Bezeichnung eintragen und den Button erneut klicken, dann heißt die neu "
			"angelegte Preisliste so."
		)

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
