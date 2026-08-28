# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt
"""Late entries measured against the employee's shift start.

Lateness is recomputed here from ``Attendance.in_time`` rather than read off
``Attendance.late_entry``, because that flag was written using whatever grace
period the Shift Type carried on the day the attendance was marked. Recomputing
lets HR re-run any past month against the current 15-minute rule and get a
consistent answer.

The shift is taken from the Attendance row, falling back to
``Employee.default_shift`` — most employees here are driven by the default
rather than an explicit Shift Assignment.
"""

import frappe
from frappe import _

from enfono_hr.hr_report_utils import (
	EMPLOYEE_COLUMNS,
	SHIFT_START_EXPR,
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
		{"label": _("Shift Start Time"), "fieldname": "shift_start", "fieldtype": "Time", "width": 130},
		{"label": _("Reported Time"), "fieldname": "in_time", "fieldtype": "Datetime", "width": 180},
		{"label": _("Late Duration"), "fieldname": "late_duration", "fieldtype": "Data", "width": 120},
		{"label": _("Late (Minutes)"), "fieldname": "late_minutes", "fieldtype": "Int", "width": 120},
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
			st.start_time           AS shift_start,
			att.in_time             AS in_time,
			att.name                AS attendance,
			TIMESTAMPDIFF(MINUTE, {SHIFT_START_EXPR}, att.in_time) AS late_minutes
		FROM `tabAttendance` att
		INNER JOIN `tabEmployee` emp ON emp.name = att.employee
		INNER JOIN `tabShift Type` st ON st.name = COALESCE(att.shift, emp.default_shift)
		WHERE att.docstatus = 1
			AND att.attendance_date BETWEEN %(from_date)s AND %(to_date)s
			AND att.in_time IS NOT NULL
			AND att.status IN ('Present', 'Half Day', 'Work From Home')
			AND TIMESTAMPDIFF(MINUTE, {SHIFT_START_EXPR}, att.in_time) > %(grace)s
			{emp_conditions}
		ORDER BY att.attendance_date DESC, emp.branch, emp.employee_name
		""",
		params,
		as_dict=True,
	)

	for row in rows:
		row["late_duration"] = format_minutes(row.get("late_minutes"))

	return rows


def get_report_summary(data):
	if not data:
		return None

	total_minutes = sum(row.get("late_minutes") or 0 for row in data)
	return [
		{"label": _("Late Occurrences"), "value": len(data), "datatype": "Int"},
		{
			"label": _("Employees Affected"),
			"value": len({row["employee"] for row in data}),
			"datatype": "Int",
		},
		{"label": _("Total Late Minutes"), "value": total_minutes, "datatype": "Int"},
	]
