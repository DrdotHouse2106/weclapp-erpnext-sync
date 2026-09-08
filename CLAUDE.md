# CLAUDE.md

Projektinterne Referenz. Diese Datei nach jeder Session mit neuen Erkenntnissen aktualisieren
(Konvention aus dem Ursprungsprojekt, siehe unten).

## Stand der Umsetzung (2026-09-08)

**Increment 1 + 2 fertig: App-Gerüst + Unterbau + Setup-Layer + erster (reduzierter)
Kunden-Mapper. Registry kennt 1 von 14 Typen (`customer`).**

### Increment 2 (nach Increment 1, siehe unten):
- `weclapp_sync/setup/` - idempotenter Setup-Vorlauf. `custom_fields.py`: `wc_id` +
  `wc_last_modified` (Data, read_only) auf allen Sync-Zieltypen, plus `wc_zahlungsart`,
  `wc_opt_in_email/letter/phone/sms`, `wc_fax` (Contact) - portiert aus
  `reference/setup.py` setup_customer_supplier_extra_fields. `naming.py`: Property Setter
  `autoname=Prompt` für Customer/Supplier/Sales Invoice/... (portiert aus setup_naming).
  `runner.py` `run_setup(full=)` - läuft bei `after_install`, `after_migrate` (hooks) und als
  Vorlauf von `run_full_import()`. **Datenintensive setup_*() (Konten, Lager, Geschäftsjahre,
  Zahlungsbedingungen, Personenkonten, Artikelgruppen, ...) noch TODO in `runner.py`.**
- `weclapp_sync/erpnext_helpers.py` - Port von `reference/erpnext/en_helper.py`. Statische
  Formatierer (Datum aus epoch-ms, Telefon-Normalisierung, `strip_html` mit
  Mehrfach-Unescape, `custom_fieldname`). Settings-abhängig: `territory_for_country`,
  `country_name` (ISO-Code -> ERPNext Country via `frappe.db`), `default_uom/currency`.
- `weclapp_sync/sync/mappers/customer.py` - **CustomerMapper, bewusst reduziert.** Mappt nur
  das Kern-`Customer`-Dokument: customer_name/type/group (Gruppen aus Settings), website,
  tax_id, default_currency, disabled=0, customer_details (nur `description`, ohne Zusatz-
  API-Calls), payment_terms, wc_zahlungsart, wc_opt_in_*. **NICHT portiert:** Adressen,
  Kontakte (inkl. "self"-Kontakt-Fallback für E-Mail/Telefon - im Altbestand ~4200/5700
  Kunden betroffen!), Bankkonten, Personenkonto (`party.customerDebtorAccountNumber`),
  Zusatzfelder (`customAttributeDefinition`-Abruf nötig), Anhänge, interne Notiz/Kommentare
  aus dem `party`-Objekt. Jeweils eigener Folge-Schritt.
- `mappers/base.py` `upsert()` erweitert: findet Bestandsdokument zuerst über `wc_id`-Feld,
  dann über deterministischen Namen; setzt `wc_id`/`wc_last_modified` automatisch; erzwingt
  bei `forces_name` den Dokumentnamen via `insert(set_name=...)` (braucht `autoname=Prompt`).
- WeClapp Settings: Abschnitt "Mapping-Standardwerte" jetzt mit realen Feldern (company,
  default_currency, customer_group_company/individual, territory/territory_germany, uom).
- Client `iter_pages()`/Delta-Filter live gegen francetec.weclapp.com geprüft (read-only):
  Paginierung (119 quotation = 50+50+19) und `lastModifiedDate-gt` korrekt.

### Increment 1:

Fertig:
- Frappe-App `weclapp_sync/`: `pyproject.toml`, `hooks.py` (Scheduler-Cron + `after_install`),
  `modules.txt`, `install.py`, `config/desktop.py`.
- `weclapp_sync/weclapp/` - read-only WeClapp-Client. `client.py`: GET-only per `_request()` hart
  erzwungen (nicht-GET -> `WeClappWriteRefused`), `iter_pages()`/`iter_all()` sind **Generatoren**
  (Seite holen -> yield -> nächste Seite; nie die ganze Entität im RAM), `count()` mit Filter,
  `modified_since_filter()` baut `{"lastModifiedDate-gt": epoch_ms}`, `iter_document_content()`
  streamt PDF-Downloads chunkweise. `doctypes.py`: `WeClappDocType`-Enum (Teilmenge).
- Doctypes unter `weclapp_sync/weclapp_sync/doctype/`:
  - **WeClapp Settings** (Single): Zugang (URL/Token/page_size), Delta-Sync-Schalter+Intervall,
    Objekttyp-Child-Tabelle, Buttons "Verbindung testen" / "Objekttyp-Liste aktualisieren" /
    "Vollimport starten". Controller füllt die Objekttyp-Zeilen aus `registry.SYNC_ORDER`.
    Mapping-Standardwerte (config_example.py-Port) = leerer Abschnitt, TODO.
  - **WeClapp Sync Object Type** (Child): pro Typ `enabled`, `last_sync_ms` (Delta-Watermark),
    `last_sync_at`, `progress_run`/`progress_page` (Resume-Cursor).
  - **WeClapp Sync Run** (+ Child **WeClapp Sync Run Type**): ein Doc pro Voll-/Delta-Lauf,
    Status + Summen + Pro-Typ-Ergebnis.
  - **WeClapp Sync Log**: ein Doc pro fehlgeschlagenem Datensatz (Run, Typ, WeClapp-ID,
    Referenz, Traceback) - kein stiller Fehlschlag.
- `weclapp_sync/sync/`:
  - `registry.py` - `ObjectTypeSpec` + `SYNC_ORDER` (feste Reihenfolge aus `reference/main.py`)
    + `register()`. **Noch `register(...)`-Aufrufe = 0** - hier wandern die Mapper rein.
  - `engine.py` - gemeinsamer Unterbau: `run_full_import()` / `run_delta_sync()` ->
    `run_sync(mode)` -> pro Spec `sync_object_type()`. Seitenweise iterieren, `commit()` +
    `progress_page` speichern pro Seite, Savepoint pro Datensatz (ein Fehler rollt nur SEINEN
    Datensatz zurück, Seite läuft weiter), Delta-Watermark erst bei Typ-Erfolg setzen.
  - `scheduler.py` - Cron-Tick (jede Minute) `enqueue_due_delta_sync()`: prüft Fälligkeit,
    enqueued **einen** Long-Job, synct nicht selbst. `recover_stale_runs()` stündlich.
  - `settings.py` - `get_client()` (baut Client aus Settings), `get_object_type_row()`.
  - `mappers/base.py` - `Mapper`-Basisklasse mit `upsert()` (deterministischer Name ->
    get_doc+save / new_doc+insert), `to_doc_fields()`/`target_name()` von Unterklassen zu füllen,
    `post_run()` für Belegketten-Nachlauf.

### Increment 3 (2026-09-08): Kunden-Mapper gegen echte Testinstanz getestet
- `sync/mappers/_party_common.py` (Adressen/Kontakte/Dynamic Links, `wc_id`-basiert),
  `customer.py` voller Graph. **Erster echter Vollimport-Test:** 100 Kunden, 105 Adressen,
  87 Kontakte, 0 Fehler auf francetec.frappe.cloud (Frappe v16.33 / ERPNext v16.34).
- Engine: `mapper.client` wird gesetzt (read-only WeClapp-Client für Zusatzabrufe).
- `debug_max_pages_per_type` in Settings (Testläufe begrenzen, Watermark bleibt dann ungesetzt).
- Kunden-Mapper lädt jetzt pro Kunde das `party`-Objekt nach (`customer` liefert
  `customerDebtorAccountNumber` / `customerInternalNote` / `salesInvoiceEmailAddressesId` NICHT).
- Personenkonten: `erpnext_helpers.ensure_personal_account()` legt das Debitorenkonto
  on-demand an (Parent-Gruppe aus neuen Settings-Feldern `debtor_/creditor_parent_account`),
  Customer.accounts wird verknüpft.
- `reference/INSTANCE_STATE.md`: Testinstanz-Zustand (Naming, vorhandene Felder, Personenkonten).
- Bekannt: Contact-`name` bekommt von ERPNext automatisch `-{customerNumber}`-Suffix
  (Standard bei verknüpften Kontakten) - deterministisch, Re-Run-Abgleich via `wc_id`.

Als Nächstes (Reihenfolge):
1. Kunden-Mapper: Bankkonten + Custom Attributes (Zusatzfelder, braucht
   `customAttributeDefinition`-Abruf) + `apply_wc_blocks` (blocked/insolvent).
2. **Lieferanten-Mapper** (`supplier_migration.py`, weitgehend analog zu Kunden).
3. **Artikel-Mapper** (`article_migration.py`) + `article_price`.
4. Für Personenkonten/Konten/Lager/Zahlungsbedingungen die fehlenden `setup_*()`-Äquivalente in
   `weclapp_sync/setup/runner.py` (`full=True`-Zweig) ergänzen - vor den abhängigen Mappern.
5. Transaktionsbelege in `SYNC_ORDER`-Reihenfolge (Rechnung, Auftrag, Zahlung, ...) - hier gelten
   die im Vorgängerprojekt gelösten Fachprobleme (Steuer-Mapping, Zahlungsabgleich), siehe dessen
   CLAUDE.md.
6. Belegketten-Rückwärtsverknüpfung als `Mapper.post_run()` (entspricht `apply_document_links`).
7. Schlussphasen `apply_wc_blocks` (gesperrte Kunden/Artikel) als eigener Nachlauf.

Offene Design-Punkte, die beim Mapper-Bau zu klären sind: siehe "Offene technische Fragen".

## Was das hier werden soll

Eine installierbare Frappe/ERPNext-App, die den **kompletten WeClapp→ERPNext-Umzug** übernimmt -
nicht nur eine Ergänzung zum bereits abgeschlossenen Batch-Import, sondern dessen vollständiger
Ersatz als aktive, laufende Lösung:

1. **Vollimport-Fähigkeit** (entspricht dem, was bisher `main.py`/`setup.py` im alten Repo als
   externes Skript gemacht haben) - muss von dieser App selbst übernommen werden können, z. B.
   für Erstinstallationen oder nach einem ERPNext-Reset.
2. **Laufender, automatischer Delta-Sync danach** (neu - gab es im alten Repo nicht) über Frappes
   eigenen Scheduler, nur geänderte WeClapp-Datensätze.

Nutzer installiert die App, trägt WeClapp-Zugangsdaten in einem Settings-Doctype ein, der Rest
läuft automatisch. Kein manuelles Skript-Ausführen mehr nötig - weder für den Erstimport noch für
laufende Aktualisierungen.

**Direktes Vorbild:** `/Users/marcelulber/Programmierung/ecommerce_integrations` (Shopware ↔
ERPNext) macht strukturell etwas Ähnliches, nur bidirektional und für ein anderes Quellsystem. Bei
Unklarheiten zur Frappe-App-Konvention (hooks.py, Settings-Doctype-Muster, Scheduler-Events) lohnt
ein Blick dorthin.

## Herkunft: Vorgänger-Projekt (wird durch dieses hier abgelöst)

`/Users/marcelulber/weclapp-erpnext-migration` (GitHub:
`DrdotHouse2106/weclapp-erpnext-migration`) war der **einmalige Batch-Import** WeClapp → ERPNext,
als externes Python-Skript. Live erfolgreich abgeschlossen (siehe dessen CLAUDE.md für den vollen
Verlauf) - **wird aber durch dieses Repo hier ersetzt, nicht nur ergänzt.** Dessen CLAUDE.md
dokumentiert viele bereits gelöste Fachprobleme (Steuer-Mapping-Fallstricke,
Personenkonto-Zuordnung, Zahlungsabgleich-Heuristiken, Zahlungsbedingungen-Parsing, ...), die hier
vermutlich identisch gelten - unbedingt vor dem jeweiligen Umbau dort nachlesen statt neu zu
recherchieren.

`reference/` enthält 1:1 kopierten Code aus diesem Vorgängerprojekt (Stand 2026-09-07) - **nicht
direkt lauffähig hier**, dient als vollständige Ausgangsbasis für den Umbau zur Frappe-App:

- `base/` - `ApiBase`/`ApiException`/`DocType`-Abstraktionen, wahrscheinlich direkt
  wiederverwendbar.
- `weclapp/` - der WeClapp-REST-Client (`wc_api.py`, `wc_doctypes.py`), read-only, braucht noch
  Filter-Unterstützung (`lastModifiedDate`) für den Delta-Sync-Teil (für den Vollimport-Teil
  passt `get_all()` unverändert).
- `erpnext/` - kompletter ERPNext-REST-Client des alten Repos (`en_api.py`, `en_doctypes.py`,
  `en_helper.py`, `en_tax_info.py`, `en_api_data.py`). **`en_api.py` selbst (die REST-Wrapper-
  Schicht) wird hier nicht gebraucht** - läuft der Code IN ERPNext, nutzt man stattdessen Frappes
  native `frappe.get_doc()`/`.insert()`/`.save()`, kein Umweg über REST/HTTP zu sich selbst. Die
  übrigen Dateien (Doctype-Enum, Namens-Helfer, Steuer-Datenklassen, `ERPNextFilter`/
  `FilterOperator`) sind wertvolle, wiederverwendbare Referenz.
- `migration_logic/full_field_mapping/` - der komplette `migration/`-Ordner des Vorgängerprojekts
  (ein Modul pro Objekttyp: Customer, SalesOrder, Item, ...) - die eigentliche
  Feld-Mapping-Logik (WeClapp-Feld → ERPNext-Feld), fachlich der wertvollste Teil, lässt sich
  fast 1:1 übernehmen, technisch aber umbauen (REST-Aufrufe → native Document-API).
- `setup.py` - alle idempotenten `setup_*()`-Funktionen (Stammdaten/Struktur anlegen: Konten,
  Lager, Geschäftsjahre, Zahlungsbedingungen, Custom Fields, ...) - **das wird für die
  Vollimport-Fähigkeit gebraucht**, nicht nur die reine Datensatz-Migration.
- `main.py` - Orchestrierung/Reihenfolge des alten Laufs (welche Migration wann, wegen
  Fremdschlüssel-Abhängigkeiten) - wichtige Referenz für die Reihenfolge im neuen Vollimport-Modus.
- `config_example.py` - Vorlage für alle bisher gebrauchten Konfigurationswerte (Konten-/
  Gruppennamen etc.) - Grundlage für die Felder im neuen "WeClapp Settings"-Doctype.

## Architektur-Plan (Entwurf, noch nicht umgesetzt)

1. **Frappe-App-Grundgerüst** (`bench new-app weclapp_sync` o. ä.), `hooks.py` mit
   `scheduler_events` für den periodischen Sync-Job (Intervall konfigurierbar).
2. **Settings-Doctype** ("WeClapp Settings", Single-Doctype): API-Token, Basis-URL,
   welche Objekttypen syncen (Checkboxen pro Typ, analog zu WeClapps eigenen Doctypes),
   Sync-Intervall, Zeitstempel des letzten erfolgreichen Laufs pro Objekttyp (Grundlage für den
   Delta-Filter), plus alle bisherigen `config.py`-Werte (Konten-/Gruppennamen etc., siehe
   `reference/config_example.py`) als Formularfelder statt Python-Konstanten.
3. **Zwei Betriebsmodi, ein gemeinsamer Unterbau:**
   - **Vollimport** (manuell anstoßbar, z. B. Button im Settings-Doctype oder eigener Menüpunkt):
     läuft `setup_*()`-Äquivalente (Stammdaten/Struktur) und danach alle Objekttyp-Migrationen in
     der Reihenfolge aus `reference/main.py`, ohne Delta-Filter (alles abfragen).
   - **Delta-Sync** (automatisch, Scheduler): dieselbe Feld-Mapping-Logik pro Objekttyp, aber nur
     für `lastModifiedDate >= letzter_sync_zeitpunkt` (siehe Punkt 4).
   - Beide Modi nutzen dieselbe Upsert-Funktion pro Objekttyp (Punkt 5) - kein doppelt gepflegter
     Code für "einmal alles" vs. "nur Neues".
   - **Streaming/seitenweise verarbeiten, nicht erst alles cachen.** Das Vorgängerprojekt hat
     jeden Objekttyp komplett nach `weclapp/cache/*.json` geladen und _danach_ verarbeitet - das
     geht hier NICHT: eine Frappe-Instanz hat wenig RAM/Disk, und der Erstimport ist eine große
     Datenmenge (5-6k Rechnungen, 6k Kunden, 6k Artikel, ...). Stattdessen pro Objekttyp Seite
     für Seite von WeClapp holen (`page`/`pageSize`), jede Seite sofort upserten, dann verwerfen.
     Nie die volle Liste eines Objekttyps im Speicher halten. Gilt für Vollimport UND Delta.
     `wc_api.py` braucht dafür einen Generator/Iterator statt `get_all()` (das die Seiten
     zusammen in eine Liste merged).
4. **Delta-Filter:** ~~Noch nicht live getestet~~ **GEKLÄRT 2026-09-07 (siehe unten):** WeClapps
   API filtert serverseitig nach `lastModifiedDate` (Query-Param `lastModifiedDate-gt=<epoch_ms>`,
   auf `/count` und Listen-Endpoint). `wc_api.py`s Seiten-Abruf muss den Filter als optionalen
   `params` durchreichen.
5. **Upsert-Semantik pro Objekttyp**, aufbauend auf den deterministischen Namen aus
   `en_helper.py` - existiert das Ziel-Dokument schon (Name bekannt), `frappe.get_doc(...).save()`
   mit aktualisierten Feldern, sonst `frappe.new_doc(...).insert()`. Idempotenz-Prinzip aus dem
   Vorgängerprojekt (jede Migration prüft vor dem Schreiben, ein Fehler bei einem Datensatz bricht
   nie den ganzen Lauf ab) unbedingt beibehalten - gilt für beide Modi (Punkt 3).
6. **Status-/Fehler-Sichtbarkeit** für den Nutzer - mindestens ein Log/Report, welche Datensätze
   beim letzten Lauf (Vollimport oder Delta) fehlgeschlagen sind (kein stiller Fehlschlag, siehe
   `ecommerce_integrations` für ein bestehendes Muster).

## Offene technische Fragen (vor dem Bau zu klären)

- ~~**Wichtigste:** Unterstützt WeClapps REST-API serverseitige Filterung nach
  `lastModifiedDate`?~~ **GEKLÄRT 2026-09-07, live gegen francetec.weclapp.com getestet (nur
  GET): JA, funktioniert vollständig.**
  - Syntax: Query-Param `<feld>-<op>=<wert>`, Operatoren `-gt -lt -ge -le -eq -ne` (dieselbe
    Suffix-Syntax wie `search()` in `reference/weclapp/wc_api.py` mit `-eq`).
  - **Wert MUSS Epoch-Millisekunden sein** (`lastModifiedDate` liegt so im Datensatz vor). Ein
    ISO-8601-String führt zu HTTP 500.
  - Greift auf `/count` UND dem Listen-Endpoint, für alle getesteten Objekttypen (`customer`,
    `party`, `salesOrder`, `salesInvoice`, `article`, `quotation`).
  - Kombinierbar (`-gt` und `-lt` in einer Query), zusätzlich `sort=-lastModifiedDate` und
    `properties=id,invoiceNumber,...` (Feldreduktion) nutzbar.
  - Exakt: `count(-gt X)` + `count(-lt X)` = `count()` ohne Filter, auf den Datensatz genau.
  - Konsequenz: `wc_api.py`s `get_all()`/`_get_page()`/`get_count()` müssen einen optionalen
    `params`-/Filter-Parameter durchreichen; kein clientseitiger Vollabruf+Vergleich nötig.
  - Read-only Probe-Skript im Repo: `scripts/weclapp_filter_probe.py` (Token via
    `WECLAPP_BASE_URL`/`WECLAPP_API_TOKEN`-Env, jeder Aufruf ein GET).
- Reihenfolge/Abhängigkeiten beim Delta-Sync: die ursprüngliche Migration hatte eine feste
  Reihenfolge (Kunden vor Rechnungen vor Zahlungen, wegen Fremdschlüsseln, siehe
  `reference/main.py`) - bei einem Delta-Sync mit potenziell nur einzelnen geänderten Rechnungen
  muss sichergestellt sein, dass referenzierte Kunden/Artikel schon existieren, sonst
  pro-Lauf-Reihenfolge oder Nachzieh-/Retry-Logik nötig.
- Wie wird der bereits über das alte Repo migrierte ERPNext-Datenbestand behandelt, wenn dieses
  Projekt zum ersten Mal läuft? Vermutlich sollte der erste Delta-Sync-Lauf (oder ein manuell
  angestoßener Vollimport) idempotent auf den bestehenden Daten aufsetzen (dieselben
  deterministischen Namen wie im alten Repo verwenden, siehe `en_helper.py`) statt alles
  doppelt anzulegen - unbedingt vor dem ersten echten Lauf gegen die produktiv genutzte
  ERPNext-Instanz verifizieren.

## Sonstiges

- GitHub: `https://github.com/DrdotHouse2106/weclapp-erpnext-sync` (öffentlich).
- Vorgängerprojekt-Konvention laut dessen eigener CLAUDE.md: "Diese Datei wird laufend
  aktualisiert" und "Immer auf Deutsch antworten" - beides hier übernommen.
