from datetime import datetime
from pydantic import BaseModel, Field

class OrderItemCreate(BaseModel):
    menu_item_id: int
    quantity: int = Field(default=1, ge=1)
    notes: str | None = None

class OrderCreate(BaseModel):
    restaurant_id: int
    location_id: int | None = None
    fulfillment_type: str = "pickup"
    customer_name: str | None = None
    customer_phone: str | None = None
    delivery_address: str | None = None
    notes: str | None = None
    items: list[OrderItemCreate]
    idempotency_key: str | None = None

class OrderItemOut(BaseModel):
    id: int
    menu_item_id: int
    item_name: str | None = None
    quantity: int
    unit_price: float
    line_total: float = 0.0
    notes: str | None = None

    class Config:
        from_attributes = True

class OrderOut(BaseModel):
    id: int
    order_number: str
    customer_id: int
    customer_name: str | None = None
    customer_phone: str | None = None
    restaurant_id: int
    location_id: int | None = None
    fulfillment_type: str = "pickup"
    delivery_address: str | None = None
    status: str
    payment_status: str
    subtotal: float = 0.0
    discount: float = 0.0
    total: float
    notes: str | None = None
    prep_time_minutes: int = 15
    estimated_ready_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemOut] = []

    class Config:
        from_attributes = True
