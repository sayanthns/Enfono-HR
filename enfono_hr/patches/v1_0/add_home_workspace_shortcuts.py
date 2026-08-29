# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt
"""Put the new HR settings, forms and reports on the Home workspace.

🔴 A Workspace in v15 needs BOTH halves. Appending rows to the `shortcuts` child
table is not enough: the workspace renders from its `content` JSON, an ordered
list of blocks, and a shortcut only appears if a `shortcut` block references it
by `shortcut_name` matching that shortcut's `label`. Rows without a block are
invisible, and blocks without a row render as an empty card.

Idempotent on both halves — a shortcut whose label is already present is not
duplicated, and a content block for a label already in `content` is not added.
So a re-run after someone rearranges the page adds only what is genuinely
missing.

Nothing existing is removed. The Home page already carries shortcuts to several
reports this work supersedes; retiring those is a separate decision for the
client, not something a patch should do behind their back.
"""

import json

import frappe

WORKSPACE = "Home"

# (type, link_to, label, colour, ref_doctype_for_reports)
FORMS = [
	("DocType", "Enfono HR Settings", "Enfono HR Settings", "Grey", None),
	("DocType", "Late Entry Early Exit Request", "Late Entry / Early Exit Request", "Blue", None),
	("DocType", "Overtime Data", "Overtime Data", "Blue", None),
	("DocType", "Employee Arrear", "Employee Arrear", "Blue", None),
]

DAILY_REPORTS = [
	("Report", "Daily Leave Request Report", "Daily Leave Request Report", "Cyan", "Leave Application"),
	("Report", "Previous Day Checkout Not Marked Report", "Previous Day Checkout Not Marked", "Cyan", "Employee Checkin"),
	("Report", "Late Entry Detail Report", "Late Entry Detail Report", "Cyan", "Attendance"),
	("Report", "Early Exit Detail Report", "Early Exit Detail Report", "Cyan", "Attendance"),
	("Report", "Tomorrow Leave List", "Tomorrow Leave List", "Cyan", "Leave Application"),
]

PAYROLL_REPORTS = [
	("Report", "Monthly Attendance Sheet Detail", "Monthly Attendance Sheet Detail", "Green", "Attendance"),
	("Report", "Leave Balance Report", "Leave Balance Report", "Green", "Employee"),
	("Report", "Break Marking Report", "Break Marking Report", "Green", "Employee Checkin"),
	("Report", "Advance Payment Request Report", "Advance Payment Request Report", "Green", "Employee Advance"),
	("Report", "Payroll Computation Preview", "Payroll Computation Preview", "Green", "Salary Slip"),
]

SECTIONS = [
	("Inlite HR &mdash; Settings &amp; Forms", FORMS),
	("Inlite HR &mdash; Daily Reports", DAILY_REPORTS),
	("Inlite HR &mdash; Monthly &amp; Payroll", PAYROLL_REPORTS),
]


def execute():
	if not frappe.db.exists("Workspace", WORKSPACE):
		frappe.logger().info(f"enfono_hr: no {WORKSPACE} workspace — skipping shortcut patch")
		return

	doc = frappe.get_doc("Workspace", WORKSPACE)
	existing_labels = {s.label for s in doc.shortcuts}
	content = json.loads(doc.content or "[]")
	blocked_labels = {
		b.get("data", {}).get("shortcut_name")
		for b in content
		if b.get("type") == "shortcut"
	}

	added_rows, added_blocks = 0, 0

	for heading, items in SECTIONS:
		# Only lay down a heading if this section actually contributes something.
		missing = [i for i in items if i[2] not in blocked_labels]
		if not missing:
			continue

		content.append(_block("spacer", {"col": 12}))
		content.append(_block("paragraph", {"text": f"<b>{heading}</b>", "col": 12}))

		for stype, link_to, label, colour, ref_doctype in items:
			if not _target_exists(stype, link_to):
				frappe.logger().info(f"enfono_hr: {stype} {link_to!r} missing — shortcut skipped")
				continue

			if label not in existing_labels:
				row = {
					"type": stype,
					"link_to": link_to,
					"label": label,
					"color": colour,
				}
				if stype == "Report":
					# A Report shortcut without its ref doctype cannot build a route.
					row["report_ref_doctype"] = ref_doctype
					# 🔴 doc_view has a fixed option list and "Report" is NOT in it —
					# only "", List, Report Builder, Dashboard, Tree, New, Calendar,
					# Kanban. Setting "Report" throws
					# 'Row #N: DocType View cannot be "Report"'. The report route is
					# built from link_to + report_ref_doctype; doc_view is irrelevant
					# here, and every existing Report shortcut on this site uses List.
					row["doc_view"] = "List"
				doc.append("shortcuts", row)
				existing_labels.add(label)
				added_rows += 1

			if label not in blocked_labels:
				content.append(_block("shortcut", {"shortcut_name": label, "col": 3}))
				blocked_labels.add(label)
				added_blocks += 1

	doc.content = json.dumps(content)
	doc.flags.ignore_permissions = True
	doc.save()
	frappe.db.commit()
	frappe.clear_cache()

	frappe.logger().info(
		f"enfono_hr: Home workspace — {added_rows} shortcut row(s), {added_blocks} content block(s) added"
	)


def _block(block_type, data):
	return {"id": frappe.generate_hash(length=10), "type": block_type, "data": data}


def _target_exists(stype, link_to):
	return bool(frappe.db.exists("DocType" if stype == "DocType" else "Report", link_to))
