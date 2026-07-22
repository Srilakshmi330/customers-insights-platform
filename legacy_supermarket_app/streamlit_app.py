import logging
import time
import traceback

import streamlit as st
import pandas as pd
import plotly.express as px
from werkzeug.security import check_password_hash

import data
import ml
import reports
from models import User, init_db, seed_default_users
from permissions import FULL_ACCESS_ROLES

PURPLE_SEQUENCE = ["#8b5cf6", "#6d28d9", "#c4b5fd", "#f59e0b", "#ef5350", "#42a5f5"]
SEGMENT_COLORS = {
    "Budget Shoppers": "#c4b5fd",
    "Regular Shoppers": "#8b5cf6",
    "High-Value Shoppers": "#5b21b6",
}
TIER_COLORS = {
    "Bronze": "#c4956c",
    "Silver": "#b8bfc7",
    "Gold": "#f5b942",
    "Platinum": "#8b5cf6",
}

SESSION_TIMEOUT_SECONDS = 30 * 60

NAV_ITEMS = [
    ("Dashboard", "all"),
    ("Upload Dataset", "full"),
    ("Data Preparation", "full"),
    ("Exploratory Analysis", "all"),
    ("Customer Profile", "all"),
    ("Customer Segmentation", "all"),
    ("Customer Analytics", "all"),
    ("Churn Prediction", "all"),
    ("Product Recommendations", "all"),
    ("Daily Revenue", "all"),
    ("Sales Forecast", "all"),
    ("Branch Comparison", "full"),
    ("Rewards & Memberships", "all"),
    ("Reports", "all"),
    ("User Management", "full"),
]

NAV_ICONS = {
    "Dashboard": "📊",
    "Upload Dataset": "📤",
    "Data Preparation": "🧹",
    "Exploratory Analysis": "🔍",
    "Customer Profile": "🧑‍🤝‍🧑",
    "Customer Segmentation": "🧩",
    "Customer Analytics": "📈",
    "Churn Prediction": "⚠️",
    "Product Recommendations": "🎯",
    "Daily Revenue": "💰",
    "Sales Forecast": "🔮",
    "Branch Comparison": "🏬",
    "Rewards & Memberships": "🏆",
    "Reports": "🗂️",
    "User Management": "👤",
}


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
    data.ensure_active_dataset()
    return True


def _do_login(username, password):
    username = username.strip()
    user = User.get_by_username(username)
    if not user:
        st.error("Invalid username or password.")
        return
    if User.is_locked(user):
        st.error("Account locked due to too many failed attempts. Try again in a few minutes.")
        return
    if check_password_hash(user.password_hash, password):
        User.register_successful_login(username)
        st.session_state.user = {
            "username": user.username,
            "role": user.role,
            "branch": user.branch,
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
        st.markdown("<h1 style='text-align:center;'>⚡ Infinity Mart Insights</h1>", unsafe_allow_html=True)
        st.markdown(
            "<p style='text-align:center; color:#6b7280;'>Customer Insights Platform for Smart Supermarkets</p>",
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
                "- admin / admin123 — full access\n"
                "- analyst / analyst123 — full access\n"
                "- manager_la / manager123 — Los Angeles\n"
                "- manager_ny / manager123 — New York\n"
                "- manager_chicago / manager123 — Chicago"
            )


def render_sidebar(user):
    st.sidebar.markdown("### ⚡ Infinity Mart")
    st.sidebar.caption("Customer Insights")
    st.sidebar.divider()

    is_full_access = user["role"] in FULL_ACCESS_ROLES
    options = [label for label, scope in NAV_ITEMS if scope == "all" or is_full_access]
    page = st.sidebar.radio(
        "Navigate", options, label_visibility="collapsed",
        format_func=lambda label: f"{NAV_ICONS.get(label, '')}  {label}",
    )

    st.sidebar.divider()
    st.sidebar.checkbox("🔴 Live refresh", key="live_refresh_enabled")
    if st.session_state.get("live_refresh_enabled"):
        st.sidebar.selectbox("Refresh every", [5, 10, 30, 60], format_func=lambda s: f"{s}s", key="live_refresh_interval")

    st.sidebar.divider()
    st.sidebar.caption(f"**{user['username']}** — {user['role']}")
    if user["branch"]:
        st.sidebar.caption(user["branch"])

    with st.sidebar.expander("Change password"):
        with st.form("change_password_form"):
            current_password = st.text_input("Current password", type="password")
            new_password = st.text_input("New password", type="password")
            confirm_new_password = st.text_input("Confirm new password", type="password")
            change_submitted = st.form_submit_button("Update password")
        if change_submitted:
            record = User.get_by_username(user["username"])
            if not record or not check_password_hash(record.password_hash, current_password):
                st.error("Current password is incorrect.")
            elif new_password != confirm_new_password:
                st.error("New passwords do not match.")
            elif len(new_password) < 6:
                st.error("New password must be at least 6 characters.")
            else:
                User.set_password(record.id, new_password)
                st.success("Password updated.")

    if st.sidebar.button("Logout"):
        st.session_state.user = None
        st.rerun()

    return page


def money(value):
    return f"${value:,.2f}"


def _validated_date_range(picked_from, picked_to):
    """Converts date_input widget values to ISO strings, guarding against From > To."""
    date_from = picked_from.isoformat() if picked_from else None
    date_to = picked_to.isoformat() if picked_to else None
    if date_from and date_to and date_from > date_to:
        st.warning("'From' date is after 'To' date — showing unfiltered results.")
        return None, None
    return date_from, date_to


def branch_date_filters(user, key, locked_branch=None):
    """Renders a branch selector (full-access roles only) and an optional date range.
    Returns (branch, date_from_str, date_to_str).
    """
    is_full_access = user["role"] in FULL_ACCESS_ROLES
    branches = data.available_branches()
    min_date, max_date = data.date_bounds()

    cols = st.columns(3) if min_date else st.columns(1)

    branch = locked_branch if locked_branch is not None else (user["branch"] if not is_full_access else None)
    if is_full_access and locked_branch is None:
        with cols[0]:
            choice = st.selectbox("Branch", ["All branches"] + branches, key=f"{key}_branch")
            branch = None if choice == "All branches" else choice

    date_from = date_to = None
    if min_date:
        lo = pd.to_datetime(min_date).date()
        hi = pd.to_datetime(max_date).date()
        with cols[1]:
            picked_from = st.date_input("From", value=None, min_value=lo, max_value=hi, key=f"{key}_from")
        with cols[2]:
            picked_to = st.date_input("To", value=None, min_value=lo, max_value=hi, key=f"{key}_to")
        date_from, date_to = _validated_date_range(picked_from, picked_to)

    return branch, date_from, date_to


def kpi_row(items):
    cols = st.columns(len(items))
    for col, (label, value) in zip(cols, items):
        col.metric(label, value)


def bar_chart(df, x, y, title, orientation="v", color=None):
    if df.empty:
        st.info("No data for this selection.")
        return
    value_col = y if orientation == "v" else x
    if (df[value_col].fillna(0) == 0).all():
        st.caption(title)
        st.info("This dataset doesn't have this data (all values are zero).")
        return
    fig = px.bar(
        df, x=x if orientation == "v" else y, y=y if orientation == "v" else x,
        orientation=orientation, color=color,
        color_discrete_sequence=PURPLE_SEQUENCE,
    )
    fig.update_layout(title=title, showlegend=color is not None, margin=dict(t=40, b=10, l=10, r=10))
    st.plotly_chart(fig, width="stretch")


def pie_chart(df, names, values, title):
    if df.empty:
        st.info("No data for this selection.")
        return
    fig = px.pie(df, names=names, values=values, color_discrete_sequence=PURPLE_SEQUENCE)
    fig.update_layout(title=title, margin=dict(t=40, b=10, l=10, r=10))
    st.plotly_chart(fig, width="stretch")


def grouped_bar_chart(df, x, y, color, title):
    """Side-by-side bars per category, split by a second dimension (e.g. membership type)."""
    if df.empty:
        st.info("No data for this selection.")
        return
    fig = px.bar(
        df, x=x, y=y, color=color, barmode="group",
        color_discrete_sequence=PURPLE_SEQUENCE,
    )
    fig.update_layout(title=title, margin=dict(t=40, b=10, l=10, r=10))
    st.plotly_chart(fig, width="stretch")


def live_page(fn):
    """Wraps a page function so it auto-reruns on a timer when Live Refresh is enabled."""
    def wrapper(user):
        enabled = st.session_state.get("live_refresh_enabled", False)
        interval = st.session_state.get("live_refresh_interval", 10) if enabled else None

        @st.fragment(run_every=interval)
        def _run():
            if interval:
                st.caption(f"🔴 Live — refreshing every {interval}s")
            fn(user)

        _run()

    wrapper.__name__ = fn.__name__
    return wrapper


def export_csv_button(df, branch):
    st.download_button(
        "Export CSV",
        data=df.to_csv(index=False),
        file_name=f"infinity-mart-sales-{branch or 'all-branches'}.csv",
        mime="text/csv",
    )


# ---------- Dashboard ----------

@live_page
def page_dashboard(user):
    if user["role"] in FULL_ACCESS_ROLES:
        page_admin_dashboard(user)
    else:
        page_branch_dashboard(user)


def page_admin_dashboard(user):
    st.header("Company-wide Overview")
    branch, date_from, date_to = branch_date_filters(user, key="admin")
    df = data.load_sales_df(branch=branch, date_from=date_from, date_to=date_to)
    stats = data.summarize(df)

    kpi_row([
        ("Total Revenue", money(stats['total_revenue'])),
        ("Transactions", stats["total_transactions"]),
        ("Avg. Basket Size", money(stats['avg_basket'])),
        ("Reward Points Issued", stats["total_reward_points"]),
    ])
    export_csv_button(df, branch)

    c1, c2 = st.columns(2)
    with c1:
        bar_chart(pd.DataFrame(stats["sales_by_branch"]), "branch", "total_price", "Revenue by Branch")
    with c2:
        pie_chart(pd.DataFrame(stats["sales_by_category"]), "product_category", "total_price", "Revenue by Category")

    c3, c4, c5 = st.columns(3)
    with c3:
        bar_chart(pd.DataFrame(stats["sales_by_city"]), "city", "total_price", "Revenue by City")
    with c4:
        pie_chart(pd.DataFrame(stats["customer_type_split"]), "customer_type", "total_price", "Member vs Normal Revenue")
    with c5:
        pie_chart(pd.DataFrame(stats["revenue_by_gender"]), "gender", "total_price", "Revenue by Gender")

    day_stats = data.day_of_week_stats(df)
    tiers = data.membership_tiers(df)
    c6, c7 = st.columns(2)
    with c6:
        if day_stats["revenue_by_day"]:
            bar_chart(pd.DataFrame(day_stats["revenue_by_day"]), "day_of_week", "total_revenue", "Revenue by Day of Week")
            st.caption(f"Busiest day: **{day_stats['best_day']}** · Slowest day: **{day_stats['worst_day']}**")
    with c7:
        if tiers["tiers"]:
            fig = px.pie(
                pd.DataFrame(tiers["tiers"]), names="tier", values="transactions",
                color="tier", color_discrete_map=TIER_COLORS,
            )
            fig.update_layout(title="Membership Tier Split (Transactions)", margin=dict(t=40, b=10, l=10, r=10))
            st.plotly_chart(fig, width="stretch")

    st.subheader("Top 5 Products")
    st.dataframe(pd.DataFrame(stats["top_products"]), width="stretch", hide_index=True)


def page_branch_dashboard(user):
    branch = user["branch"]
    st.header(f"{branch} Overview")
    _, date_from, date_to = branch_date_filters(user, key="branch_dash", locked_branch=branch)
    df = data.load_sales_df(branch=branch, date_from=date_from, date_to=date_to)
    stats = data.summarize(df)

    kpi_row([
        ("Branch Revenue", money(stats['total_revenue'])),
        ("Transactions", stats["total_transactions"]),
        ("Avg. Basket Size", money(stats['avg_basket'])),
        ("Reward Points Issued", stats["total_reward_points"]),
    ])
    export_csv_button(df, branch)

    c1, c2, c3 = st.columns(3)
    with c1:
        pie_chart(pd.DataFrame(stats["sales_by_category"]), "product_category", "total_price", "Revenue by Category")
    with c2:
        pie_chart(pd.DataFrame(stats["customer_type_split"]), "customer_type", "total_price", "Member vs Normal Revenue")
    with c3:
        pie_chart(pd.DataFrame(stats["revenue_by_gender"]), "gender", "total_price", "Revenue by Gender")

    day_stats = data.day_of_week_stats(df)
    tiers = data.membership_tiers(df)
    c4, c5 = st.columns(2)
    with c4:
        if day_stats["revenue_by_day"]:
            bar_chart(pd.DataFrame(day_stats["revenue_by_day"]), "day_of_week", "total_revenue", "Revenue by Day of Week")
            st.caption(f"Busiest day: **{day_stats['best_day']}** · Slowest day: **{day_stats['worst_day']}**")
    with c5:
        if tiers["tiers"]:
            fig = px.pie(
                pd.DataFrame(tiers["tiers"]), names="tier", values="transactions",
                color="tier", color_discrete_map=TIER_COLORS,
            )
            fig.update_layout(title="Membership Tier Split (Transactions)", margin=dict(t=40, b=10, l=10, r=10))
            st.plotly_chart(fig, width="stretch")

    st.subheader("Top 5 Products")
    bar_chart(pd.DataFrame(stats["top_products"]), "product_name", "total_price", "Top 5 Products", orientation="h")


# ---------- Upload / Data preparation ----------

def page_upload(user):
    st.header("Upload Dataset")
    current_df = data.load_sales_df()
    st.caption(f"Active dataset: {len(current_df)} rows, {len(current_df.columns)} columns.")

    uploaded = st.file_uploader("Choose a CSV file", type=["csv"])
    if uploaded is not None:
        df, error = data.validate_uploaded_csv(uploaded)
        if error:
            st.error(error)
        else:
            data.save_active_dataset(df)
            st.success(f"Dataset uploaded successfully — {len(df)} rows loaded.")
            st.rerun()

    st.divider()
    confirm = st.checkbox("I understand this will discard the current active dataset.")
    if st.button("Reset to original sample data", disabled=not confirm):
        data.reset_active_dataset()
        st.success("Dataset reset to the original sample data.")
        st.rerun()


def page_data_preparation(user):
    st.header("Data Preparation")
    df = data.load_sales_df()
    report = data.quality_report(df)

    kpi_row([
        ("Rows", report["row_count"]),
        ("Columns", report["column_count"]),
        ("Duplicate Rows", report["duplicate_rows"]),
    ])

    if report["missing"]:
        st.subheader("Missing Values")
        st.dataframe(pd.DataFrame(report["missing"]), width="stretch", hide_index=True)
    else:
        st.success("No missing values detected.")

    st.subheader("Numeric Summary")
    st.dataframe(pd.DataFrame(report["numeric_summary"]), width="stretch", hide_index=True)

    st.divider()
    if st.button("Clean dataset (remove duplicates/incomplete rows)"):
        cleaned, removed = data.clean_dataset(df)
        data.save_active_dataset(cleaned)
        st.success(f"Cleaned dataset: removed {removed} duplicate/incomplete row(s).")
        st.rerun()


# ---------- Exploratory / Profile / Segmentation / Analytics / Churn / Recommendations ----------

@live_page
def page_exploratory(user):
    st.header("Exploratory Analysis")
    branch, date_from, date_to = branch_date_filters(user, key="explore")
    df = data.load_sales_df(branch=branch, date_from=date_from, date_to=date_to)
    stats = data.exploratory_stats(df)

    if stats["sales_trend"]:
        trend_df = pd.DataFrame(stats["sales_trend"])
        fig = px.line(trend_df, x="date", y="total_price", markers=True)
        fig.update_traces(line_color="#7c3aed")
        fig.update_layout(title="Sales Trend Over Time", margin=dict(t=40, b=10, l=10, r=10))
        st.plotly_chart(fig, width="stretch")

    c1, c2 = st.columns(2)
    with c1:
        bar_chart(pd.DataFrame(stats["price_buckets"]), "bucket", "count", "Unit Price Distribution")
    with c2:
        bar_chart(pd.DataFrame(stats["quantity_buckets"]), "bucket", "count", "Quantity per Sale Distribution")

    c3, c4 = st.columns(2)
    with c3:
        pie_chart(pd.DataFrame(stats["revenue_by_gender"]), "gender", "total_price", "Revenue by Gender")
    with c4:
        pie_chart(pd.DataFrame(stats["category_transaction_share"]), "product_category", "count", "Transaction Share by Category")


@live_page
def page_customer_profile(user):
    st.header("Customer Profile")
    st.caption("Profiles grouped by membership type and gender (no individual customer IDs in this dataset).")
    branch, date_from, date_to = branch_date_filters(user, key="profile")
    df = data.load_sales_df(branch=branch, date_from=date_from, date_to=date_to)
    profiles = data.customer_profiles(df)
    profiles_df = pd.DataFrame(profiles)

    if not profiles_df.empty:
        profiles_df["segment"] = profiles_df["customer_type"] + " " + profiles_df["gender"]
        c1, c2, c3 = st.columns(3)
        with c1:
            bar_chart(profiles_df, "segment", "revenue", "Revenue by Segment")
        with c2:
            bar_chart(profiles_df, "segment", "avg_basket", "Avg. Basket by Segment")
        with c3:
            bar_chart(profiles_df, "segment", "reward_points", "Reward Points by Segment")

    st.subheader("Segment Table")
    st.dataframe(pd.DataFrame(profiles), width="stretch", hide_index=True)


@live_page
def page_segmentation(user):
    st.header("Customer Segmentation")
    st.caption("K-Means clustering on basket value, size, and reward points per purchase.")
    branch, date_from, date_to = branch_date_filters(user, key="segmentation")
    df = data.load_sales_df(branch=branch, date_from=date_from, date_to=date_to)
    result = ml.run_segmentation(df)

    if not result["available"]:
        st.info("Not enough data to run segmentation for this selection.")
        return

    points_df = pd.DataFrame(result["points"])
    c1, c2 = st.columns([2, 1])
    with c1:
        fig = px.scatter(
            points_df, x="quantity", y="total_price", color="segment",
            color_discrete_map=SEGMENT_COLORS,
            labels={"quantity": "Quantity", "total_price": "Total Price ($)"},
        )
        fig.update_layout(title="Segments — Quantity vs. Basket Value", margin=dict(t=40, b=10, l=10, r=10))
        st.plotly_chart(fig, width="stretch")
    with c2:
        summary_df = pd.DataFrame(result["summary"])
        fig = px.pie(
            summary_df, names="segment", values="customers",
            color="segment", color_discrete_map=SEGMENT_COLORS,
        )
        fig.update_layout(title="Segment Distribution", margin=dict(t=40, b=10, l=10, r=10))
        st.plotly_chart(fig, width="stretch")

    st.subheader("Segment Summary")
    st.dataframe(pd.DataFrame(result["summary"]), width="stretch", hide_index=True)


@live_page
def page_customer_analytics(user):
    st.header("Customer Analytics")
    st.caption("Deeper behavioural cuts across categories and membership types.")
    branch, date_from, date_to = branch_date_filters(user, key="cust_analytics")
    df = data.load_sales_df(branch=branch, date_from=date_from, date_to=date_to)
    stats = data.customer_analytics(df)

    c1, c2 = st.columns(2)
    with c1:
        bar_chart(pd.DataFrame(stats["avg_basket_by_category"]), "product_category", "total_price", "Avg. Basket by Category")
    with c2:
        bar_chart(pd.DataFrame(stats["reward_points_by_customer_type"]), "customer_type", "reward_points", "Avg. Reward Points by Customer Type")

    c3, c4 = st.columns(2)
    with c3:
        pie_chart(pd.DataFrame(stats["transactions_by_customer_type"]), "customer_type", "count", "Transaction Share: Member vs Normal")
    with c4:
        if stats["payment_method_split"]:
            pie_chart(pd.DataFrame(stats["payment_method_split"]), "payment_method", "total_price", "Revenue by Payment Method")

    grouped_bar_chart(
        pd.DataFrame(stats["category_by_membership"]), "product_category", "total_price", "customer_type",
        "Revenue by Category: Member vs Normal",
    )
    grouped_bar_chart(
        pd.DataFrame(stats["branch_by_membership"]), "branch", "total_price", "customer_type",
        "Revenue by Branch: Member vs Normal",
    )

    if stats["avg_rating_by_branch"]:
        c5, c6 = st.columns(2)
        with c5:
            fig = px.bar(pd.DataFrame(stats["avg_rating_by_branch"]), x="branch", y="rating", color_discrete_sequence=PURPLE_SEQUENCE)
            fig.update_layout(title="Avg. Rating by Branch", yaxis_range=[0, 10], margin=dict(t=40, b=10, l=10, r=10))
            st.plotly_chart(fig, width="stretch")
        with c6:
            fig = px.bar(
                pd.DataFrame(stats["avg_rating_by_category"]), x="rating", y="product_category",
                orientation="h", color_discrete_sequence=["#6d28d9"],
            )
            fig.update_layout(title="Avg. Rating by Category", xaxis_range=[0, 10], margin=dict(t=40, b=10, l=10, r=10))
            st.plotly_chart(fig, width="stretch")


@live_page
def page_churn(user):
    st.header("Churn Prediction")
    st.warning(
        "This dataset has no per-customer visit history or dates, so true repeat-visit churn can't be measured. "
        "This model instead predicts membership-risk: how likely a purchase's basket pattern resembles a Normal "
        "(non-member) shopper rather than a Member, using a logistic regression trained on basket features."
    )
    branch, date_from, date_to = branch_date_filters(user, key="churn")
    df = data.load_sales_df(branch=branch, date_from=date_from, date_to=date_to)
    result = ml.run_churn_risk_model(df)

    if not result["available"]:
        st.info("Not enough data (or only one customer type present) to train the model for this selection.")
        return

    kpi_row([
        ("Model Accuracy (test set)", f"{result['accuracy']}%"),
        ("Flagged At-Risk", f"{result['at_risk_count']} / {result['evaluated_count']}"),
    ])

    fig = px.pie(
        names=["Flagged At-Risk", "Likely Member"],
        values=[result["at_risk_count"], result["evaluated_count"] - result["at_risk_count"]],
        color_discrete_sequence=["#ef5350", "#8b5cf6"],
    )
    fig.update_layout(title="Risk Distribution (test set)", margin=dict(t=40, b=10, l=10, r=10))
    st.plotly_chart(fig, width="stretch")

    st.subheader("Highest Risk Purchases (test sample)")
    st.dataframe(pd.DataFrame(result["top_risk"]), width="stretch", hide_index=True)


@live_page
def page_recommendations(user):
    st.header("Product Recommendations")
    st.caption("Popularity-based recommendations for the selected shopper segment (top-selling products/categories among similar shoppers).")

    is_full_access = user["role"] in FULL_ACCESS_ROLES
    branches = data.available_branches()
    cols = st.columns(3)
    branch = user["branch"]
    if is_full_access:
        with cols[0]:
            choice = st.selectbox("Branch", ["All branches"] + branches, key="reco_branch")
            branch = None if choice == "All branches" else choice
    with cols[1]:
        customer_type = st.selectbox("Customer Type", ["Any customer type", "Member", "Normal"], key="reco_ctype")
        customer_type = None if customer_type == "Any customer type" else customer_type
    with cols[2]:
        gender = st.selectbox("Gender", ["Any gender", "Male", "Female"], key="reco_gender")
        gender = None if gender == "Any gender" else gender

    df = data.load_sales_df(branch=branch)
    result = ml.get_recommendations(df, branch=None, customer_type=customer_type, gender=gender)
    st.caption(f"Segment size: {result['segment_size']} transactions.")

    c1, c2 = st.columns(2)
    with c1:
        bar_chart(pd.DataFrame(result["products"]), "product_name", "total_price", "Top Products", orientation="h")
    with c2:
        pie_chart(pd.DataFrame(result["categories"]), "product_category", "total_price", "Top Categories")

    t1, t2 = st.columns(2)
    with t1:
        st.subheader("Top Products")
        st.dataframe(pd.DataFrame(result["products"]), width="stretch", hide_index=True)
    with t2:
        st.subheader("Top Categories")
        st.dataframe(pd.DataFrame(result["categories"]), width="stretch", hide_index=True)


# ---------- Daily Revenue / Rewards & Memberships / User Management ----------

@live_page
def page_daily_revenue(user):
    st.header("Daily Revenue")
    st.caption("Day-by-day revenue, transactions, and average basket size.")
    branch, date_from, date_to = branch_date_filters(user, key="daily_revenue")
    df = data.load_sales_df(branch=branch, date_from=date_from, date_to=date_to)
    rows = data.daily_revenue(df)

    if not rows:
        st.info("No dated sales data for this selection.")
        return

    daily_df = pd.DataFrame(rows)
    best_day = daily_df.loc[daily_df["total_revenue"].idxmax()]
    worst_day = daily_df.loc[daily_df["total_revenue"].idxmin()]
    kpi_row([
        ("Days with Sales", len(daily_df)),
        ("Avg. Daily Revenue", money(daily_df['total_revenue'].mean())),
        ("Best Day", f"{best_day['date']} ({money(best_day['total_revenue'])})"),
        ("Slowest Day", f"{worst_day['date']} ({money(worst_day['total_revenue'])})"),
    ])

    daily_df["date"] = pd.to_datetime(daily_df["date"])
    daily_df["rolling_avg_revenue"] = daily_df["total_revenue"].rolling(7, min_periods=1).mean().round(2)
    fig = px.line(daily_df, x="date", y=["total_revenue", "rolling_avg_revenue"], markers=True)
    fig.update_layout(
        title="Daily Revenue vs. 7-Day Rolling Average",
        legend_title_text="",
        margin=dict(t=40, b=10, l=10, r=10),
    )
    fig.for_each_trace(lambda t: t.update(name={"total_revenue": "Daily Revenue", "rolling_avg_revenue": "7-Day Avg"}[t.name]))
    st.plotly_chart(fig, width="stretch")

    day_stats = data.day_of_week_stats(df)
    if day_stats["revenue_by_day"]:
        c1, c2 = st.columns(2)
        with c1:
            bar_chart(pd.DataFrame(day_stats["revenue_by_day"]), "day_of_week", "total_revenue", "Total Revenue by Day of Week")
        with c2:
            bar_chart(pd.DataFrame(day_stats["revenue_by_day"]), "day_of_week", "avg_basket", "Avg. Basket Size by Day of Week")
        st.caption(f"Busiest day of week: **{day_stats['best_day']}** · Slowest day of week: **{day_stats['worst_day']}**")

    st.subheader("Daily Breakdown")
    st.dataframe(daily_df.astype({"date": str}), width="stretch", hide_index=True)


@live_page
def page_sales_forecast(user):
    st.header("Sales Forecast")
    st.caption("Revenue trend projection based on historical daily sales (simple linear trend, no seasonality).")
    branch, date_from, date_to = branch_date_filters(
        user, key="forecast", locked_branch=None if user["role"] in FULL_ACCESS_ROLES else user["branch"]
    )
    periods = st.select_slider("Forecast horizon (days)", options=[7, 14, 30, 60], value=14, key="forecast_periods")
    df = data.load_sales_df(branch=branch, date_from=date_from, date_to=date_to)
    result = ml.forecast_revenue(df, periods=periods)

    if not result["available"]:
        st.info(
            "Not enough dated sales history for this selection to build a forecast "
            "(need at least 10 days of data with sale dates)."
        )
        return

    kpi_row([
        ("Trend", result["trend"].capitalize()),
        ("Daily Trend Change", money(result["daily_trend_change"])),
        (f"Forecasted Revenue (next {periods}d)", money(result["total_forecast_revenue"])),
        ("Model Fit (R²)", f"{result['r2']}"),
    ])

    history_df = pd.DataFrame(result["history"])
    history_df["type"] = "Actual"
    forecast_df = pd.DataFrame(result["forecast"]).rename(columns={"forecast_revenue": "revenue"})
    forecast_df["type"] = "Forecast"
    combined = pd.concat([history_df, forecast_df], ignore_index=True)
    combined["date"] = pd.to_datetime(combined["date"])

    fig = px.line(
        combined, x="date", y="revenue", color="type", markers=True,
        color_discrete_map={"Actual": "#6d28d9", "Forecast": "#f59e0b"},
    )
    fig.update_layout(title="Revenue: Actual vs. Forecast", margin=dict(t=40, b=10, l=10, r=10))
    st.plotly_chart(fig, width="stretch")

    st.subheader("Forecast Detail")
    st.dataframe(pd.DataFrame(result["forecast"]), width="stretch", hide_index=True)


@live_page
def page_branch_comparison(user):
    st.header("Branch Comparison")
    st.caption("Compare revenue, transactions, and basket size across branches.")

    min_date, max_date = data.date_bounds()
    date_from = date_to = None
    if min_date:
        lo, hi = pd.to_datetime(min_date).date(), pd.to_datetime(max_date).date()
        c1, c2 = st.columns(2)
        with c1:
            picked_from = st.date_input("From", value=None, min_value=lo, max_value=hi, key="branch_cmp_from")
        with c2:
            picked_to = st.date_input("To", value=None, min_value=lo, max_value=hi, key="branch_cmp_to")
        date_from, date_to = _validated_date_range(picked_from, picked_to)

    df = data.load_sales_df(date_from=date_from, date_to=date_to)
    result = data.branch_comparison(df)

    if not result["branches"]:
        st.info("No data available for comparison.")
        return

    branches_df = pd.DataFrame(result["branches"])

    c1, c2 = st.columns(2)
    with c1:
        bar_chart(branches_df, "branch", "revenue", "Revenue by Branch")
    with c2:
        bar_chart(branches_df, "branch", "avg_basket", "Avg. Basket Size by Branch")

    c3, c4 = st.columns(2)
    with c3:
        bar_chart(branches_df, "branch", "transactions", "Transactions by Branch")
    with c4:
        bar_chart(branches_df, "branch", "member_revenue_share_pct", "Member Revenue Share (%) by Branch")

    if result["top_category_by_branch"]:
        st.subheader("Top Category per Branch")
        st.dataframe(pd.DataFrame(result["top_category_by_branch"]), width="stretch", hide_index=True)

    st.subheader("Full Comparison Table")
    st.dataframe(branches_df, width="stretch", hide_index=True)


@live_page
def page_rewards(user):
    st.header("Rewards & Memberships")
    st.caption(
        "Membership tiers derived from reward points earned per transaction. This dataset has "
        "no per-customer IDs, so tiers are assigned per-transaction rather than per-customer."
    )
    branch, date_from, date_to = branch_date_filters(user, key="rewards")
    df = data.load_sales_df(branch=branch, date_from=date_from, date_to=date_to)
    result = data.membership_tiers(df)

    if not result["tiers"]:
        st.info("Not enough data to build membership tiers for this selection.")
        return

    if result["metric_used"] == "total_price":
        st.warning(
            "This dataset's reward_points column has no variance (likely 0 for every row), "
            "so tiers are based on transaction spend instead of reward points."
        )

    tiers_df = pd.DataFrame(result["tiers"])
    kpi_row([
        ("Total Reward Points Issued", result["total_points"]),
        ("Avg. Points / Transaction", f"{tiers_df['avg_reward_points'].mean():.1f}"),
    ])

    c1, c2 = st.columns(2)
    with c1:
        fig = px.pie(
            tiers_df, names="tier", values="transactions",
            color="tier", color_discrete_map=TIER_COLORS,
        )
        fig.update_layout(title="Tier Distribution (Transactions)", margin=dict(t=40, b=10, l=10, r=10))
        st.plotly_chart(fig, width="stretch")
    with c2:
        fig = px.bar(
            tiers_df, x="tier", y="revenue", color="tier",
            color_discrete_map=TIER_COLORS,
        )
        fig.update_layout(title="Revenue by Tier", showlegend=False, margin=dict(t=40, b=10, l=10, r=10))
        st.plotly_chart(fig, width="stretch")

    trend_rows = data.membership_tier_trend(df)
    if trend_rows:
        fig = px.line(
            pd.DataFrame(trend_rows), x="date", y="total_price", color="tier",
            color_discrete_map=TIER_COLORS, markers=True,
        )
        fig.update_layout(title="Revenue by Tier Over Time", margin=dict(t=40, b=10, l=10, r=10))
        st.plotly_chart(fig, width="stretch")

    metric_label = "Reward Points" if result["metric_used"] == "reward_points" else "Transaction Spend ($)"
    fig = px.histogram(df, x=result["metric_used"], nbins=30, color_discrete_sequence=["#8b5cf6"])
    fig.update_layout(
        title=f"{metric_label} Distribution",
        xaxis_title=metric_label, yaxis_title="Transactions",
        margin=dict(t=40, b=10, l=10, r=10),
    )
    st.plotly_chart(fig, width="stretch")

    st.subheader("Tier Summary")
    st.dataframe(tiers_df, width="stretch", hide_index=True)


def page_reports(user):
    st.header("Reports")
    st.caption("Printable summary report for the selected branch and date range.")

    with st.expander("📤 Upload a dataset for this report"):
        st.caption(
            "Uploading here replaces the active dataset app-wide (same as the Upload Dataset page). "
            "To get an Inventory Report, include a `stock_quantity` column (and optionally `reorder_level`) "
            "in your file — the sample dataset doesn't track stock, only transactions."
        )
        uploaded = st.file_uploader("Choose a CSV file", type=["csv"], key="reports_uploader")
        if uploaded is not None:
            new_df, error = data.validate_uploaded_csv(uploaded)
            if error:
                st.error(error)
            else:
                data.save_active_dataset(new_df)
                st.success(f"Dataset uploaded — {len(new_df)} rows loaded.")
                st.rerun()

    branch, date_from, date_to = branch_date_filters(user, key="reports", locked_branch=None if user["role"] in FULL_ACCESS_ROLES else user["branch"])
    df = data.load_sales_df(branch=branch, date_from=date_from, date_to=date_to)
    report = data.full_report(df, branch=branch, date_from=date_from, date_to=date_to)
    stats = report["summary"]

    st.subheader(f"Scope: {report['scope']}")
    kpi_row([
        ("Total Revenue", money(stats['total_revenue'])),
        ("Transactions", stats["total_transactions"]),
        ("Avg. Basket Size", money(stats['avg_basket'])),
        ("Reward Points Issued", stats["total_reward_points"]),
    ])

    if report["row_count"] == 0:
        st.info("No data for this selection.")
        return

    dl1, dl2 = st.columns(2)
    with dl1:
        pdf_bytes = reports.build_summary_pdf(report, generated_by=user["username"])
        st.download_button(
            "Download PDF Report",
            data=pdf_bytes,
            file_name=f"infinity-mart-report-{branch or 'all-branches'}.pdf",
            mime="application/pdf",
        )
    with dl2:
        excel_bytes = reports.build_summary_excel(report)
        st.download_button(
            "Download Excel Report",
            data=excel_bytes,
            file_name=f"infinity-mart-report-{branch or 'all-branches'}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        bar_chart(pd.DataFrame(stats["top_products"]), "product_name", "total_price", "Top Products", orientation="h")
    with c2:
        pie_chart(pd.DataFrame(stats["sales_by_category"]), "product_category", "total_price", "Revenue by Category")

    st.subheader("Revenue by Branch")
    st.dataframe(pd.DataFrame(stats["sales_by_branch"]), width="stretch", hide_index=True)

    if report["day_stats"]["revenue_by_day"]:
        st.subheader("Revenue by Day of Week")
        st.dataframe(pd.DataFrame(report["day_stats"]["revenue_by_day"]), width="stretch", hide_index=True)

    if report["tiers"]["tiers"]:
        st.subheader("Membership Tier Summary")
        st.dataframe(pd.DataFrame(report["tiers"]["tiers"]), width="stretch", hide_index=True)

    st.divider()
    st.subheader("🛒 Product Report")
    products = report["products"]
    p1, p2 = st.columns(2)
    with p1:
        st.caption("Best-selling products")
        st.dataframe(pd.DataFrame(products["best_sellers"]), width="stretch", hide_index=True)
    with p2:
        st.caption("Least-selling products")
        st.dataframe(pd.DataFrame(products["least_sellers"]), width="stretch", hide_index=True)
    if products["category_performance"]:
        st.caption("Product category performance")
        bar_chart(pd.DataFrame(products["category_performance"]), "product_category", "revenue", "Revenue by Category")
        st.dataframe(pd.DataFrame(products["category_performance"]), width="stretch", hide_index=True)

    st.divider()
    st.subheader("📦 Inventory Report")
    inventory = report["inventory"]
    if not inventory["available"]:
        st.info(
            "This dataset has no stock data. Upload a dataset with a `stock_quantity` column "
            "(and optionally `reorder_level`) above to unlock available/low/out-of-stock reporting."
        )
    else:
        kpi_row([
            ("Products Tracked", inventory["total_products"]),
            ("Low Stock", inventory["low_stock_count"]),
            ("Out of Stock", inventory["out_of_stock_count"]),
        ])
        i1, i2 = st.columns(2)
        with i1:
            st.caption("Low-stock products")
            st.dataframe(pd.DataFrame(inventory["low_stock"]), width="stretch", hide_index=True)
        with i2:
            st.caption("Out-of-stock products")
            st.dataframe(pd.DataFrame(inventory["out_of_stock"]), width="stretch", hide_index=True)
        with st.expander("Full stock list"):
            st.dataframe(pd.DataFrame(inventory["products"]), width="stretch", hide_index=True)

    st.divider()
    st.subheader("🏆 Membership & Loyalty Report")
    membership = report["membership"]
    if not membership["available"]:
        st.info("No data for this selection.")
    else:
        st.caption(
            "This dataset has no per-customer ID, so 'active members' is a transaction-count proxy "
            "rather than a count of unique members."
        )
        kpi_row([
            ("Member Transactions", membership["member_transactions"]),
            ("Reward Points Earned", membership["reward_points_earned"]),
        ])
        st.caption("Membership-wise purchases")
        st.dataframe(pd.DataFrame(membership["purchases_by_membership"]), width="stretch", hide_index=True)

    st.divider()
    st.subheader("📍 Regional / Branch Report")
    regional = report["regional"]
    if not regional["available"]:
        st.info("No data for this selection.")
    else:
        st.caption(f"Top-performing branch: **{regional['top_branch']}**")
        r1, r2 = st.columns(2)
        with r1:
            bar_chart(pd.DataFrame(regional["by_location"]), "city", "revenue", "Sales by Location")
        with r2:
            bar_chart(pd.DataFrame(regional["by_branch"]), "branch", "revenue", "Sales by Branch")


def page_user_management(user):
    st.header("User Management")
    st.caption("Create, edit, and remove accounts. Admin/analyst access only.")

    users = User.list_all()
    rows = [
        {
            "username": u.username,
            "role": u.role,
            "branch": u.branch or "—",
            "locked": "Yes" if User.is_locked(u) else "No",
        }
        for u in users
    ]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    st.subheader("Create User")
    branches = data.available_branches()
    with st.form("create_user_form"):
        cols = st.columns(4)
        new_username = cols[0].text_input("Username")
        new_role = cols[1].selectbox("Role", ["manager", "analyst", "admin"])
        new_branch = cols[2].selectbox("Branch", ["(none)"] + branches)
        new_password = cols[3].text_input("Password", type="password")
        create_submitted = st.form_submit_button("Create user")
    if create_submitted:
        branch_value = None if new_branch == "(none)" else new_branch
        _, error = User.create(new_username, new_password, new_role, branch_value)
        if error:
            st.error(error)
        else:
            st.success(f"Created user {new_username}.")
            st.rerun()

    st.subheader("Edit / Remove User")
    usernames = [u.username for u in users]
    selected_username = st.selectbox("Select user", usernames, key="manage_user_select")
    selected = next((u for u in users if u.username == selected_username), None)
    if selected:
        cols = st.columns(4)
        edit_role = cols[0].selectbox("Role", ["manager", "analyst", "admin"], index=["manager", "analyst", "admin"].index(selected.role), key="edit_role")
        edit_branch = cols[1].selectbox("Branch", ["(none)"] + branches, index=(["(none)"] + branches).index(selected.branch) if selected.branch in branches else 0, key="edit_branch")
        if cols[2].button("Save changes"):
            User.set_role_branch(selected.id, edit_role, None if edit_branch == "(none)" else edit_branch)
            st.success("User updated.")
            st.rerun()
        if cols[3].button("Delete user", disabled=selected.username == user["username"]):
            User.delete(selected.id)
            st.success(f"Deleted {selected.username}.")
            st.rerun()

        with st.expander("Reset password"):
            with st.form("admin_reset_password_form"):
                reset_password = st.text_input("New password", type="password")
                reset_submitted = st.form_submit_button("Reset password")
            if reset_submitted:
                if len(reset_password) < 6:
                    st.error("Password must be at least 6 characters.")
                else:
                    User.set_password(selected.id, reset_password)
                    st.success(f"Password reset for {selected.username}.")


PAGES = {
    "Dashboard": page_dashboard,
    "Upload Dataset": page_upload,
    "Data Preparation": page_data_preparation,
    "Exploratory Analysis": page_exploratory,
    "Customer Profile": page_customer_profile,
    "Customer Segmentation": page_segmentation,
    "Customer Analytics": page_customer_analytics,
    "Churn Prediction": page_churn,
    "Product Recommendations": page_recommendations,
    "Daily Revenue": page_daily_revenue,
    "Sales Forecast": page_sales_forecast,
    "Branch Comparison": page_branch_comparison,
    "Rewards & Memberships": page_rewards,
    "Reports": page_reports,
    "User Management": page_user_management,
}


def main():
    st.set_page_config(page_title="Infinity Mart Insights", page_icon="⚡", layout="wide")
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
    page = render_sidebar(st.session_state.user)
    try:
        PAGES[page](st.session_state.user)
    except Exception:
        logging.error("Error rendering page %r:\n%s", page, traceback.format_exc())
        st.error(
            "Something went wrong loading this page. This is usually caused by the "
            "underlying data file being briefly unavailable (e.g. mid-write). "
            "Please try again — if it keeps happening, let an admin know."
        )
        if st.button("Retry", key=f"retry_{page}"):
            st.rerun()


if __name__ == "__main__":
    main()

