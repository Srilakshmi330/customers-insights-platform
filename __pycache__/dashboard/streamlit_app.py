import logging
import time
import traceback

import streamlit as st
import pandas as pd
import plotly.express as px
from sqlalchemy import text

import dataset_import
import report_builder
import segmentation
from models import (
    Category, Customer, CustomerActivity, Inventory, Order, Product,
    Recommendation, Review, User, Vendor, init_db, seed_default_users,
)
from permissions import (
    ANALYST_CAPABILITIES, ANALYST_ROLE, MANAGER_CAPABILITIES, MANAGER_ROLE,
    VENDOR_CAPABILITIES, VENDOR_ROLE,
)
from schema import connection

PURPLE_SEQUENCE = ["#8b5cf6", "#6d28d9", "#c4b5fd", "#f59e0b", "#ef5350", "#42a5f5", "#10b981", "#0ea5e9"]

SESSION_TIMEOUT_SECONDS = 30 * 60


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


def page_customer_segmentation(user):
    st.header("Customer Segmentation")
    st.caption("Groups customers into behavioral segments using KMeans clustering on completed-order history.")

    result = segmentation.run_segmentation()
    if not result["available"]:
        st.info("Not enough completed-order history yet to segment customers — record more orders first.")
        return

    customers = result["customers"]
    summary = result["summary"]

    kpi_row([
        ("Customers Segmented", len(customers)),
        ("Segments", summary["segment"].nunique()),
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
    )
    fig.update_layout(margin=dict(t=40, b=10, l=10, r=10))
    st.plotly_chart(fig, width="stretch")

    st.subheader("Segment Summary")
    st.dataframe(summary, width="stretch", hide_index=True)

    st.subheader("Customer Assignments")
    display_cols = customers[["customer", "order_count", "total_spend", "avg_order_value", "segment"]]
    st.dataframe(display_cols, width="stretch", hide_index=True)
    st.download_button(
        "Download Segmentation CSV", data=display_cols.to_csv(index=False),
        file_name="customer_segments.csv", mime="text/csv",
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
    st.caption("Export current platform data.")

    vendors = Vendor.list_all()
    vendors_df = pd.DataFrame([
        {"name": v.name, "status": v.status, "contact_email": v.contact_email, "phone": v.phone}
        for v in vendors
    ])
    st.subheader("Vendors")
    st.dataframe(vendors_df, width="stretch", hide_index=True)
    if not vendors_df.empty:
        st.download_button(
            "Download Vendors CSV", data=vendors_df.to_csv(index=False),
            file_name="vendors.csv", mime="text/csv",
        )

    with connection() as conn:
        products_df = pd.read_sql_query(
            text("""
            SELECT p.name AS product, v.name AS vendor, c.name AS category, p.unit_price, i.stock_quantity
            FROM products p
            JOIN vendors v ON v.id = p.vendor_id
            LEFT JOIN categories c ON c.id = p.category_id
            LEFT JOIN inventory i ON i.product_id = p.id
            ORDER BY v.name, p.name
            """),
            conn,
        )
        orders_df = pd.read_sql_query(
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

    st.subheader("Products")
    st.dataframe(products_df, width="stretch", hide_index=True)
    if not products_df.empty:
        st.download_button(
            "Download Products CSV", data=products_df.to_csv(index=False),
            file_name="products.csv", mime="text/csv",
        )

    st.subheader("Orders")
    st.dataframe(orders_df, width="stretch", hide_index=True)
    if not orders_df.empty:
        st.download_button(
            "Download Orders CSV", data=orders_df.to_csv(index=False),
            file_name="orders.csv", mime="text/csv",
        )

    st.divider()
    st.subheader("Summary Report")
    st.caption("A formatted PDF/Excel summary of revenue, top vendors/products, and low-stock alerts.")

    with connection() as conn:
        top_vendors = pd.read_sql_query(
            text("""
            SELECT v.name AS vendor, COALESCE(SUM(oi.total_price), 0) AS revenue
            FROM vendors v LEFT JOIN order_items oi ON oi.vendor_id = v.id
            GROUP BY v.name ORDER BY revenue DESC LIMIT 10
            """),
            conn,
        )
        top_products_report = pd.read_sql_query(
            text("""
            SELECT p.name AS product, SUM(oi.total_price) AS revenue
            FROM order_items oi JOIN products p ON p.id = oi.product_id
            GROUP BY p.name ORDER BY revenue DESC LIMIT 10
            """),
            conn,
        )
        low_stock = pd.read_sql_query(
            text("""
            SELECT p.name AS name, v.name AS vendor, i.stock_quantity AS stock_quantity
            FROM inventory i
            JOIN products p ON p.id = i.product_id
            JOIN vendors v ON v.id = p.vendor_id
            WHERE i.stock_quantity <= i.reorder_level
            ORDER BY i.stock_quantity ASC LIMIT 20
            """),
            conn,
        )
        order_count = conn.execute(text("SELECT COUNT(*) FROM orders")).scalar()
        revenue = conn.execute(text("SELECT COALESCE(SUM(total_price), 0) FROM order_items")).scalar()
        customer_count = conn.execute(text("SELECT COUNT(*) FROM customers")).scalar()

    report = {
        "total_revenue": revenue,
        "order_count": order_count,
        "vendor_count": len(vendors),
        "product_count": len(products_df),
        "customer_count": customer_count,
        "top_vendors": top_vendors.to_dict("records"),
        "top_products": top_products_report.to_dict("records"),
        "low_stock": low_stock.to_dict("records"),
    }

    cols = st.columns(2)
    cols[0].download_button(
        "Download PDF Report",
        data=report_builder.build_summary_pdf(report, user["username"]),
        file_name="infinity_mart_report.pdf", mime="application/pdf",
    )
    cols[1].download_button(
        "Download Excel Report",
        data=report_builder.build_summary_excel(report),
        file_name="infinity_mart_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ---------- Vendor pages ----------

def page_manage_products(user):
    st.header("Manage Products")
    st.caption("Products listed under your vendor account.")

    products = Product.list_for_vendor(user["vendor_id"])
    st.dataframe(pd.DataFrame(products), width="stretch", hide_index=True)

    if products:
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
        name = cols[0].text_input("Product name")
        category_choice = cols[1].selectbox("Category", ["(new category)"] + category_names)
        new_category_name = cols[2].text_input("New category name (if above is '(new category)')")
        cols2 = st.columns(4)
        sku = cols2[0].text_input("SKU")
        unit_price = cols2[1].number_input("Unit price", min_value=0.0, step=0.5)
        initial_stock = cols2[2].number_input("Initial stock", min_value=0, step=1)
        reorder_level = cols2[3].number_input("Reorder level", min_value=0, step=1, value=10)
        description = st.text_area("Description")
        create_submitted = st.form_submit_button("Add product")
    if create_submitted:
        if category_choice == "(new category)" and new_category_name.strip():
            category = Category.get_or_create(new_category_name)
        elif category_choice != "(new category)":
            category = next(c for c in categories if c.name == category_choice)
        else:
            category = None
        _, error = Product.create(
            user["vendor_id"], name, category.id if category else None,
            sku, unit_price, description, int(initial_stock), int(reorder_level),
        )
        if error:
            st.error(error)
        else:
            st.success(f"Added product {name}.")
            st.rerun()

    if products:
        st.subheader("Edit / Remove Product")
        product_names = [p["name"] for p in products]
        selected_name = st.selectbox("Select product", product_names, key="manage_product_select")
        selected = next((p for p in products if p["name"] == selected_name), None)
        if selected:
            cols = st.columns(3)
            edit_price = cols[0].number_input("Unit price", min_value=0.0, step=0.5, value=float(selected["unit_price"]), key="edit_price")
            edit_sku = cols[1].text_input("SKU", value=selected["sku"] or "", key="edit_sku")
            if cols[2].button("Save changes"):
                Product.update(selected["id"], selected["name"], selected["category_id"], edit_sku, edit_price, selected["description"])
                st.success("Product updated.")
                st.rerun()
            if st.button("Delete product", key="delete_product_btn"):
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


def page_check_inventory(user):
    st.header("Check Inventory")
    st.caption("Stock levels for your products.")

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

    kpi_row([
        ("Products", len(df)),
        ("Low Stock", int((df["status"] == "Low Stock").sum())),
        ("Out of Stock", int((df["status"] == "Out of Stock").sum())),
    ])

    c1, c2 = st.columns(2)
    with c1:
        status_counts = df["status"].value_counts().reset_index()
        status_counts.columns = ["status", "count"]
        pie_chart(status_counts, "status", "count", "Stock Status Breakdown")
    with c2:
        bar_chart(df, "name", "stock_quantity", "Stock Quantity by Product")

    st.dataframe(df[["name", "sku", "stock_quantity", "reorder_level", "status"]], width="stretch", hide_index=True)

    st.subheader("Update Stock")
    product_names = df["name"].tolist()
    selected_name = st.selectbox("Select product", product_names, key="inventory_product_select")
    selected = df[df["name"] == selected_name].iloc[0]
    cols = st.columns(3)
    new_stock = cols[0].number_input("Stock quantity", min_value=0, step=1, value=int(selected["stock_quantity"]), key="new_stock_qty")
    new_reorder = cols[1].number_input("Reorder level", min_value=0, step=1, value=int(selected["reorder_level"]), key="new_reorder_level")
    if cols[2].button("Save stock levels"):
        Inventory.update_stock(int(selected["id"]), int(new_stock), int(new_reorder))
        st.success("Stock levels updated.")
        st.rerun()


def page_view_recommendations(user):
    st.header("View Recommendations")
    st.caption("Recommendation signals generated for your products.")

    if st.button("Generate recommendations"):
        written = Recommendation.generate_for_vendor(user["vendor_id"])
        if written:
            st.success(f"Generated {written} recommendation(s) from purchase history.")
        else:
            st.info("Not enough order history yet to generate recommendations — record some orders first.")
        st.rerun()

    recs = Recommendation.list_for_vendor(user["vendor_id"])
    if not recs:
        st.info(
            "No recommendation data yet. Click 'Generate recommendations' once customers "
            "have placed orders for your products."
        )
        return

    recs_df = pd.DataFrame(recs)
    c1, c2 = st.columns(2)
    with c1:
        by_product = recs_df.groupby("product")["score"].sum().sort_values(ascending=False).reset_index()
        bar_chart(by_product, "product", "score", "Recommendation Strength by Product")
    with c2:
        by_product_count = recs_df["product"].value_counts().reset_index()
        by_product_count.columns = ["product", "count"]
        pie_chart(by_product_count, "product", "count", "Recommendations by Product")

    st.dataframe(recs_df, width="stretch", hide_index=True)


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
    "Manage Vendors": page_manage_vendors,
    "Manage Orders": page_manage_orders,
    "Upload Dataset": page_upload_dataset,
    "View Analytics": page_view_analytics,
    "Compare Vendors": page_compare_vendors,
    "Customer Segmentation": page_customer_segmentation,
    "Customer Reviews": page_customer_reviews,
    "Generate Reports": page_generate_reports,
}

ANALYST_PAGES = {
    "View Analytics": page_view_analytics,
    "Compare Vendors": page_compare_vendors,
    "Customer Segmentation": page_customer_segmentation,
    "Customer Reviews": page_customer_reviews,
    "Generate Reports": page_generate_reports,
}

VENDOR_PAGES = {
    "Manage Products": page_manage_products,
    "View Own Sales": page_view_own_sales,
    "Check Inventory": page_check_inventory,
    "View Recommendations": page_view_recommendations,
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
