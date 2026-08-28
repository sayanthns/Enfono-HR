# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt
"""Leave requests as they were reported, for a day or a date range.

"Reported Date & Time" is the moment the request was raised (``creation``),
not the date being asked for — that is the point of the report: HR wants to see
what landed in the tray today.
"""

import frappe
from frappe import _

from enfono_hr.hr_report_utils import EMPLOYEE_COLUMNS, date_range, employee_conditions


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


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
		{"label": _("Leave Reason"), "fieldname": "leave_reason", "fieldtype": "Data", "width": 260},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 100},
		{"label": _("Workflow State"), "fieldname": "workflow_state", "fieldtype": "Data", "width": 160},
		{
			"label": _("Reported Date & Time"),
			"fieldname": "reported_on",
			"fieldtype": "Datetime",
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
	from_date, to_date = date_range(filters)
	emp_conditions, params = employee_conditions(filters)
	params.update({"from_date": from_date, "to_date": to_date})

	status_condition = ""
	if filters.get("status"):
		status_condition = "AND la.status = %(status)s"
		params["status"] = filters.get("status")

	leave_type_condition = ""
	if filters.get("leave_type"):
		leave_type_condition = "AND la.leave_type = %(leave_type)s"
		params["leave_type"] = filters.get("leave_type")

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
			la.workflow_state       AS workflow_state,
			la.creation             AS reported_on,
			la.name                 AS leave_application
		FROM `tabLeave Application` la
		INNER JOIN `tabEmployee` emp ON emp.name = la.employee
		WHERE la.docstatus < 2
			AND DATE(la.creation) BETWEEN %(from_date)s AND %(to_date)s
			{emp_conditions}
			{status_condition}
			{leave_type_condition}
		ORDER BY la.creation DESC
		""",
		params,
		as_dict=True,
	)
