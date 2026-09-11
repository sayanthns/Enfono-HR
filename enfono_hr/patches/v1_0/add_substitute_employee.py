# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt
"""Requirement 11 — name a substitute when approving a leave.

    "While approving an Employees leave request, there should be an option to
     select/add the substitute employee name."

Two fields on Leave Application:

* ``custom_substitute_employee`` — a Link to Employee
* ``custom_substitute_employee_name`` — its fetched name, so reports and lists
  can show who is covering without a second lookup per row

🔴 ``allow_on_submit = 1`` on both. A Leave Application is submittable, and cover
is routinely arranged *after* the approval — somebody goes off sick and the
substitute is settled that afternoon. Without this flag the field is frozen the
moment the leave is submitted, which is exactly when it is most needed, and HR
would have to cancel and amend an approved leave to record a stand-in.

Deliberately optional. Making it mandatory would block every approval for staff
who need no cover at all, and the client has not said which roles need one —
that question is in the requirements response.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

FIELDS = {
	"Leave Application": [
		{
			"fieldname": "custom_substitute_section",
			"label": "Cover",
			"fieldtype": "Section Break",
			"insert_after": "leave_approver_name",
			"collapsible": 0,
		},
		{
			"fieldname": "custom_substitute_employee",
			"label": "Substitute Employee",
			"fieldtype": "Link",
			"options": "Employee",
			"insert_after": "custom_substitute_section",
			"allow_on_submit": 1,
			"description": "Who covers this person while they are away. Optional.",
		},
		{
			"fieldname": "custom_substitute_column",
			"fieldtype": "Column Break",
			"insert_after": "custom_substitute_employee",
		},
		{
			"fieldname": "custom_substitute_employee_name",
			"label": "Substitute Name",
			"fieldtype": "Data",
			"insert_after": "custom_substitute_column",
			"fetch_from": "custom_substitute_employee.employee_name",
			"read_only": 1,
			"allow_on_submit": 1,
		},
	]
}


def execute():
	create_custom_fields(FIELDS, ignore_validate=True)
	frappe.db.commit()

	# Prove the flag actually landed. create_custom_fields silently leaves an
	# existing field alone, so a field created by an earlier run without
	# allow_on_submit would stay frozen and nobody would know until an approver
	# tried to use it.
	for fieldname in ("custom_substitute_employee", "custom_substitute_employee_name"):
		name = frappe.db.get_value(
			"Custom Field", {"dt": "Leave Application", "fieldname": fieldname}, "name"
		)
		if name and not frappe.db.get_value("Custom Field", name, "allow_on_submit"):
			frappe.db.set_value("Custom Field", name, "allow_on_submit", 1)
			frappe.logger().info(f"enfono_hr: forced allow_on_submit on {fieldname}")

	frappe.db.commit()
	frappe.clear_cache(doctype="Leave Application")
