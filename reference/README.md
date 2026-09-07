# reference/

1:1 kopierter Code aus `weclapp-erpnext-migration` (Stand 2026-09-07) - **nicht direkt lauffähig
hier**, dient als Ausgangspunkt/Blaupause für den Umbau zur Frappe-App. Details und was sich
jeweils ändern muss: siehe CLAUDE.md im Repo-Root, Abschnitt "Herkunft: verwandtes Projekt".

- `base/` - direkt wiederverwendbare Abstraktionen.
- `weclapp/` - der WeClapp-REST-Client (`wc_api.py`, `wc_doctypes.py`), read-only, braucht noch
  Filter-Unterstützung (`lastModifiedDate`) für Delta-Sync.
- `migration_logic/en_helper.py` - deterministische Namens-/Mapping-Helfer.
- `migration_logic/full_field_mapping/` - komplettes `migration/`-Modul des Ursprungsprojekts,
  fachliche Feld-Mapping-Logik pro Objekttyp - technisch umzubauen von REST-Aufrufen (`ERPNextAPI`)
  auf Frappes native Document-API.
- `config_example.py` - Vorlage für alle bisher gebrauchten Konfigurationswerte (Konten-/
  Gruppennamen etc.) - Grundlage für die Felder im neuen "WeClapp Settings"-Doctype.
