"""Roles, the permission matrix and tenants. Deny by default.

Every /api route must appear in ROUTE_RULES with the permission it needs.
A request to an /api route that has no rule is refused, even if it is signed in.
"""
from __future__ import annotations

import re
import sqlite3

from .db import connect
from .security import load_session

ROLES = ("OWNER",)

PERMISSIONS = {
    "f:AI MESSAGE PARSER": "AI MESSAGE PARSER",
    "f:Order Management Dashboard": "Order Management Dashboard",
    "f:Recipe & Ingredient Costing": "Recipe & Ingredient Costing",
    "f:Production Planning": "Production Planning",
    "f:Automatic Grocery List": "Automatic Grocery List",
    "f:Profit & Loss Calculator": "Profit & Loss Calculator",
    "f:Customer Database": "Customer Database",
    "f:Payment Status Tracker": "Payment Status Tracker",
    "f:MESSAGE BOX": "MESSAGE BOX",
    "team": "Manage team and roles",
    "billing": "Billing and plan",
    "bot": "Shop assistant",
    "settings": "Business settings",
    "ai": "AI settings",
    "usage": "Usage and logs",
    "export": "Export data",
}

MATRIX: dict[str, set[str]] = {
    "OWNER": set(PERMISSIONS.keys()),
}


def has_permission(role: str | None, permission: str | None) -> bool:
    if not role or not permission:
        return False
    return permission in MATRIX.get(role, set())


# (method, regex, permission). Longest path wins; no entry = refused.
ROUTE_RULES: list[tuple[str, str, str]] = [
    ("GET", r"^/api/me$", "settings"),
    ("GET", r"^/api/dashboard$", "f:Order Management Dashboard"),
    ("GET", r"^/api/orders$", "f:Order Management Dashboard"),
    ("POST", r"^/api/orders$", "f:Order Management Dashboard"),
    ("GET", r"^/api/orders/\d+$", "f:Order Management Dashboard"),
    ("PATCH", r"^/api/orders/\d+$", "f:Order Management Dashboard"),
    ("PATCH", r"^/api/orders/\d+/payment$", "f:Payment Status Tracker"),
    ("DELETE", r"^/api/orders/\d+$", "f:Order Management Dashboard"),
    ("GET", r"^/api/orders/\d+/profit$", "f:Profit & Loss Calculator"),
    ("GET", r"^/api/profit$", "f:Profit & Loss Calculator"),
    ("GET", r"^/api/customers$", "f:Customer Database"),
    ("POST", r"^/api/customers$", "f:Customer Database"),
    ("GET", r"^/api/customers/\d+$", "f:Customer Database"),
    ("PATCH", r"^/api/customers/\d+$", "f:Customer Database"),
    ("GET", r"^/api/ingredients$", "f:Recipe & Ingredient Costing"),
    ("POST", r"^/api/ingredients$", "f:Recipe & Ingredient Costing"),
    ("PATCH", r"^/api/ingredients/\d+$", "f:Recipe & Ingredient Costing"),
    ("DELETE", r"^/api/ingredients/\d+$", "f:Recipe & Ingredient Costing"),
    ("GET", r"^/api/recipes$", "f:Recipe & Ingredient Costing"),
    ("POST", r"^/api/recipes$", "f:Recipe & Ingredient Costing"),
    ("GET", r"^/api/recipes/\d+$", "f:Recipe & Ingredient Costing"),
    ("PATCH", r"^/api/recipes/\d+$", "f:Recipe & Ingredient Costing"),
    ("DELETE", r"^/api/recipes/\d+$", "f:Recipe & Ingredient Costing"),
    ("POST", r"^/api/recipes/\d+/items$", "f:Recipe & Ingredient Costing"),
    ("GET", r"^/api/production$", "f:Production Planning"),
    ("GET", r"^/api/grocery$", "f:Automatic Grocery List"),
    ("GET", r"^/api/threads$", "f:MESSAGE BOX"),
    ("POST", r"^/api/threads$", "f:MESSAGE BOX"),
    ("GET", r"^/api/threads/\d+$", "f:MESSAGE BOX"),
    ("POST", r"^/api/threads/\d+/reply$", "f:MESSAGE BOX"),
    ("POST", r"^/api/bot/chat$", "bot"),
    ("POST", r"^/api/ai/parse$", "f:AI MESSAGE PARSER"),
    ("POST", r"^/api/ai/parse/\d+/approve$", "f:AI MESSAGE PARSER"),
    ("POST", r"^/api/ai/parse/\d+/reject$", "f:AI MESSAGE PARSER"),
    ("GET", r"^/api/ai/drafts$", "f:AI MESSAGE PARSER"),
    ("POST", r"^/api/ai/costing$", "f:Recipe & Ingredient Costing"),
    ("GET", r"^/api/usage$", "usage"),
    ("GET", r"^/api/ai/settings$", "ai"),
    ("PATCH", r"^/api/ai/settings$", "ai"),
    ("GET", r"^/api/billing$", "billing"),
    ("POST", r"^/api/billing/checkout$", "billing"),
    ("GET", r"^/api/export$", "export"),
    ("GET", r"^/api/team$", "team"),
    ("POST", r"^/api/team$", "team"),
    ("PATCH", r"^/api/team/\d+/role$", "team"),
    ("GET", r"^/api/shop$", "settings"),
    ("GET", r"^/api/settings/business$", "settings"),
    ("PATCH", r"^/api/settings/business$", "settings"),
    ("GET", r"^/api/products$", "settings"),
    ("POST", r"^/api/products$", "settings"),
    ("PATCH", r"^/api/products/\d+$", "settings"),
    ("DELETE", r"^/api/products/\d+$", "settings"),
    ("GET", r"^/api/notifications$", "f:Order Management Dashboard"),
    ("POST", r"^/api/notifications/read$", "f:Order Management Dashboard"),
    ("POST", r"^/api/ai/research$", "f:Recipe & Ingredient Costing"),
    ("GET", r"^/api/recipe-ideas$", "f:Recipe & Ingredient Costing"),
    ("POST", r"^/api/recipe-ideas/\d+/approve$", "f:Recipe & Ingredient Costing"),
    ("POST", r"^/api/recipe-ideas/\d+/reject$", "f:Recipe & Ingredient Costing"),
]

# Routes anyone may reach (with their own guards inside).
PUBLIC_PREFIXES = (
    "/api/health",
    "/api/auth/",
    "/api/public/",
    "/api/billing/webhook",
    "/api/meta",
)

_COMPILED = [(method, re.compile(pattern), perm) for method, pattern, perm in ROUTE_RULES]


def rule_for(method: str, path: str) -> str | None:
    best: tuple[int, str] | None = None
    for m, pattern, perm in _COMPILED:
        if m != method and m != "*":
            continue
        match = pattern.match(path)
        if match:
            length = match.end() - match.start()
            if best is None or length > best[0]:
                best = (length, perm)
    return best[1] if best else None


def is_public(path: str) -> bool:
    return any(path == p.rstrip("/") or path.startswith(p) for p in PUBLIC_PREFIXES)


def tenant_scope(tenant_id: int) -> tuple[int]:
    """Every query takes exactly one tenant id. No exceptions."""
    if not isinstance(tenant_id, int) or tenant_id <= 0:
        raise PermissionError("Missing tenant")
    return (tenant_id,)


def assert_same_tenant(row: sqlite3.Row | dict | None, tenant_id: int) -> None:
    if row is None:
        raise PermissionError("Not found")
    value = row["tenant_id"] if not isinstance(row, dict) else row.get("tenant_id")
    if int(value) != int(tenant_id):
        raise PermissionError("Not found")


def members(conn: sqlite3.Connection, tenant_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, email, full_name, phone, role, email_verified, disabled, created_at"
        " FROM users WHERE tenant_id = ? ORDER BY id",
        (tenant_id,),
    ).fetchall()
