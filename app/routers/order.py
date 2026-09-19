import random, string
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app import models
from app.core.deps import get_db, get_current_user, user_roles
from app.schemas.order import OrderCreate, OrderOut

router = APIRouter(prefix="/orders", tags=["orders"])

def generate_order_number():
    return "ORD-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))

@router.post("/", response_model=OrderOut)
async def create_order(payload: OrderCreate, db: AsyncSession = Depends(get_db), user: models.User = Depends(get_current_user)):
    total = 0.0
    order = models.Order(
        order_number=generate_order_number(),
        customer_id=user.id,
        restaurant_id=payload.restaurant_id,
        location_id=payload.location_id,
        status=models.OrderStatus.pending,
        notes=payload.notes,
    )
    db.add(order)
    await db.flush()
    for i in payload.items:
        item = await db.get(models.MenuItem, i.menu_item_id)
        if not item or not item.is_available:
            raise HTTPException(status_code=400, detail=f"Menu item {i.menu_item_id} not available")
        if item.stock < i.quantity:
            raise HTTPException(status_code=400, detail=f"Insufficient stock for {item.name}")
        total += item.price * i.quantity
        db.add(models.OrderItem(
            order_id=order.id,
            menu_item_id=i.menu_item_id,
            quantity=i.quantity,
            unit_price=item.price,
            notes=i.notes,
        ))
        item.stock -= i.quantity
    order.total = total
    await db.commit()
    await db.refresh(order)
    return order

@router.get("/", response_model=list[OrderOut])
async def list_orders(db: AsyncSession = Depends(get_db), user: models.User = Depends(get_current_user)):
    q = select(models.Order)
    if not user_roles(user) & {"admin", "kitchen"}:
        q = q.where(models.Order.customer_id == user.id)
    return (await db.scalars(q.order_by(models.Order.created_at.desc()))).all()

@router.get("/{order_id}", response_model=OrderOut)
async def get_order(order_id: int, db: AsyncSession = Depends(get_db), user: models.User = Depends(get_current_user)):
    order = await db.get(models.Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order

@router.patch("/{order_id}/status")
async def update_status(order_id: int, status: str, db: AsyncSession = Depends(get_db), user: models.User = Depends(get_current_user)):
    order = await db.get(models.Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if status not in [e.value for e in models.OrderStatus]:
        raise HTTPException(status_code=400, detail="Invalid status")
    order.status = status
    await db.commit()
    return {"order_id": order.id, "status": order.status}
