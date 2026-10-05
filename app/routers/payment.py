from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app import models
from app.core.deps import get_db, get_current_user, is_admin
from app.schemas.payment import PaymentCreate, PaymentOut

router = APIRouter(prefix="/payments", tags=["payments"])

@router.post("/", response_model=PaymentOut)
async def create_payment(payload: PaymentCreate, db: AsyncSession = Depends(get_db), user: models.User = Depends(get_current_user)):
    order = await db.get(models.Order, payload.order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # BOLA protection: customer can only pay for their own order (admins may process payments)
    if not is_admin(user) and order.customer_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to pay for this order")

    # Authoritative pricing: backend authoritative order total is strictly enforced
    data = payload.model_dump()
    data["amount"] = float(order.total)

    payment = models.Payment(**data)
    db.add(payment)
    await db.flush()
    # simulate gateway result
    payment.status = models.PaymentStatus.paid if payload.method != "cash" else models.PaymentStatus.cash
    order.payment_status = payment.status
    await db.commit()
    await db.refresh(payment)
    return payment
