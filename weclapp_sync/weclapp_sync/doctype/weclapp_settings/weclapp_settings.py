import frappe
from frappe.model.document import Document

from weclapp_sync.sync import registry

# Erklärt, warum ein Objekttyp KEINEN eigenen Mapper hat und noch kommt (Typen, die dauerhaft
# keinen eigenen Mapper brauchen - z.B. article_price, steckt in article._sync_prices() - stehen
# gar nicht erst in registry.SYNC_ORDER, damit sie hier auch nicht als Zeile auftauchen).
_UNREGISTERED_NOTES = {
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

# WeClapp-Vertriebsweg -> Marke ("Versandabsender", Doctype der "ERPNext Versand"-App) - steuert
# dort Kopfbogen + Absenderadresse auf Versandlabels. Nutzer-Vorgabe 2026-09-18 (Vertriebswege-
# Liste aus WeClapp), zweimal übereinstimmend bestätigt: gegen die Vertriebsweg-Bezeichnungen aus
# der Nutzerliste UND gegen unsere eigenen, schon länger bestehenden `price_list`-Namen in
# `price_list_mappings` (z.B. "Amazon" -> GROSS7, "kfz-isolierung.de Brutto" -> GROSS3). Bewusst
# NICHT vollständig - WeClapp kennt noch "NET10" (in der Instanz bisher ohne Marke/ohne Daten,
# taucht auch in `articlePrice` nie auf) sowie zwei weitere Versandabsender-Stammdaten
# ("EntenFrisch"/"LesDeux"), die der Nutzer explizit für diese Zuordnung ausgeschlossen hat.
_CHANNEL_VERSANDABSENDER = {
	"GROSS1": "FranceTec",
	"GROSS2": "FranceTec",
	"GROSS3": "kfz-isolierung.de",
	"GROSS4": "Federkugel.store",
	"GROSS5": "Gisbert-Frech-Verlag",
	"GROSS6": "FranceTec",
	"GROSS7": "FranceTec",
	"GROSS8": "schmelzkammer.de",
	"NET1": "FranceTec",
	"NET2": "FranceTec",
	"NET3": "FranceTec",
	"NET4": "Gisbert-Frech-Verlag",
	"NET5": "Gisbert-Frech-Verlag",
	"NET6": "FranceTec",
	"NET7": "FranceTec",
	"NET8": "FranceTec",
	"NET9": "kfz-isolierung.de",
}


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



# ---------------------------------------------------------------------------------------------
# Kontenanlage aus WeClapp - Modul-Funktionen (nicht Methoden), damit sie sowohl direkt als auch
# aus einem Hintergrund-Job (frappe.enqueue mit dotted path) ohne Doc-Instanz aufrufbar sind.
# Geteilt zwischen WeClappSettings.create_missing_ledger_accounts() (gezielt einzelne
# Kontonummern) und .import_used_ledger_accounts() (Massen-Scan "jemals gebucht") - siehe deren
# Docstrings für die Vorgeschichte (2026-09-16, Cross-Session-Anfrage von versand_integration).
# ---------------------------------------------------------------------------------------------
def _ledger_reference():
	"""Lädt WeClapps kompletten Kontenrahmen (`ledgerAccount`, ~7739 Zeilen, nur 5 schmale
	Felder - ca. 1-2 MB, einmalig für die Dauer eines Aufrufs im Speicher, wie schon die
	kleineren Referenzlisten in populate_tax_mapping()/populate_custom_attribute_mapping() -
	NICHT Teil des laufenden Datensatz-Syncs, wo Vollmaterialisierung tabu ist). Rückgabe:
	(accountNumber -> Datensatz, parentAccountId -> [Kind-Datensätze])."""
	from weclapp_sync.sync.settings import get_client

	client = get_client()
	client.open()
	try:
		ledger = list(
			client.iter_all(
				"ledgerAccount", properties="id,accountNumber,type,description,parentAccountId"
			)
		)
	finally:
		client.close()
	by_number = {a["accountNumber"]: a for a in ledger if a.get("accountNumber")}
	# Nur IMPERSONAL_ACCOUNT-Geschwister sammeln (siehe Bugfix 2026-09-17 in
	# _erpnext_sibling() - PERSONAL_ACCOUNT-Einträge unter demselben WeClapp-Elternknoten
	# würden sonst gegen die ~6200 individuellen Debitoren-/Kreditorenkonten in ERPNext
	# matchen, die ALLE unter genau zwei Sammelgruppen (debtor_/creditor_parent_account)
	# liegen - das machte live jedes einzige Sachkonto fälschlich "mehrdeutig".
	by_parent: dict[str, list[dict]] = {}
	for a in ledger:
		if a.get("type") == "IMPERSONAL_ACCOUNT":
			by_parent.setdefault(a.get("parentAccountId"), []).append(a)
	return by_number, by_parent


def _erpnext_sibling(acc: dict, by_parent: dict, company: str):
	"""Geschwisterkonto (gleicher WeClapp-Elternknoten) in ERPNext - nur eindeutig, wenn ALLE in
	ERPNext gefundenen Geschwister derselben Gruppe zugeordnet sind.

	**Bugfix 2026-09-16 (im Probelauf entdeckt, vor dem Ausliefern):** eine erste Version nahm
	einfach das ERSTE gefundene Geschwisterkonto - WeClapps Gruppe "B1660" ("Kassenbestand ...
	Guthaben bei Kreditinstituten") bündelt aber live Kasse, Postbank, PayPal, Amazon Pay,
	SumUp, eBay etc. in EINER Gruppe, während ERPNext das auf mehrere Untergruppen aufteilt
	("Kasse - FT" vs. "Bank - FT" vs. ...) - "1270 N26" (ein Bankkonto) wäre damit fälschlich
	unter "Kasse - FT"/`account_type "Cash"` gelandet, nur weil "1000 Kasse" zufällig zuerst in
	der Geschwisterliste stand. Bei Uneinigkeit unter den gefundenen Geschwistern wird jetzt
	NICHT geraten, sondern als mehrdeutig übersprungen (Rückmeldung nennt die widersprüchlichen
	Gruppen).

	**Bugfix 2026-09-17 (Live-Fund beim ersten echten Lauf von `import_used_ledger_accounts`):**
	alle 70 fehlenden Konten wurden als "mehrdeutig" übersprungen, IMMER mit demselben Konflikt
	(Debitoren-Sammelgruppe vs. Kreditoren-Sammelgruppe) - obwohl viele davon laut Vorab-
	Simulation eindeutig hätten sein müssen. Ursache: `by_parent` (jetzt in `_ledger_reference()`
	gefiltert) enthielt auch WeClapps `PERSONAL_ACCOUNT`-Einträge - teilt sich ein echtes
	Sachkonto seinen WeClapp-Elternknoten mit irgendeinem Debitoren-/Kreditoren-Platzhalter aus
	dem SKR03-Vorlagenkontenrahmen, matchte dessen Kontonummer gegen eines der ~6200 in ERPNext
	individuell angelegten Personenkonten - die liegen ALLE unter genau zwei Sammelgruppen
	(`debtor_/creditor_parent_account`), was praktisch jedes Sachkonto künstlich mehrdeutig
	machte. `by_parent` enthält jetzt nur noch `IMPERSONAL_ACCOUNT`-Geschwister."""
	matches = []
	for other in by_parent.get(acc.get("parentAccountId"), []):
		num = other.get("accountNumber") or ""
		if not num.isdigit() or num == acc.get("accountNumber"):
			continue
		row = frappe.db.get_value(
			"Account",
			{"account_number": num, "company": company},
			["name", "parent_account", "account_type"],
			as_dict=True,
		)
		if row:
			matches.append(row)
	if not matches:
		return None, "kein Geschwisterkonto in ERPNext gefunden"
	parents = sorted({m.parent_account for m in matches})
	if len(parents) > 1:
		return None, f"mehrdeutig - Geschwisterkonten liegen in ERPNext unter verschiedenen Gruppen ({', '.join(parents)}), bitte manuell anlegen"
	return matches[0], None


def _prefix_sibling(acc: dict, company: str, exclude_parents: set[str]):
	"""Fallback-Geschwistersuche über die Kontonummer, wenn `_erpnext_sibling()` (WeClapps
	eigener Elternknoten) NICHTS findet (nicht bei "mehrdeutig" - eine bereits erkannte
	Mehrdeutigkeit wird nicht durch einen zweiten, gröberen Versuch übergangen).

	Eingeführt 2026-09-18, Nutzer-Wunsch nach dem Live-Fund: selbst nach dem Bugfix in
	`_erpnext_sibling()` (Personenkonten raus) fand die Elternknoten-Suche bei ALLEN 70 aus
	`accountingTransaction` gescannten Konten kein Geschwister - WeClapps SKR03-Vorlage bildet
	die Hierarchie offenbar sehr fein/tief ab (Klasse -> Gruppe -> Untergruppe -> Konto), viele
	Sachkonten hängen an einem sehr spezifischen, in ERPNexts schlanker Teilmenge (nur
	tatsächlich genutzte Konten) praktisch nie zufällig auch besetzten Zweig.

	SKR03 ist aber eine standardisierte Nummerierung, die WeClapp und ERPNexts eigener
	Kontenplan-Import TEILEN - die Kontonummer selbst trägt also schon eine fachliche
	Gruppierung, unabhängig von WeClapps interner Baumtiefe. Testet Nummernpräfixe von 3 auf 2
	Ziffern (nicht bis auf 1 Ziffer - eine ganze Kontenklasse wie "4" wäre zu grob, würde
	fachlich sehr unterschiedliche Konten zusammenwerfen). Dieselbe Einstimmigkeits-Regel wie
	`_erpnext_sibling()`: uneinige Treffer -> mehrdeutig, nicht geraten. `exclude_parents`
	(Debitoren-/Kreditoren-Sammelgruppen) schließt Personenkonten aus denselben Gründen aus wie
	der `IMPERSONAL_ACCOUNT`-Filter in `_ledger_reference()` - Personenkontonummern sind
	ebenfalls rein numerisch und würden sonst über den Nummernpräfix genauso fälschlich als
	Geschwister erscheinen."""
	num = acc.get("accountNumber") or ""
	if not num.isdigit():
		return None, None
	for length in (3, 2):
		if len(num) <= length:
			continue
		prefix = num[:length]
		rows = frappe.get_all(
			"Account",
			filters={"company": company, "account_number": ("like", f"{prefix}%")},
			fields=["name", "parent_account", "account_type", "account_number"],
		)
		matches = [r for r in rows if r.account_number != num and r.parent_account not in exclude_parents]
		if not matches:
			continue
		parents = sorted({m.parent_account for m in matches})
		if len(parents) > 1:
			return None, (
				f"mehrdeutig (Nummernpräfix {prefix}) - Geschwisterkonten liegen in ERPNext unter "
				f"verschiedenen Gruppen ({', '.join(parents)}), bitte manuell anlegen"
			)
		return matches[0], None
	return None, None


def _create_ledger_accounts(accounts: list[dict], by_parent: dict, company: str) -> str:
	"""Legt die übergebenen WeClapp-`ledgerAccount`-Datensätze in ERPNext an, wo möglich. Nur
	echte Sachkonten (numerische `accountNumber`, `type=IMPERSONAL_ACCOUNT`) - WeClapps eigene
	Gruppen-Knoten (alphanumerische Codes wie "B1660") werden NICHT als eigene ERPNext-Gruppen
	angelegt, weil ERPNexts Kontenplan (SKR03-Import) eine eigene, andersartige Gruppenstruktur
	mit sprechenden statt WeClapp-internen Namen hat (live geprüft: ERPNext-Konto "1000 - Kasse
	- FT" hat keinen `account_number` an seiner Gruppe "Kasse - FT", WeClapp führt dieselbe
	Gruppe unter dem Code "B1660").

	**Erweiterung 2026-09-18:** findet `_erpnext_sibling()` (WeClapps eigener Elternknoten)
	nichts (nicht bei "mehrdeutig"), greift zusätzlich `_prefix_sibling()` als Fallback über die
	SKR03-Kontonummer selbst - siehe dessen Docstring für den Live-Fund, der das nötig machte."""
	existing_numbers = set(frappe.get_all("Account", filters={"company": company}, pluck="account_number"))
	settings = frappe.get_cached_doc("WeClapp Settings")
	exclude_parents = {settings.debtor_parent_account, settings.creditor_parent_account} - {None, ""}
	created, skipped = [], []
	for acc in sorted(accounts, key=lambda a: a.get("accountNumber") or ""):
		num = acc.get("accountNumber") or ""
		if num in existing_numbers:
			continue
		if acc.get("type") != "IMPERSONAL_ACCOUNT" or not num.isdigit():
			skipped.append(f"{num} ({acc.get('description')}) - kein normales Sachkonto")
			continue
		sibling, reason = _erpnext_sibling(acc, by_parent, company)
		if not sibling and reason == "kein Geschwisterkonto in ERPNext gefunden":
			sibling, prefix_reason = _prefix_sibling(acc, company, exclude_parents)
			if sibling:
				reason = None
			elif prefix_reason:
				reason = prefix_reason
		if not sibling:
			skipped.append(f"{num} ({acc.get('description')}) - {reason}")
			continue
		try:
			doc = frappe.new_doc("Account")
			doc.account_number = num
			doc.account_name = (acc.get("description") or num)[:140]
			doc.company = company
			doc.parent_account = sibling.parent_account
			if sibling.account_type:
				doc.account_type = sibling.account_type
			doc.flags.ignore_permissions = True
			doc.insert()
			created.append(doc.name)
			existing_numbers.add(num)
		except Exception as e:
			skipped.append(f"{num} ({acc.get('description')}): {e}")

	frappe.db.commit()
	out = f"{len(created)} Konten angelegt."
	if created:
		out += "\n" + "\n".join(created)
	if skipped:
		out += f"\n\nÜbersprungen ({len(skipped)}):\n" + "\n".join(skipped)
	return out


def create_missing_ledger_accounts_job(company: str, numbers: list[str]) -> None:
	"""Hintergrund-Job-Wrapper für WeClappSettings.create_missing_ledger_accounts() (siehe
	dort) - Ergebnis landet im Error Log, da ein Hintergrund-Job keine Desk-Meldung mehr direkt
	anzeigen kann."""
	by_number, by_parent = _ledger_reference()
	accounts = []
	for num in numbers:
		acc = by_number.get(num)
		accounts.append(acc if acc else {"accountNumber": num, "type": None, "description": None})
	result = _create_ledger_accounts(accounts, by_parent, company)
	frappe.log_error(title="WeClapp Kontenanlage abgeschlossen", message=result)


def import_used_ledger_accounts_job(company: str) -> None:
	"""Hintergrund-Job-Wrapper für WeClappSettings.import_used_ledger_accounts() (siehe dort) -
	Ergebnis landet im Error Log."""
	from weclapp_sync.sync.settings import get_client

	_, by_parent = _ledger_reference()

	client = get_client()
	client.open()
	try:
		id_to_account = {
			a["id"]: a
			for a in client.iter_all("ledgerAccount", properties="id,accountNumber,type,description")
		}
		used_ids: set[str] = set()
		for tx in client.iter_all("accountingTransaction", properties="id,transactionDetails.accountId"):
			for td in tx.get("transactionDetails") or []:
				acc_id = td.get("accountId")
				if acc_id:
					used_ids.add(acc_id)
	finally:
		client.close()

	accounts = [
		id_to_account[i]
		for i in used_ids
		if i in id_to_account and id_to_account[i].get("type") == "IMPERSONAL_ACCOUNT"
	]
	result = _create_ledger_accounts(accounts, by_parent, company)
	frappe.log_error(title="WeClapp Kontenanlage abgeschlossen", message=result)

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

	# ------------------------------------------------------------------ Kontenanlage aus WeClapp
	# Die eigentliche Logik steht als Modul-Funktionen VOR dieser Klasse (_ledger_reference()/
	# _erpnext_sibling()/_create_ledger_accounts()) - nicht als Methoden, damit sie auch aus den
	# Hintergrund-Job-Funktionen unten (frappe.enqueue mit einer schlanken Modul-Funktion statt
	# eines Doc-Reloads) ohne Umweg aufrufbar sind. **Bugfix 2026-09-17:** beide Buttons liefen
	# bisher synchron im Web-Request - `_ledger_reference()` allein braucht ~78 sequenzielle
	# WeClapp-Aufrufe (7739 Zeilen `ledgerAccount`, seitenweise), `import_used_ledger_accounts`
	# zusätzlich ~210 für `accountingTransaction` - lief beim ersten echten Klick in einen 504
	# Gateway Timeout, siehe `cleanup_duplicate_attachments()` (derselbe Fix: als
	# Hintergrund-Job, Ergebnis im Error Log statt als direkte Rückmeldung).

	@frappe.whitelist()
	def create_missing_ledger_accounts(self):
		"""Legt GEZIELT die in `ledger_account_numbers` eingetragenen, in ERPNext fehlenden
		Sachkonten aus WeClapps `ledgerAccount`-Entität an (nicht zu verwechseln mit
		`create_missing_tax_accounts()`, das nur die von Steuern referenzierten Konten kennt).
		Für einzelne, konkret gebrauchte Konten, die WeClapp noch nie tatsächlich bebucht hat
		(sonst würde `import_used_ledger_accounts()` unten reichen) - z.B. ein neues Bankkonto,
		das gerade erst eingerichtet wird.

		Nutzer-Anfrage 2026-09-16 (über eine parallele Session, `versand_integration`, die für
		die Portokasse-Journalbuchungen ein Konto brauchte): "1030 Portokasse"/"1270 N26"
		existieren in WeClapp, fehlten aber in ERPNext."""
		if not self.company:
			frappe.throw("Bitte zuerst die Company setzen.")

		numbers = [
			n.strip()
			for n in (self.ledger_account_numbers or "").replace(",", "\n").splitlines()
			if n.strip()
		]
		if not numbers:
			frappe.throw(
				'Bitte oben unter "Kontonummern" mindestens eine WeClapp-Kontonummer eintragen '
				"(z.B. 1030, 1270)."
			)

		frappe.enqueue(
			"weclapp_sync.weclapp_sync.doctype.weclapp_settings.weclapp_settings.create_missing_ledger_accounts_job",
			queue="long",
			timeout=1800,
			company=self.company,
			numbers=numbers,
		)
		return (
			'Wird im Hintergrund angelegt - Ergebnis landet im Error Log '
			'("WeClapp Kontenanlage abgeschlossen").'
		)

	@frappe.whitelist()
	def import_used_ledger_accounts(self):
		"""Scannt WeClapps `accountingTransaction` (jede tatsächliche Buchung, aktuell 20916)
		und legt alle bisher in ERPNext fehlenden Sachkonten an, auf die JEMALS gebucht wurde.

		Nutzer-Wunsch 2026-09-16, nachdem klar wurde, dass die gezielte Einzel-Eintragung
		(`create_missing_ledger_accounts`) zu eng ist: "Genutzt werden deutlich mehr Konten...
		importier doch alle, auf die schon jemals gebucht wurde." Präziser als WeClapps
		kompletter Kontenrahmen (7739 generische SKR03-Vorlagenkonten, siehe dort) UND
		umfassender als Einzel-Eintragung.

		Die allermeisten in Buchungen referenzierten Konten sind `PERSONAL_ACCOUNT`
		(Debitoren-/Kreditoren-Personenkonten je Kunde/Lieferant - live: 3274 von 3407
		verschiedenen referenzierten Konten) - die laufen über eine ganz andere, längst
		bestehende Anlage (`erpnext_helpers.ensure_personal_account()`, pro Kunde/Lieferant
		beim customer.py/supplier.py-Sync) und werden hier ignoriert. Nur
		`type == IMPERSONAL_ACCOUNT` (echte Sachkonten - live: 129, davon 70 in ERPNext
		fehlend) wird betrachtet."""
		if not self.company:
			frappe.throw("Bitte zuerst die Company setzen.")

		frappe.enqueue(
			"weclapp_sync.weclapp_sync.doctype.weclapp_settings.weclapp_settings.import_used_ledger_accounts_job",
			queue="long",
			timeout=1800,
			company=self.company,
		)
		return (
			'Scan läuft im Hintergrund (kann einige Minuten dauern) - Ergebnis landet im '
			'Error Log ("WeClapp Kontenanlage abgeschlossen").'
		)

	@frappe.whitelist()
	def populate_price_list_mappings(self):
		"""Legt je WeClapp-Preiskanal eine Zeile an. Kanal-Universum: NET1..NET9 + GROSS1..GROSS8
		(WeClapp-Standard) vereinigt mit den in `articlePrice` tatsächlich vorkommenden.
		Legt/benennt die ERPNext-Preisliste nach `channel_label` und setzt an ihr den
		Brutto-Haken (`custom_price_includes_tax`, falls das Feld existiert).

		Befüllt außerdem `versandabsender` aus `_CHANNEL_VERSANDABSENDER` - aber nur, wenn die
		Zeile noch leer ist (überschreibt keine manuelle Nutzer-Zuordnung) UND der referenzierte
		Versandabsender-Datensatz tatsächlich existiert (die Doctype gehört einer anderen App,
		könnte fehlen)."""
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
			if not row.versandabsender:
				suggested = _CHANNEL_VERSANDABSENDER.get(channel)
				if suggested and frappe.db.exists("Versandabsender", suggested):
					row.versandabsender = suggested

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
		"""Enqueued den Vollimport als langlaufenden Background-Job. Setzt einen abgebrochenen/
		gescheiterten Vollimport mit noch unfertigem Seiten-Fortschritt fort, statt jedes Mal
		komplett neu zu beginnen (siehe `_resumable_full_import()`)."""
		if not self.enabled:
			frappe.throw("WeClapp Sync ist deaktiviert.")

		# Gegen JEDEN laufenden Lauf prüfen, nicht nur denselben Modus - sonst startet ein
		# Vollimport parallel zu einem laufenden Delta-Sync (oder umgekehrt der Scheduler-Tick
		# parallel zu einem Vollimport, siehe scheduler.py._has_running_run() Bugfix 2026-09-12).
		# Beide gegen dieselbe WeClapp-Instanz/ERPNext-DB gleichzeitig laufen zu lassen, ist ein
		# Rennen (Existenzprüfung+Insert beim Upsert ist zwischen zwei Prozessen nicht atomar).
		running = frappe.get_all(
			"WeClapp Sync Run", filters={"status": "Running"}, fields=["mode"], limit=1
		)
		if running:
			frappe.throw(f"Es läuft bereits ein Sync-Vorgang ({running[0].mode}).")

		from weclapp_sync.sync.engine import MODE_FULL, create_run

		resume_name = self._resumable_full_import()
		# Run-Doc synchron VOR dem Enqueue auf "Running" setzen (nicht erst im Job selbst) -
		# sonst kann der minütliche Scheduler-Tick in der Lücke zwischen Enqueue und
		# tatsächlichem Job-Start noch keinen laufenden Lauf sehen und parallel einen Delta-Sync
		# anstoßen (Bugfix 2026-09-16, siehe scheduler.py für das symmetrische Gegenstück).
		if resume_name:
			run_name = resume_name
			frappe.db.set_value("WeClapp Sync Run", run_name, "status", "Running")
		else:
			run_name = create_run(MODE_FULL).name
		frappe.db.commit()

		# Eigenes, viel größeres Timeout als der Delta-Sync (siehe full_import_job_timeout-
		# Feldbeschreibung) - 2026-09-14 live beobachtet: mit `delta_job_timeout` (Default 3600 s)
		# killte RQ den Vollimport-Job nach genau einer Stunde mitten im Lauf (bei
		# aktiviertem Bild-/Dokument-Sync dauert ein Vollimport locker länger), der Run blieb bis
		# zur nächsten stündlichen `recover_stale_runs`-Aufräumroutine fälschlich auf "Running".
		frappe.enqueue(
			"weclapp_sync.sync.engine.run_full_import",
			queue="long",
			job_id="weclapp_sync_full_import",
			timeout=self.full_import_job_timeout or 21600,
			run_name=run_name,
		)
		if resume_name:
			return f"Vollimport {run_name} wird fortgesetzt (vorheriger Abbruch) – Fortschritt unter „WeClapp Sync Run“."
		return f"Vollimport {run_name} wurde gestartet – Fortschritt unter „WeClapp Sync Run“."

	@staticmethod
	def _resumable_full_import() -> str | None:
		"""Jüngster nicht erfolgreich beendeter Vollimport, der noch echten Seiten-Fortschritt
		hat (mind. ein Objekttyp mit `progress_run` == dieser Lauf). **Bugfix 2026-09-16:** der
		Resume-Mechanismus (`progress_run`/`progress_page`, siehe engine.py) existierte schon
		lange, wurde aber von keinem Aufrufer je mit `run_name` genutzt - ein abgebrochener
		Vollimport begann bei einem erneuten Start immer bei Seite 1 von vorn."""
		candidates = frappe.get_all(
			"WeClapp Sync Run",
			filters={"mode": "Full Import", "status": ("in", ("Aborted", "Aborted (stale)", "Failed"))},
			fields=["name"],
			order_by="creation desc",
			limit=1,
		)
		if not candidates:
			return None
		name = candidates[0].name
		has_progress = frappe.get_all(
			"WeClapp Sync Object Type",
			filters={"parent": "WeClapp Settings", "progress_run": name},
			limit=1,
		)
		return name if has_progress else None

	@frappe.whitelist()
	def cleanup_duplicate_attachments(self):
		"""Einmalige Bereinigung der Anhang-Dubletten aus der Zeit vor dem `wc_id`-Dedup-Fix
		(siehe `_attachments.py`). Bewusst ein separater, vom Nutzer ausgelöster Button - kein
		automatischer Teil des Syncs, weil er in ERPNext löscht (Produktivdaten).

		**Bugfix 2026-09-17:** lief bisher synchron im Web-Request - bei tausenden Dubletten
		(live: >17.000 an Items) in einen 504 Gateway Timeout gelaufen, ohne auch nur eine
		Datei zu prüfen. Jetzt als Hintergrund-Job (wie der Vollimport), Ergebnis landet im
		Error Log ("WeClapp Anhang-Bereinigung abgeschlossen").

		**Bugfix 2026-09-17 (Nachfassung):** ein 504 auf der HTTP-Antwort bedeutet NICHT, dass
		der Hintergrund-Job nicht doch losgelaufen ist (`frappe.enqueue` selbst ist sofort
		fertig, nur die Antwort kam nicht rechtzeitig an) - mehrere Klicks/Retries nach einem
		504 haben live zu **zwei parallel laufenden** Bereinigungs-Jobs geführt, die sich auf
        derselben File-Tabelle gegenseitig blockierten (`Lock wait timeout exceeded`, 4157
        Dateien in Folge fehlgeschlagen). Einfache Sperre über den Cache verhindert das."""
		lock_key = "weclapp_sync_attachment_cleanup_running"
		if frappe.cache().get_value(lock_key):
			frappe.throw(
				"Es läuft bereits eine Anhang-Bereinigung im Hintergrund - bitte warten, bis sie "
				'im Error Log als "WeClapp Anhang-Bereinigung abgeschlossen" auftaucht.'
			)
		frappe.cache().set_value(lock_key, "1", expires_in_sec=3600)
		frappe.enqueue(
			"weclapp_sync.sync.mappers._attachments.cleanup_duplicate_attachments_job",
			queue="long",
			timeout=3600,
		)
		return (
			'Bereinigung läuft im Hintergrund - Ergebnis landet im Error Log '
			'("WeClapp Anhang-Bereinigung abgeschlossen").'
		)

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
			f"{res['touched']} Feld(er) angelegt/positioniert auf: {doctypes}. "
			f"{res['enabled_rows']} Zusatzfeld(er) sind für den Sync aktiv."
		)


def _fallback_label(key: str) -> str:
	return key.replace("_", " ").title()
