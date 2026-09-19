from pydantic import BaseModel

class MenuCategoryCreate(BaseModel):
    name: str
    image_url: str | None = None

class MenuCategoryUpdate(BaseModel):
    name: str | None = None
    image_url: str | None = None

class MenuCategoryOut(BaseModel):
    id: int
    name: str
    image_url: str | None = None
    class Config:
        from_attributes = True

class MenuItemBase(BaseModel):
    category_id: int
    name: str
    description: str | None = None
    price: float
    image_url: str | None = None
    is_veg: bool = True
    tag: str | None = None
    offer_pct: int | None = None
    stock: int = 0

class MenuItemCreate(MenuItemBase):
    pass

class MenuItemUpdate(BaseModel):
    category_id: int | None = None
    name: str | None = None
    description: str | None = None
    price: float | None = None
    image_url: str | None = None
    is_veg: bool | None = None
    tag: str | None = None
    offer_pct: int | None = None
    is_available: bool | None = None
    stock: int | None = None

class MenuItemOut(MenuItemBase):
    id: int
    restaurant_id: int
    is_available: bool
    class Config:
        from_attributes = True

class RestaurantOut(BaseModel):
    id: int
    name: str
    class Config:
        from_attributes = True
