# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt
"""Month-at-a-glance attendance grid, one row per employee, one column per day.

HRMS ships ``Monthly Attendance Sheet``. This one exists because the client's
sheet has to carry Designation and Branch, count late entries and early exits
against the 15-minute rule, and total the payroll-relevant days (Present,
Absent, Half Day, On Leave) in the same view HR signs off from.

Day cells use single-letter codes so a 31-column grid stays readable:

===  ===============
``P``  Present
``A``  Absent
``H``  Half Day
``L``  On Leave
``W``  Work From Home
``O``  Holiday / weekly off
===  ===============

An empty cell means no attendance was marked at all — which is itself worth
seeing, since Payroll Settings treat unmarked days as Absent.
"""

import calendar

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, today

from enfono_hr.hr_report_utils import (
	SHIFT_END_EXPR,
	SHIFT_START_EXPR,
	employee_conditions,
	grace_minutes,
)

STATUS_CODE = {
	"Present": "P",
	"Absent": "A",
	"Half Day": "H",
	"On Leave": "L",
	"Work From Home": "W",
}


def execute(filters=None):
	filters = frappe._dict(filters or {})
	month, year = get_period(filters)
	days = calendar.monthrange(year, month)[1]

	data = get_data(filters, month, year, days)
	return get_columns(days), data, None, None, get_report_summary(data)


#: The filter is a Select of month names; API callers may pass a number instead.
MONTH_NUMBERS = {name: index for index, name in enumerate(calendar.month_name) if name}


def get_period(filters):
	todays_date = getdate(today())

	raw_month = filters.get("month")
	if not raw_month:
		month = todays_date.month
	elif isinstance(raw_month, str) and raw_month.strip().capitalize() in MONTH_NUMBERS:
		month = MONTH_NUMBERS[raw_month.strip().capitalize()]
	else:
		month = cint(raw_month)

	year = cint(filters.get("year") or todays_date.year)

	if not 1 <= month <= 12:
		frappe.throw(_("Please select a valid month"))
	if year < 1900:
		frappe.throw(_("Please select a valid year"))

	return month, year


def get_columns(days):
	columns = [
		{
			"label": _("Employee ID"),
			"fieldname": "employee",
			"fieldtype": "Link",
			"options": "Employee",
			"width": 110,
		},
		{"label": _("Employee Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 170},
		{
			"label": _("Designation"),
			"fieldname": "designation",
			"fieldtype": "Link",
			"options": "Designation",
			"width": 130,
		},
		{
			"label": _("Department"),
			"fieldname": "department",
			"fieldtype": "Link",
			"options": "Department",
			"width": 130,
		},
		{
			"label": _("Branch"),
			"fieldname": "branch",
			"fieldtype": "Link",
			"options": "Branch",
			"width": 140,
		},
	]

	columns += [
		{"label": str(day), "fieldname": f"day_{day}", "fieldtype": "Data", "width": 45}
		for day in range(1, days + 1)
	]

	columns += [
		{"label": _("Present"), "fieldname": "total_present", "fieldtype": "Float", "width": 85},
		{"label": _("Absent"), "fieldname": "total_absent", "fieldtype": "Float", "width": 80},
		{"label": _("Half Day"), "fieldname": "total_half_day", "fieldtype": "Float", "width": 90},
		{"label": _("On Leave"), "fieldname": "total_leave", "fieldtype": "Float", "width": 90},
		{"label": _("Unmarked"), "fieldname": "total_unmarked", "fieldtype": "Int", "width": 95},
		{"label": _("Late Entries"), "fieldname": "late_entries", "fieldtype": "Int", "width": 110},
		{"label": _("Early Exits"), "fieldname": "early_exits", "fieldtype": "Int", "width": 105},
		{"label": _("Payable Days"), "fieldname": "payable_days", "fieldtype": "Float", "width": 115},
	]

	return columns


def get_employees(filters):
	emp_conditions, params = employee_conditions(filters)

	return frappe.db.sql(
		f"""
		SELECT
			emp.name            AS employee,
			emp.employee_name   AS employee_name,
			emp.designation     AS designation,
			emp.department      AS department,
			emp.branch          AS branch,
			emp.holiday_list    AS holiday_list,
			emp.default_shift   AS default_shift
		FROM `tabEmployee` emp
		WHERE 1 = 1
			{emp_conditions}
		ORDER BY emp.branch, emp.department, emp.employee_name
		""",
		params,
		as_dict=True,
	)


def get_attendance(filters, month, year):
	emp_conditions, params = employee_conditions(filters)
	params.update({"month": month, "year": year, "grace": grace_minutes(filters)})

	return frappe.db.sql(
		f"""
		SELECT
			att.employee        AS employee,
			DAY(att.attendance_date) AS day,
			att.status          AS status,
			CASE
				WHEN att.in_time IS NOT NULL AND st.name IS NOT NULL
					AND TIMESTAMPDIFF(MINUTE, {SHIFT_START_EXPR}, att.in_time) > %(grace)s
				THEN 1 ELSE 0
			END AS is_late,
			CASE
				WHEN att.out_time IS NOT NULL AND st.name IS NOT NULL
					AND TIMESTAMPDIFF(MINUTE, att.out_time, {SHIFT_END_EXPR}) > %(grace)s
				THEN 1 ELSE 0
			END AS is_early
		FROM `tabAttendance` att
		INNER JOIN `tabEmployee` emp ON emp.name = att.employee
		LEFT JOIN `tabShift Type` st ON st.name = COALESCE(att.shift, emp.default_shift)
		WHERE att.docstatus = 1
			AND MONTH(att.attendance_date) = %(month)s
			AND YEAR(att.attendance_date) = %(year)s
			{emp_conditions}
		""",
		params,
		as_dict=True,
	)


def get_holiday_days(employees, month, year):
	"""Map holiday_list -> set of day numbers that are holidays in this month."""
	holiday_lists = {emp["holiday_list"] for emp in employees if emp.get("holiday_list")}
	if not holiday_lists:
		return {}

	holidays = frappe.db.sql(
		"""
		SELECT h.parent AS holiday_list, DAY(h.holiday_date) AS day
		FROM `tabHoliday` h
		WHERE h.parent IN %(holiday_lists)s
			AND MONTH(h.holiday_date) = %(month)s
			AND YEAR(h.holiday_date) = %(year)s
		""",
		{"holiday_lists": list(holiday_lists), "month": month, "year": year},
		as_dict=True,
	)

	mapping: dict[str, set] = {}
	for holiday in holidays:
		mapping.setdefault(holiday["holiday_list"], set()).add(holiday["day"])

	return mapping


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
	holidays = holiday_map.get(employee.get("holiday_list"), set())

	row = {
		"employee": employee["employee"],
		"employee_name": employee["employee_name"],
		"designation": employee["designation"],
		"department": employee["department"],
		"branch": employee["branch"],
		"total_present": 0.0,
		"total_absent": 0.0,
		"total_half_day": 0.0,
		"total_leave": 0.0,
		"late_entries": 0,
		"early_exits": 0,
	}

	marked_days = set()
	for record in records:
		day = record["day"]
		marked_days.add(day)
		row[f"day_{day}"] = STATUS_CODE.get(record["status"], record["status"][:1])

		if record["status"] == "Present":
			row["total_present"] += 1
		elif record["status"] == "Work From Home":
			row["total_present"] += 1
		elif record["status"] == "Absent":
			row["total_absent"] += 1
		elif record["status"] == "Half Day":
			row["total_half_day"] += 1
		elif record["status"] == "On Leave":
			row["total_leave"] += 1

		row["late_entries"] += cint(record["is_late"])
		row["early_exits"] += cint(record["is_early"])

	for day in range(1, days + 1):
		if day in marked_days:
			continue
		row[f"day_{day}"] = "O" if day in holidays else ""

	row["total_unmarked"] = days - len(marked_days) - len(holidays - marked_days)

	# Half days count as half a payable day, matching
	# Payroll Settings.daily_wages_fraction_for_half_day = 0.5 on this site.
	row["payable_days"] = flt(row["total_present"] + (row["total_half_day"] * 0.5), 2)

	return row


def get_report_summary(data):
	if not data:
		return None

	return [
		{"label": _("Employees"), "value": len(data), "datatype": "Int"},
		{
			"label": _("Total Present Days"),
			"value": flt(sum(row["total_present"] for row in data), 1),
			"datatype": "Float",
		},
		{
			"label": _("Total Absent Days"),
			"value": flt(sum(row["total_absent"] for row in data), 1),
			"datatype": "Float",
		},
		{
			"label": _("Late Entries"),
			"value": sum(row["late_entries"] for row in data),
			"datatype": "Int",
		},
		{
			"label": _("Early Exits"),
			"value": sum(row["early_exits"] for row in data),
			"datatype": "Int",
		},
	]
