import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app import models
from app.core.deps import get_db, get_current_user

router = APIRouter(prefix="/qr", tags=["qr"])

@router.post("/locations/{restaurant_id}")
async def create_location(restaurant_id: int, label: str, db: AsyncSession = Depends(get_db), user: models.User = Depends(get_current_user)):
    qr = models.QRLocation(
        restaurant_id=restaurant_id,
        label=label,
        qr_code=str(uuid.uuid4())[:8].upper(),
    )
    db.add(qr)
    await db.commit()
    await db.refresh(qr)
    return qr

@router.get("/locations/{qr_code}")
async def read_location(qr_code: str, db: AsyncSession = Depends(get_db)):
    loc = await db.scalar(select(models.QRLocation).where(models.QRLocation.qr_code == qr_code, models.QRLocation.is_active == True))
    if not loc:
        raise HTTPException(status_code=404, detail="Invalid QR code")
    return {"restaurant_id": loc.restaurant_id, "location_id": loc.id, "label": loc.label}
