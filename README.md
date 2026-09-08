# weclapp-erpnext-sync

Frappe/ERPNext-App, die den **kompletten WeClapp→ERPNext-Umzug** übernimmt: sowohl den
initialen Vollimport als auch den danach laufenden, automatischen Sync (WeClapp → ERPNext,
einseitig). Löst damit
[weclapp-erpnext-migration](https://github.com/DrdotHouse2106/weclapp-erpnext-migration) als
aktive Lösung ab - jenes Repo war ein einmaliges, extern laufendes Python-Skript und bleibt als
historische Referenz/Fundgrube für bereits gelöste Fachprobleme bestehen, wird aber nicht mehr
weiterentwickelt.

## Warum ein neues Repo statt Erweiterung des alten

Das alte Repo ist ein Skript, das extern gegen beide REST-APIs läuft. Dieses Projekt hier läuft
stattdessen **als Frappe-App direkt in ERPNext** und deckt beides ab:

1. **Vollimport** (Ersatz für das alte `main.py`) - für Erstinstallationen oder einen frisch
   zurückgesetzten ERPNext-Stand.
2. **Laufender Delta-Sync** (neu, gab es im alten Repo nicht) - danach automatisch im Hintergrund
   per Frappes Scheduler, nur geänderte Datensätze.

Andere Laufzeit-Architektur (App statt Skript, Frappes native Document-API statt REST-Aufrufe
gegen sich selbst) - deshalb ein separates Repo statt Umbau des bestehenden. Details: CLAUDE.md.

## Ziel

Übergangsphase, in der WeClapp und ERPNext parallel laufen, ohne doppelte manuelle Pflege:
WeClapp bleibt Führungssystem, ERPNext wird komplett automatisch synchron gehalten - vom ersten
Import bis zum laufenden Betrieb, ohne manuelles Skript-Ausführen. Installation soll so einfach
sein wie bei [ecommerce_integrations](https://github.com/DrdotHouse2106/ecommerce_integrations)
(App installieren, Zugangsdaten in einem Settings-Doctype eintragen, fertig).

## Installation (Entwicklung)

```bash
bench get-app weclapp_sync https://github.com/DrdotHouse2106/weclapp-erpnext-sync
bench --site <site> install-app weclapp_sync
```

Danach in ERPNext **WeClapp Settings** öffnen: Base-URL + API-Token eintragen, Verbindung testen,
Objekttypen auswählen, „WeClapp Sync aktiv" setzen. Für den Erstimport „Vollimport jetzt
starten"; für den laufenden Betrieb „Automatischen Delta-Sync aktivieren".

## Stand (2026-09-08)

**Increment 1 fertig – App-Gerüst + Unterbau, noch keine Feld-Mapper.**

| Bereich | Status |
|---|---|
| Frappe-App-Grundgerüst (`pyproject.toml`, `hooks.py`, `modules.txt`, `install.py`) | ✅ |
| Read-only WeClapp-Client (`weclapp_sync/weclapp/`) – GET-only hart erzwungen, `iter_pages()`/`iter_all()` als Generatoren (kein Cache-all), `lastModifiedDate`-Delta-Filter, streamender Dokument-Download | ✅ |
| WeClapp `lastModifiedDate`-Serverfilter | ✅ live verifiziert (siehe CLAUDE.md) |
| Doctypes: **WeClapp Settings** (Single), **WeClapp Sync Object Type** (Child), **WeClapp Sync Run** (+ Child), **WeClapp Sync Log** | ✅ |
| Sync-Engine (`weclapp_sync/sync/engine.py`) – gemeinsamer Unterbau Vollimport/Delta, seitenweises Verarbeiten + Commit pro Seite, Savepoint + Weiterlauf pro Datensatz, resumierbarer Seiten-Cursor, Fehler-Log pro Datensatz | ✅ Grundgerüst |
| Scheduler-Anbindung (`weclapp_sync/sync/scheduler.py`) – Cron-Tick enqueued nur den Job, Stale-Recovery | ✅ |
| Objekttyp-Registry + feste Reihenfolge (`weclapp_sync/sync/registry.py`) | ✅ Gerüst, **0 Typen registriert** |
| **Feld-Mapper pro Objekttyp** (Portierung aus `reference/migration_logic/`) | ❌ ausstehend |
| `setup_*()`-Äquivalente für den Vollimport (Konten, Lager, Custom Fields …, aus `reference/setup.py`) | ❌ ausstehend |
| Mapping-Standardwerte im Settings-Formular (aus `reference/config_example.py`) | ❌ ausstehend |
| Custom Fields (`wc_id`/`wc_last_synced` auf ERPNext-Doctypes) als Fixtures | ❌ ausstehend |

Nächster Schritt: ersten Mapper (Kunden) portieren und in der Registry aktivieren.
Details, Architektur-Plan und offene Fragen: `CLAUDE.md`.
