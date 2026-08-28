# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt
"""Route an Employee Advance to the right approval path.

The client asked for "a separate route advance adding option for drivers and
marketing Team". The route is stamped on the document from the employee's
designation so a Workflow can branch on a single field rather than repeating the
designation list in every transition condition.

Note for whoever configures the Workflow: there is no Marketing designation on
this site yet. The list in the patch already includes the likely names, so the
routing starts working the day one is created — no code change needed.
"""

import frappe

from enfono_hr.patches.v1_0.setup_payroll_rules import SEPARATE_ROUTE_DESIGNATIONS


def set_approval_route(doc, method=None):
	"""Stamp ``custom_advance_route`` before the advance is saved."""
	if not hasattr(doc, "custom_advance_route"):
		return

	designation = frappe.db.get_value("Employee", doc.employee, "designation")
	doc.custom_advance_route = (
		"Driver & Marketing" if designation in SEPARATE_ROUTE_DESIGNATIONS else "Standard"
	)
