# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt
"""Dry run of the Inlite payroll rules. Computes everything, writes nothing.

This is the gate before any of these numbers become money. It shows, per
employee per month, every figure the client's salary formula needs -- gross,
LOP, fines, penalties, overtime, advance, ESI, arrears and the resulting net --
so HR can reconcile a month they have already checked by hand before the
components are wired into Salary Slip.

Deliberately read-only. It calls the same functions the eventual Salary Slip
hooks will call, so what is signed off here is what will be paid.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, today

from enfono_hr.hr_report_utils import employee_conditions
from enfono_hr.payroll_rules import (
	FINE_PER_OCCURRENCE,
	FREE_OCCURRENCES_PER_MONTH,
	compute_employee_payroll,
	month_bounds,
)
from enfono_hr.enfono_hr.report.monthly_attendance_sheet_detail.monthly_attendance_sheet_detail import (
	get_period,
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	month, year = get_period(filters)

	data = get_data(filters, year, month)
	return get_columns(), data, get_message(year, month), None, get_report_summary(data)


def get_message(year, month):
	start, end = month_bounds(year, month)
	return _(
		"<b>Dry run — nothing is written.</b> Figures cover {0} to {1}. "
		"Grace period {2} minutes, {3} free occurrence-days per month, "
		"then ₹{4} per day. Reconcile a known-good month here before these "
		"components are wired into Salary Slip."
	).format(
		frappe.format(start, "Date"),
		frappe.format(end, "Date"),
		15,
		FREE_OCCURRENCES_PER_MONTH,
		cint(FINE_PER_OCCURRENCE),
	)


def get_columns():
	def col(label, fieldname, fieldtype="Float", width=110, options=None):
		column = {
			"label": _(label),
			"fieldname": fieldname,
			"fieldtype": fieldtype,
			"width": width,
		}
		if options:
			column["options"] = options
		if fieldtype in ("Float", "Currency"):
			column["precision"] = 2
		return column

	return [
		col("Employee ID", "employee", "Link", 110, "Employee"),
		col("Employee Name", "employee_name", "Data", 170),
		col("Designation", "designation", "Link", 140, "Designation"),
		col("Branch", "branch", "Link", 150, "Branch"),
		col("Wage Type", "wage_type", "Data", 100),
		col("Base", "base", "Currency", 110),
		col("Total Days", "total_days", "Int", 90),
		col("Present", "present_days", "Float", 85),
		col("Half Day", "half_days", "Float", 85),
		col("On Leave", "leave_days", "Float", 85),
		col("LOP Days", "lop_days", "Float", 90),
		col("Gross Salary", "gross_salary", "Currency", 120),
		col("LOP Amount", "lop_amount", "Currency", 115),
		col("Gross Pay", "gross_pay", "Currency", 115),
		col("Occurrence Days", "occurrence_days", "Int", 130),
		col("Free Used", "free_days_used", "Int", 95),
		col("Fined Days", "fined_days", "Int", 100),
		col("Flat Fine", "flat_fine", "Currency", 100),
		col("Hourly Deduction", "hourly_deduction", "Currency", 140),
		col("Unapproved Absent", "unapproved_absent_days", "Int", 145),
		col("Unapproved Half Day", "unapproved_half_days", "Int", 160),
		col("Missing Checkout", "missing_checkout_days", "Int", 140),
		col("Penalty Days (Raw)", "raw_penalty_days", "Float", 145),
		col("Penalty Days", "penalty_days", "Float", 115),
		col("Capped", "penalty_days_capped", "Check", 80),
		col("Penalty Amount", "penalty_amount", "Currency", 130),
		col("Fine Total", "fine_total", "Currency", 110),
		col("OT Hours", "ot_hours", "Float", 95),
		col("OT Amount", "ot_amount", "Currency", 110),
		col("Sundays Worked", "sunday_days_worked", "Int", 130),
		col("Sunday Amount", "sunday_amount", "Currency", 125),
		col("Total OT", "total_overtime", "Currency", 110),
		col("Advance", "advance_amount", "Currency", 105),
		col("ESI", "esi_amount", "Currency", 95),
		col("Arrears", "arrear_amount", "Currency", 105),
		col("Total Deductions", "total_deductions", "Currency", 140),
		col("Net (Uncapped)", "uncapped_net", "Currency", 135),
		col("Excess Deduction", "excess_deduction", "Currency", 145),
		col("Net Salary", "net_salary", "Currency", 130),
	]


def get_employees(filters):
	emp_conditions, params = employee_conditions(filters)

	return frappe.db.sql(
		f"""
		SELECT
			emp.name            AS name,
			emp.employee_name   AS employee_name,
			emp.designation     AS designation,
			emp.department      AS department,
			emp.branch          AS branch,
			emp.company         AS company
		FROM `tabEmployee` emp
		WHERE 1 = 1
			{emp_conditions}
		ORDER BY emp.branch, emp.employee_name
		""",
		params,
		as_dict=True,
	)


def get_data(filters, year, month):
	employees = get_employees(filters)
	if not employees:
		return []

	attach_wage_fields(employees)

	rows = []
	for employee in employees:
		row = compute_employee_payroll(employee, year, month)
		row.pop("daily_wage_detail", None)

		if not cint(filters.get("show_zero_rows")) and not row["base"] and not row["gross_salary"]:
			continue

		rows.append(row)

	return rows


def attach_wage_fields(employees):
	"""Read the daily-wage fields if the customisation has been applied yet.

	The report has to work before and after the wage-type patch lands, so the
	columns are probed rather than assumed.
	"""
	wage_columns = [
		column
		for column in ("custom_wage_type", "custom_daily_wage_rate", "custom_sunday_wage_rate")
		if frappe.db.has_column("Employee", column)
	]

	if not wage_columns:
		return

	names = [employee["name"] for employee in employees]
	records = frappe.get_all(
		"Employee", filters={"name": ["in", names]}, fields=["name", *wage_columns]
	)
	by_name = {record["name"]: record for record in records}

	for employee in employees:
		employee.update(by_name.get(employee["name"], {}))


def get_report_summary(data):
	if not data:
		return None

	return [
		{"label": _("Employees"), "value": len(data), "datatype": "Int"},
		{
			"label": _("Total Fines"),
			"value": flt(sum(row["fine_total"] for row in data), 2),
			"datatype": "Currency",
		},
		{
			"label": _("Total Overtime"),
			"value": flt(sum(row["total_overtime"] for row in data), 2),
			"datatype": "Currency",
		},
		{
			"label": _("Capped Rows"),
			"value": sum(1 for row in data if row.get("penalty_days_capped")),
			"datatype": "Int",
		},
		{
			"label": _("Excess Deduction Not Applied"),
			"value": flt(sum(row["excess_deduction"] for row in data), 2),
			"datatype": "Currency",
		},
		{
			"label": _("Total Net Salary"),
			"value": flt(sum(row["net_salary"] for row in data), 2),
			"datatype": "Currency",
		},
	]
