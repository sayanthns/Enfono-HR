# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt
"""Approved overtime for one employee on one day.

The rate is derived, never typed. The client's spec gives two OT formulas that
only agree at 31 days and an 8-hour paid shift; the confirmed basis is the fixed
``base / 31 / 8``, so a 12-hour driver and an 8-hour office worker earn the same
hourly rate.

Working a Sunday earns one extra day of salary. That is deliberately *not* added
to ``ot_amount`` here — it is a day of salary, not overtime hours, and payroll
adds it separately so the two never double-count.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate

from enfono_hr.payroll_rules import (
	get_monthly_base_salary,
	hourly_rate_from_base,
	resolve_shift,
)


class OvertimeData(Document):
	def validate(self):
		self.validate_hours()
		self.validate_duplicate()
		self.set_shift_and_day()
		self.calculate_amount()

	def on_submit(self):
		if self.overtime_status not in ("Approved", "Rejected"):
			frappe.throw(
				_("Set the Overtime Status to Approved or Rejected before submitting.")
			)

	def validate_hours(self):
		if flt(self.ot_hours) <= 0:
			frappe.throw(_("OT Total Hours must be greater than zero."))

		if flt(self.ot_hours) > 24:
			frappe.throw(_("OT Total Hours cannot exceed 24 hours in a single day."))

		if getdate(self.date) > getdate(frappe.utils.today()):
			frappe.throw(_("Overtime cannot be recorded for a future date."))

	def validate_duplicate(self):
		existing = frappe.db.exists(
			"Overtime Data",
			{
				"employee": self.employee,
				"date": self.date,
				"docstatus": ["<", 2],
				"name": ["!=", self.name or ""],
			},
		)
		if existing:
			frappe.throw(
				_("Overtime is already recorded for this employee on this date: ")
				+ str(existing)
			)

	def set_shift_and_day(self):
		attendance_shift = frappe.db.get_value(
			"Attendance",
			{"employee": self.employee, "attendance_date": self.date, "docstatus": 1},
			"shift",
		)
		shift = resolve_shift(self.employee, attendance_shift)
		self.shift = shift.name if shift else None

		# Python's weekday(): Monday is 0, Sunday is 6.
		self.is_sunday = cint(getdate(self.date).weekday() == 6)

	def calculate_amount(self):
		self.base_salary = get_monthly_base_salary(self.employee, self.date)

		if not self.base_salary:
			self.ot_rate = 0
			self.ot_amount = 0
			frappe.msgprint(
				_(
					"No Salary Structure Assignment was found for this employee on this "
					"date, so the overtime amount could not be calculated."
				),
				indicator="orange",
				title=_("Overtime Not Priced"),
			)
			return

		self.ot_rate = flt(hourly_rate_from_base(self.base_salary), 2)
		self.ot_amount = flt(flt(self.ot_rate) * flt(self.ot_hours), 2)
