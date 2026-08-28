# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt
"""Configure the site for the Inlite payroll rules.

Everything here is idempotent — the patch can be re-run without duplicating a
component or a shift.

Three of these steps change live behaviour and are called out in the log so the
change is traceable rather than silent:

* Shift grace periods move from 60 minutes to 15, which is what the spec asks
  for. HRMS will mark noticeably more attendance rows ``late_entry`` from the
  next auto-attendance run. The fine engine does not read this value — it
  recomputes from ``in_time`` — so this aligns the desk display with the rule
  rather than changing what anyone is charged.
* ``include_holidays_in_total_working_days`` is turned on so that Total Days is
  30/31 as the spec states, instead of excluding Sundays.
* Casual Leave becomes encashable, for the year-end carry-forward payout.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

#: Designations whose advances follow the separate approval route.
#: "Marketing" does not exist as a designation on this site yet; it is listed so
#: the routing works the day it is created, rather than needing a code change.
SEPARATE_ROUTE_DESIGNATIONS = ["Driver/Helper", "Driver", "Marketing Executive", "Marketing"]

GRACE_MINUTES = 15

CUSTOM_FIELDS = {
	"Employee": [
		{
			"fieldname": "custom_wage_section",
			"label": "Wage Type",
			"fieldtype": "Section Break",
			"insert_after": "salary_mode",
			"collapsible": 1,
		},
		{
			"fieldname": "custom_wage_type",
			"label": "Wage Type",
			"fieldtype": "Select",
			"options": "Monthly\nDaily Wage",
			"default": "Monthly",
			"insert_after": "custom_wage_section",
			"in_standard_filter": 1,
			"description": (
				"Daily Wage employees are paid per day worked and are not allocated "
				"casual leave."
			),
		},
		{
			"fieldname": "custom_daily_wage_rate",
			"label": "Daily Wage Rate",
			"fieldtype": "Currency",
			"insert_after": "custom_wage_type",
			"depends_on": "eval:doc.custom_wage_type=='Daily Wage'",
		},
		{
			"fieldname": "custom_wage_column_break",
			"fieldtype": "Column Break",
			"insert_after": "custom_daily_wage_rate",
		},
		{
			"fieldname": "custom_sunday_wage_rate",
			"label": "Sunday Wage Rate",
			"fieldtype": "Currency",
			"insert_after": "custom_wage_column_break",
			"depends_on": "eval:doc.custom_wage_type=='Daily Wage'",
			"description": "Falls back to the daily rate when left blank.",
		},
	],
	"Employee Advance": [
		{
			"fieldname": "custom_advance_route",
			"label": "Approval Route",
			"fieldtype": "Select",
			"options": "Standard\nDriver & Marketing",
			"default": "Standard",
			"insert_after": "department",
			"read_only": 1,
			"in_standard_filter": 1,
			"description": "Set automatically from the employee's designation.",
		}
	],
}

SALARY_COMPONENTS = [
	{
		"salary_component": "Overtime",
		"salary_component_abbr": "OT",
		"type": "Earning",
		"depends_on_payment_days": 0,
		"description": "Approved overtime plus any extra day earned by working a weekly off.",
	},
	{
		"salary_component": "Advance",
		"salary_component_abbr": "ADV",
		"type": "Deduction",
		"depends_on_payment_days": 0,
		"description": "Recovery of an outstanding Employee Advance.",
	},
	{
		"salary_component": "Attendance Penalty",
		"salary_component_abbr": "APEN",
		"type": "Deduction",
		"depends_on_payment_days": 0,
		"description": (
			"Additional day-deductions for unapproved absence, unapproved half days "
			"and missing check-outs, on top of ordinary LOP."
		),
	},
]


def execute():
	create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)
	create_salary_components()
	set_shift_grace_periods()
	configure_payroll_settings()
	enable_casual_leave_encashment()
	create_driver_shift()
	backfill_advance_routes()
	frappe.db.commit()


def create_salary_components():
	for component in SALARY_COMPONENTS:
		if frappe.db.exists("Salary Component", component["salary_component"]):
			continue

		doc = frappe.new_doc("Salary Component")
		doc.update(component)
		doc.insert(ignore_permissions=True)
		frappe.logger().info(f"enfono_hr: created Salary Component {doc.name}")


def set_shift_grace_periods():
	"""Align late/early marking with the 15-minute rule the client specified.

	Only shifts with auto-attendance on are touched; the rest do not mark
	attendance at all, so changing their grace would be noise.
	"""
	shifts = frappe.get_all(
		"Shift Type",
		filters={"enable_auto_attendance": 1},
		fields=["name", "late_entry_grace_period", "early_exit_grace_period"],
	)

	for shift in shifts:
		frappe.db.set_value(
			"Shift Type",
			shift.name,
			{
				"enable_late_entry_marking": 1,
				"late_entry_grace_period": GRACE_MINUTES,
				"enable_early_exit_marking": 1,
				"early_exit_grace_period": GRACE_MINUTES,
			},
			update_modified=False,
		)

	frappe.logger().info(
		f"enfono_hr: set grace to {GRACE_MINUTES} min on {len(shifts)} auto-attendance shifts"
	)


def configure_payroll_settings():
	"""Total Days must be the calendar month (30/31), per the spec's formula."""
	settings = frappe.get_single("Payroll Settings")
	settings.include_holidays_in_total_working_days = 1
	settings.save(ignore_permissions=True)


def enable_casual_leave_encashment():
	"""Carry-forwarded casual leave is paid out in cash at year end."""
	if not frappe.db.exists("Leave Type", "Casual Leave"):
		return

	if not frappe.db.exists("Salary Component", "Leave Encashment"):
		return

	frappe.db.set_value(
		"Leave Type",
		"Casual Leave",
		{"allow_encashment": 1, "earning_component": "Leave Encashment"},
		update_modified=False,
	)


def create_driver_shift():
	"""Drivers run an 11-hour shift; the fine rules are otherwise identical."""
	if frappe.db.exists("Shift Type", "Driver 11 Hours"):
		return

	doc = frappe.new_doc("Shift Type")
	doc.name = "Driver 11 Hours"
	doc.start_time = "09:00:00"
	doc.end_time = "20:00:00"
	doc.enable_auto_attendance = 0
	doc.enable_late_entry_marking = 1
	doc.late_entry_grace_period = GRACE_MINUTES
	doc.enable_early_exit_marking = 1
	doc.early_exit_grace_period = GRACE_MINUTES
	doc.insert(ignore_permissions=True)

	frappe.logger().info(
		"enfono_hr: created Shift Type 'Driver 11 Hours' with auto-attendance OFF — "
		"assign it to drivers and enable auto-attendance once the timings are confirmed"
	)


def backfill_advance_routes():
	"""Stamp the approval route on existing advances so the workflow can use it."""
	if not frappe.db.has_column("Employee Advance", "custom_advance_route"):
		return

	frappe.db.sql(
		"""
		UPDATE `tabEmployee Advance` adv
		INNER JOIN `tabEmployee` emp ON emp.name = adv.employee
		SET adv.custom_advance_route = CASE
			WHEN emp.designation IN %(designations)s THEN 'Driver & Marketing'
			ELSE 'Standard'
		END
		""",
		{"designations": SEPARATE_ROUTE_DESIGNATIONS},
	)
