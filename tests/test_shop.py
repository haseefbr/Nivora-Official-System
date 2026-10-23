"""The shop side: menu, buyer orders, notifications and AI recipe ideas (M9)."""
from decimal import Decimal


def _setup_shop(client, seed):
    business = client.get("/api/settings/business").json()
    client.patch("/api/settings/business", json={
        "name": "Kuih Lapis Aminah", "tagline": "Dibuat setiap pagi",
        "phone": "+60123456789", "address": "12 Jalan Melati, 43000 Kajang",
        "hours": "Setiap hari, 9 pagi – 6 petang",
    })
    dish = client.post("/api/products", json={
        "name": "Nasi Lemak Special", "price": 7.50, "category": "Rice & meals",
        "description": "Coconut rice, sambal, egg.",
    }).json()["product"]
    kuih = client.post("/api/products", json={
        "name": "Kuih Lapis", "price": 12.00, "category": "Kuih",
        "description": "Box of ten.", "recipe_id": seed["recipe_id"],
    }).json()["product"]
    return business["slug"], dish, kuih


def test_the_seller_sets_the_shop_name_and_menu(seed):
    client = seed["client"]
    slug, dish, kuih = _setup_shop(client, seed)
    business = client.get("/api/settings/business").json()
    assert business["name"] == "Kuih Lapis Aminah"
    assert business["tagline"] == "Dibuat setiap pagi"
    assert business["slug"] == slug
    assert business["hours"] == "Setiap hari, 9 pagi – 6 petang"

    products = client.get("/api/products").json()["products"]
    by_name = {p["name"]: p for p in products}
    assert set(by_name) == {"Nasi Lemak Special", "Kuih Lapis"}
    assert by_name["Nasi Lemak Special"]["price"] == "7.50"
    assert by_name["Kuih Lapis"]["recipe_id"] == seed["recipe_id"]


def test_a_dish_can_be_edited_and_removed(seed):
    client = seed["client"]
    slug, dish, kuih = _setup_shop(client, seed)
    updated = client.patch(f"/api/products/{dish['id']}", json={"price": 8.00, "category": "Rice"})
    assert updated.status_code == 200, updated.text
    assert updated.json()["product"]["price"] == "8.00"
    removed = client.delete(f"/api/products/{kuih['id']}")
    assert removed.status_code == 200
    names = [p["name"] for p in client.get("/api/products").json()["products"]]
    assert names == ["Nasi Lemak Special"]

def test_the_public_shop_shows_the_menu_without_signing_in(seed):
    client = seed["client"]
    slug, dish, kuih = _setup_shop(client, seed)
    public = client.get(f"/api/public/shops/{slug}")
    assert public.status_code == 200, public.text
    body = public.json()
    assert body["business"]["name"] == "Kuih Lapis Aminah"
    assert len(body["products"]) == 2
    assert "Rice & meals" in body["categories"]
    prices = {p["name"]: p["price"] for p in body["products"]}
    assert prices["Nasi Lemak Special"] == "7.50"
    # nothing private leaks into the public payload
    assert "ai_model" not in public.text
    assert "email" not in public.text.lower()


def test_a_shop_link_that_does_not_exist_is_a_404(seed):
    assert seed["client"].get("/api/public/shops/not-a-shop").status_code == 404


def test_a_buyer_order_lands_on_the_seller_dashboard(seed):
    client = seed["client"]
    slug, dish, kuih = _setup_shop(client, seed)
    response = client.post(f"/api/public/shops/{slug}/orders", json={
        "customer_name": "Farah", "phone": "0129998888",
        "address": "9 Jalan Mawar, 43000 Kajang", "order_type": "Delivery",
        "payment_method": "Cash on delivery", "delivery_date": "2026-11-30",
        "items": [{"product_id": dish["id"], "quantity": 2}, {"product_id": kuih["id"], "quantity": 1}],
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reference"].startswith("NIV-")
    assert body["items_total"] == "27.00"          # 2 x 7.50 + 12.00
    assert body["delivery_fee"] == "4.00"
    assert body["total"] == "31.00"
    assert body["thread_token"]

    orders = client.get("/api/orders").json()["orders"]
    order = [o for o in orders if o["id"] == body["order_id"]][0]
    assert order["customer_name"] == "Farah"
    assert order["source"] == "buyer"
    assert order["payment_status"] == "unpaid"

    notifications = client.get("/api/notifications").json()
    assert notifications["unread"] >= 1
    assert any("Farah" in n["title"] for n in notifications["notifications"])


def test_a_pickup_order_has_no_delivery_fee(seed):
    client = seed["client"]
    slug, dish, kuih = _setup_shop(client, seed)
    body = client.post(f"/api/public/shops/{slug}/orders", json={
        "customer_name": "Siti", "phone": "0127776666", "order_type": "Pickup",
        "delivery_date": "2026-12-01", "items": [{"product_id": dish["id"], "quantity": 1}],
    }).json()
    assert body["delivery_fee"] == "0.00"
    assert body["total"] == "7.50"


def test_a_buyer_can_look_up_their_orders_by_phone(seed):
    client = seed["client"]
    slug, dish, kuih = _setup_shop(client, seed)
    client.post(f"/api/public/shops/{slug}/orders", json={
        "customer_name": "Aina", "phone": "0123334444", "order_type": "Pickup",
        "delivery_date": "2026-12-02", "items": [{"product_id": dish["id"], "quantity": 3}],
    })
    history = client.get(f"/api/public/shops/{slug}/orders?phone=0123334444").json()["orders"]
    assert len(history) == 1
    assert history[0]["reference"].startswith("NIV-")
    assert history[0]["total"] == "22.50"
    assert history[0]["items"][0]["product_name"] == "Nasi Lemak Special"
    # another phone number sees nothing
    assert client.get(f"/api/public/shops/{slug}/orders?phone=0190000000").json()["orders"] == []


def test_a_dish_from_another_shop_cannot_be_ordered(seed, owner2):
    client = seed["client"]
    slug, dish, kuih = _setup_shop(client, seed)
    other_slug = owner2["client"].get("/api/settings/business").json()["slug"]
    foreign = owner2["client"].post("/api/products", json={
        "name": "Foreign Dish", "price": 9.99, "category": "Food"}).json()["product"]
    response = client.post(f"/api/public/shops/{slug}/orders", json={
        "customer_name": "X", "phone": "0120000000", "delivery_date": "2026-12-03",
        "items": [{"product_id": foreign["id"], "quantity": 1}],
    })
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_item"


def test_an_order_with_no_items_is_refused(seed):
    client = seed["client"]
    slug, dish, kuih = _setup_shop(client, seed)
    response = client.post(f"/api/public/shops/{slug}/orders", json={
        "customer_name": "X", "phone": "0120000000", "items": [],
    })
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_order"


def test_the_ai_researches_a_recipe_for_an_ordered_dish(seed):
    client = seed["client"]
    slug, dish, kuih = _setup_shop(client, seed)
    client.post(f"/api/public/shops/{slug}/orders", json={
        "customer_name": "Hafiz", "phone": "0125551111", "order_type": "Pickup",
        "delivery_date": "2026-12-04", "items": [{"product_id": dish["id"], "quantity": 1}],
    })
    ideas = client.get("/api/recipe-ideas").json()["ideas"]
    assert ideas, "a dish with no recipe should get an idea"
    idea = ideas[0]
    assert idea["dish"].lower().startswith("nasi lemak")
    assert len(idea["payload"]["items"]) >= 3
    assert idea["payload"]["yield_units"] > 0
    assert all("price" not in item for item in idea["payload"]["items"])


def test_approving_an_idea_saves_a_recipe_and_links_the_dish(seed):
    client = seed["client"]
    slug, dish, kuih = _setup_shop(client, seed)
    client.post(f"/api/public/shops/{slug}/orders", json={
        "customer_name": "Hafiz", "phone": "0125551111", "order_type": "Pickup",
        "delivery_date": "2026-12-05", "items": [{"product_id": dish["id"], "quantity": 1}],
    })
    idea = client.get("/api/recipe-ideas").json()["ideas"][0]
    approved = client.post(f"/api/recipe-ideas/{idea['id']}/approve")
    assert approved.status_code == 200, approved.text
    applied = approved.json()["applied"]
    assert applied["recipe_id"], applied
    assert applied["matched_cost"] != "0.00", "the santan in the seed should match"
    products = client.get("/api/products").json()["products"]
    linked = [p for p in products if p["id"] == dish["id"]][0]
    assert linked["recipe_id"] == applied["recipe_id"]
    assert client.get("/api/recipe-ideas").json()["ideas"] == []


def test_the_shop_page_and_login_offer_both_roles(client):
    shop_page = client.get("/shop")
    assert shop_page.status_code == 200
    assert "shop.js" in shop_page.text
    login = client.get("/login")
    assert login.status_code == 200
    body = login.text
    assert "I'm a seller" in body
    assert "I'm a buyer" in body
    assert "/static/brand/nivora-lockup.png" in body
