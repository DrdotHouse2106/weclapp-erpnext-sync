"""Setzt die Felder am bestehenden "WeClapp Sync"-Workspace, die eine frühere Version ohne
`app`/`type` angelegt hat - sonst taucht der Bereich in der v16-Sidebar nicht auf."""

import frappe


def execute():
	if not frappe.db.exists("Workspace", "WeClapp Sync"):
		return
	frappe.db.set_value(
		"Workspace",
		"WeClapp Sync",
		{
			"app": "weclapp_sync",
			"type": "Workspace",
			"public": 1,
			"is_hidden": 0,
			"for_user": "",
		},
		update_modified=False,
	)
	frappe.clear_cache()
