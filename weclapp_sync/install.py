import frappe


def after_install():
	"""Legt die Single-"WeClapp Settings" an, falls noch nicht vorhanden, damit der Nutzer
	direkt nach `bench install-app weclapp_sync` das Formular vorfindet."""
	if not frappe.db.exists("WeClapp Settings", "WeClapp Settings"):
		doc = frappe.new_doc("WeClapp Settings")
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
