import json
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import AsyncSessionLocal
from app.core.security import decode_token
from app import models

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

async def get_db():
    async with AsyncSessionLocal() as db:
        yield db

async def get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)):
    payload = decode_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user = await db.scalar(select(models.User).where(models.User.email == payload["sub"]))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user

def user_roles(user: models.User) -> set:
    try:
        return set(json.loads(user.roles or '["customer"]'))
    except Exception:
        return {"customer"}


def is_super_admin(user: models.User) -> bool:
    return "super_admin" in user_roles(user)


def is_admin(user: models.User) -> bool:
    """True if user has admin or super_admin role (super_admin inherits admin)."""
    return bool(user_roles(user) & {"admin", "super_admin"})


def is_kitchen(user: models.User) -> bool:
    return "kitchen" in user_roles(user)


def require_role(*roles: str):
    async def checker(user: models.User = Depends(get_current_user)):
        roles_set = set(roles)
        u_roles = user_roles(user)
        # super_admin inherits admin privileges
        if "admin" in roles_set and "super_admin" in u_roles:
            return user
        if not u_roles & roles_set:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not enough permissions",
            )
        return user
    return checker


async def require_super_admin(user: models.User = Depends(get_current_user)) -> models.User:
    if not is_super_admin(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super Admin access required.",
        )
    return user


async def require_admin(user: models.User = Depends(get_current_user)) -> models.User:
    if not is_admin(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    return user
