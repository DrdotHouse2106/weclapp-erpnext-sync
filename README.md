# weclapp-erpnext-sync

Frappe/ERPNext-App, die WeClapp aktiv und laufend nach ERPNext synchronisiert (WeClapp → ERPNext,
einseitig) - als Ergänzung zum abgeschlossenen einmaligen Batch-Import in
[weclapp-erpnext-migration](https://github.com/DrdotHouse2106/weclapp-erpnext-migration).

## Warum ein neues Repo statt Erweiterung des Migrations-Repos

Das Migrations-Repo ist ein eigenständiges Python-Skript (`main.py`), das extern gegen beide
REST-APIs läuft, einmal komplett durchläuft und danach idempotent erneut laufen kann. Dieses
Projekt hier soll stattdessen **als Frappe-App in ERPNext selbst installiert werden** und
**automatisch im Hintergrund** (Frappes Scheduler) nur die seit dem letzten Lauf geänderten
WeClapp-Datensätze nachziehen. Das ist eine andere Laufzeit-Architektur (App statt Skript,
Frappes native Document-API statt REST-Aufrufe gegen sich selbst), deshalb ein separates Repo -
siehe CLAUDE.md für die Details.

## Ziel

Übergangsphase, in der WeClapp und ERPNext parallel laufen, ohne doppelte manuelle Pflege:
WeClapp bleibt Führungssystem, ERPNext wird laufend automatisch synchron gehalten. Installation
soll so einfach wie bei [ecommerce_integrations](https://github.com/DrdotHouse2106/ecommerce_integrations)
sein (App installieren, Zugangsdaten in einem Settings-Doctype eintragen, fertig).

## Stand

Frisch angelegt, siehe CLAUDE.md für Architektur-Plan und was aus dem Migrations-Repo als
Referenz übernommen wurde (`reference/`).
