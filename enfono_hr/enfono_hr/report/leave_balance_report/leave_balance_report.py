# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt
"""Leave balance per employee per leave type, with Designation and Branch.

HRMS already ships ``Employee Leave Balance``. This report exists because the
client's spec needs Designation and Branch columns and branch scoping, which
that report does not carry — and because the site currently has four competing
hand-rolled balance reports that disagree with each other.

The ledger arithmetic itself is *not* reimplemented. Opening balance, allocation,
expiry and carry-forward all come from HRMS's own helpers, so this report agrees
with the standard one by construction and keeps agreeing across HRMS upgrades.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, today

from hrms.hr.doctype.leave_application.leave_application import get_leaves_for_period
from hrms.hr.report.employee_leave_balance.employee_leave_balance import (
	get_allocated_and_expired_leaves,
	get_opening_balance,
)

from enfono_hr.hr_report_utils import EMPLOYEE_COLUMNS, date_range, employee_conditions


def execute(filters=None):
	filters = frappe._dict(filters or {})
	filters.from_date, filters.to_date = date_range(
		filters,
		default_from=str(getdate(today()).replace(month=1, day=1)),
		default_to=today(),
	)

	data = get_data(filters)
	return get_columns(), data, None, None, get_report_summary(data)


def get_columns():
	return EMPLOYEE_COLUMNS + [
		{
			"label": _("Leave Type"),
			"fieldname": "leave_type",
			"fieldtype": "Link",
			"options": "Leave Type",
			"width": 150,
		},
		{
			"label": _("Opening Balance"),
			"fieldname": "opening_balance",
			"fieldtype": "Float",
			"width": 140,
		},
		{"label": _("Allocated"), "fieldname": "allocated", "fieldtype": "Float", "width": 110},
		{
			"label": _("Carry Forwarded"),
			"fieldname": "carry_forwarded",
			"fieldtype": "Float",
			"width": 140,
		},
		{"label": _("Taken"), "fieldname": "taken", "fieldtype": "Float", "width": 100},
		{"label": _("Expired"), "fieldname": "expired", "fieldtype": "Float", "width": 100},
		{
			"label": _("Closing Balance"),
			"fieldname": "closing_balance",
			"fieldtype": "Float",
			"width": 140,
		},
	]


def get_employees(filters):
	emp_conditions, params = employee_conditions(filters)

	return frappe.db.sql(
		f"""
		SELECT
			emp.name            AS employee,
			emp.employee_name   AS employee_name,
			emp.designation     AS designation,
			emp.department      AS department,
			emp.branch          AS branch
		FROM `tabEmployee` emp
		WHERE 1 = 1
			{emp_conditions}
		ORDER BY emp.branch, emp.department, emp.employee_name
		""",
		params,
		as_dict=True,
	)


def get_leave_types(filters):
	if filters.get("leave_type"):
		return [filters.get("leave_type")]

	return frappe.get_all("Leave Type", pluck="name", order_by="name")


def get_data(filters):
	employees = get_employees(filters)
	if not employees:
		return []

	leave_types = get_leave_types(filters)
	hide_empty = not cint(filters.get("show_zero_balance_rows"))
	rows = []

	for employee in employees:
		for leave_type in leave_types:
			row = build_row(employee, leave_type, filters)
			if hide_empty and not any(
				flt(row[key])
				for key in ("opening_balance", "allocated", "carry_forwarded", "taken", "expired")
			):
				continue

			rows.append(row)

	return rows


def build_row(employee, leave_type, filters):
	"""One employee × leave-type line, using HRMS's ledger helpers throughout."""
	allocated, expired, carry_forwarded = get_allocated_and_expired_leaves(
		filters.from_date, filters.to_date, employee["employee"], leave_type
	)
	opening = get_opening_balance(employee["employee"], leave_type, filters, carry_forwarded)

	# get_leaves_for_period returns a negative number for consumed leave.
	taken = get_leaves_for_period(
		employee["employee"], leave_type, filters.from_date, filters.to_date
	)
	taken = abs(flt(taken))

	return {
		**employee,
		"leave_type": leave_type,
		"opening_balance": flt(opening, 2),
		"allocated": flt(allocated, 2),
		"carry_forwarded": flt(carry_forwarded, 2),
		"taken": flt(taken, 2),
		"expired": flt(expired, 2),
		"closing_balance": flt(
			flt(opening) + flt(allocated) - flt(expired) - flt(taken), 2
		),
	}


def get_report_summary(data):
	if not data:
		return None

	return [
		{
			"label": _("Employees"),
			"value": len({row["employee"] for row in data}),
			"datatype": "Int",
		},
		{
			"label": _("Total Leaves Taken"),
			"value": flt(sum(row["taken"] for row in data), 2),
			"datatype": "Float",
		},
		{
			"label": _("Total Closing Balance"),
			"value": flt(sum(row["closing_balance"] for row in data), 2),
			"datatype": "Float",
		},
	]
