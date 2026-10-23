"""The shop side of the API: menu, buyer orders, notifications, recipe ideas."""
from __future__ import annotations

from fastapi import BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .. import models, shop as shop_service
from ..ai.runner import Runner
from ..auth import current_user, get_db
from ..money import s
from ..ratelimit import hit
from ..security import iso

from .api import _fail, _settings, _tenant, router


class ProductIn(BaseModel):
    name: str
    price: float
    category: str = "Food"
    description: str | None = None
    image_url: str | None = None
    recipe_id: int | None = None


class ProductPatch(BaseModel):
    name: str | None = None
    price: float | None = None
    category: str | None = None
    description: str | None = None
    image_url: str | None = None
    recipe_id: int | None = None
    active: bool | None = None


class BusinessIn(BaseModel):
    name: str
    tagline: str | None = None
    phone: str | None = None
    address: str | None = None
    hours: str | None = None


class NotificationReadIn(BaseModel):
    notification_id: int | None = None


class ResearchIn(BaseModel):
    dish: str


class BuyerItemIn(BaseModel):
    product_id: int
    quantity: float


class BuyerOrderIn(BaseModel):
    customer_name: str
    phone: str
    address: str | None = None
    order_type: str = "Delivery"
    payment_method: str = "Cash"
    notes: str | None = None
    delivery_date: str | None = None
    items: list[BuyerItemIn] = Field(default_factory=list)


# ------------------------------------------------------------------- seller

@router.get("/shop")
def my_shop(request: Request, conn=Depends(get_db)):
    session = current_user(request)
    tenant = _tenant(conn, session["tenant_id"])
    slug = shop_service.shop_slug_for(conn, session["tenant_id"])
    base = str(request.base_url).rstrip("/")
    return {
        "ok": True,
        "slug": slug,
        "shop_url": f"{base}/shop?b={slug}",
        "business": {"name": tenant["name"], "tagline": tenant["tagline"],
                     "phone": tenant["phone"], "address": tenant["address"]},
        "products": shop_service.list_products(conn, session["tenant_id"]),
    }


@router.get("/settings/business")
def get_business(request: Request, conn=Depends(get_db)):
    session = current_user(request)
    tenant = _tenant(conn, session["tenant_id"])
    slug = shop_service.shop_slug_for(conn, session["tenant_id"])
    return {
        "ok": True,
        "name": tenant["name"],
        "tagline": tenant["tagline"],
        "phone": tenant["phone"],
        "address": tenant["address"],
        "hours": tenant["hours"] if "hours" in tenant.keys() else None,
        "slug": slug,
        "support": {"email": "support@nivora.app", "whatsapp": "+60123456789"},
    }


@router.patch("/settings/business")
def patch_business(payload: BusinessIn, request: Request, conn=Depends(get_db)):
    session = current_user(request)
    name = (payload.name or "").strip()
    if not (1 <= len(name) <= 120):
        _fail(400, "invalid_name", "Give the shop a name")
    hours = (payload.hours or "").strip()[:80] or None
    conn.execute(
        "UPDATE tenants SET name = ?, tagline = ?, phone = ?, address = ?, hours = ? WHERE id = ?",
        (name, (payload.tagline or None), (payload.phone or None), (payload.address or None),
         hours, session["tenant_id"]),
    )
    return get_business(request, conn)


@router.get("/products")
def list_products(request: Request, conn=Depends(get_db)):
    session = current_user(request)
    return {"ok": True, "products": shop_service.list_products(conn, session["tenant_id"])}


@router.post("/products")
def create_product(payload: ProductIn, request: Request, conn=Depends(get_db)):
    session = current_user(request)
    try:
        product_id = shop_service.create_product(
            conn, session["tenant_id"], payload.name, payload.price, payload.category,
            payload.description, payload.image_url, payload.recipe_id)
    except shop_service.ShopError as exc:
        _fail(exc.status, exc.code, str(exc))
    return {"ok": True, "product": shop_service.get_product(conn, session["tenant_id"], product_id),
            "products": shop_service.list_products(conn, session["tenant_id"])}


@router.patch("/products/{product_id}")
def patch_product(product_id: int, payload: ProductPatch, request: Request, conn=Depends(get_db)):
    session = current_user(request)
    try:
        product = shop_service.update_product(
            conn, session["tenant_id"], product_id, payload.model_dump(exclude_none=True))
    except shop_service.ShopError as exc:
        _fail(exc.status, exc.code, str(exc))
    return {"ok": True, "product": product,
            "products": shop_service.list_products(conn, session["tenant_id"])}


@router.delete("/products/{product_id}")
def delete_product(product_id: int, request: Request, conn=Depends(get_db)):
    session = current_user(request)
    shop_service.delete_product(conn, session["tenant_id"], product_id)
    return {"ok": True, "products": shop_service.list_products(conn, session["tenant_id"])}


@router.get("/notifications")
def notifications(request: Request, conn=Depends(get_db)):
    session = current_user(request)
    return {
        "ok": True,
        "unread": shop_service.unread_notifications(conn, session["tenant_id"]),
        "notifications": shop_service.list_notifications(conn, session["tenant_id"]),
    }


@router.post("/notifications/read")
def read_notifications(payload: NotificationReadIn, request: Request, conn=Depends(get_db)):
    session = current_user(request)
    shop_service.mark_notifications_read(conn, session["tenant_id"], payload.notification_id)
    return {"ok": True, "unread": shop_service.unread_notifications(conn, session["tenant_id"])}


def _research_missing(settings, conn, tenant: dict, tenant_id: int,
                      dishes: list[str]) -> list[int]:
    """Ask the AI for a recipe for ordered dishes that have none. Saved as ideas."""
    created: list[int] = []
    try:
        missing = shop_service.product_names_without_recipe(conn, tenant_id, list(dict.fromkeys(dishes)))
        for dish in missing[:2]:
            result = Runner(settings).run("research", conn, tenant, 0, dish)
            if not (result.ok and result.payload and result.payload.get("ingredients")):
                continue
            payload = dict(result.payload)
            payload["recipe_name"] = dish
            payload["product_name"] = dish
            payload["items"] = payload.pop("ingredients", [])
            suggestion_id = shop_service.save_suggestion(conn, tenant_id, dish, payload)
            shop_service.add_notification(
                conn, tenant_id, "recipe_idea",
                f"Recipe idea ready: {dish}",
                "Ingredients were researched. Check them, then approve to cost it.",
            )
            created.append(suggestion_id)
    except Exception:
        # Research is a convenience: an order must never fail because of it.
        return created
    return created


def _research_ordered_dishes(settings, db_path: str, tenant_id: int, dishes: list[str]) -> None:
    """Runs after the buyer's response: its own connection, own limits."""
    from ..db import connect

    conn = connect(db_path)
    try:
        row = conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
        if row is None:
            return
        _research_missing(settings, conn, dict(row), tenant_id, dishes)
    finally:
        conn.close()


@router.post("/ai/research")
def research(payload: ResearchIn, request: Request, conn=Depends(get_db)):
    session = current_user(request)
    tenant = _tenant(conn, session["tenant_id"])
    dish = (payload.dish or "").strip()
    if not (2 <= len(dish) <= 120):
        _fail(400, "invalid_dish", "Name the dish you want researched")
    result = Runner(_settings(request)).run("research", conn, tenant, session["user_id"], dish)
    if not result.ok:
        status = int((result.error or {}).get("status") or 400)
        return JSONResponse({"ok": False, **(result.error or {}), "request_id": result.request_id},
                            status_code=status)
    body = {"ok": True, **result.to_dict()}
    if result.payload and result.payload.get("ingredients"):
        payload_out = dict(result.payload)
        payload_out["recipe_name"] = dish
        payload_out["product_name"] = dish
        payload_out["items"] = payload_out.pop("ingredients", [])
        body["suggestion_id"] = shop_service.save_suggestion(
            conn, session["tenant_id"], dish, payload_out)
    return body


@router.get("/recipe-ideas")
def recipe_ideas(request: Request, conn=Depends(get_db)):
    session = current_user(request)
    return {"ok": True, "ideas": shop_service.list_suggestions(conn, session["tenant_id"])}


@router.post("/recipe-ideas/{idea_id}/approve")
def approve_idea(idea_id: int, request: Request, conn=Depends(get_db)):
    session = current_user(request)
    try:
        applied = shop_service.approve_suggestion(conn, session["tenant_id"], idea_id)
    except shop_service.ShopError as exc:
        _fail(exc.status, exc.code, str(exc))
    return {"ok": True, "applied": applied,
            "ideas": shop_service.list_suggestions(conn, session["tenant_id"])}


@router.post("/recipe-ideas/{idea_id}/reject")
def reject_idea(idea_id: int, request: Request, conn=Depends(get_db)):
    session = current_user(request)
    shop_service.reject_suggestion(conn, session["tenant_id"], idea_id)
    return {"ok": True, "ideas": shop_service.list_suggestions(conn, session["tenant_id"])}


# ------------------------------------------------------------------- buyer

@router.get("/public/shops/{slug}")
def public_shop(slug: str, request: Request, conn=Depends(get_db)):
    try:
        return {"ok": True, **shop_service.shop_for_slug(conn, slug)}
    except shop_service.ShopError as exc:
        _fail(exc.status, exc.code, str(exc))


@router.post("/public/shops/{slug}/orders")
def public_order(slug: str, payload: BuyerOrderIn, request: Request,
                 background: BackgroundTasks, conn=Depends(get_db)):
    try:
        shop = shop_service.shop_for_slug(conn, slug)
    except shop_service.ShopError as exc:
        _fail(exc.status, exc.code, str(exc))
    tenant = conn.execute("SELECT * FROM tenants WHERE public_slug = ?", (slug,)).fetchone()
    tenant_id = int(tenant["id"])
    client_host = request.client.host if request.client else "unknown"
    limit = hit(conn, f"nivora:public:{slug}:order:{client_host}", tenant_id, 10, 600)
    if not limit["allowed"]:
        _fail(429, "slow_down", "Too many orders from this device. Try again later.",
              retry_after=limit["retry_after"])
    try:
        result = shop_service.create_buyer_order(conn, tenant_id, payload.model_dump())
    except shop_service.ShopError as exc:
        _fail(exc.status, exc.code, str(exc))
    except models.ValidationError as exc:
        _fail(400, "invalid_order", str(exc))

    dishes = [row["product_name"] for row in conn.execute(
        "SELECT product_name FROM order_items WHERE tenant_id = ? AND order_id = ?",
        (tenant_id, result["order_id"])).fetchall()]
    background.add_task(_research_ordered_dishes, _settings(request),
                        _settings(request).database_path, tenant_id, dishes)
    return {"ok": True, **result, "shop": shop["business"]["name"]}


@router.get("/public/shops/{slug}/orders")
def public_history(slug: str, phone: str, request: Request, conn=Depends(get_db)):
    try:
        shop_service.shop_for_slug(conn, slug)
    except shop_service.ShopError as exc:
        _fail(exc.status, exc.code, str(exc))
    tenant = conn.execute("SELECT id FROM tenants WHERE public_slug = ?", (slug,)).fetchone()
    client_host = request.client.host if request.client else "unknown"
    limit = hit(conn, f"nivora:public:{slug}:history:{client_host}", int(tenant["id"]), 40, 60)
    if not limit["allowed"]:
        _fail(429, "slow_down", "Too many lookups. Try again in a minute.",
              retry_after=limit["retry_after"])
    return {"ok": True, "orders": shop_service.buyer_history(conn, int(tenant["id"]), phone)}
