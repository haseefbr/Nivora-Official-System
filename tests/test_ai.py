"""Milestone M4 and M5: one checked model call.

Providers, the three check layers, the failure policy, budgets, usage, the
safe log line, and the two rate limits.
"""
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.ai.contracts import (
    COSTING, PARSER, ContractRuleError, ContractSchemaError, ContractSyntaxError,
)
from app.ai.provider import CallableProvider, Completion, ProviderChain, ProviderError
from app.ai.runner import Runner
from app.db import connect
from app.ratelimit import check_ai_limits, day_key, hit
from app.settings import Settings


def _good_parser_reply(**over):
    payload = {
        "intent": "order", "customer_name": None,
        "items": [{"product_name": "kuih lapis", "quantity": 20, "unit": "biji", "recipe": None}],
        "delivery_date": None, "address": None, "note": None, "confidence": 0.92,
    }
    payload.update(over)
    return json.dumps(payload)


def _chain(*providers):
    return ProviderChain(list(providers), deadline_seconds=5.0, sleeper=lambda s: None)


def _fake(text, name="fake", tokens=(11, 22)):
    return CallableProvider(
        lambda system, user, max_tokens, timeout: Completion(
            text=text, tokens_in=tokens[0], tokens_out=tokens[1],
            model="fake-1", provider=name),
        name=name, model="fake-1")


# ------------------------------------------------------------- the layers

def test_a_valid_reply_passes_all_three_layers():
    payload, report = PARSER.check(_good_parser_reply(), "20 biji kuih lapis", date.today())
    assert report.ok
    assert payload["items"][0]["quantity"] == 20


def test_broken_json_fails_at_syntax():
    with pytest.raises(ContractSyntaxError) as error:
        PARSER.check("not json at all", "20 biji kuih lapis", date.today())
    assert error.value.layer == "syntax"


def test_a_missing_field_fails_at_schema():
    payload = json.loads(_good_parser_reply())
    del payload["confidence"]
    with pytest.raises(ContractSchemaError) as error:
        PARSER.check(json.dumps(payload), "20 biji kuih lapis", date.today())
    assert "confidence" in str(error.value)


def test_a_broken_business_rule_fails_at_business():
    payload = json.loads(_good_parser_reply())
    payload["delivery_date"] = "2027-01-01"
    with pytest.raises(ContractRuleError) as error:
        PARSER.check(json.dumps(payload), "20 biji kuih lapis", date.today())
    assert "date" in str(error.value)


def test_a_banned_word_or_promise_is_caught():
    payload = json.loads(_good_parser_reply())
    payload["note"] = "We guarantee the best price, free delivery"
    with pytest.raises(ContractRuleError) as error:
        PARSER.check(json.dumps(payload), "20 biji kuih lapis", date.today())
    assert "banned" in str(error.value)


def test_an_invented_address_is_caught():
    payload = json.loads(_good_parser_reply(address="99 Jalan Rekaan, 50000 Kuala Lumpur"))
    with pytest.raises(ContractRuleError):
        PARSER.check(json.dumps(payload), "20 biji kuih lapis", date.today())


def test_the_costing_contract_refuses_a_price_from_the_model():
    payload = {
        "recipe_name": "kuih lapis", "product_name": "kuih lapis", "yield_units": 40,
        "items": [{"ingredient": "gula", "quantity": 300, "unit": "g", "price": 1.0}],
        "confidence": 0.9,
    }
    with pytest.raises(ContractSchemaError):
        COSTING.check(json.dumps(payload), "Resepi kuih lapis: 300 g gula. Dapat 40 biji.", date.today())


# ---------------------------------------------------------- the runner

def test_a_fake_provider_returns_the_reply_and_the_token_counts(seed, settings):
    conn = seed["client"].app.state.connect()
    tenant = conn.execute("SELECT * FROM tenants WHERE id = ?", (seed["tenant_id"],)).fetchone()
    result = Runner(settings).run(
        "parse", conn, dict(tenant), seed["user_id"], "20 biji kuih lapis",
        chain=_chain(_fake(_good_parser_reply())),
    )
    conn.close()
    assert result.ok, result.error
    assert result.tokens_in == 11
    assert result.tokens_out == 22
    assert result.provider == "fake"
    assert result.payload["items"][0]["quantity"] == 20


def test_a_missing_key_gives_a_clear_error_not_a_crash(seed, tmp_path):
    settings = Settings(
        app_secret="x", database_path=str(tmp_path / "k.db"), log_path=str(tmp_path / "k.log"),
        dev_mode=True, session_secure=False, ai_provider="anthropic", anthropic_api_key="",
        ai_local_fallback=False, fallback_provider="none",
    )
    from app.db import init_db
    init_db(settings.database_path)
    conn = connect(settings.database_path)
    conn.execute("INSERT INTO tenants (tenant_id, name, public_slug, plan, ai_provider, created_at)"
                 " VALUES (0,'K','k','standard','anthropic','2026-01-01T00:00:00+00:00')")
    tenant_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    conn.execute("UPDATE tenants SET tenant_id = id WHERE id = ?", (tenant_id,))
    tenant = dict(conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone())
    result = Runner(settings).run("parse", conn, tenant, 1, "20 biji kuih lapis")
    conn.close()
    assert result.ok is False
    assert result.error["code"] == "ai_not_configured"
    assert result.error["status"] == 503
    assert "ANTHROPIC_API_KEY" in result.error["message"]


def test_the_key_never_appears_in_a_response_or_a_log(seed, tmp_path):
    key = "sk-ant-secret-key-1234567890"
    settings = Settings(
        app_secret="x", database_path=str(tmp_path / "k2.db"), log_path=str(tmp_path / "k2.log"),
        dev_mode=True, session_secure=False, ai_provider="ollama",
        ollama_base_url="http://127.0.0.1:9", fallback_provider="anthropic",
        anthropic_api_key=key, anthropic_base_url="http://127.0.0.1:9",
        ai_timeout_seconds=1.0, ai_total_deadline_seconds=3.0, ai_local_fallback=True,
    )
    from app.db import init_db
    init_db(settings.database_path)
    conn = connect(settings.database_path)
    conn.execute("INSERT INTO tenants (tenant_id, name, public_slug, plan, created_at)"
                 " VALUES (0,'K','k2','standard','2026-01-01T00:00:00+00:00')")
    tenant_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    conn.execute("UPDATE tenants SET tenant_id = id WHERE id = ?", (tenant_id,))
    tenant = dict(conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone())
    result = Runner(settings).run("parse", conn, tenant, 1, "20 biji kuih lapis")
    conn.close()
    blob = json.dumps(result.to_dict()) + open(settings.log_path, encoding="utf-8").read()
    assert key not in blob
    assert "sk-ant" not in blob


def test_the_failure_policy_repairs_once_then_gives_a_safe_reply(seed, settings):
    conn = seed["client"].app.state.connect()
    tenant = dict(conn.execute("SELECT * FROM tenants WHERE id = ?", (seed["tenant_id"],)).fetchone())
    broken = _fake("I am sorry, here is your order in prose.")
    result = Runner(settings).run("parse", conn, tenant, seed["user_id"],
                                  "20 biji kuih lapis", chain=_chain(broken))
    conn.close()
    assert result.ok is True
    assert result.outcome == "safe_reply"
    assert result.needs_human is True
    assert result.payload["items"] == []
    assert result.payload["confidence"] == 0.0


def test_a_repair_that_works_is_flagged_for_a_person(seed, settings):
    conn = seed["client"].app.state.connect()
    tenant = dict(conn.execute("SELECT * FROM tenants WHERE id = ?", (seed["tenant_id"],)).fetchone())
    state = {"n": 0}

    def flaky(system, user, max_tokens, timeout):
        state["n"] += 1
        return "not json" if state["n"] == 1 else _good_parser_reply()

    result = Runner(settings).run("parse", conn, tenant, seed["user_id"], "20 biji kuih lapis",
                                  chain=_chain(CallableProvider(flaky)))
    conn.close()
    assert result.ok is True
    assert result.repaired is True
    assert result.needs_human is True
    assert result.checks.startswith("syntax+schema+business")


def test_a_timeout_moves_to_the_second_provider():
    def slow(system, user, max_tokens, timeout):
        raise ProviderError("timed out", retryable=True)

    chain = _chain(CallableProvider(slow, name="slow"),
                   _fake(_good_parser_reply(), name="second"))
    completion, fallback = chain.complete("s", "u", 100, per_call_timeout=1)
    assert completion.provider == "second"
    assert fallback is True


def test_a_retryable_failure_backs_off_and_tries_again():
    calls = {"n": 0}
    pauses = []

    def once(system, user, max_tokens, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ProviderError("server error", retryable=True)
        return Completion("ok", 1, 2, "m", "p")

    chain = ProviderChain([CallableProvider(once)], deadline_seconds=5, sleeper=pauses.append)
    completion, _ = chain.complete("s", "u", 100)
    assert completion.text == "ok"
    assert calls["n"] == 2
    assert pauses and pauses[0] > 0


def test_a_429_moves_on_without_retrying_the_same_provider():
    class Limited:
        name = "limited"
        model = "m"

        def __init__(self):
            self.calls = 0

        def complete(self, system, user, max_tokens, timeout):
            self.calls += 1
            raise ProviderError("429", status=429)

    limited = Limited()
    chain = _chain(limited, _fake(_good_parser_reply(), name="second"))
    completion, _ = chain.complete("s", "u", 100)
    assert completion.provider == "second"
    assert limited.calls == 1


def test_a_message_over_the_limit_never_reaches_the_model(seed, settings):
    conn = seed["client"].app.state.connect()
    tenant = dict(conn.execute("SELECT * FROM tenants WHERE id = ?", (seed["tenant_id"],)).fetchone())
    calls = {"n": 0}

    def counting(system, user, max_tokens, timeout):
        calls["n"] += 1
        return _good_parser_reply()

    result = Runner(settings).run("parse", conn, tenant, seed["user_id"], "x" * 5000,
                                  chain=_chain(CallableProvider(counting)))
    conn.close()
    assert result.ok is False
    assert result.error["code"] == "input_too_long"
    assert calls["n"] == 0


def test_call_eleven_in_a_minute_is_refused(seed, monkeypatch):
    """Ten calls are allowed in a minute; the eleventh is refused.

    The window is a wall-clock minute, so the clock is frozen for this test:
    a run that straddled :00 would reset the counter and hide a real bug.
    """
    from datetime import datetime as real_datetime, timezone

    frozen = real_datetime(2026, 1, 1, 10, 30, 0, tzinfo=timezone.utc)

    class FrozenDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen if tz else frozen.replace(tzinfo=None)

    monkeypatch.setattr("app.ratelimit.datetime", FrozenDatetime)
    client = seed["client"]
    codes = [client.post("/api/ai/parse", json={"message": "20 biji kuih lapis"}).status_code
             for _ in range(11)]
    assert codes[:10] == [200] * 10, codes
    assert codes[10] == 429, codes
    body = client.post("/api/ai/parse", json={"message": "20 biji kuih lapis"}).json()
    assert body["code"] == "rate_limited"
    assert body["retry_after"] > 0


def test_call_fifty_seven_in_a_day_is_refused(seed, settings):
    conn = seed["client"].app.state.connect()
    tenant = dict(conn.execute("SELECT * FROM tenants WHERE id = ?", (seed["tenant_id"],)).fetchone())
    at = datetime.now(timezone.utc)
    for _ in range(56):
        hit(conn, day_key(seed["tenant_id"], at), seed["tenant_id"], 56, 86400, at)
    outcome = check_ai_limits(conn, settings, tenant, seed["user_id"], at=at, plan_limit=56)
    conn.close()
    assert outcome["ok"] is False
    assert outcome["code"] == "plan_limit"
    assert "Upgrade" in outcome["message"]


def test_the_safe_log_line_has_no_message_text(seed, settings):
    seed["client"].post("/api/ai/parse", json={
        "message": "Rahsia pelanggan: 20 biji kuih lapis untuk esok"
    })
    log = open(settings.log_path, encoding="utf-8").read()
    assert "ai_call" in log
    assert "tenant=" in log and "tokens_in=" in log and "outcome=" in log
    assert "Rahsia" not in log
    assert "kuih lapis" not in log


def test_each_customer_sees_only_their_own_usage(seed, owner2):
    seed["client"].post("/api/ai/parse", json={"message": "20 biji kuih lapis"})
    mine = seed["client"].get("/api/usage").json()["usage"]
    theirs = owner2["client"].get("/api/usage").json()["usage"]
    assert mine["calls"] >= 1
    assert theirs["calls"] == 0


def test_a_customer_over_budget_is_paused_with_a_clear_message(seed, app):
    client = seed["client"]
    conn = app.state.connect()
    conn.execute(
        "INSERT INTO ai_calls (tenant_id, request_id, feature, model, provider, tokens_in,"
        " tokens_out, cost_usd, duration_ms, outcome, checks, fallback_used, needs_human, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (seed["tenant_id"], "seed-budget", "AI MESSAGE PARSER", "m", "p", 10, 10,
         "1000.00", 10, "call_ok", "", 0, 0, datetime.now(timezone.utc).isoformat()),
    )
    conn.close()
    response = client.post("/api/ai/parse", json={"message": "20 biji kuih lapis"})
    assert response.status_code == 402
    body = response.json()
    assert body["code"] == "budget_paused"
    assert "budget" in body["message"].lower()


def test_an_alert_goes_out_at_eighty_percent(seed, app):
    conn = app.state.connect()
    conn.execute(
        "INSERT INTO ai_calls (tenant_id, request_id, feature, model, provider, tokens_in,"
        " tokens_out, cost_usd, duration_ms, outcome, checks, fallback_used, needs_human, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (seed["tenant_id"], "seed-80", "AI MESSAGE PARSER", "m", "p", 10, 10,
         "850.00", 10, "call_ok", "", 0, 0, datetime.now(timezone.utc).isoformat()),
    )
    conn.close()
    assert seed["client"].post("/api/ai/parse", json={"message": "20 biji kuih lapis"}).status_code == 200
    alerts = seed["client"].get("/api/usage").json()["alerts"]
    assert any(alert["kind"] == "budget_80" for alert in alerts)


def test_changing_the_model_in_settings_changes_the_next_call(seed, app):
    client = seed["client"]
    updated = client.patch("/api/ai/settings",
                           json={"ai_provider": "ollama", "ai_model": "llama3.2:3b"})
    assert updated.status_code == 200, updated.text
    assert updated.json()["ai_model"] == "llama3.2:3b"
    assert updated.json()["ai_provider"] == "ollama"
    conn = app.state.connect()
    tenant = dict(conn.execute("SELECT * FROM tenants WHERE id = ?", (seed["tenant_id"],)).fetchone())
    conn.close()
    chain = Runner(app.state.settings).build_chain(tenant, date.today())
    ollama = [p for p in chain.providers if p.name == "ollama"]
    assert ollama and ollama[0].model == "llama3.2:3b"


def test_a_low_confidence_reply_waits_for_a_person(seed, settings):
    conn = seed["client"].app.state.connect()
    tenant = dict(conn.execute("SELECT * FROM tenants WHERE id = ?", (seed["tenant_id"],)).fetchone())
    reply = _good_parser_reply(confidence=0.2)
    result = Runner(settings).run("parse", conn, tenant, seed["user_id"], "20 biji kuih lapis",
                                  chain=_chain(_fake(reply)))
    conn.close()
    assert result.ok is True
    assert result.needs_human is True
