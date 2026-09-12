# CLAUDE.md

Projektinterne Referenz. Diese Datei nach jeder Session mit neuen Erkenntnissen aktualisieren
(Konvention aus dem Ursprungsprojekt, siehe unten).

### Increment 19 (2026-09-12): Item-Steuer-Template-Konflikt sauber gelöst
Offenes Problem aus Increment 12 (siehe dort: "Die Steuern sind aber immernoch nicht gesetzt"):
wie schlägt ERPNext künftigen, von Hand erfassten Belegen (nach Live-Umstellung) einen
Steuersatz vor, ohne den permanenten Konflikt mit den Actual-Steuerzeilen des Syncs zu
reproduzieren (natives `Item.taxes` -> `validate_item_wise_tax_detail` lehnt Belege ab, deren
Artikel historisch zu einem anderen Satz verkauft wurde)? Nutzer hat extern recherchierte
Lösungsoptionen eingebracht (Monkey-Patch der Core-Validierung, `valid_from`-Datierung, Custom
Field + Client Script, Tax Rules/Categories) - **Custom Field + Client Script** umgesetzt:
- **Neues Custom Field `Item.custom_default_item_tax_template`** (Link Item Tax Template,
  `setup/custom_fields.py` `_item_tax_hint_fields()`) - rein informativ, fließt in KEINE
  ERPNext-Steuerberechnung/-Validierung ein. Wird von `article.py`
  `_default_item_tax_template()` aus `taxRateType` befüllt (derselbe `_TAX_RATE_TEMPLATES`-
  Mapping wie der zurückgerollte Versuch, aber auf das getrennte Feld statt auf `Item.taxes`).
- **Neues Modul `setup/item_tax_hint.py`**: legt je Beleg-Doctype mit Steuerbezug (Quotation,
  Sales Order, Sales Invoice, Purchase Order, Purchase Invoice) ein **Client Script** an, das
  beim manuellen Anlegen einer Position im Browser (`item_code`-Change-Event auf der jeweiligen
  Item-Kindtabelle) das Custom Field vom Artikel liest und NUR in die neue Zeile als
  `item_tax_template` einträgt (überschreibt nichts Vorhandenes). Idempotent über
  `frappe.db.get_value("Client Script", {"dt":..., "script": ["like", "%custom_default_item_tax_template%"]})`
  gesucht/aktualisiert - Client Script hat Hash-Naming, kein deterministischer `name` möglich
  (analog zum Property-Setter-Abgleich in `naming.py`). Läuft in `setup/runner.py` `run_setup()`
  (immer, wie die anderen Setup-Schritte).
- **Warum das den Sync nicht berührt:** ein Client Script läuft ausschließlich im Browser: der
  Sync (Python, `frappe.new_doc(...).insert()`/`.save()`) triggert es nie. Die Trennung
  natives Feld (leer, für den Sync) vs. Custom Field (befüllt, nur für die UI) ist von
  Konstruktion her ohne jede Rückwirkung auf importierte/synctierte Belege - kein Monkey-Patch
  der ERPNext-Core-Validierung nötig, kein Wartungsrisiko bei Updates.
- **Noch nicht gegen die Live-Instanz getestet** (Custom Field + Client Script anlegen lassen,
  dann eine Testposition manuell in einem neuen Angebot erfassen und prüfen, ob der Steuersatz
  vorgeschlagen wird).

### Nachtrag 2026-09-12: stock_movement scheiterte massenhaft ("Bewertungssatz erforderlich")
`WC-SYNC-00032` (der oben genannte, ungewollt parallel gestartete Delta-Sync) hat beim gerade
erst aktivierten `stock_movement` **9110 von 15944 Fehlschlägen** produziert (6834 ok). Per
Read-Only-Blick ins WeClapp Sync Log: `frappe.exceptions.ValidationError: Der Bewertungssatz für
den Posten ... ist erforderlich` aus `stock_entry.py` `calculate_rate_and_amount()` ->
`get_valuation_rate()`. **Ursache:** ERPNext berechnet Zeilenbeträge eines Stock Entry auch im
Entwurf (`validate()` läuft bei jedem `.insert()`/`.save()`, nicht erst beim Submit) und verlangt
dafür bei Warenausgängen (`s_warehouse` gesetzt) einen Bewertungssatz. Da dieser Mapper bewusst
NIE submitted (siehe Moduldocstring), gab es für viele Artikel nie eine echte Lagerbewertung.
**Fix:** `item["allow_zero_valuation_rate"] = 1` auf jeder Stock-Entry-Zeile - unbedenklich, weil
diese Entwürfe ohnehin nie eine echte GL-/Lagerbuchung auslösen (das reale, einmalige
1:1-Nachbauen des Lagerbestands per gezieltem Submit bleibt ein bewusster Folge-Schritt, siehe
Increment 18). **Nach dem nächsten Sync-Lauf sollten die 9110 Fehlschläge behoben sein**, bisher
nicht erneut getestet.

### Nachtrag 2026-09-12: Scheduler enqueued Delta-Sync parallel zu laufendem Vollimport
Nutzer meldete: `WC-SYNC-00031` (Vollimport) blieb trotz `abort_requested=1` auf
`purchase_order`/`purchase_invoice` stehen. Per Read-Only-Check direkt gegen die Instanz
gefunden: parallel lief bereits `WC-SYNC-00032` (**Delta Sync**, vom Scheduler-Tick um 12:40
automatisch enqueued) - zog gerade `crm_event` (3784, gerade erst aktiviert) und `stock_movement`
(Seite 41, ebenfalls gerade aktiviert, praktisch ein Erstimport von ~16.000 Datensätzen).
**Root Cause:** `scheduler.py` `_has_running_run(mode)` prüfte nur auf denselben Modus - der
Tick sah keinen laufenden "Delta Sync" (der Vollimport lief ja unter `mode="Full Import"`) und
enqueued einen neuen Delta-Sync-Job, OBWOHL der Vollimport noch aktiv war. Beide liefen dann
gleichzeitig gegen dieselbe WeClapp-Instanz (Rate-Limit-Konkurrenz - erklärt die Stockung) UND
gegen dieselbe ERPNext-DB (Existenzprüfung+Insert beim Upsert ist zwischen zwei Prozessen NICHT
atomar - Risiko doppelt angelegter Datensätze, falls beide zufällig denselben Datensatz treffen).
Dieselbe Lücke steckte auch im "Vollimport starten"-Button (`weclapp_settings.py`
`start_full_import()`) - prüfte nur auf einen zweiten laufenden Vollimport, nicht auf einen
laufenden Delta-Sync.
**Fix:** `_has_running_run()` (ohne Modus-Parameter) prüft jetzt auf JEDEN laufenden Sync-Lauf,
beide Stellen nutzen das. `WC-SYNC-00031` selbst wurde NICHT manuell eingegriffen (kein Write
gegen einen laufenden Job) - der bereits gesetzte `abort_requested=1` sollte greifen, sobald der
Job (jetzt ohne Konkurrenz durch neue Delta-Sync-Ticks) die nächste Seitengrenze erreicht.

### Nachtrag 2026-09-12: Artikelbilder, Beleg-PDFs, Lieferzeit-Felder (Cross-Session-Absprache)
Nutzer-Fragen: (1) Wiederbeschaffungstage/Durchschnittliche Lieferzeit aus WeClapp gesynct? (2)
Bilder bei Artikeln, Dokumente (PDFs) bei Belegen? (3) Für die Lieferzeit ein gemeinsames Feld
mit der `ecommerce_integrations`-App (Shopware-Anbindung, läuft als eigene Claude-Session)
aushandeln, statt getrennter Felder.

**procurementLeadDays/averageDeliveryTime:** ersteres -> ERPNexts natives `lead_time_days`
(kein Zusatzfeld nötig). Für `averageDeliveryTime` gibt's kein natives Pendant - **Cross-Session-
Absprache mit `ecommerce-integrations-9d`**: die Shopware-App wollte ihr eigenes `delivery_time`
NICHT von uns mitbenutzt haben (Begründung: bestehende Semantik "leer = Shopware-Standard-
Lieferzeit greift" auf schon produktiven Installationen, sonst Schreib-Wettlauf mit ihrem
eigenen Shopware-Sync). Einigung: eigenes Feld **`wc_average_delivery_time`** (Int, Tage) - die
Shopware-App liest es nur als Read-Only-Fallback, wenn ihr `delivery_time` leer ist (`order_
mapper.calculate_delivery_date` hat dafür laut ihrer Aussage schon ein Fallback-Präzedenzfall:
`delivery_time` -> `lead_time_days`). Kein Schreibzugriff unsererseits auf ihr Feld.

**Artikelbilder** (`articleImages`, im Artikel-Payload eingebettet - kein Extra-WeClapp-Aufruf):
war komplett ungebaut. **Download-Endpunkt live ermittelt** (WeClapp dokumentiert das nicht
offensichtlich über die generische `document`-Entität - `document?entityName=article&entityId=
...` liefert leer): die artikel-eigene Aktion `article/id/{articleId}/downloadArticleImage?
articleImageId={imageId}` (GET, 200 mit Bildinhalt, live verifiziert). Neue Client-Methode
`iter_article_image_content()` (streamend wie `iter_document_content()`). Neues Modul
`sync/mappers/_attachments.py`: `attach_article_images()` lädt jedes Bild einzeln und hängt es
als Frappe-File ans Item (`mainImage` zusätzlich als `Item.image`), idempotent über den WeClapp-
Dateinamen (kein erneuter Download bei Re-Runs). Aus `article.py` `upsert()` aufgerufen.

**Beleg-PDFs** (`document`-Entität, `entityName=<weclapp_doctype>&entityId=<id>`, live gegen
`salesInvoice` verifiziert - liefert Metadaten inkl. eines zusammengesetzten `id`-Strings wie
`"salesInvoice.2005691.2005698"`, der 1:1 an `document/id/{id}/download` geht). Die Client-
Methoden `get_documents()`/`iter_document_content()` gab es dafür schon seit Increment 1, waren
aber nie verdrahtet. `_attachments.attach_weclapp_documents()` jetzt aus `quotation.py`,
`sales_order.py`, `sales_invoice.py`, `shipment.py`, `purchase_order.py`, `purchase_invoice.py`
aufgerufen (jeweils kurz vor `return doc.name`) - hängt alle an den WeClapp-Beleg gehängten
Dateien (i.d.R. das ausgestellte PDF) idempotent (Dateiname-Abgleich) ans ERPNext-Dokument.

**Speicher-Prinzip gewahrt:** beide Funktionen laden nie mehr als EINE Datei gleichzeitig in den
Speicher (der WeClapp-Client streamt chunkweise, `b"".join(...)` sammelt genau diese eine Datei,
keine Vorab-Cache-Ordner wie im Vorgänger-Importer, siehe dessen `WC_CACHE_IMAGES_BASE`/
`WC_CACHE_DOCUMENTS_BASE` - dafür brauchte es dort einen separaten Cache-Lauf vor der eigentlichen
Migration).
**Noch nicht gegen die Live-Instanz getestet** (Custom Field + Client Script/Attachments nach
Redeploy prüfen).

### Nachtrag 2026-09-12: Set-/Bundle-Artikel (WeClapp "Stückliste") -> ERPNext Product Bundle
Nutzer-Fund: Artikel SK000076 (`articleType == "SALES_BILL_OF_MATERIAL"`, WeClapp nennt das im
UI "Stückliste" - eine reine Verkaufs-Bündelung, KEINE Fertigungs-Stückliste, keine eigene
Lagerbuchung der Komponenten) wurde als Item angelegt, aber seine Zusammensetzung
(`salesBillOfMaterialItems`, hier: SK000062 x1, SK000075 x2, SK000077 x4) war nirgends in
ERPNext sichtbar - der Mapper hat dieses Feld schlicht nie gelesen. Live per GET geprüft: **69
solcher Artikel** insgesamt (`articleType`-Enum: SHIPPING_COST, STORABLE,
SALES_BILL_OF_MATERIAL, LOADING_EQUIPMENT, PACKAGING_UNIT, SERVICE, SERVICE_QUOTA, BASIC,
LOADING_EQUIPMENT_STORABLE - nur SALES_BILL_OF_MATERIAL relevant für dieses Feature, war im
Vorgänger-Importer nie gebaut/dokumentiert).
**Fix:** `article.py` `_sync_product_bundle()` (aus `upsert()` aufgerufen, analog zu
`_sync_prices()`) bildet `salesBillOfMaterialItems` auf ERPNexts **Product Bundle** ab - das ist
genau das passende ERPNext-Konzept dafür (nicht-lagerhaltiger Verkaufsartikel, der beim
Beleg-Erfassen zu seinen Bestandteilen "explodiert", keine eigene Buchung/kein BOM/Manufacturing).
`Product Bundle.new_item_code` = Item-Code (Controller-Autoname, kein `set_name` nötig),
`items`-Kindtabelle aus den Komponenten. Komponenten über das schon vorhandene
`_transaction.resolve_line_item()` aufgelöst - legt bei Bedarf einen Stub-Artikel an, falls eine
Komponente in der Iterationsreihenfolge des Artikel-Vollimports noch nicht drankam (identisches
Muster wie bei Beleg-Positionen), ein späterer Durchlauf/Re-Run vervollständigt sie automatisch.
**Noch nicht gegen die Live-Instanz getestet.**

### Nachtrag 2026-09-12: doppeltes "Details" war ein GANZ ANDERER Bug (`wc_sync_section`)
Nutzer meldete den doppelten "Details"-Bereich erneut, obwohl der Zusatzfelder-Tab-Fix
(Increment 12, Commit 319a9f7) stand. **Per Live-GET verifiziert**
(`frappe.desk.form.load.getdoctype?doctype=Item`, read-only): `wc_zusatzfelder_tab` sitzt
korrekt bei idx 164 (direkt nach "Connections", wie erwartet) - der Zusatzfelder-Fix war also
tatsächlich in Ordnung. Der **echte, andere** Übeltäter: `wc_sync_section`
(`setup/custom_fields.py` `_wc_id_fields()`) hatte von Anfang an **gar kein** `insert_after` -
saß dadurch bei **idx 1**, VOR dem echten "Details"-Tab (idx 4). Frappe umhüllt Felder vor dem
ersten Tab Break mit einem impliziten, standardmäßig ebenfalls "Details" gelabelten Tab -> exakt
der doppelte "Details"-Bereich. Betraf **alle 15 `_WC_ID_DOCTYPES`**, nicht nur Item.
**Fix:** `_last_foreign_field(doctype)` berechnet jetzt live einen echten Anker (letztes Feld,
das NICHT selbst Teil der `wc_sync_section`/`wc_id`/`wc_last_modified`-Kette ist - sonst
Ringschluss bei der Neupositionierung). Läuft bei JEDEM `apply_custom_fields()`-Lauf (nicht nur
einmalig), dieselbe bereits verifizierte `.save()`-basierte Idx-Neuberechnung wie beim
Zusatzfelder-Tab-Fix repositioniert damit auch die bereits falsch stehenden Bestandsfelder aller
15 Doctypes automatisch beim nächsten `run_setup()` (kein manueller Nacharbeitsschritt nötig).

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
- **Ergebnis nach allen Fixes:** 99/99 Angebote, alle geprüften Brutto-Summen cent-genau gegen
  WeClapp (296,75 / 1166,37 / 437,36 / 466,44 / 118,17). Die 1 "übersprungene" ist AN-2025AN1056
  = WeClapp-Angebot mit 0 Positionen (`should_skip` korrekt). **Angebots-Mapper verifiziert.**
  Danach voller Angebots-Import erfolgreich durchgelaufen.

### Increment 14 (2026-09-10): Rechnungs-Mapper
- `sync/mappers/sales_invoice.py` (`SalesInvoiceMapper`, registriert, 6/14): Name =
  `<invoiceNumber>`, `_transaction`-Basis. `posting_date` aus `invoiceDate`, `due_date` =
  `max(dueDate, invoiceDate)`, `update_stock=0` (Lagerabgang läuft über Lieferschein/Stock),
  `payment_terms_template` = „Migration - unbegrenzt" (100 J.) + expliziter `payment_schedule`
  mit dem echten `dueDate` - sonst füllt ERPNext das Template aus `Customer.payment_terms` und
  lehnt unser `due_date` ab. `debit_to` lässt ERPNext aus `Customer.accounts` ziehen (= das
  individuelle DATEV-Debitorenkonto).
- **Gutschriften** (`salesInvoiceType == "CREDIT_NOTE"`): WeClapp führt Betrag/Menge positiv,
  ERPNext bekommt `is_return=1` mit negierten Mengen/Steuern/Kopfrabatt, kein payment_schedule.
  `check_gross_total(negate=is_return)`.
- `setup/custom_fields._doc_link_fields()`: `wc_sales_order` (Link Sales Order) auf Sales Invoice.
- `_transaction.check_gross_total` bekam `negate`-Param.
- WeClapp: 5326 Rechnungen. `salesInvoiceItems` + `shippingCostItems`. Typen STANDARD_INVOICE /
  CREDIT_NOTE. `netAmount <= 0` -> `should_skip` (Anomalie).
- Feld-Mapping-Referenz + gelöste Fachprobleme: Vorgänger invoice_migration.py + dessen CLAUDE.md.
- **1. Testlauf: 5256 ok, 31 fail, 39 skip.**
  - 29× „Einzelpreis muss positive Zahl sein" (Gutschriften + WeClapp-Reduktionszeilen wie
    „Schwinge ausgeschlagen −40"). Fix: `masters.setup_pricing_settings()` setzt jetzt auch
    `allow_negative_rates_for_items = 1` auf Selling + Buying Settings (Port von
    `setup_negative_rate_settings`). Auf der Testinstanz per API gesetzt.
  - 4× `FiscalYearError` „Buchungsdatum 31.12.**0023**" - WeClapp-Datumstippfehler („23" ->
    Jahr 0023). Fix: `h.clamp_posting_date()` klemmt Jahr außerhalb 2000..2100 auf den Beginn
    des frühesten Geschäftsjahres. In sales_invoice (posting/due) + sales_order (order_date).
  - 39 skip = `netAmount <= 0` (Anomalien), korrekt.
- **2. Testlauf: 5287 ok, 0 fail, 39 skip.** **Rechnungs-Mapper fertig + verifiziert.**

### Increment 18 (2026-09-11): CRM-Ereignisse + Lagerbewegungen
- `sync/mappers/crm_event.py` (`CrmEventMapper`, registriert, 10/14): WeClapp `crmEvent` ->
  `Communication`. Nur Telefonanrufe kommen in der echten Daten vor (`type` INCOMING_CALL/
  OUTGOING_CALL, ~3895 Events); andere Typen übersprungen. `partyId` -> Customer/Supplier über
  reinen DB-Lookup auf `wc_id` (live bestätigt: `party.id` == `Customer.wc_id`/`Supplier.wc_id`,
  WeClapp `customer`/`supplier`/`party` teilen sich den id-Raum) - **kein** zusätzlicher
  WeClapp-Aufruf pro Event nötig. Name `CRM-<id>`. Kein docstatus-Workflow (einmal angelegt,
  Re-Runs überspringen - Anrufhistorie ändert sich nicht nachträglich).
- `sync/mappers/stock_movement.py` (`StockMovementMapper`, registriert, 11/14): WeClapp
  `warehouseStockMovement` -> `Stock Entry`. **Bleibt IMMER Entwurf**, anders als der Vorgänger
  (der hat damit einmalig real den ERPNext-Lagerbestand nachgebaut - der einzige Schritt dort,
  der das tat). Für den laufenden Sync zu riskant, solange der Lagerbestand-Aufbau nicht separat
  geklärt ist - ein 1:1-Nachbau bleibt ein bewusster, einmaliger Extra-Schritt (gezieltes
  Submitten), nicht Teil des Syncs. `articleId` -> `Item.wc_id` (DB-Lookup), `storagePlaceId` ->
  `storagePlace.warehouseId` -> `warehouse.name` -> `h.ensure_warehouse()` (zwei kleine, einmalig
  pro Lauf gecachte WeClapp-Listen: `storagePlace` ~1350, `warehouse` <20). Name `LB-<id>`.
  WeClapp: 15939 Lagerbewegungen.
- Damit **11 von 14** Objekttypen registriert. Bewusst weiter unregistriert (siehe Increment 15):
  `sales_payment`/`purchase_payment` (Zahlungsabgleich - erst für Live-Betrieb). `article_price`
  bleibt ebenfalls unregistriert, weil bereits vollständig `article._sync_prices()` mit erledigt
  (WeClapp liefert `articlePrices` eingebettet im `article`-Payload, keine eigene Abfrage nötig).
- **Noch nicht getestet.**
- **Nutzer-Fund direkt danach:** die Objekttyp-Tabelle in den Settings zeigte `article_price`
  trotzdem als eigene, ankreuzbare Zeile ("(Mapper fehlt)") - wirkte wie ein eigener, nur noch
  nicht gebauter Sync-Schritt, obwohl er nie einen eigenen bekommt. Auf Nutzer-Wunsch **ganz aus
  `registry.SYNC_ORDER` entfernt** (nicht nur umbeschriftet) - `article_price` taucht in der
  Objekttyp-Tabelle jetzt gar nicht mehr auf (Tabelle wird bei jedem `validate()` aus
  `SYNC_ORDER` neu aufgebaut, räumt die alte Zeile automatisch weg). **Effektiv 13 sinnvolle
  Objekttypen insgesamt** (nicht mehr 14) - `sales_payment`/`purchase_payment` bleiben als
  Zeilen mit erklärendem Hinweis stehen, weil die echt noch kommen (nur später).

### Increment 17 (2026-09-11): Einkaufsseite (Bestellung + Eingangsrechnung)
- `sync/mappers/purchase_order.py` (`PurchaseOrderMapper`, registriert, 8/14): spiegelbildlich
  zu `sales_order.py` - `_transaction`-Basis mit `is_selling=False` (`expense_account`,
  Einkaufssteuer-Fallback `default_purchase_tax_account`). Name = WeClapp-`purchaseOrderNumber`.
  `schedule_date` aus `plannedDeliveryDate` (Header+Position), Lager aus `warehouseName`
  (wie Auftrag). `wc_sales_order`-Link für Streckengeschäft (WeClapp `salesOrderNumber` an der
  Bestellung, falls direkt für einen Verkaufsauftrag beim Lieferanten bestellt).
- `sync/mappers/purchase_invoice.py` (`PurchaseInvoiceMapper`, registriert, 9/14): Name =
  WeClapp-**`internalInvoiceNumber`** (FranceTecs eigene Nummer) - **nicht** `invoiceNumber`
  (das ist die Nummer des Lieferanten, landet in `bill_no`). `update_stock=0`, 100-Jahre-
  Zahlungsziel-Template + expliziter `payment_schedule` (gleiche `Customer`/`Supplier.
  payment_terms`-Falle wie bei Sales Invoice). Gutschriften (`purchaseInvoiceType ==
  "CREDIT_NOTE"`) negiert wie beim Verkauf. `wc_paid`/`wc_payment_status` info-only (gleiche
  Design-Entscheidung wie Sales Invoice, siehe Increment 15). Belegkette `wc_purchase_order`
  aus `purchaseOrders[0].id` -> Auflösung über `frappe.db.get_value("Purchase Order",
  {"wc_id": ...})` (einfacher als die Vorgänger-Lösung mit eigener id->Nummer-Lookup-Tabelle,
  weil unsere Belege sowieso `wc_id` führen).
  `importSalesTaxAmount` (Einfuhrumsatzsteuer bei Drittland-Importen, ~2/500) als zusätzliche
  Actual-Steuerzeile auf das Fallback-Einkaufssteuerkonto (kein eigenes `taxId`, daher kein
  Steuer-Mapping-Eintrag möglich).
  **`should_skip` schärfer als der Vorgänger:** zusätzlich `status not in (OCR_VERIFICATION,
  CANCELLED)` - live geprüft, `OCR_VERIFICATION`-Belege (unverifizierte OCR-Entwürfe) haben
  teils schon eine `supplierNumber`, der reine Lieferanten-Check reicht hier nicht mehr;
  `CANCELLED` hat reale (auch positive) `netAmount`-Werte, würde sonst durchrutschen.
- `setup/custom_fields.py`: `wc_sales_order` (Purchase Order), `wc_purchase_order`/`wc_paid`/
  `wc_payment_status` (Purchase Invoice).
- WeClapp: 667 Bestellungen, 2885 Eingangsrechnungen (482 STANDARD_INVOICE + 18 CREDIT_NOTE in
  einer 500er-Stichprobe der bereits abgeschlossenen, `OPEN_ITEM_CREATED`/`CANCELLED`).
- **1. Testlauf: purchase_order 100/0, purchase_invoice 96/0/4 (1 Seite), 0 Bruttoabweichungen,
  Stichprobe cent-genau.** Dabei gefunden: WeClapp `purchaseInvoice.paid` ist bei **allen**
  Belegen `null` (anders als `salesInvoice`, wo das Bool zuverlässig gesetzt ist) - `wc_paid`
  wäre sonst immer 0 gewesen. Fix: `wc_paid` jetzt zusätzlich aus `paymentStatus == "PAID"`
  abgeleitet (`record.get("paid") or record.get("paymentStatus") == "PAID"`), in **beiden**
  Rechnungs-Mappern (sales_invoice + purchase_invoice) aus Konsistenzgründen.

### Increment 16 (2026-09-11): Lieferschein-Mapper
- `sync/mappers/shipment.py` (`ShipmentMapper`, registriert, 7/14): Name = WeClapp-`shipmentNumber`.
  **Bleibt immer Entwurf (docstatus 0), egal was `submit_documents` sagt** - ein submitteter
  Delivery Note bucht in ERPNext unbedingt auf den Lagerbestand (kein `update_stock`-Opt-out,
  anders als Sales Invoice - im Vorgänger live bestätigt). Sobald `stock_movement` gebaut ist,
  bildet der dieselbe Wareneinbewegung schon ab -> submitten würde doppelt abziehen.
- `should_skip`: nur `status == "SHIPPED"` (NEW/DELIVERY_NOTE_PRINTED haben das Lager noch
  nicht verlassen). WeClapp: 3351 shipments gesamt, in einer 500er-Stichprobe (älteste zuerst)
  494 SHIPPED / 6 CANCELLED - gute Abdeckung.
  Positionen: `rate`/`price_list_rate` = 0 + `is_free_item=1` (reine Lieferdokumentation, keine
  Finanzdaten - die stehen auf der Rechnung; `is_free_item` verhindert wie bei den anderen
  Belegen einen Preislisten-Override der 0). Lager aus `record.warehouseName` (Header-Feld,
  wie bei `sales_order` - kein Pick-Storage-Place-Feingranulat, rein informativ ohnehin).
- Felder: `wc_sales_order` (Link), `wc_tracking_nummer`, `wc_versanddienstleister`.
- **Noch nicht getestet.**
- **Nutzer-Fund nach dem ersten Vollimport:** Lieferadresse fehlte, nur Rechnungsadresse da.
  Ursache: ohne explizites Setzen zieht ERPNext nur die Kunden-Standardadresse; WeClapp führt
  am Shipment aber eine EIGENE `recipientAddress`/`invoiceAddress` (kein Adress-Datensatz mit
  eigener id, nur eingebettet), die abweichen kann (Live-Beispiel geprüft: id 2004884 - dort
  identisch, aber strukturell eigenständig). Fix: `_match_customer_address()` sucht eine
  bestehende Kunden-Address mit gleicher Straße/PLZ (dann Link `shipping_address_name`/
  `customer_address`), sonst nur Text (`shipping_address`/`address_display` via
  `_address_text()`). **Lieferscheinnummer-Frage geklärt:** ist da (`name` = `shipmentNumber`,
  live verifiziert: id 2004884 -> ERPNext-Name "5243" = WeClapp `shipmentNumber`) - nur nicht
  die fett angezeigte Titelzeile, die zeigt bei Delivery Note laut Doctype-Meta `customer_name`
  (`title_field`, ERPNext-Standardverhalten) - Nummer steht in URL/ID-Zeile/Listenansicht.
**Kein `sales_payment`-Mapper mit Payment Entries für den historischen Bestand.** Grund: Solange
`submit_documents = 0` ist, sind alle importierten Belege Entwürfe (docstatus 0) - die erzeugen
KEINE echte GL-Buchung/Bestandsbewegung. Die alten Rechnungen sind in WeClapp (und beim
Steuerberater) längst real gebucht; sie in ERPNext zusätzlich zu "submitten" wäre eine
Doppelbuchung reiner Vergangenheit. Ein Entwurf-Payment-Entry dazu würde ebenfalls nichts Echtes
buchen und den offenen Betrag der (auch nicht submitteten) Rechnung nicht mal verändern - der
ganze Vorgänger-Aufwand (Buchungsjournal-Abgleich für Bankkonto + Zahlung-vs-Abschreibung-
Unterscheidung, siehe `reference/migration_logic/full_field_mapping/payment_entry_migration.py`)
wäre für diesen Fall verschwendete Mühe.
- **Stattdessen:** rein informative Felder direkt an der Rechnung, aus WeClapp `paid`/
  `paymentStatus` (die Rechnung selbst führt das schon - kein Umweg über `salesOpenItem`/
  `accountingTransaction` nötig): `wc_paid` (Check) + `wc_payment_status` (Data, Rohwert:
  PAID/OPEN/CLEARED_WITH_CREDIT_NOTE/NO_OPEN_ITEM/...). In `sales_invoice.py` gesetzt.
- **"Später zuordnen" geht ohne Zusatzarbeit:** die Rechnung existiert mit `wc_id` + WeClapp-
  `invoiceNumber` als Name - eine künftige ECHTE Zahlung (live, nach Umstellung) referenziert sie
  ganz normal über `reference_doctype: "Sales Invoice", reference_name: <Name>`.
- **Für den Live-Betrieb** (wenn `submit_documents` an ist): dann braucht es einen echten
  `sales_payment`-Mapper mit Payment Entries - aber nur für laufende, neue Zahlungen (Delta-Sync-
  Volumen, nicht 5300 historische), dort kann die Vorgänger-Logik (Journal-Abgleich fürs
  Bankkonto, Abschreibungs-Journal-Entries) als Vorlage dienen. **Noch nicht gebaut - erst wenn
  der Nutzer live geht.**

### Belegketten-Tiefe - Design-Entscheidung (mit Nutzer abgestimmt)
Einfache Link-Felder (`wc_quotation`, `wc_sales_order`) reichen - **kein** Umbau auf ERPNexts
native Positions-Verknüpfung (`Sales Invoice Item.sales_order`+Zeilen-ID, Connections-Tab,
%-geliefert/fakturiert-Rollups). Das würde Artikel/Menge-Matching zwischen WeClapp-Auftrags- und
-Rechnungspositionen brauchen - deutlich mehr Aufwand, für reine Nachvollziehbarkeit nicht nötig.
**Rechnung → Gutschrift lässt sich nicht verknüpfen:** WeClapp liefert bei `CREDIT_NOTE`-Belegen
keine Referenz auf die Ursprungsrechnung (weder am Kopf noch `salesInvoiceItemRelationship` an
den Positionen, live geprüft an mehreren Belegen - immer leer). Keine Verknüpfung, kein Rate-Code.
**Lieferschein → Auftrag:** analoges `wc_sales_order`-Link-Feld, sobald der Mapper existiert.

### Increment 13 (2026-09-10): Auftrags-Mapper + API-Update + Belegnamen ohne Präfix
- `sync/mappers/sales_order.py` (`SalesOrderMapper`, registriert, 5/14): Dokumentname =
  WeClapp-`orderNumber` (**kein Präfix**), gleiche `_transaction`-Basis wie Angebot (Positionen,
  Actual-Steuerzeilen, Kopfrabatt, `is_free_item` für Nullzeilen, `ignore_pricing_rule`).
  Zusätzlich: `transaction_date` aus `orderDate`, `delivery_date` aus `plannedShippingDate`
  (Header + je Position), optional `submit`. Belegkette: `wc_quotation` (read-only Link
  Quotation) aus `quotationNumber` - nur ~1/50 Aufträge haben eins.
- `setup/custom_fields._doc_link_fields()`: `wc_quotation` auf Sales Order.
- **Belegnamen ohne Präfix** (Nutzer-Wunsch): Angebot heißt jetzt `<quotationNumber>` statt
  `AN-<...>`, Auftrag `<orderNumber>` statt `SO-<...>`. `autoname=Prompt` erlaubt das.
  → bereits importierte 99 Angebote behalten ihr `AN-`-Präfix (wc_id-Abgleich); für saubere
  Namen einmal löschen + neu importieren.
- **`TransactionMapper.check_gross_total()`**: nach Insert Bruttosumme gegen WeClapp
  `grossAmount` prüfen, bei Abweichung > 1 ct nur Error-Log (kein Abbruch) - wie
  `_post_validation` im Vorgänger. In quotation + sales_order eingehängt.
- `build_lines` sortiert Positionen jetzt nach `positionNumber`.
- **WeClapp API-Update (2026-09-10) eingearbeitet:** `client._request` respektiert
  `X-Weclapp-Wait-Ms` (wartet vor dem nächsten Call) und retryt 429/503 gebremst
  (`_MAX_RETRIES=4`, Sleeps auf 30 s gedeckelt). `headerDiscount/Surcharge` null->0 und
  Entfall `ADDITION_ABSOLUTE`/`REDUCTION_ABSOLUTE`: **betrifft uns nicht** (wir nutzen
  `netAmount` + Prozent-Kopfrabatt, keine absoluten Rabatt-Typen, kein `rebate`).
  `positionNumber`-Pflicht bei `/contract`,`/purchaseOrderRequest`,`/purchaseInvoice`:
  relevant erst beim Einkaufs-Rechnungs-Mapper. Neue Summenfelder (`vatAmount`,
  `netAmountWithoutShippingCosts`) - für spätere Plausibilitätsprüfungen nutzbar.
- WeClapp: 3545 Aufträge. Gemischte Steuersätze pro Beleg (19 % + 7 %) kommen vor.
- **1. Testlauf: 190 ok, 3354 `WarehouseRequired`** -> `h.ensure_warehouse(record["warehouseName"])`
  ("Hauptlager Langgöns" bei 99/100, on-demand angelegt) + Settings-Feld `default_warehouse`,
  je Position gesetzt. `default_warehouse()` fällt zurück: Settings -> `Company.default_warehouse`
  -> erstes aktives Nicht-Gruppen-Lager.
- **2. Testlauf: 3105 ok, 439 fail** - Rest = Amazon-Aufträge (`salesChannel GROSS7`) ohne
  WeClapp-Lager, `default_warehouse` war nicht gesetzt -> Fallback-Kette (s.o.) eingebaut.
- **Bruttosummen:** 3105 Aufträge, nur **1** Abweichung (`check_gross_total`): 2026AU2234
  ERPNext 257,62 vs WeClapp 260 (-2,38). Ursache: WeClapp-Steuer `1407276` „IT IVA ridotta"
  (OSS, ermäßigt IT) hat **in WeClapp selbst keine Konten** -> nicht im Steuer-Mapping ->
  `_accumulate_tax` verschluckte die Zeilensteuer. Fix: **Fallback-Steuerkonto** (Settings
  `default_sales_tax_account` / `default_purchase_tax_account`). `_accumulate_tax`/`build_tax_rows`
  bucketn jetzt **pro ERPNext-Konto** (nicht mehr pro `taxId`); nicht gemappte Steuern gehen
  aufs Fallback-Konto statt verloren. Nutzer sollte den Fallback auf `1767` (USt EG-Land) setzen.
- **Verifiziert cent-genau:** 2026AU2289/2288, 11510 (= WeClapp `grossAmount`).
- **3. Testlauf: 3541 ok, 3 fail, 1 skip.** 3 Rest-Fehler behoben: 2x `plannedShippingDate`
  vor `orderDate` -> `delivery_date = max(plannedShippingDate, orderDate)`; 1x Negativ-Auftrag
  (WeClapp-Retoure `netAmount < 0`, "Grand Total must be >= 0") -> `should_skip`. Die 1
  Bruttoabweichung (2026AU2234) bleibt bis der Nutzer `default_sales_tax_account` = 1767 setzt.
  **Auftrags-Mapper damit im Wesentlichen durch.**

### Increment 12 (2026-09-10): Zusatzfeld-Mapper (UI statt Code-Liste)
Der Vorgänger-Importer hatte die customAttribute->Custom-Field-Zuordnung als kuratierte
Python-Listen (`setup.py` `setup_custom_fields`, `EN_CUSTOM_ATTRIBUTE_EXCLUDE`, ...).
Hier stattdessen **UI-gesteuert**:
- Neues Child-Doctype **WeClapp Custom Attribute Mapping** (`custom_attribute_mappings` in den
  Settings, Abschnitt "Zusatzfelder"). Pro (Attribut, WeClapp-Objekt) eine Zeile: lesbare
  Bezeichnung (`label`), WeClapp-Typ, Gruppe, Ziel-Doctype(s), `enabled`, `target_fieldname`
  (vorbelegt via `h.custom_fieldname`), `fieldtype` (vorbelegt aus `attributeType`),
  `field_options` (aus `selectableValues`), `field_status` (vorhanden/fehlt/teilweise).
- Button **"Zusatzfelder aus WeClapp laden"** (`populate_custom_attribute_mapping`): holt alle
  99 `customAttributeDefinition` (read-only), baut die Tabelle neu, Nutzer-Auswahl bleibt.
- Button **"Ausgewählte Felder anlegen"** (`apply_custom_attribute_fields`): legt je aktivierter
  Zeile das fehlende Custom Field an (Sammel-Sektion "WeClapp Zusatzfelder" pro Doctype),
  schreibt `field_status` zurück. Läuft auch in `run_setup()` (idempotent).
- `setup/custom_attribute_fields.py`: `WC_ENTITY_DOCTYPES` (article->Item, party->Customer/
  Supplier/Contact, salesOrder->Sales Order, ...), `ATTR_TYPE_TO_FIELDTYPE`, `field_map(doctype)`.
- `sync/mappers/_custom_attributes.resolve()` nimmt jetzt `field_map` (nur aktivierte Zeilen des
  Ziel-Doctypes) statt `target_doctype` + Feldname-Raten. `Mapper.custom_attribute_field_map()`
  lädt sie einmal pro Lauf. customer/supplier/article/quotation angepasst.
- WeClapp `customAttributeDefinition`-Bestand: 99 Defs (article 76, party 19, salesOrder 4,
  shipment 4, salesInvoice 2, salesOrderItem 1). Typen: STRING 38, BOOLEAN 30, LIST 10,
  MULTISELECT_LIST 9, LARGE_TEXT 8, DECIMAL 3, URL 1. Alle mit `label`, viele mit `groupName`.
- **MULTISELECT_LIST -> „Table MultiSelect"** (Increment 12b): je aktiviertem Multiselect-
  Zusatzfeld werden zwei Custom-DocTypes generiert - Master `WC ZF <Label>` (Data-Feld `wert`,
  unique) + Child `WC ZF <Label> Eintrag` (Link `wert` -> Master). `_ensure_ms_doctypes` /
  `_sync_ms_values` (füllt Master aus `field_options` = WeClapp `selectableValues`).
  `resolve()` gibt für Table MultiSelect `[{"wert": v}, ...]` zurück. Feldtyp im Mapping
  umstellbar (dann Fallback ", "-Text).
- **Layout:** `apply_custom_attribute_fields()` legt je Ziel-Doctype einen Reiter „WeClapp
  Zusatzfelder" an, darin je WeClapp-`groupName` eine Sektion (statt einer flachen Sammel-
  Sektion). `_raw_value` deckt jetzt DATE (`dateValue`) + DECIMAL-als-String ab.
- **Nutzer-Fund 2026-09-11 (Artikel SK000034/SK000074): zwei Bugs, einer echt, einer keiner.**
  1. **Echter Bug - Feld-Reihenfolge lief aus dem Tab:** `_layout()`s Anker für NEUE Gruppen/
     Felder bei einem Folge-Lauf war `_last_field(doctype)` = das letzte Feld des GANZEN
     Doctypes - nicht das letzte Feld INNERHALB unseres "WeClapp Zusatzfelder"-Tabs. Auf einer
     Instanz mit weiteren Apps (hier: Shopware-/AI-Zusatzfelder auf Item, fremd) landete das
     nach deren Feldern, außerhalb unseres Tabs - im Formular als zweiter, fälschlich
     "Details" gelabelter Bereich sichtbar (Frappe gruppiert positionslose Folgefelder unter
     den nächsten erreichbaren Tab-Kontext). **Fix: `apply_custom_attribute_fields()` jetzt
     selbstheilend** - berechnet bei JEDEM Lauf die komplette Soll-Kette für alle aktivierten
     Felder (nicht nur neue). Tab-Position selbst wird nie angefasst (andere Apps könnten
     seither dahinter eingefügt haben).
     **Nachfassung (Nutzer meldete: Bereich immer noch doppelt):** der erste Fix reichte nicht -
     er kettete bestehende Felder per `frappe.db.set_value(..., "insert_after", ...)` um, aber
     das ändert die tatsächliche Formular-Position NICHT. Die hängt an `idx`, das Frappe nur
     neu berechnet, wenn ein Custom Field regulär über `.save()` läuft. Jetzt läuft die
     komplette Soll-Kette bei JEDEM Lauf für ALLE aktivierten Felder durch
     `create_custom_fields()` - auch längst vorhandene (das übernimmt intern das `.save()`
     inkl. `idx`-Neuberechnung). Rückgabe jetzt `res["touched"]` statt `created`/`repaired`.
  2. **Kein Bug - "Steuer"-Tab leer ist Absicht:** Item Tax Template wird bewusst NICHT gesetzt
     (Steuer läuft pro Belegzeile als "Actual", siehe Docstring in `article.py` + Vorgänger-
     CLAUDE.md Punkt 5 "Item-Steuer-Template-Konflikt").
  3. **Kein Bug - "leere Zusatzfelder" bei SK000074:** live geprüft, `Item.modified ==
     Item.creation` (2026-09-09 19:50, der erste Artikel-Vollimport) - der Artikel wurde seit
     Anlage der Zusatzfelder-Mapping-Einträge **nie erneut synct** (kein Delta-/Vollimport lief
     seither über diesen Datensatz). WeClapp hat für ihn reichlich befüllte Attribute (u.a.
     `4444` -> `artikelbeschreibung_francetec`, aktiviert). Braucht nur einen frischen
     Artikel-Vollimport, kein Code-Fix.
- **Item Tax Template: gesetzt, sofort als Regression zurückgerollt (2026-09-11).** Auf
  Nutzer-Nachfrage ("woher weiß ERPNext bei künftigen Belegen den Satz?") aus `article.
  taxRateType` (`STANDARD`/`REDUCED`, 127 Artikel `REDUCED`) gesetzt - fälschlich als "betrifft
  migrierte Belege nicht" eingeschätzt. **War falsch:** reproduzierte 1:1 den vom Vorgänger
  dokumentierten "Item-Steuer-Template-Konflikt" ("Artikelbezogene Steuerdetails stimmen nicht
  mit den Steuern und Abgaben überein") - live beim nächsten Vollimport 46 Angebote + 506
  Aufträge gescheitert (ERPNext vergleicht den vom Template erwarteten Betrag gegen unsere
  Actual-Zeilen, schlägt fehl sobald ein Artikel historisch zu einem anderen Satz verkauft
  wurde). **Sofort zurückgerollt:** `to_doc_fields()` schreibt `"taxes": []` wieder **explizit**
  (nicht nur weglassen - sonst bleibt ein einmal gesetztes Template stehen, weil ein fehlender
  Dict-Key die bestehende Kindtabelle nicht anfasst). `_item_tax_rows()`/`_TAX_RATE_TEMPLATES`
  bleiben als unbenutzter, fertiger Baustein für einen **separaten, einmaligen Schritt kurz vor
  der Live-Umstellung** (analog zur `sales_payment`-Entscheidung, Increment 15) - nicht Teil des
  laufenden Syncs. **Nutzer muss den Artikel-Vollimport erneut laufen lassen**, um die während
  des kurzen Regressionsfensters gesetzten Templates wieder zu entfernen, bevor Angebot/Auftrag/
  Rechnung erneut importiert werden.
- **Offen am Zusatzfeld-Mapper:** Belegzeilen-Entities (`salesOrderItem` etc.) - Felder werden
  angelegt, aber `_transaction.build_lines` ruft `ca.resolve` noch nicht pro Position;
  `crmEvent` (kein Mapper); neue WeClapp-Auswahlwerte brauchen erneutes „Laden" + „Anlegen",
  sonst scheitert der einzelne Datensatz (Link-Validierung, wird geloggt).
- **Bewusst so (kein Bug):** eine deaktivierte Mapping-Zeile lässt ihr Feld stehen (kein
  Datenverlust); generierte MS-DocTypes bleiben bei Deinstallation liegen.
- **Feldname aus der Bezeichnung:** `suggested_fieldname(label, key)` slugifiziert die lesbare
  WeClapp-Bezeichnung (Umlaut-Translit) -> `citroen_originalnummer` statt `cf_4437i966...`.
  Fallback auf den technischen `attributeKey` nur, wenn der Slug leer ist / mit Ziffer beginnt.
  Das ERPNext-Feld-**Label** ist die volle WeClapp-Bezeichnung, `description` = "WeClapp-
  Zusatzfeld: <key>".
- **WeClapp Settings in Reiter aufgeteilt** (Tab Break): „Verbindung & Sync" / „Mapping-
  Standardwerte" / „Preiskanäle" / „Steuer & Konten" / „Zusatzfelder".
- **Editierbares `target_label`** (Spalte „ERPNext-Feld-Label") + Grid-Button „Vorhandenes
  Feld zuordnen …" (`weclapp_settings.js` `assign_existing_field`): Dialog mit Ziel-Doctype +
  Feldauswahl aus allen vorhandenen Standard-/Custom-Feldern -> setzt
  target_fieldname/target_label/fieldtype. Zeigt ein WeClapp-Attribut auf ein bestehendes
  Feld, wird beim „Anlegen" nichts Neues erzeugt (Status „vorhanden").

### Increment 11 (2026-09-10): kontrollierter Abbruch für laufende Importe
- Feld `abort_requested` (Check) + Status `Aborted` am *WeClapp Sync Run*; `weclapp_sync_run.js`
  Button "Abbruch anfordern" (nur bei Status Running).
- `engine.sync_object_type()`: prüft `_abort_requested(run_name)` an jeder Seitengrenze -> stoppt
  kontrolliert (`result.status="aborted"`, kein Watermark, `progress_page` bleibt); `run_sync()`
  bricht dann die Objekttyp-Schleife ab, `_finish_run()` setzt Status `Aborted`.
- `scheduler._STALE_HOURS` 6 -> 1 (ein hart gekillter RQ-Job hängt sonst 6 h als "Running" und
  blockiert neue Läufe; `recover_stale_runs` räumt ihn jetzt nach 1 h weg).
- Hintergrund: RQ Job stoppen allein lässt den Run auf "Running" -> `start_full_import` und der
  Scheduler denken, es läuft noch. Der Button ist der saubere Weg.

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
