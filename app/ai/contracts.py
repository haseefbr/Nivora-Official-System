"""The two prompt contracts and the three check layers.

Every model reply is checked in code before anything uses it:
  syntax  -> the reply parses as JSON           (ContractSyntaxError)
  schema  -> the fields are the right shape      (ContractSchemaError)
  business-> the rules and never-rules hold      (ContractRuleError)

Failure policy: repair once, then a safe reply (app/ai/runner.py).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

from .text import (
    banned_hits,
    has_currency,
    injection_flags,
    iso_dates,
    matches_grounded,
    normalize,
    prices_in,
    strip_code_fences,
)


class ContractError(Exception):
    layer = "contract"

    def __init__(self, message: str, detail: str | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail


class ContractSyntaxError(ContractError):
    layer = "syntax"


class ContractSchemaError(ContractError):
    layer = "schema"


class ContractRuleError(ContractError):
    layer = "business"


@dataclass
class CheckReport:
    syntax: bool = False
    schema: bool = False
    business: bool = False
    errors: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.syntax and self.schema and self.business

    def fail(self, layer: str, message: str) -> "CheckReport":
        self.errors.append({"layer": layer, "message": message})
        return self

    def summary(self) -> str:
        if self.ok:
            return "syntax+schema+business"
        return ";".join(f"{e['layer']}:{e['message']}" for e in self.errors)[:500]

    def to_dict(self) -> dict:
        return {
            "syntax": self.syntax, "schema": self.schema, "business": self.business,
            "ok": self.ok, "errors": self.errors,
        }


def parse_json_reply(text: str) -> Any:
    cleaned = strip_code_fences(text)
    try:
        return json.loads(cleaned)
    except (ValueError, TypeError):
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = cleaned.find(opener), cleaned.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except ValueError:
                continue
    raise ContractSyntaxError("The reply is not valid JSON")


def _number(value: Any, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractSchemaError(f"Field '{name}' must be a number")
    value = float(value)
    if not (low <= value <= high):
        raise ContractSchemaError(f"Field '{name}' is outside {low}..{high}")
    return value


def _optional_text(value: Any, name: str, limit: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ContractSchemaError(f"Field '{name}' must be text or null")
    value = value.strip()
    if len(value) > limit:
        raise ContractSchemaError(f"Field '{name}' is longer than {limit} characters")
    return value or None


def _iso_day(value: Any, name: str) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ContractSchemaError(f"Field '{name}' must be a date (YYYY-MM-DD) or null")
    try:
        parsed = date.fromisoformat(value[:10])
    except ValueError as exc:
        raise ContractSchemaError(f"Field '{name}' is not a date like 2026-10-24") from exc
    if not (2000 <= parsed.year <= 2100):
        raise ContractSchemaError(f"Field '{name}' has an implausible year")
    return parsed.isoformat()


# ------------------------------------------------------------- F1: parser

PARSER_SCHEMA = {
    "intent": "order | question | other",
    "customer_name": "text | null",
    "items": "[{product_name: text, quantity: number > 0, unit: text, recipe: text | null}]",
    "delivery_date": "YYYY-MM-DD | null",
    "address": "text | null",
    "note": "text | null",
    "confidence": "number 0..1",
}


def check_parser_schema(payload: Any) -> dict:
    if not isinstance(payload, dict):
        raise ContractSchemaError("The reply must be a JSON object")
    for key in ("intent", "items", "delivery_date", "address", "confidence"):
        if key not in payload:
            raise ContractSchemaError(f"The reply is missing '{key}'")
    intent = payload["intent"]
    if intent not in ("order", "question", "other"):
        raise ContractSchemaError("Field 'intent' must be order, question or other")
    items = payload["items"]
    if not isinstance(items, list):
        raise ContractSchemaError("Field 'items' must be a list")
    if len(items) > 30:
        raise ContractSchemaError("Too many items in one reply")
    clean_items = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ContractSchemaError(f"Item {index + 1} must be an object")
        product = _optional_text(item.get("product_name"), f"items[{index}].product_name", 120)
        if not product:
            raise ContractSchemaError(f"Item {index + 1} is missing a product name")
        quantity = _number(item.get("quantity"), f"items[{index}].quantity", 0.001, 1_000_000)
        unit = _optional_text(item.get("unit"), f"items[{index}].unit", 12) or "biji"
        recipe = _optional_text(item.get("recipe"), f"items[{index}].recipe", 120)
        clean_items.append({"product_name": product, "quantity": quantity, "unit": unit, "recipe": recipe})
    return {
        "intent": intent,
        "customer_name": _optional_text(payload.get("customer_name"), "customer_name", 120),
        "items": clean_items,
        "delivery_date": _iso_day(payload.get("delivery_date"), "delivery_date"),
        "address": _optional_text(payload.get("address"), "address", 500),
        "note": _optional_text(payload.get("note"), "note", 300),
        "confidence": _number(payload.get("confidence", 0), "confidence", 0.0, 1.0),
    }


def check_parser_rules(payload: dict, raw: str, today: date) -> None:
    problems: list[str] = []
    if payload["intent"] == "order" and not payload["items"]:
        problems.append("an order needs at least one item")
    if payload["intent"] != "order" and payload["items"]:
        problems.append("items were found but the intent is not 'order'")
    supported_dates = set(iso_dates(raw, today))
    if payload["delivery_date"] and payload["delivery_date"] not in supported_dates:
        problems.append("the delivery date is not in the message (never invent a date)")
    if payload["address"] and not matches_grounded(payload["address"], raw, 0.5):
        problems.append("the address is not in the message (never invent an address)")
    if payload["customer_name"] and not matches_grounded(payload["customer_name"], raw, 0.5):
        problems.append("the customer name is not in the message (never invent a name)")
    for item in payload["items"]:
        if not matches_grounded(item["product_name"], raw, 0.5):
            problems.append(f"product '{item['product_name']}' is not in the message")
        if item["recipe"] and not matches_grounded(item["recipe"], raw, 0.5):
            problems.append("the recipe name is not in the message")
    message_prices = set(prices_in(raw))
    reply_prices = set(prices_in(json.dumps(payload, ensure_ascii=False)))
    invented = {str(p) for p in reply_prices - message_prices}
    if invented:
        problems.append("a price was invented (the message has no such price)")
    if has_currency(json.dumps(payload)) and not has_currency(raw):
        problems.append("a price was invented (the message has no price)")
    for word in banned_hits(json.dumps(payload, ensure_ascii=False)):
        if normalize(word) not in normalize(raw):
            problems.append(f"banned word or promise: '{word}'")
    if problems:
        raise ContractRuleError(problems[0], "; ".join(problems[:5]))


# ------------------------------------------------------------ F3: costing

COSTING_SCHEMA = {
    "recipe_name": "text",
    "product_name": "text | null",
    "yield_units": "whole number > 0",
    "items": "[{ingredient: text, quantity: number > 0, unit: text}]",
    "confidence": "number 0..1",
}


def check_costing_schema(payload: Any) -> dict:
    if not isinstance(payload, dict):
        raise ContractSchemaError("The reply must be a JSON object")
    for key in ("recipe_name", "yield_units", "items", "confidence"):
        if key not in payload:
            raise ContractSchemaError(f"The reply is missing '{key}'")
    name = _optional_text(payload.get("recipe_name"), "recipe_name", 120)
    if not name:
        raise ContractSchemaError("Field 'recipe_name' is empty")
    try:
        yield_units = int(payload["yield_units"])
    except (TypeError, ValueError) as exc:
        raise ContractSchemaError("Field 'yield_units' must be a whole number") from exc
    if not (0 < yield_units <= 100_000):
        raise ContractSchemaError("Field 'yield_units' must be above 0")
    items = payload["items"]
    if not isinstance(items, list):
        raise ContractSchemaError("Field 'items' must be a list")
    if len(items) > 60:
        raise ContractSchemaError("Too many ingredients in one reply")
    clean_items = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ContractSchemaError(f"Ingredient {index + 1} must be an object")
        ingredient = _optional_text(item.get("ingredient"), f"items[{index}].ingredient", 120)
        if not ingredient:
            raise ContractSchemaError(f"Ingredient {index + 1} is missing a name")
        quantity = _number(item.get("quantity"), f"items[{index}].quantity", 0.001, 1_000_000)
        unit = _optional_text(item.get("unit"), f"items[{index}].unit", 12) or "g"
        if "price" in item or "cost" in item or "total" in item:
            raise ContractSchemaError("The model must not set prices; code computes them")
        clean_items.append({"ingredient": ingredient, "quantity": quantity, "unit": unit})
    return {
        "recipe_name": name,
        "product_name": _optional_text(payload.get("product_name"), "product_name", 120),
        "yield_units": yield_units,
        "items": clean_items,
        "confidence": _number(payload.get("confidence", 0), "confidence", 0.0, 1.0),
    }


def check_costing_rules(payload: dict, raw: str, today: date) -> None:
    problems: list[str] = []
    if not payload["items"]:
        problems.append("a recipe needs at least one ingredient")
    for item in payload["items"]:
        if not matches_grounded(item["ingredient"], raw, 0.5):
            problems.append(f"ingredient '{item['ingredient']}' is not in the message")
    if has_currency(json.dumps(payload)) or any(k in payload for k in ("price", "cost", "total")):
        problems.append("the model must not invent a price; code computes costs")
    if payload.get("product_name") and not matches_grounded(payload["product_name"], raw, 0.5):
        problems.append("the product name is not in the message (never invent a name)")
    yield_text = str(payload["yield_units"])
    if yield_text not in normalize(raw) and not re.search(r"\b(?:dapat|yield|makes|hasil)\b", normalize(raw)):
        problems.append("the yield is not in the message (never invent a quantity)")
    for word in banned_hits(json.dumps(payload, ensure_ascii=False)):
        if normalize(word) not in normalize(raw):
            problems.append(f"banned word or promise: '{word}'")
    if problems:
        raise ContractRuleError(problems[0], "; ".join(problems[:5]))


# ------------------------------------------------------- F10: recipe ideas

RESEARCH_SCHEMA = {
    "dish": "text",
    "yield_units": "whole number > 0",
    "ingredients": "[{ingredient: text, quantity: number > 0, unit: text}]",
    "steps": "[text] (optional, 5 at most)",
    "confidence": "number 0..1",
}


def check_research_schema(payload: Any) -> dict:
    if not isinstance(payload, dict):
        raise ContractSchemaError("The reply must be a JSON object")
    for key in ("dish", "yield_units", "ingredients", "confidence"):
        if key not in payload:
            raise ContractSchemaError(f"The reply is missing '{key}'")
    dish = _optional_text(payload.get("dish"), "dish", 120)
    if not dish:
        raise ContractSchemaError("Field 'dish' is empty")
    try:
        yield_units = int(payload["yield_units"])
    except (TypeError, ValueError) as exc:
        raise ContractSchemaError("Field 'yield_units' must be a whole number") from exc
    if not (0 < yield_units <= 100_000):
        raise ContractSchemaError("Field 'yield_units' must be above 0")
    ingredients = payload["ingredients"]
    if not isinstance(ingredients, list):
        raise ContractSchemaError("Field 'ingredients' must be a list")
    if len(ingredients) > 40:
        raise ContractSchemaError("Too many ingredients in one suggestion")
    clean = []
    for index, item in enumerate(ingredients):
        if not isinstance(item, dict):
            raise ContractSchemaError(f"Ingredient {index + 1} must be an object")
        name = _optional_text(item.get("ingredient"), f"ingredients[{index}].ingredient", 120)
        if not name:
            raise ContractSchemaError(f"Ingredient {index + 1} is missing a name")
        if "price" in item or "cost" in item:
            raise ContractSchemaError("The model must not set prices; code computes them")
        clean.append({
            "ingredient": name,
            "quantity": _number(item.get("quantity"), f"ingredients[{index}].quantity", 0.001, 1_000_000),
            "unit": _optional_text(item.get("unit"), f"ingredients[{index}].unit", 12) or "g",
        })
    steps = payload.get("steps") or []
    if not isinstance(steps, list):
        steps = []
    return {
        "dish": dish,
        "yield_units": yield_units,
        "ingredients": clean,
        "steps": [str(step)[:240] for step in steps[:5]],
        "confidence": _number(payload.get("confidence", 0), "confidence", 0.0, 1.0),
    }


def check_research_rules(payload: dict, raw: str, today: date) -> None:
    problems: list[str] = []
    if len(payload["ingredients"]) < 3:
        problems.append("a recipe needs at least three ingredients")
    blob = json.dumps(payload, ensure_ascii=False)
    if has_currency(blob):
        problems.append("a price appeared in a recipe idea (money is always computed in code)")
    for word in banned_hits(blob):
        problems.append(f"banned word or promise: '{word}'")
    if problems:
        raise ContractRuleError(problems[0], "; ".join(problems[:5]))


RESEARCH_SAFE_REPLY = {
    "dish": "",
    "yield_units": 1,
    "ingredients": [],
    "steps": [],
    "confidence": 0.0,
    "note": "No recipe idea could be prepared safely. Add the recipe by hand.",
}


# ------------------------------------------------------------------ specs

@dataclass
class Contract:
    key: str
    name: str
    schema: dict
    schema_check: Callable[[Any], dict]
    rule_check: Callable[[dict, str, date], None]
    safe_reply: dict

    def check(self, text: str, raw: str, today: date) -> tuple[dict, CheckReport]:
        report = CheckReport()
        try:
            payload = parse_json_reply(text)
        except ContractSyntaxError as exc:
            report.fail("syntax", exc.message)
            raise
        report.syntax = True
        try:
            clean = self.schema_check(payload)
        except ContractSchemaError as exc:
            report.fail("schema", exc.message)
            raise
        report.schema = True
        try:
            self.rule_check(clean, raw, today)
        except ContractRuleError as exc:
            report.fail("business", exc.detail or exc.message)
            raise
        report.business = True
        return clean, report


PARSER_SAFE_REPLY = {
    "intent": "other",
    "customer_name": None,
    "items": [],
    "delivery_date": None,
    "address": None,
    "note": "Maaf, saya tidak dapat membaca tempahan ini dengan pasti. Sila tulis semula: produk, bilangan, tarikh dan alamat.",
    "confidence": 0.0,
}

COSTING_SAFE_REPLY = {
    "recipe_name": "Unread recipe",
    "product_name": None,
    "yield_units": 1,
    "items": [],
    "note": "Maaf, resipi ini tidak dapat dibaca dengan pasti. Sila tulis setiap bahan dengan jumlah dan unit.",
    "confidence": 0.0,
}

PARSER = Contract(
    key="parse",
    name="AI MESSAGE PARSER",
    schema=PARSER_SCHEMA,
    schema_check=check_parser_schema,
    rule_check=check_parser_rules,
    safe_reply=PARSER_SAFE_REPLY,
)

COSTING = Contract(
    key="costing",
    name="Recipe & Ingredient Costing",
    schema=COSTING_SCHEMA,
    schema_check=check_costing_schema,
    rule_check=check_costing_rules,
    safe_reply=COSTING_SAFE_REPLY,
)

RESEARCH = Contract(
    key="research",
    name="Recipe research",
    schema=RESEARCH_SCHEMA,
    schema_check=check_research_schema,
    rule_check=check_research_rules,
    safe_reply=RESEARCH_SAFE_REPLY,
)

CONTRACTS = {"parse": PARSER, "costing": COSTING, "research": RESEARCH}


def input_flags(raw: str, max_chars: int) -> list[str]:
    flags = []
    if len(raw or "") > max_chars:
        flags.append("length")
    if injection_flags(raw):
        flags.append("injection")
    return flags
