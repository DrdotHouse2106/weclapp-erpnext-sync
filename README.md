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

## Stand

Frisch angelegt, siehe CLAUDE.md für Architektur-Plan und was aus dem alten Repo als Referenz
übernommen wurde (`reference/`).
