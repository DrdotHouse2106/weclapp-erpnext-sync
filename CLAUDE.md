# CLAUDE.md

Projektinterne Referenz - **noch kein Code, nur Scaffold + Plan.** Diese Datei nach jeder Session
mit neuen Erkenntnissen aktualisieren (Konvention aus dem Ursprungsprojekt, siehe unten).

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
4. **Delta-Filter:** WeClapp-Entitäten haben `lastModifiedDate`/`version`-Felder (live im Cache
   des Vorgängerprojekts bestätigt) - `wc_api.py`s `get_all()` muss um Filter-Unterstützung
   erweitert werden (WeClapps API unterstützt Query-Filter, siehe die vom Nutzer geteilte
   Endpunkt-Liste). **Noch nicht live gegen die echte WeClapp-API getestet, ob
   `lastModifiedDate`-Filterung serverseitig funktioniert** - das ist der wichtigste offene
   technische Punkt vor dem Bau, siehe unten.
5. **Upsert-Semantik pro Objekttyp**, aufbauend auf den deterministischen Namen aus
   `en_helper.py` - existiert das Ziel-Dokument schon (Name bekannt), `frappe.get_doc(...).save()`
   mit aktualisierten Feldern, sonst `frappe.new_doc(...).insert()`. Idempotenz-Prinzip aus dem
   Vorgängerprojekt (jede Migration prüft vor dem Schreiben, ein Fehler bei einem Datensatz bricht
   nie den ganzen Lauf ab) unbedingt beibehalten - gilt für beide Modi (Punkt 3).
6. **Status-/Fehler-Sichtbarkeit** für den Nutzer - mindestens ein Log/Report, welche Datensätze
   beim letzten Lauf (Vollimport oder Delta) fehlgeschlagen sind (kein stiller Fehlschlag, siehe
   `ecommerce_integrations` für ein bestehendes Muster).

## Offene technische Fragen (vor dem Bau zu klären)

- **Wichtigste:** Unterstützt WeClapps REST-API serverseitige Filterung nach `lastModifiedDate`
  (Query-Parameter, analog zu ERPNexts `filters`)? Noch nicht live getestet, nur die Datenfelder
  selbst sind bestätigt vorhanden. Falls nicht möglich: Delta-Erkennung müsste clientseitig über
  einen Vollabruf + Vergleich laufen, was den ganzen Ansatz deutlich weniger effizient macht -
  vor größerem Implementierungsaufwand klären.
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
