# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt
"""Inlite payroll rules — fines, penalties, overtime, advances and arrears.

Every figure the client's spec defines is computed here and nowhere else, so the
dry-run preview report and the eventual Salary Slip hooks cannot disagree.

Nothing in this module writes. It reads attendance, leave and approvals and
returns numbers. Wiring those numbers into a Salary Slip is a separate, later
step, deliberately: the preview report has to be reconciled against a month HR
has already checked by hand before any of this becomes money.

Rules implemented, per ``HRMS AUTOMATION REPORT.docx``:

* 15-minute grace on late entry and early exit.
* First 3 occurrence-days in a month are free; each one beyond that is a flat
  fine of INR 100.
* An approved Late Entry / Early Exit Request replaces the flat fine for that
  day with an hourly deduction.
* Overtime is paid at ``base / 31 / 8`` per hour (client-confirmed basis).
* Working a Sunday adds one extra day of salary.
* Unapproved full-day absence costs a second day on top of the LOP ERPNext
  already applies; an unapproved or rejected half day costs the other half; a
  missing checkout with no half-day request costs a full day.
* Daily-wage employees are paid per day worked, at a Sunday rate on Sundays,
  and receive no casual leave.
"""

import calendar

import frappe
from frappe.utils import cint, flt, get_datetime, get_first_day, get_last_day, getdate

# --- Defaults --------------------------------------------------------------------
#
# These are the values from the client's spec. They are FALLBACKS ONLY: the live
# figures come from the "Enfono HR Settings" singleton, so HR can tune policy --
# especially the missing-checkout penalty -- without a code change. The constants
# stay here so the module still behaves sensibly if the singleton is missing, and
# so the shipped defaults are readable in one place.

DEFAULTS = {
	"enable_late_early_fines": 1,
	"grace_minutes": 15,
	"free_occurrences_per_month": 3,
	"fine_per_occurrence": 100.0,
	# Attendance below this many hours is a logging artefact, not a day worked.
	# Live data has an employee who logged OUT then IN two seconds apart, marked
	# Present with both late_entry and early_exit set. Fining a double tap would
	# be indefensible.
	"min_working_hours_for_fine": 0.25,
	"enable_attendance_penalties": 1,
	"unapproved_absent_penalty_type": "Days of Salary",
	"unapproved_absent_penalty_days": 1.0,
	"unapproved_absent_penalty_amount": 0.0,
	"unapproved_half_day_penalty_type": "Days of Salary",
	"unapproved_half_day_penalty_days": 0.5,
	"unapproved_half_day_penalty_amount": 0.0,
	"missing_checkout_penalty_type": "Days of Salary",
	"missing_checkout_penalty_days": 1.0,
	"missing_checkout_penalty_amount": 0.0,
	"missing_checkout_free_days_per_month": 0,
	"cap_penalty_at_payable_days": 1,
	"max_penalty_days_per_month": 0.0,
	"floor_net_salary_at_zero": 1,
	"max_total_deduction_percent": 0.0,
	"enable_overtime": 1,
	# The spec gives two OT formulas that only agree at 31 days and an 8-hour paid
	# shift. The client confirmed this fixed basis.
	"ot_rate_days_per_month": 31,
	"ot_rate_hours_per_day": 8.0,
	"pay_extra_day_for_weekly_off": 1,
	"weekly_off_day": "Sunday",
	"default_daily_wage_rate": 300.0,
	"default_sunday_wage_rate": 400.0,
}

#: MariaDB DAYOFWEEK(): Sunday is 1.
WEEKDAY_NUMBERS = {
	"Sunday": 1,
	"Monday": 2,
	"Tuesday": 3,
	"Wednesday": 4,
	"Thursday": 5,
	"Friday": 6,
	"Saturday": 7,
}


def get_settings():
	"""Live payroll settings, falling back to the shipped defaults.

	Returns a plain dict so callers can pass it around without holding a document,
	and so a missing singleton degrades to the spec defaults rather than raising
	in the middle of a payroll run.
	"""
	values = dict(DEFAULTS)

	try:
		doc = frappe.get_cached_doc("Enfono HR Settings")
	except Exception:
		return frappe._dict(values)

	for key in DEFAULTS:
		value = doc.get(key)
		# A blank Select or an unset field should not override a sane default;
		# a deliberate 0 on a numeric field should.
		if value not in (None, ""):
			values[key] = value

	return frappe._dict(values)


def resolve_penalty(settings, prefix: str, count: float, daily_rate: float) -> float:
	"""Charge for ``count`` occurrences of one penalty kind, in rupees.

	Handles both shapes HR can choose: a number of days of salary, or a flat
	amount per occurrence. Returns money, not days, so the two are comparable.
	"""
	penalty_type = settings.get(prefix + "_penalty_type") or "None"

	if penalty_type == "Days of Salary":
		return flt(count) * flt(settings.get(prefix + "_penalty_days")) * flt(daily_rate)

	if penalty_type == "Fixed Amount":
		return flt(count) * flt(settings.get(prefix + "_penalty_amount"))

	return 0.0


def penalty_days_equivalent(settings, prefix: str, count: float) -> float:
	"""Days of salary a penalty represents, for the payable-days ceiling.

	A fixed-amount penalty contributes no days, so it is not constrained by the
	day ceiling -- the total-deduction and negative-salary guards still apply.
	"""
	if (settings.get(prefix + "_penalty_type") or "None") != "Days of Salary":
		return 0.0

	return flt(count) * flt(settings.get(prefix + "_penalty_days"))


# --- Shift helpers --------------------------------------------------------------


def resolve_shift(employee: str, shift: str | None = None):
	"""Shift for an employee, falling back to ``Employee.default_shift``.

	Most employees on this site are driven by the default rather than an explicit
	Shift Assignment, so reading only the Attendance row's shift misses them.
	"""
	shift_name = shift or frappe.db.get_value("Employee", employee, "default_shift")
	if not shift_name:
		return None

	return frappe.db.get_value(
		"Shift Type",
		shift_name,
		["name", "start_time", "end_time"],
		as_dict=True,
	)


def shift_boundary_datetime(date, shift, boundary: str):
	"""Datetime a shift starts or ends on ``date``.

	Overnight shifts (end earlier on the clock than the start, e.g. 8PM-8AM) have
	their end rolled to the following day, otherwise every night worker looks
	twelve hours early.
	"""
	date = getdate(date)
	start, end = shift.start_time, shift.end_time

	if boundary == "start":
		return get_datetime(str(date)) + start

	crosses_midnight = end <= start
	base_date = frappe.utils.add_days(date, 1) if crosses_midnight else date
	return get_datetime(str(base_date)) + end


# --- Rate helpers ---------------------------------------------------------------


def get_monthly_base_salary(employee: str, on_date) -> float:
	"""Base from the most recent Salary Structure Assignment effective on a date."""
	base = frappe.db.get_value(
		"Salary Structure Assignment",
		{
			"employee": employee,
			"docstatus": 1,
			"from_date": ["<=", getdate(on_date)],
		},
		"base",
		order_by="from_date desc",
	)
	return flt(base)


def hourly_rate_from_base(base: float, settings=None) -> float:
	"""Hourly rate. Divisors come from settings; the agreed basis is 31 and 8."""
	settings = settings or get_settings()
	days = cint(settings.ot_rate_days_per_month) or DEFAULTS["ot_rate_days_per_month"]
	hours = flt(settings.ot_rate_hours_per_day) or DEFAULTS["ot_rate_hours_per_day"]
	return flt(base) / days / hours


def daily_rate_from_base(base: float, settings=None) -> float:
	settings = settings or get_settings()
	days = cint(settings.ot_rate_days_per_month) or DEFAULTS["ot_rate_days_per_month"]
	return flt(base) / days


def month_bounds(year: int, month: int) -> tuple:
	first = getdate(f"{year}-{month:02d}-01")
	return first, get_last_day(first)


# --- Late entry / early exit ----------------------------------------------------


def get_occurrences(employee: str, start, end, settings=None) -> list[dict]:
	"""Late-entry and early-exit occurrences for one employee in a period.

	Returns one entry per (date, type). Days that look like logging artefacts, and
	checkouts invented by the nightly Auto Check-Out job, are excluded.
	"""
	rows = frappe.db.sql(
		"""
		SELECT
			att.name            AS attendance,
			att.attendance_date AS attendance_date,
			att.in_time         AS in_time,
			att.out_time        AS out_time,
			att.working_hours   AS working_hours,
			st.name             AS shift,
			st.start_time       AS start_time,
			st.end_time         AS end_time
		FROM `tabAttendance` att
		INNER JOIN `tabEmployee` emp ON emp.name = att.employee
		LEFT JOIN `tabShift Type` st ON st.name = COALESCE(att.shift, emp.default_shift)
		WHERE att.docstatus = 1
			AND att.employee = %(employee)s
			AND att.attendance_date BETWEEN %(start)s AND %(end)s
			AND att.status IN ('Present', 'Half Day', 'Work From Home')
		ORDER BY att.attendance_date
		""",
		{"employee": employee, "start": start, "end": end},
		as_dict=True,
	)

	settings = settings or get_settings()
	grace = cint(settings.grace_minutes)
	min_hours = flt(settings.min_working_hours_for_fine)

	auto_checkout_times = get_auto_checkout_times(employee, start, end)
	occurrences = []

	for row in rows:
		if not row.shift or flt(row.working_hours) < min_hours:
			continue

		if row.in_time:
			boundary = shift_boundary_datetime(row.attendance_date, row, "start")
			minutes = int((get_datetime(row.in_time) - boundary).total_seconds() // 60)
			if minutes > grace:
				occurrences.append(_occurrence(row, "Late Entry", minutes))

		if row.out_time and row.out_time not in auto_checkout_times:
			boundary = shift_boundary_datetime(row.attendance_date, row, "end")
			minutes = int((boundary - get_datetime(row.out_time)).total_seconds() // 60)
			if minutes > grace and get_datetime(row.out_time) > get_datetime(row.in_time):
				occurrences.append(_occurrence(row, "Early Exit", minutes))

	return occurrences


def _occurrence(row, occurrence_type: str, minutes: int) -> dict:
	return {
		"date": row.attendance_date,
		"type": occurrence_type,
		"minutes": minutes,
		"attendance": row.attendance,
		"shift": row.shift,
		"working_hours": flt(row.working_hours),
	}


def get_auto_checkout_times(employee: str, start, end) -> set:
	"""Checkout timestamps the nightly Auto Check-Out job invented, not the employee."""
	if not frappe.db.has_column("Employee Checkin", "custom_is_auto_checkout"):
		return set()

	rows = frappe.db.sql(
		"""
		SELECT `time`
		FROM `tabEmployee Checkin`
		WHERE employee = %(employee)s
			AND log_type = 'OUT'
			AND custom_is_auto_checkout = 1
			AND DATE(`time`) BETWEEN %(start)s AND %(end)s
		""",
		{"employee": employee, "start": start, "end": end},
	)
	return {row[0] for row in rows}


def get_approved_requests(employee: str, start, end) -> dict:
	"""Approved late/early requests, keyed by ``(date, type)``."""
	rows = frappe.get_all(
		"Late Entry Early Exit Request",
		filters={
			"employee": employee,
			"docstatus": 1,
			"status": "Approved",
			"request_date": ["between", [start, end]],
		},
		fields=["name", "request_date", "request_type", "minutes", "deduction_amount"],
	)
	return {(row.request_date, row.request_type): row for row in rows}


def compute_late_early_charges(employee: str, start, end, base: float, settings=None) -> dict:
	"""Flat fines and hourly deductions for one employee in one payroll month.

	The allowance is three *days*, not three occurrences: a day on which someone
	is both late and leaves early is one day against the allowance, which is how
	the client's worded rule reads.

	Approved days are excluded from the allowance count entirely — they are
	charged hourly instead, so an approval must not consume someone's free days.
	"""
	settings = settings or get_settings()

	if not cint(settings.enable_late_early_fines):
		return {
			"occurrences": [],
			"occurrence_days": 0,
			"approved_days": 0,
			"free_days_used": 0,
			"fined_days": 0,
			"fine_amount": 0.0,
			"hourly_deduction": 0.0,
		}

	occurrences = get_occurrences(employee, start, end, settings)
	approved = get_approved_requests(employee, start, end)

	hourly_deduction = 0.0
	approved_days = set()
	unapproved_by_day: dict = {}

	for occurrence in occurrences:
		key = (occurrence["date"], occurrence["type"])
		if key in approved:
			approved_days.add(occurrence["date"])
			hourly_deduction += flt(approved[key].deduction_amount) or flt(
				hourly_rate_from_base(base, settings) * (occurrence["minutes"] / 60.0)
			)
		else:
			unapproved_by_day.setdefault(occurrence["date"], []).append(occurrence)

	free_allowance = cint(settings.free_occurrences_per_month)
	chargeable_days = sorted(unapproved_by_day)
	fined_days = chargeable_days[free_allowance:]

	return {
		"occurrences": occurrences,
		"occurrence_days": len(unapproved_by_day) + len(approved_days),
		"approved_days": len(approved_days),
		"free_days_used": min(len(chargeable_days), free_allowance),
		"fined_days": len(fined_days),
		"fine_amount": flt(len(fined_days) * flt(settings.fine_per_occurrence), 2),
		"hourly_deduction": flt(hourly_deduction, 2),
	}


# --- Attendance penalties -------------------------------------------------------


def compute_attendance_penalties(
	employee: str, start, end, base: float, payable_days: float, settings=None
) -> dict:
	"""Extra deductions the leave rules impose on top of ordinary loss of pay.

	ERPNext already deducts for Absent and Half Day through attendance-based
	payroll. Everything here is *additional*, so the shipped defaults are
	incremental: a second day where ERPNext took one, the other half where it
	took a half, a full day where it took nothing.

	Each of the three kinds can be charged as days of salary or as a flat amount,
	or switched off entirely, from Enfono HR Settings. Missing check-outs also
	get a monthly free allowance, because on real data they are an endemic
	logging habit rather than a disciplinary event.
	"""
	settings = settings or get_settings()

	if not cint(settings.enable_attendance_penalties):
		return _empty_penalties()

	daily_rate = daily_rate_from_base(base, settings)

	unapproved_full_days = _count_unapproved_absences(employee, start, end)
	unapproved_half_days = _count_unapproved_half_days(employee, start, end)
	missing_checkout_days = _count_missing_checkouts(employee, start, end)

	# The free allowance is spent before anything is charged.
	free_checkouts = cint(settings.missing_checkout_free_days_per_month)
	chargeable_checkouts = max(missing_checkout_days - free_checkouts, 0)

	kinds = (
		("unapproved_absent", unapproved_full_days),
		("unapproved_half_day", unapproved_half_days),
		("missing_checkout", chargeable_checkouts),
	)

	raw_amount = sum(resolve_penalty(settings, prefix, count, daily_rate) for prefix, count in kinds)
	raw_days = sum(penalty_days_equivalent(settings, prefix, count) for prefix, count in kinds)

	capped_days = raw_days
	if cint(settings.cap_penalty_at_payable_days):
		# Nobody can lose more days than they were paid for. Without this the
		# literal rules produced 24 penalty days against 23 days present.
		capped_days = min(capped_days, max(flt(payable_days), 0))

	monthly_ceiling = flt(settings.max_penalty_days_per_month)
	if monthly_ceiling > 0:
		capped_days = min(capped_days, monthly_ceiling)

	# Scale the money down in the same proportion the days were clipped, so a
	# mix of day-based and amount-based penalties stays consistent.
	if raw_days > 0 and capped_days < raw_days:
		day_amount = raw_days * daily_rate
		fixed_amount = max(raw_amount - day_amount, 0)
		amount = (capped_days * daily_rate) + fixed_amount
	else:
		amount = raw_amount

	return {
		"unapproved_absent_days": unapproved_full_days,
		"unapproved_half_days": unapproved_half_days,
		"missing_checkout_days": missing_checkout_days,
		"chargeable_checkout_days": chargeable_checkouts,
		"raw_penalty_days": flt(raw_days, 2),
		"penalty_days": flt(capped_days, 2),
		"penalty_days_capped": flt(raw_days, 2) > flt(capped_days, 2),
		"penalty_amount": flt(amount, 2),
	}


def _empty_penalties() -> dict:
	return {
		"unapproved_absent_days": 0,
		"unapproved_half_days": 0,
		"missing_checkout_days": 0,
		"chargeable_checkout_days": 0,
		"raw_penalty_days": 0.0,
		"penalty_days": 0.0,
		"penalty_days_capped": False,
		"penalty_amount": 0.0,
	}


def _count_unapproved_absences(employee: str, start, end) -> int:
	"""Absent days with no approved leave covering them."""
	return cint(
		frappe.db.sql(
			"""
			SELECT COUNT(*)
			FROM `tabAttendance` att
			WHERE att.docstatus = 1
				AND att.employee = %(employee)s
				AND att.attendance_date BETWEEN %(start)s AND %(end)s
				AND att.status = 'Absent'
				AND NOT EXISTS (
					SELECT 1 FROM `tabLeave Application` la
					WHERE la.employee = att.employee
						AND la.docstatus = 1
						AND la.status = 'Approved'
						AND att.attendance_date BETWEEN la.from_date AND la.to_date
				)
			""",
			{"employee": employee, "start": start, "end": end},
		)[0][0]
	)


def _count_unapproved_half_days(employee: str, start, end) -> int:
	"""Half days with no approved half-day leave behind them."""
	return cint(
		frappe.db.sql(
			"""
			SELECT COUNT(*)
			FROM `tabAttendance` att
			WHERE att.docstatus = 1
				AND att.employee = %(employee)s
				AND att.attendance_date BETWEEN %(start)s AND %(end)s
				AND att.status = 'Half Day'
				AND NOT EXISTS (
					SELECT 1 FROM `tabLeave Application` la
					WHERE la.employee = att.employee
						AND la.docstatus = 1
						AND la.status = 'Approved'
						AND la.half_day = 1
						AND att.attendance_date BETWEEN la.from_date AND la.to_date
				)
			""",
			{"employee": employee, "start": start, "end": end},
		)[0][0]
	)


def _count_missing_checkouts(employee: str, start, end) -> int:
	"""Present days where the employee never genuinely checked out.

	Excludes days covered by an approved half-day request, which is exactly the
	carve-out the client's rule states.
	"""
	if not frappe.db.has_column("Employee Checkin", "custom_is_auto_checkout"):
		return 0

	return cint(
		frappe.db.sql(
			"""
			SELECT COUNT(*) FROM (
				SELECT DATE(eci.`time`) AS log_date
				FROM `tabEmployee Checkin` eci
				WHERE eci.employee = %(employee)s
					AND DATE(eci.`time`) BETWEEN %(start)s AND %(end)s
				GROUP BY DATE(eci.`time`)
				HAVING SUM(CASE WHEN eci.log_type = 'IN' THEN 1 ELSE 0 END) > 0
					AND SUM(
						CASE WHEN eci.log_type = 'OUT' AND eci.custom_is_auto_checkout = 0
						THEN 1 ELSE 0 END
					) = 0
			) gaps
			WHERE NOT EXISTS (
				SELECT 1 FROM `tabLeave Application` la
				WHERE la.employee = %(employee)s
					AND la.docstatus = 1
					AND la.status = 'Approved'
					AND la.half_day = 1
					AND gaps.log_date BETWEEN la.from_date AND la.to_date
			)
			""",
			{"employee": employee, "start": start, "end": end},
		)[0][0]
	)


# --- Overtime -------------------------------------------------------------------


def compute_overtime(employee: str, start, end, base: float, settings=None) -> dict:
	"""Approved overtime plus the extra day earned by working a weekly off."""
	settings = settings or get_settings()

	if not cint(settings.enable_overtime):
		return {
			"ot_hours": 0.0,
			"ot_amount": 0.0,
			"sunday_days_worked": 0,
			"sunday_amount": 0.0,
			"total_overtime": 0.0,
		}

	records = frappe.get_all(
		"Overtime Data",
		filters={
			"employee": employee,
			"docstatus": 1,
			"overtime_status": "Approved",
			"date": ["between", [start, end]],
		},
		fields=["name", "date", "ot_hours", "ot_amount"],
	)

	hourly_rate = hourly_rate_from_base(base, settings)
	ot_hours = sum(flt(row.ot_hours) for row in records)
	# Trust a stored amount if one was set; otherwise price it at the standard rate.
	ot_amount = sum(
		flt(row.ot_amount) or flt(hourly_rate * flt(row.ot_hours)) for row in records
	)

	sunday_days = _count_weekly_off_worked(employee, start, end, settings)
	sunday_amount = (
		sunday_days * daily_rate_from_base(base, settings)
		if cint(settings.pay_extra_day_for_weekly_off)
		else 0.0
	)

	return {
		"ot_hours": flt(ot_hours, 2),
		"ot_amount": flt(ot_amount, 2),
		"sunday_days_worked": sunday_days,
		"sunday_amount": flt(sunday_amount, 2),
		"total_overtime": flt(ot_amount + sunday_amount, 2),
	}


def _count_weekly_off_worked(employee: str, start, end, settings=None) -> int:
	"""Present days that fall on the company weekly off.

	The spec names Sunday, but the day is a setting rather than a literal so a
	branch on a different weekly off does not need a code change.
	"""
	settings = settings or get_settings()
	day_number = WEEKDAY_NUMBERS.get(settings.weekly_off_day or "Sunday", 1)

	return cint(
		frappe.db.sql(
			"""
			SELECT COUNT(*)
			FROM `tabAttendance`
			WHERE docstatus = 1
				AND employee = %(employee)s
				AND attendance_date BETWEEN %(start)s AND %(end)s
				AND status IN ('Present', 'Work From Home')
				AND DAYOFWEEK(attendance_date) = %(day_number)s
			""",
			{"employee": employee, "start": start, "end": end, "day_number": day_number},
		)[0][0]
	)


# --- Advances and arrears -------------------------------------------------------


def compute_advance(employee: str, end) -> dict:
	"""Outstanding employee advance recoverable from this month's salary."""
	rows = frappe.get_all(
		"Employee Advance",
		filters={
			"employee": employee,
			"docstatus": 1,
			"repay_unclaimed_amount_from_salary": 1,
			"posting_date": ["<=", end],
		},
		fields=["name", "paid_amount", "claimed_amount", "return_amount"],
	)

	outstanding = sum(
		flt(row.paid_amount) - flt(row.claimed_amount) - flt(row.return_amount)
		for row in rows
	)

	return {"advance_amount": flt(max(outstanding, 0), 2), "advance_count": len(rows)}


def compute_arrears(employee: str, end) -> dict:
	"""Arrear instalment due in the payroll month ending ``end``."""
	from enfono_hr.enfono_hr.doctype.employee_arrear.employee_arrear import get_due_amount

	rows = frappe.get_all(
		"Employee Arrear",
		filters={"employee": employee, "docstatus": 1, "status": "Active"},
		fields=[
			"name",
			"outstanding_amount",
			"monthly_deduction_amount",
			"additional_deduction_amount",
			"deduction_start_month",
			"deduction_end_month",
			"total_deducted",
		],
	)

	due = sum(get_due_amount(row, end) for row in rows)
	return {"arrear_amount": flt(due, 2), "arrear_count": len(rows)}


# --- Daily wage -----------------------------------------------------------------


def is_daily_wage(employee_doc: dict) -> bool:
	"""Whether an employee is paid per day rather than monthly.

	Driven by ``Employee.custom_wage_type``, not by gender or branch. The spec
	describes the Chelambra factory group as "female employees", but the
	distinguishing fact is that they are daily-wage workers -- and keying a pay
	rule on gender would be both wrong when a male daily-wager is hired and
	indefensible on its own terms.
	"""
	return (employee_doc.get("custom_wage_type") or "Monthly") == "Daily Wage"


def compute_daily_wage_earning(employee_doc: dict, start, end, settings=None) -> dict:
	"""Earnings for a daily-wage employee: day rate, with a weekly-off premium."""
	settings = settings or get_settings()
	employee = employee_doc["name"]

	# Per-employee rate wins; the settings default covers everyone else.
	daily_rate = flt(employee_doc.get("custom_daily_wage_rate")) or flt(
		settings.default_daily_wage_rate
	)
	sunday_rate = (
		flt(employee_doc.get("custom_sunday_wage_rate"))
		or flt(settings.default_sunday_wage_rate)
		or daily_rate
	)
	day_number = WEEKDAY_NUMBERS.get(settings.weekly_off_day or "Sunday", 1)

	rows = frappe.db.sql(
		"""
		SELECT
			SUM(CASE WHEN DAYOFWEEK(attendance_date) = %(day_number)s THEN 1 ELSE 0 END) AS sundays,
			SUM(CASE WHEN DAYOFWEEK(attendance_date) <> %(day_number)s THEN 1 ELSE 0 END) AS weekdays,
			SUM(CASE WHEN status = 'Half Day' THEN 1 ELSE 0 END) AS half_days
		FROM `tabAttendance`
		WHERE docstatus = 1
			AND employee = %(employee)s
			AND attendance_date BETWEEN %(start)s AND %(end)s
			AND status IN ('Present', 'Half Day', 'Work From Home')
		""",
		{"employee": employee, "start": start, "end": end, "day_number": day_number},
		as_dict=True,
	)[0]

	sundays = cint(rows.sundays)
	weekdays = cint(rows.weekdays)
	half_days = cint(rows.half_days)

	# A half day is paid at half the applicable rate; it was counted as a whole
	# day above, so remove the half that was not worked.
	gross = (weekdays * daily_rate) + (sundays * sunday_rate) - (half_days * daily_rate * 0.5)

	return {
		"weekdays_worked": weekdays,
		"sundays_worked": sundays,
		"half_days": half_days,
		"daily_rate": daily_rate,
		"sunday_rate": sunday_rate,
		"gross_earning": flt(max(gross, 0), 2),
	}


# --- Whole-employee summary -----------------------------------------------------


def compute_employee_payroll(employee_doc: dict, year: int, month: int) -> dict:
	"""Every figure the client's salary formula needs, for one employee-month.

	Net Salary = Gross Pay - Advance - ESI - Fine - Arrears + OT, per the spec.
	"""
	settings = get_settings()
	start, end = month_bounds(year, month)
	employee = employee_doc["name"]
	total_days = calendar.monthrange(year, month)[1]

	base = get_monthly_base_salary(employee, end)
	daily_wage = is_daily_wage(employee_doc)

	counts = _attendance_counts(employee, start, end)
	lop_days = flt(counts["absent"])
	payable_days = flt(counts["present"]) + (flt(counts["half_day"]) * 0.5)

	if daily_wage:
		wage = compute_daily_wage_earning(employee_doc, start, end, settings)
		gross_salary = wage["gross_earning"]
		lop_amount = 0.0
		gross_pay = gross_salary
	else:
		wage = {}
		gross_salary = base
		lop_amount = flt((base / total_days) * lop_days, 2) if total_days else 0.0
		gross_pay = flt(gross_salary - lop_amount, 2)

	late_early = compute_late_early_charges(employee, start, end, base, settings)
	penalties = compute_attendance_penalties(
		employee, start, end, base, payable_days, settings
	)
	overtime = compute_overtime(employee, start, end, base, settings)
	advance = compute_advance(employee, end)
	arrears = compute_arrears(employee, end)
	esi = _get_esi_amount(employee, end)

	fine_total = flt(
		late_early["fine_amount"] + late_early["hourly_deduction"] + penalties["penalty_amount"],
		2,
	)

	requested_deductions = flt(
		advance["advance_amount"] + esi + fine_total + arrears["arrear_amount"], 2
	)
	earnings = flt(gross_pay + overtime["total_overtime"], 2)

	# Optional ceiling on everything deducted, as a share of gross pay.
	total_deductions = requested_deductions
	deduction_ceiling = flt(settings.max_total_deduction_percent)
	if deduction_ceiling > 0:
		total_deductions = min(total_deductions, flt(gross_pay) * deduction_ceiling / 100.0)

	uncapped_net = flt(earnings - total_deductions, 2)

	# A salary slip must never go negative. Whatever the rules ask for beyond what
	# the month can pay is reported rather than silently applied -- carrying it
	# forward or waiving it is a client decision, not one to bury in a formula.
	if cint(settings.floor_net_salary_at_zero):
		net_salary = max(uncapped_net, 0.0)
	else:
		net_salary = uncapped_net

	total_deductions = flt(total_deductions, 2)
	excess_deduction = flt(requested_deductions - total_deductions, 2) + flt(
		abs(min(uncapped_net, 0.0)) if cint(settings.floor_net_salary_at_zero) else 0.0, 2
	)

	return {
		"employee": employee,
		"employee_name": employee_doc.get("employee_name"),
		"designation": employee_doc.get("designation"),
		"department": employee_doc.get("department"),
		"branch": employee_doc.get("branch"),
		"wage_type": "Daily Wage" if daily_wage else "Monthly",
		"base": flt(base, 2),
		"total_days": total_days,
		"present_days": flt(counts["present"], 1),
		"half_days": flt(counts["half_day"], 1),
		"leave_days": flt(counts["on_leave"], 1),
		"lop_days": lop_days,
		"payable_days": flt(payable_days, 2),
		"gross_salary": flt(gross_salary, 2),
		"lop_amount": lop_amount,
		"gross_pay": gross_pay,
		"occurrence_days": late_early["occurrence_days"],
		"free_days_used": late_early["free_days_used"],
		"fined_days": late_early["fined_days"],
		"flat_fine": late_early["fine_amount"],
		"hourly_deduction": late_early["hourly_deduction"],
		"penalty_days": penalties["penalty_days"],
		"penalty_amount": penalties["penalty_amount"],
		"unapproved_absent_days": penalties["unapproved_absent_days"],
		"unapproved_half_days": penalties["unapproved_half_days"],
		"missing_checkout_days": penalties["missing_checkout_days"],
		"chargeable_checkout_days": penalties["chargeable_checkout_days"],
		"fine_total": fine_total,
		"ot_hours": overtime["ot_hours"],
		"ot_amount": overtime["ot_amount"],
		"sunday_days_worked": overtime["sunday_days_worked"],
		"sunday_amount": overtime["sunday_amount"],
		"total_overtime": overtime["total_overtime"],
		"advance_amount": advance["advance_amount"],
		"arrear_amount": arrears["arrear_amount"],
		"esi_amount": flt(esi, 2),
		"raw_penalty_days": penalties["raw_penalty_days"],
		"penalty_days_capped": penalties["penalty_days_capped"],
		"total_deductions": total_deductions,
		"uncapped_net": uncapped_net,
		"excess_deduction": excess_deduction,
		"net_salary": net_salary,
		"daily_wage_detail": wage,
	}


def _attendance_counts(employee: str, start, end) -> dict:
	row = frappe.db.sql(
		"""
		SELECT
			SUM(status = 'Present') AS present,
			SUM(status = 'Work From Home') AS wfh,
			SUM(status = 'Absent') AS absent,
			SUM(status = 'Half Day') AS half_day,
			SUM(status = 'On Leave') AS on_leave
		FROM `tabAttendance`
		WHERE docstatus = 1
			AND employee = %(employee)s
			AND attendance_date BETWEEN %(start)s AND %(end)s
		""",
		{"employee": employee, "start": start, "end": end},
		as_dict=True,
	)[0]

	return {
		"present": cint(row.present) + cint(row.wfh),
		"absent": cint(row.absent),
		"half_day": cint(row.half_day),
		"on_leave": cint(row.on_leave),
	}


def _get_esi_amount(employee: str, on_date) -> float:
	"""Fixed ESI deduction from the employee's Salary Structure Assignment."""
	assignment = frappe.db.get_value(
		"Salary Structure Assignment",
		{"employee": employee, "docstatus": 1, "from_date": ["<=", getdate(on_date)]},
		"name",
		order_by="from_date desc",
	)
	if not assignment:
		return 0.0

	return flt(
		frappe.db.get_value(
			"Salary Detail",
			{
				"parent": assignment,
				"parenttype": "Salary Structure Assignment",
				"salary_component": "ESI",
			},
			"amount",
		)
	)
