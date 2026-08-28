# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt
"""Serve the HR Handbook inside the ERP, to signed-in staff only.

The handbook states this company's own payroll policy — the grace period, the
fine, what a missing checkout costs — and quotes measured figures from its own
attendance data. That is not public information, so the page refuses Guest
rather than relying on the URL being unguessable.

🔴 THE FILENAME IS LOad-BEARING. This controller was first written as
`hr-handbook.py` beside `hr-handbook.html`. A hyphen is not valid in a Python
module name, so Frappe could not import it, skipped it in silence, and served
the full handbook to Guest with a 200. Underscores here; the pretty URL comes
from a `website_route_rules` entry in hooks.py.
"""

import frappe
from frappe import _

no_cache = 1


def get_context(context):
	if frappe.session.user == "Guest":
		# raise_exception sends the visitor to /login and comes back here after.
		frappe.throw(
			_("Please sign in to read the HR Handbook."),
			frappe.PermissionError,
		)

	context.no_cache = 1
	context.show_sidebar = False
	return context
