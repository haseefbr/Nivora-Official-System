"""The product API. Every query is tenant-scoped; every route names its permission."""
from __future__ import annotations

import csv
import io
import json
import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from .. import billing, models
from ..ai.contracts import CONTRACTS
from ..ai.runner import Runner
from ..auth import current_user, get_db
from ..money import D, money, s
from ..permissions import members
from ..ratelimit import hit
from ..security import iso, validate_email
from ..settings import Settings

router = APIRouter(prefix="/api", tags=["app"])


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _tenant(conn, tenant_id: int) -> dict:
    row = conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
    if row is None:
        raise HTTPException(404, detail={"code": "no_tenant", "message": "Business not found"})
    return dict(row)


def _fail(status: int, code: str, message: str, **extra):
    body = {"code": code, "message": message}
    body.update(extra)
    raise HTTPException(status_code=status, detail=body)


# ------------------------------------------------------------------- models

class ItemIn(BaseModel):
    product_name: str
    quantity: float
    unit: str | None = "biji"
    unit_price: float | None = None
    recipe_id: int | None = None


class OrderIn(BaseModel):
    customer_id: int | None = None
    customer_name: str | None = None
    customer_phone: str | None = None
    delivery_date: str | None = None
    address: str | None = None
    notes: str | None = None
    items: list[ItemIn] = Field(default_factory=list)
    status: str = "active"


class OrderPatch(BaseModel):
    status: str | None = None
    delivery_date: str | None = None
    address: str | None = None
    notes: str | None = None


class PaymentIn(BaseModel):
    payment_status: str
    amount_paid: float | None = None


class CustomerIn(BaseModel):
    name: str
    phone_number: str | None = None
    email: str | None = None
    address: str | None = None
    notes: str | None = None


class IngredientIn(BaseModel):
    name: str
    unit: str
    pack_price: float
    pack_size: float
    supplier: str | None = None


class RecipeItemIn(BaseModel):
    ingredient_id: int
    quantity: float


class RecipeIn(BaseModel):
    name: str
    product_name: str | None = None
    yield_units: int = 1
    sell_price: float | None = 0
    notes: str | None = None
    items: list[RecipeItemIn] = Field(default_factory=list)


class MessageIn(BaseModel):
    message: str


class ReplyIn(BaseModel):
    body: str


class ThreadIn(BaseModel):
    customer_id: int | None = None
    customer_name: str | None = None


class AiSettingsIn(BaseModel):
    ai_provider: str | None = None
    ai_model: str | None = None
    ai_budget_rm: float | None = None


class PublicMessageIn(BaseModel):
    body: str
    name: str | None = None


class TeamIn(BaseModel):
    email: str
    role: str = "OWNER"


class RoleIn(BaseModel):
    role: str


# ------------------------------------------------------------------ health

@router.get("/health")
def health(request: Request):
    conn = request.app.state.connect()
    try:
        conn.execute("SELECT 1").fetchone()
        tables = len(conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall())
    finally:
        conn.close()
    return {"status": "ok", "app": "NIVORA", "database": "ok", "tables": tables}


@router.get("/meta")
def meta(request: Request):
    settings = _settings(request)
    return {"app": "NIVORA", "version": "1.0.0", "terms_version": settings.terms_version,
            "plans": billing.PLANS, "support": billing.SUPPORT,
            "dev_mode": settings.dev_mode,
            "google_enabled": bool(settings.google_client_id),
            "google_client_id": settings.google_client_id}


# ---------------------------------------------------------------- session

@router.get("/me")
def me(request: Request, conn=Depends(get_db)):
    session = current_user(request)
    tenant = _tenant(conn, session["tenant_id"])
    return {
        "ok": True,
        "user_id": session["user_id"],
        "email": session["email"],
        "full_name": session["full_name"],
        "role": session["role"],
        "tenant": {"id": tenant["id"], "name": tenant["name"], "plan": tenant["plan"]},
        "csrf_token": session["csrf_token"],
        "email_verified": bool(session["email_verified"]),
        "two_factor_enabled": bool(session["totp_secret"]),
        "permissions": sorted(__import__("app.permissions", fromlist=["MATRIX"]).MATRIX.get(session["role"], set())),
        "unread": models.unread_count(conn, session["tenant_id"]),
    }


@router.get("/dashboard")
def dashboard(request: Request, conn=Depends(get_db)):
    session = current_user(request)
    tenant_id = session["tenant_id"]
    today = date.today().isoformat()
    active = conn.execute(
        "SELECT COUNT(*) AS n FROM orders WHERE tenant_id = ? AND status = 'active'", (tenant_id,)
    ).fetchone()["n"]
    due_today = conn.execute(
        "SELECT COUNT(*) AS n FROM orders WHERE tenant_id = ? AND status = 'active' AND delivery_date = ?",
        (tenant_id, today),
    ).fetchone()["n"]
    unpaid = conn.execute(
        "SELECT COUNT(*) AS n FROM orders WHERE tenant_id = ? AND status = 'active' AND payment_status != 'paid'",
        (tenant_id,),
    ).fetchone()["n"]
    month_start = models.month_start_iso()[:10]
    today_date = date.today()
    month_end = (date(today_date.year + (today_date.month == 12), (today_date.month % 12) + 1, 1)
                 - __import__("datetime").timedelta(days=1)).isoformat()
    profit = models.profit_report(conn, tenant_id, month_start, month_end)
    pending = conn.execute(
        "SELECT COUNT(*) AS n FROM parsed_drafts WHERE tenant_id = ? AND status = 'pending'", (tenant_id,)
    ).fetchone()["n"]
    upcoming = conn.execute(
        "SELECT o.id, o.delivery_date, o.payment_status, o.status, c.name AS customer_name,"
        " (SELECT COUNT(*) FROM order_items i WHERE i.tenant_id = o.tenant_id AND i.order_id = o.id) AS items"
        " FROM orders o LEFT JOIN customers c ON c.id = o.customer_id AND c.tenant_id = o.tenant_id"
        " WHERE o.tenant_id = ? AND o.status = 'active' AND o.delivery_date >= ?"
        " ORDER BY o.delivery_date LIMIT 8",
        (tenant_id, today),
    ).fetchall()
    return {
        "ok": True,
        "tenant": _tenant(conn, tenant_id)["name"],
        "active_orders": active,
        "due_today": due_today,
        "unpaid_orders": unpaid,
        "pending_drafts": pending,
        "unread_messages": models.unread_count(conn, tenant_id),
        "month": {"revenue": profit["revenue"], "cogs": profit["cogs"],
                  "net_profit": profit["net_profit"], "margin_percent": profit["margin_percent"]},
        "upcoming": [dict(r) for r in upcoming],
        "usage": models.usage_summary(conn, tenant_id, D(_tenant(conn, tenant_id)["ai_budget_rm"])),
    }


# ------------------------------------------------------------------ orders

@router.get("/orders")
def list_orders(request: Request, status: str | None = None, payment: str | None = None,
                delivery_from: str | None = None, delivery_to: str | None = None,
                search: str = "", limit: int = 200, conn=Depends(get_db)):
    session = current_user(request)
    return {"ok": True, "orders": models.list_orders(
        conn, session["tenant_id"], status, payment, delivery_from, delivery_to, search, limit)}


@router.post("/orders")
def create_order(payload: OrderIn, request: Request, conn=Depends(get_db)):
    session = current_user(request)
    tenant_id = session["tenant_id"]
    customer_id = payload.customer_id
    if customer_id is None and payload.customer_name:
        row = conn.execute(
            "SELECT id FROM customers WHERE tenant_id = ? AND lower(name) = lower(?)",
            (tenant_id, payload.customer_name.strip()),
        ).fetchone()
        customer_id = int(row["id"]) if row else models.create_customer(
            conn, tenant_id, payload.customer_name, payload.customer_phone, address=payload.address)
    try:
        order_id = models.create_order(
            conn, tenant_id, customer_id, payload.delivery_date, payload.address,
            [i.model_dump() for i in payload.items], notes=payload.notes, status=payload.status,
        )
    except models.ValidationError as exc:
        _fail(400, "invalid_order", str(exc))
    except models.NotFound as exc:
        _fail(404, "not_found", str(exc))
    return {"ok": True, "order": models.get_order(conn, tenant_id, order_id)}


@router.get("/orders/{order_id}")
def get_order(order_id: int, request: Request, conn=Depends(get_db)):
    session = current_user(request)
    try:
        return {"ok": True, "order": models.get_order(conn, session["tenant_id"], order_id)}
    except models.NotFound:
        _fail(404, "not_found", "Order not found")


@router.patch("/orders/{order_id}")
def patch_order(order_id: int, payload: OrderPatch, request: Request, conn=Depends(get_db)):
    session = current_user(request)
    try:
        return {"ok": True, "order": models.update_order(
            conn, session["tenant_id"], order_id, payload.model_dump(exclude_none=True))}
    except models.NotFound:
        _fail(404, "not_found", "Order not found")
    except models.ValidationError as exc:
        _fail(400, "invalid_order", str(exc))


@router.patch("/orders/{order_id}/payment")
def patch_payment(order_id: int, payload: PaymentIn, request: Request, conn=Depends(get_db)):
    session = current_user(request)
    try:
        return {"ok": True, "order": models.set_payment(
            conn, session["tenant_id"], order_id, payload.payment_status, payload.amount_paid)}
    except models.NotFound:
        _fail(404, "not_found", "Order not found")
    except models.ValidationError as exc:
        _fail(400, "invalid_payment", str(exc))


@router.delete("/orders/{order_id}")
def delete_order(order_id: int, request: Request, conn=Depends(get_db)):
    session = current_user(request)
    models.delete_order(conn, session["tenant_id"], order_id)
    return {"ok": True}


@router.get("/orders/{order_id}/profit")
def order_profit(order_id: int, request: Request, conn=Depends(get_db)):
    session = current_user(request)
    try:
        return {"ok": True, "profit": models.order_profit(
            conn, session["tenant_id"], order_id, _settings(request).payment_fee_ratio)}
    except models.NotFound:
        _fail(404, "not_found", "Order not found")


@router.get("/profit")
def profit(start: str | None = None, end: str | None = None, request: Request = None,
           conn=Depends(get_db)):
    session = current_user(request)
    try:
        return {"ok": True, "profit": models.profit_report(
            conn, session["tenant_id"], start, end, _settings(request).payment_fee_ratio)}
    except models.ValidationError as exc:
        _fail(400, "invalid_date", str(exc))


# --------------------------------------------------------------- customers

@router.get("/customers")
def list_customers(request: Request, search: str = "", conn=Depends(get_db)):
    session = current_user(request)
    return {"ok": True, "customers": models.list_customers(conn, session["tenant_id"], search)}


@router.post("/customers")
def create_customer(payload: CustomerIn, request: Request, conn=Depends(get_db)):
    session = current_user(request)
    try:
        customer_id = models.create_customer(
            conn, session["tenant_id"], payload.name, payload.phone_number, payload.email,
            payload.address, payload.notes)
    except models.ValidationError as exc:
        _fail(400, "invalid_customer", str(exc))
    return {"ok": True, "customer": models.get_customer(conn, session["tenant_id"], customer_id)}


@router.get("/customers/{customer_id}")
def get_customer(customer_id: int, request: Request, conn=Depends(get_db)):
    session = current_user(request)
    try:
        customer = models.get_customer(conn, session["tenant_id"], customer_id)
    except models.NotFound:
        _fail(404, "not_found", "Customer not found")
    customer["orders"] = models.customer_history(conn, session["tenant_id"], customer_id)
    return {"ok": True, "customer": customer}


@router.patch("/customers/{customer_id}")
def patch_customer(customer_id: int, payload: CustomerIn, request: Request, conn=Depends(get_db)):
    session = current_user(request)
    try:
        return {"ok": True, "customer": models.update_customer(
            conn, session["tenant_id"], customer_id, payload.model_dump(exclude_none=True))}
    except models.NotFound:
        _fail(404, "not_found", "Customer not found")


# ------------------------------------------------------- ingredients/recipes

@router.get("/ingredients")
def list_ingredients(request: Request, conn=Depends(get_db)):
    session = current_user(request)
    return {"ok": True, "ingredients": models.list_ingredients(conn, session["tenant_id"])}


@router.post("/ingredients")
def create_ingredient(payload: IngredientIn, request: Request, conn=Depends(get_db)):
    session = current_user(request)
    try:
        ingredient_id = models.create_ingredient(
            conn, session["tenant_id"], payload.name, payload.unit,
            payload.pack_price, payload.pack_size, payload.supplier)
    except models.ValidationError as exc:
        _fail(400, "invalid_ingredient", str(exc))
    return {"ok": True, "ingredients": models.list_ingredients(conn, session["tenant_id"]),
            "id": ingredient_id}


@router.patch("/ingredients/{ingredient_id}")
def patch_ingredient(ingredient_id: int, payload: IngredientIn, request: Request, conn=Depends(get_db)):
    session = current_user(request)
    try:
        return {"ok": True, "ingredient": models.update_ingredient(
            conn, session["tenant_id"], ingredient_id, payload.model_dump(exclude_none=True))}
    except models.NotFound:
        _fail(404, "not_found", "Ingredient not found")
    except models.ValidationError as exc:
        _fail(400, "invalid_ingredient", str(exc))


@router.delete("/ingredients/{ingredient_id}")
def delete_ingredient(ingredient_id: int, request: Request, conn=Depends(get_db)):
    session = current_user(request)
    try:
        models.delete_ingredient(conn, session["tenant_id"], ingredient_id)
    except models.ValidationError as exc:
        _fail(409, "ingredient_in_use", str(exc))
    return {"ok": True}


@router.get("/recipes")
def list_recipes(request: Request, conn=Depends(get_db)):
    session = current_user(request)
    return {"ok": True, "recipes": models.list_recipes(conn, session["tenant_id"])}


@router.post("/recipes")
def create_recipe(payload: RecipeIn, request: Request, conn=Depends(get_db)):
    session = current_user(request)
    try:
        recipe_id = models.create_recipe(
            conn, session["tenant_id"], payload.name, payload.product_name or payload.name,
            payload.yield_units, payload.sell_price, payload.notes,
            [i.model_dump() for i in payload.items])
    except (models.ValidationError, models.NotFound) as exc:
        _fail(400, "invalid_recipe", str(exc))
    return {"ok": True, "recipe": models.recipe_detail(conn, session["tenant_id"], recipe_id)}


@router.get("/recipes/{recipe_id}")
def get_recipe(recipe_id: int, request: Request, conn=Depends(get_db)):
    session = current_user(request)
    try:
        return {"ok": True, "recipe": models.recipe_detail(conn, session["tenant_id"], recipe_id)}
    except models.NotFound:
        _fail(404, "not_found", "Recipe not found")


@router.patch("/recipes/{recipe_id}")
def patch_recipe(recipe_id: int, payload: RecipeIn, request: Request, conn=Depends(get_db)):
    session = current_user(request)
    try:
        return {"ok": True, "recipe": models.update_recipe(
            conn, session["tenant_id"], recipe_id, payload.model_dump(exclude_none=True))}
    except models.NotFound:
        _fail(404, "not_found", "Recipe not found")
    except models.ValidationError as exc:
        _fail(400, "invalid_recipe", str(exc))


@router.delete("/recipes/{recipe_id}")
def delete_recipe(recipe_id: int, request: Request, conn=Depends(get_db)):
    session = current_user(request)
    models.delete_recipe(conn, session["tenant_id"], recipe_id)
    return {"ok": True}


@router.post("/recipes/{recipe_id}/items")
def add_recipe_item(recipe_id: int, payload: RecipeItemIn, request: Request, conn=Depends(get_db)):
    session = current_user(request)
    try:
        return {"ok": True, "recipe": models.add_recipe_item(
            conn, session["tenant_id"], recipe_id, payload.model_dump())}
    except (models.NotFound, models.ValidationError) as exc:
        _fail(400, "invalid_item", str(exc))


# -------------------------------------------------------------- production

@router.get("/production")
def production(request: Request, date: str | None = None, conn=Depends(get_db)):
    session = current_user(request)
    day = date or models.parse_day(datetime.now(timezone.utc).date().isoformat())
    try:
        return {"ok": True, "plan": models.production_plan(conn, session["tenant_id"], day)}
    except models.ValidationError as exc:
        _fail(400, "invalid_date", str(exc))


@router.get("/grocery")
def grocery(request: Request, date: str | None = None, start: str | None = None,
            end: str | None = None, conn=Depends(get_db)):
    session = current_user(request)
    first = start or date or date_or_today()
    try:
        return {"ok": True, "list": models.grocery_list(conn, session["tenant_id"], first, end or date or first)}
    except models.ValidationError as exc:
        _fail(400, "invalid_date", str(exc))


def date_or_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# --------------------------------------------------------------- message box

@router.get("/threads")
def threads(request: Request, conn=Depends(get_db)):
    session = current_user(request)
    return {"ok": True, "threads": models.list_threads(conn, session["tenant_id"])}


@router.post("/threads")
def create_thread(payload: ThreadIn, request: Request, conn=Depends(get_db)):
    session = current_user(request)
    try:
        thread = models.create_thread(conn, session["tenant_id"], payload.customer_id,
                                      payload.customer_name)
    except models.NotFound as exc:
        _fail(404, "not_found", str(exc))
    thread["public_path"] = f"/chat.html?t={thread['public_token']}"
    return {"ok": True, "thread": thread}


@router.get("/threads/{thread_id}")
def get_thread(thread_id: int, request: Request, conn=Depends(get_db)):
    session = current_user(request)
    try:
        thread = models.get_thread(conn, session["tenant_id"], thread_id)
    except models.NotFound:
        _fail(404, "not_found", "Conversation not found")
    models.mark_thread_read(conn, session["tenant_id"], thread_id)
    return {"ok": True, "thread": thread}


@router.post("/threads/{thread_id}/reply")
def reply(thread_id: int, payload: ReplyIn, request: Request, conn=Depends(get_db)):
    session = current_user(request)
    try:
        message = models.append_message(conn, session["tenant_id"], thread_id, "out", "owner",
                                        payload.body)
    except models.NotFound:
        _fail(404, "not_found", "Conversation not found")
    except models.ValidationError as exc:
        _fail(400, "invalid_message", str(exc))
    return {"ok": True, "message": message}


# ---------------------------------------------------------------- public chat

@router.get("/public/threads/{token}")
def public_thread(token: str, request: Request, conn=Depends(get_db)):
    thread = models.thread_by_public_token(conn, token)
    if thread is None:
        _fail(404, "not_found", "This chat link is not valid")
    limit = hit(conn, f"nivora:public:{token[:12]}:read", thread["tenant_id"], 60, 60)
    if not limit["allowed"]:
        _fail(429, "slow_down", "Too many requests. Try again in a minute.",
              retry_after=limit["retry_after"])
    return {"ok": True, "business": thread["business_name"],
            "thread": {"id": thread["id"], "messages": thread["messages"]}}


@router.post("/public/threads/{token}/messages")
def public_message(token: str, payload: PublicMessageIn, request: Request, conn=Depends(get_db)):
    thread = models.thread_by_public_token(conn, token)
    if thread is None:
        _fail(404, "not_found", "This chat link is not valid")
    tenant_id = thread["tenant_id"]
    limit = hit(conn, f"nivora:public:{token[:12]}:write", tenant_id, 20, 600)
    if not limit["allowed"]:
        _fail(429, "slow_down", "Too many messages. Try again later.",
              retry_after=limit["retry_after"])
    body = (payload.body or "").strip()
    if not body:
        _fail(400, "empty", "Write a message first")
    if len(body) > 2000:
        _fail(400, "too_long", "Keep the message under 2000 characters")
    message = models.append_message(conn, tenant_id, thread["id"], "in", "customer", body)
    draft_id = None
    tenant = _tenant(conn, tenant_id)
    try:
        result = Runner(_settings(request)).run("parse", conn, tenant, 0, body)
        if result.ok and result.payload and result.payload.get("intent") == "order":
            draft_id = models.create_draft(conn, tenant_id, body, result.payload,
                                           float(result.payload.get("confidence") or 0),
                                           result.needs_human)
    except Exception:  # the message must never be lost because the AI failed
        draft_id = None
    return {"ok": True, "message": message, "draft_id": draft_id}


# ---------------------------------------------------------------- AI routes

def _ai_response(result) -> JSONResponse:
    if not result.ok and result.error:
        status = int(result.error.get("status") or 400)
        body = {"ok": False, **result.error, "request_id": result.request_id}
        return JSONResponse(body, status_code=status)
    return JSONResponse({"ok": True, **result.to_dict()})


@router.post("/ai/parse")
def ai_parse(payload: MessageIn, request: Request, conn=Depends(get_db)):
    session = current_user(request)
    tenant = _tenant(conn, session["tenant_id"])
    result = Runner(_settings(request)).run("parse", conn, tenant, session["user_id"], payload.message)
    body = {"ok": True, **result.to_dict()}
    if result.ok and result.payload and result.payload.get("intent") == "order":
        draft_id = models.create_draft(conn, session["tenant_id"], payload.message,
                                       result.payload, float(result.payload.get("confidence") or 0),
                                       result.needs_human)
        body["draft_id"] = draft_id
    if not result.ok and result.error:
        status = int(result.error.get("status") or 400)
        return JSONResponse({"ok": False, **result.error, "request_id": result.request_id},
                            status_code=status)
    return JSONResponse(body)


@router.post("/ai/costing")
def ai_costing(payload: MessageIn, request: Request, conn=Depends(get_db)):
    session = current_user(request)
    tenant = _tenant(conn, session["tenant_id"])
    result = Runner(_settings(request)).run("costing", conn, tenant, session["user_id"], payload.message)
    if not result.ok and result.error:
        status = int(result.error.get("status") or 400)
        return JSONResponse({"ok": False, **result.error, "request_id": result.request_id},
                            status_code=status)
    body = {"ok": True, **result.to_dict()}
    if result.ok and result.payload:
        body["applied"] = models.apply_costing(conn, session["tenant_id"], result.payload)
    return JSONResponse(body)


@router.get("/ai/drafts")
def list_drafts(request: Request, status: str = "pending", conn=Depends(get_db)):
    session = current_user(request)
    return {"ok": True, "drafts": models.list_drafts(conn, session["tenant_id"], status)}


@router.post("/ai/parse/{draft_id}/approve")
def approve_draft(draft_id: int, request: Request, conn=Depends(get_db)):
    session = current_user(request)
    try:
        order = models.approve_draft(conn, session["tenant_id"], draft_id)
    except models.NotFound:
        _fail(404, "not_found", "Draft not found")
    except models.ValidationError as exc:
        _fail(400, "invalid_draft", str(exc))
    return {"ok": True, "order": order}


@router.post("/ai/parse/{draft_id}/reject")
def reject_draft(draft_id: int, request: Request, conn=Depends(get_db)):
    session = current_user(request)
    try:
        models.reject_draft(conn, session["tenant_id"], draft_id)
    except models.NotFound:
        _fail(404, "not_found", "Draft not found")
    return {"ok": True}


# ------------------------------------------------------- settings and usage

@router.get("/ai/settings")
def get_ai_settings(request: Request, conn=Depends(get_db)):
    session = current_user(request)
    tenant = _tenant(conn, session["tenant_id"])
    return {
        "ok": True,
        "ai_provider": tenant["ai_provider"],
        "ai_model": tenant["ai_model"],
        "ai_budget_rm": s(tenant["ai_budget_rm"]),
        "usage": models.usage_summary(conn, session["tenant_id"], D(tenant["ai_budget_rm"])),
        "providers": ["ollama", "anthropic", "heuristic"],
        "fallback": _settings(request).fallback_provider,
    }


@router.patch("/ai/settings")
def patch_ai_settings(payload: AiSettingsIn, request: Request, conn=Depends(get_db)):
    session = current_user(request)
    fields, values = [], []
    if payload.ai_provider is not None:
        provider = payload.ai_provider.strip().lower()
        if provider not in ("ollama", "anthropic", "heuristic"):
            _fail(400, "invalid_provider", "Choose ollama, anthropic or heuristic")
        fields.append("ai_provider = ?")
        values.append(provider)
    if payload.ai_model is not None:
        model = payload.ai_model.strip()
        if not (1 <= len(model) <= 120):
            _fail(400, "invalid_model", "Enter a model name")
        fields.append("ai_model = ?")
        values.append(model)
    if payload.ai_budget_rm is not None:
        budget = D(payload.ai_budget_rm)
        if budget < 0:
            _fail(400, "invalid_budget", "The budget cannot be negative")
        fields.append("ai_budget_rm = ?")
        values.append(s(budget))
    if fields:
        values.extend([session["tenant_id"]])
        conn.execute(f"UPDATE tenants SET {', '.join(fields)} WHERE id = ?", values)
    return get_ai_settings(request, conn)


@router.get("/usage")
def usage(request: Request, conn=Depends(get_db)):
    session = current_user(request)
    tenant = _tenant(conn, session["tenant_id"])
    data = models.usage_summary(conn, session["tenant_id"], D(tenant["ai_budget_rm"]))
    alerts = conn.execute(
        "SELECT kind, message, created_at FROM alerts WHERE tenant_id = ? ORDER BY id DESC LIMIT 20",
        (session["tenant_id"],),
    ).fetchall()
    return {"ok": True, "usage": data, "alerts": [dict(a) for a in alerts]}


@router.get("/team")
def team_list(request: Request, conn=Depends(get_db)):
    session = current_user(request)
    return {"ok": True, "members": [dict(m) for m in members(conn, session["tenant_id"])]}


@router.post("/team")
def team_add(payload: TeamIn, request: Request, conn=Depends(get_db)):
    session = current_user(request)
    try:
        email = validate_email(payload.email)
    except ValueError as exc:
        _fail(400, "invalid_email", str(exc))
    if conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone():
        _fail(409, "email_taken", "That email is already on NIVORA")
    if payload.role not in ("OWNER",):
        _fail(400, "invalid_role", "Choose OWNER")
    conn.execute(
        "INSERT INTO users (tenant_id, email, full_name, role, email_verified, created_at)"
        " VALUES (?,?,?,?,?,?)",
        (session["tenant_id"], email, email.split("@")[0], payload.role, 0, iso()),
    )
    return {"ok": True, "members": [dict(m) for m in members(conn, session["tenant_id"])]}


@router.patch("/team/{user_id}/role")
def team_role(user_id: int, payload: RoleIn, request: Request, conn=Depends(get_db)):
    session = current_user(request)
    if payload.role not in ("OWNER",):
        _fail(400, "invalid_role", "Choose OWNER")
    row = conn.execute("SELECT * FROM users WHERE tenant_id = ? AND id = ?",
                       (session["tenant_id"], user_id)).fetchone()
    if not row:
        _fail(404, "not_found", "Team member not found")
    conn.execute("UPDATE users SET role = ? WHERE tenant_id = ? AND id = ?",
                 (payload.role, session["tenant_id"], user_id))
    return {"ok": True, "members": [dict(m) for m in members(conn, session["tenant_id"])]}


@router.get("/billing")
def get_billing(request: Request, conn=Depends(get_db)):
    session = current_user(request)
    tenant = _tenant(conn, session["tenant_id"])
    return {"ok": True, **billing.billing_state(conn, tenant)}


@router.post("/billing/checkout")
def checkout(payload: dict, request: Request, conn=Depends(get_db)):
    session = current_user(request)
    tenant = _tenant(conn, session["tenant_id"])
    plan = (payload or {}).get("plan", "")
    try:
        return {"ok": True, **billing.create_checkout(_settings(request), tenant, plan)}
    except billing.BillingError as exc:
        _fail(exc.status, exc.code, str(exc))


@router.get("/export")
def export(request: Request, format: str = "json", conn=Depends(get_db)):
    session = current_user(request)
    tenant_id = session["tenant_id"]
    data = billing.export_tenant(conn, tenant_id)
    if format == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["order_id", "delivery_date", "customer", "status", "payment_status",
                         "product", "quantity", "unit_price", "revenue"])
        for order in data["orders"]:
            for item in order["items"]:
                writer.writerow([order["id"], order["delivery_date"], order["customer_name"],
                                 order["status"], order["payment_status"], item["product_name"],
                                 item["quantity"], item["unit_price"], item["unit_price"]])
        return StreamingResponse(
            iter([buffer.getvalue()]), media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=nivora-export.csv"})
    return data
