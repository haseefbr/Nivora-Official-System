"""Shared fixtures: a real app on a temporary database, a signed-in owner."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pyotp
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.main import create_app  # noqa: E402
from app.settings import Settings  # noqa: E402

PASSWORD = "kuih-lapis-2026"


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        app_secret="test-secret-not-a-real-one",
        database_path=str(tmp_path / "nivora.db"),
        log_path=str(tmp_path / "nivora.log"),
        dev_mode=True,
        force_https=False,
        session_secure=False,
        ai_provider="heuristic",
        ai_local_fallback=True,
        ai_timeout_seconds=2.0,
        payment_webhook_secret="whsec_test_secret",
        payment_test_mode=True,
        rate_person_per_minute=10,
        rate_tenant_per_day=56,
    )


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


def outbox_tokens(settings: Settings, kind: str = "magic") -> list[str]:
    path = Path(settings.log_path).parent / "outbox.log"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    return re.findall(r"token=([A-Za-z0-9_\-]+)", text)


def signup(client: TestClient, settings: Settings, email: str = "amina@kuihlapis.my",
           business: str = "Kuih Lapis Aminah") -> dict:
    response = client.post("/api/auth/signup", json={
        "business_name": business,
        "full_name": "Aminah binti Ali",
        "email": email,
        "password": PASSWORD,
        "accept_terms": True,
    })
    assert response.status_code == 200, response.text
    data = response.json()
    token = outbox_tokens(settings)[-1]
    verify = client.get(f"/api/auth/magic/verify?token={token}")
    assert verify.status_code == 200, verify.text
    body = verify.json()
    assert body.get("stage") == "totp", body
    code = pyotp.TOTP(data["totp_secret"]).now()
    final = client.post("/api/auth/totp", json={"challenge": body["challenge"], "code": code})
    assert final.status_code == 200, final.text
    session = final.json()
    client.headers["X-CSRF-Token"] = session["csrf_token"]
    me = client.get("/api/me").json()
    return {
        "client": client,
        "email": email,
        "password": PASSWORD,
        "csrf": session["csrf_token"],
        "totp_secret": data["totp_secret"],
        "tenant_id": me["tenant"]["id"],
        "user_id": me["user_id"],
    }


@pytest.fixture
def owner(client, settings) -> dict:
    return signup(client, settings)


@pytest.fixture
def owner2(app) -> dict:
    """A second business, to prove tenants cannot see each other."""
    with TestClient(app) as other:
        return signup(other, app.state.settings, email="meiling@tarts.my", business="Mei Ling Tarts")


@pytest.fixture
def seed(owner) -> dict:
    """Ingredients, one recipe, one customer: the numbers the tests assert on."""
    client = owner["client"]
    items = {}
    for name, unit, pack_price, pack_size in [
        ("tepung beras", "g", 4.50, 1000),
        ("gula", "g", 3.20, 1000),
        ("santan", "ml", 2.80, 400),
        ("pewarna", "ml", 6.00, 100),
    ]:
        response = client.post("/api/ingredients", json={
            "name": name, "unit": unit, "pack_price": pack_price, "pack_size": pack_size,
        })
        assert response.status_code == 200, response.text
        items[name] = response.json()["id"]
    recipe = client.post("/api/recipes", json={
        "name": "Kuih lapis asas",
        "product_name": "kuih lapis",
        "yield_units": 40,
        "sell_price": 1.20,
        "items": [
            {"ingredient_id": items["tepung beras"], "quantity": 400},
            {"ingredient_id": items["gula"], "quantity": 300},
            {"ingredient_id": items["santan"], "quantity": 200},
            {"ingredient_id": items["pewarna"], "quantity": 20},
        ],
    })
    assert recipe.status_code == 200, recipe.text
    customer = client.post("/api/customers", json={
        "name": "Aminah", "phone_number": "+60123456789",
        "address": "12 Jalan Melati, 43000 Kajang",
    })
    assert customer.status_code == 200, customer.text
    return {
        **owner,
        "ingredients": items,
        "recipe_id": recipe.json()["recipe"]["id"],
        "recipe": recipe.json()["recipe"],
        "customer_id": customer.json()["customer"]["id"],
    }
