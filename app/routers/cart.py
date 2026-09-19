import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from app import models
from app.core.deps import get_db, get_current_user

router = APIRouter(prefix="/cart", tags=["cart"])


class CartIn(BaseModel):
    items: dict[int, int]


class CartOut(BaseModel):
    items: dict[int, int]


@router.get("", response_model=CartOut)
async def get_cart(
    db: AsyncSession = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    row = await db.scalar(
        select(models.Cart).where(models.Cart.user_id == user.id)
    )
    return {"items": json.loads(row.items) if row else {}}


@router.put("", response_model=CartOut)
async def save_cart(
    payload: CartIn,
    db: AsyncSession = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    items = {str(k): v for k, v in payload.items.items() if v > 0}
    row = await db.scalar(
        select(models.Cart).where(models.Cart.user_id == user.id)
    )
    if row:
        row.items = json.dumps(items)
    else:
        row = models.Cart(user_id=user.id, items=json.dumps(items))
        db.add(row)
    await db.commit()
    return {"items": items}


@router.delete("", status_code=204)
async def clear_cart(
    db: AsyncSession = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    row = await db.scalar(
        select(models.Cart).where(models.Cart.user_id == user.id)
    )
    if row:
        await db.delete(row)
        await db.commit()
