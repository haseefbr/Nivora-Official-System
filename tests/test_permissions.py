"""Milestone M2: authorization and tenants.

Every business is a tenant; every row carries the tenant id; every route names
the permission it needs; a route with no rule is refused.
"""
import sqlite3

import pytest

from app import permissions
from app.security import create_session


def _staff_client(app, settings, tenant_id: int):
    from tests.conftest import PASSWORD
    from fastapi.testclient import TestClient

    conn = app.state.connect()
    email = f"staff-{tenant_id}@kuih.my"
    from app.security import hash_password, iso
    conn.execute(
        "INSERT OR IGNORE INTO users (tenant_id, email, full_name, role, password_hash,"
        " email_verified, created_at) VALUES (?,?,?,?,?,?,?)",
        (tenant_id, email, "Staff", "STAFF", hash_password(PASSWORD), 1, iso()),
    )
    user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    raw, csrf = create_session(conn, settings, user)
    conn.close()
    staff = TestClient(app)
    staff.cookies.set(settings.cookie_name, raw)
    staff.headers["X-CSRF-Token"] = csrf
    return staff


def test_customer_a_cannot_read_customer_b_records_on_every_table(seed, owner2):
    a = seed["client"]
    b = owner2["client"]
    customer = a.post("/api/customers", json={"name": "Secret Customer"}).json()["customer"]
    ingredient = a.post("/api/ingredients", json={
        "name": "secret sugar", "unit": "g", "pack_price": 1, "pack_size": 1000}).json()["id"]
    recipe = a.post("/api/recipes", json={
        "name": "Secret Recipe", "product_name": "secret kuih", "yield_units": 10,
        "items": [{"ingredient_id": ingredient, "quantity": 100}],
    }).json()["recipe"]
    order = a.post("/api/orders", json={
        "customer_id": customer["id"], "delivery_date": "2026-12-01",
        "items": [{"product_name": "secret kuih", "quantity": 10}],
    }).json()["order"]
    thread = a.post("/api/threads", json={"customer_name": "Secret Chat"}).json()["thread"]

    assert b.get(f"/api/customers/{customer['id']}").status_code == 404
    assert b.patch(f"/api/customers/{customer['id']}", json={"name": "hacked"}).status_code == 404
    assert b.get(f"/api/orders/{order['id']}").status_code == 404
    assert b.get(f"/api/orders/{order['id']}/profit").status_code == 404
    assert b.patch(f"/api/orders/{order['id']}", json={"status": "done"}).status_code == 404
    assert b.patch(f"/api/orders/{order['id']}/payment",
                   json={"payment_status": "paid"}).status_code in (404, 403)
    assert b.delete(f"/api/orders/{order['id']}").status_code in (200, 404)
    assert b.get(f"/api/recipes/{recipe['id']}").status_code == 404
    assert b.delete(f"/api/recipes/{recipe['id']}").status_code in (200, 404)
    assert b.delete(f"/api/ingredients/{ingredient}").status_code in (200, 409, 404)
    assert b.get(f"/api/threads/{thread['id']}").status_code == 404

    # and none of A's records show up in B's lists
    assert customer["id"] not in [r["id"] for r in b.get("/api/customers").json()["customers"]]
    assert order["id"] not in [r["id"] for r in b.get("/api/orders").json()["orders"]]
    assert recipe["id"] not in [r["id"] for r in b.get("/api/recipes").json()["recipes"]]
    assert thread["id"] not in [r["id"] for r in b.get("/api/threads").json()["threads"]]
    assert ingredient not in [r["id"] for r in b.get("/api/ingredients").json()["ingredients"]]

    # A still sees its own data, unchanged
    assert a.get(f"/api/customers/{customer['id']}").status_code == 200
    assert a.get(f"/api/orders/{order['id']}").json()["order"]["status"] == "active"
    assert a.get(f"/api/customers/{customer['id']}").json()["customer"]["name"] == "Secret Customer"


def test_a_route_with_no_permission_rule_is_refused(owner):
    client = owner["client"]
    response = client.get("/api/not-a-real-route")
    assert response.status_code == 403
    assert response.json()["code"] == "no_permission_rule"
    assert permissions.rule_for("GET", "/api/not-a-real-route") is None
    # a signed-out caller gets the same refusal, not a hint about the route
    other = client
    other.cookies.clear()
    assert other.get("/api/not-a-real-route").status_code == 403


def test_only_a_role_allowed_to_manage_the_team_can_change_a_role(seed, app, settings):
    staff = _staff_client(app, settings, seed["tenant_id"])
    target = seed["client"].get("/api/me").json()["user_id"]
    refused = staff.patch(f"/api/team/{target}/role", json={"role": "OWNER"})
    assert refused.status_code == 403
    assert refused.json()["code"] == "forbidden"
    assert staff.get("/api/team").status_code == 403
    # the owner can
    allowed = seed["client"].patch(f"/api/team/{target}/role", json={"role": "OWNER"})
    assert allowed.status_code == 200


def test_the_permission_matrix_matches_the_documents():
    assert permissions.MATRIX["OWNER"] == set(permissions.PERMISSIONS.keys())
    assert len(permissions.MATRIX["OWNER"]) == 16
    assert permissions.has_permission("OWNER", "f:AI MESSAGE PARSER")
    assert permissions.has_permission("OWNER", "team")
    assert not permissions.has_permission("STAFF", "team")
    assert not permissions.has_permission(None, "team")
    assert not permissions.has_permission("OWNER", None)


def test_every_table_carries_a_tenant_id(app):
    from app.db import tenant_tables
    conn = app.state.connect()
    try:
        missing = []
        for table in tenant_tables(conn):
            columns = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]
            if "tenant_id" not in columns:
                missing.append(table)
        assert missing == [], f"tables without tenant_id: {missing}"
        # tenants itself carries its own id as tenant_id
        columns = [row["name"] for row in conn.execute("PRAGMA table_info(tenants)")]
        assert "tenant_id" in columns
    finally:
        conn.close()


def test_every_query_filters_by_tenant(seed, owner2):
    """Two businesses, identical data; each list holds only its own rows."""
    a, b = seed["client"], owner2["client"]
    for client, name in ((a, "Shared Name"), (b, "Shared Name")):
        client.post("/api/customers", json={"name": name})
    a_customers = a.get("/api/customers").json()["customers"]
    b_customers = b.get("/api/customers").json()["customers"]
    assert {c["id"] for c in a_customers}.isdisjoint({c["id"] for c in b_customers})
    assert all(c["tenant_id"] == seed["tenant_id"] for c in a_customers)
    assert all(c["tenant_id"] == owner2["tenant_id"] for c in b_customers)


def test_a_missing_permission_on_an_ai_route_is_refused(app, settings, seed):
    staff = _staff_client(app, settings, seed["tenant_id"])
    response = staff.post("/api/ai/parse", json={"message": "20 biji kuih lapis"})
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_usage_and_export_need_their_own_permissions(seed, app, settings):
    staff = _staff_client(app, settings, seed["tenant_id"])
    assert staff.get("/api/usage").status_code == 403
    assert staff.get("/api/export").status_code == 403
    assert seed["client"].get("/api/export").status_code == 200
