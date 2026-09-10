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

### Increment 4: belegart-spezifische E-Mails, Bankkonten, Debitorenkonten je Kunde
- WeClapp `party` führt 6 belegart-spezifische E-Mail-Purposes
  (`salesInvoice/salesOrder/delivery/dunning/quotation/purchaseEmailAddressesId` ->
  `partyEmailAddresses[].toAddresses`). Nur ~37 Parteien haben überhaupt welche, aber dann
  maßgeblich. **ERPNext hat dafür kein natives Feld** - Lösung (mit Nutzer abgestimmt,
  Standardfelder wo möglich):
  - Customer-Data-Felder `invoice_/order_/delivery_/dunning_/quotation_email`
    (Section "E-Mail-Adressen je Belegart"), `purchase_email` auf Supplier.
  - Rechnung/Lieferschein zusätzlich auf `Address.email_id` der Rechnungs-/Lieferadresse
    (Standardfeld, in `_party_common.upsert_address(purpose_emails=...)`).
  - `wc_belegart_email` (read_only, `fetch_from: customer.<feld>`) auf Sales Invoice/Order,
    Delivery Note, Quotation, Dunning - zieht die Adresse automatisch auf den Beleg. Nutzer
    kann dann pro Belegart eine Standard-**Notification** (kein Code) für Autoversand
    einrichten. (`custom_fields._DOC_EMAIL_SOURCES`.)
- Bankkonten: `_party_common.upsert_bank_account()` + `ensure_bank()` (Port aus
  reference bank_/bank_account_migration.py). WeClapp `customer.bankAccounts[]` ->
  ERPNext `Bank Account` (+ `Bank`, dedup über BIC), verknüpft mit dem Kunden, `wc_id`-idempotent.
- Debitorenkonten: bestätigt 5829/5838 Kunden haben `customerDebtorAccountNumber`
  (Bereich 10000–15833), 396/396 Lieferanten `supplierCreditorAccountNumber`. Die 9 ohne
  landen auf dem Sammelkonto (WeClapp bleibt Quelle - dort Debitor-Nr. nachtragen).
  partyType: 768 ORGANIZATION + 5534 PERSON.

### Increment 5: Lieferanten-Mapper + Refactoring
- `sync/mappers/supplier.py` (`SupplierMapper`, registriert) - analog zu customer.py:
  Supplier-Kerndoc + Adressen + Kontakte + self-Kontakt + Bankkonten + Kreditorenkonto
  (Payable, `party.supplierCreditorAccountNumber`, Bereich 70000+) + `purchase_email`
  (`party.purchaseEmailAddressesId`). Kein Territory, kein opt_in, eine `default_supplier_group`.
- Gemeinsame Helfer nach `_party_common.py` gezogen: `display_name`, `block_notice`,
  `purpose_email`. `upsert_bank_account(account_type=...)` parametrisiert.
- Erster **voller Kunden-Import** (WC-SYNC-00004) gestartet: bei 1700/5838 sauber, 0 Fehler.

### Increment 6: Zusatzfelder + Artikel-Mapper
- `sync/mappers/_custom_attributes.py` - customAttributes -> Custom Fields (nur bestehende
  Felder; Feld-Anlegen aus `customAttributeDefinition` = TODO). In customer/supplier/article.
- `sync/mappers/article.py` (`ArticleMapper`, registriert, 3/14): Kern-Item + Barcode (ean) +
  Hersteller (on-demand `Manufacturer`) + Artikelgruppe (on-demand aus `articleCategory`-Map) +
  UOM (`ensure_uom`: Alias-Map / on-demand) + Zusatzfelder + **ein** Verkaufspreis (erster
  allgemeiner WeClapp-Preis -> Item Price). `description`/`item_group` nur bei Neuanlage.
- `erpnext_helpers`: `ensure_uom` / `ensure_manufacturer` / `ensure_item_group`.
- WeClapp Settings: `default_item_group` / `default_selling_price_list` /
  `default_buying_price_list`.
- Zahlen: article 6211, articleCategory 132, articleSupplySource **87012** (muss pro Artikel
  gefiltert nachgeladen werden), articlePrice 21896 (aber `articlePrices` sind im
  article-Payload eingebettet).

Noch offen am Artikel-Mapper: Bezugsquellen (`supplySources` -> Item Supplier /
item_defaults.default_supplier / Einkaufspreis), Artikelbilder.

### Increment 7: Setup-Masters, Steuer-Mapping, Belegs-Grundlage, Angebots-Mapper
- **Erster voller Kunden-Import: 5830 Kunden, 0 Fehler** (WC-SYNC-00004). ~5000 Personenkonten,
  6227 Adressen, 4721 Kontakte. Kleine Sub-Fehler im Error Log (`_guarded`).
- **Bug gefixt:** `WeClapp Sync Object Type.last_sync_ms` war `Int` -> Epoch-ms (~1.75e12)
  sprengt MySQL-INT (`DataError 1264`). Jetzt `Data` (String). `_finish_type` schreibt `str()`.
  → Watermark von WC-SYNC-00004 wurde nicht gesetzt; ein Re-Run (idempotent) holt das nach.
- `setup/masters.py`: `setup_payment_terms` / `setup_fiscal_years` / `setup_uom_settings`.
- **Steuer-Mapping**: Doctype `WeClapp Tax Mapping` (Child von Settings, `tax_mappings`).
  Button "Steuer-Mapping aus WeClapp befüllen" (`populate_tax_mapping`) holt WeClapp `tax`
  (243 Stück) und löst Konten über die WeClapp-Kontonummern auf: `defaultNominalAccountNumber`
  = Erlöskonto, `accountNumber` = USt/VSt-Konto -> ERPNext `Account.account_number`.
  Instanz-Kontenplan ist Teilmenge -> nicht auflösbare Felder bleiben leer (Nutzer prüft).
  Settings-Felder: `default_income_/expense_account`, `default_cost_center`,
  `default_sales_/purchase_taxes_template`, `submit_documents`.
- `sync/mappers/_transaction.py` (`TransactionMapper`): `net_rate` (aus `netAmount`, nicht
  `unitPrice`!), `build_lines` (Positionen + Steuer-Akkumulation), `build_tax_rows`
  ("Actual"-Zeilen, Cent-genau), `header_discount_amount`, `ensure_customer` (Minimal-Kunde
  für gelöschte WeClapp-Parteien). `Mapper.find_existing()` extrahiert (wc_id -> Name).
- `sync/mappers/quotation.py` (`QuotationMapper`, registriert, 4/14): `AN-<nr>`, Positionen,
  Steuern, Kopfrabatt, optional submit.

### Increment 8: Preiskanäle -> Preislisten
- WeClapp: 15 Preiskanäle (NET1-8 netto, GROSS1-7 brutto), alle EUR, alle mit Mengenstaffel
  (`priceScaleType=SCALE_FROM`, `priceScaleValue`=min qty), nur 8 kundenspezifische Preise.
- Doctype `WeClapp Price List Mapping` (Child von Settings, `price_list_mappings`) +
  Button `populate_price_list_mappings`: legt je Kanal eine ERPNext Price List "WeClapp <chan>"
  an, Nutzer aktiviert die gewünschten Kanäle.
- `article._sync_prices()`: **volle** WeClapp-Preishistorie je (Kanal, Staffel, Kunde) -> Item
  Prices in der gemappten Liste, mit `min_qty` (Staffel), rekonstruierter Zeitleiste
  (`valid_upto` = nächstes `startDate` - 1 Tag, sonst lehnt ERPNext überlappende offene Preise
  ab: `ItemPriceDuplicateItem`), `customer` (wc_id-Lookup). Idempotent durch **vollständigen
  Neuaufbau**: erst alle Item Prices des Artikels in den verwalteten Listen löschen, dann frisch
  anlegen - kein fragiles Bestands-Matching, immun gegen Altbestand ohne Gültigkeitsdatum.
  (2026-09-09: `_sync_prices` mehrfach überarbeitet - erst nur jüngster Preis [Nutzer wollte
  volle Historie], dann volle Historie mit Zeitleiste, dann Delete+Rebuild. **Ursache der
  100/100-Artikelfehler war `min_qty`:** ERPNext "Item Price" hat das Feld nicht ->
  `frappe.get_all(... fields=["min_qty"])` warf `Unknown column 'min_qty'`. Jetzt nur nutzen
  wenn `meta.has_field("min_qty")`, sonst Staffelpreise `priceScaleValue > 1` auslassen -
  Mengenstaffeln = Pricing Rules = Folge-Schritt, wie im Vorgänger-Importer.
  Danach 3/100: WeClapp-Preise ohne `startDate` -> leeres `valid_from` bei gesetztem
  `valid_upto` wertet ERPNext als HEUTE -> `InvalidDates`. Fix: leeres `valid_from` ->
  `2000-01-01`; `valid_upto <= valid_from` auslassen (ERPNext verlangt strikt danach).)

### Increment 9 (2026-09-09): Artikel-Import sauber, Angebots-Test
- Artikel-Vollimport läuft fehlerfrei (100/100 im Debug-Lauf, nach den `min_qty`- und
  `valid_from`-Fixes oben).
- **Angebots-Test: 92/100 `LinkValidationError` "Artikel-Code ... nicht gefunden"** - die
  Angebote verweisen auf Artikel außerhalb der 100 debug-importierten. Fix in
  `_transaction.resolve_line_item()`: Zeile ohne `articleNumber` -> Platzhalter-Item `FREITEXT`
  (lazy angelegt, `is_stock_item=0`); `articleNumber` ohne Item -> Minimal-Item aus den
  Zeilendaten (`wc_id` aus `articleId`, damit ein späterer Artikel-Sync es über das Feld
  wiederfindet und vervollständigt). Damit ist die Beleg-Import-Reihenfolge robust gegen
  fehlende/gelöschte Artikel (entspricht `EN_FREE_TEXT_ITEM` im Vorgänger-Importer, plus
  Stub-Anlage die es dort nicht gab, weil dort immer erst alle Artikel liefen).
- **Für den echten Test:** Artikel-Vollimport ohne Debug-Limit fahren, dann Angebote - sonst
  entstehen ~6000 Stub-Items, die erst ein späterer Artikel-Lauf füllt.

### Increment 10 (2026-09-10): Vollimport sauber + Angebots-Verifikation + rate-Präzision
- **Vollimport:** Kunde 5831/0, Lieferant 396/0, Artikel 6210/**2**. Die 2 Artikel-Fehler:
  EAN schon von einem anderen Artikel belegt (WeClapp erlaubt geteilte EANs, ERPNext nicht) ->
  `article._barcodes()` setzt den Barcode nur, wenn frei. Re-Run holt die 2 nach.
- **Angebote:** 99/99 importiert, 0 Fehler (nach FREITEXT/Stub-Item-Fix + vollem Artikelbestand).
- **Summen gegen WeClapp verprobt (GET):** meist cent-genau, teils +1-2 ct. Ursache: WeClapp gibt
  `netAmount` je Position, ERPNext will `rate` und rechnet `rate*Menge`; bei rabattierten
  Mengenpositionen ist `netAmount/Menge` krumm und `rate` rundet auf 2 NK -> Drift. (Der alte
  Importer lehnte solche Belege komplett ab.)
- **Fix (mit Nutzer abgestimmt): `setup/precision.py`** - Property Setter `precision = 6` auf
  `rate`/`price_list_rate`/`net_rate` (+ base_-Pendants, discount_amount) der 7 Positions-
  Doctypes (Quotation/Sales Order/Sales Invoice/Delivery Note/Purchase Order/Purchase Invoice/
  Purchase Receipt Item). ERPNext speichert den Einzelpreis dann exakt; Beträge bleiben 2-NK.
  Läuft in `run_setup()` (nach naming). Bestehende 99 Angebote: ein Re-Run korrigiert die Summen.
- **Danach: Preislisten-Override.** Re-Run von AN-2026AN1099 war +8,40 zu hoch. Zwei Ursachen:
  (1) **Stock Settings `auto_insert_price_list_rate_if_missing = 1`** - jede Belegzeile ohne
  Item Price legte beim 1. Lauf eine in der Beleg-Preisliste ("Standard Selling") an; der 2.
  Lauf las sie zurück und überschrieb den WeClapp-Zeilenpreis. Fix: `masters.setup_pricing_settings()`
  setzt das Flag auf 0 (läuft immer in `run_setup`), + auf der Testinstanz die 338 Streu-Item-
  Prices in "Standard Selling" gelöscht. (2) **WeClapp-Nullzeilen** (Zwischenüberschrift,
  `netAmount==grossAmount==0`): ERPNext ersetzte rate 0 durch den Preislisten-Preis. Fix:
  `_transaction._add_line` markiert sie `is_free_item=1` (erzwingt rate 0, kein Preis-Lookup),
  setzt für alle Zeilen `price_list_rate=rate`+`discount_percentage=0`; Quotation-Header
  `ignore_pricing_rule=1`.

Als Nächstes:
1. **Nutzer:** Redeploy, `run_setup(full)` läuft mit; Steuer-Mapping- + Preiskanal-Button +
   Konten/Templates/Kostenstelle in Settings prüfen; Kunden-Delta einmal re-runnen (Watermark).
2. Angebots-Import testen, dann `sales_order` + `sales_invoice` (+ `payment_entry` aus
   `salesOpenItem`), dann Einkaufsseite. Steuerlogik in `_transaction.py` ist da, muss aber
   gegen echte Belege verifiziert werden (Vorgängerprojekt-CLAUDE.md: gelöste Fälle).
3. `apply_wc_blocks`, `crm_event`, `stock_movement`, `shipment`, Belegketten (`post_run`).
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
