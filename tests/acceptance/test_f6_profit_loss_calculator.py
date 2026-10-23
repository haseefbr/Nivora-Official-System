"""Acceptance tests: Profit & Loss Calculator (UC6, F6).

Revenue minus ingredient cost (and fees) per order, and for a date range.
"""
from datetime import date, timedelta


def _order(client, customer_id, day, product="kuih lapis", quantity=40, price=None):
    item = {"product_name": product, "quantity": quantity, "unit": "biji"}
    if price is not None:
        item["unit_price"] = price
    response = client.post("/api/orders", json={
        "customer_id": customer_id, "delivery_date": day, "items": [item],
    })
    assert response.status_code == 200, response.text
    return response.json()["order"]


def test_ac6_1_profit_per_order_is_revenue_minus_ingredients(seed):
    client = seed["client"]
    order = _order(client, seed["customer_id"], "2026-11-25", quantity=40)
    profit = client.get(f"/api/orders/{order['id']}/profit").json()["profit"]
    assert profit["revenue"] == "48.00"       # 40 x RM1.20
    assert profit["cogs"] == "5.20"           # 40 x RM0.13
    assert profit["net_profit"] == "42.80"
    assert profit["margin_percent"] == "89.17"
    assert profit["missing_recipes"] == []


def test_ac6_2_the_line_shows_the_unit_cost_behind_the_profit(seed):
    client = seed["client"]
    order = _order(client, seed["customer_id"], "2026-11-26", quantity=20)
    line = client.get(f"/api/orders/{order['id']}/profit").json()["profit"]["lines"][0]
    assert line["unit_price"] == "1.20"
    assert line["unit_cost"] == "0.13"
    assert line["cost"] == "2.60"
    assert line["recipe_id"] == seed["recipe_id"]


def test_ac6_3_a_product_without_a_recipe_is_flagged_and_not_counted(seed):
    client = seed["client"]
    order = _order(client, seed["customer_id"], "2026-11-27", product="seri muka",
                   quantity=10, price=2.00)
    profit = client.get(f"/api/orders/{order['id']}/profit").json()["profit"]
    assert profit["revenue"] == "20.00"
    assert profit["cogs"] == "0.00"
    assert profit["missing_recipes"] == ["seri muka"]
    assert "seri muka" in [line["product_name"] for line in profit["lines"]]


def test_ac6_4_the_range_report_adds_up_the_orders(seed):
    client = seed["client"]
    _order(client, seed["customer_id"], "2026-12-05", quantity=40)
    _order(client, seed["customer_id"], "2026-12-06", quantity=40)
    report = client.get("/api/profit?start=2026-12-05&end=2026-12-06").json()["profit"]
    assert report["revenue"] == "96.00"
    assert report["cogs"] == "10.40"
    assert report["net_profit"] == "85.60"
    assert len(report["orders"]) == 2


def test_ac6_5_orders_outside_the_range_are_left_out(seed):
    client = seed["client"]
    _order(client, seed["customer_id"], "2026-12-07", quantity=40)
    _order(client, seed["customer_id"], "2027-01-07", quantity=40)
    report = client.get("/api/profit?start=2026-12-01&end=2026-12-31").json()["profit"]
    assert report["revenue"] == "48.00"
    assert len(report["orders"]) == 1


def test_ac6_6_a_cancelled_order_is_not_profit(seed):
    client = seed["client"]
    order = _order(client, seed["customer_id"], "2026-12-08", quantity=40)
    client.patch(f"/api/orders/{order['id']}", json={"status": "cancelled"})
    report = client.get("/api/profit?start=2026-12-08&end=2026-12-08").json()["profit"]
    assert report["revenue"] == "0.00"
    assert report["orders"] == []


def test_ac6_7_a_deposit_does_not_change_the_profit(seed):
    client = seed["client"]
    order = _order(client, seed["customer_id"], "2026-12-09", quantity=40)
    before = client.get(f"/api/orders/{order['id']}/profit").json()["profit"]
    client.patch(f"/api/orders/{order['id']}/payment",
                 json={"payment_status": "deposit", "amount_paid": 20})
    after = client.get(f"/api/orders/{order['id']}/profit").json()["profit"]
    assert before["net_profit"] == after["net_profit"], "profit is not cash received"


def test_ac6_8_a_bad_date_is_refused(seed):
    response = seed["client"].get("/api/profit?start=2026-13-40&end=2026-12-01")
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_date"
