# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt
"""Apply the unambiguous parts of the client's HRMS FEEDBACK document.

Two items only. The rest of that document either needs a decision from Inlite
(the overtime-to-late-entry offset, the three factory shift timings) or is a
request for a proposal, and none of that belongs in a patch.

1. Area Sales Officers are the "marketing team".
   The feedback answers a question that had been open since the original spec:
   "Marketing Team - Area Sales Officers (ASOs)". The advance approval route
   already branches on designation, but its list was guessing at names
   ("Marketing Executive", "Marketing") that do not exist on this site. There
   are 6 active Area Sales Officers.

2. The seven daily-wage staff at Chelambra.
   🔴 Every name in the feedback is spelt differently from the Employee record.
   The mapping below was resolved against the Chelambra roster and is recorded
   here explicitly so it can be checked by a human rather than re-derived by
   fuzzy matching later:

       Feedback          Employee record        ID
       Kamarunnisa    -> Kamarunnesa K          ILF00101
       Bindhu KC      -> Bindu K C              ILF00172
       Bindu C        -> Bindhu C               ILF00090
       Sreejitha      -> Sreejisha M            ILF00173
       Safeera        -> Safeera                ILF00088
       Rajani         -> Rajani                 ILF00091
       Sarada         -> Sarada  V P            ILF00170

   Note "Bindhu KC" and "Bindu C" are two different people whose names differ
   only by the K, and the feedback spells the h in the opposite place from the
   system for both. The K C / C suffix is what distinguishes them.

   🔴 Sarada V P is recorded as MALE. The original specification said
   "Chelembra Factory Female Employees Are Daily-Wage workers", so a rule keyed
   on gender would have paid this employee as salaried staff. This is the
   concrete case that justifies wage type being a per-employee setting.

Employees are matched by ID, not by name. A name-matched patch would silently
skip anyone renamed and, worse, could match the wrong person.
"""

import frappe

from enfono_hr.patches.v1_0.setup_payroll_rules import SEPARATE_ROUTE_DESIGNATIONS

# (employee_id, expected_name_fragment) — the fragment is a guard, not a lookup.
DAILY_WAGE_STAFF = [
	("ILF00101", "Kamarunnesa"),
	("ILF00172", "Bindu K C"),
	("ILF00090", "Bindhu C"),
	("ILF00173", "Sreejisha"),
	("ILF00088", "Safeera"),
	("ILF00091", "Rajani"),
	("ILF00170", "Sarada"),
]

DAILY_RATE = 300.0
WEEKLY_OFF_RATE = 400.0


def execute():
	_backfill_advance_routes()
	_set_daily_wage_staff()
	frappe.db.commit()


def _backfill_advance_routes():
	"""Re-stamp existing advances now that Area Sales Officer is on the route list.

	The route list is a Python constant (SEPARATE_ROUTE_DESIGNATIONS), not a
	settings field, so adding the designation only affects documents saved from
	now on. Existing advances keep whatever route they were stamped with, which
	means every ASO advance already on the system still reads "Standard".
	"""
	if not frappe.db.has_column("Employee Advance", "custom_advance_route"):
		frappe.logger().info("enfono_hr: custom_advance_route missing — backfill skipped")
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
	frappe.logger().info("enfono_hr: advance routes re-stamped")


def _set_daily_wage_staff():
	"""Mark the seven Chelambra daily-wage employees, with their rates."""
	if not frappe.db.has_column("Employee", "custom_wage_type"):
		frappe.logger().info("enfono_hr: custom_wage_type missing — daily wage skipped")
		return

	for emp_id, expect in DAILY_WAGE_STAFF:
		name = frappe.db.get_value("Employee", emp_id, "employee_name")
		if not name:
			# Never guess a replacement. A missing ID is a data question for a
			# human, not something a patch should resolve by searching names.
			frappe.logger().info(f"enfono_hr: employee {emp_id} not found — skipped")
			continue

		if expect.lower() not in name.lower():
			# The ID exists but holds someone else. Setting a wage type on the
			# wrong person changes their pay, so stop rather than proceed.
			frappe.logger().info(
				f"enfono_hr: {emp_id} is {name!r}, expected {expect!r} — skipped, needs review"
			)
			continue

		frappe.db.set_value(
			"Employee",
			emp_id,
			{
				"custom_wage_type": "Daily Wage",
				"custom_daily_wage_rate": DAILY_RATE,
				"custom_sunday_wage_rate": WEEKLY_OFF_RATE,
			},
			update_modified=False,
		)
		frappe.logger().info(f"enfono_hr: {emp_id} {name} -> Daily Wage")
