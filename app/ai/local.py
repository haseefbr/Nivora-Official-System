"""The deterministic local provider.

Ollama (gigalab-local) is the chosen model. When no model is reachable — a
laptop with no ollama, or the offline demo — this provider reads the message
with rules and returns the same JSON shape. Its replies go through exactly the
same contract checks, and the call log records provider="local-rules", so no
one mistakes it for the model.
"""
from __future__ import annotations

import json
import re
from datetime import date

from .provider import Completion
from .text import QTY_RE, BARE_QTY_RE, UNIT_WORDS, is_question, iso_dates, normalize
from .research import heuristic_research

STOP = {
    "saya", "aku", "nak", "mahu", "ingin", "want", "wants", "wanted", "would", "like",
    "to", "order", "orders", "ordering", "tempah", "book", "booking", "pesan", "beli",
    "please", "tolong", "boleh", "can", "could", "you", "your", "kami", "kita", "i",
    "we", "me", "my", "a", "an", "the", "some", "of", "for", "pada", "untuk", "hari",
    "ini", "tu", "itu", "ya", "hi", "hai", "hello", "hey", "salam", "assalamualaikum",
    "thanks", "thank", "terima", "kasih", "sebanyak", "about", "around", "dan", "and",
    "juga", "plus", "dengan", "with", "delivery", "antar", "antarkan", "hantar",
    "hantarkan", "ke", "di", "at", "on", "by", "before", "after", "pagi", "petang",
    "malam", "tengah", "noon", "adalah", "ialah", "ni", "resepi", "resipi", "recipe",
    "minta", "bagi", "give", "add", "tambah", "sila", "customer", "pelanggan",
    "delivered", "deliver", "delivering", "dihantar", "diantar", "sampai", "until",
    "sebelum", "pukul", "jam", "this", "is", "was", "we", "please", "kindly", "would",
}


def _clean(phrase: str) -> str:
    text = normalize(phrase)
    text = re.sub(r"\b(?:nama saya|my name is|name is)\b.*$", " ", text)
    text = re.sub(r"\b(?:esok|lusa|hari ini|today|tomorrow|minggu depan|next week)\b", " ", text)
    text = re.sub(r"\b(?:isnin|selasa|rabu|khamis|jumaat|sabtu|ahad|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", " ", text)
    text = re.sub(r"\d{1,4}[/-]\d{1,2}(?:[/-]\d{2,4})?", " ", text)
    words = [w for w in re.findall(r"[a-z0-9]+", text) if w not in STOP and not w.isdigit()]
    return " ".join(words[-6:]).strip()


def _unit(word: str) -> str:
    return UNIT_WORDS.get((word or "").lower().rstrip("."), (word or "biji").lower())


def _extract_address(raw: str) -> str | None:
    text = raw.strip()
    markers = (
        r"(?:alamat(?: saya)?|address|antar(?:kan)? ke|hantar(?:kan)? ke|"
        r"deliver(?:y|ed|ing)?(?:\s+on\s+[^,.]{1,20})?\s+to|send\s+to|diantar\s+ke|dihantar\s+ke)"
    )
    match = re.search(markers + r"\s*[:\-]?\s*(.+?)(?:[.;\n]|$)", text, re.I)
    if match:
        value = match.group(1).strip()
        value = re.split(r"\b(?:resepi|resipi|recipe|terima kasih|thanks|this is|nama saya|"
                         r"my name is)\b", value, flags=re.I)[0]
        # "12 Jalan Melati, nama Aminah" -> the name is not part of the street.
        value = re.sub(r"[,\s]+(?:nama|name)\s+(?:saya\s+|is\s+)?[A-Za-z@][A-Za-z@ .]{1,40}$",
                       "", value, flags=re.I).strip(" ,.")
        value = re.sub(r"\b(?:esok|lusa|hari ini|today|tomorrow)\b.*$", "", value, flags=re.I).strip(" ,.")
        if len(value) >= 6:
            return value[:300]
    # Street + postcode, stopping at the end of the clause.
    street = re.search(r"(\d{1,4}\s+[A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*){0,4},\s*\d{5}\s+[A-Z][A-Za-z ]{2,30})", text)
    if street:
        return street.group(1).strip(" ,.")[:300]
    postcode = re.search(r"(\d{5}\s+[A-Z][A-Za-z]{2,30})", text)
    if postcode:
        return postcode.group(1).strip(" ,.")[:300]
    return None


def _extract_name(raw: str) -> str | None:
    for pattern in (r"nama saya\s+([A-Za-z@][A-Za-z@ .]{1,40})",
                    r"[,\s]+nama\s+([A-Za-z@][A-Za-z@.]{1,40})",
                    r"my name is\s+([A-Za-z@][A-Za-z@ .]{1,40})",
                    r"name is\s+([A-Za-z@][A-Za-z@ .]{1,40})"):
        match = re.search(pattern, raw, re.I)
        if match:
            value = re.split(r"[,.;\n]|\b(?:dan|and|untuk|for)\b", match.group(1), flags=re.I)[0]
            value = value.strip(" ,.")
            if 1 < len(value) <= 120:
                return value
    return None


def _extract_recipe(raw: str) -> str | None:
    match = re.search(r"(?:resepi|resipi|recipe|guna resepi|using recipe)\s*[:\-]?\s*([A-Za-z0-9 .]{2,60})", raw, re.I)
    if match:
        value = re.split(r"[,:;\n]", match.group(1))[0].strip(" .")
        if value:
            return value
    return None


def _items(text: str) -> list[dict]:
    matches = list(QTY_RE.finditer(text))
    if not matches:
        matches = list(BARE_QTY_RE.finditer(text))
    items: list[dict] = []
    seen: set[str] = set()
    for index, match in enumerate(matches):
        following_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        following = text[match.end():following_end]
        preceding = text[matches[index - 1].end() if index else 0:match.start()]
        product = ""
        if re.match(r"\s*[A-Za-z]", following):
            cut = re.split(r"[,;.\n]|\b(?:dan|and|untuk|for|pada|on)\b", following, maxsplit=1, flags=re.I)[0]
            product = _clean(cut)
        if len(product) < 2:
            product = _clean(preceding)
        if len(product) < 2:
            continue
        quantity = match.group(1).replace(",", ".")
        unit = _unit(match.group(2) if match.lastindex and match.lastindex >= 2 else "biji")
        key = product.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "product_name": product[:120],
            "quantity": float(quantity),
            "unit": unit,
            "recipe": None,
        })
    return items


def heuristic_parse(raw: str, today: date) -> dict:
    address = _extract_address(raw)
    body = raw
    if address:
        body = re.sub(re.escape(address), " ", body, count=1, flags=re.I)
    items = _items(body)
    dates = iso_dates(raw, today)
    intent = "order" if items else ("question" if is_question(raw) else "other")
    confidence = 0.33
    if items:
        confidence = 0.94 if dates else 0.86
    elif intent == "question":
        confidence = 0.35
    note = None
    if intent == "question":
        note = ("Kami menjual kuih-muih dan makanan Melayu seperti kuih lapis, seri muka "
                "dan pineapple tart. Beritahu produk, bilangan, tarikh dan alamat untuk tempahan.")
    elif intent == "other":
        note = "Saya belum nampak tempahan yang jelas. Sila tulis produk, bilangan, tarikh dan alamat."
    return {
        "intent": intent,
        "customer_name": _extract_name(raw),
        "items": items,
        "delivery_date": dates[0] if dates else None,
        "address": address,
        "note": note,
        "confidence": confidence,
    }


def heuristic_cost(raw: str, today: date) -> dict:
    text = raw.strip()
    before = re.search(r"([A-Za-z0-9 ]{2,40})\s+(?:resepi|resipi|recipe)\b", text, re.I)
    after = re.search(r"(?:resepi|resipi|recipe)\s*[:\-]?\s*([^:,\n]{2,60})", text, re.I)
    if before:
        recipe_name = before.group(1).strip(" .")
    elif after:
        recipe_name = after.group(1).strip(" .")
    else:
        recipe_name = "Recipe"
    body = text
    if ":" in text:
        body = text.split(":", 1)[1]
    elif after:
        body = text[after.end():]
    yield_match = re.search(r"(?:dapat|menghasilkan|hasil|yield|makes|make)\s*(\d{1,4})", body, re.I)
    yield_units = int(yield_match.group(1)) if yield_match else 1
    if yield_match:
        body = body[:yield_match.start()] + " " + body[yield_match.end():]
    matches = list(QTY_RE.finditer(body))
    items, seen = [], set()
    for index, match in enumerate(matches):
        following_end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        following = body[match.end():following_end]
        preceding = body[matches[index - 1].end() if index else 0:match.start()]
        ingredient = ""
        if re.match(r"\s*[A-Za-z]", following):
            cut = re.split(r"[,;.\n]|\b(?:dan|and)\b", following, maxsplit=1, flags=re.I)[0]
            ingredient = _clean(cut)
        if len(ingredient) < 2:
            ingredient = _clean(preceding)
        if len(ingredient) < 2:
            continue
        key = ingredient.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "ingredient": ingredient[:120],
            "quantity": float(match.group(1).replace(",", ".")),
            "unit": _unit(match.group(2) if match.lastindex and match.lastindex >= 2 else "g"),
        })
    confidence = 0.9 if items and yield_units > 1 else (0.7 if items else 0.2)
    return {
        "recipe_name": recipe_name[:120] or "Recipe",
        "product_name": recipe_name[:120] or None,
        "yield_units": max(1, yield_units),
        "items": items,
        "confidence": confidence,
    }


class LocalProvider:
    """Deterministic, no network. Last in the chain; used only when no model answers."""

    name = "local-rules"

    def __init__(self, today: date, model: str = "local-rules"):
        self.today = today
        self.model = model

    def complete(self, system: str, user: str, max_tokens: int, timeout: float) -> Completion:
        raw = user
        start = raw.find("<dish>")
        end = raw.find("</dish>")
        if start != -1 and end != -1:
            dish = raw[start + len("<dish>"):end].replace("‹", "<").replace("›", ">").strip()
            payload = heuristic_research(dish)
            return Completion(
                text=json.dumps(payload, ensure_ascii=False),
                tokens_in=max(1, len(user) // 4),
                tokens_out=max(1, len(json.dumps(payload)) // 4),
                model="local-recipe-kb",
                provider=self.name,
            )
        start = raw.find("<customer_message>")
        end = raw.find("</customer_message>")
        if start != -1 and end != -1:
            raw = raw[start + len("<customer_message>"):end]
            payload = heuristic_parse(raw.replace("‹", "<").replace("›", ">"), self.today)
        else:
            start = raw.find("<recipe_message>")
            end = raw.find("</recipe_message>")
            if start != -1 and end != -1:
                raw = raw[start + len("<recipe_message>"):end]
                payload = heuristic_cost(raw.replace("‹", "<").replace("›", ">"), self.today)
            else:
                payload = heuristic_parse(raw, self.today)
        return Completion(
            text=json.dumps(payload, ensure_ascii=False),
            tokens_in=max(1, len(user) // 4),
            tokens_out=max(1, len(json.dumps(payload)) // 4),
            model=self.model,
            provider=self.name,
        )
