# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt
"""Shared helpers for the Enfono HR report pack.

Every report in ``enfono_hr/enfono_hr/report`` builds its WHERE clause through
:func:`employee_conditions` so that scoping, permissions and parameter binding
stay consistent. Values are always bound as ``%(name)s`` parameters — never
interpolated into the SQL string.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, getdate, today

#: Minutes an employee may be late / leave early before it counts as an occurrence.
DEFAULT_GRACE_MINUTES = 15

#: Employee columns every report in the pack shares, in the order the client asked for.
EMPLOYEE_COLUMNS = [
	{
		"label": _("Employee ID"),
		"fieldname": "employee",
		"fieldtype": "Link",
		"options": "Employee",
		"width": 120,
	},
	{"label": _("Employee Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 180},
	{
		"label": _("Designation"),
		"fieldname": "designation",
		"fieldtype": "Link",
		"options": "Designation",
		"width": 150,
	},
	{
		"label": _("Department"),
		"fieldname": "department",
		"fieldtype": "Link",
		"options": "Department",
		"width": 150,
	},
	{"label": _("Branch"), "fieldname": "branch", "fieldtype": "Link", "options": "Branch", "width": 150},
]

# Filter name -> Employee column it maps to. Fixed map, so the column name can
# never come from user input.
_EMPLOYEE_FILTER_MAP = {
	"employee": "name",
	"branch": "branch",
	"department": "department",
	"designation": "designation",
	"company": "company",
}


def get_user_branch(user: str | None = None) -> str | None:
	"""Branch of the Employee record linked to ``user``, if there is one."""
	return frappe.db.get_value("Employee", {"user_id": user or frappe.session.user}, "branch")


def resolve_branch(filters: dict) -> str | None:
	"""Explicit branch filter wins; otherwise fall back to the viewer's own branch.

	System Manager and HR Manager see every branch when they leave the filter
	blank — everyone else is scoped to their own, matching how the site's
	existing check-in reports behave.
	"""
	if filters.get("branch"):
		return filters["branch"]

	roles = set(frappe.get_roles())
	if roles & {"System Manager", "HR Manager", "Administrator"}:
		return None

	return get_user_branch()


def employee_conditions(filters: dict, alias: str = "emp") -> tuple[str, dict]:
	"""Build the shared employee WHERE fragment and its bound parameters.

	Returns a ``(sql, params)`` pair. ``alias`` and the column names come from a
	fixed internal map, so nothing user-supplied ever reaches the SQL string.
	"""
	conditions: list[str] = []
	params: dict = {}

	scoped = dict(filters or {})
	scoped["branch"] = resolve_branch(scoped)

	for key, column in _EMPLOYEE_FILTER_MAP.items():
		value = scoped.get(key)
		if value:
			conditions.append(f"AND {alias}.{column} = %({key})s")
			params[key] = value

	if not cint(scoped.get("include_inactive")):
		conditions.append(f"AND {alias}.status = %(employee_status)s")
		params["employee_status"] = "Active"

	return " ".join(conditions), params


def date_range(filters: dict, default_from=None, default_to=None) -> tuple[str, str]:
	"""Normalised ``(from_date, to_date)``, defaulting to today when unset."""
	from_date = getdate(filters.get("from_date") or default_from or today())
	to_date = getdate(filters.get("to_date") or default_to or from_date)

	if from_date > to_date:
		frappe.throw(_("From Date cannot be after To Date"))

	return str(from_date), str(to_date)


def grace_minutes(filters: dict) -> int:
	"""Grace period from the filter, falling back to the company-wide default."""
	value = filters.get("grace_period")
	return cint(value) if value not in (None, "") else DEFAULT_GRACE_MINUTES


def tomorrow() -> str:
	return str(add_days(getdate(today()), 1))


def yesterday() -> str:
	return str(add_days(getdate(today()), -1))


def format_minutes(minutes) -> str:
	"""Render a minute count as ``2h 15m`` / ``45m`` for a human reading a report."""
	minutes = cint(minutes)
	if minutes <= 0:
		return ""

	hours, mins = divmod(minutes, 60)
	if hours and mins:
		return f"{hours}h {mins}m"
	if hours:
		return f"{hours}h"
	return f"{mins}m"


#: Clock time the nightly Auto Check-Out job stamps on the rows it creates.
AUTO_CHECKOUT_TIME = "23:00:00"


def auto_checkout_predicate(alias: str = "eci") -> str:
	"""SQL predicate matching a checkout the nightly Auto Check-Out job invented.

	The job stamps a 23:00 OUT at lat/long ``0.0`` for anyone who forgot to check
	out. Those rows must never be read as a real early exit, and must never hide
	a genuinely missing checkout.

	Rows created from the point ``custom_is_auto_checkout`` shipped carry the flag
	directly. Older rows predate it, so the historical signature is matched too —
	that combination (exactly 23:00:00 at the null island) does not occur in
	organic check-out data here.

	``alias`` is supplied by calling reports, never by user input.
	"""
	signature = (
		f"(TIME({alias}.time) = '{AUTO_CHECKOUT_TIME}'"
		f" AND {alias}.latitude = '0.0' AND {alias}.longitude = '0.0')"
	)

	if frappe.db.has_column("Employee Checkin", "custom_is_auto_checkout"):
		return f"({alias}.custom_is_auto_checkout = 1 OR {signature})"

	return signature


#: SQL expression for the datetime a shift starts on a given attendance date.
SHIFT_START_EXPR = "TIMESTAMP(att.attendance_date, st.start_time)"

#: SQL expression for the datetime a shift ends, rolling to the next day for
#: overnight shifts (end_time earlier in the clock than start_time).
SHIFT_END_EXPR = """
	CASE
		WHEN st.end_time > st.start_time
			THEN TIMESTAMP(att.attendance_date, st.end_time)
		ELSE TIMESTAMP(DATE_ADD(att.attendance_date, INTERVAL 1 DAY), st.end_time)
	END
"""
