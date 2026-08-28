# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt
"""Every payroll rule figure HR is allowed to change, in one place.

These started life as constants in ``payroll_rules.py``. They are settings
because they are policy, not logic: the missing-checkout penalty in particular
has to be tuned against real attendance behaviour, and nobody should need a code
deployment to do that.

Validation here is deliberately noisy. A wrong number in this form silently
changes what every employee is paid, so the form warns as soon as a value looks
capable of doing damage rather than waiting for someone to notice a payslip.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt


class EnfonoHRSettings(Document):
	def validate(self):
		self.validate_non_negative()
		self.validate_rate_divisors()
		self.warn_about_severe_penalties()

	def on_update(self):
		# payroll_rules reads this through get_cached_doc, so the cache has to go
		# or the next payroll run silently uses the old numbers.
		frappe.clear_cache(doctype=self.doctype)

	def validate_non_negative(self):
		fields = (
			"grace_minutes",
			"free_occurrences_per_month",
			"fine_per_occurrence",
			"min_working_hours_for_fine",
			"unapproved_absent_penalty_days",
			"unapproved_absent_penalty_amount",
			"unapproved_half_day_penalty_days",
			"unapproved_half_day_penalty_amount",
			"missing_checkout_penalty_days",
			"missing_checkout_penalty_amount",
			"missing_checkout_free_days_per_month",
			"max_penalty_days_per_month",
			"default_daily_wage_rate",
			"default_sunday_wage_rate",
		)

		for fieldname in fields:
			if flt(self.get(fieldname)) < 0:
				label = self.meta.get_label(fieldname)
				frappe.throw(_("This value cannot be negative: ") + str(label))

		if not 0 <= flt(self.max_total_deduction_percent) <= 100:
			frappe.throw(_("Maximum Total Deduction must be between 0 and 100 percent."))

	def validate_rate_divisors(self):
		if cint(self.ot_rate_days_per_month) <= 0:
			frappe.throw(_("Rate Divisor — Days Per Month must be greater than zero."))

		if flt(self.ot_rate_hours_per_day) <= 0:
			frappe.throw(_("Rate Divisor — Hours Per Day must be greater than zero."))

	def warn_about_severe_penalties(self):
		"""Flag settings that would take an implausible share of somebody's pay.

		The missing-checkout rule is called out by name because it is the one that
		actually bit: applied at a full day per occurrence against this site's real
		attendance, it removed roughly a third of total payroll.
		"""
		if not self.enable_attendance_penalties:
			return

		if (
			self.missing_checkout_penalty_type == "Days of Salary"
			and flt(self.missing_checkout_penalty_days) >= 1
			and not cint(self.missing_checkout_free_days_per_month)
		):
			frappe.msgprint(
				_(
					"Charging a full day for every missing checkout, with no free "
					"allowance, is severe. Missing check-outs are common here. Run the "
					"Payroll Computation Preview for a full month before relying on this."
				),
				indicator="red",
				title=_("Check This Penalty"),
			)

		if not self.floor_net_salary_at_zero:
			frappe.msgprint(
				_(
					"With the negative-salary guard off, deductions can exceed a "
					"month's pay and produce a negative net salary."
				),
				indicator="orange",
				title=_("Negative Salary Allowed"),
			)


def get_hr_settings():
	"""Cached settings singleton. Safe to call in a loop."""
	return frappe.get_cached_doc("Enfono HR Settings")
