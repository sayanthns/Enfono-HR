# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt
"""Breaks taken during a shift, inferred from check-in/check-out pairs.

There is no break event in the data model — ``Employee Checkin.log_type`` is only
``IN`` or ``OUT``. A break is therefore read as an OUT followed by an IN on the
same day: the employee stepped out and came back. The first IN and the final OUT
bracket the working day and are not breaks.

That means the report is only as good as the logging discipline: an employee who
never logs out for lunch shows no break. If Inlite wants exact break tracking,
explicit Break In / Break Out actions have to be added to the ESS mobile app —
that is an app release, not a report.

Rows created by the nightly Auto Check-Out job are ignored, so a forgotten
checkout never fabricates a break.
"""

import frappe
from frappe import _
from frappe.utils import cint, get_datetime

from enfono_hr.hr_report_utils import (
	EMPLOYEE_COLUMNS,
	auto_checkout_predicate,
	date_range,
	employee_conditions,
	format_minutes,
)

#: Ignore sub-minute in/out bounces — those are double taps, not breaks.
MIN_BREAK_MINUTES = 1

#: Beyond this, an OUT/IN pair is not a break.
#:
#: Someone who logs out at 09:00 and back in at 18:00 did not take a nine-hour
#: break — they left and returned, and the middle of that day is absence, not
#: rest. Without a ceiling those gaps dominate the averages and make the report
#: useless for spotting genuinely long lunches.
MAX_BREAK_MINUTES = 240


def execute(filters=None):
	filters = frappe._dict(filters or {})
	data = get_data(filters)
	return get_columns(), data, None, None, get_report_summary(data)


def get_columns():
	return EMPLOYEE_COLUMNS + [
		{"label": _("Date"), "fieldname": "log_date", "fieldtype": "Date", "width": 100},
		{"label": _("Break No"), "fieldname": "break_no", "fieldtype": "Int", "width": 90},
		{"label": _("Break Out"), "fieldname": "break_out", "fieldtype": "Datetime", "width": 180},
		{"label": _("Break In"), "fieldname": "break_in", "fieldtype": "Datetime", "width": 180},
		{"label": _("Break Duration"), "fieldname": "break_duration", "fieldtype": "Data", "width": 130},
		{
			"label": _("Break (Minutes)"),
			"fieldname": "break_minutes",
			"fieldtype": "Int",
			"width": 130,
		},
		{
			"label": _("Total Breaks (Day)"),
			"fieldname": "total_breaks_day",
			"fieldtype": "Int",
			"width": 140,
		},
		{
			"label": _("Total Break Minutes (Day)"),
			"fieldname": "total_break_minutes_day",
			"fieldtype": "Int",
			"width": 190,
		},
	]


def get_data(filters):
	from_date, to_date = date_range(filters)
	emp_conditions, params = employee_conditions(filters)
	params.update({"from_date": from_date, "to_date": to_date})

	auto_checkout = auto_checkout_predicate("eci")

	logs = frappe.db.sql(
		f"""
		SELECT
			emp.name            AS employee,
			emp.employee_name   AS employee_name,
			emp.designation     AS designation,
			emp.department      AS department,
			emp.branch          AS branch,
			DATE(eci.time)      AS log_date,
			eci.time            AS log_time,
			eci.log_type        AS log_type
		FROM `tabEmployee Checkin` eci
		INNER JOIN `tabEmployee` emp ON emp.name = eci.employee
		WHERE DATE(eci.time) BETWEEN %(from_date)s AND %(to_date)s
			AND NOT ({auto_checkout})
			{emp_conditions}
		ORDER BY emp.name, eci.time
		""",
		params,
		as_dict=True,
	)

	return build_breaks(
		logs,
		cint(filters.get("min_break_minutes") or MIN_BREAK_MINUTES),
		cint(filters.get("max_break_minutes") or MAX_BREAK_MINUTES),
	)


def build_breaks(logs, min_break_minutes, max_break_minutes):
	"""Turn an ordered check-in stream into break rows.

	Walks each employee-day in time order and emits a row for every OUT that is
	followed by an IN. The trailing OUT of the day has no following IN, so it
	falls out naturally as the end of the working day rather than a break.
	"""
	by_day: dict[tuple, list[dict]] = {}
	for log in logs:
		by_day.setdefault((log["employee"], log["log_date"]), []).append(log)

	rows = []
	for (_employee, _log_date), day_logs in sorted(by_day.items(), key=lambda kv: (kv[0][1], kv[0][0])):
		day_rows = []
		break_no = 0

		for current, following in zip(day_logs, day_logs[1:]):
			if current["log_type"] != "OUT" or following["log_type"] != "IN":
				continue

			minutes = int(
				(get_datetime(following["log_time"]) - get_datetime(current["log_time"])).total_seconds()
				// 60
			)
			if minutes < min_break_minutes or minutes > max_break_minutes:
				continue

			break_no += 1
			day_rows.append(
				{
					"employee": current["employee"],
					"employee_name": current["employee_name"],
					"designation": current["designation"],
					"department": current["department"],
					"branch": current["branch"],
					"log_date": current["log_date"],
					"break_no": break_no,
					"break_out": current["log_time"],
					"break_in": following["log_time"],
					"break_minutes": minutes,
					"break_duration": format_minutes(minutes),
				}
			)

		total_minutes = sum(row["break_minutes"] for row in day_rows)
		for row in day_rows:
			row["total_breaks_day"] = len(day_rows)
			row["total_break_minutes_day"] = total_minutes

		rows.extend(day_rows)

	rows.sort(key=lambda row: (row["log_date"], row["branch"] or "", row["employee_name"] or "", row["break_no"]))
	return rows


def get_report_summary(data):
	if not data:
		return None

	total_minutes = sum(row["break_minutes"] for row in data)
	return [
		{"label": _("Breaks Logged"), "value": len(data), "datatype": "Int"},
		{
			"label": _("Employees"),
			"value": len({row["employee"] for row in data}),
			"datatype": "Int",
		},
		{"label": _("Total Break Minutes"), "value": total_minutes, "datatype": "Int"},
		{
			"label": _("Avg Break (Minutes)"),
			"value": round(total_minutes / len(data)) if data else 0,
			"datatype": "Int",
		},
	]
