import pytest
from app import models


@pytest.fixture()
def setup_restaurant(client, db_session):
    """Create test restaurant, categories, and test menu items with known stock."""
    # 1. Register users
    sa_res = client.post("/auth/register", json={
        "email": "sa_ord@test.com", "name": "Super Admin", "password": "pass", "roles": ["super_admin"]
    })
    admin_res = client.post("/auth/admins", json={
        "email": "admin_ord@test.com", "name": "Admin", "password": "pass", "roles": ["admin"]
    }, headers={"Authorization": f"Bearer {client.post('/auth/token', json={'username': 'sa_ord@test.com', 'password': 'pass'}).json()['access_token']}"})
    chef_res = client.post("/auth/register", json={
        "email": "chef_ord@test.com", "name": "Chef", "password": "pass", "roles": ["kitchen"]
    })
    cust1_res = client.post("/auth/register", json={
        "email": "cust1_ord@test.com", "name": "Alice", "password": "pass", "roles": ["customer"]
    })
    cust2_res = client.post("/auth/register", json={
        "email": "cust2_ord@test.com", "name": "Bob", "password": "pass", "roles": ["customer"]
    })

    # Tokens
    sa_tok = client.post("/auth/token", json={"username": "sa_ord@test.com", "password": "pass"}).json()["access_token"]
    admin_tok = client.post("/auth/token", json={"username": "admin_ord@test.com", "password": "pass"}).json()["access_token"]
    chef_tok = client.post("/auth/token", json={"username": "chef_ord@test.com", "password": "pass"}).json()["access_token"]
    c1_tok = client.post("/auth/token", json={"username": "cust1_ord@test.com", "password": "pass"}).json()["access_token"]
    c2_tok = client.post("/auth/token", json={"username": "cust2_ord@test.com", "password": "pass"}).json()["access_token"]

    # 2. Restaurant
    rest = models.Restaurant(name="Spice Route Kitchen", owner_id=sa_res.json()["id"])
    db_session.add(rest)
    db_session.commit()
    db_session.refresh(rest)

    # 3. Category & Items via Admin
    admin_hdr = {"Authorization": f"Bearer {admin_tok}"}
    cat = client.post(f"/menu/restaurants/{rest.id}/categories", json={"name": "Biryani"}, headers=admin_hdr).json()

    # Item 1: In stock (stock=10, price=200, 10% offer)
    item1 = client.post(f"/menu/restaurants/{rest.id}/items", json={
        "category_id": cat["id"],
        "name": "Chicken Biryani",
        "price": 200.0,
        "offer_pct": 10.0,
        "stock": 10,
        "prep_time_minutes": 20,
    }, headers=admin_hdr).json()

    # Item 2: Low stock (stock=1, price=100)
    item2 = client.post(f"/menu/restaurants/{rest.id}/items", json={
        "category_id": cat["id"],
        "name": "Gulab Jamun",
        "price": 100.0,
        "offer_pct": 0.0,
        "stock": 1,
        "prep_time_minutes": 5,
    }, headers=admin_hdr).json()

    # Item 3: Out of stock (stock=0, price=50)
    item3 = client.post(f"/menu/restaurants/{rest.id}/items", json={
        "category_id": cat["id"],
        "name": "Ice Cream",
        "price": 50.0,
        "stock": 0,
        "prep_time_minutes": 5,
    }, headers=admin_hdr).json()

    return {
        "rest_id": rest.id,
        "item1": item1,
        "item2": item2,
        "item3": item3,
        "tokens": {
            "sa": sa_tok,
            "admin": admin_tok,
            "chef": chef_tok,
            "c1": c1_tok,
            "c2": c2_tok,
        },
    }


def test_authoritative_pricing_and_tamper_resistance(client, setup_restaurant):
    """Client-provided prices, subtotals, and totals must be completely ignored."""
    data = setup_restaurant
    c1_hdr = {"Authorization": f"Bearer {data['tokens']['c1']}"}
    item1_id = data["item1"]["id"]

    # Malicious client attempts to pass price: 1.0, subtotal: 1.0, total: 1.0
    payload = {
        "restaurant_id": data["rest_id"],
        "fulfillment_type": "pickup",
        "items": [
            {
                "menu_item_id": item1_id,
                "quantity": 2,
                "unit_price": 1.0,
                "price": 1.0,
                "line_total": 2.0,
            }
        ],
        "subtotal": 2.0,
        "discount": 0.0,
        "total": 2.0,
    }

    res = client.post("/orders/", json=payload, headers=c1_hdr)
    assert res.status_code == 200, res.text
    order = res.json()

    # Authoritative calculation:
    # Item 1 original price: 200.0, 10% discount -> eff_price = 180.0
    # Qty = 2 -> subtotal = 400.0, discount = 40.0, total = 360.0
    assert order["subtotal"] == 400.0
    assert order["discount"] == 40.0
    assert order["total"] == 360.0
    assert len(order["items"]) == 1
    assert order["items"][0]["unit_price"] == 180.0
    assert order["items"][0]["line_total"] == 360.0


def test_atomic_stock_deduction_and_inventory_log(client, setup_restaurant, db_session):
    """Ordering items decrements stock and writes inventory logs."""
    data = setup_restaurant
    c1_hdr = {"Authorization": f"Bearer {data['tokens']['c1']}"}
    item1_id = data["item1"]["id"]

    # Initial stock is 10
    res = client.post("/orders/", json={
        "restaurant_id": data["rest_id"],
        "fulfillment_type": "pickup",
        "items": [{"menu_item_id": item1_id, "quantity": 3}],
    }, headers=c1_hdr)
    assert res.status_code == 200
    order_num = res.json()["order_number"]

    # Verify stock in DB is decremented to 7
    db_item = db_session.get(models.MenuItem, item1_id)
    assert db_item.stock == 7

    # Verify InventoryLog was written
    logs = db_session.query(models.InventoryLog).filter(
        models.InventoryLog.menu_item_id == item1_id,
        models.InventoryLog.reason == f"order:{order_num}"
    ).all()
    assert len(logs) == 1
    assert logs[0].change == -3


def test_insufficient_stock_rejects_and_prevents_negative(client, setup_restaurant, db_session):
    """If quantity exceeds available stock, order must fail and stock must not change."""
    data = setup_restaurant
    c1_hdr = {"Authorization": f"Bearer {data['tokens']['c1']}"}
    item2_id = data["item2"]["id"]  # stock = 1

    # Request quantity 2 when stock is 1
    res = client.post("/orders/", json={
        "restaurant_id": data["rest_id"],
        "fulfillment_type": "pickup",
        "items": [{"menu_item_id": item2_id, "quantity": 2}],
    }, headers=c1_hdr)
    assert res.status_code == 400
    assert "stock" in res.json()["detail"].lower()

    # Stock must still be 1 (no negative stock, no deduction)
    db_item = db_session.get(models.MenuItem, item2_id)
    assert db_item.stock == 1

    # Out of stock item (stock = 0)
    item3_id = data["item3"]["id"]
    res_zero = client.post("/orders/", json={
        "restaurant_id": data["rest_id"],
        "fulfillment_type": "pickup",
        "items": [{"menu_item_id": item3_id, "quantity": 1}],
    }, headers=c1_hdr)
    assert res_zero.status_code == 400
    assert "out of stock" in res_zero.json()["detail"].lower()


def test_idempotency_prevents_duplicate_orders(client, setup_restaurant, db_session):
    """Submitting the same idempotency_key returns original order without double deduction."""
    data = setup_restaurant
    c1_hdr = {"Authorization": f"Bearer {data['tokens']['c1']}"}
    item1_id = data["item1"]["id"]
    idemp_key = "unique_req_key_12345"

    initial_stock = db_session.get(models.MenuItem, item1_id).stock

    # First submission
    res1 = client.post("/orders/", json={
        "restaurant_id": data["rest_id"],
        "fulfillment_type": "pickup",
        "items": [{"menu_item_id": item1_id, "quantity": 2}],
        "idempotency_key": idemp_key,
    }, headers=c1_hdr)
    assert res1.status_code == 200
    ord1_id = res1.json()["id"]

    # Stock decremented by 2
    db_session.expire_all()
    assert db_session.get(models.MenuItem, item1_id).stock == initial_stock - 2

    # Second submission with same idempotency key (simulating network retry/double-click)
    res2 = client.post("/orders/", json={
        "restaurant_id": data["rest_id"],
        "fulfillment_type": "pickup",
        "items": [{"menu_item_id": item1_id, "quantity": 2}],
        "idempotency_key": idemp_key,
    }, headers=c1_hdr)
    assert res2.status_code == 200
    assert res2.json()["id"] == ord1_id

    # Stock was NOT decremented again!
    db_session.expire_all()
    assert db_session.get(models.MenuItem, item1_id).stock == initial_stock - 2


def test_fulfillment_validation(client, setup_restaurant):
    """Delivery requires address; Pickup does not require address."""
    data = setup_restaurant
    c1_hdr = {"Authorization": f"Bearer {data['tokens']['c1']}"}
    item1_id = data["item1"]["id"]

    # 1. Delivery without address -> 400
    res_bad = client.post("/orders/", json={
        "restaurant_id": data["rest_id"],
        "fulfillment_type": "delivery",
        "delivery_address": "",
        "items": [{"menu_item_id": item1_id, "quantity": 1}],
    }, headers=c1_hdr)
    assert res_bad.status_code == 400
    assert "address" in res_bad.json()["detail"].lower()

    # 2. Delivery with address -> 200
    res_deliv = client.post("/orders/", json={
        "restaurant_id": data["rest_id"],
        "fulfillment_type": "delivery",
        "delivery_address": "Flat 402, Lotus Tower, Kolkata",
        "customer_phone": "9876543210",
        "items": [{"menu_item_id": item1_id, "quantity": 1}],
    }, headers=c1_hdr)
    assert res_deliv.status_code == 200
    assert res_deliv.json()["fulfillment_type"] == "delivery"
    assert res_deliv.json()["delivery_address"] == "Flat 402, Lotus Tower, Kolkata"

    # 3. Pickup -> 200 without address
    res_pickup = client.post("/orders/", json={
        "restaurant_id": data["rest_id"],
        "fulfillment_type": "pickup",
        "items": [{"menu_item_id": item1_id, "quantity": 1}],
    }, headers=c1_hdr)
    assert res_pickup.status_code == 200
    assert res_pickup.json()["fulfillment_type"] == "pickup"


def test_bola_and_unauthenticated_security(client, setup_restaurant):
    """Customer A cannot view Customer B's order; Unauthenticated user rejected."""
    data = setup_restaurant
    c1_hdr = {"Authorization": f"Bearer {data['tokens']['c1']}"}
    c2_hdr = {"Authorization": f"Bearer {data['tokens']['c2']}"}
    chef_hdr = {"Authorization": f"Bearer {data['tokens']['chef']}"}
    admin_hdr = {"Authorization": f"Bearer {data['tokens']['admin']}"}
    item1_id = data["item1"]["id"]

    # Unauthenticated user cannot create order
    unauth_res = client.post("/orders/", json={
        "restaurant_id": data["rest_id"],
        "fulfillment_type": "pickup",
        "items": [{"menu_item_id": item1_id, "quantity": 1}],
    })
    assert unauth_res.status_code == 401

    # Customer 1 creates an order
    ord_res = client.post("/orders/", json={
        "restaurant_id": data["rest_id"],
        "fulfillment_type": "pickup",
        "items": [{"menu_item_id": item1_id, "quantity": 1}],
    }, headers=c1_hdr)
    assert ord_res.status_code == 200
    order_id = ord_res.json()["id"]

    # Customer 1 CAN view their own order
    c1_view = client.get(f"/orders/{order_id}", headers=c1_hdr)
    assert c1_view.status_code == 200

    # Customer 2 CANNOT view Customer 1's order (BOLA protection)
    c2_view = client.get(f"/orders/{order_id}", headers=c2_hdr)
    assert c2_view.status_code == 403

    # Chef CAN view the order
    chef_view = client.get(f"/orders/{order_id}", headers=chef_hdr)
    assert chef_view.status_code == 200

    # Admin CAN view the order
    admin_view = client.get(f"/orders/{order_id}", headers=admin_hdr)
    assert admin_view.status_code == 200

    # Unauthenticated CANNOT view the order
    unauth_view = client.get(f"/orders/{order_id}")
    assert unauth_view.status_code == 401


def test_status_lifecycle_and_cancellation_stock_restoration(client, setup_restaurant, db_session):
    """Tests the complete status state machine and stock restoration upon cancellation."""
    data = setup_restaurant
    c1_hdr = {"Authorization": f"Bearer {data['tokens']['c1']}"}
    chef_hdr = {"Authorization": f"Bearer {data['tokens']['chef']}"}
    admin_hdr = {"Authorization": f"Bearer {data['tokens']['admin']}"}
    item1_id = data["item1"]["id"]

    # 1. Customer creates order (pending)
    ord_res = client.post("/orders/", json={
        "restaurant_id": data["rest_id"],
        "fulfillment_type": "pickup",
        "items": [{"menu_item_id": item1_id, "quantity": 2}],
    }, headers=c1_hdr)
    assert ord_res.status_code == 200
    oid = ord_res.json()["id"]
    order_num = ord_res.json()["order_number"]

    # Customer cannot advance to preparing or ready
    bad1 = client.patch(f"/orders/{oid}/status", json={"status": "preparing"}, headers=c1_hdr)
    assert bad1.status_code == 403

    bad2 = client.patch(f"/orders/{oid}/status", json={"status": "ready"}, headers=c1_hdr)
    assert bad2.status_code == 403

    # Chef confirms and prepares:
    # confirmed -> preparing
    adv_prep = client.patch(f"/orders/{oid}/status", json={"status": "preparing"}, headers=chef_hdr)
    assert adv_prep.status_code == 200
    assert adv_prep.json()["status"] == "preparing"

    # preparing -> ready
    adv_ready = client.patch(f"/orders/{oid}/status", json={"status": "ready"}, headers=chef_hdr)
    assert adv_ready.status_code == 200
    assert adv_ready.json()["status"] == "ready"

    # ready -> picked_up
    adv_picked = client.patch(f"/orders/{oid}/status", json={"status": "picked_up"}, headers=admin_hdr)
    assert adv_picked.status_code == 200
    assert adv_picked.json()["status"] == "picked_up"

    # Test Cancellation and Stock Restoration:
    # Create another order
    ord2_res = client.post("/orders/", json={
        "restaurant_id": data["rest_id"],
        "fulfillment_type": "pickup",
        "items": [{"menu_item_id": item1_id, "quantity": 3}],
    }, headers=c1_hdr)
    assert ord2_res.status_code == 200
    oid2 = ord2_res.json()["id"]
    ord2_num = ord2_res.json()["order_number"]

    # Stock is decremented
    db_session.expire_all()
    stock_before_cancel = db_session.get(models.MenuItem, item1_id).stock

    # Admin cancels order
    cancel_res = client.patch(f"/orders/{oid2}/status", json={"status": "cancelled"}, headers=admin_hdr)
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "cancelled"

    # Stock is restored (+3)
    db_session.expire_all()
    assert db_session.get(models.MenuItem, item1_id).stock == stock_before_cancel + 3

    # InventoryLog recorded the cancellation
    cancel_logs = db_session.query(models.InventoryLog).filter(
        models.InventoryLog.menu_item_id == item1_id,
        models.InventoryLog.reason == f"order_cancelled:{ord2_num}"
    ).all()
    assert len(cancel_logs) == 1
    assert cancel_logs[0].change == 3
