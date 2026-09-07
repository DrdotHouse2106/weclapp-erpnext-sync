# CLAUDE.md

Projektinterne Referenz - **noch kein Code, nur Scaffold + Plan.** Diese Datei nach jeder Session
mit neuen Erkenntnissen aktualisieren (Konvention aus dem Schwesterprojekt, siehe unten).

## Was das hier werden soll

Eine installierbare Frappe/ERPNext-App, die WeClapp laufend und automatisch nach ERPNext
synchronisiert (einseitig, WeClapp → ERPNext - kein Zurückschreiben). Ziel: Übergangsphase, in
der beide Systeme parallel laufen, ohne doppelte manuelle Datenpflege. Nutzer installiert die App,
trägt WeClapp-Zugangsdaten in einem Settings-Doctype ein, der Rest läuft automatisch über Frappes
eigenen Scheduler.

**Direktes Vorbild:** `/Users/marcelulber/Programmierung/ecommerce_integrations` (Shopware ↔
ERPNext) macht strukturell genau das, nur bidirektional und für ein anderes Quellsystem. Bei
Unklarheiten zur Frappe-App-Konvention (hooks.py, Settings-Doctype-Muster, Scheduler-Events) lohnt
ein Blick dorthin.

## Herkunft: verwandtes Projekt

`/Users/marcelulber/weclapp-erpnext-migration` (GitHub:
`DrdotHouse2106/weclapp-erpnext-migration`) ist der abgeschlossene **einmalige Batch-Import**
WeClapp → ERPNext (siehe dessen eigene CLAUDE.md für den vollen Verlauf - viele dort schon gelöste
Probleme, z. B. Steuer-Mapping-Fallstricke, Personenkonto-Zuordnung, Zahlungsabgleich-Heuristiken,
gelten hier vermutlich genauso). Dieses Repo hier ist bewusst **kein Fork/keine Erweiterung**
davon, sondern eine neue Laufzeit-Architektur für denselben fachlichen Zweck - siehe README.md
für das "Warum".

`reference/` enthält 1:1 kopierten Code aus diesem Ursprungsprojekt, NICHT direkt lauffähig hier,
sondern Ausgangspunkt/Blaupause:
- `reference/base/` - `ApiBase`/`ApiException`/`DocType`-Abstraktionen, wahrscheinlich direkt
  wiederverwendbar.
- `reference/weclapp/wc_api.py` - der WeClapp-REST-Client. **Wichtig: aktuell strukturell
  read-only** (`create()`/`update()`/`delete()` verweigern jeden Aufruf, `_request()` lehnt
  Nicht-GET-Methoden ab) - das passt exakt zu diesem Projekt (wir wollen nie nach WeClapp
  zurückschreiben), diese Garantie beibehalten. `get_all()` holt aktuell aber IMMER alle
  Datensätze eines Typs, keine Filterung - siehe "Offene technische Fragen" unten, das ist der
  wichtigste Umbau.
- `reference/weclapp/wc_doctypes.py` - Enum aller WeClapp-Objekttypen.
- `reference/migration_logic/en_helper.py` - deterministische Namens-/Mapping-Helfer
  (`get_wc_warehouse_name()` etc.) - die Konvention "Namen direkt aus WeClapp-Nummern ableiten,
  kein persistiertes Mapping" gilt hier genauso und sollte übernommen werden.
- `reference/migration_logic/full_field_mapping/` - der komplette `migration/`-Ordner des
  Ursprungsprojekts (ein Modul pro Objekttyp: Customer, SalesOrder, Item, ...). Die eigentliche
  Feld-Mapping-Logik (WeClapp-Feld → ERPNext-Feld) ist der wertvollste Teil und lässt sich
  fachlich fast 1:1 übernehmen - **muss aber technisch umgebaut werden**: dort wird über
  `ERPNextAPI` (REST-Aufrufe gegen `en_api.py`) geschrieben, hier läuft der Code IN ERPNext und
  sollte stattdessen Frappes native `frappe.get_doc()`/`.insert()`/`.save()` nutzen - kein
  Umweg über REST/HTTP zu sich selbst. `en_api.py` selbst wurde deshalb bewusst NICHT mitkopiert.

## Architektur-Plan (Entwurf, noch nicht umgesetzt)

1. **Frappe-App-Grundgerüst** (`bench new-app weclapp_sync` o. ä.), `hooks.py` mit
   `scheduler_events` für den periodischen Sync-Job (Intervall konfigurierbar).
2. **Settings-Doctype** ("WeClapp Settings", Single-Doctype): API-Token, Basis-URL,
   welche Objekttypen syncen (Checkboxen pro Typ, analog zu WeClapps eigenen Doctypes),
   Sync-Intervall, evtl. Zeitstempel des letzten erfolgreichen Laufs pro Objekttyp (für den
   Delta-Filter, siehe unten).
3. **Delta-Sync statt Vollabgleich:** WeClapp-Entitäten haben `lastModifiedDate`/`version`-Felder
   (live im Cache des Ursprungsprojekts bestätigt) - `wc_api.py`s `get_all()` muss um
   Filter-Unterstützung erweitert werden (WeClapps API unterstützt Query-Filter, siehe die vom
   Nutzer geteilte Endpunkt-Liste), damit pro Lauf nur `lastModifiedDate >= letzter_sync_zeitpunkt`
   abgefragt wird - sonst skaliert das bei tausenden Bestandsdatensätzen nicht (siehe
   `weclapp-erpnext-migration`s Erfahrung mit dem `_skip_if_exists()`-Bulk-Fix, ähnliches Problem
   in Grün).
4. **Upsert-Semantik pro Objekttyp**, aufbauend auf den deterministischen Namen aus
   `en_helper.py` - existiert das Ziel-Dokument schon (Name bekannt), `frappe.get_doc(...).save()`
   mit aktualisierten Feldern, sonst `frappe.new_doc(...).insert()`. Idempotenz-Prinzip aus dem
   Ursprungsprojekt (jede Migration prüft vor dem Schreiben, ein Fehler bei einem Datensatz bricht
   nie den ganzen Lauf ab) unbedingt beibehalten.
5. **Status-/Fehler-Sichtbarkeit** für den Nutzer - mindestens ein Log/Report, welche Datensätze
   beim letzten Lauf fehlgeschlagen sind (kein stiller Fehlschlag, siehe `ecommerce_integrations`
   für ein bestehendes Muster).

## Offene technische Fragen (vor dem Bau zu klären)

- Unterstützt WeClapps REST-API serverseitige Filterung nach `lastModifiedDate` (Query-Parameter,
  analog zu ERPNexts `filters`)? Noch nicht live getestet, nur die Datenfelder selbst sind
  bestätigt vorhanden.
- Reihenfolge/Abhängigkeiten beim Delta-Sync: die ursprüngliche Migration hatte eine feste
  Reihenfolge (Kunden vor Rechnungen vor Zahlungen, wegen Fremdschlüsseln) - bei einem
  Delta-Sync mit potenziell nur einzelnen geänderten Rechnungen muss sichergestellt sein, dass
  referenzierte Kunden/Artikel schon existieren, sonst pro-Lauf-Reihenfolge oder
  Nachzieh-Logik nötig.
- Soll es einen "einmaligen Vollabgleich"-Modus geben (für die Erstinstallation, wenn noch kein
  `weclapp-erpnext-migration`-Lauf existiert) getrennt vom laufenden Delta-Sync? Für dieses
  konkrete Setup vermutlich nicht nötig (die Vollmigration ist über das Schwesterprojekt bereits
  erledigt), aber für Portabilität/andere Installationen relevant.

## Sonstiges

- GitHub: `https://github.com/DrdotHouse2106/weclapp-erpnext-sync` (öffentlich).
- Ursprungsprojekt-Konvention laut dessen eigener CLAUDE.md: "Diese Datei wird laufend
  aktualisiert" und "Immer auf Deutsch antworten" - beides hier übernommen.
