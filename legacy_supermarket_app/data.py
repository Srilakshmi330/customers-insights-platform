import re
import time
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).parent
ORIGINAL_CSV_PATH = BASE_DIR / "sales.csv"
DATA_DIR = BASE_DIR / "data"
ACTIVE_CSV_PATH = DATA_DIR / "active_sales.csv"

REQUIRED_COLUMNS = [
    "sale_id",
    "branch",
    "city",
    "customer_type",
    "gender",
    "product_name",
    "product_category",
    "unit_price",
    "quantity",
    "tax",
    "total_price",
    "reward_points",
]

# Transactions must at least identify who/what/how much and which branch. Everything else
# (sale_id, city, product_name, tax, total_price, reward_points) can be derived.
CORE_REQUIRED_COLUMNS = ["branch", "customer_type", "gender", "unit_price", "quantity"]

# Accepts common alternate column names, e.g. from the popular Kaggle
# "Supermarket Sales" dataset (Invoice ID, Product line, Tax 5%, Total, ...).
COLUMN_ALIASES = {
    "sale_id": ["sale_id", "invoice_id", "id", "transaction_id"],
    "branch": ["branch", "store", "outlet"],
    "city": ["city", "location"],
    "customer_type": ["customer_type", "membership", "member_type"],
    "gender": ["gender", "sex"],
    "product_name": ["product_name", "item", "item_name", "product"],
    "product_category": ["product_category", "product_line", "category", "product_type"],
    "unit_price": ["unit_price", "price"],
    "quantity": ["quantity", "qty"],
    "tax": ["tax", "tax_5", "tax_5_percent", "vat"],
    "total_price": ["total_price", "total", "sales", "gross_sales"],
    "reward_points": ["reward_points", "loyalty_points", "points"],
    "sale_date": ["sale_date", "date", "order_date", "purchase_date"],
    "payment_method": ["payment_method", "payment", "payment_type"],
    "rating": ["rating", "review_rating", "customer_rating"],
    "stock_quantity": ["stock_quantity", "stock", "quantity_in_stock", "inventory", "available_stock", "stock_on_hand"],
    "reorder_level": ["reorder_level", "low_stock_threshold", "min_stock", "reorder_point"],
}

OPTIONAL_DERIVED_COLUMNS = ["sale_date", "payment_method", "rating", "stock_quantity", "reorder_level"]

# Old branch/city name -> new city name, for reconciling data uploaded before the
# Infinity Central/North/South -> Los Angeles/New York/Chicago account rename.
BRANCH_RENAME_MAP = {
    "Brooklyn": "Los Angeles",
    "Queens": "New York",
    "Manhattan": "Chicago",
}


def _normalize_column_name(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def map_uploaded_columns(df):
    """Rename columns to our canonical names using COLUMN_ALIASES, case/punctuation-insensitively."""
    alias_lookup = {
        _normalize_column_name(alias): canonical
        for canonical, aliases in COLUMN_ALIASES.items()
        for alias in aliases
    }
    rename_map = {}
    for col in df.columns:
        normalized = _normalize_column_name(col)
        if normalized in alias_lookup:
            rename_map[col] = alias_lookup[normalized]
    return df.rename(columns=rename_map)


def ensure_active_dataset():
    """Seed the working dataset from the original sample CSV on first run."""
    DATA_DIR.mkdir(exist_ok=True)
    if not ACTIVE_CSV_PATH.exists():
        pd.read_csv(ORIGINAL_CSV_PATH).to_csv(ACTIVE_CSV_PATH, index=False)
    migrate_branch_names()


def migrate_branch_names():
    """Relabel any branch/city values still using the pre-rename names (e.g. from a
    dataset uploaded before Infinity Central/North/South became Los Angeles/New York/Chicago)."""
    if not ACTIVE_CSV_PATH.exists():
        return
    df = _read_active_csv_with_retry()
    if not set(BRANCH_RENAME_MAP).intersection(df.get("branch", pd.Series(dtype=object)).unique()):
        return
    df["branch"] = df["branch"].replace(BRANCH_RENAME_MAP)
    if "city" in df.columns:
        df["city"] = df["city"].replace(BRANCH_RENAME_MAP)
    df.to_csv(ACTIVE_CSV_PATH, index=False)


def _read_active_csv_with_retry(attempts=3, delay_seconds=0.3):
    """Cloud-synced folders (OneDrive, etc.) can briefly serve a truncated/empty
    file while writing it out. Retry a couple of times before giving up."""
    last_error = None
    for attempt in range(attempts):
        try:
            df = pd.read_csv(ACTIVE_CSV_PATH)
            if df.empty and attempt < attempts - 1:
                raise pd.errors.EmptyDataError("active dataset read as empty")
            return df
        except (pd.errors.EmptyDataError, pd.errors.ParserError) as exc:
            last_error = exc
            if attempt < attempts - 1:
                time.sleep(delay_seconds)
    raise last_error


def load_sales_df(branch=None, date_from=None, date_to=None):
    ensure_active_dataset()
    df = _read_active_csv_with_retry()
    if branch:
        df = df[df["branch"] == branch]
    if "sale_date" in df.columns and (date_from or date_to):
        parsed = pd.to_datetime(df["sale_date"], errors="coerce")
        mask = pd.Series(True, index=df.index)
        if date_from:
            mask &= parsed >= pd.to_datetime(date_from)
        if date_to:
            mask &= parsed <= pd.to_datetime(date_to)
        df = df[mask]
    return df


def date_bounds():
    """Earliest/latest sale_date in the active dataset, as ISO strings (None, None if unavailable)."""
    df = load_sales_df()
    if "sale_date" not in df.columns:
        return None, None
    parsed = pd.to_datetime(df["sale_date"], errors="coerce").dropna()
    if parsed.empty:
        return None, None
    return parsed.min().date().isoformat(), parsed.max().date().isoformat()


def available_branches():
    """Branch codes actually present in the active dataset (uploaded datasets may not use A/B)."""
    df = load_sales_df()
    return sorted(df["branch"].dropna().astype(str).unique().tolist())


def save_active_dataset(df):
    DATA_DIR.mkdir(exist_ok=True)
    df.to_csv(ACTIVE_CSV_PATH, index=False)


def reset_active_dataset():
    pd.read_csv(ORIGINAL_CSV_PATH).to_csv(ACTIVE_CSV_PATH, index=False)


def validate_uploaded_csv(file_stream):
    """Return (df, error_message). df is None if validation fails.

    Column names are matched flexibly (case/punctuation-insensitive aliases), and
    anything not essential (sale_id, product_name, tax, total_price, reward_points)
    is derived if missing, so datasets like Kaggle's "Supermarket Sales" export
    (Invoice ID, Product line, Tax 5%, Total, ...) upload without renaming columns.
    """
    try:
        df = pd.read_csv(file_stream)
    except Exception as exc:
        return None, f"Could not read this file as CSV: {exc}"

    df = map_uploaded_columns(df)

    missing = [col for col in CORE_REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        return None, (
            f"Missing required column(s): {', '.join(missing)}. "
            f"Found columns: {', '.join(df.columns)}"
        )

    if "product_category" not in df.columns:
        return None, "Missing a product category / product line column."

    if "city" not in df.columns:
        df["city"] = df["branch"]

    if "product_name" not in df.columns:
        df["product_name"] = df["product_category"]

    base = df["unit_price"] * df["quantity"]
    if "total_price" not in df.columns:
        if "tax" in df.columns:
            df["total_price"] = (base + df["tax"]).round(2)
        else:
            df["tax"] = (base * 0.05).round(2)
            df["total_price"] = (base + df["tax"]).round(2)
    elif "tax" not in df.columns:
        df["tax"] = (df["total_price"] - base).round(2)

    if "reward_points" not in df.columns:
        df["reward_points"] = 0

    if "sale_id" not in df.columns:
        df["sale_id"] = range(1, len(df) + 1)

    keep_cols = REQUIRED_COLUMNS + [c for c in OPTIONAL_DERIVED_COLUMNS if c in df.columns]
    return df[keep_cols], None


def quality_report(df):
    missing_counts = df.isna().sum()
    missing = [
        {"column": col, "missing": int(count)}
        for col, count in missing_counts.items()
        if count > 0
    ]
    duplicate_rows = int(df.duplicated().sum())
    numeric_cols = df.select_dtypes(include="number").columns
    numeric_summary = (
        df[numeric_cols].describe().round(2).transpose().reset_index().rename(columns={"index": "column"})
        .to_dict("records")
    )
    return {
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
        "missing": missing,
        "duplicate_rows": duplicate_rows,
        "numeric_summary": numeric_summary,
    }


def clean_dataset(df):
    """Drop exact duplicates and rows missing required fields."""
    before = len(df)
    cleaned = df.drop_duplicates()
    cleaned = cleaned.dropna(subset=REQUIRED_COLUMNS)
    after = len(cleaned)
    return cleaned, before - after


def summarize(df):
    """Build the aggregate figures used across dashboards."""
    if df.empty:
        return {
            "total_revenue": 0,
            "total_transactions": 0,
            "avg_basket": 0,
            "total_reward_points": 0,
            "top_products": [],
            "sales_by_category": [],
            "sales_by_city": [],
            "sales_by_branch": [],
            "customer_type_split": [],
            "revenue_by_gender": [],
        }

    total_revenue = round(df["total_price"].sum(), 2)
    total_transactions = int(len(df))
    avg_basket = round(total_revenue / total_transactions, 2) if total_transactions else 0
    total_reward_points = int(df["reward_points"].sum())

    top_products = (
        df.groupby("product_name")["total_price"]
        .sum()
        .sort_values(ascending=False)
        .head(5)
        .round(2)
        .reset_index()
        .to_dict("records")
    )

    sales_by_category = (
        df.groupby("product_category")["total_price"]
        .sum()
        .round(2)
        .sort_values(ascending=False)
        .reset_index()
        .to_dict("records")
    )

    sales_by_city = (
        df.groupby("city")["total_price"]
        .sum()
        .round(2)
        .sort_values(ascending=False)
        .reset_index()
        .to_dict("records")
    )

    sales_by_branch = (
        df.groupby("branch")["total_price"]
        .sum()
        .round(2)
        .sort_values(ascending=False)
        .reset_index()
        .to_dict("records")
    )

    customer_type_split = (
        df.groupby("customer_type")["total_price"]
        .sum()
        .round(2)
        .reset_index()
        .to_dict("records")
    )

    revenue_by_gender = (
        df.groupby("gender")["total_price"]
        .sum()
        .round(2)
        .reset_index()
        .to_dict("records")
    )

    return {
        "total_revenue": total_revenue,
        "total_transactions": total_transactions,
        "avg_basket": avg_basket,
        "total_reward_points": total_reward_points,
        "top_products": top_products,
        "sales_by_category": sales_by_category,
        "sales_by_city": sales_by_city,
        "sales_by_branch": sales_by_branch,
        "customer_type_split": customer_type_split,
        "revenue_by_gender": revenue_by_gender,
    }


def exploratory_stats(df):
    if df.empty:
        return {
            "price_buckets": [],
            "quantity_buckets": [],
            "revenue_by_gender": [],
            "category_transaction_share": [],
            "sales_trend": [],
        }

    price_bins = [0, 5, 10, 15, 20, float("inf")]
    price_labels = ["$0-5", "$5-10", "$10-15", "$15-20", "$20+"]
    price_buckets = (
        pd.cut(df["unit_price"], bins=price_bins, labels=price_labels, right=False)
        .value_counts()
        .reindex(price_labels, fill_value=0)
        .reset_index()
    )
    price_buckets.columns = ["bucket", "count"]

    qty_bins = [0, 5, 10, 15, 20, float("inf")]
    qty_labels = ["1-5", "6-10", "11-15", "16-20", "21+"]
    quantity_buckets = (
        pd.cut(df["quantity"], bins=qty_bins, labels=qty_labels, right=True)
        .value_counts()
        .reindex(qty_labels, fill_value=0)
        .reset_index()
    )
    quantity_buckets.columns = ["bucket", "count"]

    revenue_by_gender = (
        df.groupby("gender")["total_price"]
        .sum()
        .round(2)
        .reset_index()
        .to_dict("records")
    )

    category_transaction_share = (
        df.groupby("product_category")["sale_id"]
        .count()
        .sort_values(ascending=False)
        .reset_index()
        .rename(columns={"sale_id": "count"})
        .to_dict("records")
    )

    sales_trend = []
    if "sale_date" in df.columns:
        parsed_dates = pd.to_datetime(df["sale_date"], errors="coerce")
        if parsed_dates.notna().any():
            trend_df = df.assign(_date=parsed_dates.dt.date).dropna(subset=["_date"])
            sales_trend = (
                trend_df.groupby("_date")["total_price"]
                .sum()
                .round(2)
                .reset_index()
                .rename(columns={"_date": "date"})
                .sort_values("date")
                .astype({"date": str})
                .to_dict("records")
            )

    return {
        "price_buckets": price_buckets.to_dict("records"),
        "quantity_buckets": quantity_buckets.to_dict("records"),
        "revenue_by_gender": revenue_by_gender,
        "category_transaction_share": category_transaction_share,
        "sales_trend": sales_trend,
    }


def customer_profiles(df):
    if df.empty:
        return []
    grouped = (
        df.groupby(["customer_type", "gender"])
        .agg(
            transactions=("sale_id", "count"),
            revenue=("total_price", "sum"),
            avg_basket=("total_price", "mean"),
            reward_points=("reward_points", "sum"),
        )
        .round(2)
        .reset_index()
        .sort_values("revenue", ascending=False)
    )
    return grouped.to_dict("records")


def daily_revenue(df):
    """Per-day revenue/transactions/avg-basket cut (day-by-day detail, vs. the smoothed
    trend line in exploratory_stats)."""
    if df.empty or "sale_date" not in df.columns:
        return []
    parsed = pd.to_datetime(df["sale_date"], errors="coerce")
    working = df.assign(_date=parsed.dt.date).dropna(subset=["_date"])
    if working.empty:
        return []
    grouped = (
        working.groupby("_date")
        .agg(total_revenue=("total_price", "sum"), transactions=("sale_id", "count"))
        .round(2)
        .reset_index()
        .rename(columns={"_date": "date"})
        .sort_values("date")
    )
    grouped["avg_basket"] = (grouped["total_revenue"] / grouped["transactions"]).round(2)
    return grouped.astype({"date": str}).to_dict("records")


DAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def day_of_week_stats(df):
    """Revenue/transaction patterns by day of week, to find the busiest and slowest days."""
    if df.empty or "sale_date" not in df.columns:
        return {"revenue_by_day": [], "best_day": None, "worst_day": None}

    parsed = pd.to_datetime(df["sale_date"], errors="coerce")
    working = df.assign(_day=parsed.dt.day_name()).dropna(subset=["_day"])
    if working.empty:
        return {"revenue_by_day": [], "best_day": None, "worst_day": None}

    grouped = (
        working.groupby("_day")
        .agg(total_revenue=("total_price", "sum"), transactions=("sale_id", "count"))
        .reindex(DAY_ORDER, fill_value=0)
        .round(2)
        .reset_index()
        .rename(columns={"_day": "day_of_week"})
    )
    grouped["avg_basket"] = (
        grouped["total_revenue"] / grouped["transactions"].replace(0, pd.NA)
    ).round(2).fillna(0)

    present = grouped[grouped["transactions"] > 0]
    best_day = present.loc[present["total_revenue"].idxmax(), "day_of_week"] if not present.empty else None
    worst_day = present.loc[present["total_revenue"].idxmin(), "day_of_week"] if not present.empty else None

    return {
        "revenue_by_day": grouped.to_dict("records"),
        "best_day": best_day,
        "worst_day": worst_day,
    }


MEMBERSHIP_TIER_LABELS = ["Bronze", "Silver", "Gold", "Platinum"]


def membership_tiers(df):
    """Buckets transactions into membership tiers by reward points earned. If the dataset's
    reward_points has no variance (e.g. an uploaded dataset that never populated it), falls
    back to tiering by transaction spend instead, since there's no per-customer ID to tier by."""
    if df.empty:
        return {"tiers": [], "metric_used": None, "total_points": 0}

    metric = "reward_points"
    if "reward_points" not in df.columns or df["reward_points"].nunique() <= 1:
        metric = "total_price"

    working = df.dropna(subset=[metric]).copy()
    if len(working) < len(MEMBERSHIP_TIER_LABELS):
        return {"tiers": [], "metric_used": metric, "total_points": int(df.get("reward_points", pd.Series(dtype=float)).sum())}

    try:
        working["tier"] = pd.qcut(working[metric], q=len(MEMBERSHIP_TIER_LABELS), labels=MEMBERSHIP_TIER_LABELS, duplicates="drop")
    except ValueError:
        return {"tiers": [], "metric_used": metric, "total_points": int(df.get("reward_points", pd.Series(dtype=float)).sum())}

    summary = (
        working.groupby("tier", observed=True)
        .agg(
            transactions=("sale_id", "count"),
            revenue=("total_price", "sum"),
            avg_reward_points=("reward_points", "mean"),
        )
        .round(2)
        .reset_index()
        .to_dict("records")
    )

    return {
        "tiers": summary,
        "metric_used": metric,
        "total_points": int(df["reward_points"].sum()) if "reward_points" in df.columns else 0,
    }


def membership_tier_trend(df):
    """Daily revenue by membership tier, so tier growth/decline over time is visible.
    Uses the same metric (reward points, or spend as a fallback) as membership_tiers()."""
    if df.empty or "sale_date" not in df.columns:
        return []

    metric = "reward_points"
    if "reward_points" not in df.columns or df["reward_points"].nunique() <= 1:
        metric = "total_price"

    working = df.dropna(subset=[metric, "sale_date"]).copy()
    if len(working) < len(MEMBERSHIP_TIER_LABELS):
        return []

    try:
        working["tier"] = pd.qcut(
            working[metric], q=len(MEMBERSHIP_TIER_LABELS), labels=MEMBERSHIP_TIER_LABELS, duplicates="drop"
        )
    except ValueError:
        return []

    parsed = pd.to_datetime(working["sale_date"], errors="coerce")
    working = working.assign(_date=parsed.dt.date).dropna(subset=["_date"])
    if working.empty:
        return []

    grouped = (
        working.groupby(["_date", "tier"], observed=True)["total_price"]
        .sum()
        .round(2)
        .reset_index()
        .rename(columns={"_date": "date"})
        .sort_values("date")
        .astype({"date": str})
    )
    return grouped.to_dict("records")


def customer_analytics(df):
    if df.empty:
        return {
            "avg_basket_by_category": [],
            "reward_points_by_customer_type": [],
            "transactions_by_customer_type": [],
            "payment_method_split": [],
            "avg_rating_by_branch": [],
            "avg_rating_by_category": [],
            "category_by_membership": [],
            "branch_by_membership": [],
        }

    avg_basket_by_category = (
        df.groupby("product_category")["total_price"]
        .mean()
        .round(2)
        .sort_values(ascending=False)
        .reset_index()
        .to_dict("records")
    )

    reward_points_by_customer_type = (
        df.groupby("customer_type")["reward_points"]
        .mean()
        .round(2)
        .reset_index()
        .to_dict("records")
    )

    transactions_by_customer_type = (
        df.groupby("customer_type")["sale_id"]
        .count()
        .reset_index()
        .rename(columns={"sale_id": "count"})
        .to_dict("records")
    )

    payment_method_split = []
    if "payment_method" in df.columns:
        payment_method_split = (
            df.groupby("payment_method")["total_price"]
            .sum()
            .round(2)
            .sort_values(ascending=False)
            .reset_index()
            .to_dict("records")
        )

    avg_rating_by_branch = []
    avg_rating_by_category = []
    if "rating" in df.columns:
        avg_rating_by_branch = (
            df.groupby("branch")["rating"]
            .mean()
            .round(2)
            .sort_values(ascending=False)
            .reset_index()
            .to_dict("records")
        )
        avg_rating_by_category = (
            df.groupby("product_category")["rating"]
            .mean()
            .round(2)
            .sort_values(ascending=False)
            .reset_index()
            .to_dict("records")
        )

    category_by_membership = (
        df.groupby(["product_category", "customer_type"])["total_price"]
        .sum()
        .round(2)
        .reset_index()
        .to_dict("records")
    )

    branch_by_membership = (
        df.groupby(["branch", "customer_type"])["total_price"]
        .sum()
        .round(2)
        .reset_index()
        .to_dict("records")
    )

    return {
        "avg_basket_by_category": avg_basket_by_category,
        "reward_points_by_customer_type": reward_points_by_customer_type,
        "transactions_by_customer_type": transactions_by_customer_type,
        "payment_method_split": payment_method_split,
        "avg_rating_by_branch": avg_rating_by_branch,
        "avg_rating_by_category": avg_rating_by_category,
        "category_by_membership": category_by_membership,
        "branch_by_membership": branch_by_membership,
    }


def branch_comparison(df):
    """Per-branch metrics side by side, for comparing performance across branches."""
    if df.empty:
        return {"branches": [], "top_category_by_branch": []}

    grouped = (
        df.groupby("branch")
        .agg(
            revenue=("total_price", "sum"),
            transactions=("sale_id", "count"),
            avg_basket=("total_price", "mean"),
            reward_points=("reward_points", "sum"),
        )
        .round(2)
        .reset_index()
        .sort_values("revenue", ascending=False)
    )

    member_share = (
        df[df["customer_type"] == "Member"]
        .groupby("branch")["total_price"]
        .sum()
        .reindex(grouped["branch"], fill_value=0)
    )
    grouped["member_revenue_share_pct"] = (
        (member_share.values / grouped["revenue"].replace(0, pd.NA) * 100).round(1).fillna(0)
    )

    top_category_by_branch = (
        df.groupby(["branch", "product_category"])["total_price"]
        .sum()
        .reset_index()
        .sort_values("total_price", ascending=False)
        .groupby("branch")
        .first()
        .reset_index()
        .rename(columns={"product_category": "top_category", "total_price": "top_category_revenue"})
        .round(2)
        .to_dict("records")
    )

    return {
        "branches": grouped.to_dict("records"),
        "top_category_by_branch": top_category_by_branch,
    }


def product_report(df, top_n=10):
    """Best/least-selling products by revenue and category-level performance."""
    if df.empty:
        return {"best_sellers": [], "least_sellers": [], "category_performance": []}

    by_product = (
        df.groupby("product_name")
        .agg(revenue=("total_price", "sum"), quantity_sold=("quantity", "sum"), transactions=("sale_id", "count"))
        .round(2)
        .reset_index()
    )

    best_sellers = by_product.sort_values("revenue", ascending=False).head(top_n).to_dict("records")
    least_sellers = by_product.sort_values("revenue", ascending=True).head(top_n).to_dict("records")

    category_performance = (
        df.groupby("product_category")
        .agg(revenue=("total_price", "sum"), quantity_sold=("quantity", "sum"), transactions=("sale_id", "count"))
        .round(2)
        .sort_values("revenue", ascending=False)
        .reset_index()
        .to_dict("records")
    )

    return {
        "best_sellers": best_sellers,
        "least_sellers": least_sellers,
        "category_performance": category_performance,
    }


DEFAULT_LOW_STOCK_THRESHOLD = 10


def inventory_report(df):
    """Available/low/out-of-stock breakdown by product. Requires an uploaded dataset with a
    stock_quantity column (this app's sample sales data has no inventory data of its own,
    since it's transaction-level, not stock-level)."""
    if df.empty or "stock_quantity" not in df.columns:
        return {"available": False}

    working = df.dropna(subset=["stock_quantity"]).copy()
    if working.empty:
        return {"available": False}

    if "sale_date" in working.columns:
        working["_sort"] = pd.to_datetime(working["sale_date"], errors="coerce")
        working = working.sort_values("_sort")

    latest = working.groupby("product_name").last().reset_index()
    if "reorder_level" not in latest.columns:
        latest["reorder_level"] = DEFAULT_LOW_STOCK_THRESHOLD
    latest["reorder_level"] = latest["reorder_level"].fillna(DEFAULT_LOW_STOCK_THRESHOLD)

    stock_df = latest[["product_name", "product_category", "stock_quantity", "reorder_level"]].round(2).copy()
    stock_df["status"] = stock_df.apply(
        lambda r: "Out of Stock" if r["stock_quantity"] <= 0
        else ("Low Stock" if r["stock_quantity"] <= r["reorder_level"] else "In Stock"),
        axis=1,
    )

    low_stock = stock_df[stock_df["status"] == "Low Stock"]
    out_of_stock = stock_df[stock_df["status"] == "Out of Stock"]

    return {
        "available": True,
        "products": stock_df.to_dict("records"),
        "low_stock": low_stock.to_dict("records"),
        "out_of_stock": out_of_stock.to_dict("records"),
        "total_products": int(len(stock_df)),
        "low_stock_count": int(len(low_stock)),
        "out_of_stock_count": int(len(out_of_stock)),
    }


def membership_report(df):
    """Membership/loyalty figures. 'Active members' is a transaction-count proxy since this
    dataset has no per-customer ID to count unique members by."""
    if df.empty:
        return {"available": False}

    purchases_by_membership = (
        df.groupby("customer_type")
        .agg(transactions=("sale_id", "count"), revenue=("total_price", "sum"), reward_points=("reward_points", "sum"))
        .round(2)
        .reset_index()
        .to_dict("records")
    )

    return {
        "available": True,
        "member_transactions": int((df["customer_type"] == "Member").sum()),
        "reward_points_earned": int(df["reward_points"].sum()) if "reward_points" in df.columns else 0,
        "purchases_by_membership": purchases_by_membership,
    }


def regional_report(df):
    """Sales by location/branch and the top-performing branch."""
    if df.empty:
        return {"available": False}

    by_branch = (
        df.groupby("branch")
        .agg(revenue=("total_price", "sum"), transactions=("sale_id", "count"))
        .round(2)
        .sort_values("revenue", ascending=False)
        .reset_index()
    )
    by_location = (
        df.groupby("city")
        .agg(revenue=("total_price", "sum"), transactions=("sale_id", "count"))
        .round(2)
        .sort_values("revenue", ascending=False)
        .reset_index()
    )

    return {
        "available": True,
        "by_branch": by_branch.to_dict("records"),
        "by_location": by_location.to_dict("records"),
        "top_branch": by_branch.iloc[0]["branch"] if not by_branch.empty else None,
    }


def full_report(df, branch=None, date_from=None, date_to=None):
    """Aggregates the figures used across the dashboards into a single report payload,
    for the Reports page and its PDF export."""
    stats = summarize(df)
    day_stats = day_of_week_stats(df)
    tiers = membership_tiers(df)

    scope_bits = [branch or "All branches"]
    if date_from or date_to:
        scope_bits.append(f"{date_from or 'earliest'} to {date_to or 'latest'}")
    scope = " · ".join(scope_bits)

    return {
        "scope": scope,
        "row_count": int(len(df)),
        "summary": stats,
        "day_stats": day_stats,
        "tiers": tiers,
        "products": product_report(df),
        "inventory": inventory_report(df),
        "membership": membership_report(df),
        "regional": regional_report(df),
    }
