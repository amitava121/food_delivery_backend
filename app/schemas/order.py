from datetime import datetime
from pydantic import BaseModel

class OrderItemCreate(BaseModel):
    menu_item_id: int
    quantity: int = 1
    notes: str | None = None

class OrderCreate(BaseModel):
    restaurant_id: int
    location_id: int
    items: list[OrderItemCreate]
    notes: str | None = None

class OrderItemOut(BaseModel):
    id: int
    menu_item_id: int
    quantity: int
    unit_price: float
    notes: str | None
    class Config:
        from_attributes = True

class OrderOut(BaseModel):
    id: int
    order_number: str
    customer_id: int
    restaurant_id: int
    location_id: int
    status: str
    payment_status: str
    total: float
    notes: str | None
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemOut]
    class Config:
        from_attributes = True
