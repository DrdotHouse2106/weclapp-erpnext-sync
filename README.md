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

## Stand (2026-09-11)

**Registry: 6 von 14 Objekttypen registriert** (Kunde, Lieferant, Artikel, Angebot, Auftrag,
Rechnung). Details/Fachprobleme/Increments: `CLAUDE.md`.

### Getestet (Vollimport gegen die echte Testinstanz `francetec.frappe.cloud`, 0 Fehler bzw.
alle Restfehler geklärt; Bruttosummen wo zutreffend cent-genau gegen WeClapp `grossAmount`
verprobt)

| Objekttyp | Ergebnis |
|---|---|
| **Kunde** | 5830 Kunden, 0 Fehler (inkl. Adressen, Kontakte, Bankkonten, Personenkonto, belegart-spezifische E-Mails) |
| **Lieferant** | 396 Lieferanten, 0 Fehler |
| **Artikel** | 6210 Artikel, 0 Fehler (inkl. Barcode, Hersteller, Artikelgruppe, volle Preishistorie über alle Preiskanäle) |
| **Angebot** | Vollimport, 0 Fehler, Summen cent-genau |
| **Auftrag** | 3544 Aufträge, 0 Fehler (bis auf 1 korrekt übersprungene Retoure), Summen cent-genau, Lager-/Liefertermin-Logik geklärt |
| **Rechnung** | 5287 Rechnungen, 0 Fehler (39 korrekt übersprungene Nullrechnungen), inkl. Gutschriften (`is_return`), Summen cent-genau |
| **Zusatzfelder (WeClapp customAttributes)** | UI-gesteuertes Mapping gebaut (Reiter „Zusatzfelder" in den Settings) inkl. Table-MultiSelect-Generierung - **Feldauswahl/-anlage selbst noch nicht vom Nutzer final durchgespielt** |
| Delta-Sync-Mechanismus (Watermark, Scheduler, Wiederaufnahme, Abbrechen-Button) | Grundgerüst läuft, Watermarks für Kunde/Lieferant/Artikel gesetzt - **noch kein längerer Dauerbetrieb beobachtet** |

### Noch nicht gebaut / nicht getestet

- **Zahlungsabgleich** (`sales_payment`, WeClapp `salesOpenItem`/`accountingTransaction` → `Payment Entry`/Journal Entry für Abschreibungen) - fachlich der komplexeste verbleibende Teil, siehe `CLAUDE.md`
- Einkaufsseite komplett: `purchase_order`, `purchase_invoice`, `purchase_payment`
- `shipment`/Delivery Note, `stock_movement`, `crm_event`
- Belegketten-Rückwärtsverknüpfung (`post_run`, z. B. Kunde ⇄ letzte Rechnung)
- `apply_wc_blocks` (gesperrte/inaktive Kunden, Lieferanten, Artikel aus WeClapp übernehmen)
- Datenintensive `setup_*()`-Reste (Lager/Konten/Steuer-Templates - meist instanzspezifisch, oft schon vorhanden)
- Start-Workspace-Sichtbarkeit auf der Desk-Startseite (Datensatz korrekt, Anzeige beim Nutzer zuletzt noch nicht bestätigt)
