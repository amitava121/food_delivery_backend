from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.db.base import Base
from app.db.session import engine
from app import models
from app.routers import auth, menu, order, payment, qr, inventory, report, notification, upload, ws, banner, cart

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()

app = FastAPI(title="QR Fast Food Ordering System", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(menu.router)
app.include_router(order.router)
app.include_router(payment.router)
app.include_router(qr.router)
app.include_router(inventory.router)
app.include_router(report.router)
app.include_router(notification.router)
app.include_router(upload.router)
app.include_router(ws.router)
app.include_router(banner.router)
app.include_router(cart.router)

@app.get("/")
async def root():
    return {"message": "QR Fast Food Ordering API"}
