"""SQLite schema and connection helpers.

Every table carries `id` and `tenant_id`; every query in app/ filters by tenant.
Indexes exist for every list and search (docs/QUALITY.md).
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
-- One business = one tenant. tenant_id on the tenants row equals its own id.
CREATE TABLE IF NOT EXISTS tenants (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id           INTEGER NOT NULL,
    name                TEXT    NOT NULL,
    public_slug         TEXT    NOT NULL UNIQUE,
    plan                TEXT    NOT NULL DEFAULT 'standard',
    ai_provider         TEXT    NOT NULL DEFAULT 'ollama',
    ai_model            TEXT    NOT NULL DEFAULT 'gigalab-local',
    ai_budget_rm        TEXT    NOT NULL DEFAULT '1000.00',
    require_2fa         INTEGER NOT NULL DEFAULT 1,
    terms_version       TEXT,
    terms_accepted_at   TEXT,
    created_at          TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(id),
    email           TEXT    NOT NULL UNIQUE,
    phone           TEXT,
    full_name       TEXT,
    role            TEXT    NOT NULL DEFAULT 'OWNER',
    password_hash   TEXT,
    email_verified  INTEGER NOT NULL DEFAULT 0,
    phone_verified  INTEGER NOT NULL DEFAULT 0,
    totp_secret     TEXT,
    disabled        INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_users_tenant ON users(tenant_id, role);
CREATE INDEX IF NOT EXISTS idx_users_phone ON users(tenant_id, phone);

CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id   INTEGER NOT NULL,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    token_hash  TEXT    NOT NULL UNIQUE,
    csrf_token  TEXT    NOT NULL,
    ip          TEXT,
    user_agent  TEXT,
    created_at  TEXT    NOT NULL,
    expires_at  TEXT    NOT NULL,
    revoked_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(tenant_id, user_id);

CREATE TABLE IF NOT EXISTS auth_tokens (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id   INTEGER NOT NULL,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    kind        TEXT    NOT NULL,           -- magic | reset | phone | verify_email
    token_hash  TEXT    NOT NULL,
    code_hash   TEXT,
    expires_at  TEXT    NOT NULL,
    used_at     TEXT,
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_auth_tokens_lookup ON auth_tokens(tenant_id, kind, token_hash);

CREATE TABLE IF NOT EXISTS login_attempts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id   INTEGER NOT NULL DEFAULT 0,
    identifier  TEXT    NOT NULL,
    kind        TEXT    NOT NULL,
    ok          INTEGER NOT NULL,
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_login_attempts ON login_attempts(identifier, kind, created_at);
CREATE INDEX IF NOT EXISTS idx_login_attempts_tenant ON login_attempts(tenant_id, created_at);

CREATE TABLE IF NOT EXISTS customers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(id),
    name            TEXT    NOT NULL,
    phone_number    TEXT,
    email           TEXT,
    address         TEXT,
    notes           TEXT,
    created_at      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_customers_tenant_name ON customers(tenant_id, name);

CREATE TABLE IF NOT EXISTS ingredients (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id   INTEGER NOT NULL REFERENCES tenants(id),
    name        TEXT    NOT NULL,
    unit        TEXT    NOT NULL,          -- g | kg | ml | l | biji | unit
    pack_price  TEXT    NOT NULL,          -- Decimal, RM
    pack_size   TEXT    NOT NULL,          -- Decimal, in `unit`
    supplier    TEXT,
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ingredients_tenant_name ON ingredients(tenant_id, name);

CREATE TABLE IF NOT EXISTS recipes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id    INTEGER NOT NULL REFERENCES tenants(id),
    name         TEXT    NOT NULL,
    product_name TEXT    NOT NULL,
    yield_units  INTEGER NOT NULL DEFAULT 1,
    sell_price   TEXT    NOT NULL DEFAULT '0.00',
    notes        TEXT,
    created_at   TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_recipes_tenant ON recipes(tenant_id, product_name);

CREATE TABLE IF NOT EXISTS recipe_items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id     INTEGER NOT NULL REFERENCES tenants(id),
    recipe_id     INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    ingredient_id INTEGER NOT NULL REFERENCES ingredients(id),
    quantity      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_recipe_items ON recipe_items(tenant_id, recipe_id);

CREATE TABLE IF NOT EXISTS orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(id),
    customer_id     INTEGER REFERENCES customers(id),
    delivery_date   TEXT,                  -- YYYY-MM-DD
    address         TEXT,
    status          TEXT    NOT NULL DEFAULT 'active',   -- draft | active | done | cancelled
    payment_status  TEXT    NOT NULL DEFAULT 'unpaid',   -- unpaid | deposit | paid
    amount_paid     TEXT    NOT NULL DEFAULT '0.00',
    source          TEXT    NOT NULL DEFAULT 'manual',   -- manual | parser | message
    notes           TEXT,
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_tenant_date ON orders(tenant_id, delivery_date, status);
CREATE INDEX IF NOT EXISTS idx_orders_tenant_status ON orders(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(tenant_id, customer_id);

CREATE TABLE IF NOT EXISTS order_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id    INTEGER NOT NULL REFERENCES tenants(id),
    order_id     INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_name TEXT    NOT NULL,
    quantity     TEXT    NOT NULL,
    unit         TEXT    NOT NULL DEFAULT 'unit',
    unit_price   TEXT    NOT NULL DEFAULT '0.00',
    recipe_id    INTEGER REFERENCES recipes(id)
);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(tenant_id, order_id);
CREATE INDEX IF NOT EXISTS idx_order_items_product ON order_items(tenant_id, product_name);

CREATE TABLE IF NOT EXISTS message_threads (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(id),
    customer_id     INTEGER REFERENCES customers(id),
    customer_name   TEXT,
    public_token    TEXT    NOT NULL UNIQUE,
    last_message_at TEXT,
    created_at      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_threads_tenant ON message_threads(tenant_id, last_message_at);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id   INTEGER NOT NULL REFERENCES tenants(id),
    thread_id   INTEGER NOT NULL REFERENCES message_threads(id) ON DELETE CASCADE,
    direction   TEXT    NOT NULL,          -- in | out
    author      TEXT    NOT NULL,          -- customer | owner
    body        TEXT    NOT NULL,
    created_at  TEXT    NOT NULL,
    read_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(tenant_id, thread_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_unread ON messages(tenant_id, direction, read_at);

CREATE TABLE IF NOT EXISTS parsed_drafts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id    INTEGER NOT NULL REFERENCES tenants(id),
    raw_text     TEXT    NOT NULL,
    payload_json TEXT    NOT NULL,
    confidence   TEXT    NOT NULL DEFAULT '0',
    status       TEXT    NOT NULL DEFAULT 'pending',  -- pending | approved | rejected
    order_id     INTEGER REFERENCES orders(id),
    needs_human  INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_drafts_tenant ON parsed_drafts(tenant_id, status, created_at);

CREATE TABLE IF NOT EXISTS ai_calls (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id     INTEGER NOT NULL,
    request_id    TEXT    NOT NULL,
    feature       TEXT    NOT NULL,
    model         TEXT    NOT NULL,
    provider      TEXT    NOT NULL,
    tokens_in     INTEGER NOT NULL DEFAULT 0,
    tokens_out    INTEGER NOT NULL DEFAULT 0,
    cost_usd      TEXT    NOT NULL DEFAULT '0.00',
    duration_ms   INTEGER NOT NULL DEFAULT 0,
    outcome       TEXT    NOT NULL,        -- ok | repaired | failed | safe_reply | refused
    checks        TEXT    NOT NULL DEFAULT '',
    fallback_used INTEGER NOT NULL DEFAULT 0,
    needs_human   INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ai_calls_tenant_time ON ai_calls(tenant_id, created_at);
CREATE INDEX IF NOT EXISTS idx_ai_calls_outcome ON ai_calls(tenant_id, outcome, created_at);

CREATE TABLE IF NOT EXISTS alerts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id  INTEGER NOT NULL,
    kind       TEXT    NOT NULL,           -- budget_80 | failures | cost | uptime
    message    TEXT    NOT NULL,
    created_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alerts_tenant ON alerts(tenant_id, created_at);

CREATE TABLE IF NOT EXISTS rate_limits (
    key        TEXT    PRIMARY KEY,
    tenant_id  INTEGER NOT NULL,
    count      INTEGER NOT NULL,
    expires_at REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rate_limits_expiry ON rate_limits(expires_at);
CREATE INDEX IF NOT EXISTS idx_rate_limits_tenant ON rate_limits(tenant_id, expires_at);

CREATE TABLE IF NOT EXISTS payments (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id          INTEGER NOT NULL,
    provider_event_id  TEXT    NOT NULL UNIQUE,
    event_type         TEXT    NOT NULL,
    plan               TEXT,
    payload_json       TEXT    NOT NULL,
    created_at         TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_payments_tenant ON payments(tenant_id, created_at);

CREATE TABLE IF NOT EXISTS plans (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id      INTEGER NOT NULL DEFAULT 0,
    code           TEXT    NOT NULL UNIQUE,
    name           TEXT    NOT NULL,
    calls_per_day  INTEGER NOT NULL,
    ai_budget_rm   TEXT    NOT NULL,
    price_rm_month TEXT    NOT NULL
);

-- What the shop sells: the buyer menu, priced.
CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id   INTEGER NOT NULL REFERENCES tenants(id),
    name        TEXT    NOT NULL,
    category    TEXT    NOT NULL DEFAULT 'Food',
    price       TEXT    NOT NULL DEFAULT '0.00',
    description TEXT,
    image_url   TEXT,
    recipe_id   INTEGER REFERENCES recipes(id),
    active      INTEGER NOT NULL DEFAULT 1,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_products_tenant ON products(tenant_id, active, sort_order);

-- The seller's bell: something arrived that needs a person.
CREATE TABLE IF NOT EXISTS notifications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id  INTEGER NOT NULL,
    kind       TEXT    NOT NULL,          -- buyer_order | recipe_idea | message
    title      TEXT    NOT NULL,
    body       TEXT,
    order_id   INTEGER,
    thread_id  INTEGER,
    created_at TEXT    NOT NULL,
    read_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_notifications_tenant ON notifications(tenant_id, read_at, created_at);

-- What the AI suggests for a dish it was asked to research. Never a price.
CREATE TABLE IF NOT EXISTS recipe_suggestions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id    INTEGER NOT NULL,
    dish         TEXT    NOT NULL,
    payload_json TEXT    NOT NULL,
    status       TEXT    NOT NULL DEFAULT 'pending',
    recipe_id    INTEGER,
    created_at   TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_recipe_suggestions ON recipe_suggestions(tenant_id, status);
"""

PLAN_ROWS = [
    (0, "basic", "Basic", 20, "150.00", "29.00"),
    (0, "standard", "Standard", 56, "1000.00", "79.00"),
    (0, "pro", "Pro", 200, "3000.00", "149.00"),
]


def connect(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: one connection per request, and the sync dependency
    # and the sync endpoint may run on different threadpool threads.
    conn = sqlite3.connect(path, timeout=30.0, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


@contextmanager
def tx(conn: sqlite3.Connection):
    """One transaction: nothing is left half-saved."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def init_db(path: str) -> None:
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        # Small forward migrations: a column added after the first release.
        for table, column, ddl in (
            ("users", "locale", "TEXT NOT NULL DEFAULT 'en'"),
            ("orders", "delivery_fee", "TEXT NOT NULL DEFAULT '0.00'"),
            ("tenants", "tagline", "TEXT"),
            ("tenants", "phone", "TEXT"),
            ("tenants", "address", "TEXT"),
            ("tenants", "hours", "TEXT"),
        ):
            columns = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]
            if column not in columns:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        with tx(conn):
            for row in PLAN_ROWS:
                conn.execute(
                    "INSERT OR IGNORE INTO plans (tenant_id, code, name, calls_per_day, ai_budget_rm, price_rm_month)"
                    " VALUES (?,?,?,?,?,?)",
                    row,
                )
    finally:
        conn.close()


def table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return [r["name"] for r in rows]


def tenant_tables(conn: sqlite3.Connection) -> list[str]:
    """Tables that must carry a tenant_id column (all except tenants itself)."""
    names = table_names(conn)
    return [n for n in names if n != "tenants"]
