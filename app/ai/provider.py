"""Model providers: gigalab-local (ollama) first, a second on timeout or 429.

Nothing here is called from the browser: the server holds the keys.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Callable, Protocol

import httpx

from ..settings import Settings


@dataclass
class Completion:
    text: str
    tokens_in: int
    tokens_out: int
    model: str
    provider: str


class ProviderError(Exception):
    def __init__(self, message: str, *, retryable: bool = False, status: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status = status


class Provider(Protocol):
    name: str
    model: str

    def complete(self, system: str, user: str, max_tokens: int, timeout: float) -> Completion: ...


_DOWN: dict[str, float] = {}
DOWN_SECONDS = 60.0


def mark_down(key: str) -> None:
    """A refused socket will refuse again in a second: remember it briefly."""
    _DOWN[key] = time.monotonic() + DOWN_SECONDS


def is_down(key: str) -> bool:
    until = _DOWN.get(key)
    if until is None:
        return False
    if time.monotonic() >= until:
        _DOWN.pop(key, None)
        return False
    return True


class OllamaProvider:
    """ollama · gigalab-local, on your server."""

    name = "ollama"

    def __init__(self, settings: Settings, base_url: str | None = None, model: str | None = None):
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = model or settings.ollama_model

    def complete(self, system: str, user: str, max_tokens: int, timeout: float) -> Completion:
        if is_down(self.base_url):
            raise ProviderError(f"The model is not reachable at {self.base_url}", retryable=False)
        payload = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0, "num_predict": max_tokens},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            response = httpx.post(
                f"{self.base_url}/api/chat", json=payload,
                timeout=httpx.Timeout(timeout, connect=min(1.5, timeout)),
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            # Nothing is listening: do not retry this provider, use the next one.
            mark_down(self.base_url)
            raise ProviderError(f"The model is not reachable at {self.base_url}", retryable=False) from exc
        except httpx.TimeoutException as exc:
            raise ProviderError("The model timed out", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"The model is unreachable: {type(exc).__name__}", retryable=True) from exc
        if response.status_code == 429:
            raise ProviderError("The model provider is rate limiting", retryable=False, status=429)
        if response.status_code >= 500:
            raise ProviderError("The model provider failed", retryable=True, status=response.status_code)
        if response.status_code != 200:
            raise ProviderError("The model provider refused the call", status=response.status_code)
        try:
            body = response.json()
            text = body["message"]["content"]
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError("The model provider sent an unreadable reply", retryable=True) from exc
        return Completion(
            text=text,
            tokens_in=int(body.get("prompt_eval_count") or 0),
            tokens_out=int(body.get("eval_count") or 0),
            model=self.model,
            provider=self.name,
        )


class AnthropicProvider:
    """The second provider, used on timeout or 429."""

    name = "anthropic"

    def __init__(self, settings: Settings, model: str | None = None, api_key: str | None = None):
        self.model = model or settings.fallback_model
        self.base_url = settings.anthropic_base_url.rstrip("/")
        self.api_key = api_key if api_key is not None else settings.anthropic_api_key

    def complete(self, system: str, user: str, max_tokens: int, timeout: float) -> Completion:
        if not self.api_key:
            raise ProviderError("No second provider is configured", retryable=False)
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": 0,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        try:
            response = httpx.post(
                f"{self.base_url}/v1/messages", json=payload, headers=headers,
                timeout=httpx.Timeout(timeout, connect=min(1.5, timeout)),
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise ProviderError("The second provider is not reachable") from exc
        except httpx.TimeoutException as exc:
            raise ProviderError("The second provider timed out", retryable=False) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"The second provider is unreachable: {type(exc).__name__}") from exc
        if response.status_code == 429:
            raise ProviderError("The second provider is rate limiting", status=429)
        if response.status_code >= 500:
            raise ProviderError("The second provider failed", retryable=True, status=response.status_code)
        if response.status_code != 200:
            raise ProviderError("The second provider refused the call", status=response.status_code)
        try:
            body = response.json()
            text = "".join(block.get("text", "") for block in body.get("content", []))
            usage = body.get("usage", {})
        except (ValueError, AttributeError) as exc:
            raise ProviderError("The second provider sent an unreadable reply", retryable=True) from exc
        return Completion(
            text=text,
            tokens_in=int(usage.get("input_tokens") or 0),
            tokens_out=int(usage.get("output_tokens") or 0),
            model=self.model,
            provider=self.name,
        )


class CallableProvider:
    """A provider from a function: used by tests and by the local fallback."""

    def __init__(self, fn: Callable[[str, str, int, float], str | Completion],
                 name: str = "test", model: str = "test-model"):
        self._fn = fn
        self.name = name
        self.model = model

    def complete(self, system: str, user: str, max_tokens: int, timeout: float) -> Completion:
        result = self._fn(system, user, max_tokens, timeout)
        if isinstance(result, Completion):
            return result
        return Completion(text=str(result), tokens_in=0, tokens_out=0, model=self.model, provider=self.name)


class ProviderChain:
    """Try each provider in order, inside one deadline. Back off, then move on."""

    def __init__(self, providers: list[Provider], deadline_seconds: float = 60.0,
                 sleeper: Callable[[float], None] = time.sleep):
        self.providers = providers
        self.deadline_seconds = deadline_seconds
        self._sleep = sleeper

    def complete(self, system: str, user: str, max_tokens: int, per_call_timeout: float = 20.0) -> tuple[Completion, bool]:
        started = time.monotonic()
        errors: list[str] = []
        used_fallback = False
        for index, provider in enumerate(self.providers):
            if index > 0:
                used_fallback = True
            remaining = self.deadline_seconds - (time.monotonic() - started)
            if remaining <= 0.5:
                errors.append("deadline reached")
                break
            attempts = 2
            for attempt in range(attempts):
                budget = self.deadline_seconds - (time.monotonic() - started)
                if budget <= 0.5:
                    break
                try:
                    completion = provider.complete(
                        system, user, max_tokens,
                        timeout=max(1.0, min(per_call_timeout, budget)),
                    )
                    if not (completion.text or "").strip():
                        raise ProviderError("The model returned nothing", retryable=True)
                    return completion, used_fallback
                except ProviderError as exc:
                    errors.append(f"{provider.name}: {exc}")
                    if exc.retryable and attempt + 1 < attempts:
                        pause = 0.4 * (2 ** attempt)
                        if time.monotonic() - started + pause < self.deadline_seconds:
                            self._sleep(pause)
                        continue
                    break
        raise ProviderError("; ".join(errors[-4:]) or "No model provider answered")


def provider_name(settings: Settings) -> str:
    return settings.ai_provider


def build_chain(settings: Settings, extra: list[Provider] | None = None,
                local_fallback: Provider | None = None) -> ProviderChain:
    """Settings decide the order; no code change to switch models."""
    providers: list[Provider] = []
    if settings.ai_enabled:
        if settings.ai_provider == "ollama":
            providers.append(OllamaProvider(settings))
        if settings.ai_provider == "anthropic" and settings.anthropic_api_key:
            providers.append(AnthropicProvider(settings))
        if settings.ai_provider == "heuristic":
            pass  # the local deterministic provider is appended below
        if settings.ai_provider == "ollama" and settings.fallback_provider == "anthropic" and settings.anthropic_api_key:
            providers.append(AnthropicProvider(settings))
        if settings.ai_provider == "anthropic" and settings.fallback_provider == "ollama":
            providers.append(OllamaProvider(settings))
    if extra:
        providers.extend(extra)
    if local_fallback is not None:
        providers.append(local_fallback)
    return ProviderChain(providers, deadline_seconds=settings.ai_total_deadline_seconds)
