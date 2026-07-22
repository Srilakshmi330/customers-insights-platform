"""
Merge the dunnhumby "Complete Journey" relational CSVs into one flat CSV that
matches Infinity Mart's Upload Dataset schema (see data.py: CORE_REQUIRED_COLUMNS).

Fields with no equivalent in the source data are filled per user decision:
  - gender: dunnhumby has no per-household gender field. Assigned randomly,
    but held constant per household_key so one household reads consistently.
  - customer_type: dunnhumby is entirely loyalty-card households, so the accurate
    label would be "Member" for every row -- but the app's Churn Prediction model
    requires two classes (Member/Normal) to train on. 25% of households are
    randomly relabeled "Normal" (held constant per household_key) purely to
    unlock that page; this split is fabricated, not a real segment.

sale_date is reconstructed from the relative `DAY` column (1-711) anchored to
an arbitrary epoch (2024-01-01) — it preserves real day-to-day ordering/spacing
from the source data, it's just not tied to real calendar dates.
"""
import numpy as np
import pandas as pd

SRC_DIR = r"C:\Users\potha\Downloads\dunnhumby_The-Complete-Journey\dunnhumby_The-Complete-Journey\dunnhumby_The-Complete-Journey CSV"
OUT_PATH = r"C:\Users\potha\OneDrive\Desktop\customers  insights platform\scratch\infinity_mart_upload.csv"

EPOCH = pd.Timestamp("2024-01-01")
RNG_SEED = 42

txn = pd.read_csv(
    f"{SRC_DIR}\\transaction_data.csv",
    usecols=["household_key", "BASKET_ID", "PRODUCT_ID", "DAY", "QUANTITY", "SALES_VALUE", "STORE_ID"],
)

product = pd.read_csv(
    f"{SRC_DIR}\\product.csv",
    usecols=["PRODUCT_ID", "COMMODITY_DESC", "SUB_COMMODITY_DESC"],
)

df = txn.merge(product, on="PRODUCT_ID", how="left")

df["branch"] = df["STORE_ID"].astype(str)
df["quantity"] = df["QUANTITY"]
df["unit_price"] = np.where(df["QUANTITY"] > 0, df["SALES_VALUE"] / df["QUANTITY"], df["SALES_VALUE"])
df["total_price"] = df["SALES_VALUE"]
df["product_category"] = df["COMMODITY_DESC"].fillna("Unknown")
df["product_name"] = df["SUB_COMMODITY_DESC"].fillna(df["product_category"])
df["sale_date"] = (EPOCH + pd.to_timedelta(df["DAY"] - 1, unit="D")).dt.date.astype(str)

# Real transaction id: dunnhumby's BASKET_ID groups the line items bought in one
# visit, so rows sharing a sale_id here are genuinely one transaction/basket.
df["sale_id"] = df["BASKET_ID"]

# No formal loyalty-points program exists in this dataset, so points are earned
# proportional to actual spend (1 point per dollar) -- gives the Rewards page
# real variance to build tiers from, instead of a flat 0 for every row.
df["reward_points"] = df["total_price"].clip(lower=0).round().astype(int)

rng = np.random.default_rng(RNG_SEED)
household_ids = df["household_key"].unique()
gender_by_household = pd.Series(
    rng.choice(["Male", "Female"], size=len(household_ids)),
    index=household_ids,
)
df["gender"] = df["household_key"].map(gender_by_household)

customer_type_by_household = pd.Series(
    rng.choice(["Member", "Normal"], size=len(household_ids), p=[0.75, 0.25]),
    index=household_ids,
)
df["customer_type"] = df["household_key"].map(customer_type_by_household)

out_cols = [
    "sale_id", "branch", "customer_type", "gender", "unit_price", "quantity",
    "product_category", "product_name", "total_price", "reward_points", "sale_date",
]
out = df[out_cols]
out.to_csv(OUT_PATH, index=False)

size_mb = round(__import__("os").path.getsize(OUT_PATH) / (1024 * 1024), 1)
print(f"Wrote {len(out):,} rows to {OUT_PATH} ({size_mb} MB)")
