from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app import models
from app.core.deps import get_db, require_role
from app.routers.upload import delete_r2_object
from app.routers.ws import menu_broadcaster
from app.schemas.banner import BannerCreate, BannerOut, BannerUpdate

router = APIRouter(prefix="/banners", tags=["banners"])

manager = require_role(models.UserRole.admin)


@router.get("/restaurants/{restaurant_id}", response_model=list[BannerOut])
async def list_banners(restaurant_id: int, include_inactive: bool = False, db: AsyncSession = Depends(get_db)):
    q = select(models.Banner).where(models.Banner.restaurant_id == restaurant_id)
    if not include_inactive:
        q = q.where(models.Banner.is_active == True)
    return (await db.scalars(q.order_by(models.Banner.sort_order, models.Banner.id))).all()


@router.post("/restaurants/{restaurant_id}", response_model=BannerOut)
async def create_banner(restaurant_id: int, payload: BannerCreate, db: AsyncSession = Depends(get_db), user: models.User = Depends(manager)):
    banner = models.Banner(**payload.model_dump(), restaurant_id=restaurant_id)
    db.add(banner)
    await db.commit()
    await db.refresh(banner)
    await menu_broadcaster.notify()
    return banner


@router.patch("/{banner_id}", response_model=BannerOut)
async def update_banner(banner_id: int, payload: BannerUpdate, db: AsyncSession = Depends(get_db), user: models.User = Depends(manager)):
    banner = await db.get(models.Banner, banner_id)
    if not banner:
        raise HTTPException(status_code=404, detail="Banner not found")
    updates = payload.model_dump(exclude_unset=True)
    old_image = banner.image_url
    for field, value in updates.items():
        setattr(banner, field, value)
    await db.commit()
    await db.refresh(banner)
    if "image_url" in updates and updates["image_url"] != old_image:
        await delete_r2_object(old_image)
    await menu_broadcaster.notify()
    return banner


@router.delete("/{banner_id}", status_code=204)
async def delete_banner(banner_id: int, db: AsyncSession = Depends(get_db), user: models.User = Depends(manager)):
    banner = await db.get(models.Banner, banner_id)
    if not banner:
        raise HTTPException(status_code=404, detail="Banner not found")
    image = banner.image_url
    await db.delete(banner)
    await db.commit()
    await delete_r2_object(image)
    await menu_broadcaster.notify()
