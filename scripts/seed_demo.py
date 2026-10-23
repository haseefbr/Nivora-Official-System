"""Create a demo business so you can try NIVORA by hand.

    ./.venv/Scripts/python.exe -m scripts.seed_demo

Sign in with the printed email and password. Two-factor is off for this demo
business only (the seeded owner), so no authenticator app is needed.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import models  # noqa: E402
from app.db import connect, init_db  # noqa: E402
from app.security import hash_password, iso  # noqa: E402
from app.settings import Settings  # noqa: E402

EMAIL = "demo@nivora.my"
PASSWORD = "nivora-demo-2026"


def main() -> None:
    settings = Settings.from_env()
    settings.ensure_dirs()
    init_db(settings.database_path)
    conn = connect(settings.database_path)
    existing = conn.execute("SELECT id, tenant_id FROM users WHERE email = ?", (EMAIL,)).fetchone()
    if existing:
        tenant_id = int(existing["tenant_id"])
        print(f"Demo business already exists (tenant {tenant_id}).")
    else:
        stamp = iso()
        conn.execute(
            "INSERT INTO tenants (tenant_id, name, public_slug, plan, ai_provider, ai_model,"
            " ai_budget_rm, require_2fa, terms_version, terms_accepted_at, created_at)"
            " VALUES (0,?,?,?,?,?,?,?,?,?,?)",
            ("Dapur Aminah", "dapur-aminah", "standard", settings.ai_provider,
             settings.ollama_model, "1000.00", 0, settings.terms_version, stamp, stamp),
        )
        tenant_id = int(conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])
        conn.execute("UPDATE tenants SET tenant_id = id WHERE id = ?", (tenant_id,))
        conn.execute(
            "INSERT INTO users (tenant_id, email, phone, full_name, role, password_hash,"
            " email_verified, phone_verified, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (tenant_id, EMAIL, "+60123456789", "Aminah binti Ali", "OWNER",
             hash_password(PASSWORD), 1, 1, stamp),
        )
        print(f"Created demo business (tenant {tenant_id}).")

    def maybe_recipe() -> int | None:
        row = conn.execute("SELECT id FROM recipes WHERE tenant_id = ? AND lower(name) = 'kuih lapis asas'",
                           (tenant_id,)).fetchone()
        return int(row["id"]) if row else None

    if not maybe_recipe():
        ingredients = {}
        for name, unit, price, size in [
            ("tepung beras", "g", 4.50, 1000),
            ("gula", "g", 3.20, 1000),
            ("santan", "ml", 2.80, 400),
            ("pewarna", "ml", 6.00, 100),
            ("tepung gandum", "g", 3.90, 1000),
            ("mentega", "g", 12.00, 250),
            ("jem nanas", "g", 9.50, 500),
            ("telur", "biji", 14.00, 30),
        ]:
            ingredients[name] = models.create_ingredient(conn, tenant_id, name, unit, price, size)
        models.create_recipe(
            conn, tenant_id, "Kuih lapis asas", "kuih lapis", 40, 1.20,
            "Steam 20 minutes per layer.", [
                {"ingredient_id": ingredients["tepung beras"], "quantity": 400},
                {"ingredient_id": ingredients["gula"], "quantity": 300},
                {"ingredient_id": ingredients["santan"], "quantity": 200},
                {"ingredient_id": ingredients["pewarna"], "quantity": 20},
            ])
        models.create_recipe(
            conn, tenant_id, "Pineapple tart", "pineapple tart", 60, 1.50,
            "Egg wash before baking.", [
                {"ingredient_id": ingredients["tepung gandum"], "quantity": 1000},
                {"ingredient_id": ingredients["mentega"], "quantity": 500},
                {"ingredient_id": ingredients["jem nanas"], "quantity": 800},
                {"ingredient_id": ingredients["telur"], "quantity": 3},
            ])
    customers = conn.execute("SELECT id, name FROM customers WHERE tenant_id = ?", (tenant_id,)).fetchall()
    if not customers:
        models.create_customer(conn, tenant_id, "Aminah", "+60123456789",
                              address="12 Jalan Melati, 43000 Kajang")
        models.create_customer(conn, tenant_id, "Mei Ling", "+60198887777",
                              address="8 Lorong Satu, 43300 Seri Kembangan")
        models.create_customer(conn, tenant_id, "Siti", "+60172223333",
                              address="44 Jalan Kenari, 43400 Seri Kembangan")
        customers = conn.execute("SELECT id, name FROM customers WHERE tenant_id = ?", (tenant_id,)).fetchall()

    if not conn.execute("SELECT id FROM orders WHERE tenant_id = ?", (tenant_id,)).fetchone():
        today = date.today()
        plan = [
            (customers[0]["id"], today + timedelta(days=1), "12 Jalan Melati, 43000 Kajang",
             [("kuih lapis", 40, "biji")], "paid"),
            (customers[1]["id"], today + timedelta(days=1), "8 Lorong Satu, 43300 Seri Kembangan",
             [("pineapple tart", 120, "biji")], "deposit"),
            (customers[2]["id"], today + timedelta(days=2), "44 Jalan Kenari, 43400 Seri Kembangan",
             [("kuih lapis", 80, "biji"), ("pineapple tart", 60, "biji")], "unpaid"),
        ]
        for customer_id, day, address, items, payment in plan:
            order_id = models.create_order(
                conn, tenant_id, customer_id, day.isoformat(), address,
                [{"product_name": p, "quantity": q, "unit": u} for p, q, u in items],
                source="manual")
            models.set_payment(conn, tenant_id, order_id, payment)

    thread = conn.execute("SELECT id FROM message_threads WHERE tenant_id = ?", (tenant_id,)).fetchone()
    if not thread:
        thread = models.create_thread(conn, tenant_id, customers[0]["id"], "Aminah")
        models.append_message(conn, tenant_id, thread["id"], "in", "customer",
                              "Salam, saya nak order 20 biji kuih lapis untuk esok. Antar ke 12 Jalan Melati, 43000 Kajang. Nama saya Aminah.")
        models.append_message(conn, tenant_id, thread["id"], "out", "owner",
                              "Waalaikumussalam Aminah, boleh. Saya sahkan esok pagi.")
        print(f"Customer chat link: /chat.html?t={thread['public_token']}")

    # The buyer menu: what the shop page sells.
    if not conn.execute("SELECT id FROM products WHERE tenant_id = ?", (tenant_id,)).fetchone():
        from app.shop import create_product
        from app.models import recipe_for_product
        menu = [
            ("Nasi Ayam", "Rice & meals", 8.90, "Poached chicken, fragrant rice, chili garlic dip."),
            ("Nasi Lemak Special", "Rice & meals", 7.50, "Coconut rice, sambal, anchovies, peanuts, egg."),
            ("Chicken Teriyaki Rice", "Rice & meals", 12.90, "Grilled chicken, teriyaki glaze, sesame."),
            ("Buttermilk Chicken Rice", "Rice & meals", 11.90, "Crispy chicken in buttery curry-leaf gravy."),
            ("Spaghetti Carbonara", "Noodles", 13.90, "Creamy sauce, smoked chicken, parmesan."),
            ("Creamy Tomyam Noodles", "Noodles", 9.90, "Spicy tomyam broth, seafood, mushrooms."),
            ("Crispy Chicken Burger", "Snacks", 10.90, "Fried chicken thigh, cheese, brioche bun."),
            ("French Fries", "Snacks", 5.50, "Golden fries with chili and garlic aioli."),
            ("Chocolate Brownies", "Desserts", 6.90, "Fudgy dark chocolate squares."),
            ("Strawberry Cheesecake", "Desserts", 9.90, "Baked cheesecake, strawberry compote."),
            ("Matcha Latte", "Drinks", 8.50, "Uji matcha with fresh milk."),
            ("Iced Lemon Tea", "Drinks", 4.50, "Brewed black tea, real lemon."),
            ("Kuih Lapis", "Kuih", 12.00, "Steamed layer cake, box of 10 pieces."),
            ("Pineapple Tart", "Kuih", 15.00, "Buttery pastry, pineapple jam, box of 10."),
        ]
        for name, category, price, description in menu:
            recipe = recipe_for_product(conn, tenant_id, name.lower())
            create_product(conn, tenant_id, name, price, category, description,
                           recipe_id=int(recipe["id"]) if recipe else None)
        conn.execute(
            "UPDATE tenants SET tagline = ?, phone = ?, address = ?, hours = ? WHERE id = ?",
            ("Kuih muih dan makanan Melayu, dibuat setiap pagi.",
             "+60123456789", "12 Jalan Melati, 43000 Kajang",
             "Setiap hari, 9:00 pagi – 6:00 petang (tutup hari Isnin)", tenant_id),
        )
        print("Seeded 14 dishes for the shop page.")

    conn.close()
    print("")
    print("Sign in at http://localhost:8000/login")
    print(f"  email:    {EMAIL}")
    print(f"  password: {PASSWORD}")


if __name__ == "__main__":
    main()
