"""Sign-in: magic link, Google, phone one-time code, email and password.

Passwords are hashed by argon2, sessions live on the server in SQLite, and no
token is ever logged. Owners must pass two-factor sign-in.
"""
from __future__ import annotations

import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx
import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from . import models
from .notify import send_email, send_sms
from .permissions import MATRIX
from .ratelimit import hit
from .safelog import security_event
from .security import (
    clear_session_cookie,
    compare,
    create_session,
    hash_password,
    iso,
    load_session,
    new_otp,
    new_token,
    now,
    parse_iso,
    revoke_all_sessions,
    revoke_session,
    set_session_cookie,
    sha256,
    validate_email,
    validate_password,
    validate_phone,
    verify_password,
)
from .settings import Settings

router = APIRouter(prefix="/api/auth", tags=["auth"])

LOCKOUT_WINDOW = 900


class AuthError(HTTPException):
    def __init__(self, status: int, code: str, message: str, retry_after: int | None = None):
        super().__init__(status_code=status, detail={"code": code, "message": message})
        self.retry_after = retry_after


def get_db(request: Request):
    conn = request.app.state.connect()
    try:
        yield conn
    finally:
        conn.close()


def settings_of(request: Request) -> Settings:
    return request.app.state.settings


# ------------------------------------------------------------------ helpers

def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    return (forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else ""))[:64]


def _find_user_by_email(conn, email: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()


def _find_user_by_phone(conn, phone: str) -> sqlite3.Row | None:
    digits = "".join(ch for ch in phone if ch.isdigit())
    rows = conn.execute("SELECT * FROM users WHERE phone IS NOT NULL").fetchall()
    for row in rows:
        stored = "".join(ch for ch in (row["phone"] or "") if ch.isdigit())
        if stored and (digits.endswith(stored[-9:]) or stored.endswith(digits[-9:])):
            return row
    return None


def _tenant(conn, tenant_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
    if row is None:
        raise AuthError(401, "unknown_tenant", "That account no longer exists.")
    return row


def _failures(conn, identifier: str, kind: str) -> int:
    since = iso(now() - timedelta(seconds=LOCKOUT_WINDOW))
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM login_attempts WHERE identifier = ? AND kind = ? AND ok = 0 AND created_at >= ?",
        (identifier, kind, since),
    ).fetchone()
    return int(row["n"])


def _record_attempt(conn, tenant_id: int, identifier: str, kind: str, ok: bool, settings: Settings) -> None:
    conn.execute(
        "INSERT INTO login_attempts (tenant_id, identifier, kind, ok, created_at) VALUES (?,?,?,?,?)",
        (tenant_id, identifier[:254], kind[:20], int(ok), iso()),
    )
    if not ok:
        security_event(settings, event="signin_failed", tenant_id=tenant_id,
                       identifier=identifier[:3] + "***", detail=kind)


def _guard_attempts(conn, identifier: str, kind: str, settings: Settings) -> None:
    failures = _failures(conn, identifier, kind)
    if failures >= settings.lockout_threshold:
        last = conn.execute(
            "SELECT created_at FROM login_attempts WHERE identifier = ? AND kind = ? AND ok = 0"
            " ORDER BY id DESC LIMIT 1",
            (identifier, kind),
        ).fetchone()
        last_at = parse_iso(last["created_at"]) if last else now()
        wait = int((last_at + timedelta(seconds=settings.lockout_seconds) - now()).total_seconds())
        raise AuthError(429, "locked_out",
                        f"Too many attempts. Try again in {max(wait, 1)} seconds.",
                        retry_after=max(wait, 1))
    if failures >= settings.slow_down_after:
        # Slowed down: each further attempt costs a pause, and hammering it
        # still counts towards the lockout.
        conn.execute(
            "INSERT INTO login_attempts (tenant_id, identifier, kind, ok, created_at) VALUES (?,?,?,?,?)",
            (0, identifier[:254], kind[:20], 0, iso()),
        )
        security_event(settings, event="signin_slowed", tenant_id=0,
                       identifier=identifier[:3] + "***", detail=kind)
        raise AuthError(429, "slow_down",
                        "Too many attempts. Wait a moment before trying again.",
                        retry_after=30)


def _token_key(kind: str, raw: str) -> str:
    return sha256(f"{kind}:{raw}")


def _issue_token(conn, tenant_id: int, user_id: int, kind: str, ttl: int,
                 code: str | None = None) -> str:
    raw, _ = new_token()
    conn.execute(
        "INSERT INTO auth_tokens (tenant_id, user_id, kind, token_hash, code_hash, expires_at, created_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (tenant_id, user_id, kind, _token_key(kind, raw),
         sha256(code) if code else None, iso(now() + timedelta(seconds=ttl)), iso()),
    )
    return raw


def _consume_token(conn, kind: str, raw: str, code: str | None = None) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM auth_tokens WHERE kind = ? AND token_hash = ?",
        (kind, _token_key(kind, raw)),
    ).fetchone()
    if row is None:
        raise AuthError(400, "bad_token", "This link is not valid. Request a new one.")
    if row["used_at"] is not None:
        raise AuthError(400, "token_used", "This link was already used. Request a new one.")
    expires = parse_iso(row["expires_at"])
    if expires is None or expires <= now():
        raise AuthError(400, "token_expired", "This link has expired. Request a new one.")
    if code is not None and not compare(sha256(code), row["code_hash"] or ""):
        raise AuthError(400, "bad_code", "That code is not right. Check it and try again.")
    conn.execute("UPDATE auth_tokens SET used_at = ? WHERE id = ?", (iso(), row["id"]))
    return row


def _needs_totp(conn, user: sqlite3.Row) -> bool:
    tenant = conn.execute("SELECT require_2fa FROM tenants WHERE id = ?", (user["tenant_id"],)).fetchone()
    return bool(tenant and tenant["require_2fa"] and user["role"] == "OWNER" and user["totp_secret"])


def _challenge_2fa(conn, user: sqlite3.Row, settings: Settings) -> JSONResponse:
    challenge = _issue_token(conn, user["tenant_id"], user["id"], "2fa", 300)
    return JSONResponse({"ok": True, "stage": "totp", "challenge": challenge,
                         "message": "Enter the 6-digit code from your authenticator app."})


def _start_session(request: Request, conn, user: sqlite3.Row, response_type="json"):
    settings = settings_of(request)
    raw, csrf = create_session(conn, settings, user, _client_ip(request),
                               request.headers.get("user-agent"))
    payload = {
        "ok": True,
        "stage": "signed_in",
        "role": user["role"],
        "email": user["email"],
        "email_verified": bool(user["email_verified"]),
        "csrf_token": csrf,
        "permissions": sorted(MATRIX.get(user["role"], set())),
    }
    response = JSONResponse(payload)
    set_session_cookie(response, raw, settings)
    return response


def _after_credentials(request: Request, conn, user: sqlite3.Row):
    if _needs_totp(conn, user):
        return _challenge_2fa(conn, user, settings_of(request))
    return _start_session(request, conn, user)


def _link(request: Request, path: str) -> str:
    base = str(request.base_url).rstrip("/")
    return f"{base}{path}"


def _can_show_dev_links(request: Request) -> bool:
    """Development only, and only for a request from this machine.

    With no email or SMS provider configured, the one-time link or code would
    otherwise be invisible. Nothing is shown to a remote caller, and never when
    DEV_MODE is off.
    """
    settings = request.app.state.settings
    if not (settings.dev_mode and getattr(settings, "dev_show_links", False)):
        return False
    host = request.client.host if request.client else ""
    return host in {"127.0.0.1", "::1", "localhost", "testclient"}


def _dev_extra(request: Request, **values) -> dict:
    if not _can_show_dev_links(request):
        return {}
    return {key: value for key, value in values.items() if value}


def current_session(request: Request) -> dict | None:
    conn = request.app.state.connect()
    try:
        return load_session(conn, request.cookies.get(request.app.state.settings.cookie_name))
    finally:
        conn.close()


def current_user(request: Request) -> dict:
    session = current_session(request)
    if session is None:
        raise HTTPException(status_code=401, detail={
            "code": "not_signed_in", "message": "Please sign in to continue."})
    if not session["email_verified"] and not session["phone_verified"]:
        raise HTTPException(status_code=403, detail={
            "code": "email_unverified",
            "message": "Verify your email address first: open the link we sent you."})
    return session


# ------------------------------------------------------------------ models

class SignupIn(BaseModel):
    business_name: str = Field(min_length=1, max_length=120)
    full_name: str = Field(min_length=1, max_length=120)
    email: str
    password: str
    phone: str | None = None
    accept_terms: bool = False


class PasswordIn(BaseModel):
    email: str
    password: str


class MagicIn(BaseModel):
    email: str


class PhoneIn(BaseModel):
    phone: str


class PhoneVerifyIn(BaseModel):
    phone: str
    code: str


class TotpIn(BaseModel):
    challenge: str
    code: str


class GoogleIn(BaseModel):
    credential: str
    business_name: str | None = None


class ResetRequestIn(BaseModel):
    email: str


class ResetIn(BaseModel):
    token: str
    new_password: str


class EnrollIn(BaseModel):
    code: str


# ------------------------------------------------------------------ routes

@router.post("/signup")
def signup(payload: SignupIn, request: Request, conn=Depends(get_db)):
    settings = settings_of(request)
    if not payload.accept_terms:
        raise AuthError(400, "terms_required", "Please accept the terms of service to continue.")
    try:
        email = validate_email(payload.email)
        validate_password(payload.password)
    except ValueError as exc:
        raise AuthError(400, "invalid_signup", str(exc)) from exc
    if _find_user_by_email(conn, email):
        raise AuthError(409, "email_taken", "That email already has an account. Sign in instead.")
    tenant_slug = secrets.token_urlsafe(8)
    stamp = iso()
    totp_secret = pyotp.random_base32()
    conn.execute(
        "INSERT INTO tenants (tenant_id, name, public_slug, plan, ai_provider, ai_model, ai_budget_rm,"
        " require_2fa, terms_version, terms_accepted_at, created_at) VALUES (0,?,?,?,?,?,?,?,?,?,?)",
        (payload.business_name.strip()[:120], tenant_slug, settings.plan, settings.ai_provider,
         settings.ollama_model, str(settings.budget_rm_month), 1, settings.terms_version, stamp, stamp),
    )
    tenant_id = int(conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])
    conn.execute("UPDATE tenants SET tenant_id = id WHERE id = ?", (tenant_id,))
    phone = None
    if payload.phone:
        try:
            phone = validate_phone(payload.phone)
        except ValueError:
            phone = None
    conn.execute(
        "INSERT INTO users (tenant_id, email, phone, full_name, role, password_hash, email_verified,"
        " phone_verified, totp_secret, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (tenant_id, email, phone, payload.full_name.strip()[:120], "OWNER",
         hash_password(payload.password), 0, 0, totp_secret, stamp),
    )
    user_id = int(conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    token = _issue_token(conn, tenant_id, user_id, "magic", settings.magic_link_ttl_seconds)
    link = _link(request, f"/api/auth/magic/verify?token={quote(token)}")
    send_email(settings, email, "Verify your NIVORA account",
               f"Welcome to NIVORA.\n\nOpen this link once to verify your email:\n{link}\n\n"
               f"It expires in {settings.magic_link_ttl_seconds // 60} minutes.")
    response = _start_session(request, conn, user)
    body = response.body
    import json
    data = json.loads(body)
    data.update({
        "totp_secret": totp_secret,
        "otpauth_uri": pyotp.TOTP(totp_secret).provisioning_uri(email, issuer_name="NIVORA"),
        "must_verify_email": True,
        **_dev_extra(request, dev_link=link),
    })
    new_response = JSONResponse(data)
    new_response.headers["set-cookie"] = response.headers.get("set-cookie", "")
    return new_response


@router.post("/password")
def sign_in_password(payload: PasswordIn, request: Request, conn=Depends(get_db)):
    settings = settings_of(request)
    try:
        email = validate_email(payload.email)
    except ValueError as exc:
        raise AuthError(400, "bad_email", str(exc)) from exc
    _guard_attempts(conn, email, "password", settings)
    user = _find_user_by_email(conn, email)
    ok = bool(user and verify_password(user["password_hash"], payload.password) and not user["disabled"])
    _record_attempt(conn, user["tenant_id"] if user else 0, email, "password", ok, settings)
    if not ok:
        raise AuthError(401, "bad_credentials", "That email and password do not match.")
    return _after_credentials(request, conn, user)


@router.post("/totp")
def sign_in_totp(payload: TotpIn, request: Request, conn=Depends(get_db)):
    settings = settings_of(request)
    _guard_attempts(conn, "totp:" + payload.challenge[:8], "totp", settings)
    row = conn.execute(
        "SELECT * FROM auth_tokens WHERE kind = '2fa' AND token_hash = ?",
        (_token_key("2fa", payload.challenge),),
    ).fetchone()
    if row is None:
        raise AuthError(400, "bad_challenge", "That sign-in expired. Start again.")
    _consume_token(conn, "2fa", payload.challenge)
    user = conn.execute("SELECT * FROM users WHERE id = ?", (row["user_id"],)).fetchone()
    if not user or not user["totp_secret"]:
        raise AuthError(400, "no_2fa", "Two-factor is not set up for this account.")
    totp = pyotp.TOTP(user["totp_secret"])
    if not totp.verify(payload.code.strip().replace(" ", ""), valid_window=1):
        _record_attempt(conn, user["tenant_id"], f"totp:{payload.challenge[:8]}", "totp", False, settings)
        raise AuthError(401, "bad_code", "That code is not right. Wait for the next one and try again.")
    _record_attempt(conn, user["tenant_id"], f"totp:{payload.challenge[:8]}", "totp", True, settings)
    return _start_session(request, conn, user)


@router.post("/magic/request")
def magic_request(payload: MagicIn, request: Request, conn=Depends(get_db)):
    settings = settings_of(request)
    try:
        email = validate_email(payload.email)
    except ValueError:
        return {"ok": True, "delivered": True}  # no account enumeration
    limit = hit(conn, f"nivora:auth:{email}:magic", 0, 5, 900)
    if not limit["allowed"]:
        raise AuthError(429, "slow_down", "Too many links requested. Try again later.",
                        retry_after=limit["retry_after"])
    link = None
    user = _find_user_by_email(conn, email)
    if user:
        token = _issue_token(conn, user["tenant_id"], user["id"], "magic", settings.magic_link_ttl_seconds)
        link = _link(request, f"/api/auth/magic/verify?token={quote(token)}")
        send_email(settings, email, "Your NIVORA sign-in link",
                   f"Open this link once to sign in:\n{link}\n\n"
                   f"It expires in {settings.magic_link_ttl_seconds // 60} minutes.")
    return {"ok": True, "delivered": True, **_dev_extra(request, dev_link=link)}


@router.get("/magic/verify")
def magic_verify(token: str, request: Request, conn=Depends(get_db)):
    settings = settings_of(request)
    row = _consume_token(conn, "magic", token)
    user = conn.execute("SELECT * FROM users WHERE id = ?", (row["user_id"],)).fetchone()
    if not user or user["disabled"]:
        raise AuthError(401, "disabled", "This account cannot sign in.")
    conn.execute("UPDATE users SET email_verified = 1 WHERE id = ?", (user["id"],))
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    if _needs_totp(conn, user):
        challenge = _issue_token(conn, user["tenant_id"], user["id"], "2fa", 300)
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            return RedirectResponse(f"/login?stage=totp&challenge={quote(challenge)}", status_code=303)
        return JSONResponse({"ok": True, "stage": "totp", "challenge": challenge,
                             "message": "Enter the 6-digit code from your authenticator app."})
    raw, _csrf = create_session(conn, settings, user, _client_ip(request), request.headers.get("user-agent"))
    response = RedirectResponse("/?signed_in=1", status_code=303)
    set_session_cookie(response, raw, settings)
    return response


@router.post("/phone/request")
def phone_request(payload: PhoneIn, request: Request, conn=Depends(get_db)):
    settings = settings_of(request)
    try:
        phone = validate_phone(payload.phone)
    except ValueError as exc:
        raise AuthError(400, "bad_phone", str(exc)) from exc
    limit = hit(conn, f"nivora:auth:{phone}:sms", 0, 5, 900)
    if not limit["allowed"]:
        raise AuthError(429, "slow_down", "Too many codes requested. Try again later.",
                        retry_after=limit["retry_after"])
    user = _find_user_by_phone(conn, phone)
    dev_code = None
    if user:
        code = new_otp()
        dev_code = code
        _issue_token(conn, user["tenant_id"], user["id"], "phone", settings.otp_ttl_seconds, code=code)
        send_sms(settings, phone, f"Your NIVORA code is {code}. It expires in 5 minutes.")
    return {"ok": True, "delivered": True, **_dev_extra(request, dev_code=dev_code)}


@router.post("/phone/verify")
def phone_verify(payload: PhoneVerifyIn, request: Request, conn=Depends(get_db)):
    settings = settings_of(request)
    try:
        phone = validate_phone(payload.phone)
    except ValueError as exc:
        raise AuthError(400, "bad_phone", str(exc)) from exc
    _guard_attempts(conn, phone, "phone", settings)
    candidates = conn.execute(
        "SELECT * FROM auth_tokens WHERE kind = 'phone' AND used_at IS NULL ORDER BY id DESC LIMIT 50"
    ).fetchall()
    match = None
    for row in candidates:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (row["user_id"],)).fetchone()
        if user and user["phone"] and "".join(c for c in user["phone"] if c.isdigit())[-9:] == phone[-9:]:
            if compare(sha256(payload.code.strip()), row["code_hash"] or ""):
                match = row
                break
    if match is None:
        _record_attempt(conn, 0, phone, "phone", False, settings)
        raise AuthError(401, "bad_code", "That code is not right or has expired.")
    expires = parse_iso(match["expires_at"])
    if expires is None or expires <= now():
        raise AuthError(400, "token_expired", "That code expired. Request a new one.")
    conn.execute("UPDATE auth_tokens SET used_at = ? WHERE id = ?", (iso(), match["id"]))
    conn.execute("UPDATE users SET phone_verified = 1 WHERE id = ?", (match["user_id"],))
    _record_attempt(conn, match["tenant_id"], phone, "phone", True, settings)
    user = conn.execute("SELECT * FROM users WHERE id = ?", (match["user_id"],)).fetchone()
    return _after_credentials(request, conn, user)


def default_google_verifier(settings: Settings, credential: str) -> dict:
    if not settings.google_client_id:
        raise AuthError(503, "google_not_configured", "Google sign-in is not configured on this server.")
    try:
        response = httpx.get("https://oauth2.googleapis.com/tokeninfo",
                             params={"id_token": credential}, timeout=10.0)
    except httpx.HTTPError as exc:
        raise AuthError(503, "google_unavailable", "Google sign-in is unavailable right now.") from exc
    if response.status_code != 200:
        raise AuthError(401, "bad_google_token", "That Google sign-in is not valid.")
    claims = response.json()
    if claims.get("aud") != settings.google_client_id:
        raise AuthError(401, "bad_google_token", "That Google sign-in is for another app.")
    if str(claims.get("email_verified")).lower() not in ("true", "1"):
        raise AuthError(403, "email_unverified", "Your Google email is not verified.")
    return claims


@router.post("/google")
def google_sign_in(payload: GoogleIn, request: Request, conn=Depends(get_db)):
    settings = settings_of(request)
    verifier = getattr(request.app.state, "google_verifier", default_google_verifier)
    claims = verifier(settings, payload.credential)
    email = validate_email(claims.get("email", ""))
    user = _find_user_by_email(conn, email)
    if user is None:
        # A first Google sign-in creates the business, with the terms accepted
        # only when the client passes business_name (the sign-up screen does).
        if not payload.business_name:
            raise AuthError(404, "no_account", "No account for that email. Sign up first.")
        tenant_slug = secrets.token_urlsafe(8)
        stamp = iso()
        conn.execute(
            "INSERT INTO tenants (tenant_id, name, public_slug, plan, ai_provider, ai_model, ai_budget_rm,"
            " require_2fa, created_at) VALUES (0,?,?,?,?,?,?,?,?)",
            (payload.business_name.strip()[:120], tenant_slug, settings.plan, settings.ai_provider,
             settings.ollama_model, str(settings.budget_rm_month), 1, stamp),
        )
        tenant_id = int(conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])
        conn.execute("UPDATE tenants SET tenant_id = id WHERE id = ?", (tenant_id,))
        conn.execute(
            "INSERT INTO users (tenant_id, email, full_name, role, email_verified, totp_secret, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (tenant_id, email, claims.get("name") or email.split("@")[0], "OWNER", 1,
             pyotp.random_base32(), stamp),
        )
        user = _find_user_by_email(conn, email)
    if user["disabled"]:
        raise AuthError(401, "disabled", "This account cannot sign in.")
    if not user["email_verified"]:
        conn.execute("UPDATE users SET email_verified = 1 WHERE id = ?", (user["id"],))
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    return _after_credentials(request, conn, user)


@router.post("/logout")
def logout(request: Request, conn=Depends(get_db)):
    settings = settings_of(request)
    revoke_session(conn, request.cookies.get(settings.cookie_name))
    response = JSONResponse({"ok": True})
    clear_session_cookie(response, settings)
    return response


@router.get("/session")
def session_info(request: Request):
    session = current_session(request)
    if session is None:
        return {"ok": False, "signed_in": False}
    return {
        "ok": True,
        "signed_in": True,
        "email": session["email"],
        "role": session["role"],
        "email_verified": bool(session["email_verified"]),
        "csrf_token": session["csrf_token"],
        "two_factor_enabled": bool(session["totp_secret"]),
    }


@router.post("/reset/request")
def reset_request(payload: ResetRequestIn, request: Request, conn=Depends(get_db)):
    settings = settings_of(request)
    try:
        email = validate_email(payload.email)
    except ValueError:
        return {"ok": True, "delivered": True}
    limit = hit(conn, f"nivora:auth:{email}:reset", 0, 5, 900)
    if not limit["allowed"]:
        raise AuthError(429, "slow_down", "Too many reset requests. Try again later.",
                        retry_after=limit["retry_after"])
    user = _find_user_by_email(conn, email)
    link = None
    if user:
        token = _issue_token(conn, user["tenant_id"], user["id"], "reset", settings.reset_ttl_seconds)
        link = _link(request, f"/reset?token={quote(token)}")
        send_email(settings, email, "Reset your NIVORA password",
                   f"Open this link once to choose a new password:\n{link}\n\n"
                   f"It expires in {settings.reset_ttl_seconds // 60} minutes.")
    return {"ok": True, "delivered": True, **_dev_extra(request, dev_link=link)}


@router.post("/reset")
def reset_password(payload: ResetIn, request: Request, conn=Depends(get_db)):
    settings = settings_of(request)
    validate_password(payload.new_password)
    row = _consume_token(conn, "reset", payload.token)
    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                 (hash_password(payload.new_password), row["user_id"]))
    revoke_all_sessions(conn, row["tenant_id"], int(row["user_id"]))
    return {"ok": True, "message": "Password changed. Sign in with the new one."}


@router.post("/2fa/enroll")
def enroll_2fa(request: Request, conn=Depends(get_db)):
    session = current_user(request)
    secret = session["totp_secret"] or pyotp.random_base32()
    conn.execute("UPDATE users SET totp_secret = ? WHERE tenant_id = ? AND id = ?",
                 (secret, session["tenant_id"], session["user_id"]))
    return {
        "ok": True,
        "secret": secret,
        "otpauth_uri": pyotp.TOTP(secret).provisioning_uri(session["email"], issuer_name="NIVORA"),
    }


@router.post("/2fa/confirm")
def confirm_2fa(payload: EnrollIn, request: Request, conn=Depends(get_db)):
    session = current_user(request)
    if not session["totp_secret"]:
        raise AuthError(400, "no_2fa", "Start enrolling first.")
    if not pyotp.TOTP(session["totp_secret"]).verify(payload.code.strip(), valid_window=1):
        raise AuthError(401, "bad_code", "That code is not right. Check the clock on your phone.")
    return {"ok": True, "two_factor_enabled": True}
