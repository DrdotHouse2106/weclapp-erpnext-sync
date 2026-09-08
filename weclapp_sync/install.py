import frappe

from weclapp_sync.setup.runner import run_setup


def after_install():
	"""Legt die Single-"WeClapp Settings" an und zieht Custom Fields + Naming nach."""
	if not frappe.db.exists("WeClapp Settings", "WeClapp Settings"):
		doc = frappe.new_doc("WeClapp Settings")
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)

	run_setup()
	frappe.db.commit()
