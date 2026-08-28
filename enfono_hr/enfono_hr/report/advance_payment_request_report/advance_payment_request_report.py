# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt
"""Employee advances with their outstanding balance and approval route.

The client asked for an "Advance Payment Request List/Report" and for drivers
and the marketing team to follow a separate route. The route column is what a
Workflow branches on, so this report doubles as the queue each approver works
from — filter by route, act on what is pending.
"""

import frappe
from frappe import _
from frappe.utils import flt

from enfono_hr.hr_report_utils import EMPLOYEE_COLUMNS, employee_conditions


def execute(filters=None):
	filters = frappe._dict(filters or {})
	data = get_data(filters)
	return get_columns(), data, None, None, get_report_summary(data)


def get_columns():
	return EMPLOYEE_COLUMNS + [
		{
			"label": _("Advance"),
			"fieldname": "advance",
			"fieldtype": "Link",
			"options": "Employee Advance",
			"width": 150,
		},
		{"label": _("Posting Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 110},
		{"label": _("Approval Route"), "fieldname": "advance_route", "fieldtype": "Data", "width": 150},
		{"label": _("Purpose"), "fieldname": "purpose", "fieldtype": "Data", "width": 200},
		{
			"label": _("Advance Amount"),
			"fieldname": "advance_amount",
			"fieldtype": "Currency",
			"width": 130,
		},
		{"label": _("Paid"), "fieldname": "paid_amount", "fieldtype": "Currency", "width": 110},
		{"label": _("Claimed"), "fieldname": "claimed_amount", "fieldtype": "Currency", "width": 110},
		{"label": _("Returned"), "fieldname": "return_amount", "fieldtype": "Currency", "width": 110},
		{"label": _("Outstanding"), "fieldname": "outstanding", "fieldtype": "Currency", "width": 130},
		{
			"label": _("Recover From Salary"),
			"fieldname": "repay_unclaimed_amount_from_salary",
			"fieldtype": "Check",
			"width": 160,
		},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 110},
	]


def get_data(filters):
	emp_conditions, params = employee_conditions(filters)

	date_condition = ""
	if filters.get("from_date") and filters.get("to_date"):
		date_condition = "AND adv.posting_date BETWEEN %(from_date)s AND %(to_date)s"
		params.update({"from_date": filters["from_date"], "to_date": filters["to_date"]})

	status_condition = ""
	if filters.get("status"):
		status_condition = "AND adv.status = %(status)s"
		params["status"] = filters["status"]

	route_condition = ""
	has_route = frappe.db.has_column("Employee Advance", "custom_advance_route")
	route_select = "adv.custom_advance_route" if has_route else "'Standard'"

	if has_route and filters.get("advance_route"):
		route_condition = "AND adv.custom_advance_route = %(advance_route)s"
		params["advance_route"] = filters["advance_route"]

	rows = frappe.db.sql(
		f"""
		SELECT
			emp.name            AS employee,
			emp.employee_name   AS employee_name,
			emp.designation     AS designation,
			emp.department      AS department,
			emp.branch          AS branch,
			adv.name            AS advance,
			adv.posting_date    AS posting_date,
			{route_select}      AS advance_route,
			adv.purpose         AS purpose,
			adv.advance_amount  AS advance_amount,
			adv.paid_amount     AS paid_amount,
			adv.claimed_amount  AS claimed_amount,
			adv.return_amount   AS return_amount,
			adv.repay_unclaimed_amount_from_salary AS repay_unclaimed_amount_from_salary,
			adv.status          AS status
		FROM `tabEmployee Advance` adv
		INNER JOIN `tabEmployee` emp ON emp.name = adv.employee
		WHERE adv.docstatus < 2
			{date_condition}
			{status_condition}
			{route_condition}
			{emp_conditions}
		ORDER BY adv.posting_date DESC, emp.employee_name
		""",
		params,
		as_dict=True,
	)

	for row in rows:
		row["outstanding"] = flt(
			flt(row["paid_amount"]) - flt(row["claimed_amount"]) - flt(row["return_amount"]), 2
		)

	return rows


def get_report_summary(data):
	if not data:
		return None

	return [
		{"label": _("Advances"), "value": len(data), "datatype": "Int"},
		{
			"label": _("Total Outstanding"),
			"value": flt(sum(row["outstanding"] for row in data), 2),
			"datatype": "Currency",
		},
		{
			"label": _("Driver & Marketing Route"),
			"value": sum(1 for row in data if row.get("advance_route") == "Driver & Marketing"),
			"datatype": "Int",
		},
	]
