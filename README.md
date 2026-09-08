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

Danach erscheint im Desk der Bereich **WeClapp Sync** (Workspace). Dort **WeClapp Settings** öffnen: Base-URL + API-Token eintragen, Verbindung testen,
Objekttypen auswählen, „WeClapp Sync aktiv" setzen. Für den Erstimport „Vollimport jetzt
starten"; für den laufenden Betrieb „Automatischen Delta-Sync aktivieren".

## Stand (2026-09-08)

**Increment 1 + 2: App-Gerüst, Unterbau, Setup-Layer, erster (reduzierter) Kunden-Mapper.**

| Bereich | Status |
|---|---|
| Frappe-App-Grundgerüst (`pyproject.toml`, `hooks.py`, `modules.txt`, `install.py`) | ✅ |
| Read-only WeClapp-Client – GET-only hart erzwungen, `iter_pages()`/`iter_all()` als Generatoren (kein Cache-all), `lastModifiedDate`-Delta-Filter, streamender Dokument-Download | ✅ live gegen echte API getestet (Paginierung + Delta) |
| Doctypes: **WeClapp Settings** (Single, inkl. Mapping-Standardwerte), **WeClapp Sync Object Type** (Child), **WeClapp Sync Run** (+ Child), **WeClapp Sync Log** | ✅ |
| Sync-Engine – Unterbau Vollimport/Delta, seitenweise + Commit pro Seite, Savepoint + Weiterlauf pro Datensatz, resumierbarer Seiten-Cursor, Fehler-Log pro Datensatz | ✅ Grundgerüst |
| Scheduler-Anbindung – Cron-Tick enqueued nur den Job, Stale-Recovery | ✅ |
| Setup-Layer (`weclapp_sync/setup/`) – Custom Fields (`wc_id`/`wc_last_modified` + `wc_opt_in_*`/`wc_zahlungsart`/`wc_fax`), `autoname=Prompt`-Property-Setter; läuft bei `after_install`/`after_migrate` und vor dem Vollimport | ✅ |
| `erpnext_helpers.py` – Port von `en_helper.py` (Datum, Telefon, HTML-Strip, Territory, Country, UOM) | ✅ |
| Objekttyp-Registry + feste Reihenfolge | ✅ – **1 von 14 Typen registriert (Kunden)** |
| **Kunden-Mapper** – Kern-`Customer`-Dokument (Name, Gruppe, Typ, Währung, USt-IdNr., Notiz, Opt-Ins, `wc_id`) | ⚠️ reduziert – **ohne Adressen, Kontakte, Bankkonten, Personenkonto, Zusatzfelder** (jeweils eigener Folge-Schritt) |
| Übrige Mapper (Lieferant, Artikel, Rechnung, Auftrag, Zahlung, …) | ❌ ausstehend |
| Datenintensive `setup_*()`-Äquivalente (Konten, Lager, Geschäftsjahre, Zahlungsbedingungen, Personenkonten, …) | ❌ ausstehend |

Nächster Schritt: Kunden-Mapper vervollständigen (Adressen + Kontakte, wg. E-Mail/Telefon-Abdeckung
im Altbestand kritisch), dann Lieferanten- und Artikel-Mapper.
Details, Architektur-Plan und offene Fragen: `CLAUDE.md`.
