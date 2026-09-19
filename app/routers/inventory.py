from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app import models
from app.core.deps import get_db, get_current_user

router = APIRouter(prefix="/inventory", tags=["inventory"])

@router.get("/restaurants/{restaurant_id}")
async def list_inventory(restaurant_id: int, db: AsyncSession = Depends(get_db)):
    return (await db.scalars(select(models.MenuItem).where(models.MenuItem.restaurant_id == restaurant_id))).all()

@router.post("/restaurants/{restaurant_id}/adjust")
async def adjust_stock(restaurant_id: int, menu_item_id: int, change: int, reason: str, db: AsyncSession = Depends(get_db), user: models.User = Depends(get_current_user)):
    item = await db.scalar(select(models.MenuItem).where(models.MenuItem.id == menu_item_id, models.MenuItem.restaurant_id == restaurant_id))
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    item.stock += change
    db.add(models.InventoryLog(restaurant_id=restaurant_id, menu_item_id=menu_item_id, change=change, reason=reason))
    await db.commit()
    return item
