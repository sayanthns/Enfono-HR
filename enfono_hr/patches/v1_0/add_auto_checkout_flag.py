# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt
"""Add ``Employee Checkin.custom_is_auto_checkout``.

The nightly ``Auto Check-Out`` scheduled job invents a 23:00 OUT for anyone who
forgot to check out. Without a marker, those synthetic rows are indistinguishable
from real ones — which makes the "Previous Day Checkout Not Marked" report
permanently empty and silently disables the payroll rule that fines a missing
checkout.

The field is read-only: it is set by the job, never by a person.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

CUSTOM_FIELDS = {
	"Employee Checkin": [
		{
			"fieldname": "custom_is_auto_checkout",
			"label": "Auto Check-Out",
			"fieldtype": "Check",
			"insert_after": "log_type",
			"read_only": 1,
			"in_standard_filter": 1,
			"description": (
				"Set by the nightly Auto Check-Out job. A checkout the employee "
				"never actually made — excluded from early-exit and break reporting."
			),
		}
	]
}


def execute():
	create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)
	backfill_historical_rows()


def backfill_historical_rows():
	"""Flag pre-existing synthetic checkouts so history reads correctly too.

	The job's signature is unmistakable: exactly 23:00:00 with lat/long "0.0".
	Real check-outs carry a device geolocation, and an organic checkout landing on
	the exact second of 23:00:00 does not occur in this data.
	"""
	frappe.db.sql(
		"""
		UPDATE `tabEmployee Checkin`
		SET custom_is_auto_checkout = 1
		WHERE log_type = 'OUT'
			AND TIME(`time`) = '23:00:00'
			AND latitude = '0.0'
			AND longitude = '0.0'
		"""
	)
