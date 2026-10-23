"""Acceptance tests: authentication (milestone M1).

Magic link, Google, phone one-time code, email and password (argon2), email
verification, lockout, two-factor for owners, and a one-time reset link.
"""
import re
from datetime import timedelta
from pathlib import Path

import pyotp

from app.security import hash_password, iso, now

PASSWORD = "kuih-lapis-2026"


def _outbox(settings) -> str:
    path = Path(settings.log_path).parent / "outbox.log"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _db(app):
    return app.state.connect()


def test_a_signed_out_request_is_refused(client):
    for path in ("/api/orders", "/api/dashboard", "/api/customers", "/api/me"):
        response = client.get(path)
        assert response.status_code == 401, path
        assert response.json()["code"] == "not_signed_in"


def test_password_sign_in_and_sign_out(client, settings):
    from tests.conftest import signup

    owner = signup(client, settings, email="out@kuih.my", business="Sign Out Bakery")
    assert client.get("/api/me").status_code == 200
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/me").status_code == 401
    # the session is gone on the server too: the old cookie cannot be replayed
    cookie = client.cookies.get(settings.cookie_name)
    assert cookie is None


def test_a_password_is_never_stored_in_plain_text(owner, app):
    conn = _db(app)
    row = conn.execute("SELECT password_hash FROM users WHERE email = ?", (owner["email"],)).fetchone()
    conn.close()
    assert row["password_hash"].startswith("$argon2")
    assert PASSWORD not in row["password_hash"]


def test_a_session_token_never_appears_in_a_log(owner, settings):
    text = _outbox(settings) + Path(settings.log_path).read_text(encoding="utf-8")
    cookie_values = [owner["csrf"]]
    for value in cookie_values:
        assert value not in text
    assert PASSWORD not in text
    assert "session" not in text.lower() or "sessions" not in text.lower()


def test_a_magic_link_works_once(client, settings, app):
    owner = {"email": "magic@kuih.my"}
    response = client.post("/api/auth/signup", json={
        "business_name": "Magic Bakery", "full_name": "Magic Owner", "email": owner["email"],
        "password": PASSWORD, "accept_terms": True,
    })
    assert response.status_code == 200, response.text
    token = re.findall(r"token=([A-Za-z0-9_\-]+)", _outbox(settings))[-1]
    first = client.get(f"/api/auth/magic/verify?token={token}", follow_redirects=False)
    assert first.status_code in (200, 303)
    second = client.get(f"/api/auth/magic/verify?token={token}", follow_redirects=False)
    assert second.status_code == 400
    assert second.json()["code"] in ("token_used", "bad_token")


def test_a_magic_link_expires(client, settings, app):
    client.post("/api/auth/signup", json={
        "business_name": "Expiry Bakery", "full_name": "Owner", "email": "expiry@kuih.my",
        "password": PASSWORD, "accept_terms": True,
    })
    token = re.findall(r"token=([A-Za-z0-9_\-]+)", _outbox(settings))[-1]
    conn = _db(app)
    conn.execute("UPDATE auth_tokens SET expires_at = ? WHERE kind = 'magic'",
                 (iso(now() - timedelta(minutes=1)),))
    conn.close()
    response = client.get(f"/api/auth/magic/verify?token={token}", follow_redirects=False)
    assert response.status_code == 400
    assert response.json()["code"] == "token_expired"


def test_phone_one_time_code_sign_in(owner, client, settings, app):
    phone = "+60111222333"
    conn = _db(app)
    conn.execute("UPDATE users SET phone = ?, phone_verified = 0 WHERE email = ?",
                 (phone, owner["email"]))
    conn.close()
    requested = client.post("/api/auth/phone/request", json={"phone": phone})
    assert requested.status_code == 200
    code = re.findall(r"code is (\d{6})", _outbox(settings))[-1]
    verified = client.post("/api/auth/phone/verify", json={"phone": phone, "code": code})
    assert verified.status_code == 200, verified.text
    # 2FA is on for this owner, so the phone step asks for the authenticator code
    assert verified.json()["stage"] == "totp"
    challenge = verified.json()["challenge"]
    totp = pyotp.TOTP(owner["totp_secret"]).now()
    final = client.post("/api/auth/totp", json={"challenge": challenge, "code": totp})
    assert final.status_code == 200, final.text
    assert final.json()["stage"] == "signed_in"


def test_google_sign_in_uses_the_verified_identity(owner, client, app, settings):
    def verifier(settings_obj, credential):
        assert credential == "google-test-token"
        return {"email": owner["email"], "email_verified": "true", "name": "Aminah"}

    app.state.google_verifier = verifier
    response = client.post("/api/auth/google", json={"credential": "google-test-token"})
    assert response.status_code == 200, response.text
    assert response.json()["stage"] == "totp"


def test_an_unverified_email_cannot_use_the_app(client, settings, app):
    from app.security import create_session, hash_password
    from app.db import connect

    client.post("/api/auth/signup", json={
        "business_name": "Unverified Bakery", "full_name": "Owner", "email": "unverified@kuih.my",
        "password": PASSWORD, "accept_terms": True,
    })
    conn = _db(app)
    user = conn.execute("SELECT * FROM users WHERE email = 'unverified@kuih.my'").fetchone()
    conn.execute("UPDATE users SET email_verified = 0 WHERE id = ?", (user["id"],))
    raw, csrf = create_session(conn, settings, conn.execute(
        "SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone())
    conn.close()
    client.cookies.set(settings.cookie_name, raw)
    client.headers["X-CSRF-Token"] = csrf
    response = client.get("/api/orders")
    assert response.status_code == 403
    assert response.json()["code"] == "email_unverified"


def test_repeated_failed_sign_ins_are_slowed_then_locked(owner, client):
    codes = []
    for _ in range(6):
        response = client.post("/api/auth/password", json={
            "email": owner["email"], "password": "wrong-password",
        })
        codes.append(response.status_code)
    assert codes[0] == 401
    assert 429 in codes, "repeated failures must slow down, then lock"
    locked = client.post("/api/auth/password", json={
        "email": owner["email"], "password": PASSWORD,
    })
    assert locked.status_code == 429
    assert locked.json()["code"] in ("locked_out", "slow_down")
    assert locked.headers.get("retry-after")


def test_an_owner_must_pass_two_factor(owner, client):
    client.post("/api/auth/logout")
    response = client.post("/api/auth/password", json={
        "email": owner["email"], "password": PASSWORD,
    })
    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "totp"
    assert "set-cookie" not in {k.lower() for k in response.headers}
    assert client.get("/api/me").status_code == 401, "no session before the code"
    wrong = client.post("/api/auth/totp", json={"challenge": body["challenge"], "code": "000000"})
    assert wrong.status_code == 401
    fresh = client.post("/api/auth/password", json={
        "email": owner["email"], "password": PASSWORD,
    }).json()
    right = client.post("/api/auth/totp", json={
        "challenge": fresh["challenge"], "code": pyotp.TOTP(owner["totp_secret"]).now(),
    })
    assert right.status_code == 200, right.text
    assert right.json()["stage"] == "signed_in"


def test_a_reset_link_works_once_and_expires(owner, client, settings, app):
    requested = client.post("/api/auth/reset/request", json={"email": owner["email"]})
    assert requested.status_code == 200
    token = re.findall(r"token=([A-Za-z0-9_\-]+)", _outbox(settings))[-1]
    changed = client.post("/api/auth/reset", json={"token": token, "new_password": "new-password-2026"})
    assert changed.status_code == 200, changed.text
    reused = client.post("/api/auth/reset", json={"token": token, "new_password": "another-2026"})
    assert reused.status_code == 400
    # the old password no longer works, the new one does
    assert client.post("/api/auth/password", json={
        "email": owner["email"], "password": PASSWORD,
    }).status_code == 401

    client.post("/api/auth/reset/request", json={"email": owner["email"]})
    expiring = re.findall(r"token=([A-Za-z0-9_\-]+)", _outbox(settings))[-1]
    conn = _db(app)
    conn.execute("UPDATE auth_tokens SET expires_at = ? WHERE kind = 'reset'",
                 (iso(now() - timedelta(minutes=1)),))
    conn.close()
    expired = client.post("/api/auth/reset", json={"token": expiring, "new_password": "third-password-2026"})
    assert expired.status_code == 400
    assert expired.json()["code"] == "token_expired"


def test_signup_requires_the_terms(client):
    response = client.post("/api/auth/signup", json={
        "business_name": "No Terms", "full_name": "Owner", "email": "noterms@kuih.my",
        "password": PASSWORD, "accept_terms": False,
    })
    assert response.status_code == 400
    assert response.json()["code"] == "terms_required"
