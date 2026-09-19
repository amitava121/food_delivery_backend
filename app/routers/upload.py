import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from app import models
from app.core.config import settings
from app.core.deps import require_role

router = APIRouter(prefix="/upload", tags=["upload"])

manager = require_role(models.UserRole.admin)

ALLOWED = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/avif"}


def is_r2_url(url: str | None) -> bool:
    return bool(url and settings.R2_PUBLIC_URL and url.startswith(settings.R2_PUBLIC_URL + "/"))


async def delete_r2_object(image_url: str | None) -> None:
    """Best-effort: remove the R2 object backing an image_url (skips non-R2/external URLs)."""
    if not is_r2_url(image_url) or not settings.R2_UPLOAD_URL or not settings.R2_UPLOAD_KEY:
        return
    key = image_url[len(settings.R2_PUBLIC_URL) + 1 :]
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            await client.delete(
                f"{settings.R2_UPLOAD_URL}/object",
                params={"key": key},
                headers={"x-upload-key": settings.R2_UPLOAD_KEY},
            )
    except Exception:
        pass

@router.post("/image")
async def upload_image(file: UploadFile = File(...), user: models.User = Depends(manager)):
    if file.content_type not in ALLOWED:
        raise HTTPException(status_code=415, detail="Unsupported image type")
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image too large (max 5 MB)")
    if not settings.R2_UPLOAD_URL or not settings.R2_UPLOAD_KEY:
        raise HTTPException(status_code=503, detail="Image upload not configured")
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{settings.R2_UPLOAD_URL}/upload",
            content=data,
            headers={"content-type": file.content_type, "x-upload-key": settings.R2_UPLOAD_KEY},
        )
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail="Image upload failed")
    return r.json()

@router.delete("/object", status_code=204)
async def delete_object(url: str, user: models.User = Depends(manager)):
    """Delete an R2 object by its public URL (e.g. an upload that was never saved)."""
    if not is_r2_url(url):
        raise HTTPException(status_code=400, detail="Not an R2 URL")
    await delete_r2_object(url)
