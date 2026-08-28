# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt
"""Who is on leave tomorrow, so branch managers can plan cover.

Defaults to tomorrow but takes any date, which makes it usable for the whole
week ahead. Only approved and submitted applications count — a pending request
is not cover you can plan around, though it is shown separately in the summary
so nobody is caught out by a late approval.
"""

import frappe
from frappe import _
from frappe.utils import cint, getdate

from enfono_hr.hr_report_utils import EMPLOYEE_COLUMNS, employee_conditions, tomorrow


def execute(filters=None):
	filters = frappe._dict(filters or {})
	data = get_data(filters)
	return get_columns(), data, None, None, get_report_summary(data)


def get_columns():
	return EMPLOYEE_COLUMNS + [
		{
			"label": _("Leave Type"),
			"fieldname": "leave_type",
			"fieldtype": "Link",
			"options": "Leave Type",
			"width": 140,
		},
		{"label": _("From Date"), "fieldname": "from_date", "fieldtype": "Date", "width": 100},
		{"label": _("To Date"), "fieldname": "to_date", "fieldtype": "Date", "width": 100},
		{"label": _("Days"), "fieldname": "total_leave_days", "fieldtype": "Float", "width": 70},
		{"label": _("Half Day"), "fieldname": "half_day", "fieldtype": "Check", "width": 80},
		{"label": _("Reason"), "fieldname": "leave_reason", "fieldtype": "Data", "width": 240},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 100},
		{
			"label": _("Leave Approver"),
			"fieldname": "leave_approver",
			"fieldtype": "Link",
			"options": "User",
			"width": 180,
		},
		{
			"label": _("Leave Application"),
			"fieldname": "leave_application",
			"fieldtype": "Link",
			"options": "Leave Application",
			"width": 150,
		},
	]


def get_data(filters):
	on_date = str(getdate(filters.get("on_date") or tomorrow()))
	emp_conditions, params = employee_conditions(filters)
	params["on_date"] = on_date

	if cint(filters.get("include_pending")):
		status_condition = "AND la.status IN ('Approved', 'Open')"
	else:
		status_condition = "AND la.status = 'Approved'"

	return frappe.db.sql(
		f"""
		SELECT
			emp.name                AS employee,
			emp.employee_name       AS employee_name,
			emp.designation         AS designation,
			emp.department          AS department,
			emp.branch              AS branch,
			la.leave_type           AS leave_type,
			la.from_date            AS from_date,
			la.to_date              AS to_date,
			la.total_leave_days     AS total_leave_days,
			la.half_day             AS half_day,
			la.description          AS leave_reason,
			la.status               AS status,
			la.leave_approver       AS leave_approver,
			la.name                 AS leave_application
		FROM `tabLeave Application` la
		INNER JOIN `tabEmployee` emp ON emp.name = la.employee
		WHERE la.docstatus < 2
			AND %(on_date)s BETWEEN la.from_date AND la.to_date
			{status_condition}
			{emp_conditions}
		ORDER BY emp.branch, emp.department, emp.employee_name
		""",
		params,
		as_dict=True,
	)


def get_report_summary(data):
	if not data:
		return None

	return [
		{"label": _("On Leave"), "value": len(data), "datatype": "Int"},
		{
			"label": _("Branches Affected"),
			"value": len({row["branch"] for row in data if row.get("branch")}),
			"datatype": "Int",
		},
		{
			"label": _("Pending Approval"),
			"value": sum(1 for row in data if row.get("status") == "Open"),
			"datatype": "Int",
		},
	]
