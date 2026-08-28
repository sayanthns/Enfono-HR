// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Enfono HR Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Payroll Computation Preview"), () => {
			frappe.set_route("query-report", "Payroll Computation Preview");
		});

		frm.dashboard.add_comment(
			__(
				"These settings change what every employee is paid. After any change, " +
					"run the Payroll Computation Preview for a full month and check the " +
					"totals before the next payroll run."
			),
			"blue",
			true
		);
	},
});
