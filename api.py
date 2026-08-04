"""REST API for Infinity Mart (Phase 10 / Step 18).

A FastAPI layer over the same Postgres schema used by the Streamlit app
(models.py / schema.py) — every endpoint reads/writes the exact same tables,
so data created here shows up in the Streamlit UI and vice versa.

Run it with:
    python -m uvicorn api:app --reload --port 8000
(Use `python -m uvicorn`, not the bare `uvicorn` command — on this machine
the standalone .exe gets blocked by a Windows Application Control policy,
same as streamlit.exe and pip.exe did earlier.)

Then open http://127.0.0.1:8000/docs for interactive, click-to-try API
documentation (Swagger UI) — the fastest way to test every endpoint below
without needing Postman or writing curl commands by hand.

Auth:
- Vendor: POST /vendor/register then POST /vendor/login. Endpoints under
  /products, /product, /inventory, /sales, /forecast, /customers,
  /recommendation are scoped to that vendor.
- Manager/Analyst: POST /auth/login (works for any role, including vendor).
  Endpoints /vendors, /analytics, /compare-vendors, /churn, /segmentation,
  /reports/summary require a manager or analyst token (vendors get 403).
  Only managers can POST /vendors (create a vendor).

Click "Authorize" in /docs (or send `Authorization: Bearer <token>`) after
logging in to call any protected endpoint.
"""
import os
from datetime import datetime, timedelta
from typing import Optional

import jwt
import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import text

import churn
import forecasting_engine
import recommendation_engine
import report_builder
import segmentation
from models import Category, Inventory, Product, User, Vendor, init_db, seed_default_users
from schema import connection

JWT_SECRET = os.environ.get("API_JWT_SECRET", "dev-secret-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 12

app = FastAPI(
    title="Infinity Mart API",
    version="1.0.0",
    description=(
        "REST API for vendor operations: registration, login, products, inventory, "
        "sales, forecasting, customers, and recommendations."
    ),
)
security = HTTPBearer()


@app.on_event("startup")
def on_startup():
    init_db()
    seed_default_users()


def create_token(vendor_id: int, username: str) -> str:
    payload = {
        "vendor_id": vendor_id,
        "username": username,
        "role": "vendor",
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_token_for_role(username: str, role: str, vendor_id: Optional[int] = None) -> str:
    payload = {
        "username": username,
        "role": role,
        "vendor_id": vendor_id,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def get_current_vendor(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    token = credentials.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired — please log in again.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token.")
    return payload


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """Same token decoding as get_current_vendor, but for any role (manager/
    analyst/vendor) — used by the Manager/Analyst analytics endpoints below."""
    token = credentials.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired — please log in again.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token.")
    return payload


def require_role(*allowed_roles: str):
    """Dependency factory: raises 403 unless the token's role is one of
    allowed_roles. Usage: Depends(require_role("manager", "analyst"))."""
    def _check(current: dict = Depends(get_current_user)) -> dict:
        if current.get("role") not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"This endpoint requires one of these roles: {', '.join(allowed_roles)}.",
            )
        return current
    return _check


# ---------- Request/response schemas ----------

class VendorRegisterRequest(BaseModel):
    vendor_name: str
    contact_email: Optional[str] = None
    phone: Optional[str] = None
    username: str
    password: str = Field(min_length=6)


class VendorLoginRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class VendorCreateRequest(BaseModel):
    name: str
    contact_email: Optional[str] = None
    phone: Optional[str] = None


class ProductCreateRequest(BaseModel):
    name: str
    category: Optional[str] = None
    unit_price: float
    sku: Optional[str] = None
    description: Optional[str] = None
    initial_stock: int = 0
    reorder_level: int = 10
    store: Optional[str] = None
    warehouse: Optional[str] = None


class InventoryUpdateRequest(BaseModel):
    product_id: int
    stock_quantity: int
    reorder_level: int = 10


# ---------- Endpoints ----------

@app.get("/")
def root():
    return {"service": "Infinity Mart API", "status": "ok", "docs": "/docs"}


@app.post("/vendor/register", status_code=201)
def register_vendor(payload: VendorRegisterRequest):
    vendor, error = Vendor.create(payload.vendor_name, payload.contact_email, payload.phone)
    if error:
        raise HTTPException(status_code=400, detail=error)

    user, user_error = User.create(payload.username, payload.password, "vendor", vendor.id)
    if user_error:
        Vendor.delete(vendor.id)
        raise HTTPException(status_code=400, detail=user_error)

    return {"vendor_id": vendor.id, "username": user.username, "message": "Vendor registered successfully."}


@app.post("/vendor/login")
def login_vendor(payload: VendorLoginRequest):
    user = User.get_by_username(payload.username)
    if not user or user.role != "vendor":
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    if User.is_locked(user):
        raise HTTPException(status_code=423, detail="Account locked due to too many failed attempts. Try again later.")
    if not User.check_password(user, payload.password):
        User.register_failed_login(payload.username)
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    User.register_successful_login(payload.username)
    token = create_token(user.vendor_id, user.username)
    return {"access_token": token, "token_type": "bearer", "vendor_id": user.vendor_id}


@app.get("/products")
def list_products(current=Depends(get_current_vendor)):
    return Product.list_for_vendor(current["vendor_id"])


@app.post("/product", status_code=201)
def create_product(payload: ProductCreateRequest, current=Depends(get_current_vendor)):
    category = Category.get_or_create(payload.category) if payload.category else None
    product_id, error = Product.create(
        current["vendor_id"], payload.name, category.id if category else None,
        payload.sku, payload.unit_price, payload.description, payload.initial_stock,
        payload.reorder_level, store=payload.store, warehouse=payload.warehouse,
    )
    if error:
        raise HTTPException(status_code=400, detail=error)
    return {"product_id": product_id, "message": "Product created successfully."}


@app.put("/inventory")
def update_inventory(payload: InventoryUpdateRequest, current=Depends(get_current_vendor)):
    products = Product.list_for_vendor(current["vendor_id"])
    if not any(p["id"] == payload.product_id for p in products):
        raise HTTPException(status_code=404, detail="Product not found for this vendor.")

    Inventory.adjust_stock(
        payload.product_id, current["vendor_id"], payload.stock_quantity, payload.reorder_level,
        reason="api_update",
    )
    return {"message": "Inventory updated successfully."}


@app.get("/sales")
def get_sales(current=Depends(get_current_vendor)):
    with connection() as conn:
        row = conn.execute(
            text("""
                SELECT COALESCE(SUM(oi.total_price), 0) AS revenue,
                       COUNT(DISTINCT oi.order_id) AS orders,
                       COALESCE(SUM(oi.quantity), 0) AS units
                FROM order_items oi JOIN orders o ON o.id = oi.order_id
                WHERE oi.vendor_id = :vid AND o.status = 'completed'
            """),
            {"vid": current["vendor_id"]},
        ).first()
    return {"revenue": row.revenue, "orders": row.orders, "units_sold": int(row.units)}


@app.get("/forecast")
def get_forecast(
    product_id: int,
    algorithm: str = Query("Random Forest", description="Random Forest | XGBoost | Seasonal (SARIMAX)"),
    horizon_days: int = 14,
    current=Depends(get_current_vendor),
):
    products = Product.list_for_vendor(current["vendor_id"])
    product = next((p for p in products if p["id"] == product_id), None)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found for this vendor.")

    result = forecasting_engine.forecast_product(product_id, algorithm, horizon_days, product["unit_price"])
    if not result["available"]:
        raise HTTPException(status_code=400, detail=result["reason"])

    forecast_records = result["forecast"].to_dict("records")
    for r in forecast_records:
        if isinstance(r.get("date"), pd.Timestamp):
            r["date"] = r["date"].isoformat()

    return {
        "product_id": product_id, "algorithm": algorithm, "mae": result["mae"],
        "total_predicted_demand": result["total_predicted_demand"], "forecast": forecast_records,
    }


@app.get("/customers")
def get_customers(current=Depends(get_current_vendor)):
    with connection() as conn:
        rows = conn.execute(
            text("""
                SELECT DISTINCT c.id, c.name, c.email
                FROM customers c
                JOIN orders o ON o.customer_id = c.id
                JOIN order_items oi ON oi.order_id = o.id
                WHERE oi.vendor_id = :vid
            """),
            {"vid": current["vendor_id"]},
        ).mappings().all()
    return [dict(r) for r in rows]


@app.get("/recommendation")
def get_recommendation(customer_id: Optional[int] = None, current=Depends(get_current_vendor)):
    if customer_id:
        df = recommendation_engine.recommend_for_customer(customer_id, top_n=8, vendor_id=current["vendor_id"])
    else:
        df = recommendation_engine.trending_products(days=7, top_n=8, vendor_id=current["vendor_id"])
    return df.to_dict("records") if not df.empty else []


# ---------- Manager / Analyst endpoints ----------
# These use a generic login (any role) instead of /vendor/login, and are
# scoped to the whole platform rather than one vendor.

@app.post("/auth/login")
def login(payload: LoginRequest):
    """Login for Manager, Analyst, or Vendor accounts. Returns a token whose
    role determines which endpoints below are usable."""
    user = User.get_by_username(payload.username)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    if User.is_locked(user):
        raise HTTPException(status_code=423, detail="Account locked due to too many failed attempts. Try again later.")
    if not User.check_password(user, payload.password):
        User.register_failed_login(payload.username)
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    User.register_successful_login(payload.username)
    token = create_token_for_role(user.username, user.role, user.vendor_id)
    return {"access_token": token, "token_type": "bearer", "role": user.role, "vendor_id": user.vendor_id}


@app.get("/vendors")
def list_vendors(current=Depends(require_role("manager", "analyst"))):
    vendors = Vendor.list_all()
    return [
        {
            "id": v.id, "name": v.name, "contact_email": v.contact_email,
            "phone": v.phone, "status": v.status,
        }
        for v in vendors
    ]


@app.post("/vendors", status_code=201)
def create_vendor(payload: VendorCreateRequest, current=Depends(require_role("manager"))):
    vendor, error = Vendor.create(payload.name, payload.contact_email, payload.phone)
    if error:
        raise HTTPException(status_code=400, detail=error)
    return {"id": vendor.id, "name": vendor.name}


@app.get("/analytics")
def get_analytics(current=Depends(require_role("manager", "analyst"))):
    with connection() as conn:
        order_count = conn.execute(text("SELECT COUNT(*) FROM orders")).scalar()
        revenue = conn.execute(text("SELECT COALESCE(SUM(total_price), 0) FROM order_items")).scalar()
        vendor_count = conn.execute(text("SELECT COUNT(*) FROM vendors")).scalar()
        product_count = conn.execute(text("SELECT COUNT(*) FROM products")).scalar()
        by_vendor = conn.execute(
            text("""
                SELECT v.name AS vendor, SUM(oi.total_price) AS revenue
                FROM order_items oi JOIN vendors v ON v.id = oi.vendor_id
                GROUP BY v.name ORDER BY revenue DESC
            """)
        ).mappings().all()

    return {
        "total_revenue": revenue,
        "order_count": order_count,
        "vendor_count": vendor_count,
        "product_count": product_count,
        "revenue_by_vendor": [dict(r) for r in by_vendor],
    }


@app.get("/compare-vendors")
def compare_vendors(current=Depends(require_role("manager", "analyst"))):
    with connection() as conn:
        comparison = conn.execute(
            text("""
                SELECT
                    v.name AS vendor, v.status,
                    COUNT(DISTINCT p.id) AS products,
                    COALESCE(SUM(oi.total_price), 0) AS revenue,
                    COUNT(DISTINCT oi.order_id) AS orders
                FROM vendors v
                LEFT JOIN products p ON p.vendor_id = v.id
                LEFT JOIN order_items oi ON oi.vendor_id = v.id
                GROUP BY v.name, v.status
                ORDER BY revenue DESC, products DESC
            """)
        ).mappings().all()
    return [dict(r) for r in comparison]


@app.get("/churn")
def get_churn(current=Depends(require_role("manager", "analyst"))):
    result = churn.run_churn_model()
    if not result["available"]:
        raise HTTPException(status_code=404, detail="Not enough order history to run the churn model yet.")
    return {
        "accuracy": result["accuracy"],
        "churned_count": result["churned_count"],
        "total_count": result["total_count"],
        "customers": result["customers"].to_dict("records"),
        "summary": result["summary"].to_dict("records"),
    }


@app.get("/segmentation")
def get_segmentation(current=Depends(require_role("manager", "analyst"))):
    result = segmentation.run_segmentation()
    if not result["available"]:
        raise HTTPException(status_code=404, detail="Not enough completed-order history to segment customers yet.")
    return {
        "customers": result["customers"].to_dict("records"),
        "summary": result["summary"].to_dict("records"),
    }


@app.get("/reports/summary")
def reports_summary(current=Depends(require_role("manager", "analyst"))):
    with connection() as conn:
        top_vendors = conn.execute(
            text("""
                SELECT v.name AS vendor, COALESCE(SUM(oi.total_price), 0) AS revenue
                FROM vendors v LEFT JOIN order_items oi ON oi.vendor_id = v.id
                GROUP BY v.name ORDER BY revenue DESC LIMIT 10
            """)
        ).mappings().all()
        top_products = conn.execute(
            text("""
                SELECT p.name AS product, SUM(oi.total_price) AS revenue
                FROM order_items oi JOIN products p ON p.id = oi.product_id
                GROUP BY p.name ORDER BY revenue DESC LIMIT 10
            """)
        ).mappings().all()
        low_stock = conn.execute(
            text("""
                SELECT p.name AS name, v.name AS vendor, i.stock_quantity AS stock_quantity
                FROM inventory i
                JOIN products p ON p.id = i.product_id
                JOIN vendors v ON v.id = p.vendor_id
                WHERE i.stock_quantity <= i.reorder_level
                ORDER BY i.stock_quantity ASC LIMIT 20
            """)
        ).mappings().all()
        order_count = conn.execute(text("SELECT COUNT(*) FROM orders")).scalar()
        revenue = conn.execute(text("SELECT COALESCE(SUM(total_price), 0) FROM order_items")).scalar()
        vendor_count = conn.execute(text("SELECT COUNT(*) FROM vendors")).scalar()
        product_count = conn.execute(text("SELECT COUNT(*) FROM products")).scalar()
        customer_count = conn.execute(text("SELECT COUNT(*) FROM customers")).scalar()

    return {
        "total_revenue": revenue,
        "order_count": order_count,
        "vendor_count": vendor_count,
        "product_count": product_count,
        "customer_count": customer_count,
        "top_vendors": [dict(r) for r in top_vendors],
        "top_products": [dict(r) for r in top_products],
        "low_stock": [dict(r) for r in low_stock],
    }
