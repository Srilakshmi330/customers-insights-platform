import pandas as pd
from faker import Faker
import os

# ---- CONFIG ----
input_path = os.path.expanduser("~/Downloads/supermarketsales_updated.csv")
output_path = os.path.expanduser("~/Downloads/supermarketsales_enhanced.csv")

fake = Faker()

# Load data
df = pd.read_csv(input_path)

print("Original columns:", list(df.columns))
print("Row count:", len(df))

# ---- 1. vendor_name: map each branch to a vendor name ----
unique_branches = df['branch'].unique()
branch_to_vendor = {branch: f"{branch} Store" for branch in unique_branches}
df['vendor_name'] = df['branch'].map(branch_to_vendor)

# ---- 2. customer_name: consistent fake name per customer_id ----
unique_customers = df['customer_id'].unique()
customer_to_name = {cid: fake.name() for cid in unique_customers}
df['customer_name'] = df['customer_id'].map(customer_to_name)

# Save
df.to_csv(output_path, index=False)

print("Done. New columns:", list(df.columns))
print(f"Saved to: {output_path}")
print(f"Unique vendors created: {len(unique_branches)}")
print(f"Unique customers named: {len(unique_customers)}")