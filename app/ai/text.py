"""Text utilities shared by the contracts and the local fallback parser."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta
from decimal import Decimal

BANNED = [
    "free", "percuma", "guarantee", "guaranteed", "dijamin", "jaminan", "refund",
    "100%", "pasti untung", "confirm untung", "risk-free", "no risk", "tanpa risiko",
    "investment advice", "nasihat pelaburan",
]

INJECTION_PATTERNS = [
    r"ignore (all |your |the )?(previous |prior )?(rules|instructions|prompt)",
    r"disregard (all |your |the )?(previous |prior )?(rules|instructions)",
    r"abaikan (semua )?(arahan|peraturan|prompt)",
    r"jangan ikut (arahan|peraturan)",
    r"you are now",
    r"act as (an? )?(admin|developer|system)",
    r"system prompt",
    r"reveal (your|the) (prompt|instructions|rules)",
    r"developer mode",
    r"jailbreak",
    r"reply (with )?(only )?[A-Z]{3,}",
]

MONTHS = {
    "januari": 1, "january": 1, "jan": 1,
    "februari": 2, "february": 2, "feb": 2,
    "mac": 3, "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "mei": 5, "may": 5,
    "jun": 6, "june": 6,
    "julai": 7, "july": 7, "jul": 7,
    "ogos": 8, "august": 8, "aug": 8,
    "september": 9, "sep": 9,
    "oktober": 10, "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "disember": 12, "december": 12, "dec": 12,
}
WEEKDAYS = {
    "isnin": 0, "monday": 0, "mon": 0,
    "selasa": 1, "tuesday": 1, "tue": 1,
    "rabu": 2, "wednesday": 2, "wed": 2,
    "khamis": 3, "thursday": 3, "thu": 3,
    "jumaat": 4, "friday": 4, "fri": 4,
    "sabtu": 5, "saturday": 5, "sat": 5,
    "ahad": 6, "sunday": 6, "sun": 6,
}

UNIT_WORDS = {
    "biji": "biji", "biji.": "biji", "pcs": "biji", "pc": "biji", "piece": "biji",
    "pieces": "biji", "unit": "biji", "units": "biji",
    "kotak": "kotak", "box": "kotak", "boxes": "kotak",
    "kg": "kg", "kilogram": "kg", "kilograms": "kg",
    "g": "g", "gram": "g", "grams": "g",
    "ml": "ml", "l": "liter", "liter": "liter", "litre": "liter", "litres": "liter",
    "batang": "batang", "paket": "paket", "packet": "paket", "pack": "paket",
    "packets": "paket", "packs": "paket", "trays": "dulang", "tray": "dulang",
    "dozen": "lusin", "lusin": "lusin", "dulang": "dulang",
    "buku": "buku",
}

QTY_RE = re.compile(
    r"(?<![\d/])(\d{1,5}(?:[.,]\d{1,3})?)\s*"
    r"(biji|kotak|boxes|box|pcs|pc|pieces|piece|units?|kg|kilograms?|gram|grams|g|ml|"
    r"liter|litre|litres|l|batang|paket|packet|pack|dozen|lusin|tray|dulang|buku)\b",
    re.I,
)
BARE_QTY_RE = re.compile(r"(?<![\d/])(\d{1,4})\s+(?=[A-Za-z])")
PRICE_RE = re.compile(r"(?:rm|myr|\$)\s?\d+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?\s?(?:ringgit|rm\b)", re.I)
DATE_NUMERIC_RE = re.compile(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b")
DATE_ISO_RE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
DATE_TEXT_RE = re.compile(
    r"\b(\d{1,2})\s+(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\b(?:\s+(\d{4}))?",
    re.I,
)
TIME_WORDS = {
    "esok": 1, "tomorrow": 1, "hari ini": 0, "today": 0, "lusa": 2,
    "minggu depan": 7, "next week": 7, "bulan depan": 30, "next month": 30,
}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower()
    return re.sub(r"\s+", " ", text).strip()


def tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", normalize(text)) if len(t) >= 3]


def strip_code_fences(text: str) -> str:
    value = (text or "").strip()
    if value.startswith("```"):
        value = re.sub(r"^```[a-zA-Z]*\s*", "", value)
        value = re.sub(r"\s*```$", "", value)
    return value.strip()


def iso_dates(raw: str, today: date) -> list[str]:
    """Every date the message actually says, as ISO strings."""
    text = normalize(raw)
    found: set[date] = set()
    for match in DATE_ISO_RE.finditer(text):
        try:
            found.add(date(int(match.group(1)), int(match.group(2)), int(match.group(3))))
        except ValueError:
            pass
    for match in DATE_NUMERIC_RE.finditer(text):
        day, month = int(match.group(1)), int(match.group(2))
        year = int(match.group(3)) if match.group(3) else today.year
        if year < 100:
            year += 2000
        try:
            found.add(date(year, month, day))
        except ValueError:
            continue
    for match in DATE_TEXT_RE.finditer(text):
        day, month_name = int(match.group(1)), match.group(2)
        month = MONTHS.get(month_name)
        year = int(match.group(3)) if match.group(3) else today.year
        if month:
            try:
                found.add(date(year, month, day))
            except ValueError:
                pass
    for phrase, offset in TIME_WORDS.items():
        if phrase in text:
            found.add(today + timedelta(days=offset))
    for name, weekday in WEEKDAYS.items():
        if re.search(rf"\b{name}\b", text):
            delta = (weekday - today.weekday()) % 7 or 7
            found.add(today + timedelta(days=delta))
    return sorted(d.isoformat() for d in found)


def prices_in(raw: str) -> list[Decimal]:
    out = []
    for match in PRICE_RE.finditer(normalize(raw)):
        number = re.sub(r"[^0-9.,]", "", match.group(0)).replace(",", ".")
        try:
            out.append(Decimal(number))
        except ArithmeticError:
            continue
    return out


def has_currency(text: str) -> bool:
    return bool(PRICE_RE.search(normalize(text)))


def injection_flags(raw: str) -> list[str]:
    text = normalize(raw)
    return [p for p in INJECTION_PATTERNS if re.search(p, text, re.I)]


def banned_hits(text: str) -> list[str]:
    text = normalize(text)
    return [word for word in BANNED if word in text]


def is_question(raw: str) -> bool:
    text = normalize(raw)
    text = re.sub(r"^(hi|hai|hello|hey|salam|assalamualaikum|selamat pagi|selamat tengah hari|"
                  r"good morning|good afternoon|good evening)[\s,.!]*", "", text)
    if "?" in text:
        return True
    if re.search(r"\b(tanya|bertanya|nak tahu|what do you sell|what do you have|your menu|"
                 r"price list|berapa harga|menu apa)\b", text):
        return True
    starters = ("apa", "apakah", "berapa", "bila", "di mana", "mana", "siapa", "boleh tak",
                "what", "do you", "can you", "how", "when", "where", "which", "is there", "are there")
    return any(text.startswith(s) for s in starters)


def matches_grounded(value: str, raw: str, min_ratio: float = 0.6) -> bool:
    """True when the words of `value` really appear in the customer's message."""
    value_tokens = [t for t in tokens(value) if not t.isdigit() or len(t) >= 3]
    if not value_tokens:
        return True
    raw_norm = " " + normalize(raw) + " "
    hits = sum(1 for t in value_tokens if t in raw_norm)
    if hits / len(value_tokens) >= min_ratio:
        return True
    # Numbers are grounded by value, not by token length.
    numbers = [t for t in re.findall(r"\d+", value or "") if t not in raw_norm]
    if numbers:
        return False
    return hits / len(value_tokens) >= min_ratio
