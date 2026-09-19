from fastapi import APIRouter

router = APIRouter(prefix="/notifications", tags=["notifications"])

@router.get("/")
async def list_notifications():
    # WebSocket / push integration placeholder
    return {"message": "Notification service stub"}
