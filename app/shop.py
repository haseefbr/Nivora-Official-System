"""The shop: products, buyer orders, notifications and recipe suggestions."""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from .db import tx
from .money import D, money, q, s, hq
from .security import iso
from .models import (
    append_message,
    apply_costing,
    create_customer,
    create_order,
    create_thread,
    get_recipe_row,
)


class ShopError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


# ----------------------------------------------------------------- products

def list_products(conn, tenant_id: int, active_only: bool = False) -> list[dict]:
    sql = "SELECT * FROM products WHERE tenant_id = ?"
    values: list = [tenant_id]
    if active_only:
        sql += " AND active = 1"
    sql += " ORDER BY sort_order, name"
    rows = conn.execute(sql, values).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["price"] = s(row["price"])
        item["active"] = bool(row["active"])
        out.append(item)
    return out


def create_product(conn, tenant_id: int, name: str, price, category: str = "Food",
                   description: str | None = None, image_url: str | None = None,
                   recipe_id: int | None = None) -> int:
    name = (name or "").strip()
    if not name:
        raise ShopError("invalid_product", "A menu item needs a name")
    value = D(price)
    if value < 0:
        raise ShopError("invalid_product", "The price cannot be negative")
    if recipe_id is not None:
        get_recipe_row(conn, tenant_id, int(recipe_id))
    with tx(conn):
        cur = conn.execute(
            "INSERT INTO products (tenant_id, name, category, price, description, image_url,"
            " recipe_id, active, sort_order, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (tenant_id, name[:120], (category or "Food")[:40], s(value),
             (description or "")[:400] or None, (image_url or "")[:500] or None,
             recipe_id, 1, 0, iso()),
        )
    return int(cur.lastrowid)


def update_product(conn, tenant_id: int, product_id: int, fields: dict) -> dict:
    get_product(conn, tenant_id, product_id)
    sets, values = [], []
    for key in ("name", "category", "description", "image_url"):
        if key in fields and fields[key] is not None:
            sets.append(f"{key} = ?")
            values.append(str(fields[key])[:400])
    if "price" in fields and fields["price"] is not None:
        value = D(fields["price"])
        if value < 0:
            raise ShopError("invalid_product", "The price cannot be negative")
        sets.append("price = ?")
        values.append(s(value))
    if "active" in fields and fields["active"] is not None:
        sets.append("active = ?")
        values.append(1 if fields["active"] else 0)
    if "recipe_id" in fields and fields["recipe_id"] is not None:
        get_recipe_row(conn, tenant_id, int(fields["recipe_id"]))
        sets.append("recipe_id = ?")
        values.append(int(fields["recipe_id"]))
    if sets:
        values.extend([tenant_id, product_id])
        conn.execute(f"UPDATE products SET {', '.join(sets)} WHERE tenant_id = ? AND id = ?", values)
    return get_product(conn, tenant_id, product_id)


def get_product(conn, tenant_id: int, product_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM products WHERE tenant_id = ? AND id = ?", (tenant_id, product_id)
    ).fetchone()
    if not row:
        raise ShopError("not_found", "Menu item not found", 404)
    item = dict(row)
    item["price"] = s(row["price"])
    item["active"] = bool(row["active"])
    return item


def delete_product(conn, tenant_id: int, product_id: int) -> None:
    conn.execute("DELETE FROM products WHERE tenant_id = ? AND id = ?", (tenant_id, product_id))


# ------------------------------------------------------------- public shop

def shop_for_slug(conn, slug: str) -> dict:
    tenant = conn.execute("SELECT * FROM tenants WHERE public_slug = ?", (slug,)).fetchone()
    if tenant is None:
        raise ShopError("not_found", "This shop link is not valid", 404)
    products = list_products(conn, int(tenant["id"]), active_only=True)
    categories: list[str] = []
    for product in products:
        if product["category"] not in categories:
            categories.append(product["category"])
    return {
        "business": {
            "name": tenant["name"],
            "tagline": tenant["tagline"],
            "phone": tenant["phone"],
            "address": tenant["address"],
        },
        "slug": slug,
        "products": products,
        "categories": categories,
        "delivery_fee": "4.00",
        "currency": "RM",
    }


def create_buyer_order(conn, tenant_id: int, payload: dict) -> dict:
    """A buyer's basket becomes an order, a customer, a chat thread and a bell."""
    name = (payload.get("customer_name") or "").strip()
    phone = (payload.get("phone") or "").strip()
    if not name:
        raise ShopError("invalid_order", "Please give your name")
    if len(phone) < 8:
        raise ShopError("invalid_order", "Please give a phone number we can reach you on")
    raw_items = payload.get("items") or []
    if not raw_items:
        raise ShopError("invalid_order", "Your basket is empty")

    prepared = []
    for entry in raw_items:
        product_id = int(entry.get("product_id") or 0)
        product = conn.execute(
            "SELECT * FROM products WHERE tenant_id = ? AND id = ? AND active = 1",
            (tenant_id, product_id),
        ).fetchone()
        if product is None:
            raise ShopError("invalid_item", "One of those dishes is no longer on the menu")
        quantity = D(entry.get("quantity") or 0)
        if quantity <= 0:
            raise ShopError("invalid_order", "Every dish needs a quantity above 0")
        prepared.append({
            "product_name": product["name"],
            "quantity": quantity,
            "unit": "biji",
            "unit_price": D(product["price"]),
            "recipe_id": product["recipe_id"],
            "product_id": int(product["id"]),
        })

    order_type = (payload.get("order_type") or "Delivery").strip()[:20]
    delivery_fee = D(payload.get("delivery_fee") or "4.00")
    if order_type.lower().startswith("pickup"):
        delivery_fee = Decimal("0")
    payment_method = (payload.get("payment_method") or "Cash").strip()[:30]
    notes = (payload.get("notes") or "").strip()
    delivery_date = payload.get("delivery_date") or date.today().isoformat()
    try:
        delivery_date = date.fromisoformat(str(delivery_date)[:10]).isoformat()
    except ValueError as exc:
        raise ShopError("invalid_order", "Choose a valid delivery date") from exc
    if delivery_date < date.today().isoformat():
        raise ShopError("invalid_order", "That delivery date has already passed")

    customer = conn.execute(
        "SELECT id FROM customers WHERE tenant_id = ? AND (phone_number = ? OR lower(name) = lower(?))"
        " ORDER BY id LIMIT 1",
        (tenant_id, phone, name),
    ).fetchone()
    customer_id = int(customer["id"]) if customer else create_customer(
        conn, tenant_id, name, phone, address=payload.get("address"))

    order_id = create_order(
        conn, tenant_id, customer_id, delivery_date, payload.get("address"),
        [{"product_name": p["product_name"], "quantity": p["quantity"], "unit": "biji",
          "unit_price": p["unit_price"], "recipe_id": p["recipe_id"]} for p in prepared],
        source="buyer",
        notes=f"{order_type} · {payment_method}" + (f" · {notes}" if notes else ""),
    )
    if delivery_fee > 0:
        conn.execute("UPDATE orders SET delivery_fee = ? WHERE tenant_id = ? AND id = ?",
                     (s(delivery_fee), tenant_id, order_id))

    items_total = sum((p["quantity"] * p["unit_price"] for p in prepared), Decimal("0"))
    total = money(items_total + delivery_fee)

    thread = conn.execute(
        "SELECT id, public_token FROM message_threads WHERE tenant_id = ? AND customer_id = ?"
        " ORDER BY id LIMIT 1",
        (tenant_id, customer_id),
    ).fetchone()
    if thread is None:
        thread_row = create_thread(conn, tenant_id, customer_id, name)
        thread_id, token = int(thread_row["id"]), thread_row["public_token"]
    else:
        thread_id, token = int(thread["id"]), thread["public_token"]

    summary = ", ".join(f"{hq(p['quantity'])} × {p['product_name']}" for p in prepared)
    append_message(conn, tenant_id, thread_id, "in", "customer",
                   f"Order {reference(order_id)}: {summary}. {order_type} on {delivery_date}. "
                   f"Total RM{total}.")

    add_notification(
        conn, tenant_id, "buyer_order",
        f"New order from {name}",
        f"{summary} · RM{total} · {order_type} {delivery_date}",
        order_id=order_id, thread_id=thread_id,
    )

    return {
        "reference": reference(order_id),
        "order_id": order_id,
        "total": s(total),
        "items_total": s(items_total),
        "delivery_fee": s(delivery_fee),
        "delivery_date": delivery_date,
        "thread_token": token,
        "status": "received",
    }


def reference(order_id: int) -> str:
    return f"NIV-{order_id:04d}"


def buyer_history(conn, tenant_id: int, phone: str) -> list[dict]:
    rows = conn.execute(
        """SELECT o.id, o.delivery_date, o.status, o.payment_status, o.delivery_fee, o.created_at,
                  (SELECT COALESCE(SUM(CAST(oi.quantity AS REAL) * CAST(oi.unit_price AS REAL)), 0)
                     FROM order_items oi WHERE oi.tenant_id = o.tenant_id AND oi.order_id = o.id) AS items_total
           FROM orders o JOIN customers c ON c.id = o.customer_id AND c.tenant_id = o.tenant_id
           WHERE o.tenant_id = ? AND (c.phone_number = ? OR replace(c.phone_number, '-', '') = replace(?, '-', ''))
           ORDER BY o.id DESC LIMIT 20""",
        (tenant_id, phone, phone),
    ).fetchall()
    out = []
    for row in rows:
        items = conn.execute(
            "SELECT product_name, quantity, unit_price FROM order_items WHERE tenant_id = ? AND order_id = ?",
            (tenant_id, row["id"]),
        ).fetchall()
        out.append({
            "reference": reference(row["id"]),
            "delivery_date": row["delivery_date"],
            "status": row["status"],
            "payment_status": row["payment_status"],
            "total": s(D(row["items_total"]) + D(row["delivery_fee"])),
            "items": [{"product_name": i["product_name"], "quantity": hq(i["quantity"]),
                       "unit_price": s(i["unit_price"])} for i in items],
            "created_at": row["created_at"],
        })
    return out


def shop_slug_for(conn, tenant_id: int) -> str:
    row = conn.execute("SELECT public_slug FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
    return row["public_slug"] if row else ""


# ------------------------------------------------------------ notifications

def add_notification(conn, tenant_id: int, kind: str, title: str, body: str | None = None,
                     order_id: int | None = None, thread_id: int | None = None) -> int:
    with tx(conn):
        cur = conn.execute(
            "INSERT INTO notifications (tenant_id, kind, title, body, order_id, thread_id, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (tenant_id, kind[:30], title[:160], (body or "")[:300] or None,
             order_id, thread_id, iso()),
        )
    return int(cur.lastrowid)


def list_notifications(conn, tenant_id: int, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM notifications WHERE tenant_id = ? ORDER BY id DESC LIMIT ?",
        (tenant_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def unread_notifications(conn, tenant_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM notifications WHERE tenant_id = ? AND read_at IS NULL",
        (tenant_id,),
    ).fetchone()
    return int(row["n"])


def mark_notifications_read(conn, tenant_id: int, notification_id: int | None = None) -> None:
    if notification_id:
        conn.execute(
            "UPDATE notifications SET read_at = ? WHERE tenant_id = ? AND id = ? AND read_at IS NULL",
            (iso(), tenant_id, notification_id),
        )
    else:
        conn.execute(
            "UPDATE notifications SET read_at = ? WHERE tenant_id = ? AND read_at IS NULL",
            (iso(), tenant_id),
        )


# ------------------------------------------------------- recipe suggestions

def save_suggestion(conn, tenant_id: int, dish: str, payload: dict) -> int:
    with tx(conn):
        cur = conn.execute(
            "INSERT INTO recipe_suggestions (tenant_id, dish, payload_json, status, created_at)"
            " VALUES (?,?,?,?,?)",
            (tenant_id, dish[:120], json.dumps(payload, ensure_ascii=False), "pending", iso()),
        )
    return int(cur.lastrowid)


def list_suggestions(conn, tenant_id: int, status: str = "pending") -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM recipe_suggestions WHERE tenant_id = ? AND status = ? ORDER BY id DESC LIMIT 50",
        (tenant_id, status),
    ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["payload"] = json.loads(row["payload_json"])
        item.pop("payload_json", None)
        out.append(item)
    return out


def approve_suggestion(conn, tenant_id: int, suggestion_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM recipe_suggestions WHERE tenant_id = ? AND id = ?", (tenant_id, suggestion_id)
    ).fetchone()
    if row is None:
        raise ShopError("not_found", "That suggestion is gone", 404)
    if row["status"] != "pending":
        raise ShopError("already_handled", "That suggestion was already handled")
    payload = json.loads(row["payload_json"])
    applied = apply_costing(conn, tenant_id, payload)
    conn.execute(
        "UPDATE recipe_suggestions SET status = 'approved', recipe_id = ? WHERE tenant_id = ? AND id = ?",
        (applied.get("recipe_id"), tenant_id, suggestion_id),
    )
    if applied.get("recipe_id"):
        product = conn.execute(
            "SELECT id FROM products WHERE tenant_id = ? AND lower(name) = lower(?)",
            (tenant_id, row["dish"]),
        ).fetchone()
        if product:
            conn.execute("UPDATE products SET recipe_id = ? WHERE tenant_id = ? AND id = ?",
                         (applied["recipe_id"], tenant_id, product["id"]))
    return applied


def reject_suggestion(conn, tenant_id: int, suggestion_id: int) -> None:
    conn.execute(
        "UPDATE recipe_suggestions SET status = 'rejected' WHERE tenant_id = ? AND id = ?",
        (tenant_id, suggestion_id),
    )


def product_names_without_recipe(conn, tenant_id: int, names: list[str]) -> list[str]:
    missing = []
    for name in names:
        row = conn.execute(
            "SELECT id, recipe_id FROM products WHERE tenant_id = ? AND lower(name) = lower(?)",
            (tenant_id, name),
        ).fetchone()
        if row is None:
            recipe = conn.execute(
                "SELECT id FROM recipes WHERE tenant_id = ? AND lower(product_name) = lower(?)",
                (tenant_id, name),
            ).fetchone()
            if recipe is None:
                missing.append(name)
        elif not row["recipe_id"]:
            recipe = conn.execute(
                "SELECT id FROM recipes WHERE tenant_id = ? AND lower(product_name) = lower(?)",
                (tenant_id, name),
            ).fetchone()
            if recipe is None:
                missing.append(name)
            else:
                conn.execute("UPDATE products SET recipe_id = ? WHERE tenant_id = ? AND id = ?",
                             (recipe["id"], tenant_id, row["id"]))
    return missing
