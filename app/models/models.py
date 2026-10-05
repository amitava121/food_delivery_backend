from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime, Text, Table, Enum
from sqlalchemy.orm import relationship
from app.db.base import Base
import enum

class UserRole(str, enum.Enum):
    customer = "customer"
    kitchen = "kitchen"
    admin = "admin"
    super_admin = "super_admin"

class OrderStatus(str, enum.Enum):
    pending = "pending"
    confirmed = "confirmed"
    preparing = "preparing"
    ready = "ready"
    out_for_delivery = "out_for_delivery"
    picked_up = "picked_up"
    delivered = "delivered"
    cancelled = "cancelled"

class FulfillmentType(str, enum.Enum):
    pickup = "pickup"
    delivery = "delivery"

class PaymentStatus(str, enum.Enum):
    pending = "pending"
    paid = "paid"
    failed = "failed"
    cash = "cash"

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    phone = Column(String, nullable=True)
    name = Column(String)
    hashed_password = Column(String)
    roles = Column(Text, default='["customer"]')
    is_active = Column(Boolean, default=True)
    firebase_uid = Column(String, unique=True, nullable=True, index=True)
    photo_url = Column(String, nullable=True)
    is_blocked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    restaurants = relationship("Restaurant", back_populates="owner")
    orders = relationship("Order", back_populates="customer")

class Restaurant(Base):
    __tablename__ = "restaurants"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    owner_id = Column(Integer, ForeignKey("users.id"))
    owner = relationship("User", back_populates="restaurants")
    locations = relationship("QRLocation", back_populates="restaurant")
    menu_items = relationship("MenuItem", back_populates="restaurant")
    orders = relationship("Order", back_populates="restaurant")

class QRLocation(Base):
    __tablename__ = "qr_locations"
    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"))
    label = Column(String)  # e.g. Booth 1 / Counter
    qr_code = Column(String, unique=True, index=True)
    is_active = Column(Boolean, default=True)
    restaurant = relationship("Restaurant", back_populates="locations")

class MenuCategory(Base):
    __tablename__ = "menu_categories"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    image_url = Column(String, nullable=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"))
    items = relationship("MenuItem", back_populates="category")

class MenuItem(Base):
    __tablename__ = "menu_items"
    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"))
    category_id = Column(Integer, ForeignKey("menu_categories.id"))
    name = Column(String)
    description = Column(Text, nullable=True)
    price = Column(Float)
    image_url = Column(String, nullable=True)
    is_veg = Column(Boolean, default=True)
    tag = Column(String, nullable=True)  # e.g. Bestseller, Must try
    offer_pct = Column(Integer, nullable=True)  # e.g. 20 => 20% off
    is_available = Column(Boolean, default=True)
    stock = Column(Integer, default=0)  # from inventory
    category = relationship("MenuCategory", back_populates="items")
    restaurant = relationship("Restaurant", back_populates="menu_items")

class OrderItem(Base):
    __tablename__ = "order_items"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    menu_item_id = Column(Integer, ForeignKey("menu_items.id"))
    item_name = Column(String, nullable=True)
    quantity = Column(Integer, default=1)
    unit_price = Column(Float)
    line_total = Column(Float, default=0.0)
    notes = Column(Text, nullable=True)
    order = relationship("Order", back_populates="items")

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    order_number = Column(String, unique=True, index=True)
    customer_id = Column(Integer, ForeignKey("users.id"))
    customer_name = Column(String, nullable=True)
    customer_phone = Column(String, nullable=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"))
    location_id = Column(Integer, ForeignKey("qr_locations.id"), nullable=True)
    fulfillment_type = Column(String, default="pickup")
    delivery_address = Column(Text, nullable=True)
    status = Column(Enum(OrderStatus), default=OrderStatus.pending)
    payment_status = Column(Enum(PaymentStatus), default=PaymentStatus.pending)
    subtotal = Column(Float, default=0.0)
    discount = Column(Float, default=0.0)
    total = Column(Float, default=0.0)
    notes = Column(Text, nullable=True)
    prep_time_minutes = Column(Integer, default=15)
    estimated_ready_at = Column(DateTime, nullable=True)
    idempotency_key = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    customer = relationship("User", back_populates="orders")
    restaurant = relationship("Restaurant", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", lazy="selectin")

class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    amount = Column(Float)
    method = Column(String)  # upi, card, wallet, cash
    status = Column(Enum(PaymentStatus), default=PaymentStatus.pending)
    transaction_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class InventoryLog(Base):
    __tablename__ = "inventory_logs"
    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"))
    menu_item_id = Column(Integer, ForeignKey("menu_items.id"))
    change = Column(Integer)  # positive or negative
    reason = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

class Cart(Base):
    __tablename__ = "carts"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True)
    items = Column(Text, default="{}")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Banner(Base):
    __tablename__ = "banners"
    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"))
    title = Column(String, nullable=False)
    subtitle = Column(String, nullable=True)
    cta_text = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    bg_color = Column(String, default="#f6e3b4")
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
