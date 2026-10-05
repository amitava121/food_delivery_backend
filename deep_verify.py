import httpx
import json
import sqlite3
import subprocess
import sys

BASE_URL = "http://127.0.0.1:8000"

def get_db_user(email: str):
    conn = sqlite3.connect("qr_orders.db")
    c = conn.cursor()
    c.execute("SELECT id, email, name, roles, is_blocked FROM users WHERE email = ?", (email,))
    row = c.fetchone()
    conn.close()
    return row

def get_db_counts():
    conn = sqlite3.connect("qr_orders.db")
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM menu_items")
    items = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM menu_categories")
    cats = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM banners")
    banners = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users")
    users = c.fetchone()[0]
    conn.close()
    return {"items": items, "cats": cats, "banners": banners, "users": users}

def test_assert(cond, msg):
    if not cond:
        print(f"FAILED: {msg}")
        sys.exit(1)
    else:
        print(f"PASS: {msg}")

def main():
    client = httpx.Client(base_url=BASE_URL, timeout=10.0)
    print("============================================================")
    print("STARTING DEEP VERIFICATION AND HARDENING TEST PASS")
    print("============================================================\n")

    # 1. SETUP AUTH TOKENS
    sa_res = client.post("/auth/token", json={"username": "owner@demo.com", "password": "demo123"})
    test_assert(sa_res.status_code == 200, "Super Admin login")
    sa_token = sa_res.json()["access_token"]
    sa_hdr = {"Authorization": f"Bearer {sa_token}"}

    admin_res = client.post("/auth/token", json={"username": "admin@demo.com", "password": "demo123"})
    test_assert(admin_res.status_code == 200, "Normal Admin login")
    admin_token = admin_res.json()["access_token"]
    admin_hdr = {"Authorization": f"Bearer {admin_token}"}

    chef_res = client.post("/auth/token", json={"username": "chef@demo.com", "password": "demo123"})
    test_assert(chef_res.status_code == 200, "Chef login")
    chef_token = chef_res.json()["access_token"]
    chef_hdr = {"Authorization": f"Bearer {chef_token}"}

    cust_res = client.post("/auth/token", json={"username": "customer@demo.com", "password": "demo123"})
    test_assert(cust_res.status_code == 200, "Customer login")
    cust_token = cust_res.json()["access_token"]
    cust_hdr = {"Authorization": f"Bearer {cust_token}"}

    sa_info = client.get("/auth/me", headers=sa_hdr).json()
    sa_id = sa_info["id"]
    admin_info = client.get("/auth/me", headers=admin_hdr).json()
    admin_id = admin_info["id"]

    # -------------------------------------------------------------
    # SECTION 3: VERIFY USER MANAGEMENT (GET /auth/users)
    # -------------------------------------------------------------
    print("\n--- SECTION 3: GET /auth/users ---")
    # Super Admin
    r = client.get("/auth/users", headers=sa_hdr)
    test_assert(r.status_code == 200, "Super Admin GET /auth/users returns 200")
    for u in r.json():
        test_assert("admin" not in u["roles"] and "super_admin" not in u["roles"], 
                    f"Super Admin users list excludes admin/super_admin: {u['email']}")

    # Normal Admin
    r = client.get("/auth/users", headers=admin_hdr)
    test_assert(r.status_code == 200, "Admin GET /auth/users returns 200")
    for u in r.json():
        test_assert("admin" not in u["roles"] and "super_admin" not in u["roles"], 
                    f"Admin users list excludes admin/super_admin: {u['email']}")

    # Kitchen
    r = client.get("/auth/users", headers=chef_hdr)
    test_assert(r.status_code == 403, "Kitchen GET /auth/users returns 403")

    # Customer
    r = client.get("/auth/users", headers=cust_hdr)
    test_assert(r.status_code == 403, "Customer GET /auth/users returns 403")

    # Unauthenticated
    r = client.get("/auth/users")
    test_assert(r.status_code == 401, "Unauthenticated GET /auth/users returns 401")

    # -------------------------------------------------------------
    # SECTION 4: VERIFY USER CREATION (POST /auth/users & POST /auth/register)
    # -------------------------------------------------------------
    print("\n--- SECTION 4: POST /auth/users & POST /auth/register ---")
    # A. roles=["customer"] via Admin -> 201
    r = client.post("/auth/users", json={
        "email": "test_cust_create@demo.com", "name": "Created Cust", "password": "pass", "roles": ["customer"]
    }, headers=admin_hdr)
    test_assert(r.status_code == 201, "Normal Admin can create customer")
    temp_cust_id = r.json()["id"]

    # B. roles=["kitchen"] via Admin -> 201
    r = client.post("/auth/users", json={
        "email": "test_chef_create@demo.com", "name": "Created Chef", "password": "pass", "roles": ["kitchen"]
    }, headers=admin_hdr)
    test_assert(r.status_code == 201, "Normal Admin can create kitchen user")
    temp_chef_id = r.json()["id"]

    # C. roles=["admin"] via Admin -> 403
    r = client.post("/auth/users", json={
        "email": "test_admin_forbidden@demo.com", "name": "Forbid Admin", "password": "pass", "roles": ["admin"]
    }, headers=admin_hdr)
    test_assert(r.status_code == 403, "Normal Admin CANNOT create admin on /auth/users (403)")
    test_assert(get_db_user("test_admin_forbidden@demo.com") is None, "DB verify: test_admin_forbidden was NOT created")

    # D. roles=["super_admin"] via Admin -> 403
    r = client.post("/auth/users", json={
        "email": "test_sa_forbidden@demo.com", "name": "Forbid SA", "password": "pass", "roles": ["super_admin"]
    }, headers=admin_hdr)
    test_assert(r.status_code == 403, "Normal Admin CANNOT create super_admin on /auth/users (403)")
    test_assert(get_db_user("test_sa_forbidden@demo.com") is None, "DB verify: test_sa_forbidden was NOT created")

    # Super Admin calling POST /auth/users with admin role must use /auth/admins
    r = client.post("/auth/users", json={
        "email": "test_sa_via_users@demo.com", "name": "SA via Users", "password": "pass", "roles": ["admin"]
    }, headers=sa_hdr)
    test_assert(r.status_code == 403, "Super Admin creating admin must use /auth/admins, not /auth/users (403)")

    # Kitchen cannot create users
    r = client.post("/auth/users", json={
        "email": "chef_create_test@demo.com", "name": "Chef Create", "password": "pass", "roles": ["customer"]
    }, headers=chef_hdr)
    test_assert(r.status_code == 403, "Kitchen cannot create users (403)")

    # Customer cannot create users
    r = client.post("/auth/users", json={
        "email": "cust_create_test@demo.com", "name": "Cust Create", "password": "pass", "roles": ["customer"]
    }, headers=cust_hdr)
    test_assert(r.status_code == 403, "Customer cannot create users (403)")

    # Unauthenticated cannot create users
    r = client.post("/auth/users", json={
        "email": "anon_create_test@demo.com", "name": "Anon Create", "password": "pass", "roles": ["customer"]
    })
    test_assert(r.status_code == 401, "Unauthenticated cannot create users (401)")

    # Public registration security gap test: unauthenticated attempt to register as admin or super_admin
    r = client.post("/auth/register", json={
        "email": "public_exploit_admin@demo.com", "name": "Exploiter", "password": "pass", "roles": ["admin"]
    })
    test_assert(r.status_code == 403, "Public /auth/register with roles=['admin'] is BLOCKED (403)")
    test_assert(get_db_user("public_exploit_admin@demo.com") is None, "DB verify: public_exploit_admin was NOT created")

    r = client.post("/auth/register", json={
        "email": "public_exploit_sa@demo.com", "name": "Exploiter SA", "password": "pass", "roles": ["super_admin"]
    })
    test_assert(r.status_code == 403, "Public /auth/register with roles=['super_admin'] is BLOCKED (403)")
    test_assert(get_db_user("public_exploit_sa@demo.com") is None, "DB verify: public_exploit_sa was NOT created")

    # -------------------------------------------------------------
    # SECTION 5: VERIFY USER ROLE EDITING (All 12 Transitions on /auth/users/{id})
    # -------------------------------------------------------------
    print("\n--- SECTION 5: PATCH /auth/users/{id} Role Transitions ---")
    # Transitions tested with Normal Admin:
    # 1. customer -> customer
    r = client.patch(f"/auth/users/{temp_cust_id}", json={"roles": ["customer"]}, headers=admin_hdr)
    test_assert(r.status_code == 200, "Admin: customer -> customer allowed (200)")

    # 2. customer -> kitchen
    r = client.patch(f"/auth/users/{temp_cust_id}", json={"roles": ["kitchen"]}, headers=admin_hdr)
    test_assert(r.status_code == 200, "Admin: customer -> kitchen allowed (200)")

    # 3. kitchen -> customer
    r = client.patch(f"/auth/users/{temp_cust_id}", json={"roles": ["customer"]}, headers=admin_hdr)
    test_assert(r.status_code == 200, "Admin: kitchen -> customer allowed (200)")

    # 4. customer -> admin -> 403
    r = client.patch(f"/auth/users/{temp_cust_id}", json={"roles": ["admin"]}, headers=admin_hdr)
    test_assert(r.status_code == 403, "Admin: customer -> admin FORBIDDEN (403)")
    test_assert("admin" not in get_db_user("test_cust_create@demo.com")[3], "DB verify: role remains customer")

    # 5. customer -> super_admin -> 403
    r = client.patch(f"/auth/users/{temp_cust_id}", json={"roles": ["super_admin"]}, headers=admin_hdr)
    test_assert(r.status_code == 403, "Admin: customer -> super_admin FORBIDDEN (403)")
    test_assert("super_admin" not in get_db_user("test_cust_create@demo.com")[3], "DB verify: role remains customer")

    # 6. kitchen -> admin -> 403
    r = client.patch(f"/auth/users/{temp_chef_id}", json={"roles": ["admin"]}, headers=admin_hdr)
    test_assert(r.status_code == 403, "Admin: kitchen -> admin FORBIDDEN (403)")
    test_assert("admin" not in get_db_user("test_chef_create@demo.com")[3], "DB verify: role remains kitchen")

    # 7. kitchen -> super_admin -> 403
    r = client.patch(f"/auth/users/{temp_chef_id}", json={"roles": ["super_admin"]}, headers=admin_hdr)
    test_assert(r.status_code == 403, "Admin: kitchen -> super_admin FORBIDDEN (403)")
    test_assert("super_admin" not in get_db_user("test_chef_create@demo.com")[3], "DB verify: role remains kitchen")

    # 8. admin -> customer (target is admin) -> 403
    r = client.patch(f"/auth/users/{admin_id}", json={"roles": ["customer"]}, headers=admin_hdr)
    test_assert(r.status_code == 403, "Admin: admin -> customer FORBIDDEN (403)")
    test_assert("admin" in get_db_user("admin@demo.com")[3], "DB verify: role remains admin")

    # 9. admin -> kitchen -> 403
    r = client.patch(f"/auth/users/{admin_id}", json={"roles": ["kitchen"]}, headers=admin_hdr)
    test_assert(r.status_code == 403, "Admin: admin -> kitchen FORBIDDEN (403)")

    # 10. admin -> super_admin -> 403
    r = client.patch(f"/auth/users/{admin_id}", json={"roles": ["super_admin"]}, headers=admin_hdr)
    test_assert(r.status_code == 403, "Admin: admin -> super_admin FORBIDDEN (403)")

    # 11. super_admin -> admin -> 403
    r = client.patch(f"/auth/users/{sa_id}", json={"roles": ["admin"]}, headers=admin_hdr)
    test_assert(r.status_code == 403, "Admin: super_admin -> admin FORBIDDEN (403)")

    # 12. super_admin -> customer -> 403
    r = client.patch(f"/auth/users/{sa_id}", json={"roles": ["customer"]}, headers=admin_hdr)
    test_assert(r.status_code == 403, "Admin: super_admin -> customer FORBIDDEN (403)")

    # Clean up temporary normal users created for test
    client.delete(f"/auth/users/{temp_cust_id}", headers=admin_hdr)
    client.delete(f"/auth/users/{temp_chef_id}", headers=admin_hdr)

    # -------------------------------------------------------------
    # SECTION 6: VERIFY ADMIN MANAGEMENT (GET/POST/PATCH/DELETE /auth/admins)
    # -------------------------------------------------------------
    print("\n--- SECTION 6: /auth/admins RBAC ---")
    # Super Admin -> 200
    r = client.get("/auth/admins", headers=sa_hdr)
    test_assert(r.status_code == 200, "Super Admin: GET /auth/admins allowed (200)")

    # Normal Admin -> 403
    r = client.get("/auth/admins", headers=admin_hdr)
    test_assert(r.status_code == 403, "Admin: GET /auth/admins FORBIDDEN (403)")

    # Kitchen -> 403
    r = client.get("/auth/admins", headers=chef_hdr)
    test_assert(r.status_code == 403, "Kitchen: GET /auth/admins FORBIDDEN (403)")

    # Customer -> 403
    r = client.get("/auth/admins", headers=cust_hdr)
    test_assert(r.status_code == 403, "Customer: GET /auth/admins FORBIDDEN (403)")

    # Unauthenticated -> 401
    r = client.get("/auth/admins")
    test_assert(r.status_code == 401, "Unauthenticated: GET /auth/admins UNAUTHORIZED (401)")

    # -------------------------------------------------------------
    # SECTION 7: VERIFY SUPER ADMIN PROTECTION
    # -------------------------------------------------------------
    print("\n--- SECTION 7: Super Admin Protection ---")
    # 1. Super Admin deletes self -> 400
    r = client.delete(f"/auth/admins/{sa_id}", headers=sa_hdr)
    test_assert(r.status_code == 400, "Super Admin deletes self: REJECTED (400)")
    test_assert(get_db_user("owner@demo.com") is not None, "DB verify: owner still exists")

    # 2. Super Admin demotes self (only SA) -> 400
    r = client.patch(f"/auth/admins/{sa_id}", json={"roles": ["admin"]}, headers=sa_hdr)
    test_assert(r.status_code == 400, "Super Admin demotes last Super Admin: REJECTED (400)")
    test_assert("super_admin" in get_db_user("owner@demo.com")[3], "DB verify: owner remains super_admin")

    # 3. Normal Admin deletes Super Admin -> 403
    r = client.delete(f"/auth/admins/{sa_id}", headers=admin_hdr)
    test_assert(r.status_code == 403, "Normal Admin deletes Super Admin: FORBIDDEN (403)")
    test_assert(get_db_user("owner@demo.com") is not None, "DB verify: owner still exists")

    # 4. Normal Admin demotes Super Admin -> 403
    r = client.patch(f"/auth/admins/{sa_id}", json={"roles": ["admin"]}, headers=admin_hdr)
    test_assert(r.status_code == 403, "Normal Admin demotes Super Admin: FORBIDDEN (403)")

    # 5. Normal Admin blocks Super Admin via /auth/users or /auth/admins -> 403
    r1 = client.patch(f"/auth/users/{sa_id}", json={"is_blocked": True}, headers=admin_hdr)
    test_assert(r1.status_code == 403, "Normal Admin blocks Super Admin via /auth/users: FORBIDDEN (403)")
    r2 = client.patch(f"/auth/admins/{sa_id}", json={"is_blocked": True}, headers=admin_hdr)
    test_assert(r2.status_code == 403, "Normal Admin blocks Super Admin via /auth/admins: FORBIDDEN (403)")
    test_assert(get_db_user("owner@demo.com")[4] == 0, "DB verify: owner is NOT blocked")

    # 6. Super Admin blocks last Super Admin -> 400
    r = client.patch(f"/auth/admins/{sa_id}", json={"is_blocked": True}, headers=sa_hdr)
    test_assert(r.status_code == 400, "Super Admin blocks only Super Admin: REJECTED (400)")
    test_assert(get_db_user("owner@demo.com")[4] == 0, "DB verify: owner is NOT blocked")

    # 7. Super Admin creates Admin -> 201
    r = client.post("/auth/admins", json={
        "email": "temp_admin_test@demo.com", "name": "Temp Admin", "password": "pass", "roles": ["admin"]
    }, headers=sa_hdr)
    test_assert(r.status_code == 201, "Super Admin creates Admin: SUCCESS (201)")
    temp_admin_id = r.json()["id"]

    # 8. Super Admin edits Admin -> 200
    r = client.patch(f"/auth/admins/{temp_admin_id}", json={"name": "Temp Admin Renamed"}, headers=sa_hdr)
    test_assert(r.status_code == 200 and r.json()["name"] == "Temp Admin Renamed", "Super Admin edits Admin name: SUCCESS (200)")

    # 9. Super Admin blocks Admin -> 200
    r = client.patch(f"/auth/admins/{temp_admin_id}", json={"is_blocked": True}, headers=sa_hdr)
    test_assert(r.status_code == 200 and r.json()["is_blocked"] is True, "Super Admin blocks Admin: SUCCESS (200)")
    test_assert(get_db_user("temp_admin_test@demo.com")[4] == 1, "DB verify: temp admin is blocked")

    # 10. Super Admin unblocks Admin -> 200
    r = client.patch(f"/auth/admins/{temp_admin_id}", json={"is_blocked": False}, headers=sa_hdr)
    test_assert(r.status_code == 200 and r.json()["is_blocked"] is False, "Super Admin unblocks Admin: SUCCESS (200)")
    test_assert(get_db_user("temp_admin_test@demo.com")[4] == 0, "DB verify: temp admin is unblocked")

    # Clean up temp admin
    r = client.delete(f"/auth/admins/{temp_admin_id}", headers=sa_hdr)
    test_assert(r.status_code == 204, "Super Admin deletes Admin: SUCCESS (204)")
    test_assert(get_db_user("temp_admin_test@demo.com") is None, "DB verify: temp admin deleted")

    # -------------------------------------------------------------
    # SECTION 12: VERIFY DATABASE SAFETY & MIGRATION IDEMPOTENCY
    # -------------------------------------------------------------
    print("\n--- SECTION 12: Database Safety & Idempotent Migration ---")
    before_counts = get_db_counts()
    print(f"Pre-migration counts: {before_counts}")

    run1 = subprocess.run([sys.executable, "seed.py"], capture_output=True, text=True)
    test_assert(run1.returncode == 0, f"Seed run 1 exit code 0: {run1.stderr}")

    run2 = subprocess.run([sys.executable, "seed.py"], capture_output=True, text=True)
    test_assert(run2.returncode == 0, f"Seed run 2 exit code 0: {run2.stderr}")

    after_counts = get_db_counts()
    print(f"Post-migration counts: {after_counts}")
    test_assert(before_counts["items"] == after_counts["items"], "Menu items count unchanged")
    test_assert(before_counts["cats"] == after_counts["cats"], "Menu categories count unchanged")
    test_assert(before_counts["banners"] == after_counts["banners"], "Banners count unchanged")
    test_assert(before_counts["users"] == after_counts["users"], "Users count unchanged")

    # -------------------------------------------------------------
    # SECTION 14: AUTHENTICATION INTEGRITY
    # -------------------------------------------------------------
    print("\n--- SECTION 14: Authentication Integrity ---")
    for email, role_chk in [
        ("owner@demo.com", "super_admin"),
        ("admin@demo.com", "admin"),
        ("chef@demo.com", "kitchen"),
        ("customer@demo.com", "customer"),
    ]:
        lr = client.post("/auth/token", json={"username": email, "password": "demo123"})
        test_assert(lr.status_code == 200, f"Login functional for {email}")
        mr = client.get("/auth/me", headers={"Authorization": f"Bearer {lr.json()['access_token']}"})
        test_assert(mr.status_code == 200 and role_chk in mr.json()["roles"], f"Role {role_chk} verified for {email}")

    print("\n============================================================")
    print("ALL DEEP VERIFICATION AND HARDENING TESTS PASSED 100%!")
    print("============================================================\n")

if __name__ == "__main__":
    main()
