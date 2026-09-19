import json
import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app import models
from app.core import security
from app.core.config import settings
from app.core.deps import get_db, get_current_user, require_role, user_roles
from app.routers.ws import menu_broadcaster
from app.schemas.auth import (
    UserCreate,
    UserOut,
    SyncOut,
    Token,
    Login,
    UserSync,
    UserPatch,
    GoogleToken,
)

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/register", response_model=UserOut)
async def register(payload: UserCreate, db: AsyncSession = Depends(get_db)):
    if await db.scalar(select(models.User).where(models.User.email == payload.email)):
        raise HTTPException(status_code=400, detail="Email already registered")
    user = models.User(
        email=payload.email,
        name=payload.name,
        phone=payload.phone,
        roles=json.dumps([r.value for r in payload.roles]),
        hashed_password=security.get_password_hash(payload.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user

@router.post("/token", response_model=Token)
async def login(form: Login, db: AsyncSession = Depends(get_db)):
    user = await db.scalar(select(models.User).where(models.User.email == form.username))
    if not user or not security.verify_password(form.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect credentials")
    token = security.create_access_token({"sub": user.email, "roles": sorted(user_roles(user))})
    return {"access_token": token, "token_type": "bearer"}

@router.get("/me", response_model=UserOut)
async def me(user: models.User = Depends(get_current_user)):
    return user


@router.post("/google", response_model=Token)
async def google_login(payload: GoogleToken, db: AsyncSession = Depends(get_db)):
    """Admin Google sign-in: verify the Firebase ID token with Google, then
    issue our own JWT — only if the email maps to an owner/admin account."""
    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.post(
            "https://identitytoolkit.googleapis.com/v1/accounts:lookup",
            params={"key": settings.FIREBASE_API_KEY},
            json={"idToken": payload.id_token},
        )
    if res.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid Google token")
    info = res.json()["users"][0]
    user = await db.scalar(
        select(models.User).where(models.User.email == info["email"])
    )
    roles = user_roles(user) if user else set()
    if not user or not roles & {models.UserRole.admin.value, models.UserRole.kitchen.value}:
        raise HTTPException(status_code=403, detail="Not a staff account")
    if user.is_blocked:
        raise HTTPException(status_code=403, detail="Account is blocked")
    if not user.firebase_uid:
        user.firebase_uid = info["localId"]
        user.photo_url = info.get("photoUrl")
        await db.commit()
    token = security.create_access_token(
        {"sub": user.email, "roles": sorted(roles)}
    )
    return {"access_token": token, "token_type": "bearer"}


@router.post("/sync", response_model=SyncOut)
async def sync_google_user(payload: UserSync, db: AsyncSession = Depends(get_db)):
    """Called by the customer site after a Google sign-in — upserts the user.
    Blocked users get 403 so the site signs them back out."""
    user = await db.scalar(
        select(models.User).where(
            (models.User.firebase_uid == payload.uid)
            | (models.User.email == payload.email)
        )
    )
    if user and user.is_blocked:
        raise HTTPException(status_code=403, detail="Account is blocked")
    if user:
        user.name = payload.name
        user.photo_url = payload.photo
        user.firebase_uid = payload.uid
    else:
        user = models.User(
            email=payload.email,
            name=payload.name,
            firebase_uid=payload.uid,
            photo_url=payload.photo,
            hashed_password="",
            roles='["customer"]',
        )
        db.add(user)
    await db.commit()
    await db.refresh(user)
    await menu_broadcaster.notify("users_changed")
    token = security.create_access_token(
        {"sub": user.email, "roles": sorted(user_roles(user))}
    )
    out = UserOut.model_validate(user)
    return SyncOut(**out.model_dump(), access_token=token)


admin_only = require_role(models.UserRole.admin)


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
    _: models.User = Depends(admin_only),
):
    """Admin-created staff account (admin / kitchen / customer)."""
    if await db.scalar(
        select(models.User).where(models.User.email == payload.email)
    ):
        raise HTTPException(status_code=400, detail="Email already registered")
    user = models.User(
        email=payload.email,
        name=payload.name,
        phone=payload.phone,
        roles=json.dumps([r.value for r in payload.roles]),
        hashed_password=security.get_password_hash(payload.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    await menu_broadcaster.notify("users_changed")
    return user


@router.get("/users", response_model=list[UserOut])
async def list_users(
    db: AsyncSession = Depends(get_db), _: models.User = Depends(admin_only)
):
    return (
        await db.scalars(
            select(models.User).order_by(models.User.created_at.desc())
        )
    ).all()


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    payload: UserPatch,
    db: AsyncSession = Depends(get_db),
    _: models.User = Depends(admin_only),
):
    user = await db.get(models.User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if payload.name is not None:
        user.name = payload.name
    if payload.is_blocked is not None:
        user.is_blocked = payload.is_blocked
    if payload.roles is not None:
        user.roles = json.dumps([r.value for r in payload.roles])
    await db.commit()
    await db.refresh(user)
    await menu_broadcaster.notify("users_changed")
    return user


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _: models.User = Depends(admin_only),
):
    user = await db.get(models.User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await db.delete(user)
    await db.commit()
    await menu_broadcaster.notify("users_changed")
