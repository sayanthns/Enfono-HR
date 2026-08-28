# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt
"""An outstanding amount recovered from an employee over several payroll months.

The client asked for five things on this record — outstanding amount, monthly
deduction, deduction end month, an additional one-off deduction, and remarks —
so those are the fields. Everything else here exists to stop the same rupee
being recovered twice.

``total_deducted`` and ``balance_amount`` are maintained by the payroll run, not
typed in: a person editing a running balance by hand is how over-recovery
happens.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, get_last_day, getdate


class EmployeeArrear(Document):
	def validate(self):
		self.validate_amounts()
		self.validate_period()
		self.update_balance()

	def on_submit(self):
		self.db_set("status", "Completed" if self.balance_amount <= 0 else "Active")

	def on_cancel(self):
		self.db_set("status", "Cancelled")

	def validate_amounts(self):
		if flt(self.outstanding_amount) <= 0:
			frappe.throw(_("Outstanding Amount must be greater than zero."))

		if flt(self.monthly_deduction_amount) <= 0:
			frappe.throw(_("Monthly Deduction Amount must be greater than zero."))

		if flt(self.monthly_deduction_amount) > flt(self.outstanding_amount):
			frappe.throw(
				_("Monthly Deduction Amount cannot be greater than the Outstanding Amount.")
			)

	def validate_period(self):
		if not self.deduction_end_month:
			return

		if getdate(self.deduction_end_month) < getdate(self.deduction_start_month):
			frappe.throw(_("Deduction End Month cannot be before Deduction Start Month."))

		months = months_between(self.deduction_start_month, self.deduction_end_month)
		recoverable = flt(self.monthly_deduction_amount) * months + flt(
			self.additional_deduction_amount
		)

		if recoverable < flt(self.outstanding_amount):
			frappe.msgprint(
				_(
					"The monthly deduction will not clear the outstanding amount within the "
					"chosen period. A balance will remain after the end month."
				),
				indicator="orange",
				title=_("Recovery Period Too Short"),
			)

	def update_balance(self):
		self.total_deducted = flt(self.total_deducted)
		self.balance_amount = flt(self.outstanding_amount) - flt(self.total_deducted)

		if self.docstatus == 1:
			self.status = "Completed" if self.balance_amount <= 0 else "Active"

	def record_deduction(self, amount):
		"""Called by the payroll run once a slip actually carries this deduction.

		Uses ``db_set`` rather than ``save`` because the caller may be holding the
		document while a Salary Slip is being written — re-saving here would raise
		a TimestampMismatchError on the next write.
		"""
		amount = flt(amount)
		if amount <= 0:
			return

		total = flt(self.total_deducted) + amount
		balance = flt(self.outstanding_amount) - total

		self.db_set("total_deducted", total, update_modified=False)
		self.db_set("balance_amount", balance, update_modified=False)
		self.db_set(
			"status", "Completed" if balance <= 0 else "Active", update_modified=False
		)


def months_between(start, end) -> int:
	"""Inclusive count of payroll months spanned by two dates."""
	start, end = getdate(start), getdate(end)
	return (end.year - start.year) * 12 + (end.month - start.month) + 1


def get_due_amount(arrear: dict, period_end) -> float:
	"""Amount this arrear should recover in the payroll month ending ``period_end``.

	Never recovers more than the remaining balance, and pays out the one-off
	additional deduction only in the first month of the plan.
	"""
	period_end = getdate(period_end)
	start = getdate(arrear["deduction_start_month"])

	if period_end < get_last_day(start):
		return 0.0

	if arrear.get("deduction_end_month") and period_end > get_last_day(
		getdate(arrear["deduction_end_month"])
	):
		return 0.0

	balance = flt(arrear["outstanding_amount"]) - flt(arrear.get("total_deducted"))
	if balance <= 0:
		return 0.0

	due = flt(arrear["monthly_deduction_amount"])

	is_first_month = get_last_day(start) == period_end
	if is_first_month:
		due += flt(arrear.get("additional_deduction_amount"))

	return min(due, balance)
