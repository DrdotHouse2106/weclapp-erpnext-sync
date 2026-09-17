"""WeClapp-Dokumente (PDFs an Belegen) + Artikelbilder -> Frappe-File-Anhänge.

Streamend wie der Rest des Syncs: nur der Dateiinhalt des GERADE bearbeiteten Datensatzes liegt
kurz im Speicher (WeClapp-Client streamt chunkweise, `b"".join(...)` sammelt genau EINE Datei -
keine Vorab-Zwischenspeicherung ganzer Objekttypen wie im Vorgänger-Importer, der dafür einen
separaten Cache-Ordner-Lauf brauchte, siehe reference/config_example.py WC_CACHE_*_BASE).

Idempotent über `File.wc_id` (WeClapp `document.id` bzw. `articleImage.id`). **Bugfix
2026-09-16:** vorher über `File.file_name` abgeglichen - Frappe hängt beim Speichern aber
Hash-Suffixe an den Dateinamen an, der Abgleich griff dadurch praktisch nie (live: 21034 von
21507 File-Datensätzen an Items trugen einen Suffix). Jeder Lauf hat seither dieselben Dateien
erneut heruntergeladen und angehängt (live: 5718 Items mit derselben Datei mehrfach, teils >15x).

Ein Fehler bei einer einzelnen Datei bricht nie den ganzen Datensatz-Upsert ab (gleiche
Fehlertoleranz wie im Vorgänger, siehe dessen `upload_weclapp_documents`/`_upload_article_images`),
wird aber jetzt geloggt statt lautlos verschluckt (`except Exception: continue` ohne jedes Log
verletzte das "kein stiller Fehlschlag"-Prinzip).

Über Settings-Schalter `sync_attachments` (Default aus) abschaltbar - pro Datensatz ein bis zwei
zusätzliche WeClapp-Aufrufe, macht Testläufe mit vielen Datensätzen spürbar langsamer. Der
Schalter wird hier zentral geprüft, nicht an jeder Aufrufstelle im jeweiligen Mapper.
"""

from __future__ import annotations

import frappe
from frappe.utils.file_manager import save_file

from weclapp_sync.sync.settings import get_settings


def _enabled() -> bool:
	return bool(get_settings().sync_attachments)


def _existing_wc_ids(doctype: str, name: str) -> set[str]:
	return {
		wc_id
		for wc_id in frappe.get_all(
			"File",
			filters={"attached_to_doctype": doctype, "attached_to_name": name},
			pluck="wc_id",
		)
		if wc_id
	}


def attach_weclapp_documents(client, weclapp_doctype, weclapp_id, target_doctype: str, target_name: str) -> None:
	"""Alle an einen WeClapp-Beleg gehängten Dokumente (i.d.R. das PDF, generische `document`-
	Entität) als Frappe-File am Zieldokument anhängen. No-op ohne Client/ID/Dokumente oder wenn
	`sync_attachments` in den Settings deaktiviert ist."""
	if client is None or not weclapp_id or not target_name or not _enabled():
		return
	try:
		docs = client.get_documents(weclapp_doctype, str(weclapp_id))
	except Exception:
		frappe.log_error(
			title=f"WeClapp Anhänge: Liste für {target_doctype} {target_name} fehlgeschlagen",
			message=frappe.get_traceback(),
		)
		return
	if not docs:
		return

	existing = _existing_wc_ids(target_doctype, target_name)
	for d in docs:
		filename = d.get("name")
		doc_id = d.get("id")
		if not (filename and doc_id) or doc_id in existing:
			continue
		try:
			content = b"".join(client.iter_document_content(doc_id))
			file_doc = save_file(filename, content, target_doctype, target_name, decode=False, is_private=1)
			frappe.db.set_value("File", file_doc.name, "wc_id", doc_id, update_modified=False)
		except Exception:
			frappe.log_error(
				title=f"WeClapp Anhang: {filename} an {target_doctype} {target_name} fehlgeschlagen",
				message=frappe.get_traceback(),
			)


def attach_article_images(client, record: dict, item_code: str) -> None:
	"""WeClapp `articleImages` (im Artikel-Payload eingebettete Metadaten, kein Extra-Aufruf
	nötig) als Frappe-File am Item anhängen. Das Hauptbild (`mainImage`) wird zusätzlich als
	`Item.image` gesetzt - Download über die artikel-eigene `downloadArticleImage`-Aktion
	(siehe client.iter_article_image_content), nicht die generische `document`-Entität. No-op,
	wenn `sync_attachments` in den Settings deaktiviert ist."""
	images = record.get("articleImages") or []
	if client is None or not images or not item_code or not _enabled():
		return

	article_id = record.get("id")
	if not article_id:
		return

	existing = _existing_wc_ids("Item", item_code)
	for img in images:
		filename = img.get("fileName")
		image_id = img.get("id")
		if not (filename and image_id) or image_id in existing:
			continue
		try:
			content = b"".join(client.iter_article_image_content(article_id, image_id))
			file_doc = save_file(filename, content, "Item", item_code, decode=False, is_private=0)
			frappe.db.set_value("File", file_doc.name, "wc_id", image_id, update_modified=False)
			if img.get("mainImage"):
				frappe.db.set_value("Item", item_code, "image", file_doc.file_url)
		except Exception:
			frappe.log_error(
				title=f"WeClapp Artikelbild: {filename} an Item {item_code} fehlgeschlagen",
				message=frappe.get_traceback(),
			)


# Doctypes, an die _attachments.py tatsächlich Dateien hängt (Item über attach_article_images,
# die Belegs-Doctypes über attach_weclapp_documents) - die Bereinigung NUR hierauf eingrenzen.
# **Bugfix 2026-09-17:** ohne diese Eingrenzung durchsucht die Funktion ALLE File-Datensätze im
# gesamten System (auch fremde Apps, Kommentar-Anhänge, ...) - live beim ersten echten Aufruf
# in einen 504 Gateway Timeout gelaufen, bevor auch nur eine einzige Datei geprüft wurde.
_ATTACHMENT_DOCTYPES = [
	"Item",
	"Quotation",
	"Sales Order",
	"Sales Invoice",
	"Delivery Note",
	"Purchase Order",
	"Purchase Invoice",
]

_COMMIT_EVERY = 200


def cleanup_duplicate_attachments(doctype: str | None = None) -> dict:
	"""Einmalige Bereinigung der Dubletten aus der Zeit vor dem `wc_id`-Dedup-Fix (siehe
	Moduldocstring): je (attached_to_doctype, attached_to_name, file_url) werden alle File-
	Datensätze bis auf den ältesten gelöscht. `doctype` optional zum weiteren Eingrenzen
	(z.B. nur "Item") - Default: alle `_ATTACHMENT_DOCTYPES`. Wird über einen Settings-Button
	als Hintergrund-Job ausgelöst (siehe `weclapp_settings.py`), NICHT automatisch beim Sync -
	das ist ein einmaliger, vom Nutzer bestätigter Aufräum-Schritt gegen echte Produktivdaten.

	**Bugfix 2026-09-17:** committet jetzt alle `_COMMIT_EVERY` Löschungen statt erst ganz am
	Ende - bei mehreren tausend Dubletten (live: >17.000 an Items allein) wäre sonst eine
	einzige, sehr lange offene Transaktion nötig gewesen."""
	filters: dict = {"attached_to_doctype": ("in", [doctype] if doctype else _ATTACHMENT_DOCTYPES)}
	rows = frappe.get_all(
		"File",
		filters=filters,
		fields=["name", "attached_to_doctype", "attached_to_name", "file_url", "creation"],
		order_by="creation asc",
	)
	seen: dict[tuple, str] = {}
	to_delete: list[str] = []
	for r in rows:
		if not (r.attached_to_doctype and r.attached_to_name and r.file_url):
			continue
		key = (r.attached_to_doctype, r.attached_to_name, r.file_url)
		if key in seen:
			to_delete.append(r.name)
		else:
			seen[key] = r.name

	deleted, failed = 0, 0
	for name in to_delete:
		try:
			frappe.delete_doc("File", name, ignore_permissions=True, force=True)
			deleted += 1
		except Exception:
			failed += 1
			frappe.log_error(title=f"WeClapp Anhang-Bereinigung: {name} fehlgeschlagen", message=frappe.get_traceback())
		if (deleted + failed) % _COMMIT_EVERY == 0:
			frappe.db.commit()
	frappe.db.commit()
	return {"checked": len(rows), "duplicates_found": len(to_delete), "deleted": deleted, "failed": failed}


def cleanup_duplicate_attachments_job() -> None:
	"""Hintergrund-Job-Wrapper für den Settings-Button (siehe weclapp_settings.py) - bei
	tausenden Dubletten (live: >17.000 an Items) dauert die eigentliche Bereinigung zu lange
	für einen synchronen Web-Request (504 Gateway Timeout beim ersten Versuch 2026-09-17, siehe
	`cleanup_duplicate_attachments()`-Docstring). Ergebnis landet im Error Log, da ein
	Hintergrund-Job keine Desk-Meldung mehr direkt anzeigen kann."""
	res = cleanup_duplicate_attachments()
	frappe.log_error(
		title="WeClapp Anhang-Bereinigung abgeschlossen",
		message=(
			f"{res['checked']} Dateien geprüft, {res['duplicates_found']} Dubletten gefunden, "
			f"{res['deleted']} gelöscht, {res['failed']} fehlgeschlagen."
		),
	)
