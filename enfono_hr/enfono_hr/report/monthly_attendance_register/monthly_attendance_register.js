// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt

frappe.query_reports["Monthly Attendance Register"] = {
	filters: [
		{
			fieldname: "month",
			label: __("Month"),
			fieldtype: "Select",
			reqd: 1,
			options: [
				{ value: 1, label: __("January") }, { value: 2, label: __("February") },
				{ value: 3, label: __("March") }, { value: 4, label: __("April") },
				{ value: 5, label: __("May") }, { value: 6, label: __("June") },
				{ value: 7, label: __("July") }, { value: 8, label: __("August") },
				{ value: 9, label: __("September") }, { value: 10, label: __("October") },
				{ value: 11, label: __("November") }, { value: 12, label: __("December") },
			],
			default: frappe.datetime.str_to_obj(frappe.datetime.get_today()).getMonth() + 1,
		},
		{
			fieldname: "year",
			label: __("Year"),
			fieldtype: "Int",
			reqd: 1,
			default: frappe.datetime.str_to_obj(frappe.datetime.get_today()).getFullYear(),
		},
		{ fieldname: "employee", label: __("Employee"), fieldtype: "Link", options: "Employee" },
		{ fieldname: "branch", label: __("Branch"), fieldtype: "Link", options: "Branch" },
		{ fieldname: "department", label: __("Department"), fieldtype: "Link", options: "Department" },
		{ fieldname: "designation", label: __("Designation"), fieldtype: "Link", options: "Designation" },
		{
			fieldname: "show_employees_without_attendance",
			label: __("Show Employees Without Attendance"),
			fieldtype: "Check",
		},
		{
			fieldname: "include_inactive",
			label: __("Include Inactive Employees"),
			fieldtype: "Check",
		},
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		// Colour only the day columns, and only by the client's own codes, so the
		// grid can be read at a glance without a legend beside it.
		if (column.fieldname && column.fieldname.startsWith("day_")) {
			const code = (data && data[column.fieldname]) || "";
			const colour = {
				P: "green", A: "red", L: "orange", CL: "blue", HD: "purple",
				H: "grey", WO: "grey",
			}[code];
			if (colour) value = `<span style="color:var(--text-on-${colour}, inherit)">${value}</span>`;
			if (code === "A") value = `<b style="color:#c0392b">${value}</b>`;
			if (code === "CL") value = `<b style="color:#2563eb">${value}</b>`;
		}
		return value;
	},
};
