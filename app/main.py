from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.db.base import Base
from app.db.session import engine
from app import models
from app.routers import auth, menu, order, payment, qr, inventory, report, notification, upload, ws, banner, cart

from sqlalchemy import text

def _migrate_sqlite_columns(connection):
    if connection.dialect.name == "sqlite":
        cols_menu = {row[1] for row in connection.execute(text("PRAGMA table_info(menu_items)"))}
        for col, ddl in {
            "is_veg": "ALTER TABLE menu_items ADD COLUMN is_veg BOOLEAN DEFAULT 1",
            "tag": "ALTER TABLE menu_items ADD COLUMN tag VARCHAR",
            "offer_pct": "ALTER TABLE menu_items ADD COLUMN offer_pct INTEGER",
        }.items():
            if col not in cols_menu:
                connection.execute(text(ddl))

        cols_orders = {row[1] for row in connection.execute(text("PRAGMA table_info(orders)"))}
        for col, ddl in {
            "customer_name": "ALTER TABLE orders ADD COLUMN customer_name VARCHAR",
            "customer_phone": "ALTER TABLE orders ADD COLUMN customer_phone VARCHAR",
            "fulfillment_type": "ALTER TABLE orders ADD COLUMN fulfillment_type VARCHAR DEFAULT 'pickup'",
            "delivery_address": "ALTER TABLE orders ADD COLUMN delivery_address TEXT",
            "subtotal": "ALTER TABLE orders ADD COLUMN subtotal FLOAT DEFAULT 0.0",
            "discount": "ALTER TABLE orders ADD COLUMN discount FLOAT DEFAULT 0.0",
            "prep_time_minutes": "ALTER TABLE orders ADD COLUMN prep_time_minutes INTEGER DEFAULT 15",
            "estimated_ready_at": "ALTER TABLE orders ADD COLUMN estimated_ready_at DATETIME",
            "idempotency_key": "ALTER TABLE orders ADD COLUMN idempotency_key VARCHAR",
        }.items():
            if col not in cols_orders:
                connection.execute(text(ddl))

        cols_items = {row[1] for row in connection.execute(text("PRAGMA table_info(order_items)"))}
        for col, ddl in {
            "item_name": "ALTER TABLE order_items ADD COLUMN item_name VARCHAR",
            "line_total": "ALTER TABLE order_items ADD COLUMN line_total FLOAT DEFAULT 0.0",
        }.items():
            if col not in cols_items:
                connection.execute(text(ddl))

        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_customer_idempotency ON orders(customer_id, idempotency_key) WHERE idempotency_key IS NOT NULL"))

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate_sqlite_columns)
    yield
    await engine.dispose()

app = FastAPI(title="QR Fast Food Ordering System", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(menu.router)
app.include_router(order.router)
app.include_router(payment.router)
app.include_router(qr.router)
app.include_router(inventory.router)
app.include_router(report.router)
app.include_router(notification.router)
app.include_router(upload.router)
app.include_router(ws.router)
app.include_router(banner.router)
app.include_router(cart.router)

@app.get("/")
async def root():
    return {"message": "QR Fast Food Ordering API"}
