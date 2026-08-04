"""Logistic-regression based churn prediction: labels customers as
Churned/Active based on order recency (no completed order in the last
CHURN_WINDOW_DAYS), then trains a classifier on their order-history behavior
(frequency, spend, tenure) so churn risk can be scored for every customer."""
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score
from sqlalchemy import text

from schema import connection

CHURN_WINDOW_DAYS = 90
FEATURES = ["order_count", "total_spend", "avg_order_value", "tenure_days", "avg_days_between_orders"]


def customer_order_history():
    with connection() as conn:
        return pd.read_sql_query(
            text("""
            SELECT
                c.id AS customer_id, c.name AS customer,
                o.order_date AS order_date, o.total_amount AS total_amount
            FROM customers c
            JOIN orders o ON o.customer_id = c.id AND o.status = 'completed'
            ORDER BY c.id, o.order_date
            """),
            conn,
        )


def _build_features(history: pd.DataFrame, as_of):
    rows = []
    for cust_id, group in history.groupby("customer_id"):
        group = group.sort_values("order_date")
        dates = pd.to_datetime(group["order_date"])
        order_count = len(group)
        total_spend = group["total_amount"].sum()
        avg_order_value = group["total_amount"].mean()
        first_order, last_order = dates.min(), dates.max()
        tenure_days = max((last_order - first_order).days, 0)
        if order_count > 1:
            avg_gap = dates.diff().dropna().dt.days.mean()
        else:
            avg_gap = tenure_days  # single-order customers: no gap signal yet
        recency_days = (as_of - last_order).days

        rows.append({
            "customer_id": cust_id,
            "customer": group["customer"].iloc[0],
            "order_count": order_count,
            "total_spend": total_spend,
            "avg_order_value": avg_order_value,
            "tenure_days": tenure_days,
            "avg_days_between_orders": avg_gap,
            "recency_days": recency_days,
        })
    return pd.DataFrame(rows)


def run_churn_model():
    """Returns {"available": bool, "customers": DataFrame, "summary": DataFrame,
    "accuracy": float, "churned_count": int, "total_count": int}."""
    history = customer_order_history()
    if history.empty:
        return {"available": False}

    as_of = pd.to_datetime(history["order_date"]).max()
    features_df = _build_features(history, as_of)
    features_df["churned"] = (features_df["recency_days"] > CHURN_WINDOW_DAYS).astype(int)

    if features_df["churned"].nunique() < 2 or len(features_df) < 20:
        return {"available": False}

    X = features_df[FEATURES].fillna(0)
    y = features_df["churned"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=42, stratify=y
    )

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    model = LogisticRegression(max_iter=1000)
    model.fit(X_train_scaled, y_train)
    accuracy = round(accuracy_score(y_test, model.predict(X_test_scaled)) * 100, 1)

    X_all_scaled = scaler.transform(X)
    features_df["churn_probability"] = model.predict_proba(X_all_scaled)[:, 1]
    features_df["risk_level"] = pd.cut(
        features_df["churn_probability"],
        bins=[-0.01, 0.33, 0.66, 1.0],
        labels=["Low Risk", "Medium Risk", "High Risk"],
    )
    features_df["status"] = features_df["churned"].map({1: "Churned", 0: "Active"})

    summary = (
        features_df.groupby("risk_level", observed=True)
        .agg(customers=("customer_id", "count"), avg_spend=("total_spend", "mean"))
        .round(2)
        .reset_index()
    )

    return {
        "available": True,
        "accuracy": accuracy,
        "customers": features_df,
        "summary": summary,
        "churned_count": int(features_df["churned"].sum()),
        "total_count": len(features_df),
    }