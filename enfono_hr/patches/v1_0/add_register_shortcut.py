# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt
"""Re-run the Home shortcut patch so `Monthly Attendance Register` appears.

`add_home_workspace_shortcuts` already ran on every site, and Frappe will not
run a patch twice — so adding the new report to its list changes nothing on a
site that has already migrated. This entry exists only to trigger that same
idempotent function again.

Without it the register is reachable only by typing its name into the search
bar, which is exactly how a delivered report goes unused.
"""

from enfono_hr.patches.v1_0.add_home_workspace_shortcuts import execute as add_shortcuts


def execute():
	add_shortcuts()
