import pytest
from app import models


def test_role_separation(client, db_session):
    # 1. Setup accounts directly
    super_admin_reg = client.post("/auth/register", json={
        "email": "sa@test.com", "name": "Super Admin", "password": "secret", "roles": ["super_admin"]
    })
    assert super_admin_reg.status_code == 200
    sa_id = super_admin_reg.json()["id"]

    # Log in Super Admin
    sa_tok = client.post("/auth/token", json={"username": "sa@test.com", "password": "secret"}).json()["access_token"]
    sa_hdr = {"Authorization": f"Bearer {sa_tok}"}

    # Verify public /auth/register CANNOT create admin once system has a super_admin
    unauth_admin_reg = client.post("/auth/register", json={
        "email": "hacker@test.com", "name": "Hacker", "password": "secret", "roles": ["admin"]
    })
    assert unauth_admin_reg.status_code == 403

    # Super Admin creates normal Admin via /auth/admins
    admin_reg = client.post("/auth/admins", json={
        "email": "admin@test.com", "name": "Admin", "password": "secret", "roles": ["admin"]
    }, headers=sa_hdr)
    assert admin_reg.status_code == 201
    admin_id = admin_reg.json()["id"]

    chef_reg = client.post("/auth/register", json={
        "email": "chef@test.com", "name": "Chef", "password": "secret", "roles": ["kitchen"]
    })
    assert chef_reg.status_code == 200

    cust_reg = client.post("/auth/register", json={
        "email": "cust@test.com", "name": "Cust", "password": "secret", "roles": ["customer"]
    })
    assert cust_reg.status_code == 200
    cust_id = cust_reg.json()["id"]

    admin_tok = client.post("/auth/token", json={"username": "admin@test.com", "password": "secret"}).json()["access_token"]
    admin_hdr = {"Authorization": f"Bearer {admin_tok}"}

    chef_tok = client.post("/auth/token", json={"username": "chef@test.com", "password": "secret"}).json()["access_token"]
    chef_hdr = {"Authorization": f"Bearer {chef_tok}"}

    cust_tok = client.post("/auth/token", json={"username": "cust@test.com", "password": "secret"}).json()["access_token"]
    cust_hdr = {"Authorization": f"Bearer {cust_tok}"}

    # -------------------------------------------------------------
    # TEST 1: Super Admin Access
    # -------------------------------------------------------------
    # Super Admin can list admins
    res = client.get("/auth/admins", headers=sa_hdr)
    assert res.status_code == 200
    admin_emails = [u["email"] for u in res.json()]
    assert "sa@test.com" in admin_emails
    assert "admin@test.com" in admin_emails
    assert "cust@test.com" not in admin_emails

    # Super Admin can create an admin
    new_admin = client.post("/auth/admins", json={
        "email": "admin2@test.com", "name": "Admin 2", "password": "secret", "roles": ["admin"]
    }, headers=sa_hdr)
    assert new_admin.status_code == 201
    admin2_id = new_admin.json()["id"]

    # Super Admin can update an admin
    patch_res = client.patch(f"/auth/admins/{admin2_id}", json={"name": "Admin 2 Updated"}, headers=sa_hdr)
    assert patch_res.status_code == 200
    assert patch_res.json()["name"] == "Admin 2 Updated"

    # Super Admin can delete an admin
    del_res = client.delete(f"/auth/admins/{admin2_id}", headers=sa_hdr)
    assert del_res.status_code == 204

    # Super Admin protection: cannot delete self
    del_self = client.delete(f"/auth/admins/{sa_id}", headers=sa_hdr)
    assert del_self.status_code == 400

    # Super Admin protection: cannot demote only Super Admin
    demote_self = client.patch(f"/auth/admins/{sa_id}", json={"roles": ["admin"]}, headers=sa_hdr)
    assert demote_self.status_code == 400

    # -------------------------------------------------------------
    # TEST 2 & 3: Normal Admin CANNOT Access /auth/admins
    # -------------------------------------------------------------
    # Direct GET /auth/admins -> 403 Forbidden
    res = client.get("/auth/admins", headers=admin_hdr)
    assert res.status_code == 403
    assert "Super Admin access required" in res.json()["detail"]

    # -------------------------------------------------------------
    # TEST 4: Normal Admin CANNOT Create Admin
    # -------------------------------------------------------------
    # Via /auth/admins -> 403
    res = client.post("/auth/admins", json={
        "email": "fakeadmin@test.com", "name": "Fake Admin", "password": "secret", "roles": ["admin"]
    }, headers=admin_hdr)
    assert res.status_code == 403

    # Via /auth/users with roles=["admin"] -> 403
    res = client.post("/auth/users", json={
        "email": "fakeadmin2@test.com", "name": "Fake Admin 2", "password": "secret", "roles": ["admin"]
    }, headers=admin_hdr)
    assert res.status_code == 403

    # Via /auth/users with roles=["super_admin"] -> 403
    res = client.post("/auth/users", json={
        "email": "fakesuper@test.com", "name": "Fake Super", "password": "secret", "roles": ["super_admin"]
    }, headers=admin_hdr)
    assert res.status_code == 403

    # -------------------------------------------------------------
    # TEST 5: Normal Admin CANNOT Modify Super Admin or Admins
    # -------------------------------------------------------------
    # Modifying Super Admin via /auth/users -> 403
    res = client.patch(f"/auth/users/{sa_id}", json={"name": "Hacked"}, headers=admin_hdr)
    assert res.status_code == 403

    # Modifying another Admin via /auth/users -> 403
    res = client.patch(f"/auth/users/{admin_id}", json={"name": "Hacked Admin"}, headers=admin_hdr)
    assert res.status_code == 403

    # Promoting a customer to admin -> 403
    res = client.patch(f"/auth/users/{cust_id}", json={"roles": ["admin"]}, headers=admin_hdr)
    assert res.status_code == 403

    # Deleting Super Admin via /auth/users -> 403
    res = client.delete(f"/auth/users/{sa_id}", headers=admin_hdr)
    assert res.status_code == 403

    # -------------------------------------------------------------
    # TEST 6: Normal Admin CAN Manage Normal Users
    # -------------------------------------------------------------
    # List normal users excludes admins
    users_list = client.get("/auth/users", headers=admin_hdr)
    assert users_list.status_code == 200
    listed_emails = [u["email"] for u in users_list.json()]
    assert "cust@test.com" in listed_emails
    assert "chef@test.com" in listed_emails
    assert "admin@test.com" not in listed_emails
    assert "sa@test.com" not in listed_emails

    # Create chef
    new_chef = client.post("/auth/users", json={
        "email": "chef2@test.com", "name": "Chef 2", "password": "secret", "roles": ["kitchen"]
    }, headers=admin_hdr)
    assert new_chef.status_code == 201

    # Update customer name
    patch_cust = client.patch(f"/auth/users/{cust_id}", json={"name": "Updated Customer"}, headers=admin_hdr)
    assert patch_cust.status_code == 200
    assert patch_cust.json()["name"] == "Updated Customer"

    # -------------------------------------------------------------
    # TEST 7: Kitchen / Chef Permissions
    # -------------------------------------------------------------
    # Chef cannot access /auth/admins -> 403
    assert client.get("/auth/admins", headers=chef_hdr).status_code == 403
    # Chef cannot access /auth/users -> 403
    assert client.get("/auth/users", headers=chef_hdr).status_code == 403
    # Chef can list orders
    assert client.get("/orders/", headers=chef_hdr).status_code == 200

    # -------------------------------------------------------------
    # TEST 8: Customer Permissions
    # -------------------------------------------------------------
    # Customer cannot access /auth/admins -> 403
    assert client.get("/auth/admins", headers=cust_hdr).status_code == 403
    # Customer cannot access /auth/users -> 403
    assert client.get("/auth/users", headers=cust_hdr).status_code == 403

    # -------------------------------------------------------------
    # TEST 9: Unauthenticated Requests
    # -------------------------------------------------------------
    assert client.get("/auth/admins").status_code == 401
    assert client.get("/auth/users").status_code == 401
