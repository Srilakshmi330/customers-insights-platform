import logging
import time
import traceback

import streamlit as st

import os
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from sqlalchemy import text

import dataset_import
import forecasting_engine
import recommendation_engine
import report_builder
import segmentation
from models import (
    Category, Customer, CustomerActivity, ForecastResult, Inventory, InventoryMovement, Order, Product,
    Promotion, Recommendation, Review, User, Vendor, init_db, seed_default_users,
)
from permissions import (
    ANALYST_CAPABILITIES, ANALYST_ROLE, MANAGER_CAPABILITIES, MANAGER_ROLE,
    VENDOR_CAPABILITIES, VENDOR_ROLE,
)
from schema import connection


PURPLE_SEQUENCE = ["#8b5cf6", "#6d28d9", "#c4b5fd", "#f59e0b", "#ef5350", "#42a5f5", "#10b981", "#0ea5e9"]

SESSION_TIMEOUT_SECONDS = 30 * 60

PRODUCT_IMAGE_DIR = "uploads/product_images"


def _save_product_image(uploaded_file, product_id):
    os.makedirs(PRODUCT_IMAGE_DIR, exist_ok=True)
    ext = os.path.splitext(uploaded_file.name)[1]
    file_path = os.path.join(PRODUCT_IMAGE_DIR, f"product_{product_id}{ext}")
    with open(file_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return file_path


def inject_theme_css():
    st.markdown(
        """
        <style>
        .stApp { background: linear-gradient(180deg, #faf8ff 0%, #ffffff 320px); }
        section[data-testid="stSidebar"] {
            background: linear-gradient(180deg, #2e1065 0%, #4c1d95 100%);
        }
        section[data-testid="stSidebar"] * { color: #ede9fe !important; }
        section[data-testid="stSidebar"] hr { border-color: rgba(237,233,254,0.25); }
        div[data-testid="stMetric"] {
            background: #ffffff;
            border: 1px solid #ede9fe;
            border-radius: 12px;
            padding: 14px 16px;
            box-shadow: 0 1px 3px rgba(109,40,217,0.08);
        }
        div[data-testid="stMetricValue"] { color: #5b21b6; }
        .stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {
            border-radius: 8px;
            border: 1px solid #7c3aed;
            color: #ffffff;
            background: linear-gradient(135deg, #8b5cf6, #6d28d9);
        }
        .stButton > button:hover, .stDownloadButton > button:hover, .stFormSubmitButton > button:hover {
            border-color: #5b21b6;
            background: linear-gradient(135deg, #7c3aed, #5b21b6);
            color: #ffffff;
        }
        h1, h2, h3 { color: #4c1d95; }
        .stTabs [data-baseweb="tab"] { font-weight: 600; }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_resource
def bootstrap():
    init_db()
    seed_default_users()
    return True


@st.cache_data(ttl=300)
def _cached_recommend_for_customer(customer_id, vendor_id):
    return recommendation_engine.recommend_for_customer(customer_id, top_n=8, vendor_id=vendor_id)


@st.cache_data(ttl=300)
def _cached_similar_collaborative(product_id):
    return recommendation_engine.similar_products_collaborative(product_id, top_n=8)


@st.cache_data(ttl=300)
def _cached_similar_content(product_id):
    return recommendation_engine.similar_products_content(product_id, top_n=8)


@st.cache_data(ttl=300)
def _cached_trending(days, vendor_id):
    return recommendation_engine.trending_products(days=days, top_n=10, vendor_id=vendor_id)


@st.cache_data(ttl=300)
def _cached_forecast(product_id, algorithm, horizon_days, unit_price):
    return forecasting_engine.forecast_product(product_id, algorithm, horizon_days=horizon_days, unit_price=unit_price)


def money(value):
    return f"${value:,.2f}"


def kpi_row(items):
    cols = st.columns(len(items))
    for col, (label, value) in zip(cols, items):
        col.metric(label, value)


def bar_chart(df, x, y, title, orientation="v"):
    if df.empty:
        st.info("No data for this selection.")
        return
    fig = px.bar(
        df, x=x if orientation == "v" else y, y=y if orientation == "v" else x,
        orientation=orientation, color_discrete_sequence=PURPLE_SEQUENCE,
    )
    fig.update_layout(title=title, margin=dict(t=40, b=10, l=10, r=10))
    st.plotly_chart(fig, width="stretch")


def pie_chart(df, names, values, title):
    if df.empty:
        st.info("No data for this selection.")
        return
    fig = px.pie(df, names=names, values=values, color_discrete_sequence=PURPLE_SEQUENCE, hole=0.35)
    fig.update_traces(textinfo="percent+label")
    fig.update_layout(title=title, margin=dict(t=40, b=10, l=10, r=10))
    st.plotly_chart(fig, width="stretch")


def line_chart(df, x, y, title):
    if df.empty:
        st.info("No data for this selection.")
        return
    fig = px.line(df, x=x, y=y, markers=True, color_discrete_sequence=PURPLE_SEQUENCE)
    fig.update_layout(title=title, margin=dict(t=40, b=10, l=10, r=10))
    st.plotly_chart(fig, width="stretch")


def area_chart(df, x, y, title):
    if df.empty:
        st.info("No data for this selection.")
        return
    fig = px.area(df, x=x, y=y, color_discrete_sequence=PURPLE_SEQUENCE)
    fig.update_layout(title=title, margin=dict(t=40, b=10, l=10, r=10))
    st.plotly_chart(fig, width="stretch")


def _do_login(username, password):
    username = username.strip()
    user = User.get_by_username(username)
    if not user:
        st.error("Invalid username or password.")
        return
    if User.is_locked(user):
        st.error("Account locked due to too many failed attempts. Try again in a few minutes.")
        return
    if User.check_password(user, password):
        User.register_successful_login(username)
        vendor = Vendor.get_by_id(user.vendor_id) if user.vendor_id else None
        st.session_state.user = {
            "username": user.username,
            "role": user.role,
            "vendor_id": user.vendor_id,
            "vendor_name": vendor.name if vendor else None,
        }
        st.session_state.last_active = time.time()
        st.rerun()
    else:
        User.register_failed_login(username)
        st.error("Invalid username or password.")


def login_view():
    inject_theme_css()
    _, center, _ = st.columns([1, 1.4, 1])
    with center:
        st.markdown("<h1 style='text-align:center;'>🛒 Infinity Mart</h1>", unsafe_allow_html=True)
        st.markdown(
            "<p style='text-align:center; color:#6b7280;'>Multi-vendor marketplace analytics</p>",
            unsafe_allow_html=True,
        )

        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", width="stretch")
        if submitted:
            _do_login(username, password)

        with st.expander("Demo accounts"):
            st.markdown(
                "- manager / manager123 — Manager\n"
                "- analyst / analyst123 — Analyst\n"
                "- vendor / vendor123 — Vendor (Demo Vendor)"
            )


ROLE_LABELS = {MANAGER_ROLE: "Manager", ANALYST_ROLE: "Analyst"}


def render_sidebar(user):
    st.sidebar.markdown("### 🛒 Infinity Mart")
    st.sidebar.caption(ROLE_LABELS.get(user["role"], f"Vendor — {user['vendor_name']}"))
    st.sidebar.divider()

    if user["role"] == MANAGER_ROLE:
        options = MANAGER_CAPABILITIES
    elif user["role"] == ANALYST_ROLE:
        options = ANALYST_CAPABILITIES
    else:
        options = VENDOR_CAPABILITIES
    page = st.sidebar.radio("Navigate", options, label_visibility="collapsed")

    st.sidebar.divider()
    st.sidebar.caption(f"**{user['username']}**")
    if st.sidebar.button("Logout"):
        st.session_state.user = None
        st.rerun()

    return page


# ---------- Admin pages ----------

def page_admin_dashboard(user):
    st.header("Admin Dashboard")
    st.caption("Platform-wide overview: revenue, orders, customers, products, top vendors, low stock, and trends.")

    with connection() as conn:
        revenue = conn.execute(text("""
            SELECT COALESCE(SUM(oi.total_price), 0)
            FROM order_items oi JOIN orders o ON o.id = oi.order_id
            WHERE o.status = 'completed'
        """)).scalar()
        order_count = conn.execute(text("SELECT COUNT(*) FROM orders")).scalar()
        customer_count = conn.execute(text("SELECT COUNT(*) FROM customers")).scalar()
        product_count = conn.execute(text("SELECT COUNT(*) FROM products")).scalar()

    kpi_row([
        ("Revenue", money(revenue)),
        ("Orders", order_count),
        ("Customers", customer_count),
        ("Products", product_count),
    ])

    if order_count == 0:
        st.info("No orders yet. Once orders exist (Manage Orders, or Upload Dataset), this dashboard fills in automatically.")
        return

    with connection() as conn:
        top_vendors = pd.read_sql_query(
            text("""
                SELECT v.name AS vendor, COALESCE(SUM(oi.total_price), 0) AS revenue
                FROM vendors v
                LEFT JOIN order_items oi ON oi.vendor_id = v.id
                LEFT JOIN orders o ON o.id = oi.order_id AND o.status = 'completed'
                GROUP BY v.name
                ORDER BY revenue DESC
                LIMIT 5
            """),
            conn,
        )
        low_stock = pd.read_sql_query(
            text("""
                SELECT p.name AS product, v.name AS vendor, i.stock_quantity, i.reorder_level
                FROM inventory i
                JOIN products p ON p.id = i.product_id
                JOIN vendors v ON v.id = p.vendor_id
                WHERE i.stock_quantity <= i.reorder_level
                ORDER BY i.stock_quantity ASC
                LIMIT 10
            """),
            conn,
        )
        daily_revenue = pd.read_sql_query(
            text("""
                SELECT CAST(o.order_date AS DATE) AS day, SUM(oi.total_price) AS revenue
                FROM order_items oi JOIN orders o ON o.id = oi.order_id
                WHERE o.status = 'completed' AND o.order_date >= NOW() - INTERVAL '60 days'
                GROUP BY day ORDER BY day
            """),
            conn,
        )

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Top Vendors")
        bar_chart(top_vendors, "vendor", "revenue", "Top 5 Vendors by Revenue")
    with c2:
        st.subheader("Low Stock")
        if low_stock.empty:
            st.success("No products at or below their reorder level right now.")
        else:
            st.dataframe(low_stock, width="stretch", hide_index=True)

    st.subheader("Sales Trend")
    line_chart(daily_revenue, "day", "revenue", "Daily Revenue (last 60 days)")

    st.subheader("Forecast")
    horizon = st.selectbox("Forecast horizon", [7, 14, 30], index=1, key="admin_forecast_horizon")
    if len(daily_revenue) < 7:
        st.info("Not enough daily revenue history yet (need at least 7 days) to project a forecast.")
    else:
        st.caption(
            "This is a simple linear trend projection based on the last 60 days of revenue — a quick "
            "baseline, not the full ML forecasting model (Random Forest / XGBoost / Prophet) planned "
            "separately for Inventory Forecasting."
        )
        history = daily_revenue.copy()
        history["day"] = pd.to_datetime(history["day"])
        x = np.arange(len(history))
        y = history["revenue"].values
        slope, intercept = np.polyfit(x, y, 1)

        future_x = np.arange(len(history), len(history) + horizon)
        future_days = pd.date_range(history["day"].max() + pd.Timedelta(days=1), periods=horizon)
        forecast_values = slope * future_x + intercept
        forecast_values = np.clip(forecast_values, 0, None)

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=history["day"], y=history["revenue"], mode="lines+markers",
            name="Actual", line=dict(color=PURPLE_SEQUENCE[1]),
        ))
        fig.add_trace(go.Scatter(
            x=future_days, y=forecast_values, mode="lines+markers",
            name="Forecast (linear trend)", line=dict(color=PURPLE_SEQUENCE[3], dash="dash"),
        ))
        fig.update_layout(
            title=f"Revenue Forecast — next {horizon} days",
            margin=dict(t=40, b=10, l=10, r=10),
        )
        st.plotly_chart(fig, width="stretch")


def page_manage_vendors(user):
    st.header("Manage Vendors")
    st.caption("Create and maintain vendor accounts on the platform.")

    vendors = Vendor.list_all()
    rows = [
        {
            "id": v.id, "name": v.name, "contact_email": v.contact_email or "—",
            "phone": v.phone or "—", "status": v.status, "created_at": v.created_at,
        }
        for v in vendors
    ]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    if vendors:
        status_counts = pd.Series([v.status for v in vendors]).value_counts().reset_index()
        status_counts.columns = ["status", "count"]
        pie_chart(status_counts, "status", "count", "Vendors by Status")

    st.subheader("Add Vendor")
    with st.form("create_vendor_form"):
        cols = st.columns(3)
        new_name = cols[0].text_input("Vendor name")
        new_email = cols[1].text_input("Contact email")
        new_phone = cols[2].text_input("Phone")
        create_submitted = st.form_submit_button("Create vendor")
    if create_submitted:
        _, error = Vendor.create(new_name, new_email, new_phone)
        if error:
            st.error(error)
        else:
            st.success(f"Created vendor {new_name}.")
            st.rerun()

    if vendors:
        st.subheader("Edit / Remove Vendor")
        names = [v.name for v in vendors]
        selected_name = st.selectbox("Select vendor", names, key="manage_vendor_select")
        selected = next((v for v in vendors if v.name == selected_name), None)
        if selected:
            cols = st.columns(4)
            edit_email = cols[0].text_input("Contact email", value=selected.contact_email or "", key="edit_vendor_email")
            edit_phone = cols[1].text_input("Phone", value=selected.phone or "", key="edit_vendor_phone")
            edit_status = cols[2].selectbox(
                "Status", ["active", "inactive"],
                index=["active", "inactive"].index(selected.status), key="edit_vendor_status",
            )
            if cols[3].button("Save changes"):
                Vendor.update(selected.id, selected.name, edit_email, edit_phone, edit_status)
                st.success("Vendor updated.")
                st.rerun()
            if st.button("Delete vendor", key="delete_vendor_btn"):
                Vendor.delete(selected.id)
                st.success(f"Deleted {selected.name}.")
                st.rerun()

    st.divider()
    st.subheader("Vendor Logins")
    st.caption("Create the login account a vendor uses to sign in.")
    users = User.list_all()
    user_rows = [
        {
            "username": u.username, "role": u.role,
            "vendor": next((v.name for v in vendors if v.id == u.vendor_id), "—"),
            "locked": "Yes" if User.is_locked(u) else "No",
        }
        for u in users
    ]
    st.dataframe(pd.DataFrame(user_rows), width="stretch", hide_index=True)

    if vendors:
        with st.form("create_vendor_login_form"):
            cols = st.columns(4)
            new_username = cols[0].text_input("Username")
            new_password = cols[1].text_input("Password", type="password")
            new_role = cols[2].selectbox("Role", ["vendor", "analyst", "manager"], key="new_login_role")
            vendor_choice = cols[3].selectbox("Vendor", names, key="new_login_vendor")
            login_submitted = st.form_submit_button("Create login")
        if login_submitted:
            vendor_id = next(v.id for v in vendors if v.name == vendor_choice) if new_role == "vendor" else None
            _, error = User.create(new_username, new_password, new_role, vendor_id)
            if error:
                st.error(error)
            else:
                st.success(f"Created login for {new_username}.")
                st.rerun()


def page_manage_orders(user):
    st.header("Manage Orders")
    st.caption("Record customer orders across all vendors — this is what feeds Analytics, Compare Vendors, and vendor sales/inventory data.")

    orders = Order.list_all()
    if orders:
        orders_df = pd.DataFrame(orders)
        kpi_row([
            ("Orders", len(orders_df)),
            ("Revenue", money(orders_df["total_amount"].sum())),
            ("Completed", int((orders_df["status"] == "completed").sum())),
            ("Cancelled", int((orders_df["status"] == "cancelled").sum())),
        ])

        c1, c2 = st.columns(2)
        with c1:
            status_counts = orders_df["status"].value_counts().reset_index()
            status_counts.columns = ["status", "count"]
            pie_chart(status_counts, "status", "count", "Orders by Status")
        with c2:
            trend_df = orders_df.copy()
            trend_df["day"] = pd.to_datetime(trend_df["order_date"], errors="coerce").dt.date
            by_day = trend_df.dropna(subset=["day"]).groupby("day")["total_amount"].sum().reset_index()
            bar_chart(by_day, "day", "total_amount", "Revenue by Day")

        st.dataframe(orders_df, width="stretch", hide_index=True)
    else:
        st.info("No orders yet. Create the first one below.")

    st.divider()
    st.subheader("Create Order")

    products = Product.list_all_active()
    if not products:
        st.info("No products available yet — a vendor needs to add products first (Manage Products).")
        return

    customers = Customer.list_all()
    cols = st.columns(3)
    customer_choice = cols[0].selectbox("Customer", ["(new customer)"] + [c.name for c in customers])
    new_customer_name = cols[1].text_input("New customer name (if above is '(new customer)')")
    new_customer_email = cols[2].text_input("New customer email (optional)")

    label_to_id = {
        f"{p['vendor']} — {p['name']} (${p['unit_price']:.2f}, {p['stock_quantity']} in stock)": p["id"]
        for p in products
    }
    labels = list(label_to_id.keys())

    line_items_df = st.data_editor(
        pd.DataFrame([{"Product": labels[0], "Quantity": 1}]),
        column_config={
            "Product": st.column_config.SelectboxColumn("Product", options=labels, required=True),
            "Quantity": st.column_config.NumberColumn("Quantity", min_value=1, step=1, required=True),
        },
        num_rows="dynamic",
        width="stretch",
        key="order_line_items",
    )
    payment_method = st.selectbox("Payment method", ["cash", "card", "upi", "wallet"])

    if st.button("Place order", type="primary"):
        if customer_choice == "(new customer)":
            if not new_customer_name.strip():
                st.error("Enter a name for the new customer.")
                return
            customer, cust_error = Customer.create(new_customer_name, new_customer_email)
            if cust_error:
                st.error(cust_error)
                return
            customer_id = customer.id
        else:
            customer_id = next(c.id for c in customers if c.name == customer_choice)

        items = []
        for _, row in line_items_df.iterrows():
            product_label = row.get("Product")
            qty = row.get("Quantity")
            if not product_label or product_label not in label_to_id or not qty:
                continue
            items.append({"product_id": label_to_id[product_label], "quantity": int(qty)})

        order_id, error = Order.create_with_items(customer_id, items, payment_method)
        if error:
            st.error(error)
        else:
            st.session_state.pop("order_line_items", None)
            st.success(f"Created order #{order_id}.")
            st.rerun()


def page_upload_dataset(user):
    st.header("Upload Dataset")
    st.caption("Bulk-import transactions from a CSV file directly into the platform database.")

    with st.expander("Expected CSV columns"):
        st.markdown(dataset_import.COLUMN_HELP)

    uploaded = st.file_uploader("Choose a CSV file", type="csv")
    if uploaded is None:
        return

    df, error = dataset_import.validate_csv(uploaded)
    if df is None:
        st.error(error)
        return
    if error:
        st.warning(error)

    st.write(f"{len(df)} row(s) ready to import.")
    st.dataframe(df.head(20), width="stretch", hide_index=True)

    if st.button("Import into database", type="primary"):
        with st.spinner("Importing..."):
            summary = dataset_import.import_transactions(df)
        st.success(f"Imported {summary['orders_created']} order(s) from {summary['rows_processed']} row(s).")
        if summary["errors"]:
            st.warning(f"{len(summary['errors'])} row group(s) skipped due to errors:")
            st.dataframe(pd.DataFrame(summary["errors"]), width="stretch", hide_index=True)


def page_customer_dashboard(user):
    st.header("Customer Dashboard")
    st.caption("New vs. returning customers, retention, churn, and lifetime value.")

    period_days = st.selectbox(
        "Period for New / Returning / Retention / Churn "
        "(compares this period vs. the same-length period right before it)",
        [30, 90, 180], index=0, format_func=lambda d: f"Last {d} days", key="customer_dashboard_period",
    )

    with connection() as conn:
        first_order_df = pd.read_sql_query(
            text("SELECT customer_id, MIN(order_date) AS first_order_date FROM orders GROUP BY customer_id"),
            conn,
        )
        current_df = pd.read_sql_query(
            text(f"""
                SELECT DISTINCT customer_id FROM orders
                WHERE order_date >= NOW() - INTERVAL '{period_days} days'
            """),
            conn,
        )
        previous_df = pd.read_sql_query(
            text(f"""
                SELECT DISTINCT customer_id FROM orders
                WHERE order_date >= NOW() - INTERVAL '{period_days * 2} days'
                  AND order_date < NOW() - INTERVAL '{period_days} days'
            """),
            conn,
        )
        clv_row = conn.execute(text("""
            SELECT COUNT(DISTINCT o.customer_id) AS customers, COALESCE(SUM(oi.total_price), 0) AS revenue
            FROM order_items oi JOIN orders o ON o.id = oi.order_id
            WHERE o.status = 'completed'
        """)).first()
        monthly_orders_df = pd.read_sql_query(
            text("""
                SELECT customer_id, TO_CHAR(order_date, 'YYYY-MM') AS month
                FROM orders
                WHERE order_date >= NOW() - INTERVAL '12 months'
            """),
            conn,
        )

    if first_order_df.empty:
        st.info("No orders yet. Record orders under Manage Orders, or import a dataset, to populate this dashboard.")
        return

    first_order_map = dict(zip(first_order_df["customer_id"], pd.to_datetime(first_order_df["first_order_date"])))
    period_start = pd.Timestamp.now() - pd.Timedelta(days=period_days)

    current_customers = set(current_df["customer_id"])
    previous_customers = set(previous_df["customer_id"])

    new_customers = {c for c in current_customers if first_order_map.get(c, period_start) >= period_start}
    returning_customers = current_customers - new_customers
    retained = current_customers & previous_customers

    retention_pct = round(100 * len(retained) / len(previous_customers), 1) if previous_customers else 0.0
    churn_pct = round(100 - retention_pct, 1) if previous_customers else 0.0

    clv = round(clv_row.revenue / clv_row.customers, 2) if clv_row.customers else 0.0

    kpi_row([
        ("New Customers", len(new_customers)),
        ("Returning Customers", len(returning_customers)),
        ("Retention %", f"{retention_pct}%"),
        ("Churn %", f"{churn_pct}%"),
        ("CLV (lifetime avg)", money(clv)),
    ])
    st.caption(
        "Retention % = customers active in the previous period who were also active this period, "
        "as a share of the previous period's active customers. Churn % is the rest of that group. "
        "CLV here is a lifetime average (total completed revenue ÷ customers who've ever ordered), "
        "not a predictive/discounted CLV model."
    )

    if not monthly_orders_df.empty:
        monthly_orders_df["first_month"] = monthly_orders_df["customer_id"].map(
            lambda c: first_order_map.get(c).strftime("%Y-%m") if c in first_order_map else None
        )
        monthly_orders_df = monthly_orders_df.drop_duplicates(subset=["customer_id", "month"])
        monthly_orders_df["type"] = monthly_orders_df.apply(
            lambda r: "New" if r["month"] == r["first_month"] else "Returning", axis=1,
        )
        monthly_summary = (
            monthly_orders_df.groupby(["month", "type"])["customer_id"]
            .nunique()
            .reset_index(name="customers")
            .sort_values("month")
        )

        st.subheader("New vs. Returning Customers by Month")
        fig = px.bar(
            monthly_summary, x="month", y="customers", color="type", barmode="group",
            color_discrete_sequence=PURPLE_SEQUENCE,
        )
        fig.update_layout(title="New vs. Returning Customers (last 12 months)", margin=dict(t=40, b=10, l=10, r=10))
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("Not enough recent order history to chart monthly new/returning customers.")

    c1, c2 = st.columns(2)
    with c1:
        breakdown = pd.DataFrame([
            {"segment": "New", "count": len(new_customers)},
            {"segment": "Returning", "count": len(returning_customers)},
        ])
        pie_chart(breakdown, "segment", "count", f"New vs. Returning (last {period_days} days)")
    with c2:
        retention_breakdown = pd.DataFrame([
            {"segment": "Retained", "count": len(retained)},
            {"segment": "Churned", "count": max(len(previous_customers) - len(retained), 0)},
        ])
        pie_chart(retention_breakdown, "segment", "count", f"Retention vs. Churn (of {len(previous_customers)} prior active customers)")


def page_customer_segmentation(user):
    st.header("Customer Segmentation")
    st.caption(
        "Groups every customer into Premium, Regular, Occasional, or Inactive using KMeans clustering "
        "on order frequency, total spend, average basket size, and recency (days since last order)."
    )

    result = segmentation.run_segmentation()
    if not result["available"]:
        st.info("Not enough customer history yet to segment customers — record more orders first.")
        return

    customers = result["customers"]
    summary = result["summary"]

    kpi_row([
        ("Customers Segmented", len(customers)),
        ("Segments", summary["segment"].nunique()),
        ("Inactive Customers", int(summary.loc[summary["segment"] == "Inactive", "customers"].sum())),
    ])

    c1, c2 = st.columns(2)
    with c1:
        pie_chart(summary, "segment", "customers", "Customers by Segment")
    with c2:
        bar_chart(summary, "segment", "avg_spend", "Average Spend by Segment")

    fig = px.scatter(
        customers, x="order_count", y="total_spend", color="segment",
        color_discrete_sequence=PURPLE_SEQUENCE, title="Customer Clusters (Orders vs. Spend)",
        labels={"order_count": "Orders", "total_spend": "Total Spend"},
        hover_data=["days_since_last_order"],
    )
    fig.update_layout(margin=dict(t=40, b=10, l=10, r=10))
    st.plotly_chart(fig, width="stretch")

    st.subheader("Segment Summary")
    st.dataframe(summary, width="stretch", hide_index=True)

    st.subheader("Customer Assignments")
    display_cols = customers[[
        "customer", "order_count", "total_spend", "avg_order_value", "days_since_last_order", "segment",
    ]]
    st.dataframe(display_cols, width="stretch", hide_index=True)
    st.download_button(
        "Download Segmentation CSV", data=display_cols.to_csv(index=False),
        file_name="customer_segments.csv", mime="text/csv",
    )


def page_sales_dashboard(user):
    st.header("Sales Dashboard")
    st.caption("Revenue, orders, and sales trends across the platform.")

    period_days = st.selectbox(
        "Period for Daily Sales", [7, 30, 90], index=1,
        format_func=lambda d: f"Last {d} days", key="sales_dashboard_period",
    )
    margin_pct = st.slider(
        "Assumed profit margin % (for the Profit estimate below)",
        min_value=5, max_value=80, value=30, step=5,
        help="Your data doesn't store product cost, so Profit can't be calculated exactly. "
             "This applies an assumed margin to Revenue as an estimate — adjust it to match "
             "your real margins.",
    )

    with connection() as conn:
        gmv = conn.execute(text("SELECT COALESCE(SUM(total_amount), 0) FROM orders")).scalar()
        revenue = conn.execute(text("""
            SELECT COALESCE(SUM(oi.total_price), 0)
            FROM order_items oi JOIN orders o ON o.id = oi.order_id
            WHERE o.status = 'completed'
        """)).scalar()
        order_count = conn.execute(text("SELECT COUNT(*) FROM orders")).scalar()
        completed_order_count = conn.execute(
            text("SELECT COUNT(*) FROM orders WHERE status = 'completed'")
        ).scalar()

    aov = round(revenue / completed_order_count, 2) if completed_order_count else 0
    profit_estimate = round(revenue * (margin_pct / 100), 2)

    kpi_row([
        ("GMV", money(gmv)),
        ("Revenue", money(revenue)),
        (f"Profit (est. {margin_pct}%)", money(profit_estimate)),
        ("Orders", order_count),
        ("Avg Order Value", money(aov)),
    ])

    if order_count == 0:
        st.info("No orders yet. Record orders under Manage Orders, or import a dataset, to populate this dashboard.")
        return

    with connection() as conn:
        daily = pd.read_sql_query(
            text(f"""
                SELECT CAST(o.order_date AS DATE) AS day, SUM(oi.total_price) AS revenue
                FROM order_items oi
                JOIN orders o ON o.id = oi.order_id
                WHERE o.status = 'completed' AND o.order_date >= NOW() - INTERVAL '{period_days} days'
                GROUP BY day ORDER BY day
            """),
            conn,
        )
        monthly = pd.read_sql_query(
            text("""
                SELECT TO_CHAR(o.order_date, 'YYYY-MM') AS month, SUM(oi.total_price) AS revenue
                FROM order_items oi
                JOIN orders o ON o.id = oi.order_id
                WHERE o.status = 'completed' AND o.order_date >= NOW() - INTERVAL '12 months'
                GROUP BY month ORDER BY month
            """),
            conn,
        )
        status_counts = pd.read_sql_query(
            text("SELECT status, COUNT(*) AS count FROM orders GROUP BY status"), conn,
        )
        by_payment = pd.read_sql_query(
            text("""
                SELECT COALESCE(p.method, 'unknown') AS payment_method, SUM(p.amount) AS revenue
                FROM payments p
                WHERE p.status = 'paid'
                GROUP BY payment_method ORDER BY revenue DESC
            """),
            conn,
        )

    st.subheader("Daily Sales")
    line_chart(daily, "day", "revenue", f"Revenue by Day (last {period_days} days)")

    st.subheader("Monthly Sales")
    area_chart(monthly, "month", "revenue", "Revenue by Month (last 12 months)")

    c1, c2 = st.columns(2)
    with c1:
        pie_chart(status_counts, "status", "count", "Orders by Status")
    with c2:
        bar_chart(by_payment, "payment_method", "revenue", "Revenue by Payment Method")


def page_vendor_performance(user):
    st.header("Vendor Performance")
    st.caption("Revenue, fulfillment, growth, and ratings by vendor — ranked by revenue.")

    period_days = st.selectbox(
        "Period for Growth % (compares this period vs. the same-length period before it)",
        [7, 30, 90], index=1, format_func=lambda d: f"Last {d} days", key="vendor_perf_period",
    )

    with connection() as conn:
        vendors_df = pd.read_sql_query(text("SELECT id, name FROM vendors"), conn)

        orders_df = pd.read_sql_query(
            text("""
                SELECT vendor_id,
                       COUNT(*) AS orders,
                       SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed_orders,
                       SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled_orders
                FROM (
                    SELECT DISTINCT oi.vendor_id, oi.order_id, o.status
                    FROM order_items oi JOIN orders o ON o.id = oi.order_id
                ) vendor_orders
                GROUP BY vendor_id
            """),
            conn,
        )

        revenue_df = pd.read_sql_query(
            text("""
                SELECT oi.vendor_id, SUM(oi.total_price) AS revenue
                FROM order_items oi JOIN orders o ON o.id = oi.order_id
                WHERE o.status = 'completed'
                GROUP BY oi.vendor_id
            """),
            conn,
        )

        current_revenue_df = pd.read_sql_query(
            text(f"""
                SELECT oi.vendor_id, SUM(oi.total_price) AS revenue
                FROM order_items oi JOIN orders o ON o.id = oi.order_id
                WHERE o.status = 'completed' AND o.order_date >= NOW() - INTERVAL '{period_days} days'
                GROUP BY oi.vendor_id
            """),
            conn,
        )

        previous_revenue_df = pd.read_sql_query(
            text(f"""
                SELECT oi.vendor_id, SUM(oi.total_price) AS revenue
                FROM order_items oi JOIN orders o ON o.id = oi.order_id
                WHERE o.status = 'completed'
                  AND o.order_date >= NOW() - INTERVAL '{period_days * 2} days'
                  AND o.order_date < NOW() - INTERVAL '{period_days} days'
                GROUP BY oi.vendor_id
            """),
            conn,
        )

        rating_df = pd.read_sql_query(
            text("""
                SELECT p.vendor_id, AVG(r.rating) AS avg_rating, COUNT(r.id) AS review_count
                FROM reviews r JOIN products p ON p.id = r.product_id
                GROUP BY p.vendor_id
            """),
            conn,
        )

    if vendors_df.empty:
        st.info("No vendors yet — add one under Manage Vendors.")
        return

    df = vendors_df.rename(columns={"id": "vendor_id", "name": "vendor"})
    df = df.merge(orders_df, on="vendor_id", how="left")
    df = df.merge(revenue_df, on="vendor_id", how="left")
    df = df.merge(current_revenue_df.rename(columns={"revenue": "current_revenue"}), on="vendor_id", how="left")
    df = df.merge(previous_revenue_df.rename(columns={"revenue": "previous_revenue"}), on="vendor_id", how="left")
    df = df.merge(rating_df, on="vendor_id", how="left")

    for col in ["orders", "completed_orders", "cancelled_orders"]:
        df[col] = df[col].fillna(0).astype(int)
    for col in ["revenue", "current_revenue", "previous_revenue", "avg_rating"]:
        df[col] = df[col].fillna(0.0)
    df["review_count"] = df["review_count"].fillna(0).astype(int)

    df["fulfillment_pct"] = df.apply(
        lambda r: round(100 * r["completed_orders"] / r["orders"], 1) if r["orders"] else 0.0, axis=1,
    )
    df["refund_pct"] = df.apply(
        lambda r: round(100 * r["cancelled_orders"] / r["orders"], 1) if r["orders"] else 0.0, axis=1,
    )
    df["growth_pct"] = df.apply(
        lambda r: round(100 * (r["current_revenue"] - r["previous_revenue"]) / r["previous_revenue"], 1)
        if r["previous_revenue"] else (100.0 if r["current_revenue"] > 0 else 0.0),
        axis=1,
    )

    df = df.sort_values("revenue", ascending=False).reset_index(drop=True)
    df.insert(0, "rank", df.index + 1)

    kpi_row([
        ("Vendors", len(df)),
        ("Total Revenue", money(df["revenue"].sum())),
        ("Avg Fulfillment %", f"{df['fulfillment_pct'].mean():.1f}%"),
        ("Avg Refund %", f"{df['refund_pct'].mean():.1f}%"),
    ])
    st.caption(
        "Refund % is approximated as cancelled orders ÷ total orders per vendor (your data doesn't have a "
        "separate refund flag beyond order status). Growth % compares the selected period's revenue to the "
        "same-length period right before it."
    )

    c1, c2 = st.columns(2)
    with c1:
        bar_chart(df, "vendor", "revenue", "Revenue by Vendor")
    with c2:
        bar_chart(df, "vendor", "growth_pct", f"Growth % (last {period_days} days vs. prior {period_days} days)")

    st.subheader("Vendor Ranking")
    display_df = df[[
        "rank", "vendor", "revenue", "orders", "avg_rating", "review_count",
        "fulfillment_pct", "growth_pct", "refund_pct",
    ]].rename(columns={
        "vendor": "Vendor", "revenue": "Revenue", "orders": "Orders",
        "avg_rating": "Avg Rating", "review_count": "Reviews",
        "fulfillment_pct": "Fulfillment %", "growth_pct": "Growth %", "refund_pct": "Refund %",
    })
    display_df["Avg Rating"] = display_df["Avg Rating"].round(2)
    st.dataframe(display_df, width="stretch", hide_index=True)
    st.download_button(
        "Download Vendor Performance CSV", data=display_df.to_csv(index=False),
        file_name="vendor_performance.csv", mime="text/csv",
    )


def page_view_analytics(user):
    st.header("View Analytics")
    st.caption("Platform-wide performance across all vendors.")

    with connection() as conn:
        order_count = conn.execute(text("SELECT COUNT(*) FROM orders")).scalar()
        revenue = conn.execute(text("SELECT COALESCE(SUM(total_price), 0) FROM order_items")).scalar()
        vendor_count = conn.execute(text("SELECT COUNT(*) FROM vendors")).scalar()
        product_count = conn.execute(text("SELECT COUNT(*) FROM products")).scalar()

    kpi_row([
        ("Total Revenue", money(revenue)),
        ("Orders", order_count),
        ("Vendors", vendor_count),
        ("Products", product_count),
    ])

    if order_count == 0:
        st.info(
            "No orders yet. Head to Manage Orders to record the first one — "
            "this page will chart revenue and order trends automatically once orders exist."
        )
        return

    with connection() as conn:
        by_vendor = pd.read_sql_query(
            text("""
            SELECT v.name AS vendor, SUM(oi.total_price) AS revenue
            FROM order_items oi
            JOIN vendors v ON v.id = oi.vendor_id
            GROUP BY v.name
            ORDER BY revenue DESC
            """),
            conn,
        )
        top_products = pd.read_sql_query(
            text("""
            SELECT p.name AS product, SUM(oi.total_price) AS revenue
            FROM order_items oi
            JOIN products p ON p.id = oi.product_id
            GROUP BY p.name
            ORDER BY revenue DESC
            LIMIT 10
            """),
            conn,
        )
        status_counts = pd.read_sql_query(
            text("SELECT status, COUNT(*) AS count FROM orders GROUP BY status"), conn,
        )
        revenue_trend = pd.read_sql_query(
            text("""
            SELECT CAST(o.order_date AS DATE) AS day, SUM(oi.total_price) AS revenue
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            GROUP BY day
            ORDER BY day
            """),
            conn,
        )

    c1, c2 = st.columns(2)
    with c1:
        bar_chart(by_vendor, "vendor", "revenue", "Revenue by Vendor")
    with c2:
        pie_chart(by_vendor, "vendor", "revenue", "Revenue Share by Vendor")

    c3, c4 = st.columns(2)
    with c3:
        bar_chart(top_products, "product", "revenue", "Top 10 Products by Revenue")
    with c4:
        pie_chart(status_counts, "status", "count", "Orders by Status")

    bar_chart(revenue_trend, "day", "revenue", "Revenue Trend by Day")


def page_compare_vendors(user):
    st.header("Compare Vendors")
    st.caption("Side-by-side vendor performance.")

    with connection() as conn:
        comparison = pd.read_sql_query(
            text("""
            SELECT
                v.name AS vendor,
                v.status,
                COUNT(DISTINCT p.id) AS products,
                COALESCE(SUM(oi.total_price), 0) AS revenue,
                COUNT(DISTINCT oi.order_id) AS orders
            FROM vendors v
            LEFT JOIN products p ON p.vendor_id = v.id
            LEFT JOIN order_items oi ON oi.vendor_id = v.id
            GROUP BY v.name, v.status
            ORDER BY revenue DESC, products DESC
            """),
            conn,
        )

    if comparison.empty:
        st.info("No vendors yet — add one under Manage Vendors.")
        return

    c1, c2 = st.columns(2)
    with c1:
        bar_chart(comparison, "vendor", "products", "Products Listed by Vendor")
    with c2:
        bar_chart(comparison, "vendor", "revenue", "Revenue by Vendor")

    revenue_share = comparison[comparison["revenue"] > 0]
    if not revenue_share.empty:
        pie_chart(revenue_share, "vendor", "revenue", "Market Share by Revenue")

    st.subheader("Comparison Table")
    st.dataframe(comparison, width="stretch", hide_index=True)


def page_customer_reviews(user):
    st.header("Customer Reviews")
    st.caption("Ratings and feedback customers have left on products.")

    reviews = Review.list_all()
    if reviews:
        reviews_df = pd.DataFrame(reviews)
        kpi_row([
            ("Reviews", len(reviews_df)),
            ("Average Rating", round(reviews_df["rating"].mean(), 2)),
        ])
        c1, c2 = st.columns(2)
        with c1:
            rating_counts = reviews_df["rating"].value_counts().sort_index().reset_index()
            rating_counts.columns = ["rating", "count"]
            pie_chart(rating_counts, "rating", "count", "Rating Distribution")
        with c2:
            by_vendor = reviews_df.groupby("vendor")["rating"].mean().round(2).reset_index()
            bar_chart(by_vendor, "vendor", "rating", "Average Rating by Vendor")
        st.dataframe(reviews_df, width="stretch", hide_index=True)
    else:
        st.info("No reviews yet — add one below.")

    if user["role"] != MANAGER_ROLE:
        st.caption("Read-only — sign in as a Manager to add reviews.")
        return

    st.divider()
    st.subheader("Add Review")
    customers = Customer.list_all()
    products = Product.list_all_active()
    if not customers or not products:
        st.info("Record an order under Manage Orders first — that creates the customers and products a review needs.")
        return

    product_labels = [f"{p['vendor']} — {p['name']}" for p in products]
    with st.form("add_review_form"):
        cols = st.columns(4)
        customer_choice = cols[0].selectbox("Customer", [c.name for c in customers])
        product_choice = cols[1].selectbox("Product", product_labels)
        rating = cols[2].slider("Rating", 1, 5, 5)
        comment = cols[3].text_input("Comment")
        submitted = st.form_submit_button("Add review")
    if submitted:
        customer_id = next(c.id for c in customers if c.name == customer_choice)
        product_id = next(p["id"] for p, label in zip(products, product_labels) if label == product_choice)
        _, error = Review.create(product_id, customer_id, rating, comment)
        if error:
            st.error(error)
        else:
            st.success("Review added.")
            st.rerun()


def page_generate_reports(user):
    st.header("Generate Reports")
    st.caption("Sales, Inventory, Vendor, and Customer reports — each exportable as PDF or CSV.")

    tab_sales, tab_inventory, tab_vendor, tab_customer = st.tabs(
        ["Sales Report", "Inventory Report", "Vendor Report", "Customer Report"]
    )

    # ---------- Sales Report ----------
    with tab_sales:
        with connection() as conn:
            gmv = conn.execute(text("SELECT COALESCE(SUM(total_amount), 0) FROM orders")).scalar()
            revenue = conn.execute(text("""
                SELECT COALESCE(SUM(oi.total_price), 0)
                FROM order_items oi JOIN orders o ON o.id = oi.order_id
                WHERE o.status = 'completed'
            """)).scalar()
            order_count = conn.execute(text("SELECT COUNT(*) FROM orders")).scalar()
            completed_order_count = conn.execute(
                text("SELECT COUNT(*) FROM orders WHERE status = 'completed'")
            ).scalar()
            by_status_df = pd.read_sql_query(
                text("SELECT status, COUNT(*) AS count FROM orders GROUP BY status"), conn,
            )
            by_payment_df = pd.read_sql_query(
                text("""
                    SELECT COALESCE(p.method, 'unknown') AS payment_method, SUM(p.amount) AS revenue
                    FROM payments p WHERE p.status = 'paid' GROUP BY payment_method ORDER BY revenue DESC
                """),
                conn,
            )
            monthly_df = pd.read_sql_query(
                text("""
                    SELECT TO_CHAR(o.order_date, 'YYYY-MM') AS month, SUM(oi.total_price) AS revenue
                    FROM order_items oi JOIN orders o ON o.id = oi.order_id
                    WHERE o.status = 'completed' AND o.order_date >= NOW() - INTERVAL '12 months'
                    GROUP BY month ORDER BY month
                """),
                conn,
            )
            orders_detail_df = pd.read_sql_query(
                text("""
                    SELECT o.id AS order_id, o.order_date, o.status, c.name AS customer,
                           p.name AS product, v.name AS vendor, oi.quantity, oi.total_price
                    FROM order_items oi
                    JOIN orders o ON o.id = oi.order_id
                    JOIN customers c ON c.id = o.customer_id
                    JOIN products p ON p.id = oi.product_id
                    JOIN vendors v ON v.id = oi.vendor_id
                    ORDER BY o.order_date DESC
                """),
                conn,
            )

        aov = round(revenue / completed_order_count, 2) if completed_order_count else 0.0
        kpi_row([
            ("GMV", money(gmv)), ("Revenue", money(revenue)),
            ("Orders", order_count), ("Avg Order Value", money(aov)),
        ])
        st.dataframe(orders_detail_df, width="stretch", hide_index=True)

        sales_data = {
            "total_revenue": revenue, "gmv": gmv, "order_count": order_count,
            "completed_order_count": completed_order_count, "aov": aov,
            "by_status": by_status_df.to_dict("records"),
            "by_payment": by_payment_df.to_dict("records"),
            "monthly": monthly_df.to_dict("records"),
        }
        cols = st.columns(2)
        cols[0].download_button(
            "Download Sales Report PDF",
            data=report_builder.build_sales_report_pdf(sales_data, user["username"]),
            file_name="sales_report.pdf", mime="application/pdf", key="sales_pdf",
        )
        cols[1].download_button(
            "Download Sales Report CSV",
            data=orders_detail_df.to_csv(index=False),
            file_name="sales_report.csv", mime="text/csv", key="sales_csv",
        )

    # ---------- Inventory Report ----------
    with tab_inventory:
        with connection() as conn:
            product_count = conn.execute(text("SELECT COUNT(*) FROM products")).scalar()
            total_stock = conn.execute(text("SELECT COALESCE(SUM(stock_quantity), 0) FROM inventory")).scalar()
            low_stock_count = conn.execute(text("""
                SELECT COUNT(*) FROM inventory WHERE stock_quantity <= reorder_level AND stock_quantity > 0
            """)).scalar()
            out_of_stock_count = conn.execute(
                text("SELECT COUNT(*) FROM inventory WHERE stock_quantity <= 0")
            ).scalar()
            inventory_detail_df = pd.read_sql_query(
                text("""
                    SELECT p.name AS product, v.name AS vendor, COALESCE(c.name, 'Uncategorized') AS category,
                           p.unit_price, i.stock_quantity, i.reorder_level
                    FROM products p
                    JOIN vendors v ON v.id = p.vendor_id
                    LEFT JOIN categories c ON c.id = p.category_id
                    LEFT JOIN inventory i ON i.product_id = p.id
                    ORDER BY v.name, p.name
                """),
                conn,
            )
            low_stock_df = pd.read_sql_query(
                text("""
                    SELECT p.name AS product, v.name AS vendor, i.stock_quantity, i.reorder_level
                    FROM inventory i
                    JOIN products p ON p.id = i.product_id
                    JOIN vendors v ON v.id = p.vendor_id
                    WHERE i.stock_quantity <= i.reorder_level
                    ORDER BY i.stock_quantity ASC
                """),
                conn,
            )

        kpi_row([
            ("Products", product_count), ("Total Stock (units)", int(total_stock)),
            ("Low Stock Items", low_stock_count), ("Out of Stock Items", out_of_stock_count),
        ])
        st.dataframe(inventory_detail_df, width="stretch", hide_index=True)

        inventory_data = {
            "product_count": product_count, "total_stock": int(total_stock),
            "low_stock_count": low_stock_count, "out_of_stock_count": out_of_stock_count,
            "low_stock": low_stock_df.to_dict("records"),
        }
        cols = st.columns(2)
        cols[0].download_button(
            "Download Inventory Report PDF",
            data=report_builder.build_inventory_report_pdf(inventory_data, user["username"]),
            file_name="inventory_report.pdf", mime="application/pdf", key="inventory_pdf",
        )
        cols[1].download_button(
            "Download Inventory Report CSV",
            data=inventory_detail_df.to_csv(index=False),
            file_name="inventory_report.csv", mime="text/csv", key="inventory_csv",
        )

    # ---------- Vendor Report ----------
    with tab_vendor:
        with connection() as conn:
            vendor_perf_df = pd.read_sql_query(
                text("""
                    SELECT
                        v.id AS vendor_id, v.name AS vendor,
                        COALESCE(SUM(oi.total_price), 0) AS revenue,
                        COUNT(DISTINCT oi.order_id) AS orders,
                        COALESCE(AVG(r.rating), 0) AS avg_rating
                    FROM vendors v
                    LEFT JOIN order_items oi ON oi.vendor_id = v.id
                    LEFT JOIN orders o ON o.id = oi.order_id AND o.status = 'completed'
                    LEFT JOIN products p ON p.vendor_id = v.id
                    LEFT JOIN reviews r ON r.product_id = p.id
                    GROUP BY v.id, v.name
                """),
                conn,
            )
            fulfillment_df = pd.read_sql_query(
                text("""
                    SELECT vendor_id,
                           SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed_orders,
                           SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled_orders,
                           COUNT(*) AS total_orders
                    FROM (
                        SELECT DISTINCT oi.vendor_id, oi.order_id, o.status
                        FROM order_items oi JOIN orders o ON o.id = oi.order_id
                    ) t
                    GROUP BY vendor_id
                """),
                conn,
            )

        vendor_perf_df = vendor_perf_df.merge(fulfillment_df, on="vendor_id", how="left")
        vendor_perf_df[["completed_orders", "cancelled_orders", "total_orders"]] = vendor_perf_df[
            ["completed_orders", "cancelled_orders", "total_orders"]
        ].fillna(0)
        vendor_perf_df["fulfillment_pct"] = vendor_perf_df.apply(
            lambda r: round(100 * r["completed_orders"] / r["total_orders"], 1) if r["total_orders"] else 0.0, axis=1,
        )
        vendor_perf_df["refund_pct"] = vendor_perf_df.apply(
            lambda r: round(100 * r["cancelled_orders"] / r["total_orders"], 1) if r["total_orders"] else 0.0, axis=1,
        )
        vendor_perf_df = vendor_perf_df.sort_values("revenue", ascending=False).reset_index(drop=True)

        kpi_row([
            ("Vendors", len(vendor_perf_df)),
            ("Total Revenue", money(vendor_perf_df["revenue"].sum())),
            ("Avg Fulfillment %", f"{vendor_perf_df['fulfillment_pct'].mean():.1f}%"),
            ("Avg Refund %", f"{vendor_perf_df['refund_pct'].mean():.1f}%"),
        ])
        display_df = vendor_perf_df[["vendor", "revenue", "orders", "avg_rating", "fulfillment_pct", "refund_pct"]]
        st.dataframe(display_df, width="stretch", hide_index=True)

        vendor_data = {
            "vendor_count": len(vendor_perf_df),
            "total_revenue": vendor_perf_df["revenue"].sum(),
            "avg_fulfillment_pct": vendor_perf_df["fulfillment_pct"].mean() if not vendor_perf_df.empty else 0.0,
            "avg_refund_pct": vendor_perf_df["refund_pct"].mean() if not vendor_perf_df.empty else 0.0,
            "vendors": display_df.to_dict("records"),
        }
        cols = st.columns(2)
        cols[0].download_button(
            "Download Vendor Report PDF",
            data=report_builder.build_vendor_report_pdf(vendor_data, user["username"]),
            file_name="vendor_report.pdf", mime="application/pdf", key="vendor_pdf",
        )
        cols[1].download_button(
            "Download Vendor Report CSV",
            data=display_df.to_csv(index=False),
            file_name="vendor_report.csv", mime="text/csv", key="vendor_csv",
        )

    # ---------- Customer Report ----------
    with tab_customer:
        with connection() as conn:
            customer_count = conn.execute(text("SELECT COUNT(*) FROM customers")).scalar()
            first_order_df = pd.read_sql_query(
                text("SELECT customer_id, MIN(order_date) AS first_order_date FROM orders GROUP BY customer_id"),
                conn,
            )
            current_df = pd.read_sql_query(
                text("SELECT DISTINCT customer_id FROM orders WHERE order_date >= NOW() - INTERVAL '30 days'"), conn,
            )
            previous_df = pd.read_sql_query(
                text("""
                    SELECT DISTINCT customer_id FROM orders
                    WHERE order_date >= NOW() - INTERVAL '60 days' AND order_date < NOW() - INTERVAL '30 days'
                """),
                conn,
            )
            clv_row = conn.execute(text("""
                SELECT COUNT(DISTINCT o.customer_id) AS customers, COALESCE(SUM(oi.total_price), 0) AS revenue
                FROM order_items oi JOIN orders o ON o.id = oi.order_id
                WHERE o.status = 'completed'
            """)).first()

        segmentation_result = segmentation.run_segmentation()
        segments_summary = (
            segmentation_result["summary"].to_dict("records") if segmentation_result["available"] else []
        )
        customer_detail_df = (
            segmentation_result["customers"] if segmentation_result["available"] else pd.DataFrame()
        )

        if first_order_df.empty:
            st.info("No orders yet. This report fills in once customers place orders.")
            customer_data = {
                "customer_count": customer_count, "new_customers": 0, "returning_customers": 0,
                "retention_pct": 0.0, "churn_pct": 0.0, "clv": 0.0, "segments": [],
            }
        else:
            first_order_map = dict(zip(first_order_df["customer_id"], pd.to_datetime(first_order_df["first_order_date"])))
            period_start = pd.Timestamp.now() - pd.Timedelta(days=30)
            current_customers = set(current_df["customer_id"])
            previous_customers = set(previous_df["customer_id"])
            new_customers = {c for c in current_customers if first_order_map.get(c, period_start) >= period_start}
            returning_customers = current_customers - new_customers
            retained = current_customers & previous_customers
            retention_pct = round(100 * len(retained) / len(previous_customers), 1) if previous_customers else 0.0
            churn_pct = round(100 - retention_pct, 1) if previous_customers else 0.0
            clv = round(clv_row.revenue / clv_row.customers, 2) if clv_row.customers else 0.0

            kpi_row([
                ("Total Customers", customer_count),
                ("New (30d)", len(new_customers)),
                ("Returning (30d)", len(returning_customers)),
                ("Retention %", f"{retention_pct}%"),
                ("CLV", money(clv)),
            ])

            customer_data = {
                "customer_count": customer_count, "new_customers": len(new_customers),
                "returning_customers": len(returning_customers), "retention_pct": retention_pct,
                "churn_pct": churn_pct, "clv": clv, "segments": segments_summary,
            }

        if not customer_detail_df.empty:
            st.dataframe(
                customer_detail_df[["customer", "order_count", "total_spend", "avg_order_value", "segment"]],
                width="stretch", hide_index=True,
            )

        cols = st.columns(2)
        cols[0].download_button(
            "Download Customer Report PDF",
            data=report_builder.build_customer_report_pdf(customer_data, user["username"]),
            file_name="customer_report.pdf", mime="application/pdf", key="customer_pdf",
        )
        csv_data = (
            customer_detail_df[["customer", "order_count", "total_spend", "avg_order_value", "segment"]]
            if not customer_detail_df.empty else pd.DataFrame()
        )
        cols[1].download_button(
            "Download Customer Report CSV",
            data=csv_data.to_csv(index=False),
            file_name="customer_report.csv", mime="text/csv", key="customer_csv",
        )


# ---------- Vendor pages ----------

def page_vendor_dashboard(user):
    st.header("Vendor Dashboard")
    st.caption("Your sales, orders, inventory, top products, and recommendations at a glance.")

    vendor_id = user["vendor_id"]

    with connection() as conn:
        sales_row = conn.execute(
            text("""
                SELECT COALESCE(SUM(oi.total_price), 0) AS revenue,
                       COUNT(DISTINCT oi.order_id) AS orders,
                       COALESCE(SUM(oi.quantity), 0) AS units
                FROM order_items oi JOIN orders o ON o.id = oi.order_id
                WHERE oi.vendor_id = :vid AND o.status = 'completed'
            """),
            {"vid": vendor_id},
        ).first()

        recent_orders = pd.read_sql_query(
            text("""
                SELECT o.id AS order_id, o.order_date, o.status, c.name AS customer,
                       p.name AS product, oi.quantity, oi.total_price
                FROM order_items oi
                JOIN orders o ON o.id = oi.order_id
                JOIN customers c ON c.id = o.customer_id
                JOIN products p ON p.id = oi.product_id
                WHERE oi.vendor_id = :vid
                ORDER BY o.order_date DESC
                LIMIT 10
            """),
            conn, params={"vid": vendor_id},
        )

        top_products = pd.read_sql_query(
            text("""
                SELECT p.name AS product, SUM(oi.total_price) AS revenue
                FROM order_items oi
                JOIN orders o ON o.id = oi.order_id
                JOIN products p ON p.id = oi.product_id
                WHERE oi.vendor_id = :vid AND o.status = 'completed'
                GROUP BY p.name
                ORDER BY revenue DESC
                LIMIT 5
            """),
            conn, params={"vid": vendor_id},
        )

    products = Product.list_for_vendor(vendor_id)
    inv_df = pd.DataFrame(products)
    if not inv_df.empty:
        inv_df["stock_quantity"] = inv_df["stock_quantity"].fillna(0).astype(int)
        inv_df["reorder_level"] = inv_df["reorder_level"].fillna(10).astype(int)
        low_stock_df = inv_df[inv_df["stock_quantity"] <= inv_df["reorder_level"]]
        total_stock = int(inv_df["stock_quantity"].sum())
    else:
        low_stock_df = pd.DataFrame()
        total_stock = 0

    kpi_row([
        ("Revenue", money(sales_row.revenue)),
        ("Orders", sales_row.orders),
        ("Units Sold", int(sales_row.units)),
        ("Products", len(products)),
        ("Low Stock Items", len(low_stock_df)),
    ])

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Top Products")
        if top_products.empty:
            st.info("No completed sales yet.")
        else:
            bar_chart(top_products, "product", "revenue", "Top 5 Products by Revenue")
    with c2:
        st.subheader("Inventory Snapshot")
        st.metric("Total Stock (units)", total_stock)
        if low_stock_df.empty:
            st.success("No low-stock alerts right now.")
        else:
            st.dataframe(
                low_stock_df[["name", "stock_quantity", "reorder_level"]].rename(columns={
                    "name": "Product", "stock_quantity": "Stock", "reorder_level": "Reorder Level",
                }),
                width="stretch", hide_index=True,
            )

    st.subheader("Recent Orders")
    if recent_orders.empty:
        st.info("No orders yet for your products.")
    else:
        st.dataframe(recent_orders, width="stretch", hide_index=True)

    st.subheader("Recommendations")
    trending_df = _cached_trending(7, vendor_id)
    if trending_df.empty:
        st.info("No trending sales data yet for the last 7 days.")
    else:
        bar_chart(trending_df, "product_name", "units_sold", "Trending Products (last 7 days)")
    st.caption("For personalized recommendations and similar products, see the Recommendation System page.")


def page_manage_products(user):
    st.header("Manage Products")
    st.caption("Products listed under your vendor account.")

    products = Product.list_for_vendor(user["vendor_id"])

    if products:
        display_df = pd.DataFrame(products).drop(columns=["image_path"], errors="ignore")
        st.dataframe(display_df, width="stretch", hide_index=True)

        by_category = (
            pd.DataFrame(products)
            .assign(category_name=lambda d: d["category_name"].fillna("Uncategorized"))
            .groupby("category_name")
            .size()
            .reset_index(name="count")
        )
        pie_chart(by_category, "category_name", "count", "Products by Category")

    st.subheader("Add Product")
    categories = Category.list_all()
    category_names = [c.name for c in categories]
    with st.form("create_product_form"):
        cols = st.columns(3)
        name = cols[0].text_input("Product Name")
        category_choice = cols[1].selectbox("Category", ["(new category)"] + category_names)
        new_category_name = cols[2].text_input("New category name (if above is '(new category)')")

        cols2 = st.columns(4)
        store = cols2[0].text_input("Store")
        warehouse = cols2[1].text_input("Warehouse")
        unit_price = cols2[2].number_input("Price", min_value=0.0, step=0.5)
        initial_stock = cols2[3].number_input("Stock", min_value=0, step=1)

        cols3 = st.columns(2)
        sku = cols3[0].text_input("SKU")
        reorder_level = cols3[1].number_input("Reorder level", min_value=0, step=1, value=10)

        description = st.text_area("Description")
        product_image = st.file_uploader("Product Image", type=["png", "jpg", "jpeg"])

        create_submitted = st.form_submit_button("Add Product")

    if create_submitted:
        if not name.strip():
            st.error("Product Name is required.")
        else:
            if category_choice == "(new category)" and new_category_name.strip():
                category = Category.get_or_create(new_category_name)
            elif category_choice != "(new category)":
                category = next(c for c in categories if c.name == category_choice)
            else:
                category = None

            product_id, error = Product.create(
                user["vendor_id"], name, category.id if category else None,
                sku, unit_price, description, int(initial_stock), int(reorder_level),
                store=store, warehouse=warehouse,
            )
            if error:
                st.error(error)
            else:
                if product_image is not None:
                    image_path = _save_product_image(product_image, product_id)
                    Product.update_image(product_id, image_path)
                st.success(f"Added product {name}.")
                st.rerun()

    if products:
        st.subheader("Edit / Update Product")
        product_names = [p["name"] for p in products]
        selected_name = st.selectbox("Select product", product_names, key="manage_product_select")
        selected = next((p for p in products if p["name"] == selected_name), None)

        if selected:
            if selected.get("image_path"):
                if os.path.exists(selected["image_path"]):
                    st.image(selected["image_path"], width=160)
                else:
                    st.caption("⚠️ Image file not found on disk.")

            cols = st.columns(3)
            edit_store = cols[0].text_input("Store", value=selected.get("store") or "", key="edit_store")
            edit_warehouse = cols[1].text_input("Warehouse", value=selected.get("warehouse") or "", key="edit_warehouse")
            edit_sku = cols[2].text_input("SKU", value=selected["sku"] or "", key="edit_sku")

            cols2 = st.columns(2)
            current_category_name = selected.get("category_name") or "(none)"
            category_options = ["(none)"] + category_names
            default_index = category_options.index(current_category_name) if current_category_name in category_options else 0
            edit_category_choice = cols2[0].selectbox(
                "Category", category_options, index=default_index, key="edit_category"
            )
            edit_description = cols2[1].text_input(
                "Description", value=selected.get("description") or "", key="edit_description"
            )

            cols3 = st.columns(2)
            edit_price = cols3[0].number_input(
                "Price", min_value=0.0, step=0.5, value=float(selected["unit_price"]), key="edit_price"
            )
            edit_stock = cols3[1].number_input(
                "Stock", min_value=0, step=1,
                value=int(selected["stock_quantity"] or 0), key="edit_stock"
            )

            new_image = st.file_uploader(
                "Replace Product Image", type=["png", "jpg", "jpeg"], key="edit_image_uploader"
            )

            action_cols = st.columns(5)

            if action_cols[0].button("Save Details"):
                if edit_category_choice == "(none)":
                    category_id = None
                else:
                    category_id = next(c.id for c in categories if c.name == edit_category_choice)
                Product.update(
                    selected["id"], selected["name"], category_id,
                    edit_sku, edit_price, edit_description,
                    store=edit_store, warehouse=edit_warehouse,
                )
                st.success("Product updated.")
                st.rerun()

            if action_cols[1].button("Update Price"):
                Product.update_price(selected["id"], edit_price)
                st.success("Price updated.")
                st.rerun()

            if action_cols[2].button("Update Stock"):
                Inventory.adjust_stock(
                    selected["id"], user["vendor_id"], int(edit_stock), int(selected["reorder_level"] or 10),
                    reason="manual_adjustment",
                )
                st.success("Stock updated.")
                st.rerun()

            if action_cols[3].button("Upload Image"):
                if new_image is None:
                    st.warning("Choose an image file above first.")
                else:
                    image_path = _save_product_image(new_image, selected["id"])
                    Product.update_image(selected["id"], image_path)
                    st.success("Image uploaded.")
                    st.rerun()

            if action_cols[4].button("Delete Product"):
                Product.delete(selected["id"])
                st.success(f"Deleted {selected['name']}.")
                st.rerun()


def page_view_own_sales(user):
    st.header("View Own Sales")
    st.caption("Orders containing your products.")

    with connection() as conn:
        sales = pd.read_sql_query(
            text("""
            SELECT o.id AS order_id, o.order_date, o.status, p.name AS product,
                   oi.quantity, oi.total_price
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            JOIN products p ON p.id = oi.product_id
            WHERE oi.vendor_id = :vendor_id
            ORDER BY o.order_date DESC
            """),
            conn, params={"vendor_id": user["vendor_id"]},
        )

    if sales.empty:
        st.info("No sales yet. Orders that include your products will show up here.")
        return

    kpi_row([
        ("Total Revenue", money(sales["total_price"].sum())),
        ("Orders", sales["order_id"].nunique()),
        ("Units Sold", int(sales["quantity"].sum())),
    ])

    c1, c2 = st.columns(2)
    with c1:
        by_product = sales.groupby("product")["total_price"].sum().sort_values(ascending=False).reset_index()
        bar_chart(by_product, "product", "total_price", "Revenue by Product")
    with c2:
        status_counts = sales.groupby("order_id")["status"].first().value_counts().reset_index()
        status_counts.columns = ["status", "count"]
        pie_chart(status_counts, "status", "count", "Orders by Status")

    st.dataframe(sales, width="stretch", hide_index=True)


def page_inventory_monitoring(user):
    st.header("Inventory Monitoring")
    st.caption("Current stock, stock movement, turnover, and usage trends for your products.")

    products = Product.list_for_vendor(user["vendor_id"])
    if not products:
        st.info("You have no products yet — add one under Manage Products.")
        return

    df = pd.DataFrame(products)
    df["stock_quantity"] = df["stock_quantity"].fillna(0).astype(int)
    df["reorder_level"] = df["reorder_level"].fillna(10).astype(int)
    df["status"] = df.apply(
        lambda r: "Out of Stock" if r["stock_quantity"] <= 0
        else ("Low Stock" if r["stock_quantity"] <= r["reorder_level"] else "In Stock"),
        axis=1,
    )

    period_days = st.selectbox(
        "Period for Stock In / Stock Out / Turnover", [7, 30, 90], index=1,
        format_func=lambda d: f"Last {d} days", key="inventory_period",
    )
    summary = InventoryMovement.summary_for_vendor(user["vendor_id"], days=period_days)

    kpi_row([
        ("Current Stock (units)", summary["current_total_stock"]),
        ("Stock In", summary["stock_in"]),
        ("Stock Out", summary["stock_out"]),
        ("Inventory Turnover", summary["turnover"]),
        ("Low Stock Items", int((df["status"] == "Low Stock").sum())),
    ])
    st.caption(
        "Inventory Turnover ≈ units sold ÷ current total stock, over the selected period. "
        "Higher means stock is moving faster."
    )

    st.subheader("Stock Alerts")
    alerts = df[df["status"] != "In Stock"][["name", "sku", "stock_quantity", "reorder_level", "status"]]
    if alerts.empty:
        st.success("No low-stock or out-of-stock products right now.")
    else:
        st.dataframe(alerts, width="stretch", hide_index=True)

    st.subheader("Inventory Charts")
    c1, c2 = st.columns(2)
    with c1:
        status_counts = df["status"].value_counts().reset_index()
        status_counts.columns = ["status", "count"]
        pie_chart(status_counts, "status", "count", "Stock Status Breakdown")
    with c2:
        bar_chart(df, "name", "stock_quantity", "Current Stock by Product")

    movements = InventoryMovement.list_for_vendor(user["vendor_id"], days=period_days)
    if movements:
        moves_df = pd.DataFrame(movements)
        moves_df["day"] = pd.to_datetime(moves_df["occurred_at"]).dt.date
        daily = moves_df.groupby(["day", "movement_type"])["quantity"].sum().reset_index()
        c3, c4 = st.columns(2)
        with c3:
            daily_in = daily[daily["movement_type"] == "in"][["day", "quantity"]]
            bar_chart(daily_in, "day", "quantity", "Stock In Over Time")
        with c4:
            daily_out = daily[daily["movement_type"] == "out"][["day", "quantity"]]
            bar_chart(daily_out, "day", "quantity", "Stock Out Over Time")
    else:
        st.info("No stock movements recorded yet in this period — sales, restocks, and manual adjustments will show up here.")

    st.subheader("Monthly Usage")
    monthly = InventoryMovement.monthly_usage_for_vendor(user["vendor_id"], months=6)
    if monthly:
        monthly_df = pd.DataFrame(monthly)
        bar_chart(monthly_df, "month", "units_sold", "Units Sold by Month (last 6 months)")
    else:
        st.info("No sales history yet to show monthly usage.")

    st.divider()
    st.subheader("Update Stock")
    st.caption("Manual changes here are logged as Stock In (increase) or Stock Out (decrease) automatically.")
    product_names = df["name"].tolist()
    selected_name = st.selectbox("Select product", product_names, key="inventory_product_select")
    selected = df[df["name"] == selected_name].iloc[0]
    cols = st.columns(3)
    new_stock = cols[0].number_input("Stock quantity", min_value=0, step=1, value=int(selected["stock_quantity"]), key="new_stock_qty")
    new_reorder = cols[1].number_input("Reorder level", min_value=0, step=1, value=int(selected["reorder_level"]), key="new_reorder_level")
    if cols[2].button("Save stock levels"):
        Inventory.adjust_stock(
            int(selected["id"]), user["vendor_id"], int(new_stock), int(new_reorder),
            reason="manual_adjustment",
        )
        st.success("Stock levels updated.")
        st.rerun()


def page_inventory_forecasting(user):
    st.header("Inventory Forecasting")
    st.caption(
        "Predicts future daily demand from previous sales, month, season, festivals, and promotions, "
        "so you can see a suggested Future Stock Requirement before you run low."
    )
    st.info(
        "Third algorithm note: true Facebook Prophet needs a heavy compiler toolchain that's unreliable "
        "to install on Windows. We use **SARIMAX** (statsmodels) instead — it supports the same festival/"
        "promotion inputs and seasonal modeling, without the risky install.",
        icon="ℹ️",
    )

    products = Product.list_for_vendor(user["vendor_id"])
    if not products:
        st.info("You have no products yet — add one under Manage Products.")
        return

    product_choice = st.selectbox("Product", [p["name"] for p in products], key="forecast_product_select")
    selected = next(p for p in products if p["name"] == product_choice)

    cols = st.columns(2)
    algorithm = cols[0].selectbox(
        "Algorithm", ["Random Forest", "XGBoost", "Seasonal (SARIMAX)"], key="forecast_algorithm",
    )
    horizon = cols[1].selectbox("Forecast horizon (days)", [7, 14, 30], index=1, key="forecast_horizon")

    if st.button("Train & Forecast", type="primary"):
        with st.spinner(f"Training {algorithm} and forecasting the next {horizon} days..."):
            result = _cached_forecast(selected["id"], algorithm, horizon, selected["unit_price"])
        st.session_state["forecast_result"] = result
        st.session_state["forecast_result_product"] = selected["id"]

    result = st.session_state.get("forecast_result")
    if result is None or st.session_state.get("forecast_result_product") != selected["id"]:
        st.info("Choose a product, pick an algorithm and horizon, then click **Train & Forecast**.")
        return

    if not result["available"]:
        st.warning(result["reason"])
        return

    current_stock = selected["stock_quantity"] or 0
    total_predicted_demand = result["total_predicted_demand"]
    suggested_reorder = max(0, round(total_predicted_demand - current_stock))

    kpi_row([
        ("Predicted Demand", f"{total_predicted_demand:.0f} units"),
        ("Current Stock", int(current_stock)),
        ("Future Stock Requirement", f"{suggested_reorder} units"),
        ("Model Error (MAE)", f"{result['mae']:.2f}" if result["mae"] is not None else "n/a"),
    ])
    st.caption(
        "Future Stock Requirement = predicted demand over the horizon minus current stock — if positive, "
        "that's roughly how much more you'd need to avoid running out before the horizon ends."
    )

    history = result["history"].tail(60)
    forecast = result["forecast"]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=history["date"], y=history["qty"], mode="lines", name="Actual (last 60 days)",
        line=dict(color=PURPLE_SEQUENCE[1]),
    ))
    fig.add_trace(go.Scatter(
        x=forecast["date"], y=forecast["predicted_quantity"], mode="lines+markers",
        name=f"Forecast ({algorithm})", line=dict(color=PURPLE_SEQUENCE[3], dash="dash"),
    ))
    fig.update_layout(
        title=f"Daily Demand Forecast — {selected['name']}",
        margin=dict(t=40, b=10, l=10, r=10),
    )
    st.plotly_chart(fig, width="stretch")

    st.subheader("Forecast Detail")
    st.dataframe(
        forecast.rename(columns={
            "date": "Date", "predicted_quantity": "Predicted Units", "predicted_revenue": "Predicted Revenue",
        }),
        width="stretch", hide_index=True,
    )

    if st.button("Save this forecast"):
        rows = [
            {"date": r["date"], "predicted_quantity": r["predicted_quantity"], "predicted_revenue": r.get("predicted_revenue")}
            for r in forecast.to_dict("records")
        ]
        ForecastResult.record_batch(user["vendor_id"], selected["id"], rows, model_used=algorithm)
        st.success("Forecast saved — see history below after refreshing.")

    with st.expander("Forecast History (previously saved runs)"):
        history_rows = ForecastResult.latest_batch_for_product(selected["id"])
        if not history_rows:
            st.caption("No saved forecasts yet for this product.")
        else:
            st.dataframe(pd.DataFrame(history_rows), width="stretch", hide_index=True)

    st.divider()
    st.subheader("Manage Promotions")
    st.caption("Mark upcoming promotional periods so the forecast accounts for expected demand spikes.")

    promos = Promotion.list_for_vendor(user["vendor_id"])
    if promos:
        st.dataframe(pd.DataFrame(promos)[["product", "start_date", "end_date", "discount_pct", "description"]],
                     width="stretch", hide_index=True)

    with st.form("add_promotion_form"):
        cols = st.columns(4)
        promo_product_choice = cols[0].selectbox("Product", [p["name"] for p in products], key="promo_product")
        start_date = cols[1].date_input("Start date")
        end_date = cols[2].date_input("End date")
        discount_pct = cols[3].number_input("Discount %", min_value=0.0, max_value=100.0, step=5.0)
        description = st.text_input("Description (optional)")
        submitted = st.form_submit_button("Add promotion")
    if submitted:
        promo_product = next(p for p in products if p["name"] == promo_product_choice)
        _, error = Promotion.create(
            promo_product["id"], user["vendor_id"], start_date, end_date, discount_pct, description,
        )
        if error:
            st.error(error)
        else:
            st.success("Promotion added.")
            st.rerun()


def page_recommendation_system(user):
    st.header("Recommendation System")
    st.caption(
        "Recommended Products (collaborative filtering), Similar Products (collaborative + "
        "content-based), and Trending Products for your store."
    )

    tab1, tab2, tab3 = st.tabs(["Recommended Products", "Similar Products", "Trending Products"])

    with tab1:
        st.subheader("Recommended Products for a Customer")
        st.caption(
            "Collaborative filtering: for everything this customer has already bought, we find "
            "products frequently bought by the same customers and haven't been purchased yet."
        )
        customers = Customer.list_all()
        if not customers:
            st.info("No customers yet — recommendations need order history to work from.")
        else:
            customer_choice = st.selectbox("Customer", [c.name for c in customers], key="reco_customer_select")
            customer_id = next(c.id for c in customers if c.name == customer_choice)
            recs_df = _cached_recommend_for_customer(customer_id, user["vendor_id"])
            if recs_df.empty:
                st.info(
                    "Not enough purchase-overlap data yet to recommend products for this customer — "
                    "either they haven't ordered from you, or there isn't enough co-purchase history yet."
                )
            else:
                display = recs_df[["product_name", "unit_price", "score"]].rename(columns={
                    "product_name": "Product", "unit_price": "Price", "score": "Match Score",
                })
                st.dataframe(display, width="stretch", hide_index=True)

    with tab2:
        st.subheader("Similar Products")
        products = Product.list_for_vendor(user["vendor_id"])
        if not products:
            st.info("You have no products yet — add one under Manage Products.")
        else:
            product_choice = st.selectbox("Product", [p["name"] for p in products], key="reco_product_select")
            product_id = next(p["id"] for p in products if p["name"] == product_choice)

            sub1, sub2 = st.tabs(["Collaborative (bought together)", "Content-Based (similar attributes)"])
            with sub1:
                st.caption("Products frequently bought by the same customers as this one — platform-wide.")
                collab_df = _cached_similar_collaborative(product_id)
                if collab_df.empty:
                    st.info("Not enough co-purchase history yet for this product.")
                else:
                    display = collab_df[["product_name", "vendor_name", "unit_price", "similarity"]].rename(columns={
                        "product_name": "Product", "vendor_name": "Vendor",
                        "unit_price": "Price", "similarity": "Similarity",
                    })
                    st.dataframe(display, width="stretch", hide_index=True)
            with sub2:
                st.caption("Products with a similar category and price — works even with no sales yet.")
                content_df = _cached_similar_content(product_id)
                if content_df.empty:
                    st.info("Not enough comparable products yet (need at least one other product with a category/price).")
                else:
                    display = content_df[["product_name", "vendor_name", "category", "unit_price", "similarity"]].rename(columns={
                        "product_name": "Product", "vendor_name": "Vendor", "category": "Category",
                        "unit_price": "Price", "similarity": "Similarity",
                    })
                    st.dataframe(display, width="stretch", hide_index=True)

    with tab3:
        st.subheader("Trending Products")
        st.caption("Your products with the highest unit sales in the selected recent period.")
        days = st.selectbox("Trending window", [7, 30, 90], index=0, key="reco_trending_days")
        trending_df = _cached_trending(days, user["vendor_id"])
        if trending_df.empty:
            st.info("No sales for your products in this window yet.")
        else:
            bar_chart(trending_df, "product_name", "units_sold", f"Trending Products (last {days} days)")
            display = trending_df[["product_name", "units_sold"]].rename(columns={
                "product_name": "Product", "units_sold": "Units Sold",
            })
            st.dataframe(display, width="stretch", hide_index=True)


def page_customer_insights(user):
    st.header("Customer Insights")
    st.caption("How customers discover, engage with, and rate your products.")

    activity = CustomerActivity.list_for_vendor(user["vendor_id"])
    reviews = pd.DataFrame(Review.list_for_vendor(user["vendor_id"]))

    with connection() as conn:
        top_customers = pd.read_sql_query(
            text("""
            SELECT c.name AS customer, SUM(oi.total_price) AS revenue, COUNT(DISTINCT o.id) AS orders
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            JOIN customers c ON c.id = o.customer_id
            WHERE oi.vendor_id = :vendor_id
            GROUP BY c.name
            ORDER BY revenue DESC
            LIMIT 10
            """),
            conn, params={"vendor_id": user["vendor_id"]},
        )

    if not activity and reviews.empty and top_customers.empty:
        st.info(
            "No customer engagement data yet. This fills in once customers order your products "
            "(Manage Orders) and leave reviews (Customer Reviews)."
        )
        return

    kpi_row([
        ("Customer Activity Events", len(activity)),
        ("Reviews", len(reviews)),
        ("Unique Customers", top_customers["customer"].nunique() if not top_customers.empty else 0),
    ])

    c1, c2 = st.columns(2)
    with c1:
        if activity:
            activity_df = pd.DataFrame(activity)
            activity_counts = activity_df["activity_type"].value_counts().reset_index()
            activity_counts.columns = ["activity_type", "count"]
            pie_chart(activity_counts, "activity_type", "count", "Customer Activity Breakdown")
        else:
            st.info("No activity events logged yet.")
    with c2:
        bar_chart(top_customers, "customer", "revenue", "Top Customers by Revenue")

    c3, c4 = st.columns(2)
    with c3:
        if not reviews.empty:
            rating_counts = reviews["rating"].value_counts().sort_index().reset_index()
            rating_counts.columns = ["rating", "count"]
            pie_chart(rating_counts, "rating", "count", "Rating Distribution")
        else:
            st.info("No reviews yet.")
    with c4:
        if not reviews.empty:
            avg_rating = reviews.groupby("product")["rating"].mean().round(2).reset_index()
            bar_chart(avg_rating, "product", "rating", "Average Rating by Product")
        else:
            st.info("No reviews yet.")

    if not reviews.empty:
        st.subheader("Recent Reviews")
        st.dataframe(reviews, width="stretch", hide_index=True)


MANAGER_PAGES = {
    "Admin Dashboard": page_admin_dashboard,
    "Manage Vendors": page_manage_vendors,
    "Manage Orders": page_manage_orders,
    "Upload Dataset": page_upload_dataset,
    "Sales Dashboard": page_sales_dashboard,
    "View Analytics": page_view_analytics,
    "Compare Vendors": page_compare_vendors,
    "Vendor Performance": page_vendor_performance,
    "Customer Dashboard": page_customer_dashboard,
    "Customer Segmentation": page_customer_segmentation,
    "Customer Reviews": page_customer_reviews,
    "Generate Reports": page_generate_reports,
}

ANALYST_PAGES = {
    "Admin Dashboard": page_admin_dashboard,
    "Sales Dashboard": page_sales_dashboard,
    "View Analytics": page_view_analytics,
    "Compare Vendors": page_compare_vendors,
    "Vendor Performance": page_vendor_performance,
    "Customer Dashboard": page_customer_dashboard,
    "Customer Segmentation": page_customer_segmentation,
    "Customer Reviews": page_customer_reviews,
    "Generate Reports": page_generate_reports,
}

VENDOR_PAGES = {
    "Vendor Dashboard": page_vendor_dashboard,
    "Manage Products": page_manage_products,
    "View Own Sales": page_view_own_sales,
    "Inventory Monitoring": page_inventory_monitoring,
    "Inventory Forecasting": page_inventory_forecasting,
    "Recommendation System": page_recommendation_system,
    "Customer Insights": page_customer_insights,
}


def main():
    st.set_page_config(page_title="Infinity Mart", page_icon="🛒", layout="wide")
    bootstrap()

    if "user" not in st.session_state:
        st.session_state.user = None

    if not st.session_state.user:
        login_view()
        return

    if time.time() - st.session_state.get("last_active", time.time()) > SESSION_TIMEOUT_SECONDS:
        st.session_state.user = None
        st.warning("Session expired due to inactivity. Please sign in again.")
        login_view()
        return
    st.session_state.last_active = time.time()

    inject_theme_css()
    user = st.session_state.user
    page = render_sidebar(user)
    if user["role"] == MANAGER_ROLE:
        pages = MANAGER_PAGES
    elif user["role"] == ANALYST_ROLE:
        pages = ANALYST_PAGES
    else:
        pages = VENDOR_PAGES
    try:
        pages[page](user)
    except Exception:
        logging.error("Error rendering page %r:\n%s", page, traceback.format_exc())
        st.error(
            "Something went wrong loading this page. This is usually caused by the "
            "underlying database being briefly unavailable. Please try again — if it "
            "keeps happening, let a manager know."
        )
        if st.button("Retry", key=f"retry_{page}"):
            st.rerun()


if __name__ == "__main__":
    main()
