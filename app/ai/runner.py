"""One checked AI run: limits, budget, provider chain, contract checks, repair, log.

No tools, one model call (plus at most one repair), as docs/TOOLS.md says.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal

from .. import models
from ..money import D, s
from ..ratelimit import check_ai_limits
from ..safelog import model_call
from ..security import iso
from ..settings import Settings
from .contracts import CONTRACTS, ContractError, ContractRuleError, ContractSchemaError, ContractSyntaxError
from .local import LocalProvider
from .prompts import build_messages, repair_messages
from .provider import AnthropicProvider, Completion, OllamaProvider, ProviderChain, ProviderError

COST_Q = Decimal("0.000001")


@dataclass
class RunResult:
    ok: bool
    feature: str
    payload: dict | None = None
    request_id: str = ""
    provider: str = ""
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: str = "0.00"
    duration_ms: int = 0
    outcome: str = "ok"
    checks: str = ""
    needs_human: bool = False
    fallback_used: bool = False
    repaired: bool = False
    input_flags: list[str] = field(default_factory=list)
    error: dict | None = None
    calls: int = 1

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "feature": self.feature,
            "request_id": self.request_id,
            "payload": self.payload,
            "provider": self.provider,
            "model": self.model,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": self.cost_usd,
            "duration_ms": self.duration_ms,
            "outcome": self.outcome,
            "checks": self.checks,
            "needs_human": self.needs_human,
            "fallback_used": self.fallback_used,
            "repaired": self.repaired,
            "input_flags": self.input_flags,
            "error": self.error,
        }


class Runner:
    def __init__(self, settings: Settings):
        self.settings = settings

    # ---------------------------------------------------------- chain
    def build_chain(self, tenant: dict | None, today: date,
                    extra: list | None = None) -> ProviderChain:
        settings = self.settings
        model = (tenant or {}).get("ai_model") or settings.ollama_model
        kind = ((tenant or {}).get("ai_provider") or settings.ai_provider or "ollama").lower()
        providers: list = []
        if settings.ai_enabled:
            if kind == "ollama":
                providers.append(OllamaProvider(settings, model=model))
            elif kind == "anthropic" and settings.anthropic_api_key:
                providers.append(AnthropicProvider(settings, model=model))
            elif kind == "heuristic":
                pass
            secondary = settings.fallback_provider
            if kind == "ollama" and secondary == "anthropic" and settings.anthropic_api_key:
                providers.append(AnthropicProvider(settings))
            elif kind == "anthropic" and secondary == "ollama":
                providers.append(OllamaProvider(settings))
        if extra:
            providers.extend(extra)
        if settings.ai_local_fallback or kind == "heuristic":
            providers.append(LocalProvider(today))
        return ProviderChain(providers, deadline_seconds=settings.ai_total_deadline_seconds)

    def _cost(self, completion: Completion) -> Decimal:
        settings = self.settings
        value = (
            Decimal(completion.tokens_in) / Decimal(1000) * settings.ai_usd_per_1k_in
            + Decimal(completion.tokens_out) / Decimal(1000) * settings.ai_usd_per_1k_out
        )
        return value.quantize(COST_Q)

    def _record(self, conn, tenant_id: int, user_id: int, request_id: str, feature: str,
                completion: Completion | None, duration_ms: int, outcome: str,
                checks: str, fallback: bool, needs_human: bool, error: str = "") -> dict:
        cost = self._cost(completion) if completion else Decimal("0")
        model = completion.model if completion else "none"
        provider = completion.provider if completion else "none"
        tokens_in = completion.tokens_in if completion else 0
        tokens_out = completion.tokens_out if completion else 0
        conn.execute(
            "INSERT INTO ai_calls (tenant_id, request_id, feature, model, provider, tokens_in,"
            " tokens_out, cost_usd, duration_ms, outcome, checks, fallback_used, needs_human, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (tenant_id, request_id, feature, model, provider, tokens_in, tokens_out,
             str(cost), duration_ms, outcome, checks[:500], int(bool(fallback)),
             int(bool(needs_human)), iso()),
        )
        model_call(
            self.settings, request_id=request_id, tenant_id=tenant_id, user_id=user_id,
            feature=feature, model=model, provider=provider, tokens_in=tokens_in,
            tokens_out=tokens_out, cost_usd=str(cost), duration_ms=duration_ms,
            outcome=outcome, checks=checks, fallback_used=fallback, needs_human=needs_human,
        )
        return {"cost": cost, "tokens_in": tokens_in, "tokens_out": tokens_out,
                "model": model, "provider": provider}

    # ------------------------------------------------------------ run
    def run(self, feature: str, conn, tenant: dict, user_id: int, raw: str,
            chain: ProviderChain | None = None, at: datetime | None = None) -> RunResult:
        settings = self.settings
        contract = CONTRACTS.get(feature)
        if contract is None:
            raise ValueError(f"Unknown AI feature: {feature}")
        request_id = uuid.uuid4().hex[:16]
        today = (at or datetime.now(timezone.utc)).date()
        tenant_id = int(tenant["id"])
        raw = raw or ""

        result = RunResult(ok=False, feature=contract.name, request_id=request_id)

        if len(raw) > settings.max_input_chars:
            result.error = {
                "code": "input_too_long", "status": 400,
                "message": f"That message is longer than {settings.max_input_chars} characters. Shorten it and try again.",
            }
            result.outcome = "refused"
            self._record(conn, tenant_id, user_id, request_id, contract.name, None, 0,
                         "refused", "input:length", False, False)
            return result

        limits = check_ai_limits(conn, settings, tenant, user_id, at=at,
                                 plan_limit=models.plan_calls_per_day(conn, tenant_id))
        if not limits["ok"]:
            result.error = {
                "code": limits["code"], "status": 429,
                "message": limits["message"], "retry_after": limits["retry_after"],
            }
            result.outcome = "refused"
            self._record(conn, tenant_id, user_id, request_id, contract.name, None, 0,
                         "refused", f"limit:{limits['code']}", False, False)
            return result

        budget = D(tenant.get("ai_budget_rm") or settings.budget_rm_month)
        spent = models.month_cost(conn, tenant_id)
        if budget > 0 and spent >= budget:
            result.error = {
                "code": "budget_paused", "status": 402,
                "message": (
                    f"This month's AI budget of RM{budget} is used up. "
                    "Raise the budget in AI settings, or wait for next month."
                ),
            }
            result.outcome = "refused"
            self._record(conn, tenant_id, user_id, request_id, contract.name, None, 0,
                         "refused", "budget:paused", False, False)
            return result

        try:
            active_chain = chain or self.build_chain(tenant, today)
            if not active_chain.providers:
                raise ProviderError(
                    "The AI is not configured: set OLLAMA_BASE_URL or ANTHROPIC_API_KEY in .env"
                )
        except ProviderError as exc:
            result.error = {"code": "ai_not_configured", "status": 503, "message": str(exc)}
            result.outcome = "failed"
            self._record(conn, tenant_id, user_id, request_id, contract.name, None, 0,
                         "failed", "provider:not_configured", False, False)
            return result

        system, user = build_messages(feature, raw, settings)
        started = time.monotonic()
        completion: Completion | None = None
        fallback_used = False
        try:
            completion, fallback_used = active_chain.complete(
                system, user, min(settings.ai_output_tokens, settings.ai_max_tokens),
                per_call_timeout=settings.ai_timeout_seconds,
            )
        except ProviderError as exc:
            duration = int((time.monotonic() - started) * 1000)
            self._record(conn, tenant_id, user_id, request_id, contract.name, None, duration,
                         "failed", "provider:error", False, False)
            result.error = {
                "code": "provider_unavailable", "status": 503,
                "message": f"The AI is unavailable right now. Try again in a minute. ({exc})",
            }
            result.outcome = "failed"
            result.duration_ms = duration
            return result

        duration = int((time.monotonic() - started) * 1000)
        stats = self._record(conn, tenant_id, user_id, request_id, contract.name, completion,
                             duration, "call_ok", "call", fallback_used, False)
        result.provider = completion.provider
        result.model = completion.model
        result.tokens_in = stats["tokens_in"]
        result.tokens_out = stats["tokens_out"]
        result.cost_usd = str(stats["cost"])
        result.fallback_used = fallback_used

        checks = "syntax+schema+business"
        try:
            payload, report = contract.check(completion.text, raw, today)
        except ContractError as exc:
            checks = f"{exc.layer}: {exc.message}"
            if completion.provider == "local-rules":
                # A deterministic reader gives the same answer twice: no repair call.
                result.payload = dict(contract.safe_reply)
                result.outcome = "safe_reply"
                result.ok = True
                result.needs_human = True
                result.checks = checks
                result.duration_ms = duration
                self._record(conn, tenant_id, user_id, request_id, contract.name, None, 0,
                             "safe_reply", checks, fallback_used, True)
                return result
            system2, user2 = repair_messages(feature, raw, completion.text,
                                             f"{exc.layer}: {exc.message}", settings)
            repair_started = time.monotonic()
            try:
                second, second_fallback = active_chain.complete(
                    system2, user2, min(settings.ai_output_tokens, settings.ai_max_tokens),
                    per_call_timeout=settings.ai_timeout_seconds,
                )
            except ProviderError:
                second = None
                second_fallback = False
            repair_ms = int((time.monotonic() - repair_started) * 1000)
            if second is None:
                # The failure policy: repair once, then a safe reply.
                result.payload = dict(contract.safe_reply)
                result.outcome = "safe_reply"
                result.ok = True
                result.needs_human = True
                result.checks = checks
                result.duration_ms = duration + repair_ms
                self._record(conn, tenant_id, user_id, request_id, contract.name, None, repair_ms,
                             "safe_reply", checks, fallback_used, True)
                return result
            stats2 = self._record(conn, tenant_id, user_id, request_id, contract.name, second,
                                  repair_ms, "repair_call", checks, second_fallback, False)
            result.tokens_in += stats2["tokens_in"]
            result.tokens_out += stats2["tokens_out"]
            result.cost_usd = str(D(result.cost_usd) + stats2["cost"])
            result.calls += 1
            try:
                payload, report = contract.check(second.text, raw, today)
            except ContractError as exc2:
                result.payload = dict(contract.safe_reply)
                result.outcome = "safe_reply"
                result.ok = True
                result.needs_human = True
                result.checks = f"{checks}; repair failed: {exc2.layer}: {exc2.message}"
                result.duration_ms = duration + repair_ms
                self._record(conn, tenant_id, user_id, request_id, contract.name, None, 0,
                             "safe_reply", result.checks, fallback_used, True)
                return result
            result.repaired = True
            checks = f"{report.summary()}; repaired after {exc.layer}"
            self._record(conn, tenant_id, user_id, request_id, contract.name, None, 0,
                         "repaired", checks, second_fallback, True)

        result.payload = payload
        result.checks = checks
        result.outcome = "repaired" if result.repaired else "ok"
        result.duration_ms = duration
        if payload.get("confidence", 1.0) < settings.confidence_human_review:
            result.needs_human = True
        if result.repaired:
            result.needs_human = True
        result.ok = True
        self._after_call(conn, tenant_id, budget)
        return result

    def _after_call(self, conn, tenant_id: int, budget: Decimal) -> None:
        """Alert at 80% of the month's budget, once a month."""
        spent = models.month_cost(conn, tenant_id)
        if budget <= 0:
            return
        if spent >= budget * Decimal(str(self.settings.budget_alert_ratio)):
            existing = conn.execute(
                "SELECT id FROM alerts WHERE tenant_id = ? AND kind = 'budget_80' AND created_at >= ?",
                (tenant_id, models.month_start_iso()),
            ).fetchone()
            if not existing:
                models.add_alert(
                    conn, tenant_id, "budget_80",
                    f"AI budget at {float(spent / budget) * 100:.0f}% of RM{budget} this month",
                )


__all__ = [
    "Runner", "RunResult", "ContractError", "ContractSyntaxError",
    "ContractSchemaError", "ContractRuleError",
]
