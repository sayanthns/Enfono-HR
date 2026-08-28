// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

frappe.query_reports["Payroll Computation Preview"] = {
	filters: [
		{
			fieldname: "month",
			label: __("Month"),
			fieldtype: "Select",
			options: MONTHS,
			default: MONTHS[frappe.datetime.str_to_obj(frappe.datetime.get_today()).getMonth()],
			reqd: 1,
		},
		{
			fieldname: "year",
			label: __("Year"),
			fieldtype: "Int",
			default: frappe.datetime.str_to_obj(frappe.datetime.get_today()).getFullYear(),
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
			fieldname: "show_zero_rows",
			label: __("Show Employees Without a Salary Structure"),
			fieldtype: "Check",
		},
	],
	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && column.fieldname === "net_salary") {
			value = "<b>" + value + "</b>";
		}
		if (data && ["flat_fine", "penalty_amount", "fine_total"].includes(column.fieldname) && data[column.fieldname] > 0) {
			value = "<span style='color:var(--red-500)'>" + value + "</span>";
		}
		return value;
	},
};
