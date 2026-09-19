from pydantic import BaseModel, ConfigDict


class BannerBase(BaseModel):
    title: str
    subtitle: str | None = None
    cta_text: str | None = None
    image_url: str | None = None
    bg_color: str = "#f6e3b4"
    is_active: bool = True
    sort_order: int = 0


class BannerCreate(BannerBase):
    pass


class BannerUpdate(BaseModel):
    title: str | None = None
    subtitle: str | None = None
    cta_text: str | None = None
    image_url: str | None = None
    bg_color: str | None = None
    is_active: bool | None = None
    sort_order: int | None = None


class BannerOut(BannerBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    restaurant_id: int
