"""KMeans-based customer segmentation: groups customers into Premium/Regular/
Occasional/Inactive segments using order frequency, total spend, average
basket size, AND recency (days since last completed order). Recency is what
lets a real "Inactive" segment exist — customers with zero completed orders
(or none in a long time) previously never appeared in this query at all, so
there was no way to label anyone Inactive; now they're included with a large
recency value and naturally cluster together."""
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sqlalchemy import text

from schema import connection

SEGMENT_ORDER = ["Inactive", "Occasional", "Regular", "Premium"]
FEATURES = ["order_count", "total_spend", "avg_order_value", "days_since_last_order"]

# Customers with no completed order ever get this many "days since last order"
# so they land far out on the recency axis and separate cleanly from active
# shoppers during clustering, instead of being mistaken for recent buyers.
NEVER_ORDERED_RECENCY_DAYS = 9999


def customer_features():
    with connection() as conn:
        df = pd.read_sql_query(
            text("""
            SELECT
                c.id AS customer_id, c.name AS customer,
                COUNT(DISTINCT o.id) FILTER (WHERE o.status = 'completed') AS order_count,
                COALESCE(SUM(o.total_amount) FILTER (WHERE o.status = 'completed'), 0) AS total_spend,
                COALESCE(AVG(o.total_amount) FILTER (WHERE o.status = 'completed'), 0) AS avg_order_value,
                MAX(o.order_date) FILTER (WHERE o.status = 'completed') AS last_order_date
            FROM customers c
            LEFT JOIN orders o ON o.customer_id = c.id
            GROUP BY c.id, c.name
            """),
            conn,
        )

    now = pd.Timestamp.now()
    last_order = pd.to_datetime(df["last_order_date"])
    df["days_since_last_order"] = last_order.apply(
        lambda d: (now - d).days if pd.notna(d) else NEVER_ORDERED_RECENCY_DAYS
    )
    df["order_count"] = df["order_count"].fillna(0).astype(int)
    df["total_spend"] = df["total_spend"].fillna(0.0)
    df["avg_order_value"] = df["avg_order_value"].fillna(0.0)
    return df


def _label_clusters(working):
    """Assigns Inactive/Occasional/Regular/Premium to cluster ids based on
    each cluster's average behavior, rather than trusting KMeans' arbitrary
    cluster numbering. "Inactive" is decided by recency, not order count —
    a customer who has ordered many times but not recently is still inactive
    right now, and in datasets with no true zero-order customers, recency is
    the only reliable inactivity signal (order count alone can pick an
    unrelated low-frequency-but-recent cluster instead). The cluster with the
    highest average days-since-last-order becomes Inactive; the remaining
    clusters are ranked purely by average spend."""
    cluster_stats = working.groupby("cluster").agg(
        avg_recency=("days_since_last_order", "mean"),
        avg_spend=("total_spend", "mean"),
    )

    inactive_cluster = cluster_stats["avg_recency"].idxmax()
    remaining = cluster_stats.drop(index=inactive_cluster).sort_values("avg_spend")

    label_map = {inactive_cluster: "Inactive"}
    remaining_labels = ["Occasional", "Regular", "Premium"]
    for label, cluster_id in zip(remaining_labels, remaining.index):
        label_map[cluster_id] = label
    # If fewer than 4 clusters ended up distinct (small dataset edge case),
    # anything unmapped falls back to "Regular" rather than crashing.
    return {cid: label_map.get(cid, "Regular") for cid in cluster_stats.index}


def run_segmentation(n_clusters=4):
    """Returns {"available": bool, "customers": DataFrame, "summary": DataFrame}.
    customers has one row per segmented customer with an assigned "segment"
    column (Inactive/Occasional/Regular/Premium); summary aggregates
    count/avg spend/avg orders per segment, ordered Inactive -> Premium."""
    df = customer_features()
    if len(df) < n_clusters:
        return {"available": False, "customers": pd.DataFrame(), "summary": pd.DataFrame()}

    working = df.copy()
    scaler = StandardScaler()
    scaled = scaler.fit_transform(working[FEATURES])

    model = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    working["cluster"] = model.fit_predict(scaled)

    label_map = _label_clusters(working)
    working["segment"] = working["cluster"].map(label_map)
    working["segment"] = pd.Categorical(working["segment"], categories=SEGMENT_ORDER, ordered=True)

    summary = (
        working.groupby("segment", observed=True)
        .agg(
            customers=("customer_id", "count"),
            avg_spend=("total_spend", "mean"),
            avg_orders=("order_count", "mean"),
            avg_days_since_last_order=("days_since_last_order", "mean"),
        )
        .round(2)
        .reset_index()
        .sort_values("segment")
    )

    return {"available": True, "customers": working, "summary": summary}
