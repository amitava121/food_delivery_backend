import os

# Always run against a disposable SQLite file — the app's DATABASE_URL
# points at real Postgres; never drop/mutate that.
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_api.db"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.db.base import Base

client = TestClient(app)

sync_engine = create_engine("sqlite:///./test_api.db", connect_args={"check_same_thread": False})
SyncSession = sessionmaker(bind=sync_engine)

def test_root():
    r = client.get("/")
    assert r.status_code == 200

def test_auth_and_order_flow():
    # register owner and customer
    owner = client.post("/auth/register", json={
        "email": "owner@test.com", "name": "Owner", "password": "secret", "role": "owner"
    })
    assert owner.status_code == 200
    customer = client.post("/auth/register", json={
        "email": "customer@test.com", "name": "Customer", "password": "secret", "role": "customer"
    })
    assert customer.status_code == 200

    # login customer
    r = client.post("/auth/token", json={"username": "customer@test.com", "password": "secret"})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # create restaurant via db directly (admin not implemented)
    db = SyncSession()
    from app import models
    rest = models.Restaurant(name="Test Diner", owner_id=owner.json()["id"])
    db.add(rest)
    db.commit()
    db.refresh(rest)
    db.close()

    # create category and item as owner (menu writes are owner/admin only)
    owner_token = client.post("/auth/token", json={"username": "owner@test.com", "password": "secret"}).json()["access_token"]
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    cat = client.post(f"/menu/restaurants/{rest.id}/categories", json={"name": "Burgers"}, headers=owner_headers)
    assert cat.status_code == 200
    item = client.post(f"/menu/restaurants/{rest.id}/items", json={
        "category_id": cat.json()["id"], "name": "Cheese Burger", "price": 5.99, "stock": 10
    }, headers=owner_headers)
    assert item.status_code == 200

    # create QR location as owner
    qr = client.post(f"/qr/locations/{rest.id}", params={"label": "Booth 1"}, headers=owner_headers)
    assert qr.status_code == 200

    # place order
    order = client.post("/orders/", json={
        "restaurant_id": rest.id,
        "location_id": qr.json()["id"],
        "items": [{"menu_item_id": item.json()["id"], "quantity": 2}]
    }, headers=headers)
    assert order.status_code == 200, order.text
    assert order.json()["total"] == 11.98

    # update status
    upd = client.patch(f"/orders/{order.json()['id']}/status?status=preparing", headers=headers)
    assert upd.status_code == 200

    print("All tests passed")

if __name__ == "__main__":
    Base.metadata.drop_all(bind=sync_engine)
    Base.metadata.create_all(bind=sync_engine)
    test_root()
    test_auth_and_order_flow()
