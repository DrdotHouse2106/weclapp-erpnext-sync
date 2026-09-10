// Copyright (c) 2026, WeClapp Sync
// For license information, please see license.txt

frappe.ui.form.on("WeClapp Sync Run", {
	refresh(frm) {
		if (frm.doc.status === "Running" && !frm.doc.abort_requested) {
			frm.add_custom_button(__("Abbruch anfordern"), () => {
				frappe.confirm(
					__("Lauf an der nächsten Seitengrenze stoppen? Bereits importierte Datensätze bleiben erhalten."),
					() => {
						frappe.db
							.set_value("WeClapp Sync Run", frm.doc.name, "abort_requested", 1)
							.then(() => {
								frappe.show_alert({
									message: __("Abbruch angefordert - der Lauf stoppt in Kürze."),
									indicator: "orange",
								});
								frm.reload_doc();
							});
					},
				);
			}).addClass("btn-danger");
		}

		if (frm.doc.status === "Running" && frm.doc.abort_requested) {
			frm.dashboard.set_headline(
				__("Abbruch angefordert - der Lauf stoppt an der nächsten Seitengrenze."),
			);
		}
	},
});
