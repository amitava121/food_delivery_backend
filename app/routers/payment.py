from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app import models
from app.core.deps import get_db, get_current_user
from app.schemas.payment import PaymentCreate, PaymentOut

router = APIRouter(prefix="/payments", tags=["payments"])

@router.post("/", response_model=PaymentOut)
async def create_payment(payload: PaymentCreate, db: AsyncSession = Depends(get_db), user: models.User = Depends(get_current_user)):
    order = await db.get(models.Order, payload.order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    payment = models.Payment(**payload.model_dump())
    db.add(payment)
    await db.flush()
    # simulate gateway result
    payment.status = models.PaymentStatus.paid if payload.method != "cash" else models.PaymentStatus.cash
    order.payment_status = payment.status
    await db.commit()
    await db.refresh(payment)
    return payment
