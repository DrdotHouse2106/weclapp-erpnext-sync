import frappe
from frappe.model.document import Document

from weclapp_sync.sync import registry

# Erklärt, warum ein Objekttyp KEINEN eigenen Mapper hat (und ob das dauerhaft so bleibt oder
# noch kommt) - "(Mapper fehlt)" allein legt bei jedem unregistrierten Typ nahe, es sei nur noch
# nicht gebaut. Für article_price stimmt das nicht (steckt dauerhaft in article._sync_prices()).
_UNREGISTERED_NOTES = {
	"article_price": "steckt in „Artikel“, kein eigener Sync nötig",
	"sales_payment": "erst für Live-Betrieb geplant, siehe CLAUDE.md",
	"purchase_payment": "erst für Live-Betrieb geplant, siehe CLAUDE.md",
}

# WeClapp-tax-Feld -> Zielspalte in WeClapp Tax Mapping.
# defaultNominalAccountNumber wird je nach Ein-/Verkauf auf income_ bzw. expense_account
# gemappt (siehe populate_tax_mapping).
_TAX_FIELD_MAP = {
	"defaultNominalAccountNumber": "income_account",
	"accountNumber": "tax_account",
	"contraAccountNumber": "contra_account",
	"defaultDiscountAccountNumber": "discount_account",
}

_PURCHASE_TAX_TYPES = {"INPUT_VAT", "INPUT_VAT_REVERSED", "IMPORT_VAT", "IMPORT_SALES_TAX"}


def _is_purchase_tax(t: dict) -> bool:
	tt = t.get("taxType") or ""
	if tt in _PURCHASE_TAX_TYPES:
		return True
	# Fallback über den Namen (WeClapp-Konvention "(EK)" = Einkauf, "Vorsteuer"/"Erwerb")
	nm = (t.get("name") or "").lower()
	return "(ek)" in nm or "vorsteuer" in nm or "erwerb" in nm


def _account_nature(wc_field: str, is_purchase: bool) -> tuple[str, str | None]:
	"""(root_type, account_type) für ein neu anzulegendes Konto."""
	if wc_field == "defaultNominalAccountNumber":
		return ("Expense", "Expense Account") if is_purchase else ("Income", "Income Account")
	if wc_field == "accountNumber":
		return ("Asset", "Tax") if is_purchase else ("Liability", "Tax")
	if wc_field == "contraAccountNumber":
		# Reverse-Charge-Gegenbuchung: USt-Seite
		return ("Liability", "Tax")
	# defaultDiscountAccountNumber = Skontokonto: 3xxx erhaltene Skonti (Aufwand),
	# 8xxx gewährte Skonti (Erlös-mindernd)
	return ("Expense", None) if is_purchase else ("Income", None)


_SKR03_NAMES = {
	"1767": "USt im anderen EG-Land stpfl. Lieferung",
	"1775": "Umsatzsteuer nach § 13b UStG 16 %",
	"1787": "Umsatzsteuer § 13b UStG 19 %",
	"3123": "Innergemeinschaftlicher Erwerb ohne Vorsteuerabzug",
	"3151": "Erhaltene Skonti aus ig. Erwerb ohne Vorsteuerabzug",
	"3300": "Abziehbare Vorsteuer 7 %",
	"3400": "Abziehbare Vorsteuer 19 %",
	"3420": "Abziehbare Vorsteuer aus ig. Erwerb 7 %",
	"3425": "Abziehbare Vorsteuer aus ig. Erwerb 19 %",
	"3730": "Erhaltene Skonti",
	"3731": "Erhaltene Skonti 7 % Vorsteuer",
	"3736": "Erhaltene Skonti 19 % Vorsteuer",
	"3745": "Erhaltene Skonti aus ig. Erwerb",
	"3746": "Erhaltene Skonti aus ig. Erwerb 7 %",
	"3748": "Erhaltene Skonti § 13b UStG",
	"8100": "Steuerfreie Umsätze § 4 Nr. 8 ff. UStG",
	"8120": "Steuerfreie Umsätze Drittland",
	"8125": "Steuerfreie ig. Lieferung § 4 Nr. 1b UStG",
	"8320": "Im anderen EG-Land stpfl. Lieferungen",
	"8339": "Nicht steuerbare Umsätze (EG-Land / Drittland)",
	"8730": "Gewährte Skonti",
	"8731": "Gewährte Skonti 7 % USt",
	"8735": "Gewährte Skonti aus steuerfreien Umsätzen",
	"8736": "Gewährte Skonti 19 % USt",
	"8743": "Gewährte Skonti aus steuerfreien ig. Lieferungen",
	"8745": "Gewährte Skonti stpfl. EG-Lieferung",
}


class WeClappSettings(Document):
	def validate(self):
		self.ensure_object_type_rows()

	def on_update(self):
		# Preislisten der Preiskanal-Zeilen abgleichen (Name aus channel_label, Brutto-Haken).
		self._sync_all_channel_price_lists()

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
					"label": (
						spec.label
						if spec
						else f"{_fallback_label(key)}  ({_UNREGISTERED_NOTES.get(key, 'Mapper fehlt')})"
					),
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

	def _fetch_wc_taxes(self):
		from weclapp_sync.sync.settings import get_client

		client = get_client()
		client.open()
		try:
			return list(client.iter_all("tax"))
		finally:
			client.close()

	@frappe.whitelist()
	def populate_tax_mapping(self):
		"""Holt die WeClapp-`tax`-Liste (read-only) und legt/aktualisiert je eine Zeile an.

		WeClapp führt pro Steuer 4 Konten:
		- `defaultNominalAccountNumber` = Buchungskonto -> Erlöskonto (VALUE_ADDED_TAX) bzw.
		  Aufwands-/Wareneingangskonto (INPUT_VAT*)
		- `accountNumber` = USt-/VSt-Konto -> Steuerkonto
		- `contraAccountNumber` = Gegenkonto (Reverse-Charge / ig. Erwerb)
		- `defaultDiscountAccountNumber` = Skontokonto
		Aufgelöst über die Kontonummer im ERPNext-Kontenplan. Fehlt eine, bleibt das Feld leer
		und die Nummer landet in der Rückmeldung."""
		taxes = self._fetch_wc_taxes()
		company = self.company
		missing: dict[str, str] = {}

		def _acc(number):
			if not number:
				return None
			f = {"account_number": number, "company": company} if company else {"account_number": number}
			return frappe.db.get_value("Account", f, "name")

		# Nur Steuern mit mindestens einem in WeClapp hinterlegten Konto bekommen eine Zeile -
		# der Rest (ausländische Sätze, die FranceTec nie konfiguriert hat) wäre nur Rauschen.
		configured = {
			str(t["id"]): t for t in taxes if any(t.get(f) for f in _TAX_FIELD_MAP)
		}
		self.tax_mappings = [r for r in self.tax_mappings if r.wc_tax_id in configured]
		by_id = {row.wc_tax_id: row for row in self.tax_mappings}

		added = 0
		for tid, t in sorted(configured.items(), key=lambda kv: kv[1].get("name") or ""):
			is_purchase = _is_purchase_tax(t)
			nm = t.get("name") or ""
			row = by_id.get(tid)
			if row is None:
				row = self.append("tax_mappings", {})
				row.wc_tax_id = tid
				added += 1
			row.wc_tax_name = nm
			try:
				row.wc_rate = float(t.get("taxValue") or 0)
			except (TypeError, ValueError):
				row.wc_rate = 0

			# Kontospalten immer frisch aus WeClapp ableiten (WeClapp ist maßgeblich).
			row.income_account = None
			row.expense_account = None
			row.tax_account = None
			row.contra_account = None
			row.discount_account = None

			for wc_field, target_field in _TAX_FIELD_MAP.items():
				num = t.get(wc_field)
				if not num:
					continue
				tf = target_field
				if wc_field == "defaultNominalAccountNumber":
					tf = "expense_account" if is_purchase else "income_account"
				resolved = _acc(num)
				if resolved:
					setattr(row, tf, resolved)
				else:
					missing[num] = nm

		self.save()
		msg = (
			f"{len(configured)} WeClapp-Steuern mit hinterlegten Konten (von {len(taxes)} gesamt), "
			f"{added} neue Zeilen. Alle Kontospalten wurden aus WeClapp neu abgeleitet, "
			"Steuern ohne Konten entfernt."
		)
		if missing:
			lst = ", ".join(f"{n} ({d})" for n, d in sorted(missing.items()))
			msg += (
				f"\n\n{len(missing)} Konten fehlen im ERPNext-Kontenplan:\n{lst}\n\n"
				"Button 'Fehlende Steuerkonten anlegen (SKR03)' klicken, dann diesen erneut."
			)
		return msg

	@frappe.whitelist()
	def create_missing_tax_accounts(self):
		"""Legt die von WeClapp-Steuern referenzierten, im Kontenplan fehlenden Konten an (SKR03).
		root_type/Kontoart aus dem WeClapp-Feld + taxType; Parent von einem Geschwisterkonto."""
		if not self.company:
			frappe.throw("Bitte zuerst die Company setzen.")

		taxes = self._fetch_wc_taxes()

		# number -> (root_type, account_type, wc_tax_name)
		want: dict[str, tuple[str, str | None, str]] = {}
		for t in taxes:
			is_purchase = _is_purchase_tax(t)
			nm = t.get("name") or ""
			for wc_field in _TAX_FIELD_MAP:
				num = t.get(wc_field)
				if num:
					want.setdefault(num, _account_nature(wc_field, is_purchase) + (nm,))

		def _acc(num):
			return frappe.db.get_value("Account", {"account_number": num, "company": self.company}, "name")

		def _sibling_parent(root_type):
			return frappe.db.get_value(
				"Account", {"company": self.company, "root_type": root_type, "is_group": 0}, "parent_account"
			)

		created, skipped = [], []
		for num, (root_type, acc_type, nm) in sorted(want.items()):
			if _acc(num):
				continue
			parent = _sibling_parent(root_type)
			if not parent:
				skipped.append(f"{num} (kein Parent für {root_type})")
				continue
			try:
				doc = frappe.new_doc("Account")
				doc.account_number = num
				doc.account_name = (_SKR03_NAMES.get(num) or nm or num)[:140]
				doc.company = self.company
				doc.parent_account = parent
				doc.root_type = root_type
				if acc_type:
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
			out += f"\n\nUebersprungen ({len(skipped)}):\n" + "\n".join(skipped)
		out += "\n\nJetzt 'Steuer-Mapping aus WeClapp befuellen' erneut klicken."
		return out

	@frappe.whitelist()
	def populate_price_list_mappings(self):
		"""Legt je WeClapp-Preiskanal eine Zeile an. Kanal-Universum: NET1..NET9 + GROSS1..GROSS8
		(WeClapp-Standard) vereinigt mit den in `articlePrice` tatsächlich vorkommenden.
		Legt/benennt die ERPNext-Preisliste nach `channel_label` und setzt an ihr den
		Brutto-Haken (`custom_price_includes_tax`, falls das Feld existiert)."""
		from weclapp_sync.sync.settings import get_client

		client = get_client()
		client.open()
		try:
			used = {
				row.get("salesChannel")
				for row in client.iter_all("articlePrice", properties="id,salesChannel")
				if row.get("salesChannel")
			}
		finally:
			client.close()

		known = {f"NET{i}" for i in range(1, 10)} | {f"GROSS{i}" for i in range(1, 9)}
		channels = sorted(known | used, key=lambda c: (c[0] != "N", c))

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
			self._sync_channel_price_list(row)

		self.save()
		return (
			f"{len(channels)} Preiskanäle, {added} neue Zeilen. "
			"Bezeichnung eintragen + erneut klicken -> Preisliste wird so benannt; "
			"Brutto-Haken wird an der Preisliste gesetzt."
		)

	def _sync_channel_price_list(self, row) -> None:
		"""Stellt sicher, dass die zur Mapping-Zeile gehörende Preisliste existiert, so heißt
		wie `channel_label` und den Brutto-Haken passend gesetzt hat."""
		label = (row.channel_label or "").strip()
		desired = label or row.price_list or f"WeClapp {row.sales_channel}"

		# Auto-angelegte "WeClapp <Code>"-Liste auf die Bezeichnung umbenennen.
		if (
			row.price_list
			and label
			and row.price_list != desired
			and row.price_list.startswith("WeClapp ")
			and frappe.db.exists("Price List", row.price_list)
			and not frappe.db.exists("Price List", desired)
		):
			frappe.rename_doc("Price List", row.price_list, desired, ignore_permissions=True)
			row.price_list = desired

		if not row.price_list:
			if not frappe.db.exists("Price List", desired):
				pl = frappe.new_doc("Price List")
				pl.price_list_name = desired
				pl.selling = 1
				pl.currency = self.default_currency or "EUR"
				pl.flags.ignore_permissions = True
				pl.insert()
			row.price_list = desired

		# Brutto-Haken an der Preisliste (custom_price_includes_tax) mit dem Kanal abgleichen.
		if row.price_list and frappe.get_meta("Price List").has_field("custom_price_includes_tax"):
			frappe.db.set_value(
				"Price List", row.price_list, "custom_price_includes_tax", 1 if row.prices_include_tax else 0
			)

	def _sync_all_channel_price_lists(self) -> None:
		for row in self.price_list_mappings:
			try:
				self._sync_channel_price_list(row)
			except Exception:
				frappe.log_error(
					title=f"WeClapp: Preisliste für {row.sales_channel}", message=frappe.get_traceback()
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

	# ------------------------------------------------------------------ Zusatzfelder
	@frappe.whitelist()
	def populate_custom_attribute_mapping(self):
		"""Holt alle WeClapp-`customAttributeDefinition` (read-only) und baut die Tabelle
		`custom_attribute_mappings` neu auf. Vorhandene Nutzer-Auswahl bleibt erhalten."""
		from weclapp_sync.sync.settings import get_client
		from weclapp_sync.setup import custom_attribute_fields as caf

		client = get_client()
		client.open()
		try:
			definitions = list(client.iter_all("customAttributeDefinition"))
		finally:
			client.close()

		total, new = caf.rebuild_mapping_rows(self, definitions)
		self.save()
		return (
			f"{total} Zusatzfelder geladen ({new} neu). Bei den gewünschten „Importieren“ "
			f"anhaken, dann „Ausgewählte Felder anlegen“."
		)

	@frappe.whitelist()
	def apply_custom_attribute_fields(self):
		"""Legt die Custom Fields für alle aktivierten Mapping-Zeilen an (idempotent,
		selbstheilend - kettet auch schon vorhandene Felder bei Bedarf neu ein)."""
		from weclapp_sync.setup import custom_attribute_fields as caf

		res = caf.apply_custom_attribute_fields()
		self.reload()
		if not res["enabled_rows"]:
			return "Keine Zeile aktiviert – nichts angelegt."
		doctypes = ", ".join(res["doctypes"]) or "–"
		return (
			f"{res['created']} Feld(er) neu angelegt, {res.get('repaired', 0)} umgekettet "
			f"(Reihenfolge repariert) auf: {doctypes}. "
			f"{res['enabled_rows']} Zusatzfeld(er) sind für den Sync aktiv."
		)


def _fallback_label(key: str) -> str:
	return key.replace("_", " ").title()
