from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app import models
from app.core.deps import get_db, get_current_user

router = APIRouter(prefix="/reports", tags=["reports"])

@router.get("/dashboard")
async def dashboard(db: AsyncSession = Depends(get_db), user: models.User = Depends(get_current_user)):
    total_sales = await db.scalar(select(func.sum(models.Order.total)).where(models.Order.payment_status == models.PaymentStatus.paid)) or 0
    total_orders = await db.scalar(select(func.count()).select_from(models.Order))
    popular = (await db.execute(
        select(models.OrderItem.menu_item_id, func.sum(models.OrderItem.quantity).label("qty"))
        .group_by(models.OrderItem.menu_item_id)
        .order_by(func.sum(models.OrderItem.quantity).desc())
        .limit(5)
    )).all()
    return {"total_sales": total_sales, "total_orders": total_orders, "popular_items": [{"menu_item_id": p[0], "qty": int(p[1])} for p in popular]}

@router.get("/sales")
async def sales(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(func.date(models.Order.created_at), func.sum(models.Order.total))
        .group_by(func.date(models.Order.created_at))
    )).all()
    return [{"date": str(r[0]), "total": float(r[1])} for r in rows]
