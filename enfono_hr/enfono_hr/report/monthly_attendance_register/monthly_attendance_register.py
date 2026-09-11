# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt
"""Monthly Attendance Register — the client's own code scheme.

Requested in `HRMS AUTOMATION REQUIREMENTS.docx` (Sept 2026), which asked for a
month grid reading::

    P   Present
    A   Absent
    L   Leave
    H   Holiday
    WO  Week Off
    CL  Casual Leave

🔴 This is a SEPARATE report, deliberately. `Monthly Attendance Sheet Detail`
already uses ``H`` for **Half Day**, and it is the sheet payroll is signed off
from. Re-lettering it would silently change the meaning of every historic export
HR has already filed, so the two coexist: the Detail sheet keeps its codes for
payroll, this register carries the client's codes for reading.

The two differences worth knowing:

* ``H`` means **Holiday** here and **Half Day** on the Detail sheet. A half day
  shows as ``HD`` here so the letter stays free.
* ``CL`` is split out of ``L`` using ``Attendance.leave_type``, so casual leave
  is visible without opening anything.

🔴 Holiday and Week Off both come from the employee's Holiday List, told apart by
``Holiday.weekly_off``. On this site most employees are on a list that **expired
2026-03-31**, and the current-year lists carry no weekly-off day at all, so
``WO`` will be blank for them until the holiday lists are extended. That is a
data gap, not a fault in this report — it is called out in the report's own
summary rather than left to be discovered.
"""

from __future__ import annotations

import calendar

import frappe
from frappe import _
from frappe.utils import cint, flt

from enfono_hr.hr_report_utils import employee_conditions

# The client's scheme. HD is ours — they did not name a half-day code, and H is
# taken by Holiday in their list.
STATUS_CODE = {
	"Present": "P",
	"Absent": "A",
	"On Leave": "L",
	"Half Day": "HD",
	"Work From Home": "P",   # worked, just not on site
}

CASUAL_LEAVE_CODE = "CL"
HOLIDAY_CODE = "H"
WEEK_OFF_CODE = "WO"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	month = cint(filters.get("month")) or 1
	year = cint(filters.get("year")) or 2026
	days = calendar.monthrange(year, month)[1]

	data = get_data(filters, month, year, days)
	return get_columns(days), data, None, None, get_report_summary(data, filters, month, year)


def get_columns(days):
	columns = [
		{"label": _("Employee ID"), "fieldname": "employee", "fieldtype": "Link",
		 "options": "Employee", "width": 110},
		{"label": _("Employee Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 170},
		{"label": _("Designation"), "fieldname": "designation", "fieldtype": "Data", "width": 140},
		{"label": _("Branch"), "fieldname": "branch", "fieldtype": "Data", "width": 150},
	]

	for day in range(1, days + 1):
		columns.append(
			{"label": str(day), "fieldname": f"day_{day}", "fieldtype": "Data", "width": 45}
		)

	columns += [
		{"label": _("P"), "fieldname": "total_present", "fieldtype": "Float", "width": 60},
		{"label": _("A"), "fieldname": "total_absent", "fieldtype": "Float", "width": 60},
		{"label": _("L"), "fieldname": "total_leave", "fieldtype": "Float", "width": 60},
		{"label": _("CL"), "fieldname": "total_casual", "fieldtype": "Float", "width": 60},
		{"label": _("HD"), "fieldname": "total_half_day", "fieldtype": "Float", "width": 60},
		{"label": _("H"), "fieldname": "total_holiday", "fieldtype": "Float", "width": 60},
		{"label": _("WO"), "fieldname": "total_week_off", "fieldtype": "Float", "width": 60},
		{"label": _("Unmarked"), "fieldname": "total_unmarked", "fieldtype": "Float", "width": 90},
	]
	return columns


def get_employees(filters):
	emp_conditions, params = employee_conditions(filters)
	return frappe.db.sql(
		f"""
		SELECT
			emp.name          AS employee,
			emp.employee_name AS employee_name,
			emp.designation   AS designation,
			emp.department    AS department,
			emp.branch        AS branch,
			emp.holiday_list  AS holiday_list
		FROM `tabEmployee` emp
		WHERE 1 = 1
			{emp_conditions}
		ORDER BY emp.branch, emp.department, emp.employee_name
		""",
		params,
		as_dict=True,
	)


def get_attendance(filters, month, year):
	"""One row per employee per marked day, carrying the leave type.

	`leave_type` is what makes CL separable from every other kind of leave;
	without it every approved leave would collapse into a single ``L``.
	"""
	emp_conditions, params = employee_conditions(filters)
	params.update({"month": month, "year": year})

	return frappe.db.sql(
		f"""
		SELECT
			att.employee             AS employee,
			DAY(att.attendance_date) AS day,
			att.status               AS status,
			att.leave_type           AS leave_type
		FROM `tabAttendance` att
		INNER JOIN `tabEmployee` emp ON emp.name = att.employee
		WHERE att.docstatus = 1
			AND MONTH(att.attendance_date) = %(month)s
			AND YEAR(att.attendance_date) = %(year)s
			{emp_conditions}
		""",
		params,
		as_dict=True,
	)


def get_holiday_days(employees, month, year):
	"""holiday_list -> {day: True if it is a WEEKLY OFF, False if a real holiday}.

	The distinction is `Holiday.weekly_off`, which is what lets H and WO be told
	apart at all.
	"""
	holiday_lists = {e["holiday_list"] for e in employees if e.get("holiday_list")}
	if not holiday_lists:
		return {}

	rows = frappe.db.sql(
		"""
		SELECT h.parent AS holiday_list, DAY(h.holiday_date) AS day, h.weekly_off AS weekly_off
		FROM `tabHoliday` h
		WHERE h.parent IN %(holiday_lists)s
			AND MONTH(h.holiday_date) = %(month)s
			AND YEAR(h.holiday_date) = %(year)s
		""",
		{"holiday_lists": list(holiday_lists), "month": month, "year": year},
		as_dict=True,
	)

	mapping: dict[str, dict] = {}
	for row in rows:
		mapping.setdefault(row["holiday_list"], {})[row["day"]] = bool(cint(row["weekly_off"]))
	return mapping


def is_casual(leave_type: str | None) -> bool:
	"""Casual leave, however it happens to be spelt on this site."""
	return bool(leave_type) and "casual" in leave_type.lower()


def get_data(filters, month, year, days):
	employees = get_employees(filters)
	if not employees:
		return []

	attendance = get_attendance(filters, month, year)
	holiday_map = get_holiday_days(employees, month, year)

	by_employee: dict[str, list[dict]] = {}
	for record in attendance:
		by_employee.setdefault(record["employee"], []).append(record)

	rows = []
	for employee in employees:
		records = by_employee.get(employee["employee"], [])
		if not records and not cint(filters.get("show_employees_without_attendance")):
			continue
		rows.append(build_row(employee, records, holiday_map, days))
	return rows


def build_row(employee, records, holiday_map, days):
	holidays = holiday_map.get(employee.get("holiday_list"), {})

	row = {
		"employee": employee["employee"],
		"employee_name": employee["employee_name"],
		"designation": employee["designation"],
		"branch": employee["branch"],
		"total_present": 0.0,
		"total_absent": 0.0,
		"total_leave": 0.0,
		"total_casual": 0.0,
		"total_half_day": 0.0,
		"total_holiday": 0.0,
		"total_week_off": 0.0,
	}

	marked_days = set()
	for record in records:
		day = record["day"]
		marked_days.add(day)
		status = record["status"]

		if status == "On Leave" and is_casual(record.get("leave_type")):
			row[f"day_{day}"] = CASUAL_LEAVE_CODE
			row["total_casual"] += 1
		else:
			row[f"day_{day}"] = STATUS_CODE.get(status, status[:1])
			if status in ("Present", "Work From Home"):
				row["total_present"] += 1
			elif status == "Absent":
				row["total_absent"] += 1
			elif status == "On Leave":
				row["total_leave"] += 1
			elif status == "Half Day":
				row["total_half_day"] += 1

	# Days with no attendance record: a holiday or weekly off if the calendar says
	# so, otherwise genuinely unmarked — and an unmarked day is what payroll reads
	# as absent, so it is counted and shown rather than left blank and forgotten.
	for day in range(1, days + 1):
		if day in marked_days:
			continue
		if day in holidays:
			if holidays[day]:
				row[f"day_{day}"] = WEEK_OFF_CODE
				row["total_week_off"] += 1
			else:
				row[f"day_{day}"] = HOLIDAY_CODE
				row["total_holiday"] += 1
		else:
			row[f"day_{day}"] = ""

	row["total_unmarked"] = flt(
		days - len(marked_days) - row["total_holiday"] - row["total_week_off"], 1
	)
	return row


def get_report_summary(data, filters, month, year):
	if not data:
		return None

	summary = [
		{"label": _("Employees"), "value": len(data), "datatype": "Int"},
		{"label": _("Present (P)"), "value": flt(sum(r["total_present"] for r in data), 1),
		 "datatype": "Float"},
		{"label": _("Absent (A)"), "value": flt(sum(r["total_absent"] for r in data), 1),
		 "datatype": "Float"},
		{"label": _("Casual Leave (CL)"), "value": flt(sum(r["total_casual"] for r in data), 1),
		 "datatype": "Float"},
		{"label": _("Unmarked"), "value": flt(sum(r["total_unmarked"] for r in data), 1),
		 "datatype": "Float"},
	]

	# 🔴 Say it out loud when the holiday calendar cannot answer. Silently
	# printing a blank WO column looks like "nobody had a day off", which is a
	# very different statement from "the calendar does not cover this month".
	# Warn on each separately. The first cut tested their SUM, so a month with a
	# public holiday but no weekly offs configured looked fine — and WO was blank
	# for all 106 employees with nothing saying why.
	if not sum(r["total_week_off"] for r in data):
		summary.append(
			{
				"label": _("WO unavailable"),
				"value": _("no weekly off in the holiday list for this month"),
				"datatype": "Data",
				"indicator": "Red",
			}
		)
	if not sum(r["total_holiday"] for r in data):
		summary.append(
			{
				"label": _("H unavailable"),
				"value": _("no holiday in the holiday list for this month"),
				"datatype": "Data",
				"indicator": "Orange",
			}
		)
	return summary
