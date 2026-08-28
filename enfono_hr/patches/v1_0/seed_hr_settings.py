# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt
"""Seed Enfono HR Settings with the values from the client's specification.

Seeding only happens once. If somebody has already tuned the settings — which is
the entire point of the singleton — this patch leaves them alone.

The shipped defaults are the spec read literally, including a full day for a
missing checkout. That figure is known to be severe against this site's real
attendance, so the patch logs a warning pointing at the preview report rather
than quietly enabling it.
"""

import frappe

from enfono_hr.payroll_rules import DEFAULTS


def execute():
	if not frappe.db.exists("DocType", "Enfono HR Settings"):
		return

	settings = frappe.get_single("Enfono HR Settings")

	# A seeded singleton has a modified timestamp of its own once saved; use a
	# marker field instead so a re-run cannot clobber deliberate edits.
	if settings.get("grace_minutes"):
		return

	for fieldname, value in DEFAULTS.items():
		if settings.meta.has_field(fieldname):
			settings.set(fieldname, value)

	settings.flags.ignore_permissions = True
	settings.save()
	frappe.db.commit()

	frappe.logger().info(
		"enfono_hr: seeded Enfono HR Settings from the specification defaults. "
		"The missing-checkout penalty is one full day per occurrence, which is "
		"severe against real attendance here — run the Payroll Computation "
		"Preview for a full month before relying on it."
	)
