"""KMeans-based customer segmentation: groups customers into Budget/Regular/
High-Value shopper segments using their completed-order history (order
frequency, total spend, average basket size)."""
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sqlalchemy import text

from schema import connection

SEGMENT_LABELS = ["Budget Shoppers", "Regular Shoppers", "High-Value Shoppers"]
FEATURES = ["order_count", "total_spend", "avg_order_value"]


def customer_features():
    with connection() as conn:
        return pd.read_sql_query(
            text("""
            SELECT
                c.id AS customer_id, c.name AS customer,
                COUNT(DISTINCT o.id) AS order_count,
                COALESCE(SUM(o.total_amount), 0) AS total_spend,
                COALESCE(AVG(o.total_amount), 0) AS avg_order_value
            FROM customers c
            JOIN orders o ON o.customer_id = c.id AND o.status = 'completed'
            GROUP BY c.id, c.name
            """),
            conn,
        )


def run_segmentation(n_clusters=3):
    """Returns {"available": bool, "customers": DataFrame, "summary": DataFrame}.
    customers has one row per segmented customer with an assigned "segment"
    column; summary aggregates count/avg spend/avg orders per segment."""
    df = customer_features()
    if len(df) < n_clusters:
        return {"available": False, "customers": pd.DataFrame(), "summary": pd.DataFrame()}

    working = df.copy()
    scaler = StandardScaler()
    scaled = scaler.fit_transform(working[FEATURES])

    model = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    working["cluster"] = model.fit_predict(scaled)

    # Rank clusters by average spend so labels are consistent (lowest spend =
    # Budget, highest = High-Value) regardless of KMeans' arbitrary cluster ids.
    cluster_rank = working.groupby("cluster")["total_spend"].mean().sort_values()
    label_map = {
        cluster_id: SEGMENT_LABELS[min(rank, len(SEGMENT_LABELS) - 1)]
        for rank, cluster_id in enumerate(cluster_rank.index)
    }
    working["segment"] = working["cluster"].map(label_map)

    summary = (
        working.groupby("segment")
        .agg(
            customers=("customer_id", "count"),
            avg_spend=("total_spend", "mean"),
            avg_orders=("order_count", "mean"),
        )
        .round(2)
        .reset_index()
        .sort_values("avg_spend")
    )

    return {"available": True, "customers": working, "summary": summary}
