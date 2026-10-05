import json
import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app import models
from app.core import security
from app.core.config import settings
from app.core.deps import (
    get_db,
    get_current_user,
    require_role,
    user_roles,
    require_admin,
    require_super_admin,
    is_super_admin,
    is_admin,
)
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
    requested_roles = {r.value for r in payload.roles}
    admin_roles = {models.UserRole.admin.value, models.UserRole.super_admin.value}
    if requested_roles & admin_roles:
        # Check if an admin already exists in the system (bootstrap safeguard)
        has_admins = await db.scalar(
            select(models.User).where(
                (models.User.roles.like('%"admin"%')) | (models.User.roles.like('%"super_admin"%'))
            )
        )
        if has_admins:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Public registration cannot create administrative accounts. Use /auth/admins.",
            )
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
    issue our own JWT — only if the email maps to an owner/admin/kitchen account."""
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
    allowed_staff = {
        models.UserRole.super_admin.value,
        models.UserRole.admin.value,
        models.UserRole.kitchen.value,
    }
    if not user or not roles & allowed_staff:
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


# =========================================================================
# USERS MANAGEMENT (Normal Application Users: Customers, Kitchen/Chef)
# Accessible to both Super Admin and Admin
# =========================================================================

@router.get("/users", response_model=list[UserOut])
async def list_users(
    db: AsyncSession = Depends(get_db),
    caller: models.User = Depends(require_admin),
):
    """List normal application users (Customers and Chefs). Excludes administrators."""
    users = (
        await db.scalars(
            select(models.User).order_by(models.User.created_at.desc())
        )
    ).all()
    # Exclude admins and super_admins from the normal users list
    return [u for u in users if not (user_roles(u) & {"admin", "super_admin"})]


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
    caller: models.User = Depends(require_admin),
):
    """Create a normal application user (Customer or Chef)."""
    # Administrative accounts cannot be created here under any circumstances.
    admin_roles = {models.UserRole.admin, models.UserRole.super_admin}
    if any(r in admin_roles for r in payload.roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrative accounts cannot be created via user management. Use /auth/admins.",
        )
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


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    payload: UserPatch,
    db: AsyncSession = Depends(get_db),
    caller: models.User = Depends(require_admin),
):
    """Update normal application user. Administrators cannot be modified here."""
    user = await db.get(models.User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    target_roles = user_roles(user)
    if target_roles & {"admin", "super_admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot modify administrator accounts via user management.",
        )
    admin_roles = {models.UserRole.admin, models.UserRole.super_admin}
    if not is_super_admin(caller) and payload.roles and any(r in admin_roles for r in payload.roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Normal admins cannot promote users to administrator.",
        )
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
    caller: models.User = Depends(require_admin),
):
    """Delete a normal application user. Administrators cannot be deleted here."""
    user = await db.get(models.User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user_roles(user) & {"admin", "super_admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete administrator accounts via user management.",
        )
    await db.delete(user)
    await db.commit()
    await menu_broadcaster.notify("users_changed")


# =========================================================================
# ADMINS MANAGEMENT (Administrators & Super Admins)
# Exclusively accessible to Super Admin
# =========================================================================

@router.get("/admins", response_model=list[UserOut])
async def list_admins(
    db: AsyncSession = Depends(get_db),
    caller: models.User = Depends(require_super_admin),
):
    """List administrator accounts. Super Admin only."""
    users = (
        await db.scalars(
            select(models.User).order_by(models.User.created_at.desc())
        )
    ).all()
    return [u for u in users if user_roles(u) & {"admin", "super_admin"}]


@router.post("/admins", response_model=UserOut, status_code=201)
async def create_admin(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
    caller: models.User = Depends(require_super_admin),
):
    """Create an administrator account. Super Admin only."""
    if await db.scalar(
        select(models.User).where(models.User.email == payload.email)
    ):
        raise HTTPException(status_code=400, detail="Email already registered")
    # Ensure newly created user in /admins has admin or super_admin role
    req_roles = [r.value for r in payload.roles]
    if not set(req_roles) & {"admin", "super_admin"}:
        req_roles.append("admin")
    user = models.User(
        email=payload.email,
        name=payload.name,
        phone=payload.phone,
        roles=json.dumps(req_roles),
        hashed_password=security.get_password_hash(payload.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    await menu_broadcaster.notify("admins_changed")
    return user


@router.patch("/admins/{admin_id}", response_model=UserOut)
async def update_admin(
    admin_id: int,
    payload: UserPatch,
    db: AsyncSession = Depends(get_db),
    caller: models.User = Depends(require_super_admin),
):
    """Update administrator account. Super Admin only."""
    user = await db.get(models.User, admin_id)
    if not user:
        raise HTTPException(status_code=404, detail="Administrator not found")
    target_roles = user_roles(user)
    if not target_roles & {"admin", "super_admin"}:
        raise HTTPException(status_code=400, detail="Target user is not an administrator.")

    # Super Admin Protection: prevent demoting or blocking the last Super Admin
    if "super_admin" in target_roles:
        is_demoting = payload.roles is not None and models.UserRole.super_admin not in payload.roles
        is_blocking = payload.is_blocked is True
        if is_demoting or is_blocking:
            all_users = (await db.scalars(select(models.User))).all()
            other_active_super_admins = [
                u for u in all_users
                if u.id != user.id and "super_admin" in user_roles(u) and not u.is_blocked
            ]
            if not other_active_super_admins:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot demote or block the only active Super Admin.",
                )

    if payload.name is not None:
        user.name = payload.name
    if payload.is_blocked is not None:
        user.is_blocked = payload.is_blocked
    if payload.roles is not None:
        user.roles = json.dumps([r.value for r in payload.roles])
    await db.commit()
    await db.refresh(user)
    await menu_broadcaster.notify("admins_changed")
    return user


@router.delete("/admins/{admin_id}", status_code=204)
async def delete_admin(
    admin_id: int,
    db: AsyncSession = Depends(get_db),
    caller: models.User = Depends(require_super_admin),
):
    """Delete administrator account. Super Admin only."""
    user = await db.get(models.User, admin_id)
    if not user:
        raise HTTPException(status_code=404, detail="Administrator not found")
    if user.id == caller.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account.")
    if "super_admin" in user_roles(user):
        raise HTTPException(status_code=400, detail="Cannot delete a Super Admin account.")
    await db.delete(user)
    await db.commit()
    await menu_broadcaster.notify("admins_changed")
