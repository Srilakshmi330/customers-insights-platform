"""One-time migration: adds city, gender, age columns to the existing
`customers` table in Postgres. Safe to run more than once (uses
IF NOT EXISTS), so re-running it after it's already applied is a no-op.

Run with:
    python migrate_customer_fields.py
"""
from sqlalchemy import text

from schema import connection

STATEMENTS = [
    "ALTER TABLE customers ADD COLUMN IF NOT EXISTS city VARCHAR;",
    "ALTER TABLE customers ADD COLUMN IF NOT EXISTS gender VARCHAR;",
    "ALTER TABLE customers ADD COLUMN IF NOT EXISTS age INTEGER;",
]


def run_migration():
    with connection() as conn:
        for stmt in STATEMENTS:
            print(f"Running: {stmt}")
            conn.execute(text(stmt))
    print("Migration complete. customers table now has city, gender, age columns.")


if __name__ == "__main__":
    run_migration()
