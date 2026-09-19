import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./qr_orders.db"
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    R2_UPLOAD_URL: str | None = None
    R2_UPLOAD_KEY: str | None = None
    R2_PUBLIC_URL: str | None = None
    FIREBASE_API_KEY: str | None = None

    class Config:
        env_file = ".env"

settings = Settings()
