"""Passwords, sessions, CSRF and response hardening.

Passwords are hashed with argon2 (a proven library); this code never stores a
password or a raw session token. Sessions live on the server, in SQLite.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from .settings import Settings

_ph = PasswordHasher()

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
PHONE_RE = re.compile(r"^\+?[0-9][0-9\s\-()]{7,19}$")
MIN_PASSWORD = 10


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None = None) -> str:
    return (dt or now()).replace(microsecond=0).isoformat()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    if not password_hash or not password:
        return False
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_token() -> tuple[str, str]:
    """(raw, hash). Only the hash is stored."""
    raw = secrets.token_urlsafe(32)
    return raw, sha256(raw)


def new_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def compare(a: str, b: str) -> bool:
    return hmac.compare_digest(a or "", b or "")


def validate_email(value: str) -> str:
    value = (value or "").strip().lower()
    if len(value) > 254 or not EMAIL_RE.match(value):
        raise ValueError("Enter a valid email address")
    return value


def validate_phone(value: str) -> str:
    value = (value or "").strip()
    digits = re.sub(r"[^0-9+]", "", value)
    if not PHONE_RE.match(value) or len(re.sub(r"[^0-9]", "", digits)) < 8:
        raise ValueError("Enter a valid phone number, for example +60123456789")
    return digits


def validate_password(value: str) -> str:
    if len(value or "") < MIN_PASSWORD:
        raise ValueError(f"Use at least {MIN_PASSWORD} characters for the password")
    if len(value) > 256:
        raise ValueError("That password is too long")
    if value.lower() in {"password12", "12345678910"}:
        raise ValueError("Choose a less common password")
    return value


# ---------------------------------------------------------------- sessions

SESSION_COLUMNS = """
    s.id AS session_id, s.token_hash, s.csrf_token, s.expires_at AS session_expires_at,
    u.id AS user_id, u.tenant_id, u.email, u.phone, u.full_name, u.role,
    u.email_verified, u.phone_verified, u.totp_secret, u.disabled,
    t.name AS tenant_name, t.plan, t.ai_model, t.ai_provider, t.ai_budget_rm,
    t.require_2fa, t.public_slug
"""


def create_session(
    conn: sqlite3.Connection,
    settings: Settings,
    user_row: sqlite3.Row,
    ip: str | None = None,
    user_agent: str | None = None,
) -> tuple[str, str]:
    raw, token_hash = new_token()
    csrf = secrets.token_urlsafe(24)
    created = now()
    expires = created + timedelta(seconds=settings.session_ttl_seconds)
    conn.execute(
        "INSERT INTO sessions (tenant_id, user_id, token_hash, csrf_token, ip, user_agent, created_at, expires_at)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (
            user_row["tenant_id"],
            user_row["id"],
            token_hash,
            csrf,
            (ip or "")[:64],
            (user_agent or "")[:256],
            iso(created),
            iso(expires),
        ),
    )
    return raw, csrf


def load_session(conn: sqlite3.Connection, raw_token: str | None) -> dict | None:
    if not raw_token:
        return None
    row = conn.execute(
        f"""SELECT {SESSION_COLUMNS}
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            JOIN tenants t ON t.id = u.tenant_id
            WHERE s.token_hash = ? AND s.revoked_at IS NULL""",
        (sha256(raw_token),),
    ).fetchone()
    if row is None:
        return None
    expires = parse_iso(row["session_expires_at"])
    if expires is None or expires <= now():
        return None
    if row["disabled"]:
        return None
    return dict(row)


def revoke_session(conn: sqlite3.Connection, raw_token: str | None) -> None:
    if not raw_token:
        return
    conn.execute(
        "UPDATE sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
        (iso(), sha256(raw_token)),
    )


def revoke_all_sessions(conn: sqlite3.Connection, tenant_id: int, user_id: int) -> None:
    conn.execute(
        "UPDATE sessions SET revoked_at = ? WHERE tenant_id = ? AND user_id = ? AND revoked_at IS NULL",
        (iso(), tenant_id, user_id),
    )


def set_session_cookie(response, raw_token: str, settings: Settings) -> None:
    response.set_cookie(
        settings.cookie_name,
        raw_token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.session_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response, settings: Settings) -> None:
    response.delete_cookie(settings.cookie_name, path="/")


# ---------------------------------------------------------------- headers

CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self' https://accounts.google.com; connect-src 'self' https://accounts.google.com; "
    "frame-src https://accounts.google.com; frame-ancestors 'none'; base-uri 'self'; "
    "form-action 'self'"
)


def apply_security_headers(response, settings: Settings) -> None:
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = CSP
    response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
    if settings.dev_mode:
        # Dev: never let a stale app.js/bot.js outlive an edit.
        response.headers["Cache-Control"] = "no-store, must-revalidate"
    if settings.force_https or (not settings.dev_mode):
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"


def redact(text: str, secrets_to_hide: list[str] | None = None) -> str:
    """For log lines: remove tokens, keys, password fields."""
    out = text or ""
    for secret_value in secrets_to_hide or []:
        if secret_value and len(secret_value) >= 6:
            out = out.replace(secret_value, "[redacted]")
    out = re.sub(r'("?(?:password|token|secret|api_key|authorization)"?\s*[:=]\s*)("[^"]*"|\S+)', r"\1[redacted]", out, flags=re.I)
    out = re.sub(r"eyJ[A-Za-z0-9_\-\.]{10,}", "[redacted-jwt]", out)
    before = out
    return before
