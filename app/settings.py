"""Settings, read only from the environment (.env in development).

Rules (AGENTS.md): secrets come only from environment variables, are never
written in code, a log, a response or the browser.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _under_root(value: str) -> str:
    """A relative path in .env is relative to the project, not to the shell."""
    path = Path(value)
    return str(path if path.is_absolute() else (ROOT / path))


def load_dotenv(path: str | os.PathLike[str] = ROOT / ".env") -> None:
    """Minimal .env reader. Existing environment variables always win."""
    p = Path(path)
    if not p.exists():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    app_secret: str
    database_path: str
    dev_mode: bool = False
    force_https: bool = False
    session_secure: bool = True
    log_path: str = "data/nivora.log"

    # AI: gigalab-local (ollama) first, a second provider on timeout or 429.
    ai_enabled: bool = True
    ai_provider: str = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "gigalab-local"
    fallback_provider: str = "anthropic"
    fallback_model: str = "claude-3-5-haiku-latest"
    anthropic_api_key: str = ""
    anthropic_base_url: str = "https://api.anthropic.com"
    ai_timeout_seconds: float = 20.0
    ai_total_deadline_seconds: float = 60.0
    ai_max_tokens: int = 20000
    ai_output_tokens: int = 700
    ai_local_fallback: bool = True
    ai_usd_per_1k_in: Decimal = Decimal("0")
    ai_usd_per_1k_out: Decimal = Decimal("0")
    public_base_url: str = "http://localhost:8000"

    # Chatbot: a Flowise agent flow, proxied so the URL never reaches the browser.
    bot_enabled: bool = True
    flowise_url: str = ""
    flowise_api_key: str = ""
    flowise_timeout_seconds: float = 35.0

    # Limits (docs/STATE.md)
    max_input_chars: int = 4000
    rate_person_per_minute: int = 10
    rate_tenant_per_day: int = 56

    # AI settings per customer (docs/AI_SETTINGS.md)
    budget_rm_month: Decimal = Decimal("1000.00")
    budget_alert_ratio: float = 0.8
    plan: str = "standard"
    confidence_human_review: float = 0.60

    # Billing
    payment_test_mode: bool = True
    payment_webhook_secret: str = ""
    payment_fee_ratio: Decimal = Decimal("0")

    # Auth
    session_ttl_seconds: int = 60 * 60 * 12
    magic_link_ttl_seconds: int = 60 * 15
    reset_ttl_seconds: int = 60 * 30
    otp_ttl_seconds: int = 60 * 5
    lockout_threshold: int = 5
    lockout_seconds: int = 900
    slow_down_after: int = 3
    terms_version: str = "2026-10-22"
    # Development only: show one-time links and codes on the page, for requests
    # that come from this machine. Never true in production.
    dev_show_links: bool = False

    # Integrations (delivery in dev is written to data/outbox.log, never returned)
    email_api_key: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    sms_api_key: str = ""
    payment_api_key: str = ""

    @classmethod
    def from_env(cls, **overrides) -> "Settings":
        load_dotenv()
        base = dict(
            app_secret=os.environ.get("APP_SECRET", ""),
            database_path=_under_root(os.environ.get("DATABASE_PATH", "data/nivora.db")),
            dev_mode=_bool("DEV_MODE", True),
            force_https=_bool("FORCE_HTTPS", False),
            session_secure=_bool("SESSION_SECURE", True),
            log_path=_under_root(os.environ.get("LOG_PATH", "data/nivora.log")),
            ai_enabled=_bool("AI_ENABLED", True),
            ai_provider=os.environ.get("AI_PROVIDER", "ollama").strip().lower(),
            ollama_base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
            ollama_model=os.environ.get("OLLAMA_MODEL", "gigalab-local"),
            fallback_provider=os.environ.get("FALLBACK_PROVIDER", "anthropic").strip().lower(),
            fallback_model=os.environ.get("FALLBACK_MODEL", "claude-3-5-haiku-latest"),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            anthropic_base_url=os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
            ai_timeout_seconds=_float("AI_TIMEOUT_SECONDS", 20.0),
            ai_total_deadline_seconds=_float("AI_TOTAL_DEADLINE_SECONDS", 60.0),
            ai_max_tokens=_int("AI_MAX_TOKENS", 20000),
            ai_output_tokens=_int("AI_OUTPUT_TOKENS", 700),
            ai_local_fallback=_bool("AI_LOCAL_FALLBACK", _bool("DEV_MODE", True)),
            public_base_url=os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/"),
            bot_enabled=_bool("BOT_ENABLED", True),
            flowise_url=os.environ.get("FLOWISE_URL", "").strip(),
            flowise_api_key=os.environ.get("FLOWISE_API_KEY", "").strip(),
            flowise_timeout_seconds=_float("FLOWISE_TIMEOUT_SECONDS", 35.0),
            ai_usd_per_1k_in=Decimal(os.environ.get("AI_USD_PER_1K_IN", "0") or "0"),
            ai_usd_per_1k_out=Decimal(os.environ.get("AI_USD_PER_1K_OUT", "0") or "0"),
            max_input_chars=_int("MAX_INPUT_CHARS", 4000),
            rate_person_per_minute=_int("RATE_PERSON_PER_MINUTE", 10),
            rate_tenant_per_day=_int("RATE_TENANT_PER_DAY", 56),
            budget_rm_month=Decimal(os.environ.get("AI_BUDGET_RM_MONTH", "1000.00") or "1000.00"),
            budget_alert_ratio=_float("AI_BUDGET_ALERT_RATIO", 0.8),
            plan=os.environ.get("PLAN", "standard"),
            confidence_human_review=_float("CONFIDENCE_HUMAN_REVIEW", 0.60),
            payment_test_mode=_bool("PAYMENT_TEST_MODE", True),
            payment_webhook_secret=os.environ.get("PAYMENT_WEBHOOK_SECRET", ""),
            payment_fee_ratio=Decimal(os.environ.get("PAYMENT_FEE_RATIO", "0") or "0"),
            session_ttl_seconds=_int("SESSION_TTL_SECONDS", 60 * 60 * 12),
            magic_link_ttl_seconds=_int("MAGIC_LINK_TTL_SECONDS", 900),
            reset_ttl_seconds=_int("RESET_TTL_SECONDS", 1800),
            otp_ttl_seconds=_int("OTP_TTL_SECONDS", 300),
            lockout_threshold=_int("LOCKOUT_THRESHOLD", 5),
            lockout_seconds=_int("LOCKOUT_SECONDS", 900),
            slow_down_after=_int("SLOW_DOWN_AFTER", 3),
            terms_version=os.environ.get("TERMS_VERSION", "2026-10-22"),
            dev_show_links=_bool("DEV_SHOW_LINKS", _bool("DEV_MODE", True)),
            email_api_key=os.environ.get("EMAIL_API_KEY", ""),
            google_client_id=os.environ.get("GOOGLE_CLIENT_ID", ""),
            google_client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", ""),
            sms_api_key=os.environ.get("SMS_API_KEY", ""),
            payment_api_key=os.environ.get("PAYMENT_API_KEY", ""),
        )
        base.update(overrides)
        if not base["app_secret"]:
            if base.get("dev_mode"):
                base["app_secret"] = "dev-only-insecure-secret-change-me"
            else:
                raise RuntimeError("APP_SECRET is required (set it in .env)")
        return cls(**base)

    def ensure_dirs(self) -> None:
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.log_path).parent.mkdir(parents=True, exist_ok=True)

    @property
    def cookie_name(self) -> str:
        return "nivora_session"

    def public_dict(self) -> dict:
        """What the browser may know. Never secrets."""
        return {
            "app": "NIVORA",
            "dev_mode": self.dev_mode,
            "terms_version": self.terms_version,
            "plans": True,
        }
