"""The shop's chatbot: a Flowise agent flow, grounded on this shop's own facts.

The flow answers from its own training knowledge, so every call carries a strict
context block built from our database and rules that forbid inventing prices,
hours or policies. Nothing is stored but the call summary in `ai_calls`.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from decimal import Decimal

import httpx

from .money import money
from .security import iso
from .settings import Settings

MAX_QUESTION = 600
MAX_REPLY = 1200
MAX_HISTORY_TURNS = 6


class BotError(Exception):
    def __init__(self, message: str, code: str = "bot_unavailable", status: int = 502):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


@dataclass
class BotFacts:
    """Everything the bot may say about one shop."""
    name: str
    address: str = ""
    phone: str = ""
    tagline: str = ""
    hours: str = ""
    delivery_fee: str = "4.00"
    shop_url: str = ""
    dishes: list[dict] = field(default_factory=list)
    language: str = "bm"

    def as_context(self) -> str:
        lines = [
            "KONTEKS KEDAI (satu-satunya sumber fakta — SHOP CONTEXT):",
            f"- Nama kedai / Shop: {self.name}",
        ]
        if self.tagline:
            lines.append(f"- Tentang / About: {self.tagline}")
        if self.address:
            lines.append(f"- Alamat / Address: {self.address}")
        if self.phone:
            lines.append(f"- Telefon / Phone: {self.phone}")
        lines.append(f"- Waktu buka / Hours: {self.hours}" if self.hours else
                     "- Waktu buka / Hours: tidak dinyatakan. Jangan reka waktu buka; "
                     "minta pelanggan hubungi kedai.")
        if self.dishes:
            lines.append("- Menu dan harga / Menu and prices:")
            for dish in self.dishes:
                bits = [f"  • {dish['name']} — RM{dish['price']}"]
                if dish.get("category"):
                    bits.append(f"({dish['category']})")
                if dish.get("description"):
                    bits.append(f"– {dish['description']}")
                lines.append(" ".join(bits))
        else:
            lines.append("- Menu: belum disenaraikan / not listed yet")
        lines.append(f"- Penghantaran / Delivery: RM{self.delivery_fee} (dalam kawasan), "
                     "ambil sendiri di kedai / self-pickup: percuma (free)")
        lines.append("- Pembayaran / Payment: tunai semasa terima, atau online banking "
                     "(the shop confirms before cooking)")
        if self.shop_url:
            lines.append(f"- Pautan pesanan / Order link: {self.shop_url}")
        return "\n".join(lines)


RULES = """ARAHAN (WAJIB):
1. Jawab dalam bahasa yang sama dengan pelanggan: Bahasa Melayu atau English.
2. Guna HANYA fakta dalam KONTEKS KEDAI di atas. Jangan reka harga, menu, waktu, alamat atau polisi.
3. Jika jawapan tiada dalam konteks, kata dengan jujur anda tidak pasti dan minta pelanggan hubungi kedai.
4. Jangan sebut "konteks", "dokumen", "knowledge base", "AI" atau "model". Jawab seperti staf kedai yang mesra.
5. Ringkas dan terus: maksimum 3 ayat pendek. Tiada senarai panjang melainkan pelanggan minta menu.
6. Jangan ambil pesanan di sini. Jika pelanggan mahu membeli, beri pautan pesanan.
7. Jangan guna emoji berlebihan. Jangan tulis "Berikut adalah ringkasan" atau pembuka kosong."""


def build_question(facts: BotFacts, message: str, history: list[dict] | None = None) -> str:
    """One string for the flow: context, rules, recent turns, then the question."""
    parts = [facts.as_context(), "", RULES, ""]
    turns = [t for t in (history or []) if t.get("text")][-MAX_HISTORY_TURNS:]
    if turns:
        parts.append("PERBUALAN SEBELUM INI / EARLIER TURNS:")
        for turn in turns:
            who = "Pelanggan" if turn.get("role") != "bot" else "Kedai"
            parts.append(f"{who}: {str(turn['text'])[:300]}")
        parts.append("")
    parts.append(f"SOALAN PELANGGAN / CUSTOMER QUESTION: {message.strip()[:MAX_QUESTION]}")
    return "\n".join(parts)


_OPENERS = re.compile(
    r"^(?:berikut(?: adalah)?[^:\n]{0,80}:|here(?:'s| is)[^:\n]{0,80}:|"
    r"tentu[!,]?|sudah tentu[!,]?|of course[!,]?|sure[!,]?)\s*",
    re.I,
)


def tidy(text: str) -> str:
    """Strip the flow's chatty preamble and keep the answer."""
    text = (text or "").strip()
    text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)      # **bold** -> bold
    text = re.sub(r"^\s*#{1,4}\s*", "", text, flags=re.M)      # ### heading
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = _OPENERS.sub("", text).strip()
    text = re.sub(r"^[\-\u2014:,\s]+", "", text).strip()
    if len(text) > MAX_REPLY:
        cut = text[:MAX_REPLY]
        stop = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "), cut.rfind("\n"))
        text = cut[:stop + 1] if stop > 200 else cut
    return text.strip()


_HOURS_Q = re.compile(
    r"\b(buka|tutup|waktu|jam|pukul|operasi|open|opens|opening|closed|close|closing|hour|hours|time)\b", re.I)
_DELIVERY_Q = re.compile(
    r"\b(hantar|penghantaran|delivery|deliver|postage|pos|pickup|pick up|ambil sendiri|self.pickup)\b", re.I)
_DAY = re.compile(
    r"\b(isnin|selasa|rabu|khamis|jumaat|sabtu|ahad|monday|tuesday|wednesday|thursday|friday|"
    r"saturday|sunday)\b", re.I)
_CLOCK = re.compile(r"\d{1,2}[:.]\d{2}")


def guard(reply: str, facts: BotFacts, question: str) -> str:
    """Append a stored fact the model left out of a direct question about it.

    The flow is a general agent: it paraphrases and sometimes drops the closing
    day or the delivery fee. Those are the two facts that cost the shop money
    when they are wrong, so they are checked against the reply, not trusted to it.
    """
    text = reply.rstrip()
    lower = text.lower()
    if facts.hours and _HOURS_Q.search(question):
        days = {m.group(0).lower() for m in _DAY.finditer(facts.hours)}
        clocks = set(_CLOCK.findall(facts.hours))
        missing_day = any(day not in lower for day in days)
        missing_clock = bool(clocks) and not any(clock in lower for clock in clocks)
        if missing_day or missing_clock:
            text = text + "\n\nWaktu buka: " + facts.hours + "."
    if _DELIVERY_Q.search(question):
        fee = "RM" + str(facts.delivery_fee)
        said_fee = fee.lower() in lower
        said_free = "percuma" in lower or "free" in lower
        if not said_fee and not said_free:
            text = text + "\n\nPenghantaran " + fee + " dalam kawasan; ambil sendiri di kedai percuma."
    return text


class BotClient:
    """POST /api/v1/prediction/<flow> on Flowise."""

    name = "flowise"

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.settings = settings
        self.url = (settings.flowise_url or "").strip()
        self.key = (settings.flowise_api_key or "").strip()
        self.timeout = max(5.0, float(settings.flowise_timeout_seconds or 30.0))
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(self.url)

    def reply(self, question: str, session_id: str | None = None) -> tuple[str, int]:
        if not self.configured:
            raise BotError("The shop assistant is not switched on yet.", "bot_not_configured", 503)
        body: dict = {"question": question[:4000]}
        if session_id:
            body["sessionId"] = str(session_id)[:64]
        headers = {"Content-Type": "application/json"}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        started = time.monotonic()
        try:
            client = self._client or httpx.Client(timeout=self.timeout)
            try:
                response = client.post(self.url, json=body, headers=headers, timeout=self.timeout)
            finally:
                if self._client is None:
                    client.close()
        except httpx.TimeoutException as exc:
            raise BotError("The assistant is thinking too long. Try again.", "bot_timeout", 504) from exc
        except httpx.HTTPError as exc:
            raise BotError("The assistant is unreachable right now.", "bot_unreachable", 502) from exc
        duration = int((time.monotonic() - started) * 1000)
        if response.status_code >= 500:
            raise BotError("The assistant had a problem. Try again.", "bot_failed", 502)
        if response.status_code >= 400:
            raise BotError("The assistant refused that request.", "bot_refused", 502)
        try:
            data = response.json()
        except ValueError as exc:
            raise BotError("The assistant sent an unreadable reply.", "bot_unreadable", 502) from exc
        text = data.get("text") or data.get("answer") or data.get("output") or ""
        if isinstance(text, dict):
            text = text.get("text", "")
        text = tidy(str(text))
        if not text:
            raise BotError("The assistant had nothing to say. Try again.", "bot_empty", 502)
        return text, duration


def facts_for(conn, tenant_id: int, settings: Settings) -> BotFacts:
    """Read the shop's own truth: name, contact, menu, link."""
    tenant = conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
    if tenant is None:
        raise BotError("That shop does not exist.", "not_found", 404)
    dishes = []
    for row in conn.execute(
        "SELECT name, price, category, description FROM products"
        " WHERE tenant_id = ? AND active = 1 ORDER BY sort_order, name LIMIT 60",
        (tenant_id,),
    ).fetchall():
        dishes.append({
            "name": row["name"],
            "price": money(row["price"]),
            "category": row["category"] or "",
            "description": (row["description"] or "")[:90],
        })
    slug = tenant["public_slug"] or ""
    base = (settings.public_base_url or "").rstrip("/")
    return BotFacts(
        name=tenant["name"],
        address=tenant["address"] or "",
        phone=tenant["phone"] or "",
        hours=(tenant["hours"] or "") if "hours" in tenant.keys() else "",
        tagline=tenant["tagline"] or "",
        shop_url=f"{base}/shop?b={slug}" if slug else "",
        dishes=dishes,
        delivery_fee="4.00",
    )


def log_bot_call(conn, tenant_id: int, request_id: str, duration_ms: int,
                 outcome: str, check: str = "chat") -> None:
    """One row in ai_calls so the owner can see the bot is working."""
    conn.execute(
        "INSERT INTO ai_calls (tenant_id, request_id, feature, model, provider, tokens_in,"
        " tokens_out, cost_usd, duration_ms, outcome, checks, fallback_used, needs_human, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (tenant_id, request_id, "CHATBOT", "flowise-agent", "flowise", 0, 0, "0.000000",
         duration_ms, outcome, check[:500], 0, 0, iso()),
    )


def parse_history(raw) -> list[dict]:
    """Accept [{role, text}] from the browser, keep it small and safe."""
    out: list[dict] = []
    for item in (raw or [])[-MAX_HISTORY_TURNS:]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()[:300]
        if not text:
            continue
        out.append({"role": "bot" if item.get("role") == "bot" else "user", "text": text})
    return out


def money_str(value) -> str:
    return str(Decimal(str(value)))
