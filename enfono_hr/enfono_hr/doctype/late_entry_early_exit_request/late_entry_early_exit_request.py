# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt
"""Employee request to have a late entry or early exit excused.

Why this exists: unapproved late entries and early exits beyond the monthly
allowance attract a flat fine. An approved request replaces that flat fine with
an hourly deduction, which is both fairer and what the client asked for.

The document pulls the actual minutes off the submitted Attendance for that day
rather than trusting what the employee typed, so an approval cannot quietly
excuse more time than was actually missed.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, get_datetime, getdate, today

from enfono_hr.payroll_rules import (
	get_monthly_base_salary,
	hourly_rate_from_base,
	resolve_shift,
	shift_boundary_datetime,
)


class LateEntryEarlyExitRequest(Document):
	def validate(self):
		self.validate_date()
		self.validate_duplicate()
		self.fetch_attendance_details()
		self.calculate_deduction()
		self.set_status()

	def on_submit(self):
		if self.status not in ("Approved", "Rejected"):
			frappe.throw(
				_("Set the status to Approved or Rejected before submitting this request.")
			)

	def on_cancel(self):
		self.status = "Cancelled"

	def validate_date(self):
		if getdate(self.request_date) > getdate(today()):
			frappe.throw(_("A late entry or early exit cannot be requested for a future date."))

	def validate_duplicate(self):
		existing = frappe.db.exists(
			"Late Entry Early Exit Request",
			{
				"employee": self.employee,
				"request_date": self.request_date,
				"request_type": self.request_type,
				"docstatus": ["<", 2],
				"name": ["!=", self.name or ""],
			},
		)
		if existing:
			frappe.throw(
				_("A request of this type already exists for this employee on this date: ")
				+ str(existing)
			)

	def fetch_attendance_details(self):
		"""Read the real in/out time off Attendance and recompute the minutes.

		If no attendance has been marked yet the employee's own figure stands, but
		it is re-derived the moment attendance appears, so payroll always prices
		what actually happened rather than what was claimed.
		"""
		attendance = frappe.db.get_value(
			"Attendance",
			{
				"employee": self.employee,
				"attendance_date": self.request_date,
				"docstatus": 1,
			},
			["name", "shift", "in_time", "out_time", "working_hours"],
			as_dict=True,
		)

		if not attendance:
			self.attendance = None
			return

		self.attendance = attendance.name
		shift = resolve_shift(self.employee, attendance.shift)
		if not shift:
			return

		self.shift = shift.name

		if self.request_type == "Late Entry":
			self.shift_time = shift.start_time
			self.actual_time = attendance.in_time
			if attendance.in_time:
				boundary = shift_boundary_datetime(self.request_date, shift, "start")
				self.minutes = max(
					0, int((get_datetime(attendance.in_time) - boundary).total_seconds() // 60)
				)
		else:
			self.shift_time = shift.end_time
			self.actual_time = attendance.out_time
			if attendance.out_time:
				boundary = shift_boundary_datetime(self.request_date, shift, "end")
				self.minutes = max(
					0, int((boundary - get_datetime(attendance.out_time)).total_seconds() // 60)
				)

	def calculate_deduction(self):
		"""Price the request hourly, on the same rate basis as overtime."""
		self.deduction_hours = flt(cint(self.minutes) / 60.0, 2)

		base = get_monthly_base_salary(self.employee, self.request_date)
		if not base:
			self.deduction_amount = 0
			return

		self.deduction_amount = flt(hourly_rate_from_base(base) * flt(self.deduction_hours), 2)

	def set_status(self):
		if self.docstatus == 2:
			self.status = "Cancelled"
		elif self.docstatus == 0 and self.status in (None, "", "Cancelled"):
			self.status = "Draft"
