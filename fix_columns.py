from sqlalchemy import text
from schema import engine

with engine.connect() as conn:
    conn.execute(text("ALTER TABLE products ADD COLUMN IF NOT EXISTS store VARCHAR"))
    conn.execute(text("ALTER TABLE products ADD COLUMN IF NOT EXISTS warehouse VARCHAR"))
    conn.execute(text("ALTER TABLE products ADD COLUMN IF NOT EXISTS image_path VARCHAR"))
    conn.commit()

print("DONE - columns added")
