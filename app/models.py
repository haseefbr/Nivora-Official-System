"""Every query in the app: tenant-scoped, Decimal money, nothing half-saved."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING

from .db import tx
from .money import D, SIX, money, pct, q, qty, s
from .security import iso, now
from .ai.text import normalize as norm_text

ORDER_STATUSES = ("draft", "active", "done", "cancelled")
PAYMENT_STATUSES = ("unpaid", "deposit", "paid")


class NotFound(Exception):
    pass


class ValidationError(Exception):
    pass


def _today() -> date:
    return now().date()


def parse_day(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError as exc:
        raise ValidationError("Use a date like 2026-10-24") from exc


# ---------------------------------------------------------------- customers

def create_customer(conn, tenant_id: int, name: str, phone_number: str | None = None,
                    email: str | None = None, address: str | None = None,
                    notes: str | None = None) -> int:
    name = (name or "").strip()
    if not name:
        raise ValidationError("A customer needs a name")
    with tx(conn):
        cur = conn.execute(
            "INSERT INTO customers (tenant_id, name, phone_number, email, address, notes, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (tenant_id, name[:120], (phone_number or "")[:40] or None,
             (email or "")[:254] or None, (address or "")[:500] or None,
             (notes or "")[:1000] or None, iso()),
        )
    return int(cur.lastrowid)


def list_customers(conn, tenant_id: int, search: str = "") -> list[dict]:
    if search:
        rows = conn.execute(
            "SELECT * FROM customers WHERE tenant_id = ? AND (name LIKE ? OR phone_number LIKE ? OR email LIKE ?)"
            " ORDER BY name LIMIT 200",
            (tenant_id, f"%{search}%", f"%{search}%", f"%{search}%"),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM customers WHERE tenant_id = ? ORDER BY name LIMIT 200", (tenant_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_customer(conn, tenant_id: int, customer_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM customers WHERE tenant_id = ? AND id = ?", (tenant_id, customer_id)
    ).fetchone()
    if not row:
        raise NotFound("Customer not found")
    return dict(row)


def update_customer(conn, tenant_id: int, customer_id: int, fields: dict) -> dict:
    allowed = {"name", "phone_number", "email", "address", "notes"}
    sets, values = [], []
    for key, value in fields.items():
        if key in allowed and value is not None:
            sets.append(f"{key} = ?")
            values.append(str(value)[:1000])
    if sets:
        values.extend([tenant_id, customer_id])
        conn.execute(
            f"UPDATE customers SET {', '.join(sets)} WHERE tenant_id = ? AND id = ?", values
        )
    return get_customer(conn, tenant_id, customer_id)


def customer_history(conn, tenant_id: int, customer_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT id, delivery_date, status, payment_status, created_at FROM orders"
        " WHERE tenant_id = ? AND customer_id = ? ORDER BY created_at DESC LIMIT 100",
        (tenant_id, customer_id),
    ).fetchall()
    return [dict(r) for r in rows]


# -------------------------------------------------------------- ingredients

def create_ingredient(conn, tenant_id: int, name: str, unit: str, pack_price, pack_size,
                      supplier: str | None = None) -> int:
    name = (name or "").strip()
    unit = (unit or "").strip().lower()
    if not name or not unit:
        raise ValidationError("An ingredient needs a name and a unit")
    pack_price, pack_size = D(pack_price), D(pack_size)
    if pack_price < 0 or pack_size <= 0:
        raise ValidationError("Pack price must be 0 or more, and pack size above 0")
    with tx(conn):
        cur = conn.execute(
            "INSERT INTO ingredients (tenant_id, name, unit, pack_price, pack_size, supplier, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (tenant_id, name[:120], unit[:12], s(pack_price), q(pack_size),
             (supplier or "")[:120] or None, iso()),
        )
    return int(cur.lastrowid)


def list_ingredients(conn, tenant_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM ingredients WHERE tenant_id = ? ORDER BY name", (tenant_id,)
    ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["cost_per_unit"] = str((D(row["pack_price"]) / D(row["pack_size"])).quantize(SIX).normalize())
        out.append(item)
    return out


def get_ingredient(conn, tenant_id: int, ingredient_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM ingredients WHERE tenant_id = ? AND id = ?", (tenant_id, ingredient_id)
    ).fetchone()
    if not row:
        raise NotFound("Ingredient not found")
    return row


def update_ingredient(conn, tenant_id: int, ingredient_id: int, fields: dict) -> dict:
    get_ingredient(conn, tenant_id, ingredient_id)
    sets, values = [], []
    for key in ("name", "unit", "supplier"):
        if key in fields and fields[key] is not None:
            sets.append(f"{key} = ?")
            values.append(str(fields[key])[:120])
    for key in ("pack_price", "pack_size"):
        if key in fields and fields[key] is not None:
            value = D(fields[key])
            if value < 0 or (key == "pack_size" and value <= 0):
                raise ValidationError("Pack price must be 0 or more, and pack size above 0")
            sets.append(f"{key} = ?")
            values.append(s(value) if key == "pack_price" else q(value))
    if sets:
        values.extend([tenant_id, ingredient_id])
        conn.execute(f"UPDATE ingredients SET {', '.join(sets)} WHERE tenant_id = ? AND id = ?", values)
    row = get_ingredient(conn, tenant_id, ingredient_id)
    item = dict(row)
    item["cost_per_unit"] = s(D(row["pack_price"]) / D(row["pack_size"]))
    return item


def delete_ingredient(conn, tenant_id: int, ingredient_id: int) -> None:
    used = conn.execute(
        "SELECT COUNT(*) AS n FROM recipe_items WHERE tenant_id = ? AND ingredient_id = ?",
        (tenant_id, ingredient_id),
    ).fetchone()["n"]
    if used:
        raise ValidationError("This ingredient is used by a recipe; remove it there first")
    conn.execute("DELETE FROM ingredients WHERE tenant_id = ? AND id = ?", (tenant_id, ingredient_id))


# ------------------------------------------------------------------ recipes

def create_recipe(conn, tenant_id: int, name: str, product_name: str, yield_units: int,
                  sell_price=0, notes: str | None = None,
                  items: list[dict] | None = None) -> int:
    name = (name or "").strip()
    product_name = (product_name or name).strip()
    if not name or not product_name:
        raise ValidationError("A recipe needs a name and a product name")
    try:
        yield_units = int(yield_units)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Yield must be a whole number of units") from exc
    if yield_units <= 0:
        raise ValidationError("Yield must be at least 1 unit")
    with tx(conn):
        cur = conn.execute(
            "INSERT INTO recipes (tenant_id, name, product_name, yield_units, sell_price, notes, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (tenant_id, name[:120], product_name[:120], yield_units, s(sell_price),
             (notes or "")[:1000] or None, iso()),
        )
        recipe_id = int(cur.lastrowid)
        for item in items or []:
            _insert_recipe_item(conn, tenant_id, recipe_id, item)
    return recipe_id


def _insert_recipe_item(conn, tenant_id: int, recipe_id: int, item: dict) -> None:
    ingredient_id = int(item.get("ingredient_id") or 0)
    get_ingredient(conn, tenant_id, ingredient_id)
    amount = qty(item.get("quantity"))
    if amount <= 0:
        raise ValidationError("An ingredient amount must be above 0")
    conn.execute(
        "INSERT INTO recipe_items (tenant_id, recipe_id, ingredient_id, quantity) VALUES (?,?,?,?)",
        (tenant_id, recipe_id, ingredient_id, q(amount)),
    )


def add_recipe_item(conn, tenant_id: int, recipe_id: int, item: dict) -> dict:
    get_recipe_row(conn, tenant_id, recipe_id)
    with tx(conn):
        _insert_recipe_item(conn, tenant_id, recipe_id, item)
    return recipe_detail(conn, tenant_id, recipe_id)


def get_recipe_row(conn, tenant_id: int, recipe_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM recipes WHERE tenant_id = ? AND id = ?", (tenant_id, recipe_id)
    ).fetchone()
    if not row:
        raise NotFound("Recipe not found")
    return row


def recipe_detail(conn, tenant_id: int, recipe_id: int) -> dict:
    row = get_recipe_row(conn, tenant_id, recipe_id)
    items = conn.execute(
        """SELECT ri.id, ri.quantity, i.id AS ingredient_id, i.name AS ingredient,
                  i.unit, i.pack_price, i.pack_size
           FROM recipe_items ri JOIN ingredients i ON i.id = ri.ingredient_id
           WHERE ri.tenant_id = ? AND ri.recipe_id = ? ORDER BY i.name""",
        (tenant_id, recipe_id),
    ).fetchall()
    lines, batch_cost = [], Decimal("0")
    for item in items:
        unit_cost = D(item["pack_price"]) / D(item["pack_size"])
        line_cost = money(D(item["quantity"]) * unit_cost)
        batch_cost += line_cost
        lines.append({
            "id": item["id"],
            "ingredient_id": item["ingredient_id"],
            "ingredient": item["ingredient"],
            "quantity": q(item["quantity"]),
            "unit": item["unit"],
            "cost": s(line_cost),
        })
    batch_cost = money(batch_cost)
    yield_units = int(row["yield_units"])
    unit_cost = money(batch_cost / yield_units)
    sell_price = money(row["sell_price"])
    margin = money(sell_price - unit_cost)
    return {
        "id": row["id"],
        "name": row["name"],
        "product_name": row["product_name"],
        "yield_units": yield_units,
        "sell_price": s(sell_price),
        "notes": row["notes"],
        "items": lines,
        "batch_cost": s(batch_cost),
        "unit_cost": s(unit_cost),
        "margin_per_unit": s(margin),
        "margin_percent": str(pct(margin, sell_price)) if sell_price > 0 else "0.00",
    }


def list_recipes(conn, tenant_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT id, name, product_name, yield_units, sell_price FROM recipes"
        " WHERE tenant_id = ? ORDER BY product_name",
        (tenant_id,),
    ).fetchall()
    out = []
    for row in rows:
        detail = recipe_detail(conn, tenant_id, row["id"])
        out.append({
            "id": row["id"], "name": row["name"], "product_name": row["product_name"],
            "yield_units": row["yield_units"], "sell_price": s(row["sell_price"]),
            "unit_cost": detail["unit_cost"], "margin_per_unit": detail["margin_per_unit"],
            "item_count": len(detail["items"]),
        })
    return out


def recipe_for_product(conn, tenant_id: int, product_name: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM recipes WHERE tenant_id = ? AND lower(product_name) = lower(?)"
        " ORDER BY id LIMIT 1",
        (tenant_id, (product_name or "").strip()),
    ).fetchone()


def update_recipe(conn, tenant_id: int, recipe_id: int, fields: dict) -> dict:
    get_recipe_row(conn, tenant_id, recipe_id)
    sets, values = [], []
    for key in ("name", "product_name", "notes"):
        if key in fields and fields[key] is not None:
            sets.append(f"{key} = ?")
            values.append(str(fields[key])[:120])
    if "yield_units" in fields and fields["yield_units"] is not None:
        value = int(fields["yield_units"])
        if value <= 0:
            raise ValidationError("Yield must be at least 1 unit")
        sets.append("yield_units = ?")
        values.append(value)
    if "sell_price" in fields and fields["sell_price"] is not None:
        sets.append("sell_price = ?")
        values.append(s(fields["sell_price"]))
    if sets:
        values.extend([tenant_id, recipe_id])
        conn.execute(f"UPDATE recipes SET {', '.join(sets)} WHERE tenant_id = ? AND id = ?", values)
    return recipe_detail(conn, tenant_id, recipe_id)


def delete_recipe(conn, tenant_id: int, recipe_id: int) -> None:
    conn.execute("DELETE FROM recipes WHERE tenant_id = ? AND id = ?", (tenant_id, recipe_id))


# ------------------------------------------------------------------- orders

def create_order(conn, tenant_id: int, customer_id: int | None, delivery_date: str | None,
                 address: str | None, items: list[dict], source: str = "manual",
                 notes: str | None = None, status: str = "active") -> int:
    if status not in ORDER_STATUSES:
        raise ValidationError("Unknown order status")
    if not items:
        raise ValidationError("An order needs at least one item")
    delivery_date = parse_day(delivery_date)
    if customer_id:
        get_customer(conn, tenant_id, customer_id)
    prepared = []
    for item in items:
        product_name = (item.get("product_name") or "").strip()
        quantity = qty(item.get("quantity"))
        if not product_name:
            raise ValidationError("Every order item needs a product name")
        if quantity <= 0:
            raise ValidationError("Every order item needs a quantity above 0")
        recipe_id = item.get("recipe_id")
        recipe = None
        if recipe_id:
            recipe = get_recipe_row(conn, tenant_id, int(recipe_id))
        else:
            recipe = recipe_for_product(conn, tenant_id, product_name)
        unit_price = item.get("unit_price")
        if unit_price in (None, ""):
            unit_price = D(recipe["sell_price"]) if recipe else Decimal("0")
        prepared.append({
            "product_name": product_name[:120],
            "quantity": q(quantity),
            "unit": (item.get("unit") or "unit")[:12],
            "unit_price": s(unit_price),
            "recipe_id": int(recipe["id"]) if recipe else None,
        })
    stamp = iso()
    with tx(conn):
        cur = conn.execute(
            "INSERT INTO orders (tenant_id, customer_id, delivery_date, address, status, payment_status,"
            " amount_paid, source, notes, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (tenant_id, customer_id, delivery_date, (address or "")[:500] or None, status,
             "unpaid", "0.00", source[:20], (notes or "")[:1000] or None, stamp, stamp),
        )
        order_id = int(cur.lastrowid)
        for item in prepared:
            conn.execute(
                "INSERT INTO order_items (tenant_id, order_id, product_name, quantity, unit, unit_price, recipe_id)"
                " VALUES (?,?,?,?,?,?,?)",
                (tenant_id, order_id, item["product_name"], item["quantity"], item["unit"],
                 item["unit_price"], item["recipe_id"]),
            )
    return order_id


def get_order(conn, tenant_id: int, order_id: int) -> dict:
    row = conn.execute(
        """SELECT o.*, c.name AS customer_name, c.phone_number AS customer_phone
           FROM orders o LEFT JOIN customers c ON c.id = o.customer_id AND c.tenant_id = o.tenant_id
           WHERE o.tenant_id = ? AND o.id = ?""",
        (tenant_id, order_id),
    ).fetchone()
    if not row:
        raise NotFound("Order not found")
    items = conn.execute(
        "SELECT * FROM order_items WHERE tenant_id = ? AND order_id = ? ORDER BY id",
        (tenant_id, order_id),
    ).fetchall()
    order = dict(row)
    order["items"] = [dict(i) for i in items]
    total = sum((D(i["quantity"]) * D(i["unit_price"]) for i in items), Decimal("0"))
    order["total"] = s(total)
    detail = _order_profit_rows(conn, tenant_id, order_id)
    order["revenue"] = s(detail["revenue"])
    order["cogs"] = s(detail["cogs"])
    order["gross_profit"] = s(detail["gross_profit"])
    return order


def list_orders(conn, tenant_id: int, status: str | None = None, payment: str | None = None,
                delivery_from: str | None = None, delivery_to: str | None = None,
                search: str = "", limit: int = 200) -> list[dict]:
    sql = """SELECT o.id, o.delivery_date, o.status, o.payment_status, o.amount_paid, o.address,
                    o.source, o.created_at, o.customer_id, c.name AS customer_name,
                    (SELECT COUNT(*) FROM order_items oi WHERE oi.tenant_id = o.tenant_id AND oi.order_id = o.id) AS item_count,
                    (SELECT COALESCE(SUM(CAST(oi.quantity AS REAL) * CAST(oi.unit_price AS REAL)), 0)
                       FROM order_items oi WHERE oi.tenant_id = o.tenant_id AND oi.order_id = o.id) AS total
             FROM orders o LEFT JOIN customers c ON c.id = o.customer_id AND c.tenant_id = o.tenant_id
             WHERE o.tenant_id = ?"""
    values: list = [tenant_id]
    if status:
        sql += " AND o.status = ?"
        values.append(status)
    if payment:
        sql += " AND o.payment_status = ?"
        values.append(payment)
    if delivery_from:
        sql += " AND o.delivery_date >= ?"
        values.append(parse_day(delivery_from))
    if delivery_to:
        sql += " AND o.delivery_date <= ?"
        values.append(parse_day(delivery_to))
    if search:
        sql += " AND (c.name LIKE ? OR o.address LIKE ? OR EXISTS (SELECT 1 FROM order_items oi2 WHERE oi2.tenant_id = o.tenant_id AND oi2.order_id = o.id AND oi2.product_name LIKE ?))"
        like = f"%{search}%"
        values.extend([like, like, like])
    sql += " ORDER BY COALESCE(o.delivery_date, '9999-12-31'), o.id DESC LIMIT ?"
    values.append(max(1, min(int(limit), 500)))
    rows = conn.execute(sql, values).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["total"] = s(money(item.get("total") or 0))
        out.append(item)
    return out


def update_order(conn, tenant_id: int, order_id: int, fields: dict) -> dict:
    get_order(conn, tenant_id, order_id)
    sets, values = [], []
    if "status" in fields and fields["status"] is not None:
        if fields["status"] not in ORDER_STATUSES:
            raise ValidationError("Unknown order status")
        sets.append("status = ?")
        values.append(fields["status"])
    for key in ("delivery_date", "address", "notes"):
        if key in fields:
            sets.append(f"{key} = ?")
            value = fields[key]
            if key == "delivery_date":
                value = parse_day(value)
            values.append(value)
    if sets:
        sets.append("updated_at = ?")
        values.append(iso())
        values.extend([tenant_id, order_id])
        conn.execute(f"UPDATE orders SET {', '.join(sets)} WHERE tenant_id = ? AND id = ?", values)
    return get_order(conn, tenant_id, order_id)


def set_payment(conn, tenant_id: int, order_id: int, payment_status: str, amount_paid=None) -> dict:
    if payment_status not in PAYMENT_STATUSES:
        raise ValidationError("Payment status must be unpaid, deposit or paid")
    order = get_order(conn, tenant_id, order_id)
    if amount_paid is None:
        amount_paid = order["total"] if payment_status == "paid" else order["amount_paid"]
    if payment_status == "unpaid":
        amount_paid = "0.00"
    conn.execute(
        "UPDATE orders SET payment_status = ?, amount_paid = ?, updated_at = ?"
        " WHERE tenant_id = ? AND id = ?",
        (payment_status, s(amount_paid), iso(), tenant_id, order_id),
    )
    return get_order(conn, tenant_id, order_id)


def delete_order(conn, tenant_id: int, order_id: int) -> None:
    conn.execute("DELETE FROM orders WHERE tenant_id = ? AND id = ?", (tenant_id, order_id))


def _order_profit_rows(conn, tenant_id: int, order_id: int) -> dict:
    items = conn.execute(
        """SELECT oi.*, r.id AS matched_recipe_id, r.yield_units
           FROM order_items oi
           LEFT JOIN recipes r ON r.id = COALESCE(oi.recipe_id,
                (SELECT r2.id FROM recipes r2 WHERE r2.tenant_id = oi.tenant_id
                   AND lower(r2.product_name) = lower(oi.product_name) LIMIT 1))
             AND r.tenant_id = oi.tenant_id
           WHERE oi.tenant_id = ? AND oi.order_id = ?""",
        (tenant_id, order_id),
    ).fetchall()
    revenue = Decimal("0")
    cogs = Decimal("0")
    lines = []
    for item in items:
        quantity = D(item["quantity"])
        line_revenue = quantity * D(item["unit_price"])
        revenue += line_revenue
        unit_cost = Decimal("0")
        if item["matched_recipe_id"]:
            unit_cost = D(recipe_detail(conn, tenant_id, int(item["matched_recipe_id"]))["unit_cost"])
        line_cost = quantity * unit_cost
        cogs += line_cost
        lines.append({
            "product_name": item["product_name"],
            "quantity": q(quantity),
            "unit_price": s(item["unit_price"]),
            "unit_cost": s(unit_cost),
            "revenue": s(line_revenue),
            "cost": s(line_cost),
            "recipe_id": item["matched_recipe_id"],
        })
    return {
        "revenue": money(revenue),
        "cogs": money(cogs),
        "gross_profit": money(revenue - cogs),
        "lines": lines,
    }


def order_profit(conn, tenant_id: int, order_id: int, fee_ratio=Decimal("0")) -> dict:
    order = get_order(conn, tenant_id, order_id)
    rows = _order_profit_rows(conn, tenant_id, order_id)
    fees = money(rows["revenue"] * D(fee_ratio))
    net = money(rows["gross_profit"] - fees)
    return {
        "order_id": order_id,
        "customer_name": order.get("customer_name"),
        "delivery_date": order.get("delivery_date"),
        "revenue": s(rows["revenue"]),
        "cogs": s(rows["cogs"]),
        "gross_profit": s(rows["gross_profit"]),
        "fees": s(fees),
        "net_profit": s(net),
        "margin_percent": str(pct(net, rows["revenue"])),
        "lines": rows["lines"],
        "missing_recipes": [l["product_name"] for l in rows["lines"] if not l["recipe_id"]],
    }


def profit_report(conn, tenant_id: int, start: str | None, end: str | None,
                  fee_ratio=Decimal("0")) -> dict:
    orders = list_orders(conn, tenant_id, delivery_from=start, delivery_to=end, limit=500)
    lines, revenue, cogs = [], Decimal("0"), Decimal("0")
    for row in orders:
        if row["status"] == "cancelled":
            continue
        detail = _order_profit_rows(conn, tenant_id, row["id"])
        revenue += detail["revenue"]
        cogs += detail["cogs"]
        lines.append({
            "order_id": row["id"],
            "customer_name": row["customer_name"],
            "delivery_date": row["delivery_date"],
            "status": row["status"],
            "payment_status": row["payment_status"],
            "revenue": s(detail["revenue"]),
            "cogs": s(detail["cogs"]),
            "net_profit": s(money(detail["revenue"] - detail["cogs"])),
        })
    gross = money(revenue - cogs)
    fees = money(revenue * D(fee_ratio))
    net = money(gross - fees)
    return {
        "start": start, "end": end,
        "revenue": s(revenue), "cogs": s(cogs), "gross_profit": s(gross),
        "fees": s(fees), "net_profit": s(net),
        "margin_percent": str(pct(net, revenue)),
        "orders": lines,
    }


# -------------------------------------------------------------- production

def production_plan(conn, tenant_id: int, day: str) -> dict:
    day = parse_day(day)
    rows = conn.execute(
        """SELECT oi.product_name, oi.unit, oi.quantity, o.id AS order_id
           FROM order_items oi JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
           WHERE oi.tenant_id = ? AND o.delivery_date = ? AND o.status = 'active'
           ORDER BY oi.product_name, o.id""",
        (tenant_id, day),
    ).fetchall()
    grouped: dict[str, dict] = {}
    for row in rows:
        key = row["product_name"].strip().lower()
        bucket = grouped.setdefault(key, {
            "product_name": row["product_name"], "unit": row["unit"],
            "total_quantity": Decimal("0"), "orders": set(),
        })
        bucket["total_quantity"] += D(row["quantity"])
        bucket["orders"].add(row["order_id"])
    items = []
    for bucket in grouped.values():
        recipe = recipe_for_product(conn, tenant_id, bucket["product_name"])
        total = bucket["total_quantity"]
        batches = None
        yield_units = None
        if recipe:
            yield_units = int(recipe["yield_units"])
            batches = int((total / Decimal(yield_units)).to_integral_value(rounding=ROUND_CEILING))
        items.append({
            "product_name": bucket["product_name"],
            "unit": bucket["unit"],
            "total_quantity": q(total),
            "order_count": len(bucket["orders"]),
            "recipe_id": recipe["id"] if recipe else None,
            "yield_units": yield_units,
            "batches": batches,
        })
    return {
        "date": day,
        "items": items,
        "orders": len({r["order_id"] for r in rows}),
        "total_units": q(sum((D(r["quantity"]) for r in rows), Decimal("0"))),
        "missing_recipes": [i["product_name"] for i in items if i["recipe_id"] is None],
    }


def grocery_list(conn, tenant_id: int, start: str, end: str | None = None) -> dict:
    start_day = parse_day(start)
    end_day = parse_day(end or start)
    if end_day < start_day:
        raise ValidationError("The end date is before the start date")
    needed: dict[int, dict] = {}
    days = []
    missing: set[str] = set()
    cursor = date.fromisoformat(start_day)
    last = date.fromisoformat(end_day)
    while cursor <= last:
        plan = production_plan(conn, tenant_id, cursor.isoformat())
        days.append({"date": cursor.isoformat(), "products": len(plan["items"])})
        for item in plan["items"]:
            if not item["recipe_id"] or not item["batches"]:
                missing.add(item["product_name"])
                continue
            detail = recipe_detail(conn, tenant_id, int(item["recipe_id"]))
            recipe_items = conn.execute(
                """SELECT ri.quantity, i.* FROM recipe_items ri
                   JOIN ingredients i ON i.id = ri.ingredient_id
                   WHERE ri.tenant_id = ? AND ri.recipe_id = ?""",
                (tenant_id, item["recipe_id"]),
            ).fetchall()
            for ingredient in recipe_items:
                amount = D(ingredient["quantity"]) * item["batches"]
                bucket = needed.setdefault(int(ingredient["id"]), {
                    "ingredient_id": int(ingredient["id"]),
                    "ingredient": ingredient["name"],
                    "unit": ingredient["unit"],
                    "quantity": Decimal("0"),
                    "pack_price": D(ingredient["pack_price"]),
                    "pack_size": D(ingredient["pack_size"]),
                    "for_products": set(),
                })
                bucket["quantity"] += amount
                bucket["for_products"].add(item["product_name"])
        cursor += timedelta(days=1)
    lines = []
    total = Decimal("0")
    for bucket in needed.values():
        cost = money(bucket["quantity"] * (bucket["pack_price"] / bucket["pack_size"]))
        total += cost
        packs = None
        if bucket["pack_size"] > 0:
            packs = int((bucket["quantity"] / bucket["pack_size"]).to_integral_value(rounding=ROUND_CEILING))
        lines.append({
            "ingredient_id": bucket["ingredient_id"],
            "ingredient": bucket["ingredient"],
            "quantity": q(bucket["quantity"]),
            "unit": bucket["unit"],
            "packs_to_buy": packs,
            "estimated_cost": s(cost),
            "for_products": sorted(bucket["for_products"]),
        })
    lines.sort(key=lambda line: line["ingredient"].lower())
    return {
        "start": start_day, "end": end_day, "days": days,
        "items": lines, "total_cost": s(total),
        "missing_recipes": sorted(missing),
    }


# ------------------------------------------------------------- message box

def create_thread(conn, tenant_id: int, customer_id: int | None, customer_name: str | None) -> dict:
    from .security import new_token
    public_token, _ = new_token()
    with tx(conn):
        cur = conn.execute(
            "INSERT INTO message_threads (tenant_id, customer_id, customer_name, public_token, created_at)"
            " VALUES (?,?,?,?,?)",
            (tenant_id, customer_id, (customer_name or "Customer")[:120], public_token, iso()),
        )
    return get_thread(conn, tenant_id, int(cur.lastrowid))


def get_thread(conn, tenant_id: int, thread_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM message_threads WHERE tenant_id = ? AND id = ?", (tenant_id, thread_id)
    ).fetchone()
    if not row:
        raise NotFound("Conversation not found")
    thread = dict(row)
    messages = conn.execute(
        "SELECT id, direction, author, body, created_at, read_at FROM messages"
        " WHERE tenant_id = ? AND thread_id = ? ORDER BY created_at, id",
        (tenant_id, thread_id),
    ).fetchall()
    thread["messages"] = [dict(m) for m in messages]
    return thread


def thread_by_public_token(conn, token: str) -> dict | None:
    row = conn.execute(
        "SELECT t.*, b.name AS business_name FROM message_threads t"
        " JOIN tenants b ON b.id = t.tenant_id WHERE t.public_token = ?",
        (token,),
    ).fetchone()
    if not row:
        return None
    thread = dict(row)
    thread["messages"] = [
        dict(m) for m in conn.execute(
            "SELECT id, direction, author, body, created_at FROM messages"
            " WHERE tenant_id = ? AND thread_id = ? ORDER BY created_at, id",
            (thread["tenant_id"], thread["id"]),
        ).fetchall()
    ]
    return thread


def list_threads(conn, tenant_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT t.*, c.name AS linked_customer,
                  (SELECT body FROM messages m WHERE m.tenant_id = t.tenant_id AND m.thread_id = t.id
                     ORDER BY m.created_at DESC, m.id DESC LIMIT 1) AS last_body,
                  (SELECT COUNT(*) FROM messages m WHERE m.tenant_id = t.tenant_id AND m.thread_id = t.id
                     AND m.direction = 'in' AND m.read_at IS NULL) AS unread
           FROM message_threads t
           LEFT JOIN customers c ON c.id = t.customer_id AND c.tenant_id = t.tenant_id
           WHERE t.tenant_id = ? ORDER BY COALESCE(t.last_message_at, t.created_at) DESC LIMIT 200""",
        (tenant_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def append_message(conn, tenant_id: int, thread_id: int, direction: str, author: str,
                   body: str) -> dict:
    body = (body or "").strip()
    if not body:
        raise ValidationError("Write a message first")
    if len(body) > 4000:
        raise ValidationError("That message is too long (4000 characters at most)")
    get_thread(conn, tenant_id, thread_id)
    stamp = iso()
    with tx(conn):
        cur = conn.execute(
            "INSERT INTO messages (tenant_id, thread_id, direction, author, body, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (tenant_id, thread_id, direction[:3], author[:20], body, stamp),
        )
        conn.execute(
            "UPDATE message_threads SET last_message_at = ? WHERE tenant_id = ? AND id = ?",
            (stamp, tenant_id, thread_id),
        )
        if direction == "out":
            conn.execute(
                "UPDATE messages SET read_at = ? WHERE tenant_id = ? AND thread_id = ? AND read_at IS NULL",
                (stamp, tenant_id, thread_id),
            )
    return {"id": int(cur.lastrowid), "body": body, "created_at": stamp,
            "direction": direction, "author": author}


def mark_thread_read(conn, tenant_id: int, thread_id: int) -> None:
    conn.execute(
        "UPDATE messages SET read_at = ? WHERE tenant_id = ? AND thread_id = ? AND read_at IS NULL",
        (iso(), tenant_id, thread_id),
    )


def unread_count(conn, tenant_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM messages WHERE tenant_id = ? AND direction = 'in' AND read_at IS NULL",
        (tenant_id,),
    ).fetchone()
    return int(row["n"])


# ---------------------------------------------------------------- AI drafts

def create_draft(conn, tenant_id: int, raw_text: str, payload: dict, confidence: float,
                 needs_human: bool) -> int:
    with tx(conn):
        cur = conn.execute(
            "INSERT INTO parsed_drafts (tenant_id, raw_text, payload_json, confidence, status, needs_human, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (tenant_id, raw_text[:4000], json.dumps(payload, ensure_ascii=False),
             str(money(confidence)), "pending", 1 if needs_human else 0, iso()),
        )
    return int(cur.lastrowid)


def list_drafts(conn, tenant_id: int, status: str = "pending") -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM parsed_drafts WHERE tenant_id = ? AND status = ? ORDER BY id DESC LIMIT 100",
        (tenant_id, status),
    ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["payload"] = json.loads(row["payload_json"])
        item.pop("payload_json", None)
        out.append(item)
    return out


def get_draft(conn, tenant_id: int, draft_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM parsed_drafts WHERE tenant_id = ? AND id = ?", (tenant_id, draft_id)
    ).fetchone()
    if not row:
        raise NotFound("Draft not found")
    item = dict(row)
    item["payload"] = json.loads(row["payload_json"])
    return item


def approve_draft(conn, tenant_id: int, draft_id: int) -> dict:
    """A person approves the parsed draft; only then does an order exist."""
    draft = get_draft(conn, tenant_id, draft_id)
    if draft["status"] != "pending":
        raise ValidationError("This draft was already handled")
    payload = draft["payload"]
    items = []
    for item in payload.get("items") or []:
        items.append({
            "product_name": item.get("product_name"),
            "quantity": item.get("quantity"),
            "unit": item.get("unit") or "unit",
        })
    if not items:
        raise ValidationError("This message holds no order items to approve")
    customer_id = None
    name = (payload.get("customer_name") or "").strip()
    phone = (payload.get("customer_phone") or "").strip()
    if name:
        row = conn.execute(
            "SELECT id FROM customers WHERE tenant_id = ? AND lower(name) = lower(?)",
            (tenant_id, name),
        ).fetchone()
        if row:
            customer_id = int(row["id"])
        else:
            customer_id = create_customer(conn, tenant_id, name, phone or None,
                                          address=payload.get("address"))
    order_id = create_order(
        conn, tenant_id, customer_id, payload.get("delivery_date"), payload.get("address"),
        items, source="parser",
        notes=f"From message: {draft['raw_text'][:200]}",
    )
    conn.execute(
        "UPDATE parsed_drafts SET status = 'approved', order_id = ? WHERE tenant_id = ? AND id = ?",
        (order_id, tenant_id, draft_id),
    )
    return get_order(conn, tenant_id, order_id)


def reject_draft(conn, tenant_id: int, draft_id: int) -> None:
    conn.execute(
        "UPDATE parsed_drafts SET status = 'rejected' WHERE tenant_id = ? AND id = ?",
        (tenant_id, draft_id),
    )


# ---------------------------------------------------------------- AI usage

def month_start_iso() -> str:
    today = _today()
    return datetime(today.year, today.month, 1, tzinfo=timezone.utc).isoformat()


def month_usage(conn, tenant_id: int) -> dict:
    row = conn.execute(
        "SELECT COUNT(*) AS calls, COALESCE(SUM(tokens_in),0) AS tin,"
        " COALESCE(SUM(tokens_out),0) AS tout, COALESCE(SUM(CAST(cost_usd AS REAL)),0) AS cost"
        " FROM ai_calls WHERE tenant_id = ? AND created_at >= ? AND outcome != 'refused'",
        (tenant_id, month_start_iso()),
    ).fetchone()
    return {
        "calls": int(row["calls"]),
        "tokens_in": int(row["tin"]),
        "tokens_out": int(row["tout"]),
        "cost_usd": s(row["cost"]),
    }


def usage_summary(conn, tenant_id: int, budget_rm: Decimal) -> dict:
    usage = month_usage(conn, tenant_id)
    spent = D(usage["cost_usd"])
    ratio = float(spent / budget_rm) if budget_rm > 0 else 0.0
    recent = conn.execute(
        "SELECT request_id, feature, model, provider, tokens_in, tokens_out, cost_usd, duration_ms,"
        " outcome, checks, needs_human, created_at FROM ai_calls WHERE tenant_id = ?"
        " ORDER BY id DESC LIMIT 50",
        (tenant_id,),
    ).fetchall()
    return {
        **usage,
        "budget_usd": s(budget_rm),
        "budget_used_percent": round(ratio * 100, 2),
        "calls_per_day_limit": plan_calls_per_day(conn, tenant_id),
        "recent": [dict(r) for r in recent],
    }


def plan_calls_per_day(conn, tenant_id: int) -> int:
    row = conn.execute(
        "SELECT p.calls_per_day FROM tenants t JOIN plans p ON p.code = t.plan WHERE t.id = ?",
        (tenant_id,),
    ).fetchone()
    return int(row["calls_per_day"]) if row else 56


def month_cost(conn, tenant_id: int) -> Decimal:
    row = conn.execute(
        "SELECT COALESCE(SUM(CAST(cost_usd AS REAL)),0) AS cost FROM ai_calls"
        " WHERE tenant_id = ? AND created_at >= ? AND outcome != 'refused'",
        (tenant_id, month_start_iso()),
    ).fetchone()
    return money(row["cost"])


def add_alert(conn, tenant_id: int, kind: str, message: str) -> None:
    conn.execute(
        "INSERT INTO alerts (tenant_id, kind, message, created_at) VALUES (?,?,?,?)",
        (tenant_id, kind, message[:300], iso()),
    )


# ------------------------------------------------- AI costing -> real recipe

UNIT_FACTORS = {
    "g": ("g", Decimal("1")), "gram": ("g", Decimal("1")), "grams": ("g", Decimal("1")),
    "kg": ("g", Decimal("1000")), "kilogram": ("g", Decimal("1000")),
    "ml": ("ml", Decimal("1")), "liter": ("ml", Decimal("1000")),
    "litre": ("ml", Decimal("1000")), "l": ("ml", Decimal("1000")),
    "biji": ("biji", Decimal("1")), "unit": ("biji", Decimal("1")),
    "pcs": ("biji", Decimal("1")), "pc": ("biji", Decimal("1")),
    "kotak": ("kotak", Decimal("1")), "box": ("kotak", Decimal("1")),
    "paket": ("paket", Decimal("1")), "pack": ("paket", Decimal("1")),
    "batang": ("batang", Decimal("1")), "buku": ("buku", Decimal("1")),
    "dulang": ("dulang", Decimal("1")), "tray": ("dulang", Decimal("1")),
    "lusin": ("lusin", Decimal("1")), "dozen": ("lusin", Decimal("1")),
    "sudu": ("sudu", Decimal("1")), "sudu besar": ("sudu", Decimal("1")),
    "tbsp": ("sudu", Decimal("1")), "tsp": ("sudu", Decimal("1")),
}


def unit_factor(unit: str | None) -> tuple[str, Decimal] | None:
    key = (unit or "").strip().lower()
    return UNIT_FACTORS.get(key)


def convert_amount(amount, unit: str | None, base_unit: str | None) -> Decimal | None:
    source = unit_factor(unit)
    target = unit_factor(base_unit)
    if source is None or target is None or source[0] != target[0]:
        return None
    return D(amount) * source[1] / target[1]


def apply_costing(conn, tenant_id: int, payload: dict) -> dict:
    """Save a parsed recipe against the business's own ingredient prices.

    The model never sets a price: code reads pack price and pack size here.
    """
    rows = conn.execute("SELECT * FROM ingredients WHERE tenant_id = ?", (tenant_id,)).fetchall()
    by_name = {norm_text(row["name"]): row for row in rows}
    lines, matched = [], []
    for item in payload.get("items") or []:
        name = item.get("ingredient") or ""
        key = norm_text(name)
        ingredient = by_name.get(key)
        if ingredient is None:
            for existing_key, row in by_name.items():
                if existing_key and (existing_key in key or key in existing_key):
                    ingredient = row
                    break
        if ingredient is None:
            lines.append({"ingredient": name, "quantity": q(item.get("quantity")),
                          "unit": item.get("unit"), "matched": False,
                          "reason": "No ingredient with this name yet. Add it with its pack price."})
            continue
        amount = convert_amount(item.get("quantity"), item.get("unit"), ingredient["unit"])
        if amount is None:
            lines.append({"ingredient": name, "quantity": q(item.get("quantity")),
                          "unit": item.get("unit"), "matched": False,
                          "reason": f"Unit mismatch: the ingredient is priced per {ingredient['unit']}."})
            continue
        unit_cost = D(ingredient["pack_price"]) / D(ingredient["pack_size"])
        cost = money(amount * unit_cost)
        matched.append({"ingredient_id": int(ingredient["id"]), "quantity": amount})
        lines.append({
            "ingredient": ingredient["name"], "quantity": q(amount), "unit": ingredient["unit"],
            "matched": True, "cost": s(cost),
        })
    recipe_id = None
    if matched:
        existing = conn.execute(
            "SELECT id FROM recipes WHERE tenant_id = ? AND lower(name) = lower(?)",
            (tenant_id, payload.get("recipe_name") or ""),
        ).fetchone()
        if existing:
            recipe_id = int(existing["id"])
            conn.execute("DELETE FROM recipe_items WHERE tenant_id = ? AND recipe_id = ?",
                         (tenant_id, recipe_id))
            conn.execute("UPDATE recipes SET yield_units = ?, product_name = ? WHERE tenant_id = ? AND id = ?",
                         (int(payload.get("yield_units") or 1),
                          (payload.get("product_name") or payload.get("recipe_name") or "Product")[:120],
                          tenant_id, recipe_id))
            with tx(conn):
                for item in matched:
                    conn.execute(
                        "INSERT INTO recipe_items (tenant_id, recipe_id, ingredient_id, quantity)"
                        " VALUES (?,?,?,?)",
                        (tenant_id, recipe_id, item["ingredient_id"], q(item["quantity"])),
                    )
        else:
            recipe_id = create_recipe(
                conn, tenant_id, payload.get("recipe_name") or "Recipe",
                payload.get("product_name") or payload.get("recipe_name") or "Product",
                int(payload.get("yield_units") or 1), 0,
                "Created from a recipe message; check the price per unit.",
                matched,
            )
    total = sum((D(line["cost"]) for line in lines if line.get("matched")), Decimal("0"))
    return {
        "saved": recipe_id is not None,
        "recipe_id": recipe_id,
        "recipe": recipe_detail(conn, tenant_id, recipe_id) if recipe_id else None,
        "lines": lines,
        "unmatched": [line["ingredient"] for line in lines if not line.get("matched")],
        "matched_cost": s(total),
    }
