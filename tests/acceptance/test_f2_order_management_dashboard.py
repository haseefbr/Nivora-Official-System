"""Acceptance tests: Order Management Dashboard (UC2, F2).

All active orders, their payment status and delivery date in one place.
"""


def _order(client, customer_id, day, product="kuih lapis", quantity=40,
           address="12 Jalan Melati, 43000 Kajang"):
    response = client.post("/api/orders", json={
        "customer_id": customer_id,
        "delivery_date": day,
        "address": address,
        "items": [{"product_name": product, "quantity": quantity, "unit": "biji"}],
    })
    assert response.status_code == 200, response.text
    return response.json()["order"]


def test_ac2_1_the_dashboard_shows_active_orders_payments_and_dates(seed):
    client = seed["client"]
    order = _order(client, seed["customer_id"], "2026-11-02")
    dash = client.get("/api/dashboard").json()
    assert dash["active_orders"] >= 1
    assert dash["unpaid_orders"] >= 1
    upcoming = {row["id"]: row for row in dash["upcoming"]}
    assert order["id"] in upcoming
    assert upcoming[order["id"]]["delivery_date"] == "2026-11-02"
    assert upcoming[order["id"]]["payment_status"] == "unpaid"
    assert upcoming[order["id"]]["customer_name"] == "Aminah"


def test_ac2_2_the_order_list_carries_the_payment_status_and_total(seed):
    client = seed["client"]
    _order(client, seed["customer_id"], "2026-11-03")
    orders = client.get("/api/orders").json()["orders"]
    assert orders
    row = orders[0]
    assert row["payment_status"] in ("unpaid", "deposit", "paid")
    assert row["delivery_date"] == "2026-11-03"
    assert row["total"] == "48.00"
    assert row["item_count"] == 1


def test_ac2_3_marking_paid_changes_the_dashboard(seed):
    client = seed["client"]
    order = _order(client, seed["customer_id"], "2026-11-04")
    before = client.get("/api/dashboard").json()["unpaid_orders"]
    paid = client.patch(f"/api/orders/{order['id']}/payment", json={"payment_status": "paid"})
    assert paid.status_code == 200, paid.text
    assert paid.json()["order"]["payment_status"] == "paid"
    assert paid.json()["order"]["amount_paid"] == "48.00"
    assert client.get("/api/dashboard").json()["unpaid_orders"] == before - 1


def test_ac2_4_deliveries_are_listed_in_date_order(seed):
    client = seed["client"]
    _order(client, seed["customer_id"], "2026-11-20")
    _order(client, seed["customer_id"], "2026-11-05")
    _order(client, seed["customer_id"], "2026-11-12")
    orders = client.get("/api/orders").json()["orders"]
    dates = [row["delivery_date"] for row in orders]
    assert dates == sorted(dates), "the dashboard lists the next delivery first"


def test_ac2_5_search_finds_an_order_by_customer_or_product(seed):
    client = seed["client"]
    _order(client, seed["customer_id"], "2026-11-06", product="seri muka")
    assert client.get("/api/orders?search=Aminah").json()["orders"]
    by_product = client.get("/api/orders?search=seri").json()["orders"]
    assert by_product
    assert by_product[0]["item_count"] == 1


def test_ac2_6_a_filter_narrows_the_list_without_leaking_other_orders(seed):
    client = seed["client"]
    _order(client, seed["customer_id"], "2026-11-07")
    unpaid = client.get("/api/orders?payment=unpaid").json()["orders"]
    assert all(row["payment_status"] == "unpaid" for row in unpaid)
    paid = client.get("/api/orders?payment=paid").json()["orders"]
    assert all(row["payment_status"] == "paid" for row in paid)
    assert not ({row["id"] for row in unpaid} & {row["id"] for row in paid})


def test_ac2_7_marking_an_order_done_removes_it_from_active(seed):
    client = seed["client"]
    order = _order(client, seed["customer_id"], "2026-11-08")
    done = client.patch(f"/api/orders/{order['id']}", json={"status": "done"})
    assert done.status_code == 200, done.text
    active = client.get("/api/orders?status=active").json()["orders"]
    assert order["id"] not in [row["id"] for row in active]
    dash = client.get("/api/dashboard").json()
    assert order["id"] not in [row["id"] for row in dash["upcoming"]]


def test_ac2_8_a_bad_date_is_refused_with_a_clear_message(seed):
    client = seed["client"]
    response = client.post("/api/orders", json={
        "customer_id": seed["customer_id"], "delivery_date": "next tuesday",
        "items": [{"product_name": "kuih lapis", "quantity": 5}],
    })
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "invalid_order"
    assert "date" in body["message"].lower()
    assert len(client.get("/api/orders").json()["orders"]) == 0
