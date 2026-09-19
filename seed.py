from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.db.base import Base
from app.core.config import settings
from app.core.security import get_password_hash
from app import models

# One-shot script — uses its own sync engine (runtime backend is fully async).
SYNC_URL = settings.DATABASE_URL.replace("+asyncpg", "").replace("ssl=require", "sslmode=require")
engine = create_engine(SYNC_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def migrate():
    """Add columns introduced after the initial schema (SQLite-only; Postgres gets them via create_all)."""
    if engine.dialect.name != "sqlite":
        return
    with engine.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(menu_items)"))}
        for col, ddl in {
            "is_veg": "ALTER TABLE menu_items ADD COLUMN is_veg BOOLEAN DEFAULT 1",
            "tag": "ALTER TABLE menu_items ADD COLUMN tag VARCHAR",
            "offer_pct": "ALTER TABLE menu_items ADD COLUMN offer_pct INTEGER",
        }.items():
            if col not in cols:
                conn.execute(text(ddl))
        conn.commit()

def seed():
    Base.metadata.create_all(bind=engine)
    migrate()
    db = SessionLocal()
    if db.query(models.User).filter(models.User.email == "owner@demo.com").first():
        print("Demo users exist, skipping")
    else:
        owner = models.User(
            email="owner@demo.com",
            name="Demo Owner",
            phone="+91-9999999999",
            role=models.UserRole.owner,
            hashed_password=get_password_hash("demo123"),
        )
        customer = models.User(
            email="customer@demo.com",
            name="Demo Customer",
            role=models.UserRole.customer,
            hashed_password=get_password_hash("demo123"),
        )
        db.add_all([owner, customer])
        db.flush()

        restaurant = models.Restaurant(name="Zesty Bites", owner_id=owner.id)
        db.add(restaurant)
        db.flush()

        loc = models.QRLocation(restaurant_id=restaurant.id, label="Table 1", qr_code="TABLE01")
        db.add(loc)

        cats = [
            models.MenuCategory(name="Burgers", restaurant_id=restaurant.id),
            models.MenuCategory(name="Pizza", restaurant_id=restaurant.id),
            models.MenuCategory(name="Drinks", restaurant_id=restaurant.id),
        ]
        db.add_all(cats)
        db.flush()

        items = [
            models.MenuItem(restaurant_id=restaurant.id, category_id=cats[0].id, name="Classic Burger", description="Juicy beef patty with cheese", price=149, stock=20, image_url="https://via.placeholder.com/150"),
            models.MenuItem(restaurant_id=restaurant.id, category_id=cats[0].id, name="Veggie Burger", description="Grilled veggies and cheddar", price=129, stock=15, image_url="https://via.placeholder.com/150"),
            models.MenuItem(restaurant_id=restaurant.id, category_id=cats[1].id, name="Margherita Pizza", description="Mozzarella and basil", price=249, stock=10, image_url="https://via.placeholder.com/150"),
            models.MenuItem(restaurant_id=restaurant.id, category_id=cats[2].id, name="Coke", description="Chilled 500ml", price=49, stock=50, image_url="https://via.placeholder.com/150"),
        ]
        db.add_all(items)
        db.commit()
        print("Seeded demo restaurant with owner@demo.com / customer@demo.com (password: demo123)")

    seed_spice_route(db)
    db.close()

def seed_spice_route(db):
    """The restaurant + full menu used by restaurant-website/."""
    if db.query(models.Restaurant).filter(models.Restaurant.name == "Spice Route Kitchen").first():
        print("Spice Route Kitchen already seeded")
        return

    owner = db.query(models.User).filter(models.User.email == "owner@demo.com").first()
    rest = models.Restaurant(name="Spice Route Kitchen", owner_id=owner.id)
    db.add(rest)
    db.flush()

    cat_names = ["Pizza", "Burgers", "Biryani & Rice", "North Indian", "Desserts", "Beverages"]
    cats = {name: models.MenuCategory(name=name, restaurant_id=rest.id) for name in cat_names}
    db.add_all(cats.values())
    db.flush()

    IMG = "https://images.unsplash.com/photo-{}?w=400&q=80"
    # (name, cat, desc, price, veg, tag, photo_id)
    dishes = [
        ("Hyderabadi Chicken Biryani", "Biryani & Rice", "Fragrant basmati layered with marinated chicken, saffron, fried onions. Served with raita & mirchi ka salan.", 289, False, "Bestseller", "1589302168068-964664d93dc0"),
        ("Butter Chicken + Naan Combo", "North Indian", "Creamy tomato-butter gravy with charred tandoori chicken, paired with 2 butter naans.", 329, False, "Bestseller", "1585937421612-70a008356fbe"),
        ("Farmhouse Woodfired Pizza", "Pizza", "Loaded with capsicum, onion, mushroom, sweet corn & double mozzarella on a hand-tossed base.", 319, True, "Must try", "1513104890138-7c749659a591"),
        ("Classic Smash Burger", "Burgers", "Double-smashed patty, cheddar, caramelised onions, house sauce in a toasted brioche bun.", 219, False, None, "1568901346375-23c9450c58cd"),
        ("Margherita Blast", "Pizza", "San Marzano tomato sauce, fresh mozzarella, basil. Simple. Perfect.", 199, True, None, "1604382354936-07c5d9983bd3"),
        ("Peppy Paneer Pizza", "Pizza", "Spiced paneer cubes, crunchy capsicum & red paprika on cheesy base.", 269, True, None, "1565299624946-b28f40a0ae38"),
        ("Chicken Dominator", "Pizza", "Grilled chicken, peri-peri chicken, chicken sausage & BBQ drizzle. Meat lover's dream.", 379, False, "Bestseller", "1628840042765-356cda07504e"),
        ("Crispy Veggie Burger", "Burgers", "Crunchy veg patty, chipotle mayo, lettuce, tomato. Served with peri-peri fries.", 149, True, None, "1550547660-d9450f859349"),
        ("Zinger Chicken Burger", "Burgers", "Fiery crispy chicken fillet, jalapeños, smoky mayo in a sesame bun.", 189, False, "Bestseller", "1571091718767-18b5b1457add"),
        ("Loaded Fries + Dip", "Burgers", "Golden fries tossed in peri-peri, served with cheese & garlic dips.", 129, True, None, "1573080496219-bb080dd4f877"),
        ("Veg Dum Biryani", "Biryani & Rice", "Garden veggies & paneer slow-steamed with basmati, mint & whole spices.", 229, True, None, "1563379091339-03b21ab4a4f8"),
        ("Egg Biryani", "Biryani & Rice", "Masala-roasted eggs layered with fragrant rice. Comfort in a handi.", 199, False, None, "1512058564366-18510be2db19"),
        ("Paneer Tikka Skewers", "Biryani & Rice", "Char-grilled paneer, peppers & onions with mint chutney.", 249, True, None, "1599487488170-d11ec9c172f0"),
        ("Dal Makhani + Jeera Rice", "North Indian", "Slow-cooked black lentils finished with cream, served over cumin rice.", 239, True, None, "1546833999-b9f581a1996d"),
        ("Masala Dosa", "North Indian", "Crisp golden crepe, spiced potato filling, sambar & coconut chutney.", 169, True, "Bestseller", "1668236543090-82eba5ee5976"),
        ("Hakka Noodles", "North Indian", "Wok-tossed noodles, julienned veggies, schezwan kick.", 179, True, None, "1585032226651-759b368d7246"),
        ("Steamed Chicken Momos (8 pc)", "North Indian", "Juicy minced chicken momos with fiery red chutney.", 159, False, None, "1496116218417-1a781b1c416c"),
        ("Molten Choco Lava Cake", "Desserts", "Warm chocolate cake with a gooey molten centre. Dangerous stuff.", 109, True, "Bestseller", "1578985545062-69928b1d9587"),
        ("Belgian Chocolate Ice Cream", "Desserts", "Rich, dense, dark chocolate scoop. 450ml tub.", 149, True, None, "1563805042-7684c019e1cb"),
        ("Glazed Donut Box (2 pc)", "Desserts", "Fluffy donuts — one chocolate glazed, one strawberry sprinkle.", 129, True, None, "1551024601-bec78aea704b"),
        ("Cold Coffee Frappe", "Beverages", "Double-shot espresso blended thick with vanilla ice cream.", 159, True, None, "1541167760496-1628856ab772"),
        ("Virgin Mint Mojito", "Beverages", "Muddled mint, lime & soda over crushed ice. Super refreshing.", 119, True, None, "1551538827-9c037cb4f32a"),
        ("Thick Oreo Shake", "Beverages", "Cookies & cream milkshake topped with whipped cream.", 179, True, None, "1579954115545-a95591f28bfc"),
    ]

    db.add_all([
        models.MenuItem(
            restaurant_id=rest.id, category_id=cats[cat].id,
            name=name, description=desc, price=price,
            is_veg=veg, tag=tag, image_url=IMG.format(photo),
            offer_pct=20 if tag == "Bestseller" else None,
            stock=50,
        )
        for name, cat, desc, price, veg, tag, photo in dishes
    ])
    db.commit()
    print(f"Seeded Spice Route Kitchen (restaurant_id={rest.id}) with {len(dishes)} dishes")

if __name__ == "__main__":
    seed()
