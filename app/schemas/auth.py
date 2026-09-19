import json
from datetime import datetime
from pydantic import BaseModel, EmailStr, field_validator
from app.models.models import UserRole


class UserCreate(BaseModel):
    email: EmailStr
    name: str
    password: str
    roles: list[UserRole] = [UserRole.customer]
    phone: str | None = None


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    roles: list[str] = []
    phone: str | None
    photo_url: str | None = None
    firebase_uid: str | None = None
    is_blocked: bool = False
    created_at: datetime | None = None

    @field_validator("roles", mode="before")
    @classmethod
    def _parse_roles(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return [v] if v else []
        return v or []

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str


class Login(BaseModel):
    username: str
    password: str


class UserSync(BaseModel):
    uid: str
    name: str
    email: EmailStr
    photo: str | None = None


class SyncOut(UserOut):
    access_token: str


class UserPatch(BaseModel):
    name: str | None = None
    is_blocked: bool | None = None
    roles: list[UserRole] | None = None


class GoogleToken(BaseModel):
    id_token: str
