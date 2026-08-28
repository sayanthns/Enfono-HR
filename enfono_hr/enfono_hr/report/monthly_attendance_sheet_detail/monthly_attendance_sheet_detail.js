// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

frappe.query_reports["Monthly Attendance Sheet Detail"] = {
	filters: [
		{
			fieldname: "month",
			label: __("Month"),
			fieldtype: "Select",
			options: "January\nFebruary\nMarch\nApril\nMay\nJune\nJuly\nAugust\nSeptember\nOctober\nNovember\nDecember",
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
			fieldname: "grace_period",
			label: __("Grace Period (Minutes)"),
			fieldtype: "Int",
			default: 15,
		},
		{
			fieldname: "show_employees_without_attendance",
			label: __("Show Employees Without Attendance"),
			fieldtype: "Check",
		},
		{
			fieldname: "include_inactive",
			label: __("Include Inactive Employees"),
			fieldtype: "Check",
		}
	],
};
