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

# --- Client-specified constants -------------------------------------------------

#: Minutes of lateness or early departure tolerated before a day counts.
GRACE_MINUTES = 15

#: Occurrence-days per month allowed before the flat fine starts.
FREE_OCCURRENCES_PER_MONTH = 3

#: Flat fine per occurrence-day beyond the monthly allowance.
FINE_PER_OCCURRENCE = 100.0

#: Divisors for the hourly rate. The spec gives two formulas that only agree at
#: 31 days and an 8-hour paid shift; the client confirmed this fixed basis, so a
#: 12-hour driver and an 8-hour office worker earn the same hourly OT rate.
RATE_DAYS_PER_MONTH = 31
RATE_HOURS_PER_DAY = 8

#: Attendance below this many working hours is treated as a logging artefact
#: rather than a real day, and never attracts a late/early fine.
#:
#: This is not hypothetical. Live data has an employee who logged OUT and then IN
#: two seconds apart -- ``working_hours`` 0.0, marked Present, with HRMS setting
#: both ``late_entry`` and ``early_exit``. Fining a double tap INR 100 would be
#: indefensible, and these days are already caught by the missing-checkout rule.
MIN_WORKING_HOURS_FOR_FINE = 0.25

#: Days of salary charged for a Present day with no genuine checkout.
#:
#: The spec says one full day. Left at 1.0 against this site's real data that is
#: ruinous rather than corrective: 51 of 56 employees missed a checkout in July
#: 2026, and the literal rule wiped out roughly a third of total payroll and sent
#: two people negative. Missing checkouts here are an endemic logging habit, not
#: 51 individual disciplinary cases.
#:
#: This is deliberately a named constant, currently at the spec's 1.0, so the
#: client can dial it down after seeing the dry run rather than discovering the
#: effect on a payslip. Whatever value is agreed, the per-employee ceiling below
#: still applies.
MISSING_CHECKOUT_PENALTY_DAYS = 1.0


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


def hourly_rate_from_base(base: float) -> float:
	"""Hourly rate on the client-confirmed ``base / 31 / 8`` basis."""
	return flt(base) / RATE_DAYS_PER_MONTH / RATE_HOURS_PER_DAY


def daily_rate_from_base(base: float) -> float:
	return flt(base) / RATE_DAYS_PER_MONTH


def month_bounds(year: int, month: int) -> tuple:
	first = getdate(f"{year}-{month:02d}-01")
	return first, get_last_day(first)


# --- Late entry / early exit ----------------------------------------------------


def get_occurrences(employee: str, start, end, grace: int = GRACE_MINUTES) -> list[dict]:
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

	auto_checkout_times = get_auto_checkout_times(employee, start, end)
	occurrences = []

	for row in rows:
		if not row.shift or flt(row.working_hours) < MIN_WORKING_HOURS_FOR_FINE:
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


def compute_late_early_charges(employee: str, start, end, base: float) -> dict:
	"""Flat fines and hourly deductions for one employee in one payroll month.

	The allowance is three *days*, not three occurrences: a day on which someone
	is both late and leaves early is one day against the allowance, which is how
	the client's worded rule reads.

	Approved days are excluded from the allowance count entirely — they are
	charged hourly instead, so an approval must not consume someone's free days.
	"""
	occurrences = get_occurrences(employee, start, end)
	approved = get_approved_requests(employee, start, end)

	hourly_deduction = 0.0
	approved_days = set()
	unapproved_by_day: dict = {}

	for occurrence in occurrences:
		key = (occurrence["date"], occurrence["type"])
		if key in approved:
			approved_days.add(occurrence["date"])
			hourly_deduction += flt(approved[key].deduction_amount) or flt(
				hourly_rate_from_base(base) * (occurrence["minutes"] / 60.0)
			)
		else:
			unapproved_by_day.setdefault(occurrence["date"], []).append(occurrence)

	chargeable_days = sorted(unapproved_by_day)
	fined_days = chargeable_days[FREE_OCCURRENCES_PER_MONTH:]

	return {
		"occurrences": occurrences,
		"occurrence_days": len(unapproved_by_day) + len(approved_days),
		"approved_days": len(approved_days),
		"free_days_used": min(len(chargeable_days), FREE_OCCURRENCES_PER_MONTH),
		"fined_days": len(fined_days),
		"fine_amount": flt(len(fined_days) * FINE_PER_OCCURRENCE, 2),
		"hourly_deduction": flt(hourly_deduction, 2),
	}


# --- Attendance penalties -------------------------------------------------------


def compute_attendance_penalties(
	employee: str, start, end, base: float, payable_days: float
) -> dict:
	"""Extra day-deductions the client's leave rules impose on top of normal LOP.

	ERPNext already deducts for Absent and Half Day through attendance-based
	payroll. These are the *additional* penalty days the spec asks for, so the
	numbers here are deliberately incremental — adding a full day where ERPNext
	took nothing, or the second half where it took one half.
	"""
	daily_rate = daily_rate_from_base(base)

	unapproved_full_days = _count_unapproved_absences(employee, start, end)
	unapproved_half_days = _count_unapproved_half_days(employee, start, end)
	missing_checkout_days = _count_missing_checkouts(employee, start, end)

	# Absent already costs one day of LOP; the rule is double, so one more.
	full_day_penalty_days = unapproved_full_days
	# Half Day already costs half; an unapproved one costs a full day, so the other half.
	half_day_penalty_days = unapproved_half_days * 0.5
	# A missing checkout on a Present day currently costs nothing.
	checkout_penalty_days = missing_checkout_days * MISSING_CHECKOUT_PENALTY_DAYS

	raw_penalty_days = full_day_penalty_days + half_day_penalty_days + checkout_penalty_days

	# Hard ceiling: nobody can lose more days than they were paid for. Without
	# this the literal rules produce penalties larger than the salary itself --
	# on this site's July data, 24 penalty days against 23 days present.
	capped_penalty_days = min(raw_penalty_days, max(payable_days, 0))

	return {
		"unapproved_absent_days": unapproved_full_days,
		"unapproved_half_days": unapproved_half_days,
		"missing_checkout_days": missing_checkout_days,
		"raw_penalty_days": flt(raw_penalty_days, 2),
		"penalty_days": flt(capped_penalty_days, 2),
		"penalty_days_capped": raw_penalty_days > capped_penalty_days,
		"penalty_amount": flt(capped_penalty_days * daily_rate, 2),
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


def compute_overtime(employee: str, start, end, base: float) -> dict:
	"""Approved overtime plus the extra day earned by working a weekly off."""
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

	hourly_rate = hourly_rate_from_base(base)
	ot_hours = sum(flt(row.ot_hours) for row in records)
	# Trust a stored amount if one was set; otherwise price it at the standard rate.
	ot_amount = sum(
		flt(row.ot_amount) or flt(hourly_rate * flt(row.ot_hours)) for row in records
	)

	sunday_days = _count_sundays_worked(employee, start, end)
	sunday_amount = sunday_days * daily_rate_from_base(base)

	return {
		"ot_hours": flt(ot_hours, 2),
		"ot_amount": flt(ot_amount, 2),
		"sunday_days_worked": sunday_days,
		"sunday_amount": flt(sunday_amount, 2),
		"total_overtime": flt(ot_amount + sunday_amount, 2),
	}


def _count_sundays_worked(employee: str, start, end) -> int:
	"""Present days that fall on the employee's weekly off.

	``DAYOFWEEK`` is 1 for Sunday in MariaDB. The spec names Sunday explicitly
	rather than deriving the weekly off from the holiday list, so that is what is
	implemented -- but note it will need revisiting for any employee whose weekly
	off is not Sunday.
	"""
	return cint(
		frappe.db.sql(
			"""
			SELECT COUNT(*)
			FROM `tabAttendance`
			WHERE docstatus = 1
				AND employee = %(employee)s
				AND attendance_date BETWEEN %(start)s AND %(end)s
				AND status IN ('Present', 'Work From Home')
				AND DAYOFWEEK(attendance_date) = 1
			""",
			{"employee": employee, "start": start, "end": end},
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


def compute_daily_wage_earning(employee_doc: dict, start, end) -> dict:
	"""Earnings for a daily-wage employee: day rate, with a Sunday premium."""
	employee = employee_doc["name"]
	daily_rate = flt(employee_doc.get("custom_daily_wage_rate"))
	sunday_rate = flt(employee_doc.get("custom_sunday_wage_rate")) or daily_rate

	rows = frappe.db.sql(
		"""
		SELECT
			SUM(CASE WHEN DAYOFWEEK(attendance_date) = 1 THEN 1 ELSE 0 END) AS sundays,
			SUM(CASE WHEN DAYOFWEEK(attendance_date) <> 1 THEN 1 ELSE 0 END) AS weekdays,
			SUM(CASE WHEN status = 'Half Day' THEN 1 ELSE 0 END) AS half_days
		FROM `tabAttendance`
		WHERE docstatus = 1
			AND employee = %(employee)s
			AND attendance_date BETWEEN %(start)s AND %(end)s
			AND status IN ('Present', 'Half Day', 'Work From Home')
		""",
		{"employee": employee, "start": start, "end": end},
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
	start, end = month_bounds(year, month)
	employee = employee_doc["name"]
	total_days = calendar.monthrange(year, month)[1]

	base = get_monthly_base_salary(employee, end)
	daily_wage = is_daily_wage(employee_doc)

	counts = _attendance_counts(employee, start, end)
	lop_days = flt(counts["absent"])
	payable_days = flt(counts["present"]) + (flt(counts["half_day"]) * 0.5)

	if daily_wage:
		wage = compute_daily_wage_earning(employee_doc, start, end)
		gross_salary = wage["gross_earning"]
		lop_amount = 0.0
		gross_pay = gross_salary
	else:
		wage = {}
		gross_salary = base
		lop_amount = flt((base / total_days) * lop_days, 2) if total_days else 0.0
		gross_pay = flt(gross_salary - lop_amount, 2)

	late_early = compute_late_early_charges(employee, start, end, base)
	penalties = compute_attendance_penalties(employee, start, end, base, payable_days)
	overtime = compute_overtime(employee, start, end, base)
	advance = compute_advance(employee, end)
	arrears = compute_arrears(employee, end)
	esi = _get_esi_amount(employee, end)

	fine_total = flt(
		late_early["fine_amount"] + late_early["hourly_deduction"] + penalties["penalty_amount"],
		2,
	)

	total_deductions = flt(
		advance["advance_amount"] + esi + fine_total + arrears["arrear_amount"], 2
	)
	earnings = flt(gross_pay + overtime["total_overtime"], 2)

	# A salary slip must never go negative. If the rules ask for more than the
	# month can pay, the excess is reported rather than silently applied -- what
	# happens to it (carry to next month, or waive) is a client decision, not one
	# to bury in a formula.
	uncapped_net = flt(earnings - total_deductions, 2)
	net_salary = max(uncapped_net, 0.0)
	excess_deduction = flt(abs(min(uncapped_net, 0.0)), 2)

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
