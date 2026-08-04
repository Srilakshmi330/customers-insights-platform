"""One-time script: fills in sample city, gender, and age values for every
existing customer whose these fields are currently NULL (i.e., customers
created before the city/gender/age migration). Safe to re-run — it only
touches rows where city IS NULL, so it won't overwrite real data entered
later through the app.

Run with:
    python fill_customer_demographics.py
"""
import random

from sqlalchemy import text

from schema import connection

random.seed(7)

CITIES = [
    "New York", "Brooklyn", "Queens", "Manhattan", "Chicago", "Los Angeles",
    "Houston", "Phoenix", "San Diego", "Dallas", "Austin", "Seattle",
    "Denver", "Boston", "Atlanta", "Miami",
]
GENDERS = ["Male", "Female"]


def run():
    with connection() as conn:
        customer_ids = [
            row[0] for row in conn.execute(
                text("SELECT id FROM customers WHERE city IS NULL")
            ).fetchall()
        ]

        if not customer_ids:
            print("No customers need updating — every customer already has a city set.")
            return

        print(f"Filling demographics for {len(customer_ids)} customer(s)...")

        for cid in customer_ids:
            city = random.choice(CITIES)
            gender = random.choice(GENDERS)
            age = random.randint(18, 70)
            conn.execute(
                text("UPDATE customers SET city = :city, gender = :gender, age = :age WHERE id = :id"),
                {"city": city, "gender": gender, "age": age, "id": cid},
            )

        print(f"Done. Updated {len(customer_ids)} customer(s) with sample city/gender/age.")


if __name__ == "__main__":
    run()
