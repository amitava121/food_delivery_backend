from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app import models
from app.core.deps import get_db, get_current_user, require_role
from app.routers.upload import delete_r2_object
from app.routers.ws import menu_broadcaster
from app.schemas.menu import (
    MenuCategoryCreate, MenuCategoryOut, MenuCategoryUpdate,
    MenuItemCreate, MenuItemOut, MenuItemUpdate,
    RestaurantOut,
)

router = APIRouter(prefix="/menu", tags=["menu"])

manager = require_role(models.UserRole.admin)

@router.get("/restaurants", response_model=list[RestaurantOut])
async def list_restaurants(db: AsyncSession = Depends(get_db)):
    return (await db.scalars(select(models.Restaurant))).all()

@router.get("/restaurants/{restaurant_id}/categories", response_model=list[MenuCategoryOut])
async def list_categories(restaurant_id: int, db: AsyncSession = Depends(get_db)):
    return (await db.scalars(select(models.MenuCategory).where(models.MenuCategory.restaurant_id == restaurant_id))).all()

@router.post("/restaurants/{restaurant_id}/categories", response_model=MenuCategoryOut)
async def create_category(restaurant_id: int, payload: MenuCategoryCreate, db: AsyncSession = Depends(get_db), user: models.User = Depends(manager)):
    cat = models.MenuCategory(**payload.model_dump(), restaurant_id=restaurant_id)
    db.add(cat)
    await db.commit()
    await db.refresh(cat)
    await menu_broadcaster.notify()
    return cat

@router.patch("/categories/{category_id}", response_model=MenuCategoryOut)
async def update_category(category_id: int, payload: MenuCategoryUpdate, db: AsyncSession = Depends(get_db), user: models.User = Depends(manager)):
    cat = await db.get(models.MenuCategory, category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    updates = payload.model_dump(exclude_unset=True)
    old_image = cat.image_url
    for field, value in updates.items():
        setattr(cat, field, value)
    await db.commit()
    await db.refresh(cat)
    if "image_url" in updates and updates["image_url"] != old_image:
        await delete_r2_object(old_image)
    await menu_broadcaster.notify()
    return cat

@router.delete("/categories/{category_id}", status_code=204)
async def delete_category(category_id: int, db: AsyncSession = Depends(get_db), user: models.User = Depends(manager)):
    cat = await db.get(models.MenuCategory, category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    items = await db.scalar(select(func.count()).select_from(models.MenuItem).where(models.MenuItem.category_id == category_id))
    if items:
        raise HTTPException(status_code=400, detail="Category still has dishes — move or delete them first")
    image = cat.image_url
    await db.delete(cat)
    await db.commit()
    await delete_r2_object(image)
    await menu_broadcaster.notify()

@router.get("/restaurants/{restaurant_id}/items", response_model=list[MenuItemOut])
async def list_items(restaurant_id: int, include_unavailable: bool = False, db: AsyncSession = Depends(get_db)):
    q = select(models.MenuItem).where(models.MenuItem.restaurant_id == restaurant_id)
    if not include_unavailable:
        q = q.where(models.MenuItem.is_available == True)
    return (await db.scalars(q)).all()

@router.post("/restaurants/{restaurant_id}/items", response_model=MenuItemOut)
async def create_item(restaurant_id: int, payload: MenuItemCreate, db: AsyncSession = Depends(get_db), user: models.User = Depends(manager)):
    item = models.MenuItem(**payload.model_dump(), restaurant_id=restaurant_id)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    await menu_broadcaster.notify()
    return item

@router.patch("/items/{item_id}", response_model=MenuItemOut)
async def update_item(item_id: int, payload: MenuItemUpdate, db: AsyncSession = Depends(get_db), user: models.User = Depends(manager)):
    item = await db.get(models.MenuItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    updates = payload.model_dump(exclude_unset=True)
    old_image = item.image_url
    for field, value in updates.items():
        setattr(item, field, value)
    await db.commit()
    await db.refresh(item)
    if "image_url" in updates and updates["image_url"] != old_image:
        await delete_r2_object(old_image)
    await menu_broadcaster.notify()
    return item

@router.delete("/items/{item_id}", status_code=204)
async def delete_item(item_id: int, db: AsyncSession = Depends(get_db), user: models.User = Depends(manager)):
    item = await db.get(models.MenuItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    image = item.image_url
    await db.delete(item)
    await db.commit()
    await delete_r2_object(image)
    await menu_broadcaster.notify()
