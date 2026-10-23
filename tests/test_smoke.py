"""Smoke: the app starts, signs in, and completes one order end to end."""


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_signup_and_me(owner):
    me = owner["client"].get("/api/me").json()
    assert me["email"] == "amina@kuihlapis.my"
    assert me["role"] == "OWNER"
    assert me["tenant"]["name"] == "Kuih Lapis Aminah"


def test_full_cycle(seed):
    client = seed["client"]
    order = client.post("/api/orders", json={
        "customer_id": seed["customer_id"],
        "delivery_date": "2026-10-24",
        "address": "12 Jalan Melati, 43000 Kajang",
        "items": [{"product_name": "kuih lapis", "quantity": 40, "unit": "biji"}],
    })
    assert order.status_code == 200, order.text
    order_id = order.json()["order"]["id"]
    profit = client.get(f"/api/orders/{order_id}/profit").json()["profit"]
    assert profit["revenue"] == "48.00"
    assert profit["cogs"] == "5.20"
    assert profit["net_profit"] == "42.80"

    plan = client.get("/api/production?date=2026-10-24").json()["plan"]
    assert plan["items"][0]["batches"] == 1

    grocery = client.get("/api/grocery?date=2026-10-24").json()["list"]
    assert grocery["total_cost"] == "5.36"


def test_ai_parse(seed):
    client = seed["client"]
    response = client.post("/api/ai/parse", json={
        "message": "Salam, saya nak order 20 biji kuih lapis untuk esok. Antar ke 12 Jalan Melati, 43000 Kajang. Nama saya Aminah."
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True, body
    assert body["payload"]["items"][0]["quantity"] == 20
    assert body["draft_id"]
