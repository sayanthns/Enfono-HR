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

import html
import json

import frappe
from frappe.utils import cstr

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
	("Report", "Monthly Attendance Register", "Monthly Attendance Register", "Green", "Attendance"),
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

	repaired = _dedupe_headings(content)
	if repaired:
		frappe.logger().info(f"enfono_hr: merged {repaired} duplicated workspace heading(s)")
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

		# 🔴 If this heading is ALREADY on the page, add the missing shortcuts to
		# it rather than writing a second copy of the heading.
		#
		# The first cut appended unconditionally. That was invisible on a fresh
		# site — every section was new — and only showed itself when a later
		# patch added one more report to an existing section: the Home page then
		# carried "Inlite HR — Monthly & Payroll" twice, the second one holding a
		# single orphaned shortcut. Caught on camera while filming the route to
		# it, which is the one place a client is guaranteed to look.
		at = _section_end(content, heading)
		if at is None:
			content.append(_block("spacer", {"col": 12}))
			content.append(_block("paragraph", {"text": f"<b>{heading}</b>", "col": 12}))
			at = len(content)

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
				content.insert(at, _block("shortcut", {"shortcut_name": label, "col": 3}))
				at += 1
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


def _norm(text):
	"""Compare headings by what they RENDER as, not by how they were written.

	🔴 This function is the whole reason a second "Inlite HR — Monthly & Payroll"
	appeared on two sites. The headings here are written with `&mdash;`, but
	Frappe stores the block with that entity already decoded to an em dash while
	leaving `&amp;` alone. A literal `==` against the source string therefore
	never matched what was on the page, the section looked absent, and a fresh
	copy of the heading was appended below the real one.
	"""
	return html.unescape(html.unescape(cstr(text))).strip()


def _dedupe_headings(content):
	"""Merge any duplicate section heading back into the first one.

	Repairs the damage the entity-matching bug already did on live sites: moves
	the orphaned shortcuts up under the original heading and removes the second
	copy along with the spacer that preceded it. Returns the number merged.
	"""
	merged = 0
	seen = {}
	i = 0
	while i < len(content):
		block = content[i]
		if block.get("type") != "paragraph":
			i += 1
			continue

		key = _norm(block.get("data", {}).get("text"))
		if key not in seen:
			seen[key] = i
			i += 1
			continue

		end = i + 1
		while end < len(content) and content[end].get("type") == "shortcut":
			end += 1
		orphans = content[i + 1 : end]

		start = i - 1 if i > 0 and content[i - 1].get("type") == "spacer" else i
		del content[start:end]

		at = seen[key] + 1
		while at < len(content) and content[at].get("type") == "shortcut":
			at += 1
		content[at:at] = orphans

		merged += 1
		seen = {}
		i = 0
	return merged


def _section_end(content, heading):
	"""Index just past the last shortcut block belonging to `heading`.

	Returns None when the heading is not on the page yet, which is the signal to
	lay a fresh one down. Walking forward from the heading and stopping at the
	next paragraph or spacer keeps a section's shortcuts together even after
	somebody has rearranged the page around them.
	"""
	needle = _norm(f"<b>{heading}</b>")
	start = None
	for i, block in enumerate(content):
		if block.get("type") == "paragraph" and _norm(block.get("data", {}).get("text")) == needle:
			start = i
			break
	if start is None:
		return None

	end = start + 1
	for block in content[start + 1 :]:
		if block.get("type") != "shortcut":
			break
		end += 1
	return end


def _target_exists(stype, link_to):
	return bool(frappe.db.exists("DocType" if stype == "DocType" else "Report", link_to))
