from app import models


def test_root(client):
    r = client.get("/")
    assert r.status_code == 200


def test_auth_and_order_flow(client, db_session):
    # register admin and customer
    owner = client.post("/auth/register", json={
        "email": "owner@test.com", "name": "Owner", "password": "secret", "roles": ["admin"]
    })
    assert owner.status_code == 200
    customer = client.post("/auth/register", json={
        "email": "customer@test.com", "name": "Customer", "password": "secret", "roles": ["customer"]
    })
    assert customer.status_code == 200

    # login customer
    r = client.post("/auth/token", json={"username": "customer@test.com", "password": "secret"})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # create restaurant via db directly (admin not implemented)
    rest = models.Restaurant(name="Test Diner", owner_id=owner.json()["id"])
    db_session.add(rest)
    db_session.commit()
    db_session.refresh(rest)

    # create category and item as admin (menu writes are admin only)
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
