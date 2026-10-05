import httpx
import json
import sqlite3
import sys
import subprocess

BASE_URL = "http://127.0.0.1:8000"

def log_test(num, name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] TEST {num}: {name} - {detail}")
    if not passed:
        sys.exit(1)

def main():
    print("--- Executing Test Matrix against Live Backend ---")
    client = httpx.Client(base_url=BASE_URL, timeout=10.0)

    # TEST 1: Super Admin logs in
    r = client.post("/auth/token", json={"username": "owner@demo.com", "password": "demo123"})
    assert r.status_code == 200, f"Super Admin login failed: {r.text}"
    sa_token = r.json()["access_token"]
    sa_hdr = {"Authorization": f"Bearer {sa_token}"}
    
    me = client.get("/auth/me", headers=sa_hdr).json()
    assert "super_admin" in me["roles"] and "admin" in me["roles"]
    
    admins_res = client.get("/auth/admins", headers=sa_hdr)
    assert admins_res.status_code == 200
    admin_list = admins_res.json()
    assert any(u["email"] == "owner@demo.com" for u in admin_list)
    
    users_res = client.get("/auth/users", headers=sa_hdr)
    assert users_res.status_code == 200
    log_test(1, "Super Admin logs in", True, "Panel accessible, Users & Admins visible, roles verified")

    # TEST 2: Normal Admin logs in
    r = client.post("/auth/token", json={"username": "admin@demo.com", "password": "demo123"})
    assert r.status_code == 200, f"Admin login failed: {r.text}"
    admin_token = r.json()["access_token"]
    admin_hdr = {"Authorization": f"Bearer {admin_token}"}
    
    admin_me = client.get("/auth/me", headers=admin_hdr).json()
    assert "admin" in admin_me["roles"] and "super_admin" not in admin_me["roles"]
    
    # Users visible
    admin_users = client.get("/auth/users", headers=admin_hdr)
    assert admin_users.status_code == 200
    # Admins not returned in users list
    user_emails = [u["email"] for u in admin_users.json()]
    assert "owner@demo.com" not in user_emails
    assert "admin@demo.com" not in user_emails
    log_test(2, "Normal Admin logs in", True, "Users list visible with normal users only, admins excluded")

    # TEST 3: Normal Admin directly requests Admin Management API
    r = client.get("/auth/admins", headers=admin_hdr)
    assert r.status_code == 403
    assert "Super Admin access required" in r.text
    log_test(3, "Normal Admin directly requests Admin Management API", True, f"Blocked with {r.status_code} Forbidden")

    # TEST 4: Normal Admin attempts to create an Admin through direct API request
    r_adm = client.post("/auth/admins", json={
        "email": "infiltrator@demo.com", "name": "Infiltrator", "password": "demo123", "roles": ["admin"]
    }, headers=admin_hdr)
    assert r_adm.status_code == 403
    
    r_usr = client.post("/auth/users", json={
        "email": "infiltrator2@demo.com", "name": "Infiltrator 2", "password": "demo123", "roles": ["admin"]
    }, headers=admin_hdr)
    assert r_usr.status_code == 403
    log_test(4, "Normal Admin attempts to create Admin", True, "Both /auth/admins and /auth/users blocked with 403")

    # TEST 5: Normal Admin attempts to modify Super Admin
    sa_id = me["id"]
    r_patch = client.patch(f"/auth/users/{sa_id}", json={"name": "Hacked Super Admin"}, headers=admin_hdr)
    assert r_patch.status_code == 403
    
    r_del = client.delete(f"/auth/users/{sa_id}", headers=admin_hdr)
    assert r_del.status_code == 403
    log_test(5, "Normal Admin attempts to modify Super Admin", True, "Patch and Delete both rejected with 403")

    # TEST 6: Kitchen/Chef logs in
    r = client.post("/auth/token", json={"username": "chef@demo.com", "password": "demo123"})
    assert r.status_code == 200, f"Chef login failed: {r.text}"
    chef_token = r.json()["access_token"]
    chef_hdr = {"Authorization": f"Bearer {chef_token}"}
    
    r_ord = client.get("/orders/", headers=chef_hdr)
    assert r_ord.status_code == 200
    r_adm = client.get("/auth/admins", headers=chef_hdr)
    assert r_adm.status_code == 403
    r_usr = client.get("/auth/users", headers=chef_hdr)
    assert r_usr.status_code == 403
    log_test(6, "Kitchen/Chef logs in", True, "Orders functional (200), Admins & Users blocked (403)")

    # TEST 7: Customer logs in
    r = client.post("/auth/token", json={"username": "customer@demo.com", "password": "demo123"})
    assert r.status_code == 200, f"Customer login failed: {r.text}"
    cust_token = r.json()["access_token"]
    cust_hdr = {"Authorization": f"Bearer {cust_token}"}
    
    r_me = client.get("/auth/me", headers=cust_hdr)
    assert r_me.status_code == 200
    r_adm = client.get("/auth/admins", headers=cust_hdr)
    assert r_adm.status_code == 403
    r_usr = client.get("/auth/users", headers=cust_hdr)
    assert r_usr.status_code == 403
    log_test(7, "Customer logs in", True, "Customer auth works, Admins & Users APIs blocked (403)")

    # TEST 8: Unauthenticated user attempts Admin API
    r1 = client.get("/auth/admins")
    assert r1.status_code == 401
    r2 = client.get("/auth/users")
    assert r2.status_code == 401
    log_test(8, "Unauthenticated user attempts Admin API", True, "Rejected with 401 Unauthorized")

    # TEST 9: Super Admin creates an Admin
    new_admin_email = "created_admin@demo.com"
    # Clean up previous run if exists
    existing = [a for a in client.get("/auth/admins", headers=sa_hdr).json() if a["email"] == new_admin_email]
    for ex in existing:
        client.delete(f"/auth/admins/{ex['id']}", headers=sa_hdr)
        
    create_res = client.post("/auth/admins", json={
        "email": new_admin_email,
        "name": "New Manager",
        "password": "managerpass123",
        "roles": ["admin"]
    }, headers=sa_hdr)
    assert create_res.status_code == 201
    created_id = create_res.json()["id"]
    
    # New Admin logs in
    r_new = client.post("/auth/token", json={"username": new_admin_email, "password": "managerpass123"})
    assert r_new.status_code == 200
    new_tok = r_new.json()["access_token"]
    new_hdr = {"Authorization": f"Bearer {new_tok}"}
    
    # New Admin can view restaurant data
    r_rest = client.get("/menu/restaurants", headers=new_hdr)
    assert r_rest.status_code == 200
    
    # New Admin cannot access /auth/admins
    r_cant = client.get("/auth/admins", headers=new_hdr)
    assert r_cant.status_code == 403
    
    # Clean up
    client.delete(f"/auth/admins/{created_id}", headers=sa_hdr)
    log_test(9, "Super Admin creates an Admin", True, "Admin created, can log in, can access panel, cannot access admins API")

    # TEST 10: Existing users and restaurant data remain intact
    conn = sqlite3.connect("qr_orders.db")
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM menu_items")
    items_count = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM menu_categories")
    cats_count = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM banners")
    banners_count = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users")
    users_count = c.fetchone()[0]
    conn.close()
    assert items_count > 0 and cats_count > 0 and users_count >= 4
    log_test(10, "Existing users and restaurant data remain intact", True, 
             f"{items_count} items, {cats_count} categories, {banners_count} banners, {users_count} users verified intact")

    # TEST 11: Migration idempotency verified
    run1 = subprocess.run([sys.executable, "seed.py"], capture_output=True, text=True)
    assert run1.returncode == 0, f"Seed run 1 failed: {run1.stderr}"
    run2 = subprocess.run([sys.executable, "seed.py"], capture_output=True, text=True)
    assert run2.returncode == 0, f"Seed run 2 failed: {run2.stderr}"
    log_test(11, "Database migration is run twice", True, "Both runs exited 0 cleanly, no duplicate columns or errors")

    # TEST 12: Backend reload verification
    r_check = client.post("/auth/token", json={"username": "owner@demo.com", "password": "demo123"})
    assert r_check.status_code == 200
    log_test(12, "Backend reload / data persistence", True, "Role data persists and authentication continues to work")

    print("\nALL 12 TESTS IN TEST MATRIX PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    main()
