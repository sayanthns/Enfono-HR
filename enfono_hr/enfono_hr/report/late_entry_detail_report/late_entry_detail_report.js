// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt

frappe.query_reports["Late Entry Detail Report"] = {
	// 🔴 `on_date` is a CONVENIENCE, not a third date. Picking it writes the same
	// day into from_date and to_date, because the client runs this report for one
	// day almost every time and setting two fields for that is two clicks too many.
	// The range filters stay, so a span is still possible — clearing on_date
	// leaves them alone.
	onload(report) {
		report.page.add_inner_button(__("Today"), () => {
			const today = frappe.datetime.get_today();
			report.set_filter_value({ on_date: today, from_date: today, to_date: today });
		});
	},

	filters: [
		{
			fieldname: "on_date",
			label: __("Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			on_change(report) {
				const day = report.get_filter_value("on_date");
				if (!day) return;   // cleared — leave the range as the user set it
				report.set_filter_value({ from_date: day, to_date: day });
			},
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "employee",
			label: __("Employee"),
			fieldtype: "Link",
			options: "Employee",
		},
		{
			fieldname: "branch",
			label: __("Branch"),
			fieldtype: "Link",
			options: "Branch",
		},
		{
			fieldname: "department",
			label: __("Department"),
			fieldtype: "Link",
			options: "Department",
		},
		{
			fieldname: "designation",
			label: __("Designation"),
			fieldtype: "Link",
			options: "Designation",
		},
		{
			fieldname: "grace_period",
			label: __("Grace Period (Minutes)"),
			fieldtype: "Int",
			default: 15,
		},
		{
			fieldname: "include_inactive",
			label: __("Include Inactive Employees"),
			fieldtype: "Check",
		}
	],
};
