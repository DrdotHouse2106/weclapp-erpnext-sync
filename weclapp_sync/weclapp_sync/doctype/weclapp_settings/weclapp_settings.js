frappe.ui.form.on("WeClapp Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Zu den Sync-Läufen"), () => {
			frappe.set_route("List", "WeClapp Sync Run");
		});

		const grid = frm.get_field("custom_attribute_mappings").grid;
		if (grid && !grid._wc_assign_btn) {
			grid._wc_assign_btn = true;
			grid.add_custom_button(__("Vorhandenes Feld zuordnen …"), () => {
				const rows = grid.get_selected_children();
				if (rows.length !== 1) {
					frappe.msgprint(__("Genau eine Zeile in der Tabelle anhaken."));
					return;
				}
				assign_existing_field(frm, rows[0]);
			});
		}
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

	populate_price_list_mappings(frm) {
		frm.call({
			doc: frm.doc,
			method: "populate_price_list_mappings",
			freeze: true,
			freeze_message: __("Hole WeClapp-Preiskanäle …"),
		}).then((r) => {
			frm.reload_doc();
			frappe.show_alert({ message: r.message, indicator: "green" });
		});
	},

	create_missing_tax_accounts(frm) {
		frappe.confirm(
			__("Fehlende, von WeClapp-Steuern referenzierte SKR03-Konten im Kontenplan anlegen?"),
			() => {
				frm.call({
					doc: frm.doc,
					method: "create_missing_tax_accounts",
					freeze: true,
					freeze_message: __("Lege Konten an …"),
				}).then((r) => {
					frm.reload_doc();
					frappe.msgprint({ title: __("Steuerkonten"), message: (r.message || "").replace(/\n/g, "<br>"), indicator: "green" });
				});
			}
		);
	},

	populate_tax_mappings(frm) {
		frappe.confirm(
			__("Alle Kontospalten im Steuer-Mapping werden aus WeClapp neu abgeleitet (manuelle Änderungen gehen verloren). Fortfahren?"),
			() => {
				frm.call({
					doc: frm.doc,
					method: "populate_tax_mapping",
					freeze: true,
					freeze_message: __("Hole WeClapp-Steuern …"),
				}).then((r) => {
					frm.reload_doc();
					frappe.msgprint({ title: __("Steuer-Mapping"), message: (r.message || "").replace(/\n/g, "<br>"), indicator: "blue" });
				});
			}
		);
	},

	populate_custom_attribute_mappings(frm) {
		frm.call({
			doc: frm.doc,
			method: "populate_custom_attribute_mapping",
			freeze: true,
			freeze_message: __("Hole WeClapp-Zusatzfelder …"),
		}).then((r) => {
			frm.reload_doc();
			frappe.msgprint({ title: __("Zusatzfelder"), message: r.message, indicator: "blue" });
		});
	},

	apply_custom_attribute_fields(frm) {
		frappe.confirm(
			__("Für alle angehakten Zusatzfelder die fehlenden ERPNext-Felder anlegen?"),
			() => {
				frm.call({
					doc: frm.doc,
					method: "apply_custom_attribute_fields",
					freeze: true,
					freeze_message: __("Lege Felder an …"),
				}).then((r) => {
					frm.reload_doc();
					frappe.msgprint({ title: __("Zusatzfelder"), message: r.message, indicator: "green" });
				});
			}
		);
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

const _ASSIGNABLE_FIELDTYPES = [
	"Data", "Small Text", "Long Text", "Text", "Text Editor", "Check", "Int", "Float",
	"Currency", "Percent", "Select", "Table MultiSelect", "Date", "Datetime", "Link", "Read Only",
];

function assign_existing_field(frm, row) {
	const doctypes = (row.target_doctype || "")
		.split(",")
		.map((s) => s.trim())
		.filter((s) => s && s.indexOf("unbekannt") === -1);

	const pick_doctype = doctypes.length ? doctypes : [row.target_doctype || ""];

	const d = new frappe.ui.Dialog({
		title: __("Vorhandenes Feld zuordnen: {0}", [row.wc_label || row.wc_attribute_key]),
		fields: [
			{
				fieldname: "doctype",
				label: __("ERPNext-Doctype"),
				fieldtype: "Select",
				options: pick_doctype.join("\n"),
				default: pick_doctype[0],
				reqd: 1,
			},
			{ fieldname: "field", label: __("Feld"), fieldtype: "Select", options: "", reqd: 1 },
			{
				fieldname: "hint",
				fieldtype: "HTML",
				options: `<div class="text-muted small">${__(
					"Zeigt alle vorhandenen Felder des Doctypes (Standard- und Custom-Felder). Nach der Zuordnung wird kein neues Feld angelegt."
				)}</div>`,
			},
		],
		primary_action_label: __("Übernehmen"),
		primary_action(values) {
			const meta = frappe.get_meta(values.doctype);
			const df = (meta.fields || []).find((f) => f.fieldname === values.field);
			frappe.model.set_value(row.doctype, row.name, "target_fieldname", values.field);
			if (df) {
				frappe.model.set_value(row.doctype, row.name, "target_label", df.label || values.field);
				if (_ASSIGNABLE_FIELDTYPES.indexOf(df.fieldtype) !== -1) {
					frappe.model.set_value(row.doctype, row.name, "fieldtype", df.fieldtype);
				}
			}
			frappe.model.set_value(row.doctype, row.name, "enabled", 1);
			frm.refresh_field("custom_attribute_mappings");
			frappe.show_alert({
				message: __("Zugeordnet. Zum Speichern das Formular sichern."),
				indicator: "green",
			});
			d.hide();
		},
	});

	const load_fields = (dt) => {
		if (!dt) return;
		frappe.model.with_doctype(dt, () => {
			const meta = frappe.get_meta(dt);
			const opts = (meta.fields || [])
				.filter((f) => f.fieldname && _ASSIGNABLE_FIELDTYPES.indexOf(f.fieldtype) !== -1)
				.map((f) => ({
					label: `${f.label || f.fieldname} — ${f.fieldname} (${f.fieldtype})`,
					value: f.fieldname,
				}));
			d.set_df_property("field", "options", opts);
			if (opts.length) d.set_value("field", opts[0].value);
		});
	};

	d.fields_dict.doctype.$input.on("change", (e) => load_fields(e.target.value));
	d.show();
	load_fields(pick_doctype[0]);
}
