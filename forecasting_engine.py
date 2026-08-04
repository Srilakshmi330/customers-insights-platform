"""Inventory forecasting: predicts future daily unit demand for a product so
a vendor can see a suggested "Future Stock Requirement" (predicted demand
over the forecast horizon vs. current stock on hand).

Inputs used, per the plan (Previous Sales / Season / Month / Festival /
Promotion):
- Previous Sales   -> lag_7 / lag_30 rolling-average features
- Month            -> calendar month of each date
- Season           -> derived from month (Winter/Spring/Summer/Fall)
- Festival         -> a built-in calendar of major Indian festivals/holidays
                      (no manual data entry needed)
- Promotion        -> vendor-declared promotion date ranges (models.Promotion)

Algorithms, per the plan (Random Forest / XGBoost / Prophet):
- Random Forest and XGBoost are implemented directly.
- True Facebook Prophet needs a heavy C++/compiler toolchain (cmdstanpy) that
  is unreliable to install on Windows without extra setup. We substitute
  SARIMAX (statsmodels) as the third algorithm — it is pip-installable with
  no compiler dependency, and genuinely supports festival/promotion as
  exogenous regressors plus weekly seasonality, so it is a like-for-like
  swap in spirit, not a silent downgrade. This is clearly labeled in the UI.

No Streamlit dependency here — streamlit_app.py wraps calls with
st.cache_data for performance.
"""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error
from sqlalchemy import text
from xgboost import XGBRegressor
from statsmodels.tsa.statespace.sarimax import SARIMAX

from models import Promotion
from schema import connection

# Major Indian festivals/holidays, 2024-2027 — approximate/representative
# dates (lunar-calendar festivals shift year to year; these are close enough
# to give the model a meaningful "is this a festival period?" signal without
# requiring the vendor to enter anything). Extend this list as needed.
FESTIVAL_DATES = {
    # 2024
    "2024-01-14", "2024-01-26", "2024-03-08", "2024-03-25", "2024-04-09",
    "2024-08-15", "2024-08-19", "2024-08-26", "2024-09-07", "2024-10-02",
    "2024-10-12", "2024-10-31", "2024-11-01", "2024-11-15", "2024-12-25",
    # 2025
    "2025-01-14", "2025-01-26", "2025-03-14", "2025-04-06", "2025-08-09",
    "2025-08-15", "2025-08-16", "2025-09-05", "2025-10-02", "2025-10-02",
    "2025-10-20", "2025-10-21", "2025-11-05", "2025-12-25",
    # 2026
    "2026-01-14", "2026-01-26", "2026-03-04", "2026-03-26", "2026-08-15",
    "2026-08-28", "2026-08-26", "2026-09-25", "2026-10-02", "2026-10-09",
    "2026-10-10", "2026-11-24", "2026-12-25",
    # 2027
    "2027-01-14", "2027-01-26", "2027-02-21", "2027-03-15", "2027-08-15",
    "2027-08-17", "2027-09-14", "2027-10-02", "2027-10-29", "2027-10-30",
    "2027-12-14", "2027-12-25",
}


def is_festival_day(d):
    return pd.Timestamp(d).strftime("%Y-%m-%d") in FESTIVAL_DATES


def get_season(month):
    if month in (12, 1, 2):
        return "Winter"
    if month in (3, 4, 5):
        return "Spring"
    if month in (6, 7, 8):
        return "Summer"
    return "Fall"


def _daily_sales_series(product_id):
    """Full daily quantity-sold series for a product (completed orders),
    reindexed to include zero-sale days, from first sale to today."""
    with connection() as conn:
        df = pd.read_sql_query(
            text("""
                SELECT CAST(o.order_date AS DATE) AS day, SUM(oi.quantity) AS qty
                FROM order_items oi JOIN orders o ON o.id = oi.order_id
                WHERE oi.product_id = :pid AND o.status = 'completed'
                GROUP BY day ORDER BY day
            """),
            conn, params={"pid": product_id},
        )
    if df.empty:
        return pd.Series(dtype=float)

    df["day"] = pd.to_datetime(df["day"])
    full_range = pd.date_range(df["day"].min(), pd.Timestamp.now().normalize(), freq="D")
    series = df.set_index("day")["qty"].reindex(full_range, fill_value=0).astype(float)
    return series


def _is_promotion_day(d, promo_ranges):
    d = pd.Timestamp(d)
    for r in promo_ranges:
        if pd.Timestamp(r["start_date"]) <= d <= pd.Timestamp(r["end_date"]):
            return True
    return False


def _build_features(series, promo_ranges):
    """Turns a daily quantity series into a feature DataFrame: lag_7, lag_30,
    month, season, is_festival, is_promotion, with target = that day's qty.
    Lag features are shifted so a day's own sales never leak into its own
    features."""
    df = pd.DataFrame({"qty": series})
    df["lag_7"] = df["qty"].shift(1).rolling(7, min_periods=1).mean()
    df["lag_30"] = df["qty"].shift(1).rolling(30, min_periods=1).mean()
    df["month"] = df.index.month
    df["season"] = df["month"].map(get_season)
    df["is_festival"] = [1 if is_festival_day(d) else 0 for d in df.index]
    df["is_promotion"] = [1 if _is_promotion_day(d, promo_ranges) else 0 for d in df.index]
    df = df.dropna(subset=["lag_7", "lag_30"])
    return df


def _season_dummies(df, season_categories=("Winter", "Spring", "Summer", "Fall")):
    dummies = pd.get_dummies(df["season"])
    for cat in season_categories:
        if cat not in dummies.columns:
            dummies[cat] = 0
    return dummies[list(season_categories)]


def _train_tree_model(model_cls, df, model_kwargs=None):
    """Shared training + holdout evaluation for Random Forest and XGBoost,
    since they use the same feature set. Returns (fitted_model, mae)."""
    model_kwargs = model_kwargs or {}
    season_dummies = _season_dummies(df)
    X = pd.concat([df[["lag_7", "lag_30", "month", "is_festival", "is_promotion"]], season_dummies], axis=1)
    y = df["qty"]

    if len(df) < 14:
        model = model_cls(**model_kwargs)
        model.fit(X, y)
        return model, None

    split = int(len(df) * 0.85)
    X_train, X_test = X.iloc[:split], X.iloc[split:]
    y_train, y_test = y.iloc[:split], y.iloc[split:]

    holdout_model = model_cls(**model_kwargs)
    holdout_model.fit(X_train, y_train)
    preds = holdout_model.predict(X_test)
    mae = mean_absolute_error(y_test, preds) if len(y_test) else None

    final_model = model_cls(**model_kwargs)
    final_model.fit(X, y)
    return final_model, mae


def _recursive_forecast_tree(model, series, promo_ranges, horizon):
    """Random Forest / XGBoost don't natively predict multiple future steps —
    we predict one day at a time, feed that prediction back into the rolling
    history to compute the next day's lag features, and repeat."""
    history = list(series.values)
    last_date = series.index.max()
    results = []

    for step in range(1, horizon + 1):
        future_date = last_date + timedelta(days=step)
        lag_7 = float(np.mean(history[-7:])) if len(history) >= 1 else 0.0
        lag_30 = float(np.mean(history[-30:])) if len(history) >= 1 else 0.0
        month = future_date.month
        season = get_season(month)
        is_fest = 1 if is_festival_day(future_date) else 0
        is_promo = 1 if _is_promotion_day(future_date, promo_ranges) else 0

        row = {"lag_7": lag_7, "lag_30": lag_30, "month": month, "is_festival": is_fest, "is_promotion": is_promo}
        for cat in ("Winter", "Spring", "Summer", "Fall"):
            row[cat] = 1 if season == cat else 0
        X_future = pd.DataFrame([row])[["lag_7", "lag_30", "month", "is_festival", "is_promotion", "Winter", "Spring", "Summer", "Fall"]]

        pred = max(0.0, float(model.predict(X_future)[0]))
        history.append(pred)
        results.append({"date": future_date, "predicted_quantity": pred})

    return pd.DataFrame(results)


def _train_and_forecast_sarimax(series, promo_ranges, horizon):
    """SARIMAX with weekly seasonality and is_festival/is_promotion as
    exogenous regressors — the "Prophet-style" option (see module docstring
    for why real Prophet isn't used)."""
    exog_hist = pd.DataFrame({
        "is_festival": [1 if is_festival_day(d) else 0 for d in series.index],
        "is_promotion": [1 if _is_promotion_day(d, promo_ranges) else 0 for d in series.index],
    }, index=series.index)

    order = (1, 1, 1)
    seasonal_order = (1, 0, 1, 7) if len(series) >= 21 else (0, 0, 0, 0)

    model = SARIMAX(
        series, exog=exog_hist, order=order, seasonal_order=seasonal_order,
        enforce_stationarity=False, enforce_invertibility=False,
    )
    fit = model.fit(disp=False)

    mae = None
    if len(series) >= 21:
        split = int(len(series) * 0.85)
        train_series, test_series = series.iloc[:split], series.iloc[split:]
        train_exog, test_exog = exog_hist.iloc[:split], exog_hist.iloc[split:]
        if len(test_series) > 0:
            holdout_model = SARIMAX(
                train_series, exog=train_exog, order=order, seasonal_order=seasonal_order,
                enforce_stationarity=False, enforce_invertibility=False,
            )
            holdout_fit = holdout_model.fit(disp=False)
            preds = holdout_fit.forecast(steps=len(test_series), exog=test_exog)
            mae = mean_absolute_error(test_series, preds)

    last_date = series.index.max()
    future_dates = pd.date_range(last_date + timedelta(days=1), periods=horizon)
    future_exog = pd.DataFrame({
        "is_festival": [1 if is_festival_day(d) else 0 for d in future_dates],
        "is_promotion": [1 if _is_promotion_day(d, promo_ranges) else 0 for d in future_dates],
    }, index=future_dates)

    forecast_values = fit.forecast(steps=horizon, exog=future_exog)
    forecast_values = np.clip(forecast_values.values, 0, None)

    forecast_df = pd.DataFrame({"date": future_dates, "predicted_quantity": forecast_values})
    return forecast_df, mae


def forecast_product(product_id, algorithm, horizon_days=14, unit_price=None):
    """Main entry point. algorithm: 'Random Forest' | 'XGBoost' | 'Seasonal (SARIMAX)'.
    Returns {
        "available": bool, "history": DataFrame[date, qty], "forecast": DataFrame[date, predicted_quantity],
        "mae": float|None, "total_predicted_demand": float, "current_stock": None (caller fills in),
    } or {"available": False, "reason": str} if there isn't enough history yet.
    """
    series = _daily_sales_series(product_id)
    if series.empty or len(series) < 5:
        return {"available": False, "reason": "Not enough sales history yet for this product (need at least a few days of completed orders)."}

    promo_ranges = Promotion.list_for_product(product_id)

    if algorithm == "Random Forest":
        df = _build_features(series, promo_ranges)
        if df.empty:
            return {"available": False, "reason": "Not enough history yet after feature preparation."}
        model, mae = _train_tree_model(RandomForestRegressor, df, {"n_estimators": 200, "random_state": 42})
        forecast_df = _recursive_forecast_tree(model, series, promo_ranges, horizon_days)
    elif algorithm == "XGBoost":
        df = _build_features(series, promo_ranges)
        if df.empty:
            return {"available": False, "reason": "Not enough history yet after feature preparation."}
        model, mae = _train_tree_model(XGBRegressor, df, {"n_estimators": 200, "max_depth": 4, "random_state": 42, "verbosity": 0})
        forecast_df = _recursive_forecast_tree(model, series, promo_ranges, horizon_days)
    elif algorithm == "Seasonal (SARIMAX)":
        forecast_df, mae = _train_and_forecast_sarimax(series, promo_ranges, horizon_days)
    else:
        return {"available": False, "reason": f"Unknown algorithm: {algorithm}"}

    total_predicted_demand = float(forecast_df["predicted_quantity"].sum())
    if unit_price:
        forecast_df["predicted_revenue"] = forecast_df["predicted_quantity"] * unit_price

    history_df = series.reset_index()
    history_df.columns = ["date", "qty"]

    return {
        "available": True, "history": history_df, "forecast": forecast_df,
        "mae": mae, "total_predicted_demand": total_predicted_demand,
    }
