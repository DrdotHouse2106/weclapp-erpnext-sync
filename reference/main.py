import config
import erpnext as en
import weclapp as wc
import migration as mig
from setup import run_setup, get_wc_warehouse_full_names

def migrate_wc_en_customers():
    """Migrate all customers from WeClapp to ERPNext"""
    with mig.MigrationWrapper(wc.WeClappDocType.CUSTOMER, en.ERPNextDocType.CUSTOMER) as migration:
        migration.migrate_all()

def migrate_wc_en_suppliers():
    """Migrate all suppliers from WeClapp to ERPNext"""
    with mig.MigrationWrapper(wc.WeClappDocType.SUPPLIER, en.ERPNextDocType.SUPPLIER) as migration:
        migration.migrate_all()

def migrate_wc_en_articles():
    """Migrate all articles from WeClapp to ERPNext"""
    with mig.MigrationWrapper(wc.WeClappDocType.ARTICLE, en.ERPNextDocType.ITEM) as migration:
        migration.migrate_all()

def migrate_wc_en_invoices():
    """Migrate all sales invoices from WeClapp to ERPNext"""
    with mig.MigrationWrapper(wc.WeClappDocType.SALES_INVOICE, en.ERPNextDocType.SALES_INVOICE) as migration:
        migration.migrate_all()

def migrate_wc_en_purchase_invoices():
    """Migrate all purchase invoices from WeClapp to ERPNext"""
    with mig.MigrationWrapper(wc.WeClappDocType.PURCHASE_INVOICE, en.ERPNextDocType.PURCHASE_INVOICE) as migration:
        migration.migrate_all()

def migrate_wc_en_sales_payments():
    """Migrate all sales open items (offene Posten) from WeClapp to ERPNext Payment Entries -
    the real payment data (date/amount/bank vs. cash), replacing the old lump-sum "fully paid on
    the invoice date" shortcut. Must run after migrate_wc_en_invoices() - references the
    already-migrated Sales Invoice.
    """
    with mig.MigrationWrapper(wc.WeClappDocType.SALES_OPEN_ITEM, en.ERPNextDocType.PAYMENT_ENTRY) as migration:
        migration.migrate_all()

def migrate_wc_en_purchase_payments():
    """Migrate all purchase open items (offene Posten) from WeClapp to ERPNext Payment Entries.
    Must run after migrate_wc_en_purchase_invoices() - references the already-migrated Purchase
    Invoice.
    """
    with mig.MigrationWrapper(wc.WeClappDocType.PURCHASE_OPEN_ITEM, en.ERPNextDocType.PAYMENT_ENTRY) as migration:
        migration.migrate_all()

def migrate_wc_en_crm_events():
    """Migrate all CRM events (Ereignisse - phone calls) from WeClapp to ERPNext Communications.
    Must run after migrate_wc_en_customers()/migrate_wc_en_suppliers() - references the
    already-migrated Customer/Supplier. Events that don't resolve to either (mostly leads) are
    skipped, see crm_event_migration.py.
    """
    with mig.MigrationWrapper(wc.WeClappDocType.CRM_EVENT, en.ERPNextDocType.COMMUNICATION) as migration:
        migration.migrate_all()

def migrate_wc_en_sales_orders():
    """Migrate all sales orders (Aufträge) from WeClapp to ERPNext"""
    with mig.MigrationWrapper(wc.WeClappDocType.SALES_ORDER, en.ERPNextDocType.SALES_ORDER) as migration:
        migration.migrate_all()

def migrate_wc_en_purchase_orders():
    """Migrate all purchase orders (Bestellungen) from WeClapp to ERPNext"""
    with mig.MigrationWrapper(wc.WeClappDocType.PURCHASE_ORDER, en.ERPNextDocType.PURCHASE_ORDER) as migration:
        migration.migrate_all()

def migrate_wc_en_quotations():
    """Migrate all quotations (Angebote) from WeClapp to ERPNext"""
    with mig.MigrationWrapper(wc.WeClappDocType.QUOTATION, en.ERPNextDocType.QUOTATION) as migration:
        migration.migrate_all()

def migrate_wc_en_stock_movements():
    """Migrate all warehouse stock movements (Lagerbewegungen) from WeClapp to ERPNext, as the
    sole source of the ERPNext stock ledger for the historical import (see
    stock_entry_migration.py). Sorted chronologically by posting date before import - ERPNext's
    stock ledger triggers expensive future-entry reposting on out-of-order postings.
    """
    with mig.MigrationWrapper(wc.WeClappDocType.WAREHOUSE_STOCK_MOVEMENT, en.ERPNextDocType.STOCK_ENTRY) as migration:
        migration.migrate_all(sort_key=lambda v: v.get("postingDate") or 0)

def migrate_wc_en_shipments():
    """Migrate all shipments (Lieferungen) from WeClapp to ERPNext as Delivery Notes.
    Created as Draft (see delivery_note_migration.py) - migrate_wc_en_stock_movements() already
    covers the same goods-out events, this is a pure delivery/tracking record; a submitted
    Delivery Note would double-book the stock ledger.
    """
    with mig.MigrationWrapper(wc.WeClappDocType.SHIPMENT, en.ERPNextDocType.DELIVERY_NOTE) as migration:
        migration.migrate_all()

def apply_document_links():
    """Sets the REVERSE document-chain links (Belegkette) after all documents are imported:
    Angebot -> Auftrag, Auftrag -> Rechnung/Bestellung, Bestellung -> Eingangsrechnung.
    The forward links (Rechnung -> Auftrag etc.) are set directly at import time by the
    migrations' _transform; the reverse direction can only be filled once the target
    documents exist. Idempotent: already-set links are skipped.
    """
    import json
    en_api = en.ERPNextAPI(config.EN_API_KEY, config.EN_API_SECRET, config.EN_API_BASE)
    en_api.open()

    def set_links(doctype, links):
        """links: dict doc_name -> {field: value}"""
        updated, skipped, failed = 0, 0, 0
        for doc_name, fields in links.items():
            try:
                doc = en_api.get(doctype, doc_name)
                if not doc:
                    skipped += 1
                    continue
                missing = {f: v for f, v in fields.items() if not doc.get(f)}
                if not missing:
                    skipped += 1
                    continue
                en_api.update(doctype, doc_name, missing)
                updated += 1
            except Exception as e:
                failed += 1
                print(f"FAILED link {doctype.value} {doc_name}: {type(e).__name__}: {str(e)[:100]}")
        print(f"--- Links {doctype.value}: {updated} updated, {skipped} skipped, {failed} failed ---")

    sales_orders = json.load(open(f"{config.WC_CACHE_BASE}salesOrder.json"))["data"]
    sales_invoices = json.load(open(f"{config.WC_CACHE_BASE}salesInvoice.json"))["data"]
    purchase_orders = json.load(open(f"{config.WC_CACHE_BASE}purchaseOrder.json"))["data"]
    purchase_invoices = json.load(open(f"{config.WC_CACHE_BASE}purchaseInvoice.json"))["data"]
    po_number_by_id = {v["id"]: v.get("purchaseOrderNumber") for v in purchase_orders.values()}

    # Angebot -> Auftrag
    quotation_links = {}
    for v in sales_orders.values():
        if v.get("quotationNumber") and v.get("orderNumber"):
            quotation_links.setdefault(f"AN-{v['quotationNumber']}", {})["wc_auftrag"] = f"SO-{v['orderNumber']}"
    set_links(en.ERPNextDocType.QUOTATION, quotation_links)

    # Auftrag -> Rechnung (bei Teilrechnungen wird die erste verknüpft) und -> Bestellung.
    # Null-Rechnungen werden übersprungen - die wurden (analog zur Import-Validierung)
    # nie nach ERPNext übernommen und existieren dort als Link-Ziel nicht.
    so_links = {}
    for v in sales_invoices.values():
        if v.get("salesOrderNumber") and v.get("invoiceNumber") and float(v.get("netAmount", 0) or 0) > 0:
            so_links.setdefault(f"SO-{v['salesOrderNumber']}", {}).setdefault("wc_rechnung", f"RE-{v['invoiceNumber']}")
    for v in purchase_orders.values():
        if v.get("salesOrderNumber") and v.get("purchaseOrderNumber"):
            so_links.setdefault(f"SO-{v['salesOrderNumber']}", {}).setdefault("wc_bestellung", f"PO-{v['purchaseOrderNumber']}")
    set_links(en.ERPNextDocType.SALES_ORDER, so_links)

    # Bestellung -> Eingangsrechnung (nur echte, importierte Rechnungen - keine OCR-Entwürfe
    # ohne Lieferant und keine Null-Rechnungen, analog zur Import-Validierung)
    po_links = {}
    for v in purchase_invoices.values():
        if not v.get("supplierNumber") or float(v.get("netAmount", 0) or 0) <= 0:
            continue
        for ref in (v.get("purchaseOrders") or []):
            number = po_number_by_id.get(ref.get("id"))
            if number and v.get("internalInvoiceNumber"):
                po_links.setdefault(f"PO-{number}", {}).setdefault("wc_eingangsrechnung", f"EK-{v['internalInvoiceNumber']}")
    set_links(en.ERPNextDocType.PURCHASE_ORDER, po_links)

    en_api.close()


def apply_wc_blocks():
    """Applies WeClapp's block flags AFTER all documents are imported.
    During the import everything is created enabled, because ERPNext refuses documents that
    reference disabled parties/items - but historical documents for now-blocked customers or
    discontinued articles still have to be imported.
    """
    en_api = en.ERPNextAPI(config.EN_API_KEY, config.EN_API_SECRET, config.EN_API_BASE)
    wc_api = wc.WcCacheApi(config.WC_CACHE_BASE)
    en_api.open()
    wc_api.open()

    blocked, failed = 0, 0
    for customer in wc_api.get_all(wc.WeClappDocType.CUSTOMER):
        if customer.get("blocked") or customer.get("insolvent"):
            try:
                en_api.update(en.ERPNextDocType.CUSTOMER, customer.get("customerNumber"), {
                    "disabled": 1,
                    "is_frozen": 1 if customer.get("insolvent") else 0
                })
                blocked += 1
            except Exception as e:
                failed += 1
                print(f"FAILED blocking Customer {customer.get('customerNumber')}: {type(e).__name__}: {e}")

    for supplier in wc_api.get_all(wc.WeClappDocType.SUPPLIER):
        if supplier.get("orderBlock"):
            try:
                en_api.update(en.ERPNextDocType.SUPPLIER, supplier.get("supplierNumber"), {"disabled": 1})
                blocked += 1
            except Exception as e:
                failed += 1
                print(f"FAILED blocking Supplier {supplier.get('supplierNumber')}: {type(e).__name__}: {e}")

    for article in wc_api.get_all(wc.WeClappDocType.ARTICLE):
        if not article.get("active", True):
            try:
                en_api.update(en.ERPNextDocType.ITEM, article.get("articleNumber"), {"disabled": 1})
                blocked += 1
            except Exception as e:
                failed += 1
                print(f"FAILED disabling Item {article.get('articleNumber')}: {type(e).__name__}: {e}")

    en_api.close()
    wc_api.close()
    print(f"--- Blocks/Deactivations: {blocked} applied, {failed} failed ---")


def disable_legacy_warehouses():
    """Deactivates the entire "Lager_old" Warehouse tree (see setup.setup_warehouses()) after
    the historical Stock Entry/Delivery Note replay has posted against it. Disabling only hides
    a Warehouse from pickers for new transactions - the stock ledger history stays intact. Must
    run LAST, after migrate_wc_en_stock_movements()/migrate_wc_en_shipments() - a disabled
    Warehouse can no longer be used as a Stock Entry/Delivery Note target. Going forward, a new
    clean Warehouse for day-to-day operations is set up manually (outside this migration).
    """
    en_api = en.ERPNextAPI(config.EN_API_KEY, config.EN_API_SECRET, config.EN_API_BASE)
    en_api.open()

    disabled, failed = 0, 0
    for name in get_wc_warehouse_full_names():
        try:
            en_api.update(en.ERPNextDocType.WAREHOUSE, name, {"disabled": 1})
            disabled += 1
        except Exception as e:
            failed += 1
            print(f"FAILED disabling Warehouse {name}: {type(e).__name__}: {e}")

    en_api.close()
    print(f"--- Legacy Warehouses: {disabled} disabled, {failed} failed ---")

if __name__ == "__main__":
    # Setup: Freifelder (Custom Fields), Artikelgruppen (Item Groups) und Hersteller (Manufacturer)
    # muessen vor allem anderen existieren, sonst verwirft Frappe die Werte beim Import lautlos
    # bzw. schlaegt die Artikelanlage fehl. Idempotent - bereits vorhandene Eintraege werden uebersprungen.
    run_setup()

    # TEMPORÄR (2026-08-18): Customer/Supplier/CRM-Events/Item/Stock-Entry/Quotation/Sales-Order
    # sind live gegengeprüft vollständig (0 offene Fehler, siehe CLAUDE.md) - das erneute
    # idempotente Durchprüfen jedes einzelnen Datensatzes kostet bei instabiler Verbindung
    # trotzdem 1-2 Stunden pro main.py-Neustart, bevor der Lauf überhaupt bei den noch offenen
    # Sales Invoices (payment_terms_template-Fix, siehe invoice_migration.py) ankommt.
    # Auskommentiert, um direkt bei den offenen Abschnitten weiterzumachen - vor dem nächsten
    # "sauberen" Voll-Lauf wieder einkommentieren.
    # migrate_wc_en_customers()
    # migrate_wc_en_suppliers()
    # migrate_wc_en_crm_events()
    # migrate_wc_en_articles()
    # migrate_wc_en_stock_movements()
    # migrate_wc_en_quotations()
    # migrate_wc_en_sales_orders()
    migrate_wc_en_invoices()

    # Zahlungseingänge (echte WeClapp-Zahlungsdaten, siehe payment_entry_migration.py) - nach
    # den Rechnungen, damit die Payment-Entry-Referenz auf sie verlinken kann.
    migrate_wc_en_sales_payments()

    # Lieferungen (reine Tracking-Dokumente, keine Bestandswirkung) - nach den Aufträgen, damit
    # die Belegkette (wc_auftrag) verlinkt werden kann
    migrate_wc_en_shipments()

    # Einkaufsseitige Transaktionsdaten (Bestellung -> Eingangsrechnung), Steuerkonten-Mappings
    # live gegen den echten FranceTec-Kontenplan verifiziert
    migrate_wc_en_purchase_orders()
    migrate_wc_en_purchase_invoices()

    # Zahlungsausgänge - nach den Eingangsrechnungen, siehe oben.
    migrate_wc_en_purchase_payments()

    # Schlussphase 1: Rückwärts-Verknüpfungen der Belegkette (Angebot -> Auftrag -> Rechnung usw.)
    # setzen, jetzt wo alle Zielbelege existieren.
    apply_document_links()

    # Schlussphase 2: WeClapp-Sperren (gesperrte/insolvente Kunden, Bestellsperren, inaktive Artikel)
    # erst jetzt anwenden, nachdem alle historischen Belege importiert sind.
    apply_wc_blocks()

    # disable_legacy_warehouses() läuft bewusst NICHT mehr automatisch mit: main.py ist beliebig
    # oft re-run-bar (idempotent), aber jeder Lauf ruft am Ende trotzdem unconditional
    # disable_legacy_warehouses() auf, unabhängig davon, ob migrate_wc_en_stock_movements()/
    # migrate_wc_en_shipments() in DIESEM Lauf tatsächlich vollständig durchgelaufen sind. Live
    # beobachtet: ein erster Lauf mit vielen Stock-Entry-Fehlschlägen (z.B. fehlendes
    # Geschäftsjahr) deaktivierte die Lager trotzdem am Ende - der nächste Lauf konnte die
    # eigentlich noch offenen Stock Entries dann nicht mehr nachbuchen ("Deaktiviertes Lager kann
    # für diese Transaktion nicht verwendet werden"). disable_legacy_warehouses() ist ein
    # Cutover-Schritt für den Tag, an dem die Migration wirklich fertig ist - manuell aufrufen
    # (python3 -c "from main import disable_legacy_warehouses; disable_legacy_warehouses()"),
    # erst nachdem die Stock-Entry-/Delivery-Note-Zusammenfassungen 0 Fehler zeigen.

    # Der Zahlungsabgleich (Rechnung <-> Zahlung, siehe migrate_wc_en_sales_payments()/
    # migrate_wc_en_purchase_payments()) ist angebunden - das volle WeClapp-Buchungsjournal
    # (accountingTransaction) dagegen bewusst nicht: ERPNext erzeugt beim Submit von Sales/
    # Purchase Invoice bereits eigene GL-Einträge, ein Import würde doppelt buchen.
