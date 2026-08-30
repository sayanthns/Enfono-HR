app_name = "enfono_hr"
app_title = "Enfono HR"
app_publisher = "siva"
app_description = "Mobile App"
app_email = "siva@enfono.in"
app_license = "mit"
# required_apps = []

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/enfono_hr/css/enfono_hr.css"
# app_include_js = "/assets/enfono_hr/js/enfono_hr.js"

# include js, css files in header of web template
# web_include_css = "/assets/enfono_hr/css/enfono_hr.css"
# web_include_js = "/assets/enfono_hr/js/enfono_hr.js"
# 🔴 Do NOT re-register test_login.js here. web_include_js loads on EVERY
# website page, and that file unconditionally rewrote the first <h1> on the
# page to "Custom Login Page" — which defaced the HR Handbook at /hr-handbook
# and every other portal page, while the served HTML was perfectly correct.
# A client-side rewrite like that is invisible to curl and to the server logs.
# web_include_js = "/assets/enfono_hr/js/enfono_hr.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "enfono_hr/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "enfono_hr/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "enfono_hr.utils.jinja_methods",
# 	"filters": "enfono_hr.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "enfono_hr.install.before_install"
# after_install = "enfono_hr.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "enfono_hr.uninstall.before_uninstall"
# after_uninstall = "enfono_hr.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "enfono_hr.utils.before_app_install"
# after_app_install = "enfono_hr.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "enfono_hr.utils.before_app_uninstall"
# after_app_uninstall = "enfono_hr.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "enfono_hr.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }
# Pretty URL for the handbook. The page itself must be named with underscores —
# a hyphenated filename cannot be imported as a Python module, so its controller
# is silently skipped and the page renders with no permission check at all.
website_route_rules = [
    {"from_route": "/hr-handbook", "to_route": "hr_handbook"},
]

doc_events = {
    "Notification Log": {
        "after_insert": "enfono_hr.firebase_notification.notification_queue"
    },
    "Employee Advance": {
        "validate": "enfono_hr.employee_advance_hooks.set_approval_route"
    },
}

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"enfono_hr.tasks.all"
# 	],
# 	"daily": [
# 		"enfono_hr.tasks.daily"
# 	],
# 	"hourly": [
# 		"enfono_hr.tasks.hourly"
# 	],
# 	"weekly": [
# 		"enfono_hr.tasks.weekly"
# 	],
# 	"monthly": [
# 		"enfono_hr.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "enfono_hr.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "enfono_hr.event.get_events"
# }
override_whitelisted_methods = {
     "frappe.core.doctype.user.user.login": "enfono_hr.api.custom_login",
     "frappe.core.doctype.user.user.logout": "enfono_hr.api.custom_logout"

}

# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "enfono_hr.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["enfono_hr.utils.before_request"]
# after_request = ["enfono_hr.utils.after_request"]

# Job Events
# ----------
# before_job = ["enfono_hr.utils.before_job"]
# after_job = ["enfono_hr.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"enfono_hr.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

