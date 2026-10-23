"""One safe log line: request id, tenant, model, tokens, cost, time, outcome.

Never what people wrote. Never a key, a password or a session token.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from .settings import Settings

_LOGGERS: dict[str, logging.Logger] = {}


def close_all(settings: Settings) -> None:
    """Release file handles (tests and Windows)."""
    path = str(Path(settings.log_path).resolve())
    logger = _LOGGERS.pop(path, None)
    if logger is None:
        return
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)


def logger_for(settings: Settings) -> logging.Logger:
    path = str(Path(settings.log_path).resolve())
    if path in _LOGGERS:
        return _LOGGERS[path]
    logger = logging.getLogger(f"nivora.safe.{path}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(stream)
    _LOGGERS[path] = logger
    return logger


def _line(event: str, fields: dict) -> str:
    parts = [event]
    for key, value in fields.items():
        if value is None:
            continue
        text = str(value).replace("\n", " ").replace(" ", "_")
        parts.append(f"{key}={text}")
    return " ".join(parts)


def model_call(settings: Settings, *, request_id: str, tenant_id: int, user_id: int,
               feature: str, model: str, provider: str, tokens_in: int, tokens_out: int,
               cost_usd: str, duration_ms: int, outcome: str, checks: str,
               fallback_used: bool, needs_human: bool) -> None:
    logger_for(settings).info(_line("ai_call", {
        "request_id": request_id,
        "tenant": tenant_id,
        "user": user_id,
        "feature": feature,
        "model": model,
        "provider": provider,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": cost_usd,
        "ms": duration_ms,
        "outcome": outcome,
        "checks": checks,
        "fallback": int(bool(fallback_used)),
        "needs_human": int(bool(needs_human)),
    }))


def request_line(settings: Settings, *, request_id: str, method: str, path: str,
                 status: int, duration_ms: int, tenant_id: int | None, user_id: int | None) -> None:
    logger_for(settings).info(_line("request", {
        "request_id": request_id,
        "method": method,
        "path": path.split("?")[0],
        "status": status,
        "ms": duration_ms,
        "tenant": tenant_id,
        "user": user_id,
    }))


def security_event(settings: Settings, *, event: str, tenant_id: int | None,
                   identifier: str | None, detail: str = "") -> None:
    logger_for(settings).warning(_line("security", {
        "event": event,
        "tenant": tenant_id,
        "identifier": identifier,
        "detail": detail,
    }))
