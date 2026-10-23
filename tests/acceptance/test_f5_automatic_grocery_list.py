"""Acceptance tests: Automatic Grocery List (UC5, F5).

The shopping list comes from production plans: batches x recipe amounts, with
the cost of what you must buy.
"""
from decimal import Decimal


def _order(client, customer_id, day, product, quantity):
    response = client.post("/api/orders", json={
        "customer_id": customer_id, "delivery_date": day,
        "items": [{"product_name": product, "quantity": quantity, "unit": "biji"}],
    })
    assert response.status_code == 200, response.text
    return response.json()["order"]


def test_ac5_1_a_day_of_production_gives_the_raw_materials(seed):
    client = seed["client"]
    _order(client, seed["customer_id"], "2026-11-20", "kuih lapis", 40)
    data = client.get("/api/grocery?date=2026-11-20").json()["list"]
    lines = {line["ingredient"]: line for line in data["items"]}
    assert Decimal(lines["tepung beras"]["quantity"]) == Decimal("400")
    assert Decimal(lines["gula"]["quantity"]) == Decimal("300")
    assert Decimal(lines["santan"]["quantity"]) == Decimal("200")
    assert Decimal(lines["pewarna"]["quantity"]) == Decimal("20")
    assert data["total_cost"] == "5.36"
    assert data["missing_recipes"] == []


def test_ac5_2_the_list_follows_the_batches_not_the_pieces(seed):
    client = seed["client"]
    _order(client, seed["customer_id"], "2026-11-21", "kuih lapis", 80)
    data = client.get("/api/grocery?date=2026-11-21").json()["list"]
    lines = {line["ingredient"]: line for line in data["items"]}
    assert Decimal(lines["tepung beras"]["quantity"]) == Decimal("800"), "two batches of 40"
    assert data["total_cost"] == "10.72"


def test_ac5_3_the_packs_to_buy_round_up(seed):
    client = seed["client"]
    _order(client, seed["customer_id"], "2026-11-22", "kuih lapis", 120)
    data = client.get("/api/grocery?date=2026-11-22").json()["list"]
    lines = {line["ingredient"]: line for line in data["items"]}
    assert lines["tepung beras"]["packs_to_buy"] == 2, "1.2 kg needs two 1 kg packs"
    assert lines["santan"]["packs_to_buy"] == 2, "600 ml needs two 400 ml packs"


def test_ac5_4_a_week_adds_every_day_together(seed):
    client = seed["client"]
    _order(client, seed["customer_id"], "2026-11-23", "kuih lapis", 40)
    _order(client, seed["customer_id"], "2026-11-25", "kuih lapis", 40)
    data = client.get("/api/grocery?start=2026-11-23&end=2026-11-29").json()["list"]
    lines = {line["ingredient"]: line for line in data["items"]}
    assert Decimal(lines["tepung beras"]["quantity"]) == Decimal("800")
    assert data["total_cost"] == "10.72"
    assert len(data["days"]) == 7


def test_ac5_5_orders_outside_the_range_are_not_bought(seed):
    client = seed["client"]
    _order(client, seed["customer_id"], "2026-11-30", "kuih lapis", 40)
    _order(client, seed["customer_id"], "2026-12-02", "kuih lapis", 40)
    data = client.get("/api/grocery?start=2026-11-30&end=2026-11-30").json()["list"]
    lines = {line["ingredient"]: line for line in data["items"]}
    assert Decimal(lines["tepung beras"]["quantity"]) == Decimal("400")


def test_ac5_6_a_product_without_a_recipe_is_reported_not_guessed(seed):
    client = seed["client"]
    _order(client, seed["customer_id"], "2026-12-03", "seri muka", 20)
    data = client.get("/api/grocery?date=2026-12-03").json()["list"]
    assert data["items"] == []
    assert "seri muka" in [name.lower() for name in data["missing_recipes"]]


def test_ac5_7_the_list_names_which_product_needs_the_ingredient(seed):
    client = seed["client"]
    _order(client, seed["customer_id"], "2026-12-04", "kuih lapis", 40)
    data = client.get("/api/grocery?date=2026-12-04").json()["list"]
    for line in data["items"]:
        assert "kuih lapis" in [name.lower() for name in line["for_products"]]


def test_ac5_8_an_empty_period_gives_an_empty_list(seed):
    data = seed["client"].get("/api/grocery?date=2026-12-31").json()["list"]
    assert data["items"] == []
    assert data["total_cost"] == "0.00"


def test_ac5_9_an_end_before_the_start_is_refused(seed):
    response = seed["client"].get("/api/grocery?start=2026-12-10&end=2026-12-01")
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_date"
