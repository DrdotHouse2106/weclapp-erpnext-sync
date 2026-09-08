frappe.ui.form.on("WeClapp Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Zu den Sync-Läufen"), () => {
			frappe.set_route("List", "WeClapp Sync Run");
		});
	},

	test_connection(frm) {
		frm.call({
			doc: frm.doc,
			method: "test_weclapp_connection",
			freeze: true,
			freeze_message: __("Teste WeClapp-Verbindung …"),
			callback: (r) => {
				frm.reload_doc();
				frappe.msgprint({ title: __("Verbindungstest"), message: r.message, indicator: r.message.startsWith("OK") ? "green" : "red" });
			},
		});
	},

	refresh_object_types(frm) {
		frm.call({ doc: frm.doc, method: "refresh_object_type_list", freeze: true }).then((r) => {
			frm.reload_doc();
			frappe.show_alert({ message: r.message, indicator: "green" });
		});
	},

	run_full_import(frm) {
		frappe.confirm(
			__("Vollimport aller aktivierten Objekttypen jetzt starten? Das kann je nach Datenmenge Stunden dauern."),
			() => {
				frm.call({ doc: frm.doc, method: "start_full_import", freeze: true }).then((r) => {
					frappe.msgprint({ title: __("Vollimport"), message: r.message, indicator: "blue" });
				});
			}
		);
	},
});
