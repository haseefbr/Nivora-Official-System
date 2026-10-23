"""Acceptance tests: Production Planning (UC4, F4).

All orders for one delivery date, added up into the batches to cook.
"""
from decimal import Decimal


def _order(client, customer_id, day, product, quantity, status="active"):
    response = client.post("/api/orders", json={
        "customer_id": customer_id, "delivery_date": day, "status": status,
        "items": [{"product_name": product, "quantity": quantity, "unit": "biji"}],
    })
    assert response.status_code == 200, response.text
    return response.json()["order"]


def test_ac4_1_the_plan_adds_up_every_order_for_one_date(seed):
    client = seed["client"]
    _order(client, seed["customer_id"], "2026-11-10", "kuih lapis", 40)
    plan = client.get("/api/production?date=2026-11-10").json()["plan"]
    assert plan["orders"] == 1
    item = plan["items"][0]
    assert item["product_name"].lower() == "kuih lapis"
    assert Decimal(item["total_quantity"]) == Decimal("40")
    assert item["yield_units"] == 40
    assert item["batches"] == 1


def test_ac4_2_batches_round_up(seed):
    client = seed["client"]
    _order(client, seed["customer_id"], "2026-11-11", "kuih lapis", 41)
    plan = client.get("/api/production?date=2026-11-11").json()["plan"]
    item = plan["items"][0]
    assert Decimal(item["total_quantity"]) == Decimal("41")
    assert item["batches"] == 2, "41 pieces needs two batches of 40"


def test_ac4_3_orders_for_other_dates_are_not_counted(seed):
    client = seed["client"]
    _order(client, seed["customer_id"], "2026-11-12", "kuih lapis", 40)
    _order(client, seed["customer_id"], "2026-11-13", "kuih lapis", 80)
    plan = client.get("/api/production?date=2026-11-12").json()["plan"]
    assert plan["orders"] == 1
    assert Decimal(plan["items"][0]["total_quantity"]) == Decimal("40")
    assert plan["items"][0]["batches"] == 1


def test_ac4_4_two_products_are_planned_apart(seed):
    client = seed["client"]
    customer = seed["customer_id"]
    response = client.post("/api/orders", json={
        "customer_id": customer, "delivery_date": "2026-11-14",
        "items": [
            {"product_name": "kuih lapis", "quantity": 40, "unit": "biji"},
            {"product_name": "pineapple tart", "quantity": 30, "unit": "biji"},
        ],
    })
    assert response.status_code == 200, response.text
    plan = client.get("/api/production?date=2026-11-14").json()["plan"]
    names = [row["product_name"].lower() for row in plan["items"]]
    assert names == ["kuih lapis", "pineapple tart"]
    assert Decimal(plan["total_units"]) == Decimal("70")


def test_ac4_5_a_cancelled_order_is_not_cooked(seed):
    client = seed["client"]
    order = _order(client, seed["customer_id"], "2026-11-15", "kuih lapis", 40)
    client.patch(f"/api/orders/{order['id']}", json={"status": "cancelled"})
    plan = client.get("/api/production?date=2026-11-15").json()["plan"]
    assert plan["items"] == []
    assert plan["orders"] == 0


def test_ac4_6_a_product_without_a_recipe_is_flagged(seed):
    client = seed["client"]
    _order(client, seed["customer_id"], "2026-11-16", "seri muka", 20)
    plan = client.get("/api/production?date=2026-11-16").json()["plan"]
    assert "seri muka" in [name.lower() for name in plan["missing_recipes"]]
    item = plan["items"][0]
    assert item["recipe_id"] is None
    assert item["batches"] is None, "batches cannot be guessed without a recipe"


def test_ac4_7_an_empty_day_is_a_clear_empty_plan(seed):
    plan = seed["client"].get("/api/production?date=2026-12-25").json()["plan"]
    assert plan["items"] == []
    assert Decimal(plan["total_units"]) == Decimal("0")
    assert plan["orders"] == 0


def test_ac4_8_a_bad_date_is_refused(seed):
    response = seed["client"].get("/api/production?date=25-12-2026")
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_date"
