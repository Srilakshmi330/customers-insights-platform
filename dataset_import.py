"""Bulk-imports a transactions CSV directly into the Postgres schema, as an
alternative to building orders one at a time in Manage Orders. Column names
are matched flexibly (case/punctuation-insensitive aliases) so common export
formats work without renaming columns first."""
import re
from datetime import datetime

import pandas as pd

from models import Category, CustomerActivity, Inventory, InventoryMovement, OrderItem, Payment
from models import Customer as CustomerModel
from models import Order as OrderModel
from models import Product as ProductModel
from models import Vendor as VendorModel
from schema import session_scope

REQUIRED_COLUMNS = ["customer_name", "vendor_name", "product_name", "quantity", "unit_price"]

COLUMN_ALIASES = {
    "order_id": ["order_id", "order", "transaction_id", "invoice_id"],
    "customer_name": ["customer_name", "customer", "buyer", "buyer_name"],
    "customer_email": ["customer_email", "email"],
    "vendor_name": ["vendor_name", "vendor", "seller", "seller_name", "store"],
    "product_name": ["product_name", "product", "item", "item_name"],
    "category": ["category", "product_category", "product_line"],
    "unit_price": ["unit_price", "price"],
    "quantity": ["quantity", "qty"],
    "order_date": ["order_date", "date", "sale_date", "purchase_date"],
    "status": ["status", "order_status"],
    "payment_method": ["payment_method", "payment", "payment_type"],
}

VALID_STATUSES = {"pending", "completed", "cancelled"}

COLUMN_HELP = """
**Required columns** (flexible naming — e.g. `customer`, `buyer`, or `customer_name` all work):
- `customer_name`, `vendor_name`, `product_name`, `quantity`, `unit_price`

**Optional columns:**
- `order_id` — rows sharing the same value are grouped into one order (otherwise each row is its own order)
- `customer_email`, `category`, `order_date`, `status` (`pending`/`completed`/`cancelled`), `payment_method`

Unknown vendors/products/customers are created automatically.
"""


def _normalize(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def validate_csv(file_obj):
    """Returns (normalized_df, error_or_none)."""
    try:
        df = pd.read_csv(file_obj)
    except Exception as exc:
        return None, f"Could not read this file as CSV: {exc}"

    alias_lookup = {
        _normalize(alias): canonical
        for canonical, aliases in COLUMN_ALIASES.items()
        for alias in aliases
    }
    rename_map = {col: alias_lookup[_normalize(col)] for col in df.columns if _normalize(col) in alias_lookup}
    df = df.rename(columns=rename_map)

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        return None, (
            f"Missing required column(s): {', '.join(missing)}. "
            f"Found columns: {', '.join(df.columns)}"
        )

    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")
    df["unit_price"] = pd.to_numeric(df["unit_price"], errors="coerce")
    before = len(df)
    df = df.dropna(subset=["customer_name", "vendor_name", "product_name", "quantity", "unit_price"])
    dropped = before - len(df)
    if df.empty:
        return None, "No valid rows found after checking required fields."

    return df, (f"Skipped {dropped} row(s) missing required fields." if dropped else None)


def import_transactions(df):
    """Writes the validated dataframe into vendors/products/customers/orders.
    Also logs an inventory-out movement (reason='import') per line item so
    Inventory Monitoring's Stock Out / Turnover / Monthly Usage reflect bulk
    imports the same way they reflect manually-placed orders.
    Returns {"orders_created": int, "rows_processed": int, "errors": [...]}."""
    errors = []
    orders_created = 0
    rows_processed = 0

    with session_scope() as session:
        vendor_cache, category_cache, product_cache, customer_cache = {}, {}, {}, {}

        def get_vendor(name):
            if name not in vendor_cache:
                vendor = session.query(VendorModel).filter_by(name=name).first()
                if not vendor:
                    vendor = VendorModel(name=name, status="active")
                    session.add(vendor)
                    session.flush()
                vendor_cache[name] = vendor
            return vendor_cache[name]

        def get_category(name):
            if not name or pd.isna(name):
                return None
            name = str(name)
            if name not in category_cache:
                category_cache[name] = Category.get_or_create(name)
            return category_cache[name]

        def get_product(vendor, name, category, unit_price):
            key = (vendor.id, name)
            if key not in product_cache:
                product = session.query(ProductModel).filter_by(vendor_id=vendor.id, name=name).first()
                if not product:
                    product = ProductModel(
                        vendor_id=vendor.id, category_id=category.id if category else None,
                        name=name, unit_price=unit_price,
                    )
                    session.add(product)
                    session.flush()
                    session.add(Inventory(product_id=product.id, stock_quantity=1000, reorder_level=10))
                    session.flush()
                product_cache[key] = product
            return product_cache[key]

        def get_customer(name, email):
            key = (email or name)
            if key not in customer_cache:
                customer = None
                if email and not pd.isna(email):
                    customer = session.query(CustomerModel).filter_by(email=str(email)).first()
                if not customer:
                    customer = session.query(CustomerModel).filter_by(name=name).first()
                if not customer:
                    customer = CustomerModel(name=name, email=str(email) if email and not pd.isna(email) else None)
                    session.add(customer)
                    session.flush()
                customer_cache[key] = customer
            return customer_cache[key]

        if "order_id" in df.columns:
            groups = list(df.groupby("order_id"))
        else:
            groups = [(idx, row.to_frame().T) for idx, row in df.iterrows()]

        for group_key, group in groups:
            try:
                first = group.iloc[0]
                customer = get_customer(str(first["customer_name"]), first.get("customer_email"))

                order_date = pd.to_datetime(first.get("order_date"), errors="coerce")
                order_date = order_date.to_pydatetime() if pd.notna(order_date) else datetime.now()

                status = str(first.get("status") or "completed").strip().lower()
                if status not in VALID_STATUSES:
                    status = "completed"

                payment_method = str(first.get("payment_method") or "card")

                order = OrderModel(customer_id=customer.id, status=status, order_date=order_date, total_amount=0)
                session.add(order)
                session.flush()

                total = 0.0
                for _, row in group.iterrows():
                    vendor = get_vendor(str(row["vendor_name"]))
                    category = get_category(row.get("category"))
                    product = get_product(vendor, str(row["product_name"]), category, float(row["unit_price"]))
                    qty = int(row["quantity"])
                    line_total = round(float(row["unit_price"]) * qty, 2)
                    total += line_total

                    session.add(OrderItem(
                        order_id=order.id, product_id=product.id, vendor_id=vendor.id,
                        quantity=qty, unit_price=float(row["unit_price"]), total_price=line_total,
                    ))
                    if product.inventory:
                        product.inventory.stock_quantity = max(0, product.inventory.stock_quantity - qty)
                    session.add(InventoryMovement(
                        product_id=product.id, vendor_id=vendor.id, movement_type="out",
                        quantity=qty, reason="sale" if status == "completed" else "import",
                        occurred_at=order_date,
                    ))
                    session.add(CustomerActivity(
                        customer_id=customer.id, product_id=product.id,
                        activity_type="cart_add", occurred_at=order_date,
                    ))

                order.total_amount = round(total, 2)
                payment_status = (
                    "paid" if status == "completed"
                    else "pending" if status == "pending"
                    else "refunded"
                )
                session.add(Payment(
                    order_id=order.id, amount=order.total_amount, method=payment_method,
                    status=payment_status, paid_at=order_date if payment_status == "paid" else None,
                ))

                orders_created += 1
                rows_processed += len(group)
            except Exception as exc:
                errors.append({"group": str(group_key), "error": str(exc)})

    return {"orders_created": orders_created, "rows_processed": rows_processed, "errors": errors}