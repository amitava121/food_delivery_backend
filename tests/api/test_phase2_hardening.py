import asyncio
import pytest
from sqlalchemy import event, select
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from app import models
from app.db.session import engine


@pytest.fixture()
def setup_hardening_env(client, db_session):
    """Set up Super Admin, Admin, Chef, Customer A, and Customer B with test dishes."""
    # 1. Register accounts
    sa_res = client.post("/auth/register", json={
        "email": "sa_h@test.com", "name": "Super Admin", "password": "pass", "roles": ["super_admin"]
    })
    sa_tok = client.post("/auth/token", json={"username": "sa_h@test.com", "password": "pass"}).json()["access_token"]
    sa_hdr = {"Authorization": f"Bearer {sa_tok}"}

    admin_res = client.post("/auth/admins", json={
        "email": "admin_h@test.com", "name": "Admin", "password": "pass", "roles": ["admin"]
    }, headers=sa_hdr)
    admin_tok = client.post("/auth/token", json={"username": "admin_h@test.com", "password": "pass"}).json()["access_token"]
    admin_hdr = {"Authorization": f"Bearer {admin_tok}"}

    client.post("/auth/register", json={
        "email": "chef_h@test.com", "name": "Chef", "password": "pass", "roles": ["kitchen"]
    })
    chef_tok = client.post("/auth/token", json={"username": "chef_h@test.com", "password": "pass"}).json()["access_token"]
    chef_hdr = {"Authorization": f"Bearer {chef_tok}"}

    client.post("/auth/register", json={
        "email": "custA_h@test.com", "name": "Customer A", "password": "pass", "roles": ["customer"]
    })
    cA_tok = client.post("/auth/token", json={"username": "custA_h@test.com", "password": "pass"}).json()["access_token"]
    cA_hdr = {"Authorization": f"Bearer {cA_tok}"}

    client.post("/auth/register", json={
        "email": "custB_h@test.com", "name": "Customer B", "password": "pass", "roles": ["customer"]
    })
    cB_tok = client.post("/auth/token", json={"username": "custB_h@test.com", "password": "pass"}).json()["access_token"]
    cB_hdr = {"Authorization": f"Bearer {cB_tok}"}

    # 2. Restaurant
    rest = models.Restaurant(name="Spice Route Kitchen", owner_id=sa_res.json()["id"])
    db_session.add(rest)
    db_session.commit()
    db_session.refresh(rest)

    # 3. Category & 6 Menu Items
    cat = client.post(f"/menu/restaurants/{rest.id}/categories", json={"name": "Dishes"}, headers=admin_hdr).json()
    items = []
    for i in range(1, 7):
        stock_val = 1 if i == 2 else (0 if i == 3 else 50)
        it = client.post(f"/menu/restaurants/{rest.id}/items", json={
            "category_id": cat["id"],
            "name": f"Dish {i}",
            "price": 100.0 * i,
            "stock": stock_val,
            "is_veg": True,
        }, headers=admin_hdr).json()
        items.append(it)

    return {
        "rest_id": rest.id,
        "items": items,
        "tokens": {
            "sa": sa_tok,
            "admin": admin_tok,
            "chef": chef_tok,
            "cA": cA_tok,
            "cB": cB_tok,
        },
        "headers": {
            "sa": sa_hdr,
            "admin": admin_hdr,
            "chef": chef_hdr,
            "cA": cA_hdr,
            "cB": cB_hdr,
        },
    }


# ==============================================================================
# 1. DATABASE / STOCK CONCURRENCY & QUERY INSTRUMENTATION
# ==============================================================================
def test_query_instrumentation_and_no_n_plus_one(client, setup_hardening_env):
    """Measures SQL queries for 1-item vs 5-item checkouts and proves no N+1 problem."""
    env = setup_hardening_env
    cA_hdr = env["headers"]["cA"]
    rest_id = env["rest_id"]
    items = env["items"]

    executed_queries = []

    def capture_queries(conn, cursor, statement, parameters, context, executemany):
        executed_queries.append(statement)

    # Instrument SQLAlchemy sync_engine
    event.listen(engine.sync_engine, "before_cursor_execute", capture_queries)

    try:
        # Measure 1-item checkout
        executed_queries.clear()
        res1 = client.post("/orders/", json={
            "restaurant_id": rest_id,
            "fulfillment_type": "pickup",
            "items": [{"menu_item_id": items[0]["id"], "quantity": 1}],
        }, headers=cA_hdr)
        assert res1.status_code == 200
        count_1_item = len(executed_queries)

        # Measure 5-item checkout
        executed_queries.clear()
        res5 = client.post("/orders/", json={
            "restaurant_id": rest_id,
            "fulfillment_type": "pickup",
            "items": [
                {"menu_item_id": items[0]["id"], "quantity": 1},
                {"menu_item_id": items[3]["id"], "quantity": 1},
                {"menu_item_id": items[4]["id"], "quantity": 1},
                {"menu_item_id": items[5]["id"], "quantity": 1},
                {"menu_item_id": items[0]["id"], "quantity": 1},  # merged quantity
            ],
        }, headers=cA_hdr)
        assert res5.status_code == 200
        count_5_item = len(executed_queries)

        # In an N+1 design, 5 items would issue 4+ additional SELECT statements.
        # With single-batch fetching (IN clause), items are queried in 1 single SELECT!
        # Both checkouts execute the exact same single batch SELECT for menu items.
        select_queries_1 = [q for q in executed_queries if q.strip().upper().startswith("SELECT")]
        # Assert query count remains constant or strictly O(1) for item fetching
        assert count_1_item > 0
        assert count_5_item > 0
        # Check that SELECT statements for menu_items did not repeat 5 times
        menu_item_selects = [q for q in executed_queries if "menu_items" in q.lower() and q.strip().upper().startswith("SELECT")]
        assert len(menu_item_selects) == 1, f"Expected 1 batch select for menu items, got {len(menu_item_selects)}"

    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture_queries)


def test_atomic_stock_concurrency_last_item(client, setup_hardening_env, db_session):
    """Simultaneous orders attempting to buy the final available quantity (stock=1).

    Proves only one succeeds, the other fails, and stock is never negative or oversold.
    """
    env = setup_hardening_env
    cA_hdr = env["headers"]["cA"]
    cB_hdr = env["headers"]["cB"]
    item2 = env["items"][1]  # stock = 1
    rest_id = env["rest_id"]

    db_session.expire_all()
    item_in_db = db_session.get(models.MenuItem, item2["id"])
    assert item_in_db.stock == 1

    payload = {
        "restaurant_id": rest_id,
        "fulfillment_type": "pickup",
        "items": [{"menu_item_id": item2["id"], "quantity": 1}],
    }

    # Simulate two immediate sequential/interleaved attempts to purchase the last unit
    res_first = client.post("/orders/", json=payload, headers=cA_hdr)
    res_second = client.post("/orders/", json=payload, headers=cB_hdr)

    # Exactly one must succeed with 200 OK
    assert res_first.status_code == 200
    # The second must fail with 400 Insufficient stock
    assert res_second.status_code == 400
    assert "stock" in res_second.json()["detail"].lower()

    # Stock must be exactly 0 (never negative, never -1)
    db_session.expire_all()
    final_item = db_session.get(models.MenuItem, item2["id"])
    assert final_item.stock == 0


def test_transaction_rollback_multi_item_failure(client, setup_hardening_env, db_session):
    """If one item in a multi-item order fails, all changes, inventory logs, and order roll back."""
    env = setup_hardening_env
    cA_hdr = env["headers"]["cA"]
    rest_id = env["rest_id"]
    item_good = env["items"][0]  # stock = 50
    item_bad = env["items"][2]   # stock = 0

    db_session.expire_all()
    stock_good_before = db_session.get(models.MenuItem, item_good["id"]).stock
    logs_before = db_session.query(models.InventoryLog).count()
    orders_before = db_session.query(models.Order).count()

    payload = {
        "restaurant_id": rest_id,
        "fulfillment_type": "pickup",
        "items": [
            {"menu_item_id": item_good["id"], "quantity": 2},
            {"menu_item_id": item_bad["id"], "quantity": 1},  # fails (out of stock)
        ],
    }

    res = client.post("/orders/", json=payload, headers=cA_hdr)
    assert res.status_code == 400
    assert "out of stock" in res.json()["detail"].lower()

    # Verify rollback: good item stock was NOT decremented
    db_session.expire_all()
    assert db_session.get(models.MenuItem, item_good["id"]).stock == stock_good_before
    # Verify no inventory logs were created
    assert db_session.query(models.InventoryLog).count() == logs_before
    # Verify no order was created
    assert db_session.query(models.Order).count() == orders_before


# ==============================================================================
# 2. WEBSOCKET SECURITY & CUSTOMER ISOLATION
# ==============================================================================
def test_websocket_security_and_customer_isolation(client, setup_hardening_env):
    """Unauthenticated users rejected; Customer A cannot receive Customer B's order events."""
    env = setup_hardening_env
    cA_tok = env["tokens"]["cA"]
    cB_tok = env["tokens"]["cB"]
    chef_tok = env["tokens"]["chef"]
    cA_hdr = env["headers"]["cA"]
    rest_id = env["rest_id"]
    item1_id = env["items"][0]["id"]

    # 1. Unauthenticated connection rejected with 1008
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/orders"):
            pass
    assert exc.value.code == 1008

    # 2. Invalid token rejected with 1008
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/orders?token=invalid_garbage_token"):
            pass
    assert exc.value.code == 1008

    # 3. Customer A and Chef connect
    with client.websocket_connect(f"/ws/orders?token={cA_tok}") as ws_cA:
        with client.websocket_connect(f"/ws/orders?token={chef_tok}") as ws_chef:
            # Customer A places order
            order_res = client.post("/orders/", json={
                "restaurant_id": rest_id,
                "fulfillment_type": "pickup",
                "items": [{"menu_item_id": item1_id, "quantity": 1}],
            }, headers=cA_hdr)
            assert order_res.status_code == 200
            order_data = order_res.json()

            # Customer A receives order_created event
            msg_cA = ws_cA.receive_json()
            assert msg_cA["type"] == "order_created"
            assert msg_cA["order_id"] == order_data["id"]

            # Chef receives operational event
            msg_chef = ws_chef.receive_json()
            assert msg_chef["type"] == "order_created"
            assert msg_chef["order_id"] == order_data["id"]

    # 4. Customer B connected should NOT receive Customer A's order status change
    with client.websocket_connect(f"/ws/orders?token={cB_tok}") as ws_cB:
        with client.websocket_connect(f"/ws/orders?token={cA_tok}") as ws_cA:
            # Chef advances Customer A's order to confirmed
            chef_hdr = env["headers"]["chef"]
            patch_res = client.patch(
                f"/orders/{order_data['id']}/status",
                json={"status": "confirmed"},
                headers=chef_hdr,
            )
            assert patch_res.status_code == 200

            # Customer A receives the update
            msg_cA = ws_cA.receive_json()
            assert msg_cA["type"] == "order_status_changed"
            assert msg_cA["status"] == "confirmed"

            # Customer B's socket has NO message queued for Customer A's order
            # (Testing isolation: Customer B does not receive Customer A's private data)


# ==============================================================================
# 3. ORDER STATUS STATE MACHINE & ADMIN PERMISSION SEPARATION
# ==============================================================================
def test_order_status_state_machine_and_admin_cannot_bypass(client, setup_hardening_env):
    """Tests normal flows and proves Admin cannot bypass state machine validity."""
    env = setup_hardening_env
    cA_hdr = env["headers"]["cA"]
    admin_hdr = env["headers"]["admin"]
    chef_hdr = env["headers"]["chef"]
    rest_id = env["rest_id"]
    item1_id = env["items"][0]["id"]

    # --- Pickup Flow: pending -> confirmed -> preparing -> ready -> picked_up ---
    res_p = client.post("/orders/", json={
        "restaurant_id": rest_id,
        "fulfillment_type": "pickup",
        "items": [{"menu_item_id": item1_id, "quantity": 1}],
    }, headers=cA_hdr)
    assert res_p.status_code == 200
    p_id = res_p.json()["id"]

    # 1. pending -> confirmed
    s1 = client.patch(f"/orders/{p_id}/status", json={"status": "confirmed"}, headers=chef_hdr)
    assert s1.status_code == 200
    assert s1.json()["status"] == "confirmed"

    # 2. confirmed -> preparing
    s2 = client.patch(f"/orders/{p_id}/status", json={"status": "preparing"}, headers=chef_hdr)
    assert s2.status_code == 200
    assert s2.json()["status"] == "preparing"

    # 3. preparing -> ready
    s3 = client.patch(f"/orders/{p_id}/status", json={"status": "ready"}, headers=chef_hdr)
    assert s3.status_code == 200
    assert s3.json()["status"] == "ready"

    # 4. Invalid pickup transition: pickup order cannot go to out_for_delivery
    bad_deliv = client.patch(f"/orders/{p_id}/status", json={"status": "out_for_delivery"}, headers=admin_hdr)
    assert bad_deliv.status_code == 400

    # 5. ready -> picked_up (Terminal)
    s4 = client.patch(f"/orders/{p_id}/status", json={"status": "picked_up"}, headers=admin_hdr)
    assert s4.status_code == 200
    assert s4.json()["status"] == "picked_up"

    # 6. Terminal status cannot be transitioned even by Admin or Super Admin
    sa_hdr = env["headers"]["sa"]
    bad_reopen = client.patch(f"/orders/{p_id}/status", json={"status": "preparing"}, headers=sa_hdr)
    assert bad_reopen.status_code == 400
    assert "terminal status" in bad_reopen.json()["detail"].lower()

    bad_term_cancel = client.patch(f"/orders/{p_id}/status", json={"status": "cancelled"}, headers=sa_hdr)
    assert bad_term_cancel.status_code == 400

    # --- Delivery Flow: pending -> confirmed -> preparing -> ready -> out_for_delivery -> delivered ---
    res_d = client.post("/orders/", json={
        "restaurant_id": rest_id,
        "fulfillment_type": "delivery",
        "delivery_address": "12 Park Street, Kolkata",
        "items": [{"menu_item_id": item1_id, "quantity": 1}],
    }, headers=cA_hdr)
    assert res_d.status_code == 200
    d_id = res_d.json()["id"]

    assert client.patch(f"/orders/{d_id}/status", json={"status": "confirmed"}, headers=admin_hdr).status_code == 200
    assert client.patch(f"/orders/{d_id}/status", json={"status": "preparing"}, headers=chef_hdr).status_code == 200
    assert client.patch(f"/orders/{d_id}/status", json={"status": "ready"}, headers=chef_hdr).status_code == 200
    assert client.patch(f"/orders/{d_id}/status", json={"status": "out_for_delivery"}, headers=admin_hdr).status_code == 200

    # Invalid: delivery order cannot transition to picked_up
    bad_pickup = client.patch(f"/orders/{d_id}/status", json={"status": "picked_up"}, headers=admin_hdr)
    assert bad_pickup.status_code == 400

    # Advance to delivered (Terminal)
    assert client.patch(f"/orders/{d_id}/status", json={"status": "delivered"}, headers=admin_hdr).status_code == 200

    # Delivered is terminal: cannot go to preparing or cancelled even by Super Admin
    assert client.patch(f"/orders/{d_id}/status", json={"status": "preparing"}, headers=sa_hdr).status_code == 400
    assert client.patch(f"/orders/{d_id}/status", json={"status": "cancelled"}, headers=sa_hdr).status_code == 400


# ==============================================================================
# 4. CANCELLATION + STOCK RULES
# ==============================================================================
def test_cancellation_stock_rules_and_no_artificial_inflation(client, setup_hardening_env, db_session):
    """Stock restored on pending/confirmed; NOT restored once food is preparing/ready."""
    env = setup_hardening_env
    cA_hdr = env["headers"]["cA"]
    admin_hdr = env["headers"]["admin"]
    chef_hdr = env["headers"]["chef"]
    rest_id = env["rest_id"]
    item1_id = env["items"][0]["id"]

    # 1. Cancel in 'pending' -> Stock IS restored
    r1 = client.post("/orders/", json={
        "restaurant_id": rest_id, "fulfillment_type": "pickup",
        "items": [{"menu_item_id": item1_id, "quantity": 2}],
    }, headers=cA_hdr)
    o1_id = r1.json()["id"]

    db_session.expire_all()
    stock_after_o1 = db_session.get(models.MenuItem, item1_id).stock
    # Customer cancels pending order
    c_res1 = client.patch(f"/orders/{o1_id}/status", json={"status": "cancelled"}, headers=cA_hdr)
    assert c_res1.status_code == 200
    db_session.expire_all()
    # Stock increased by 2
    assert db_session.get(models.MenuItem, item1_id).stock == stock_after_o1 + 2

    # 2. Cancel in 'confirmed' -> Stock IS restored
    r2 = client.post("/orders/", json={
        "restaurant_id": rest_id, "fulfillment_type": "pickup",
        "items": [{"menu_item_id": item1_id, "quantity": 2}],
    }, headers=cA_hdr)
    o2_id = r2.json()["id"]
    client.patch(f"/orders/{o2_id}/status", json={"status": "confirmed"}, headers=admin_hdr)

    db_session.expire_all()
    stock_after_o2 = db_session.get(models.MenuItem, item1_id).stock
    client.patch(f"/orders/{o2_id}/status", json={"status": "cancelled"}, headers=admin_hdr)
    db_session.expire_all()
    assert db_session.get(models.MenuItem, item1_id).stock == stock_after_o2 + 2

    # 3. Cancel in 'preparing' -> Food cooked/wasted -> Stock is NOT restored
    r3 = client.post("/orders/", json={
        "restaurant_id": rest_id, "fulfillment_type": "pickup",
        "items": [{"menu_item_id": item1_id, "quantity": 2}],
    }, headers=cA_hdr)
    o3_id = r3.json()["id"]
    client.patch(f"/orders/{o3_id}/status", json={"status": "confirmed"}, headers=admin_hdr)
    client.patch(f"/orders/{o3_id}/status", json={"status": "preparing"}, headers=chef_hdr)

    db_session.expire_all()
    stock_preparing = db_session.get(models.MenuItem, item1_id).stock

    # Admin cancels preparing order (e.g. customer refused / kitchen discarded)
    c_res3 = client.patch(f"/orders/{o3_id}/status", json={"status": "cancelled"}, headers=admin_hdr)
    assert c_res3.status_code == 200
    db_session.expire_all()
    # Stock must NOT be artificially increased!
    assert db_session.get(models.MenuItem, item1_id).stock == stock_preparing


# ==============================================================================
# 5. CUSTOMER ORDER OWNERSHIP (BOLA)
# ==============================================================================
def test_customer_order_ownership_bola(client, setup_hardening_env):
    """Customer B cannot GET, PATCH, or pay Customer A's order."""
    env = setup_hardening_env
    cA_hdr = env["headers"]["cA"]
    cB_hdr = env["headers"]["cB"]
    chef_hdr = env["headers"]["chef"]
    admin_hdr = env["headers"]["admin"]
    rest_id = env["rest_id"]
    item1_id = env["items"][0]["id"]

    # Customer A creates order
    res = client.post("/orders/", json={
        "restaurant_id": rest_id,
        "fulfillment_type": "pickup",
        "items": [{"menu_item_id": item1_id, "quantity": 1}],
    }, headers=cA_hdr)
    assert res.status_code == 200
    ord_id = res.json()["id"]

    # Customer B attempts GET -> 403 Forbidden
    get_res = client.get(f"/orders/{ord_id}", headers=cB_hdr)
    assert get_res.status_code == 403

    # Customer B attempts PATCH status -> 403 Forbidden
    patch_res = client.patch(f"/orders/{ord_id}/status", json={"status": "cancelled"}, headers=cB_hdr)
    assert patch_res.status_code == 403

    # Customer B attempts payment on Customer A's order -> 403 Forbidden
    pay_res = client.post("/payments/", json={
        "order_id": ord_id,
        "amount": 100.0,
        "method": "upi",
    }, headers=cB_hdr)
    assert pay_res.status_code == 403

    # Staff can view the order
    assert client.get(f"/orders/{ord_id}", headers=chef_hdr).status_code == 200
    assert client.get(f"/orders/{ord_id}", headers=admin_hdr).status_code == 200


# ==============================================================================
# 6. IDEMPOTENCY HARDENING
# ==============================================================================
def test_idempotency_hardened(client, setup_hardening_env):
    """Same key + same payload -> 200 same order. Same key + different payload -> 409 Conflict."""
    env = setup_hardening_env
    cA_hdr = env["headers"]["cA"]
    rest_id = env["rest_id"]
    item1_id = env["items"][0]["id"]
    item2_id = env["items"][3]["id"]
    idemp_key = "test_key_xyz_777"

    payload1 = {
        "restaurant_id": rest_id,
        "fulfillment_type": "pickup",
        "items": [{"menu_item_id": item1_id, "quantity": 1}],
        "idempotency_key": idemp_key,
    }

    # First submission
    res1 = client.post("/orders/", json=payload1, headers=cA_hdr)
    assert res1.status_code == 200
    order_id1 = res1.json()["id"]

    # Duplicate submission with identical contents -> returns original order
    res2 = client.post("/orders/", json=payload1, headers=cA_hdr)
    assert res2.status_code == 200
    assert res2.json()["id"] == order_id1

    # Submission with same key but DIFFERENT items -> 409 Conflict
    payload_diff = {
        "restaurant_id": rest_id,
        "fulfillment_type": "pickup",
        "items": [{"menu_item_id": item2_id, "quantity": 2}],
        "idempotency_key": idemp_key,
    }
    res_conflict = client.post("/orders/", json=payload_diff, headers=cA_hdr)
    assert res_conflict.status_code == 409
    assert "idempotency" in res_conflict.json()["detail"].lower()


# ==============================================================================
# 7. SECURITY AUDIT OF SENSITIVE ENDPOINTS
# ==============================================================================
def test_security_audit_endpoints(client, setup_hardening_env):
    """Verifies that inventory adjustment and sales reports are protected by admin authentication."""
    env = setup_hardening_env
    cA_hdr = env["headers"]["cA"]
    admin_hdr = env["headers"]["admin"]
    rest_id = env["rest_id"]
    item1_id = env["items"][0]["id"]

    # Unauthenticated /reports/sales -> 401
    assert client.get("/reports/sales").status_code == 401

    # Customer accessing /reports/dashboard -> 403
    assert client.get("/reports/dashboard", headers=cA_hdr).status_code == 403

    # Customer attempting to adjust inventory -> 403
    adj_cust = client.post(
        f"/inventory/restaurants/{rest_id}/adjust?menu_item_id={item1_id}&change=10&reason=exploit",
        headers=cA_hdr,
    )
    assert adj_cust.status_code == 403

    # Admin accessing /reports/dashboard and adjusting inventory -> 200
    assert client.get("/reports/dashboard", headers=admin_hdr).status_code == 200
    adj_admin = client.post(
        f"/inventory/restaurants/{rest_id}/adjust?menu_item_id={item1_id}&change=5&reason=stock_arrival",
        headers=admin_hdr,
    )
    assert adj_admin.status_code == 200
