// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt

frappe.query_reports["Advance Payment Request Report"] = {
	filters: [
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date" },
		{ fieldname: "employee", label: __("Employee"), fieldtype: "Link", options: "Employee" },
		{ fieldname: "branch", label: __("Branch"), fieldtype: "Link", options: "Branch" },
		{ fieldname: "department", label: __("Department"), fieldtype: "Link", options: "Department" },
		{ fieldname: "designation", label: __("Designation"), fieldtype: "Link", options: "Designation" },
		{
			fieldname: "advance_route",
			label: __("Approval Route"),
			fieldtype: "Select",
			options: "\nStandard\nDriver & Marketing",
		},
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: "\nDraft\nUnpaid\nPaid\nClaimed\nReturned\nPartly Claimed and Returned\nCancelled",
		},
		{ fieldname: "include_inactive", label: __("Include Inactive Employees"), fieldtype: "Check" },
	],
};
