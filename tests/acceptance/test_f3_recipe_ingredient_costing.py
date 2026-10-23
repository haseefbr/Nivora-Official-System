"""Acceptance tests: Recipe & Ingredient Costing (UC3, F3).

Raw material lists and pack prices become a cost per piece. Money is Decimal,
rounded to 2 places. The model reads the recipe; code sets every price.
"""


def test_ac3_1_an_ingredient_carries_its_cost_per_unit(seed):
    ingredients = {row["name"]: row for row in seed["client"].get("/api/ingredients").json()["ingredients"]}
    gula = ingredients["gula"]
    assert gula["pack_price"] == "3.20"
    assert gula["pack_size"] == "1000.000000"
    assert gula["cost_per_unit"] == "0.0032"


def test_ac3_2_a_recipe_gives_a_batch_cost_and_a_cost_per_piece(seed):
    recipe = seed["recipe"]
    assert recipe["batch_cost"] == "5.36"
    assert recipe["unit_cost"] == "0.13"
    assert recipe["yield_units"] == 40
    assert recipe["margin_per_unit"] == "1.07"
    assert recipe["margin_percent"] == "89.17"


def test_ac3_3_the_recipe_lines_are_priced_from_the_pack_you_buy(seed):
    lines = {line["ingredient"]: line for line in seed["recipe"]["items"]}
    assert lines["tepung beras"]["cost"] == "1.80"   # 400 g of a RM4.50/kg pack
    assert lines["gula"]["cost"] == "0.96"           # 300 g of a RM3.20/kg pack
    assert lines["santan"]["cost"] == "1.40"         # 200 ml of a RM2.80/400ml pack
    assert lines["pewarna"]["cost"] == "1.20"        # 20 ml of a RM6.00/100ml pack


def test_ac3_4_a_recipe_can_be_read_from_a_message_and_saved(seed):
    response = seed["client"].post("/api/ai/costing", json={
        "message": ("Resepi kuih lapis: 400 g tepung beras, 300 g gula, "
                    "200 ml santan, 20 ml pewarna. Dapat 40 biji.")
    })
    assert response.status_code == 200, response.text
    body = response.json()
    payload = body["payload"]
    assert payload["yield_units"] == 40
    assert len(payload["items"]) == 4
    applied = body["applied"]
    assert applied["saved"] is True
    assert applied["recipe_id"]
    assert applied["matched_cost"] == "5.36"
    assert applied["unmatched"] == []
    assert applied["recipe"]["unit_cost"] == "0.13"


def test_ac3_5_an_unknown_ingredient_is_named_not_guessed(seed):
    response = seed["client"].post("/api/ai/costing", json={
        "message": "Resepi kuih lapis: 400 g tepung beras, 100 g keju. Dapat 20 biji."
    })
    assert response.status_code == 200, response.text
    applied = response.json()["applied"]
    assert "keju" in applied["unmatched"]
    assert applied["matched_cost"] == "1.80", "only the ingredient we stock has a cost"
    reasons = {line["ingredient"]: line.get("reason") for line in applied["lines"] if not line["matched"]}
    assert "price" in reasons["keju"].lower() or "ingredient" in reasons["keju"].lower()


def test_ac3_6_kilograms_are_converted_to_grams(seed):
    response = seed["client"].post("/api/ai/costing", json={
        "message": "Resepi kuih lapis: 1 kg tepung beras. Dapat 20 biji."
    })
    assert response.status_code == 200, response.text
    applied = response.json()["applied"]
    line = applied["lines"][0]
    assert line["matched"] is True
    assert float(line["quantity"]) == 1000.0
    assert line["cost"] == "4.50"


def test_ac3_7_the_model_never_sets_a_price(seed):
    """A recipe reply with a price is refused by the business check."""
    from datetime import date
    from app.ai.contracts import COSTING, ContractSchemaError

    bad = {
        "recipe_name": "kuih lapis", "product_name": "kuih lapis", "yield_units": 40,
        "items": [{"ingredient": "gula", "quantity": 300, "unit": "g", "price": 3.2}],
        "confidence": 0.9,
    }
    import json
    import pytest
    with pytest.raises(ContractSchemaError) as error:
        COSTING.check(json.dumps(bad), "Resepi kuih lapis: 300 g gula. Dapat 40 biji.", date.today())
    assert "must not set prices" in str(error.value)


def test_ac3_8_an_impossible_pack_is_refused(seed):
    response = seed["client"].post("/api/ingredients", json={
        "name": "tepung ubi", "unit": "g", "pack_price": 4.00, "pack_size": 0,
    })
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_ingredient"


def test_ac3_9_an_ingredient_in_use_cannot_be_deleted(seed):
    response = seed["client"].delete(f"/api/ingredients/{seed['ingredients']['gula']}")
    assert response.status_code == 409
    assert response.json()["code"] == "ingredient_in_use"


def test_ac3_10_updating_a_pack_price_changes_every_recipe_cost(seed):
    client = seed["client"]
    before = client.get(f"/api/recipes/{seed['recipe_id']}").json()["recipe"]["unit_cost"]
    updated = client.patch(f"/api/ingredients/{seed['ingredients']['gula']}", json={
        "name": "gula", "unit": "g", "pack_price": 6.40, "pack_size": 1000,
    })
    assert updated.status_code == 200, updated.text
    after = client.get(f"/api/recipes/{seed['recipe_id']}").json()["recipe"]["unit_cost"]
    assert before == "0.13"
    assert after == "0.16", "300 g at the new price adds RM0.96 to a batch of 40"
