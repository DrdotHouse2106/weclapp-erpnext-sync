"""WeClapp-Dokumente (PDFs an Belegen) + Artikelbilder -> Frappe-File-Anhänge.

Streamend wie der Rest des Syncs: nur der Dateiinhalt des GERADE bearbeiteten Datensatzes liegt
kurz im Speicher (WeClapp-Client streamt chunkweise, `b"".join(...)` sammelt genau EINE Datei -
keine Vorab-Zwischenspeicherung ganzer Objekttypen wie im Vorgänger-Importer, der dafür einen
separaten Cache-Ordner-Lauf brauchte, siehe reference/config_example.py WC_CACHE_*_BASE).

Idempotent über den WeClapp-Dateinamen: ist am Zieldokument schon eine `File` mit demselben
Namen angehängt, wird nichts erneut heruntergeladen. Ein Fehler bei einer einzelnen Datei bricht
nie den ganzen Datensatz-Upsert ab (gleiche Fehlertoleranz wie im Vorgänger, siehe dessen
`upload_weclapp_documents`/`_upload_article_images`).
"""

from __future__ import annotations

import frappe
from frappe.utils.file_manager import save_file


def _existing_file_names(doctype: str, name: str) -> set[str]:
	return set(
		frappe.get_all(
			"File",
			filters={"attached_to_doctype": doctype, "attached_to_name": name},
			pluck="file_name",
		)
	)


def attach_weclapp_documents(client, weclapp_doctype, weclapp_id, target_doctype: str, target_name: str) -> None:
	"""Alle an einen WeClapp-Beleg gehängten Dokumente (i.d.R. das PDF, generische `document`-
	Entität) als Frappe-File am Zieldokument anhängen. No-op ohne Client/ID/Dokumente."""
	if client is None or not weclapp_id or not target_name:
		return
	try:
		docs = client.get_documents(weclapp_doctype, str(weclapp_id))
	except Exception:
		return
	if not docs:
		return

	existing = _existing_file_names(target_doctype, target_name)
	for d in docs:
		filename = d.get("name")
		doc_id = d.get("id")
		if not (filename and doc_id) or filename in existing:
			continue
		try:
			content = b"".join(client.iter_document_content(doc_id))
			save_file(filename, content, target_doctype, target_name, decode=False, is_private=1)
		except Exception:
			continue


def attach_article_images(client, record: dict, item_code: str) -> None:
	"""WeClapp `articleImages` (im Artikel-Payload eingebettete Metadaten, kein Extra-Aufruf
	nötig) als Frappe-File am Item anhängen. Das Hauptbild (`mainImage`) wird zusätzlich als
	`Item.image` gesetzt - Download über die artikel-eigene `downloadArticleImage`-Aktion
	(siehe client.iter_article_image_content), nicht die generische `document`-Entität."""
	images = record.get("articleImages") or []
	if client is None or not images or not item_code:
		return

	article_id = record.get("id")
	if not article_id:
		return

	existing = _existing_file_names("Item", item_code)
	for img in images:
		filename = img.get("fileName")
		image_id = img.get("id")
		if not (filename and image_id) or filename in existing:
			continue
		try:
			content = b"".join(client.iter_article_image_content(article_id, image_id))
			file_doc = save_file(filename, content, "Item", item_code, decode=False, is_private=0)
			if img.get("mainImage"):
				frappe.db.set_value("Item", item_code, "image", file_doc.file_url)
		except Exception:
			continue
