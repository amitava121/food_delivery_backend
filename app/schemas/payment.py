from pydantic import BaseModel

class PaymentCreate(BaseModel):
    order_id: int
    amount: float
    method: str
    transaction_id: str | None = None

class PaymentOut(BaseModel):
    id: int
    order_id: int
    amount: float
    method: str
    status: str
    transaction_id: str | None
    class Config:
        from_attributes = True
