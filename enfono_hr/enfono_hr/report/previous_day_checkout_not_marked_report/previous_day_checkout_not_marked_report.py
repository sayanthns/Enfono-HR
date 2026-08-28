# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt
"""Employees who checked in but never genuinely checked out.

Defaults to yesterday, which is what the client asked for — HR runs it in the
morning to chase the previous day's gaps.

The one thing that makes this report non-trivial: a nightly ``Auto Check-Out``
job stamps a synthetic 23:00 OUT for anyone who forgot. Left alone, that job
would make this report permanently empty. Rows carrying that signature are
therefore treated as *no checkout at all*, and surfaced with the reason
``Auto Check-Out Applied`` so HR can tell a genuine gap from a covered one.
"""

import frappe
from frappe import _
from frappe.utils import cint

from enfono_hr.hr_report_utils import (
	EMPLOYEE_COLUMNS,
	auto_checkout_predicate,
	date_range,
	employee_conditions,
	yesterday,
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	data = get_data(filters)
	return get_columns(), data, None, None, get_report_summary(data)


def get_columns():
	return EMPLOYEE_COLUMNS + [
		{"label": _("Date"), "fieldname": "log_date", "fieldtype": "Date", "width": 100},
		{
			"label": _("Shift"),
			"fieldname": "shift",
			"fieldtype": "Link",
			"options": "Shift Type",
			"width": 150,
		},
		{"label": _("First Check-in"), "fieldname": "first_in", "fieldtype": "Datetime", "width": 180},
		{"label": _("Last Log"), "fieldname": "last_log", "fieldtype": "Datetime", "width": 180},
		{"label": _("Reason"), "fieldname": "reason", "fieldtype": "Data", "width": 200},
		{
			"label": _("Half Day Requested"),
			"fieldname": "half_day_requested",
			"fieldtype": "Check",
			"width": 150,
		},
		{
			"label": _("Attendance Status"),
			"fieldname": "attendance_status",
			"fieldtype": "Data",
			"width": 140,
		},
	]


def get_data(filters):
	from_date, to_date = date_range(filters, default_from=yesterday())
	emp_conditions, params = employee_conditions(filters)
	params.update({"from_date": from_date, "to_date": to_date})

	auto_checkout = auto_checkout_predicate("eci")

	rows = frappe.db.sql(
		f"""
		SELECT
			emp.name            AS employee,
			emp.employee_name   AS employee_name,
			emp.designation     AS designation,
			emp.department      AS department,
			emp.branch          AS branch,
			DATE(eci.time)      AS log_date,
			COALESCE(MAX(eci.shift), emp.default_shift) AS shift,
			MIN(CASE WHEN eci.log_type = 'IN' THEN eci.time END)  AS first_in,
			MAX(eci.time)       AS last_log,
			SUM(CASE WHEN eci.log_type = 'OUT' AND NOT {auto_checkout} THEN 1 ELSE 0 END)
				AS real_checkouts,
			SUM(CASE WHEN eci.log_type = 'OUT' AND {auto_checkout} THEN 1 ELSE 0 END)
				AS auto_checkouts
		FROM `tabEmployee Checkin` eci
		INNER JOIN `tabEmployee` emp ON emp.name = eci.employee
		WHERE DATE(eci.time) BETWEEN %(from_date)s AND %(to_date)s
			{emp_conditions}
		GROUP BY emp.name, emp.employee_name, emp.designation, emp.department,
			emp.branch, DATE(eci.time), emp.default_shift
		HAVING MIN(CASE WHEN eci.log_type = 'IN' THEN eci.time END) IS NOT NULL
			AND real_checkouts = 0
		ORDER BY log_date DESC, emp.branch, emp.employee_name
		""",
		params,
		as_dict=True,
	)

	if not rows:
		return rows

	annotate_half_day_requests(rows)
	annotate_attendance_status(rows)

	for row in rows:
		row["reason"] = (
			_("Auto Check-Out Applied")
			if cint(row.pop("auto_checkouts", 0))
			else _("No Check-out Logged")
		)
		row.pop("real_checkouts", None)

	return rows


def annotate_half_day_requests(rows):
	"""Mark rows where the employee did file a half-day leave for that date.

	The client's rule fines a missing checkout only when no half-day request was
	made, so HR needs to see both facts in one place.
	"""
	pairs = {(row["employee"], str(row["log_date"])) for row in rows}
	employees = list({employee for employee, _date in pairs})
	dates = sorted({date for _employee, date in pairs})

	applications = frappe.db.sql(
		"""
		SELECT employee, from_date, to_date
		FROM `tabLeave Application`
		WHERE docstatus = 1
			AND half_day = 1
			AND status = 'Approved'
			AND employee IN %(employees)s
			AND from_date <= %(max_date)s
			AND to_date >= %(min_date)s
		""",
		{"employees": employees, "min_date": dates[0], "max_date": dates[-1]},
		as_dict=True,
	)

	for row in rows:
		log_date = row["log_date"]
		row["half_day_requested"] = any(
			app["employee"] == row["employee"] and app["from_date"] <= log_date <= app["to_date"]
			for app in applications
		)


def annotate_attendance_status(rows):
	"""Attach the Attendance status already marked for that employee-day, if any."""
	employees = list({row["employee"] for row in rows})
	dates = sorted({str(row["log_date"]) for row in rows})

	records = frappe.db.sql(
		"""
		SELECT employee, attendance_date, status
		FROM `tabAttendance`
		WHERE docstatus = 1
			AND employee IN %(employees)s
			AND attendance_date BETWEEN %(min_date)s AND %(max_date)s
		""",
		{"employees": employees, "min_date": dates[0], "max_date": dates[-1]},
		as_dict=True,
	)

	status_map = {(r["employee"], r["attendance_date"]): r["status"] for r in records}
	for row in rows:
		row["attendance_status"] = status_map.get((row["employee"], row["log_date"]), "")


def get_report_summary(data):
	if not data:
		return None

	covered = sum(1 for row in data if row.get("reason") == _("Auto Check-Out Applied"))
	return [
		{"label": _("Missing Check-outs"), "value": len(data), "datatype": "Int"},
		{"label": _("Covered by Auto Check-Out"), "value": covered, "datatype": "Int"},
		{
			"label": _("With Half Day Request"),
			"value": sum(1 for row in data if row.get("half_day_requested")),
			"datatype": "Int",
		},
	]
