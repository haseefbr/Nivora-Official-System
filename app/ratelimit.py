"""Atomic rate limits and counters, in SQLite (docs/STATE.md).

Keys always start with the tenant: nivora:{tenant}:{user}:rl:{minute}
and nivora:{tenant}:rl:{day}. One statement counts; there is no GET then SET.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

from .settings import Settings

PERSON_WINDOW = 60
DAY_WINDOW = 86_400


def minute_key(tenant_id: int, user_id: int, at: datetime) -> str:
    return f"nivora:{tenant_id}:{user_id}:rl:{at.strftime('%Y%m%d%H%M')}"


def day_key(tenant_id: int, at: datetime) -> str:
    return f"nivora:{tenant_id}:rl:{at.strftime('%Y-%m-%d')}"


def hit(conn, key: str, tenant_id: int, limit: int, window_seconds: int,
        at: datetime | None = None) -> dict:
    """Count once, atomically. Returns the new count and whether it is allowed."""
    moment = at or datetime.now(timezone.utc)
    epoch = moment.timestamp()
    expires = epoch + window_seconds
    row = conn.execute(
        """INSERT INTO rate_limits (key, tenant_id, count, expires_at) VALUES (?,?,1,?)
           ON CONFLICT(key) DO UPDATE SET
             count = CASE WHEN rate_limits.expires_at <= ? THEN 1 ELSE rate_limits.count + 1 END,
             expires_at = CASE WHEN rate_limits.expires_at <= ? THEN excluded.expires_at
                               ELSE rate_limits.expires_at END
           RETURNING count, expires_at""",
        (key, tenant_id, expires, epoch, epoch),
    ).fetchone()
    count = int(row["count"])
    retry_after = max(1, int(math.ceil(float(row["expires_at"]) - epoch)))
    return {
        "key": key,
        "count": count,
        "limit": limit,
        "allowed": count <= limit,
        "remaining": max(0, limit - count),
        "retry_after": retry_after,
    }


def cleanup(conn, at: datetime | None = None) -> None:
    epoch = (at or datetime.now(timezone.utc)).timestamp()
    conn.execute("DELETE FROM rate_limits WHERE expires_at <= ?", (epoch,))


def check_ai_limits(conn, settings: Settings, tenant: dict, user_id: int,
                    at: datetime | None = None, plan_limit: int = 56) -> dict:
    """Per person per minute, then per customer per day. Refuse with a retry time."""
    moment = at or datetime.now(timezone.utc)
    day = hit(conn, day_key(int(tenant["id"]), moment), int(tenant["id"]), plan_limit, DAY_WINDOW, moment)
    if not day["allowed"]:
        return {
            "ok": False,
            "code": "plan_limit",
            "message": (
                f"This business has used its {plan_limit} AI calls for today. "
                "Upgrade the plan for more, or try again tomorrow."
            ),
            "retry_after": day["retry_after"],
            "day": day,
        }
    person = hit(conn, minute_key(int(tenant["id"]), user_id, moment), int(tenant["id"]),
                 settings.rate_person_per_minute, PERSON_WINDOW, moment)
    if not person["allowed"]:
        return {
            "ok": False,
            "code": "rate_limited",
            "message": (
                f"That is {settings.rate_person_per_minute} AI calls in a minute. "
                f"Try again in {person['retry_after']} seconds."
            ),
            "retry_after": person["retry_after"],
            "day": day,
            "person": person,
        }
    return {"ok": True, "day": day, "person": person, "retry_after": 0}
