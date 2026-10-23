"""Milestone M7: the SaaS business — billing, plans, retention, launch list."""
import hashlib
import hmac
import json
import time

from app.billing import PLANS


def _signed(secret: str, payload: dict, timestamp: int | None = None) -> tuple[str, str]:
    stamp = int(timestamp if timestamp is not None else time.time())
    body = json.dumps(payload).encode()
    signature = hmac.new(secret.encode(), f"{stamp}.".encode() + body, hashlib.sha256).hexdigest()
    return body.decode(), f"t={stamp},v1={signature}"


def _event(event_id="evt_1", tenant=1, plan="pro"):
    return {
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {"object": {"metadata": {"tenant_id": str(tenant), "plan": plan}}},
    }


def test_a_webhook_is_verified_before_a_plan_changes(seed, settings):
    client = seed["client"]
    before = client.get("/api/billing").json()["plan"]["code"]
    body, header = _signed("wrong-secret", _event(tenant=seed["tenant_id"]))
    refused = client.post("/api/billing/webhook", content=body,
                          headers={"stripe-signature": header, "content-type": "application/json"})
    assert refused.status_code == 400
    assert refused.json()["code"] == "bad_signature"
    assert client.get("/api/billing").json()["plan"]["code"] == before

    body, header = _signed(settings.payment_webhook_secret, _event(tenant=seed["tenant_id"]))
    accepted = client.post("/api/billing/webhook", content=body,
                           headers={"stripe-signature": header, "content-type": "application/json"})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["plan"] == "pro"
    assert client.get("/api/billing").json()["plan"]["code"] == "pro"


def test_a_replayed_webhook_runs_once(seed, settings):
    client = seed["client"]
    event = _event(event_id="evt_duplicate", tenant=seed["tenant_id"], plan="pro")
    body, header = _signed(settings.payment_webhook_secret, event)
    first = client.post("/api/billing/webhook", content=body,
                        headers={"stripe-signature": header, "content-type": "application/json"})
    again_body, again_header = _signed(settings.payment_webhook_secret, event)
    second = client.post("/api/billing/webhook", content=again_body,
                         headers={"stripe-signature": again_header, "content-type": "application/json"})
    assert first.status_code == 200 and second.status_code == 200
    assert second.json()["duplicate"] is True
    from app.db import connect
    conn = connect(seed["client"].app.state.settings.database_path)
    rows = conn.execute("SELECT COUNT(*) AS n FROM payments WHERE provider_event_id = 'evt_duplicate'").fetchone()["n"]
    conn.close()
    assert rows == 1


def test_an_old_webhook_is_refused(seed, settings):
    body, header = _signed(settings.payment_webhook_secret,
                           _event(event_id="evt_old", tenant=seed["tenant_id"]),
                           timestamp=int(time.time()) - 3600)
    response = seed["client"].post("/api/billing/webhook", content=body,
                                   headers={"stripe-signature": header})
    assert response.status_code == 400
    assert response.json()["code"] == "stale_webhook"


def test_usage_over_the_plan_is_refused_with_an_upgrade_message(seed, app):
    client = seed["client"]
    conn = app.state.connect()
    conn.execute("UPDATE tenants SET plan = 'basic' WHERE id = ?", (seed["tenant_id"],))
    from app.ratelimit import day_key
    from datetime import datetime, timezone
    from app.security import iso
    at = datetime.now(timezone.utc)
    conn.execute(
        "INSERT INTO rate_limits (key, tenant_id, count, expires_at) VALUES (?,?,?,?)"
        " ON CONFLICT(key) DO UPDATE SET count = 20",
        (day_key(seed["tenant_id"], at), seed["tenant_id"], 20, at.timestamp() + 86400),
    )
    conn.close()
    response = client.post("/api/ai/parse", json={"message": "20 biji kuih lapis"})
    assert response.status_code == 429
    body = response.json()
    assert body["code"] == "plan_limit"
    assert "Upgrade" in body["message"]
    assert body["retry_after"] > 0


def test_the_plans_have_increasing_limits():
    limits = [plan["calls_per_day"] for plan in PLANS]
    assert limits == sorted(limits)
    assert PLANS[0]["calls_per_day"] == 20
    assert PLANS[1]["calls_per_day"] == 56
    assert PLANS[2]["calls_per_day"] == 200


def test_signup_asks_for_the_terms(client):
    response = client.post("/api/auth/signup", json={
        "business_name": "Terms Bakery", "full_name": "Owner", "email": "terms@kuih.my",
        "password": "kuih-lapis-2026", "accept_terms": False,
    })
    assert response.status_code == 400
    assert response.json()["code"] == "terms_required"


def test_a_new_customer_can_sign_up_and_finish_a_first_task(app, settings):
    """The guided first task: sign up, verify, pass 2FA, parse one message."""
    import re
    from fastapi.testclient import TestClient
    import pyotp

    with TestClient(app) as newcomer:
        signup = newcomer.post("/api/auth/signup", json={
            "business_name": "Baru Bakery", "full_name": "Siti", "email": "baru@kuih.my",
            "password": "kuih-lapis-2026", "accept_terms": True,
        })
        assert signup.status_code == 200, signup.text
        secret = signup.json()["totp_secret"]
        from pathlib import Path
        text = (Path(settings.log_path).parent / "outbox.log").read_text(encoding="utf-8")
        token = re.findall(r"token=([A-Za-z0-9_\-]+)", text)[-1]
        verified = newcomer.get(f"/api/auth/magic/verify?token={token}")
        assert verified.status_code == 200
        if verified.json().get("stage") == "totp":
            signed_in = newcomer.post("/api/auth/totp", json={
                "challenge": verified.json()["challenge"], "code": pyotp.TOTP(secret).now()})
            assert signed_in.status_code == 200
        newcomer.headers["X-CSRF-Token"] = newcomer.get("/api/me").json()["csrf_token"]
        first_task = newcomer.post("/api/ai/parse", json={
            "message": "Salam, saya nak order 20 biji kuih lapis untuk esok."})
        assert first_task.status_code == 200, first_task.text
        assert first_task.json()["payload"]["intent"] == "order"


def test_the_support_channel_is_on_every_page(client):
    for path in ("/", "/login", "/chat.html", "/reset"):
        response = client.get(path)
        assert response.status_code == 200, path
        body = response.text
        assert "support@nivora.app" in body, path
        assert "WhatsApp" in body or "wa.me" in body, path


def test_an_export_carries_the_data_and_no_secrets(seed):
    client = seed["client"]
    client.post("/api/orders", json={
        "customer_id": seed["customer_id"], "delivery_date": "2026-12-15",
        "items": [{"product_name": "kuih lapis", "quantity": 20}],
    })
    export = client.get("/api/export").json()
    assert export["tenant"]["id"] == seed["tenant_id"]
    assert export["orders"]
    assert export["ingredients"]
    blob = json.dumps(export)
    for forbidden in ("password_hash", "totp_secret", "token_hash", "public_token", "$argon2"):
        assert forbidden not in blob
    assert "Aminah" in blob


def test_retention_is_one_year():
    from pathlib import Path
    text = Path("docs/ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "one year" in text.lower()
