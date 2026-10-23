"""Plans, Stripe billing (webhooks verified), retention and data export."""
from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import time

import httpx

from . import models
from .money import D, s
from .security import iso
from .settings import Settings

SUPPORT = {
    "email": "support@nivora.app",
    "whatsapp": "+60123456789",
    "hours": "Mon-Sat, 9am-6pm (MYT)",
}

PLANS = [
    {"code": "basic", "name": "Basic", "calls_per_day": 20, "ai_budget_rm": "150.00",
     "price_rm_month": "29.00"},
    {"code": "standard", "name": "Standard", "calls_per_day": 56, "ai_budget_rm": "1000.00",
     "price_rm_month": "79.00"},
    {"code": "pro", "name": "Pro", "calls_per_day": 200, "ai_budget_rm": "3000.00",
     "price_rm_month": "149.00"},
]
PLAN_BY_CODE = {p["code"]: p for p in PLANS}


class BillingError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code


def billing_state(conn, tenant: dict) -> dict:
    plan = PLAN_BY_CODE.get(tenant["plan"], PLAN_BY_CODE["standard"])
    usage = models.month_usage(conn, tenant["id"])
    today_row = conn.execute(
        "SELECT COUNT(*) AS n FROM ai_calls WHERE tenant_id = ? AND created_at >= ? AND outcome != 'refused'",
        (tenant["id"], models.month_start_iso()),
    ).fetchone()
    return {
        "plan": plan,
        "plans": PLANS,
        "usage_this_month": usage,
        "calls_limit_per_day": plan["calls_per_day"],
        "ai_budget_rm": s(tenant["ai_budget_rm"]),
        "test_mode": True,
        "support": SUPPORT,
        "terms_version": tenant.get("terms_version"),
    }


def create_checkout(settings: Settings, tenant: dict, plan_code: str) -> dict:
    if plan_code not in PLAN_BY_CODE:
        raise BillingError(400, "invalid_plan", "Choose Basic, Standard or Pro")
    if not settings.payment_api_key:
        raise BillingError(
            503, "payments_not_configured",
            "Payments are not switched on yet. Contact support to change your plan.",
        )
    plan = PLAN_BY_CODE[plan_code]
    base = "https://api.stripe.com/v1/checkout/sessions"
    data = {
        "mode": "subscription",
        "success_url": settings.public_base_url + "/?billing=success",
        "cancel_url": settings.public_base_url + "/?billing=cancelled",
        "metadata[tenant_id]": str(tenant["id"]),
        "metadata[plan]": plan_code,
        "line_items[0][price_data][currency]": "myr",
        "line_items[0][price_data][product_data][name]": f"NIVORA {plan['name']}",
        "line_items[0][price_data][unit_amount]": str(int(D(plan["price_rm_month"]) * 100)),
        "line_items[0][price_data][recurring][interval]": "month",
        "line_items[0][quantity]": "1",
    }
    try:
        response = httpx.post(base, data=data, auth=(settings.payment_api_key, ""), timeout=15.0)
    except httpx.HTTPError as exc:
        raise BillingError(503, "payments_unavailable", "The payment provider is unavailable.") from exc
    if response.status_code >= 300:
        raise BillingError(502, "payments_failed", "The payment provider refused the checkout.")
    body = response.json()
    return {"checkout_url": body.get("url"), "test_mode": settings.payment_test_mode}


def verify_webhook(settings: Settings, raw_body: bytes, signature_header: str | None) -> dict:
    """Stripe-style t=...,v1=... HMAC over 'timestamp.body'. Nothing changes before this passes."""
    if not settings.payment_webhook_secret:
        raise BillingError(503, "billing_not_configured", "Billing is not configured on this server.")
    if not signature_header:
        raise BillingError(400, "missing_signature", "Missing webhook signature")
    parts = {}
    for chunk in signature_header.split(","):
        key, _, value = chunk.strip().partition("=")
        parts.setdefault(key, []).append(value)
    try:
        timestamp = int(parts["t"][0])
    except (KeyError, ValueError, IndexError) as exc:
        raise BillingError(400, "bad_signature", "The webhook signature is malformed") from exc
    if abs(time.time() - timestamp) > 300:
        raise BillingError(400, "stale_webhook", "The webhook is too old; replay refused")
    signed = f"{timestamp}.".encode() + raw_body
    expected = hmac.new(settings.payment_webhook_secret.encode(), signed, hashlib.sha256).hexdigest()
    provided = parts.get("v1", [])
    if not any(hmac.compare_digest(expected, candidate) for candidate in provided):
        raise BillingError(400, "bad_signature", "The webhook signature does not match")
    try:
        return json.loads(raw_body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise BillingError(400, "bad_payload", "The webhook body is not JSON") from exc


def apply_webhook(conn, event: dict) -> dict:
    """Idempotent: the provider event id is unique, so a retry never runs twice."""
    event_id = event.get("id") or ""
    event_type = event.get("type") or ""
    if not event_id:
        raise BillingError(400, "bad_payload", "The webhook has no id")
    existing = conn.execute("SELECT id FROM payments WHERE provider_event_id = ?", (event_id,)).fetchone()
    if existing:
        return {"ok": True, "duplicate": True, "event": event_type}
    data = (event.get("data") or {}).get("object") or {}
    metadata = data.get("metadata") or {}
    tenant_id = int(metadata.get("tenant_id") or data.get("client_reference_id") or 0)
    plan = metadata.get("plan")
    if tenant_id <= 0:
        raise BillingError(400, "no_tenant", "The webhook does not name a business")
    tenant = conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
    if tenant is None:
        raise BillingError(404, "no_tenant", "That business does not exist")
    if plan and plan not in PLAN_BY_CODE:
        raise BillingError(400, "invalid_plan", "The webhook names an unknown plan")
    conn.execute(
        "INSERT INTO payments (tenant_id, provider_event_id, event_type, plan, payload_json, created_at)"
        " VALUES (?,?,?,?,?,?)",
        (tenant_id, event_id[:200], event_type[:80], plan, json.dumps(event)[:20000], iso()),
    )
    if event_type == "checkout.session.completed" and plan:
        conn.execute(
            "UPDATE tenants SET plan = ?, ai_budget_rm = ? WHERE id = ?",
            (plan, PLAN_BY_CODE[plan]["ai_budget_rm"], tenant_id),
        )
    elif event_type in ("customer.subscription.deleted", "invoice.payment_failed"):
        conn.execute("UPDATE tenants SET plan = 'basic', ai_budget_rm = ? WHERE id = ?",
                     (PLAN_BY_CODE["basic"]["ai_budget_rm"], tenant_id))
    return {"ok": True, "duplicate": False, "event": event_type, "tenant_id": tenant_id,
            "plan": plan}


def export_tenant(conn, tenant_id: int) -> dict:
    """Everything the business owns, and no secrets (no hashes, no secrets, no tokens)."""
    tenant = dict(conn.execute("SELECT id, name, plan, ai_provider, ai_model, ai_budget_rm, created_at"
                               " FROM tenants WHERE id = ?", (tenant_id,)).fetchone())
    users = [dict(r) for r in conn.execute(
        "SELECT id, email, full_name, phone, role, email_verified, created_at FROM users WHERE tenant_id = ?",
        (tenant_id,)).fetchall()]
    customers = [dict(r) for r in conn.execute(
        "SELECT * FROM customers WHERE tenant_id = ?", (tenant_id,)).fetchall()]
    ingredients = models.list_ingredients(conn, tenant_id)
    recipes = [models.recipe_detail(conn, tenant_id, r["id"]) for r in conn.execute(
        "SELECT id FROM recipes WHERE tenant_id = ?", (tenant_id,)).fetchall()]
    orders = []
    for row in conn.execute("SELECT id FROM orders WHERE tenant_id = ? ORDER BY id", (tenant_id,)).fetchall():
        orders.append(models.get_order(conn, tenant_id, row["id"]))
    threads = []
    for row in conn.execute("SELECT id FROM message_threads WHERE tenant_id = ?", (tenant_id,)).fetchall():
        thread = models.get_thread(conn, tenant_id, row["id"])
        thread.pop("public_token", None)
        threads.append(thread)
    return {
        "exported_at": iso(),
        "tenant": tenant,
        "users": users,
        "customers": customers,
        "ingredients": ingredients,
        "recipes": recipes,
        "orders": orders,
        "threads": threads,
        "retention_days": 365,
    }
