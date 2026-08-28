# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt
"""Early exits measured against the employee's shift end.

Mirror of the Late Entry Detail Report. Two differences worth knowing:

* Overnight shifts (``end_time`` earlier on the clock than ``start_time``, e.g.
  8PM–8AM) have their end rolled to the following day, otherwise every night
  worker looks twelve hours early.
* Rows whose checkout was written by the nightly Auto Check-Out job are excluded
  — a synthetic 23:00 stamp is not evidence of anything.
"""

import frappe
from frappe import _

from enfono_hr.hr_report_utils import (
	EMPLOYEE_COLUMNS,
	SHIFT_END_EXPR,
	auto_checkout_predicate,
	date_range,
	employee_conditions,
	format_minutes,
	grace_minutes,
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	data = get_data(filters)
	return get_columns(), data, None, None, get_report_summary(data)


def get_columns():
	return EMPLOYEE_COLUMNS + [
		{"label": _("Date"), "fieldname": "attendance_date", "fieldtype": "Date", "width": 100},
		{
			"label": _("Shift"),
			"fieldname": "shift",
			"fieldtype": "Link",
			"options": "Shift Type",
			"width": 150,
		},
		{"label": _("Shift End Time"), "fieldname": "shift_end", "fieldtype": "Time", "width": 130},
		{"label": _("Exit Time"), "fieldname": "out_time", "fieldtype": "Datetime", "width": 180},
		{
			"label": _("Early Exit Duration"),
			"fieldname": "early_exit_duration",
			"fieldtype": "Data",
			"width": 150,
		},
		{"label": _("Early (Minutes)"), "fieldname": "early_minutes", "fieldtype": "Int", "width": 120},
		{
			"label": _("Working Hours"),
			"fieldname": "working_hours",
			"fieldtype": "Float",
			"precision": 2,
			"width": 120,
		},
		{
			"label": _("Attendance"),
			"fieldname": "attendance",
			"fieldtype": "Link",
			"options": "Attendance",
			"width": 140,
		},
	]


def get_data(filters):
	from_date, to_date = date_range(filters)
	emp_conditions, params = employee_conditions(filters)
	params.update(
		{"from_date": from_date, "to_date": to_date, "grace": grace_minutes(filters)}
	)

	auto_checkout = auto_checkout_predicate("eci")

	rows = frappe.db.sql(
		f"""
		SELECT
			emp.name                AS employee,
			emp.employee_name       AS employee_name,
			emp.designation         AS designation,
			emp.department          AS department,
			emp.branch              AS branch,
			att.attendance_date     AS attendance_date,
			st.name                 AS shift,
			st.end_time             AS shift_end,
			att.out_time            AS out_time,
			att.name                AS attendance,
			att.working_hours       AS working_hours,
			TIMESTAMPDIFF(MINUTE, att.out_time, {SHIFT_END_EXPR}) AS early_minutes
		FROM `tabAttendance` att
		INNER JOIN `tabEmployee` emp ON emp.name = att.employee
		INNER JOIN `tabShift Type` st ON st.name = COALESCE(att.shift, emp.default_shift)
		WHERE att.docstatus = 1
			AND att.attendance_date BETWEEN %(from_date)s AND %(to_date)s
			AND att.out_time IS NOT NULL
			AND att.in_time IS NOT NULL
			AND att.status IN ('Present', 'Half Day', 'Work From Home')
			-- A day with no genuine checkout leaves out_time equal to in_time.
			-- That is a missing checkout, not an early exit: it belongs to the
			-- Previous Day Checkout Not Marked report, and counting it here would
			-- fine the same employee twice for one lapse.
			AND att.out_time > att.in_time
			AND TIMESTAMPDIFF(MINUTE, att.out_time, {SHIFT_END_EXPR}) > %(grace)s
			AND NOT EXISTS (
				SELECT 1 FROM `tabEmployee Checkin` eci
				WHERE eci.employee = att.employee
					AND eci.log_type = 'OUT'
					AND eci.time = att.out_time
					AND {auto_checkout}
			)
			{emp_conditions}
		ORDER BY att.attendance_date DESC, emp.branch, emp.employee_name
		""",
		params,
		as_dict=True,
	)

	for row in rows:
		row["early_exit_duration"] = format_minutes(row.get("early_minutes"))

	return rows


def get_report_summary(data):
	if not data:
		return None

	total_minutes = sum(row.get("early_minutes") or 0 for row in data)
	return [
		{"label": _("Early Exit Occurrences"), "value": len(data), "datatype": "Int"},
		{
			"label": _("Employees Affected"),
			"value": len({row["employee"] for row in data}),
			"datatype": "Int",
		},
		{"label": _("Total Early Minutes"), "value": total_minutes, "datatype": "Int"},
	]
