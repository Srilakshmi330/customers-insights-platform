import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

SEGMENTATION_FEATURES = ["unit_price", "quantity", "total_price", "reward_points"]


def run_segmentation(df, n_clusters=3):
    """KMeans over per-transaction purchase behaviour (basket value, size, loyalty points)."""
    working = df.dropna(subset=SEGMENTATION_FEATURES).copy()
    if len(working) < n_clusters:
        return {"points": [], "summary": [], "available": False}

    scaler = StandardScaler()
    scaled = scaler.fit_transform(working[SEGMENTATION_FEATURES])

    model = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    working["cluster"] = model.fit_predict(scaled)

    cluster_means = working.groupby("cluster")["total_price"].mean().sort_values()
    rank_to_label = {}
    labels = ["Budget Shoppers", "Regular Shoppers", "High-Value Shoppers"]
    for rank, cluster_id in enumerate(cluster_means.index):
        rank_to_label[cluster_id] = labels[min(rank, len(labels) - 1)]
    working["segment"] = working["cluster"].map(rank_to_label)

    summary = (
        working.groupby("segment")
        .agg(
            customers=("cluster", "count"),
            avg_basket=("total_price", "mean"),
            avg_quantity=("quantity", "mean"),
            avg_reward_points=("reward_points", "mean"),
        )
        .round(2)
        .reset_index()
        .to_dict("records")
    )

    points = working[["quantity", "total_price", "segment"]].round(2).to_dict("records")

    return {"points": points, "summary": summary, "available": True}


def run_churn_risk_model(df):
    """
    Proxy 'churn' model: predicts the likelihood a purchase pattern resembles a
    Normal (non-member) shopper rather than a Member, using basket features.
    The dataset has no per-customer visit history, so this is a membership-risk
    proxy rather than true repeat-visit churn prediction.
    """
    working = df.dropna(subset=["customer_type", "unit_price", "quantity", "total_price", "reward_points", "tax", "branch"]).copy()
    if working["customer_type"].nunique() < 2 or len(working) < 20:
        return {"available": False}

    working["target_at_risk"] = (working["customer_type"] == "Normal").astype(int)
    feature_cols = ["unit_price", "quantity", "total_price", "reward_points", "tax"]
    branch_dummies = pd.get_dummies(working["branch"], prefix="branch")
    X = pd.concat([working[feature_cols], branch_dummies], axis=1)
    y = working["target_at_risk"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.3, random_state=42, stratify=y
    )

    model = LogisticRegression(max_iter=1000)
    model.fit(X_train, y_train)

    accuracy = round(model.score(X_test, y_test) * 100, 1)
    probabilities = model.predict_proba(X_test)[:, 1]

    sample = X_test.copy()
    sample["actual"] = y_test.values
    sample["risk_score"] = np.round(probabilities * 100, 1)
    sample = sample.join(working.loc[X_test.index, ["product_name", "branch", "customer_type"]])
    sample = sample.sort_values("risk_score", ascending=False).head(10)

    at_risk_count = int((probabilities >= 0.5).sum())

    top_risk = sample[["product_name", "branch", "customer_type", "risk_score"]].to_dict("records")

    return {
        "available": True,
        "accuracy": accuracy,
        "at_risk_count": at_risk_count,
        "evaluated_count": len(X_test),
        "top_risk": top_risk,
    }


def get_recommendations(df, branch=None, customer_type=None, gender=None):
    """Popularity-based recommendations for a chosen shopper segment."""
    segment = df.copy()
    if branch:
        segment = segment[segment["branch"] == branch]
    if customer_type:
        segment = segment[segment["customer_type"] == customer_type]
    if gender:
        segment = segment[segment["gender"] == gender]

    if segment.empty:
        return {"products": [], "categories": [], "segment_size": 0}

    top_products = (
        segment.groupby("product_name")["total_price"]
        .sum()
        .sort_values(ascending=False)
        .head(5)
        .round(2)
        .reset_index()
        .to_dict("records")
    )
    top_categories = (
        segment.groupby("product_category")["total_price"]
        .sum()
        .sort_values(ascending=False)
        .head(5)
        .round(2)
        .reset_index()
        .to_dict("records")
    )

    return {
        "products": top_products,
        "categories": top_categories,
        "segment_size": int(len(segment)),
    }


MIN_FORECAST_HISTORY_DAYS = 10


def forecast_revenue(df, periods=14):
    """Projects daily revenue forward using linear regression on the day-index trend.
    Simple by design (no seasonality) since this is meant as a directional forecast,
    not a production-grade time series model."""
    if df.empty or "sale_date" not in df.columns:
        return {"available": False}

    parsed = pd.to_datetime(df["sale_date"], errors="coerce")
    working = df.assign(_date=parsed.dt.date).dropna(subset=["_date"])
    daily = (
        working.groupby("_date")["total_price"]
        .sum()
        .round(2)
        .reset_index()
        .rename(columns={"_date": "date", "total_price": "revenue"})
        .sort_values("date")
    )
    if len(daily) < MIN_FORECAST_HISTORY_DAYS:
        return {"available": False}

    daily["day_index"] = range(len(daily))
    X = daily[["day_index"]]
    y = daily["revenue"]

    model = LinearRegression()
    model.fit(X, y)
    r2 = round(model.score(X, y), 3)

    last_date = pd.to_datetime(daily["date"].iloc[-1])
    last_index = int(daily["day_index"].iloc[-1])
    future_indices = pd.DataFrame({"day_index": range(last_index + 1, last_index + 1 + periods)})
    future_dates = [(last_date + pd.Timedelta(days=i)).date() for i in range(1, periods + 1)]
    predictions = np.clip(model.predict(future_indices), 0, None).round(2)

    trend = "growing" if model.coef_[0] > 0.5 else ("declining" if model.coef_[0] < -0.5 else "flat")

    return {
        "available": True,
        "history": daily[["date", "revenue"]].astype({"date": str}).to_dict("records"),
        "forecast": [
            {"date": str(d), "forecast_revenue": float(p)} for d, p in zip(future_dates, predictions)
        ],
        "daily_trend_change": round(float(model.coef_[0]), 2),
        "trend": trend,
        "r2": r2,
        "total_forecast_revenue": round(float(predictions.sum()), 2),
    }
