"""Populates infinity_mart with a realistic-sized sample dataset:
100 vendors, 1000 products, 500 customers, 20,000 orders (with matching
order_items/payments/activity), and 5000 reviews. Safe to re-run — it only
adds rows, it never deletes existing ones (run against an empty database
for the counts above to match exactly).
"""
import random
from datetime import datetime, timedelta

from faker import Faker
from sqlalchemy import insert, select

import models as m
from schema import Base, engine, init_schema

fake = Faker()

VENDOR_COUNT = 100
PRODUCT_COUNT = 1000
CUSTOMER_COUNT = 500
ORDER_COUNT = 20000
REVIEW_COUNT = 5000
ORDER_BATCH_SIZE = 1000

CATEGORY_NAMES = [
    "Electronics", "Grocery", "Clothing", "Home & Kitchen", "Beauty",
    "Toys & Games", "Sports & Outdoors", "Books", "Automotive", "Health & Wellness",
]

PRODUCT_NOUNS = [
    "Mouse", "Keyboard", "Blender", "Jacket", "Novel", "Sneakers", "Backpack",
    "Headphones", "Lamp", "Watch", "Water Bottle", "Notebook", "Sunglasses",
    "Speaker", "Charger Cable", "Yoga Mat", "Coffee Maker", "Desk Chair",
    "Board Game", "Skincare Set", "Wrench Set", "Vitamin Pack", "Tent",
    "Bicycle Helmet", "Air Fryer", "Wallet", "Perfume", "Puzzle",
    "Running Shoes", "Monitor", "Toaster", "Umbrella", "Duffel Bag",
]

ORDER_STATUS_WEIGHTS = [("completed", 0.80), ("pending", 0.12), ("cancelled", 0.08)]
PAYMENT_METHODS = ["cash", "card", "upi", "wallet"]
RATING_WEIGHTS = [(1, 0.05), (2, 0.10), (3, 0.20), (4, 0.30), (5, 0.35)]


def weighted_choice(pairs):
    values, weights = zip(*pairs)
    return random.choices(values, weights=weights, k=1)[0]


def chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def bulk_insert(table_name, rows, chunk_size=5000):
    if not rows:
        return
    table = Base.metadata.tables[table_name]
    with engine.begin() as conn:
        for chunk in chunked(rows, chunk_size):
            conn.execute(insert(table), chunk)


def get_all_ids(table_name):
    table = Base.metadata.tables[table_name]
    with engine.connect() as conn:
        return [row[0] for row in conn.execute(select(table.c.id))]


def main():
    print("Ensuring schema exists...")
    init_schema()
    m.seed_default_users()

    print(f"Seeding {len(CATEGORY_NAMES)} categories...")
    category_ids = [m.Category.get_or_create(name).id for name in CATEGORY_NAMES]

    print(f"Seeding {VENDOR_COUNT} vendors...")
    fake.unique.clear()
    vendor_rows = [
        {
            "name": fake.unique.company(),
            "contact_email": fake.unique.company_email(),
            "phone": fake.phone_number(),
            "status": "active" if random.random() > 0.05 else "inactive",
        }
        for _ in range(VENDOR_COUNT)
    ]
    bulk_insert("vendors", vendor_rows)
    vendor_ids = get_all_ids("vendors")

    print(f"Seeding {PRODUCT_COUNT} products + inventory...")
    product_rows = [
        {
            "vendor_id": random.choice(vendor_ids),
            "category_id": random.choice(category_ids),
            "name": f"{fake.word().capitalize()} {random.choice(PRODUCT_NOUNS)}",
            "sku": fake.bothify(text="SKU-####-??").upper(),
            "unit_price": round(random.uniform(2.5, 500), 2),
            "description": fake.sentence(),
        }
        for _ in range(PRODUCT_COUNT)
    ]
    bulk_insert("products", product_rows)

    with engine.connect() as conn:
        products_table = Base.metadata.tables["products"]
        product_catalog = [
            {"id": r.id, "vendor_id": r.vendor_id, "unit_price": r.unit_price}
            for r in conn.execute(select(products_table.c.id, products_table.c.vendor_id, products_table.c.unit_price))
        ]

    inventory_rows = [
        {
            "product_id": p["id"],
            "stock_quantity": random.randint(0, 300),
            "reorder_level": random.randint(5, 20),
        }
        for p in product_catalog
    ]
    bulk_insert("inventory", inventory_rows)

    print(f"Seeding {CUSTOMER_COUNT} customers...")
    fake.unique.clear()
    customer_rows = [
        {"name": fake.name(), "email": fake.unique.email(), "phone": fake.phone_number()}
        for _ in range(CUSTOMER_COUNT)
    ]
    bulk_insert("customers", customer_rows)
    customer_ids = get_all_ids("customers")

    print(f"Seeding {ORDER_COUNT} orders (with items/payments/activity)...")
    now = datetime.now()
    for batch_start in range(0, ORDER_COUNT, ORDER_BATCH_SIZE):
        batch_size = min(ORDER_BATCH_SIZE, ORDER_COUNT - batch_start)

        order_rows = []
        items_per_order = []
        for _ in range(batch_size):
            status = weighted_choice(ORDER_STATUS_WEIGHTS)
            order_date = now - timedelta(days=random.randint(0, 180), hours=random.randint(0, 23))
            chosen_products = random.sample(product_catalog, k=random.randint(1, 4))

            items, total = [], 0.0
            for product in chosen_products:
                qty = random.randint(1, 5)
                line_total = round(product["unit_price"] * qty, 2)
                total += line_total
                items.append({
                    "product_id": product["id"], "vendor_id": product["vendor_id"],
                    "quantity": qty, "unit_price": product["unit_price"], "total_price": line_total,
                })

            order_rows.append({
                "customer_id": random.choice(customer_ids), "order_date": order_date,
                "status": status, "total_amount": round(total, 2),
            })
            items_per_order.append(items)

        orders_table = Base.metadata.tables["orders"]
        with engine.begin() as conn:
            result = conn.execute(insert(orders_table).returning(orders_table.c.id), order_rows)
            order_ids = [row[0] for row in result]

            item_rows, payment_rows, activity_rows = [], [], []
            for order_id, order_row, items in zip(order_ids, order_rows, items_per_order):
                for item in items:
                    item_rows.append({**item, "order_id": order_id})
                    activity_rows.append({
                        "customer_id": order_row["customer_id"], "product_id": item["product_id"],
                        "activity_type": "cart_add", "occurred_at": order_row["order_date"],
                    })
                payment_status = (
                    "paid" if order_row["status"] == "completed"
                    else "pending" if order_row["status"] == "pending"
                    else random.choice(["failed", "refunded"])
                )
                payment_rows.append({
                    "order_id": order_id, "amount": order_row["total_amount"],
                    "method": random.choice(PAYMENT_METHODS), "status": payment_status,
                    "paid_at": order_row["order_date"] if payment_status == "paid" else None,
                })

            conn.execute(insert(Base.metadata.tables["order_items"]), item_rows)
            conn.execute(insert(Base.metadata.tables["payments"]), payment_rows)
            conn.execute(insert(Base.metadata.tables["customer_activity"]), activity_rows)

        print(f"  orders {batch_start + batch_size}/{ORDER_COUNT}")

    print("Seeding extra browsing activity (view/search/wishlist)...")
    extra_activity_rows = [
        {
            "customer_id": customer_id,
            "product_id": random.choice(product_catalog)["id"],
            "activity_type": random.choice(["view", "search", "wishlist"]),
            "occurred_at": now - timedelta(days=random.randint(0, 180)),
        }
        for customer_id in customer_ids
        for _ in range(random.randint(2, 6))
    ]
    bulk_insert("customer_activity", extra_activity_rows)

    print(f"Seeding {REVIEW_COUNT} reviews...")
    product_ids = [p["id"] for p in product_catalog]
    review_rows = [
        {
            "product_id": random.choice(product_ids),
            "customer_id": random.choice(customer_ids),
            "rating": weighted_choice(RATING_WEIGHTS),
            "comment": fake.sentence(),
            "created_at": now - timedelta(days=random.randint(0, 180)),
        }
        for _ in range(REVIEW_COUNT)
    ]
    bulk_insert("reviews", review_rows)

    print("Done.")


if __name__ == "__main__":
    main()
