# reference/

1:1 kopierter Code aus `weclapp-erpnext-migration` (Stand 2026-09-07) - **nicht direkt lauffähig
hier**, dient als vollständige Ausgangsbasis für den Umbau zur Frappe-App (dieses Projekt löst das
alte Skript komplett ab, nicht nur eine Ergänzung dazu - siehe CLAUDE.md im Repo-Root, Abschnitt
"Herkunft: Vorgänger-Projekt").

- `base/` - direkt wiederverwendbare Abstraktionen.
- `weclapp/` - der WeClapp-REST-Client (`wc_api.py`, `wc_doctypes.py`), read-only, braucht noch
  Filter-Unterstützung (`lastModifiedDate`) für den Delta-Sync-Teil.
- `erpnext/` - kompletter ERPNext-REST-Client des alten Repos. `en_api.py` selbst (REST-Wrapper)
  wird hier nicht gebraucht (läuft in ERPNext, nutzt Frappes native Document-API) - die übrigen
  Dateien (Doctype-Enum, Namens-Helfer, Steuer-Datenklassen) sind wertvolle Referenz.
- `migration_logic/full_field_mapping/` - komplettes `migration/`-Modul des Vorgängerprojekts,
  fachliche Feld-Mapping-Logik pro Objekttyp - technisch umzubauen von REST-Aufrufen (`ERPNextAPI`)
  auf Frappes native Document-API.
- `setup.py` - idempotente Stammdaten-/Struktur-Erzeugung, wird für die Vollimport-Fähigkeit
  gebraucht.
- `main.py` - Orchestrierung/Reihenfolge des alten Laufs, Referenz für die Reihenfolge im neuen
  Vollimport-Modus.
- `config_example.py` - Vorlage für alle bisher gebrauchten Konfigurationswerte (Konten-/
  Gruppennamen etc.) - Grundlage für die Felder im neuen "WeClapp Settings"-Doctype.
