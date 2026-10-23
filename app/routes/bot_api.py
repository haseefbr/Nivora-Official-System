"""Chatbot endpoints: the seller's assistant and the buyer's shop assistant."""
from __future__ import annotations

from fastapi import Depends, Request
from pydantic import BaseModel, Field

from .. import bot as bot_service
from ..auth import current_user, get_db
from ..ratelimit import hit

from .api import _fail, _settings, _tenant, router


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=600)
    session_id: str | None = Field(default=None, max_length=64)
    history: list[dict] = Field(default_factory=list)


def _reply(conn, settings, facts, payload: ChatIn, request_id: str, tenant_id: int) -> dict:
    if not settings.bot_enabled:
        _fail(503, "bot_off", "The assistant is switched off.")
    client = bot_service.BotClient(settings)
    if not client.configured:
        _fail(503, "bot_not_configured", "The shop assistant is not switched on yet.")
    question = bot_service.build_question(
        facts, payload.message, bot_service.parse_history(payload.history))
    try:
        text, duration = client.reply(question, payload.session_id)
    except bot_service.BotError as exc:
        bot_service.log_bot_call(conn, tenant_id, request_id, 0, "bot_error", exc.code)
        _fail(exc.status, exc.code, exc.message)
    bot_service.log_bot_call(conn, tenant_id, request_id, duration, "chat_ok")
    return {"ok": True, "reply": bot_service.guard(text, facts, payload.message),
            "duration_ms": duration, "request_id": request_id}


@router.post("/bot/chat")
def seller_chat(payload: ChatIn, request: Request, session=Depends(current_user), conn=Depends(get_db)):
    """The owner's assistant, grounded on their own shop."""
    settings = _settings(request)
    tenant = _tenant(conn, session["tenant_id"])
    tenant_id = int(tenant["id"])
    limit = hit(conn, f"nivora:bot:{session['user_id']}", tenant_id, 25, 600)
    if not limit["allowed"]:
        _fail(429, "slow_down", "You are asking very fast. Give it a minute.",
              retry_after=limit["retry_after"])
    try:
        facts = bot_service.facts_for(conn, tenant_id, settings)
    except bot_service.BotError as exc:
        _fail(exc.status, exc.code, exc.message)
    return _reply(conn, settings, facts, payload, getattr(request.state, "request_id", "-"), tenant_id)


@router.post("/public/shops/{slug}/bot")
def buyer_chat(slug: str, payload: ChatIn, request: Request, conn=Depends(get_db)):
    """The buyer's assistant on a shop page. No account, rate limited per device."""
    settings = _settings(request)
    tenant = conn.execute("SELECT * FROM tenants WHERE public_slug = ?", (slug,)).fetchone()
    if tenant is None:
        _fail(404, "no_shop", "That shop does not exist.")
    tenant_id = int(tenant["id"])
    client_host = request.client.host if request.client else "unknown"
    limit = hit(conn, f"nivora:public:{slug}:bot:{client_host}", tenant_id, 20, 600)
    if not limit["allowed"]:
        _fail(429, "slow_down", "Too many questions from this device. Try again later.",
              retry_after=limit["retry_after"])
    try:
        facts = bot_service.facts_for(conn, tenant_id, settings)
    except bot_service.BotError as exc:
        _fail(exc.status, exc.code, exc.message)
    return _reply(conn, settings, facts, payload, getattr(request.state, "request_id", "-"), tenant_id)
