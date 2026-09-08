# Zustand der Testinstanz `francetec.frappe.cloud` (Stand 2026-09-08, read-only inspiziert)

Die Instanz, auf der der **alte** Importer (`weclapp-erpnext-migration`) gelaufen ist. Diese
Notizen sind Grundlage für die Idempotenz-/Abgleich-Strategie der neuen App.

## Identität / Naming

| Doctype | `autoname` | Dokumentname | Beispiel |
|---|---|---|---|
| Customer | Prompt | = `customerNumber` | `10008` |
| Supplier | Prompt | = `supplierNumber` | |
| Item | (Item Code) | = `articleNumber` | `100001` |
| Sales Invoice | Prompt | `RE-<invoiceNumber>` | `RE-2023-GU900000` |
| Sales Order | Prompt | `SO-<orderNumber>` | |
| Quotation | Prompt | `AN-<quotationNumber>` | |
| Payment Entry / Delivery Note / Stock Entry / Communication | Prompt | WeClapp-abgeleitet | |

**Es gibt KEIN `wc_id`-Custom-Field.** Die WeClapp-Nummer *ist* die ERPNext-Dokument-ID.
→ Für Customer/Supplier/Item/Belege ist der Bestandsabgleich der neuen App über den
**Dokumentnamen** möglich (die App vergibt denselben Namen).

## Adressen / Kontakte – NICHT sauber verschlüsselbar

- **Address**: `address_title` = `customerNumber`, `autoname = format:{address_title}-{address_type}`.
  Name z.B. `10008-Abrechnung` / `10008-Versand` (deutsche Übersetzung von Billing/Shipping,
  Instanz-Sprache = `de`). Feldwert `address_type` bleibt englisch (`Billing`/`Shipping`).
  Mehrere gleichartige Adressen → `-1`, `-2`-Suffix. Kein `wc_id`.
- **Contact**: `autoname` = `{first_name} {last_name}` + `-1/-2`-Suffix bei Kollision. Kein `wc_id`.
- **Bestehende Duplikate**: Kunde 10008 hat `sabine schweitzer-welter` UND
  `sabine schweitzer-welter-1`, **beide `is_primary_contact = 1`**. Der alte Lauf hat hier
  (self-Kontakt-Fallback + evtl. Re-Runs) schon doppelt angelegt.

→ Adressen/Kontakte lassen sich **nicht** verlässlich per deterministischem Namen wiederfinden.
Optionen: (a) einmaliger Reconciliation-Patch, der Bestandsadressen/-kontakte per
`address_title`+`address_line1` bzw. Link+Name matcht und ein neues `wc_id` backfillt; danach
Abgleich per `wc_id`. (b) Testinstanz zurücksetzen, App macht den sauberen Vollimport.

## Custom Fields, die der alte Importer angelegt hat (Auszug)

- **Customer**: `wc_opt_in_email/letter/phone/sms`, `wc_opt_in_sektion`, `wc_zahlungsart`,
  `invoice_email` (**Data-Feld**, nicht als Kontakt modelliert – anders als
  `reference/.../customer_migration.py` es beschreibt!), `opt_out_email`, `opt_out_telefon`,
  Fahrzeug-/eBay-/Register-Freifelder (aus WeClapp customAttributes).
- **Supplier**: `wc_opt_in_*`, `wc_zahlungsart`, Register-Felder.
- **Contact**: `wc_fax`, `opt_out_email`, `opt_out_telefon`, Fahrzeug-/eBay-Freifelder.
- **Item**: 83 Custom Fields (Shopware/Aic/Freifelder-lastig).
- **Sales Invoice**: `wc_auftrag` (Link), `wc_interne_notiz`, `belegkette_sektion`, …
- **Sales Order**: `wc_angebot` / `wc_bestellung` / `wc_rechnung` (Links), `wc_interne_notiz`, …
- **Address**: KEINE wc-Felder (nur Shopware/`tax_category`).

→ Die neue App darf diese Felder **nicht** duplizieren. `create_custom_fields` ist idempotent
(aktualisiert vorhandene), aber unsere Feldnamen/`insert_after` sollten nicht mit bestehenden
kollidieren. `wc_zahlungsart` / `wc_opt_in_*` / `wc_fax` sind **schon da** – unsere
`setup/custom_fields.py`-Definitionen sind dann No-Ops/Angleichungen.

## Stammdaten

- Company: `FranceTec` / Abbr `FT` / EUR.
- Customer Group: `Individual`, `Commercial` (+ `Non Profit`, `Government`).  → Settings-Defaults.
- Territory: `Germany`, `Rest Of The World`.
- Supplier Group: `All Supplier Groups`, `Services`, `Local`, …
- Payment Terms Templates: `net 7/14/30`, `2/10, net 30`, …, `Migration - unbegrenzt`.
- **Personenkonten existieren**: `Account` mit Nummer = Kundennummer, z.B.
  `13516 - sabine schweitzer-welter - FT`, parent
  `1400 - Forderungen aus Lieferungen und Leistungen mit Kontokorrent - FT`.
  Kunde.`accounts` = `[{company: FranceTec, account: "<nr> - <name> - FT"}]`.
- Item Groups: viele fachspezifische (Bremse/Elektrik/…), Fallback `All Item Groups`.
- Warehouses: `... (<wc-id>) - FT`-Muster (z.B. `BR001 (3777) - FT`) – entspricht
  `en_helper.get_wc_warehouse_name`.
- autoname=Prompt-Property-Setter für alle 12 relevanten Doctypes **schon gesetzt**.

## Zählungen (Bestand)

(werden beim nächsten Lauf ergänzt – Instanz war beim ersten Versuch inaktiv)
