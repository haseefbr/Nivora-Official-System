"""Delivery for magic links and one-time codes.

With a provider key, it posts to the provider. Without one (development), it
writes to data/outbox.log on the server. A link is never returned in an HTTP
response, so a stranger cannot ask for someone else's sign-in link.
"""
from __future__ import annotations

from pathlib import Path

import httpx

from .settings import Settings
from .safelog import logger_for


def outbox_path(settings: Settings) -> Path:
    return Path(settings.log_path).parent / "outbox.log"


def _write_outbox(settings: Settings, kind: str, to: str, subject: str, body: str) -> None:
    path = outbox_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"--- {kind} to={to} subject={subject}\n{body}\n")


def send_email(settings: Settings, to: str, subject: str, body: str) -> bool:
    if not settings.email_api_key:
        if settings.dev_mode:
            _write_outbox(settings, "email", to, subject, body)
            return True
        logger_for(settings).warning("email_not_configured")
        return False
    try:
        response = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.email_api_key}"},
            json={
                "from": "NIVORA <noreply@nivora.app>",
                "to": [to],
                "subject": subject,
                "text": body,
            },
            timeout=10.0,
        )
        if response.status_code >= 300:
            logger_for(settings).warning("email_delivery_failed status=%s", response.status_code)
            return False
        return True
    except httpx.HTTPError:
        logger_for(settings).warning("email_delivery_error")
        if settings.dev_mode:
            _write_outbox(settings, "email", to, subject, body)
            return True
        return False


def send_sms(settings: Settings, phone: str, body: str) -> bool:
    if not settings.sms_api_key:
        if settings.dev_mode:
            _write_outbox(settings, "sms", phone, "", body)
            return True
        logger_for(settings).warning("sms_not_configured")
        return False
    try:
        response = httpx.post(
            "https://api.twilio.com/2010-04-01/Accounts/messages.json",
            auth=(settings.sms_api_key.split(":")[0], ":".join(settings.sms_api_key.split(":")[1:])),
            data={"To": phone, "Body": body},
            timeout=10.0,
        )
        return response.status_code < 300
    except httpx.HTTPError:
        logger_for(settings).warning("sms_delivery_error")
        if settings.dev_mode:
            _write_outbox(settings, "sms", phone, "", body)
            return True
        return False
