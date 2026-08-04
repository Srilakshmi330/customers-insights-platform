MANAGER_ROLE = "manager"
ANALYST_ROLE = "analyst"
VENDOR_ROLE = "vendor"

# Order here also drives sidebar nav order for each role.
# Manager: full control — vendors, orders, bulk uploads, and every analytics/report page.
MANAGER_CAPABILITIES = [
    "Manage Vendors",
    "Manage Orders",
    "Upload Dataset",
    "Sales Dashboard",
    "View Analytics",
    "Compare Vendors",
    "Customer Segmentation",
    "Churn Prediction",
    "Customer Reviews",
    "Generate Reports",
]

# Analyst: every analytics/report page Manager has, but no data-editing pages
# (Manage Vendors, Manage Orders, Upload Dataset). Shared pages (e.g. Customer
# Reviews) hide their write actions for this role — see streamlit_app.py.
ANALYST_CAPABILITIES = [
    "Sales Dashboard",
    "View Analytics",
    "Compare Vendors",
    "Customer Segmentation",
    "Churn Prediction",
    "Customer Reviews",
    "Generate Reports",
]

# "Inventory Monitoring" replaces the old "Check Inventory" page (Step 8) — this
# name must match the VENDOR_PAGES dict key in streamlit_app.py exactly, or
# selecting it in the sidebar will crash with a KeyError.
VENDOR_CAPABILITIES = [
    "Manage Products",
    "View Own Sales",
    "Inventory Monitoring",
    "View Recommendations",
    "Customer Insights",
]


def has_role(user, *roles):
    return user.role in roles