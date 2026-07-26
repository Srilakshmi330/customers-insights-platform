from sqlalchemy import text
from schema import engine

with engine.connect() as conn:
    conn.execute(text("ALTER TABLE forecast_results ADD COLUMN IF NOT EXISTS predicted_quantity FLOAT"))
    conn.commit()

print("DONE - predicted_quantity column added")
