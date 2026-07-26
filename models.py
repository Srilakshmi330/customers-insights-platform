from datetime import datetime, timedelta

from sqlalchemy import (
    CheckConstraint, Column, DateTime, Float, ForeignKey, Integer, String, Text, func,
)
from sqlalchemy.orm import joinedload, relationship
from werkzeug.security import check_password_hash, generate_password_hash

from schema import Base, init_schema, session_scope

FAILED_ATTEMPT_LIMIT = 5
LOCKOUT_MINUTES = 5


def init_db():
    init_schema()


def seed_default_users():
    """Creates the three starter accounts the plan calls for: Manager, Analyst,
    and Vendor (the latter linked to a seeded demo vendor record) — only if
    they don't already exist."""
    with session_scope() as session:
        vendor = session.query(Vendor).filter_by(name="Demo Vendor").first()
        if not vendor:
            vendor = Vendor(name="Demo Vendor", contact_email="vendor@example.com", status="active")
            session.add(vendor)
            session.flush()

        defaults = [
            ("manager", "manager123", "manager", None),
            ("analyst", "analyst123", "analyst", None),
            ("vendor", "vendor123", "vendor", vendor.id),
        ]
        for username, password, role, vendor_id in defaults:
            exists = session.query(User).filter_by(username=username).first()
            if not exists:
                session.add(User(
                    username=username, password_hash=generate_password_hash(password),
                    role=role, vendor_id=vendor_id,
                ))


class Vendor(Base):
    __tablename__ = "vendors"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    contact_email = Column(String)
    phone = Column(String)
    status = Column(String, nullable=False, default="active")
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (CheckConstraint("status IN ('active','inactive')", name="ck_vendor_status"),)

    users = relationship("User", back_populates="vendor")
    products = relationship("Product", back_populates="vendor")
    order_items = relationship("OrderItem", back_populates="vendor")

    @staticmethod
    def list_all():
        with session_scope() as session:
            return session.query(Vendor).order_by(Vendor.name).all()

    @staticmethod
    def get_by_id(vendor_id):
        with session_scope() as session:
            return session.get(Vendor, vendor_id)

    @staticmethod
    def create(name, contact_email, phone):
        name = name.strip()
        if not name:
            return None, "Vendor name is required."
        with session_scope() as session:
            if session.query(Vendor).filter_by(name=name).first():
                return None, "A vendor with that name already exists."
            vendor = Vendor(name=name, contact_email=contact_email or None, phone=phone or None, status="active")
            session.add(vendor)
            session.flush()
            session.refresh(vendor)
        return vendor, None

    @staticmethod
    def update(vendor_id, name, contact_email, phone, status):
        with session_scope() as session:
            vendor = session.get(Vendor, vendor_id)
            if vendor:
                vendor.name = name
                vendor.contact_email = contact_email or None
                vendor.phone = phone or None
                vendor.status = status

    @staticmethod
    def delete(vendor_id):
        with session_scope() as session:
            vendor = session.get(Vendor, vendor_id)
            if vendor:
                session.delete(vendor)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False)
    vendor_id = Column(Integer, ForeignKey("vendors.id"), index=True)
    failed_attempts = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (CheckConstraint("role IN ('manager','analyst','vendor')", name="ck_user_role"),)

    vendor = relationship("Vendor", back_populates="users")

    @staticmethod
    def get_by_id(user_id):
        with session_scope() as session:
            return session.get(User, user_id)

    @staticmethod
    def get_by_username(username):
        with session_scope() as session:
            return session.query(User).filter_by(username=username).first()

    @staticmethod
    def list_all():
        with session_scope() as session:
            return session.query(User).order_by(User.role, User.username).all()

    @staticmethod
    def create(username, password, role, vendor_id):
        """Returns (user_or_none, error_or_none)."""
        username = username.strip()
        if not username or not password:
            return None, "Username and password are required."
        if len(password) < 6:
            return None, "Password must be at least 6 characters."
        if role == "vendor" and not vendor_id:
            return None, "A vendor account must be linked to a vendor."
        with session_scope() as session:
            if session.query(User).filter_by(username=username).first():
                return None, "That username is already taken."
            user = User(
                username=username, password_hash=generate_password_hash(password),
                role=role, vendor_id=vendor_id if role == "vendor" else None,
            )
            session.add(user)
            session.flush()
            session.refresh(user)
        return user, None

    @staticmethod
    def set_role_vendor(user_id, role, vendor_id):
        with session_scope() as session:
            user = session.get(User, user_id)
            if user:
                user.role = role
                user.vendor_id = vendor_id if role == "vendor" else None

    @staticmethod
    def set_password(user_id, new_password):
        with session_scope() as session:
            user = session.get(User, user_id)
            if user:
                user.password_hash = generate_password_hash(new_password)

    @staticmethod
    def delete(user_id):
        with session_scope() as session:
            user = session.get(User, user_id)
            if user:
                session.delete(user)

    @staticmethod
    def is_locked(user):
        if not user.locked_until:
            return False
        return user.locked_until > datetime.now()

    @staticmethod
    def register_failed_login(username):
        with session_scope() as session:
            user = session.query(User).filter_by(username=username).first()
            if not user:
                return
            attempts = user.failed_attempts + 1
            if attempts >= FAILED_ATTEMPT_LIMIT:
                user.locked_until = datetime.now() + timedelta(minutes=LOCKOUT_MINUTES)
                attempts = 0
            user.failed_attempts = attempts

    @staticmethod
    def register_successful_login(username):
        with session_scope() as session:
            user = session.query(User).filter_by(username=username).first()
            if user:
                user.failed_attempts = 0
                user.locked_until = None

    @staticmethod
    def check_password(user, password):
        return check_password_hash(user.password_hash, password)


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    description = Column(Text)

    products = relationship("Product", back_populates="category")

    @staticmethod
    def list_all():
        with session_scope() as session:
            return session.query(Category).order_by(Category.name).all()

    @staticmethod
    def get_or_create(name):
        name = name.strip()
        with session_scope() as session:
            category = session.query(Category).filter_by(name=name).first()
            if not category:
                category = Category(name=name)
                session.add(category)
                session.flush()
            session.refresh(category)
        return category


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=False, index=True)
    category_id = Column(Integer, ForeignKey("categories.id"), index=True)
    name = Column(String, nullable=False)
    sku = Column(String)
    unit_price = Column(Float, nullable=False)
    description = Column(Text)
    store = Column(String)
    warehouse = Column(String)
    image_path = Column(String)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    vendor = relationship("Vendor", back_populates="products")
    category = relationship("Category", back_populates="products")
    inventory = relationship("Inventory", back_populates="product", uselist=False)
    order_items = relationship("OrderItem", back_populates="product")
    reviews = relationship("Review", back_populates="product")
    activity = relationship("CustomerActivity", back_populates="product")
    recommendations = relationship("Recommendation", back_populates="product")
    movements = relationship("InventoryMovement", back_populates="product")

    @staticmethod
    def list_for_vendor(vendor_id):
        with session_scope() as session:
            products = (
                session.query(Product)
                .options(joinedload(Product.category), joinedload(Product.inventory))
                .filter(Product.vendor_id == vendor_id)
                .order_by(Product.name)
                .all()
            )
            return [
                {
                    "id": p.id, "vendor_id": p.vendor_id, "category_id": p.category_id,
                    "name": p.name, "sku": p.sku, "unit_price": p.unit_price,
                    "description": p.description, "created_at": p.created_at,
                    "store": p.store, "warehouse": p.warehouse, "image_path": p.image_path,
                    "category_name": p.category.name if p.category else None,
                    "stock_quantity": p.inventory.stock_quantity if p.inventory else None,
                    "reorder_level": p.inventory.reorder_level if p.inventory else None,
                }
                for p in products
            ]

    @staticmethod
    def list_all_active():
        """Products across every active vendor, for building orders from a single screen."""
        with session_scope() as session:
            products = (
                session.query(Product)
                .join(Vendor, Vendor.id == Product.vendor_id)
                .options(joinedload(Product.vendor), joinedload(Product.inventory))
                .filter(Vendor.status == "active")
                .order_by(Vendor.name, Product.name)
                .all()
            )
            return [
                {
                    "id": p.id, "name": p.name, "unit_price": p.unit_price,
                    "vendor": p.vendor.name,
                    "stock_quantity": p.inventory.stock_quantity if p.inventory else 0,
                }
                for p in products
            ]

    @staticmethod
    def create(vendor_id, name, category_id, sku, unit_price, description, initial_stock,
               reorder_level, store=None, warehouse=None):
        name = name.strip()
        if not name or unit_price is None:
            return None, "Product name and unit price are required."
        if unit_price < 0:
            return None, "Unit price cannot be negative."
        with session_scope() as session:
            product = Product(
                vendor_id=vendor_id, category_id=category_id, name=name,
                sku=sku or None, unit_price=unit_price, description=description or None,
                store=store or None, warehouse=warehouse or None,
            )
            session.add(product)
            session.flush()
            initial_stock = initial_stock or 0
            session.add(Inventory(
                product_id=product.id, stock_quantity=initial_stock,
                reorder_level=reorder_level or 10,
            ))
            if initial_stock > 0:
                session.add(InventoryMovement(
                    product_id=product.id, vendor_id=vendor_id, movement_type="in",
                    quantity=initial_stock, reason="initial_stock",
                ))
            product_id = product.id
        return product_id, None

    @staticmethod
    def update(product_id, name, category_id, sku, unit_price, description, store=None, warehouse=None):
        with session_scope() as session:
            product = session.get(Product, product_id)
            if product:
                product.name = name
                product.category_id = category_id
                product.sku = sku or None
                product.unit_price = unit_price
                product.description = description or None
                product.store = store or None
                product.warehouse = warehouse or None

    @staticmethod
    def update_price(product_id, unit_price):
        with session_scope() as session:
            product = session.get(Product, product_id)
            if product:
                product.unit_price = unit_price

    @staticmethod
    def update_image(product_id, image_path):
        with session_scope() as session:
            product = session.get(Product, product_id)
            if product:
                product.image_path = image_path

    @staticmethod
    def delete(product_id):
        with session_scope() as session:
            session.query(OrderItem).filter_by(product_id=product_id).delete()
            session.query(Recommendation).filter_by(product_id=product_id).delete()
            session.query(CustomerActivity).filter_by(product_id=product_id).delete()
            session.query(Review).filter_by(product_id=product_id).delete()
            session.query(InventoryMovement).filter_by(product_id=product_id).delete()
            session.query(Inventory).filter_by(product_id=product_id).delete()
            session.query(Product).filter_by(id=product_id).delete()


class Inventory(Base):
    __tablename__ = "inventory"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, unique=True, index=True)
    stock_quantity = Column(Integer, nullable=False, default=0)
    reorder_level = Column(Integer, nullable=False, default=10)
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    product = relationship("Product", back_populates="inventory")

    @staticmethod
    def update_stock(product_id, stock_quantity, reorder_level):
        """Kept for backward compatibility — sets stock directly without logging
        a movement. Prefer adjust_stock() for any user-facing stock change so it
        shows up in Inventory Monitoring."""
        with session_scope() as session:
            inventory = session.query(Inventory).filter_by(product_id=product_id).first()
            if inventory:
                inventory.stock_quantity = stock_quantity
                inventory.reorder_level = reorder_level
                inventory.updated_at = datetime.now()

    @staticmethod
    def adjust_stock(product_id, vendor_id, new_stock_quantity, new_reorder_level, reason="adjustment"):
        """Sets stock to an explicit new value and logs the difference as an
        inventory movement (in if it went up, out if it went down) so Inventory
        Monitoring has a real stock-in/stock-out ledger to report on."""
        with session_scope() as session:
            inventory = session.query(Inventory).filter_by(product_id=product_id).first()
            if not inventory:
                return
            old_quantity = inventory.stock_quantity
            delta = new_stock_quantity - old_quantity
            inventory.stock_quantity = new_stock_quantity
            inventory.reorder_level = new_reorder_level
            inventory.updated_at = datetime.now()
            if delta > 0:
                session.add(InventoryMovement(
                    product_id=product_id, vendor_id=vendor_id, movement_type="in",
                    quantity=delta, reason=reason,
                ))
            elif delta < 0:
                session.add(InventoryMovement(
                    product_id=product_id, vendor_id=vendor_id, movement_type="out",
                    quantity=abs(delta), reason=reason,
                ))


class InventoryMovement(Base):
    """A ledger of every stock change: sales (out), restocks/manual increases (in),
    manual decreases/write-offs (out), and bulk-import adjustments. Current Stock
    Levels live on Inventory; this table is what powers Stock In / Stock Out /
    Inventory Turnover / Monthly Usage in Inventory Monitoring."""
    __tablename__ = "inventory_movements"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=False, index=True)
    movement_type = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    reason = Column(String)
    occurred_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (CheckConstraint("movement_type IN ('in','out')", name="ck_movement_type"),)

    product = relationship("Product", back_populates="movements")
    vendor = relationship("Vendor")

    @staticmethod
    def record(product_id, vendor_id, movement_type, quantity, reason, occurred_at=None):
        if quantity <= 0:
            return
        with session_scope() as session:
            session.add(InventoryMovement(
                product_id=product_id, vendor_id=vendor_id, movement_type=movement_type,
                quantity=quantity, reason=reason, occurred_at=occurred_at or datetime.now(),
            ))

    @staticmethod
    def summary_for_vendor(vendor_id, days=30):
        """Returns stock in/out totals for the trailing window, plus a rough
        inventory turnover estimate (units sold / average current stock)."""
        since = datetime.now() - timedelta(days=days)
        with session_scope() as session:
            stock_in = (
                session.query(func.coalesce(func.sum(InventoryMovement.quantity), 0))
                .filter(
                    InventoryMovement.vendor_id == vendor_id,
                    InventoryMovement.movement_type == "in",
                    InventoryMovement.occurred_at >= since,
                )
                .scalar()
            )
            stock_out = (
                session.query(func.coalesce(func.sum(InventoryMovement.quantity), 0))
                .filter(
                    InventoryMovement.vendor_id == vendor_id,
                    InventoryMovement.movement_type == "out",
                    InventoryMovement.occurred_at >= since,
                )
                .scalar()
            )
            units_sold = (
                session.query(func.coalesce(func.sum(InventoryMovement.quantity), 0))
                .filter(
                    InventoryMovement.vendor_id == vendor_id,
                    InventoryMovement.movement_type == "out",
                    InventoryMovement.reason == "sale",
                    InventoryMovement.occurred_at >= since,
                )
                .scalar()
            )
            current_total_stock = (
                session.query(func.coalesce(func.sum(Inventory.stock_quantity), 0))
                .join(Product, Product.id == Inventory.product_id)
                .filter(Product.vendor_id == vendor_id)
                .scalar()
            )

        avg_inventory = current_total_stock if current_total_stock > 0 else 1
        turnover = round(units_sold / avg_inventory, 2)

        return {
            "stock_in": int(stock_in),
            "stock_out": int(stock_out),
            "units_sold": int(units_sold),
            "current_total_stock": int(current_total_stock),
            "turnover": turnover,
            "days": days,
        }

    @staticmethod
    def list_for_vendor(vendor_id, days=90):
        since = datetime.now() - timedelta(days=days)
        with session_scope() as session:
            rows = (
                session.query(InventoryMovement)
                .options(joinedload(InventoryMovement.product))
                .filter(InventoryMovement.vendor_id == vendor_id, InventoryMovement.occurred_at >= since)
                .order_by(InventoryMovement.occurred_at.desc())
                .all()
            )
            return [
                {
                    "occurred_at": m.occurred_at, "movement_type": m.movement_type,
                    "quantity": m.quantity, "reason": m.reason,
                    "product": m.product.name if m.product else "—",
                }
                for m in rows
            ]

    @staticmethod
    def monthly_usage_for_vendor(vendor_id, months=6):
        """Units sold (stock-out, reason='sale') grouped by calendar month, for
        the Monthly Usage chart."""
        since = datetime.now() - timedelta(days=months * 31)
        with session_scope() as session:
            rows = (
                session.query(
                    func.to_char(InventoryMovement.occurred_at, "YYYY-MM").label("month"),
                    func.sum(InventoryMovement.quantity).label("units"),
                )
                .filter(
                    InventoryMovement.vendor_id == vendor_id,
                    InventoryMovement.movement_type == "out",
                    InventoryMovement.reason == "sale",
                    InventoryMovement.occurred_at >= since,
                )
                .group_by("month")
                .order_by("month")
                .all()
            )
            return [{"month": r.month, "units_sold": int(r.units)} for r in rows]


class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True)
    phone = Column(String)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    orders = relationship("Order", back_populates="customer")
    reviews = relationship("Review", back_populates="customer")
    activity = relationship("CustomerActivity", back_populates="customer")
    recommendations = relationship("Recommendation", back_populates="customer")

    @staticmethod
    def list_all():
        with session_scope() as session:
            return session.query(Customer).order_by(Customer.name).all()

    @staticmethod
    def create(name, email=None, phone=None):
        """Returns (customer_or_none, error_or_none)."""
        name = name.strip()
        if not name:
            return None, "Customer name is required."
        with session_scope() as session:
            if email:
                existing = session.query(Customer).filter_by(email=email).first()
                if existing:
                    return None, f"A customer with email {email} already exists ({existing.name})."
            customer = Customer(name=name, email=email or None, phone=phone or None)
            session.add(customer)
            session.flush()
            session.refresh(customer)
        return customer, None


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    order_date = Column(DateTime, nullable=False, server_default=func.now())
    status = Column(String, nullable=False, default="pending")
    total_amount = Column(Float, nullable=False, default=0)

    __table_args__ = (CheckConstraint("status IN ('pending','completed','cancelled')", name="ck_order_status"),)

    customer = relationship("Customer", back_populates="orders")
    items = relationship("OrderItem", back_populates="order")
    payments = relationship("Payment", back_populates="order")

    @staticmethod
    def list_all():
        with session_scope() as session:
            orders = (
                session.query(Order)
                .options(joinedload(Order.customer))
                .order_by(Order.order_date.desc())
                .all()
            )
            return [
                {
                    "id": o.id, "order_date": o.order_date, "status": o.status,
                    "total_amount": o.total_amount, "customer": o.customer.name,
                }
                for o in orders
            ]

    @staticmethod
    def create_with_items(customer_id, items, payment_method="cash"):
        """items: list of {"product_id": int, "quantity": int}.
        Validates stock availability before writing anything, then creates the
        order, its line items, a paid payment record, decrements inventory, logs
        an inventory-out movement (reason='sale') per item so Inventory Monitoring
        can report Stock Out / Turnover / Monthly Usage, and logs a cart_add
        activity per item so downstream analytics have data to show.
        Returns (order_id_or_none, error_or_none)."""
        if not items:
            return None, "Add at least one product line."

        with session_scope() as session:
            resolved = []
            total = 0.0
            for item in items:
                product = (
                    session.query(Product)
                    .options(joinedload(Product.inventory))
                    .filter(Product.id == item["product_id"])
                    .first()
                )
                if not product:
                    return None, "One of the selected products no longer exists."
                qty = int(item["quantity"])
                if qty <= 0:
                    return None, "Quantity must be greater than zero."
                available = product.inventory.stock_quantity if product.inventory else 0
                if qty > available:
                    return None, f"Only {available} unit(s) of '{product.name}' in stock."
                line_total = round(product.unit_price * qty, 2)
                total += line_total
                resolved.append((product, qty, line_total))

            total = round(total, 2)
            order = Order(customer_id=customer_id, status="completed", total_amount=total)
            session.add(order)
            session.flush()

            for product, qty, line_total in resolved:
                session.add(OrderItem(
                    order_id=order.id, product_id=product.id, vendor_id=product.vendor_id,
                    quantity=qty, unit_price=product.unit_price, total_price=line_total,
                ))
                product.inventory.stock_quantity -= qty
                product.inventory.updated_at = datetime.now()
                session.add(InventoryMovement(
                    product_id=product.id, vendor_id=product.vendor_id, movement_type="out",
                    quantity=qty, reason="sale",
                ))
                session.add(CustomerActivity(
                    customer_id=customer_id, product_id=product.id, activity_type="cart_add",
                ))

            session.add(Payment(
                order_id=order.id, amount=total, method=payment_method,
                status="paid", paid_at=datetime.now(),
            ))
            order_id = order.id

        return order_id, None


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=False, index=True)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Float, nullable=False)
    total_price = Column(Float, nullable=False)

    order = relationship("Order", back_populates="items")
    product = relationship("Product", back_populates="order_items")
    vendor = relationship("Vendor", back_populates="order_items")


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    method = Column(String)
    status = Column(String, nullable=False, default="pending")
    paid_at = Column(DateTime)

    __table_args__ = (CheckConstraint("status IN ('pending','paid','failed','refunded')", name="ck_payment_status"),)

    order = relationship("Order", back_populates="payments")


class Review(Base):
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    rating = Column(Integer, nullable=False)
    comment = Column(Text)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (CheckConstraint("rating BETWEEN 1 AND 5", name="ck_review_rating"),)

    product = relationship("Product", back_populates="reviews")
    customer = relationship("Customer", back_populates="reviews")

    @staticmethod
    def create(product_id, customer_id, rating, comment):
        if rating is None or not (1 <= int(rating) <= 5):
            return None, "Rating must be between 1 and 5."
        with session_scope() as session:
            review = Review(
                product_id=product_id, customer_id=customer_id,
                rating=int(rating), comment=comment or None,
            )
            session.add(review)
            session.flush()
            review_id = review.id
        return review_id, None

    @staticmethod
    def list_for_vendor(vendor_id):
        with session_scope() as session:
            reviews = (
                session.query(Review)
                .join(Product, Product.id == Review.product_id)
                .options(joinedload(Review.product), joinedload(Review.customer))
                .filter(Product.vendor_id == vendor_id)
                .order_by(Review.created_at.desc())
                .all()
            )
            return [
                {
                    "id": r.id, "rating": r.rating, "comment": r.comment, "created_at": r.created_at,
                    "product": r.product.name, "customer": r.customer.name,
                }
                for r in reviews
            ]

    @staticmethod
    def list_all():
        with session_scope() as session:
            reviews = (
                session.query(Review)
                .options(
                    joinedload(Review.product).joinedload(Product.vendor),
                    joinedload(Review.customer),
                )
                .order_by(Review.created_at.desc())
                .all()
            )
            return [
                {
                    "id": r.id, "rating": r.rating, "comment": r.comment, "created_at": r.created_at,
                    "product": r.product.name, "vendor": r.product.vendor.name, "customer": r.customer.name,
                }
                for r in reviews
            ]


class CustomerActivity(Base):
    __tablename__ = "customer_activity"

    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), index=True)
    activity_type = Column(String, nullable=False)
    occurred_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("activity_type IN ('view','search','cart_add','wishlist')", name="ck_activity_type"),
    )

    customer = relationship("Customer", back_populates="activity")
    product = relationship("Product", back_populates="activity")

    @staticmethod
    def list_for_vendor(vendor_id):
        with session_scope() as session:
            rows = (
                session.query(CustomerActivity)
                .join(Product, Product.id == CustomerActivity.product_id)
                .options(joinedload(CustomerActivity.product), joinedload(CustomerActivity.customer))
                .filter(Product.vendor_id == vendor_id)
                .order_by(CustomerActivity.occurred_at.desc())
                .all()
            )
            return [
                {
                    "activity_type": a.activity_type, "occurred_at": a.occurred_at,
                    "product": a.product.name, "customer": a.customer.name,
                }
                for a in rows
            ]


class Recommendation(Base):
    __tablename__ = "recommendations"

    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    score = Column(Float)
    reason = Column(Text)
    generated_at = Column(DateTime, nullable=False, server_default=func.now())

    customer = relationship("Customer", back_populates="recommendations")
    product = relationship("Product", back_populates="recommendations")

    @staticmethod
    def generate_for_vendor(vendor_id, top_n=5):
        """Popularity-based recommender: for every customer who has bought from this
        vendor, recommend the vendor's best-selling products they haven't bought yet.
        Replaces any previously generated recommendations for this vendor's products.
        Returns the number of recommendation rows written."""
        with session_scope() as session:
            bestsellers = (
                session.query(
                    Product.id.label("product_id"), Product.name,
                    func.sum(OrderItem.quantity).label("units_sold"),
                )
                .join(OrderItem, OrderItem.product_id == Product.id)
                .filter(OrderItem.vendor_id == vendor_id)
                .group_by(Product.id, Product.name)
                .order_by(func.sum(OrderItem.quantity).desc())
                .limit(top_n)
                .all()
            )
            if not bestsellers:
                return 0

            customer_ids = [
                row[0] for row in (
                    session.query(Order.customer_id)
                    .join(OrderItem, OrderItem.order_id == Order.id)
                    .filter(OrderItem.vendor_id == vendor_id)
                    .distinct()
                    .all()
                )
            ]

            vendor_product_ids = [p.id for p in session.query(Product.id).filter_by(vendor_id=vendor_id).all()]
            session.query(Recommendation).filter(Recommendation.product_id.in_(vendor_product_ids)).delete(
                synchronize_session=False
            )

            written = 0
            for customer_id in customer_ids:
                already_bought = {
                    row[0] for row in (
                        session.query(OrderItem.product_id)
                        .join(Order, Order.id == OrderItem.order_id)
                        .filter(Order.customer_id == customer_id, OrderItem.vendor_id == vendor_id)
                        .distinct()
                        .all()
                    )
                }
                for rank, product in enumerate(bestsellers):
                    if product.product_id in already_bought:
                        continue
                    score = round(1.0 - (rank / max(top_n, 1)) * 0.5, 3)
                    session.add(Recommendation(
                        customer_id=customer_id, product_id=product.product_id, score=score,
                        reason=f"Best seller ({int(product.units_sold)} sold)",
                    ))
                    written += 1
        return written

    @staticmethod
    def list_for_vendor(vendor_id):
        with session_scope() as session:
            recs = (
                session.query(Recommendation)
                .join(Product, Product.id == Recommendation.product_id)
                .options(joinedload(Recommendation.product), joinedload(Recommendation.customer))
                .filter(Product.vendor_id == vendor_id)
                .order_by(Recommendation.generated_at.desc())
                .all()
            )
            return [
                {
                    "generated_at": r.generated_at, "customer": r.customer.name,
                    "product": r.product.name, "score": r.score, "reason": r.reason,
                }
                for r in recs
            ]


class ForecastResult(Base):
    __tablename__ = "forecast_results"

    id = Column(Integer, primary_key=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), index=True)
    forecast_date = Column(DateTime, nullable=False)
    predicted_revenue = Column(Float)
    predicted_quantity = Column(Float)
    model_used = Column(String)
    generated_at = Column(DateTime, nullable=False, server_default=func.now())

    @staticmethod
    def record_batch(vendor_id, product_id, forecast_rows, model_used):
        """forecast_rows: list of {"date": datetime, "predicted_quantity": float,
        "predicted_revenue": float}. Stores one row per forecasted day so past
        forecasts stay auditable (what did we predict, and when)."""
        with session_scope() as session:
            for row in forecast_rows:
                session.add(ForecastResult(
                    vendor_id=vendor_id, product_id=product_id,
                    forecast_date=row["date"], predicted_quantity=row["predicted_quantity"],
                    predicted_revenue=row.get("predicted_revenue"), model_used=model_used,
                ))

    @staticmethod
    def latest_batch_for_product(product_id):
        with session_scope() as session:
            rows = (
                session.query(ForecastResult)
                .filter(ForecastResult.product_id == product_id)
                .order_by(ForecastResult.generated_at.desc())
                .limit(60)
                .all()
            )
            return [
                {
                    "forecast_date": r.forecast_date, "predicted_quantity": r.predicted_quantity,
                    "predicted_revenue": r.predicted_revenue, "model_used": r.model_used,
                    "generated_at": r.generated_at,
                }
                for r in rows
            ]


class Promotion(Base):
    """A vendor-declared promotional period for one product. Used as a real
    input feature ("Promotion") for Inventory Forecasting — both for training
    (was this past date under a promotion?) and for forecasting the future
    (is an upcoming date already scheduled for a promotion?)."""
    __tablename__ = "promotions"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=False, index=True)
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    discount_pct = Column(Float)
    description = Column(String)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (CheckConstraint("end_date >= start_date", name="ck_promotion_dates"),)

    @staticmethod
    def create(product_id, vendor_id, start_date, end_date, discount_pct, description):
        if end_date < start_date:
            return None, "End date must be on or after the start date."
        with session_scope() as session:
            promo = Promotion(
                product_id=product_id, vendor_id=vendor_id, start_date=start_date, end_date=end_date,
                discount_pct=discount_pct, description=description or None,
            )
            session.add(promo)
            session.flush()
            promo_id = promo.id
        return promo_id, None

    @staticmethod
    def list_for_vendor(vendor_id):
        with session_scope() as session:
            rows = (
                session.query(Promotion, Product.name)
                .join(Product, Product.id == Promotion.product_id)
                .filter(Promotion.vendor_id == vendor_id)
                .order_by(Promotion.start_date.desc())
                .all()
            )
            return [
                {
                    "id": p.id, "product_id": p.product_id, "product": name,
                    "start_date": p.start_date, "end_date": p.end_date,
                    "discount_pct": p.discount_pct, "description": p.description,
                }
                for p, name in rows
            ]

    @staticmethod
    def list_for_product(product_id):
        """All promotion date ranges for a product — used by the forecasting
        engine to build the is_promotion feature for both historical and
        future dates."""
        with session_scope() as session:
            rows = (
                session.query(Promotion)
                .filter(Promotion.product_id == product_id)
                .order_by(Promotion.start_date)
                .all()
            )
            return [{"start_date": p.start_date, "end_date": p.end_date} for p in rows]

    @staticmethod
    def delete(promotion_id):
        with session_scope() as session:
            promo = session.get(Promotion, promotion_id)
            if promo:
                session.delete(promo)
