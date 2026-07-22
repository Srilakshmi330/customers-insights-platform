MANAGER_ROLE = "manager"
ANALYST_ROLE = "analyst"
VENDOR_ROLE = "vendor"

# Order here also drives sidebar nav order for each role.
# Manager: full control — vendors, orders, bulk uploads, and every analytics/report page.
MANAGER_CAPABILITIES = [
    "Manage Vendors",
    "Manage Orders",
    "Upload Dataset",
    "View Analytics",
    "Compare Vendors",
    "Customer Segmentation",
    "Customer Reviews",
    "Generate Reports",
]

# Analyst: every analytics/report page Manager has, but no data-editing pages
# (Manage Vendors, Manage Orders, Upload Dataset). Shared pages (e.g. Customer
# Reviews) hide their write actions for this role — see streamlit_app.py.
ANALYST_CAPABILITIES = [
    "View Analytics",
    "Compare Vendors",
    "Customer Segmentation",
    "Customer Reviews",
    "Generate Reports",
]

VENDOR_CAPABILITIES = [
    "Manage Products",
    "View Own Sales",
    "Check Inventory",
    "View Recommendations",
    "Customer Insights",
]


def has_role(user, *roles):
    return user.role in roles
