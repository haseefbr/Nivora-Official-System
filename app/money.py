"""Money as Decimal, rounded to 2 places, never float."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

TWO = Decimal("0.01")
SIX = Decimal("0.000001")


def D(value) -> Decimal:
    """Parse anything into an exact Decimal."""
    if isinstance(value, Decimal):
        return value
    if value is None or value == "":
        return Decimal("0")
    try:
        return Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, ValueError, AttributeError) as exc:
        raise ValueError(f"Not a number: {value!r}") from exc


def money(value) -> Decimal:
    """Round to 2 decimal places, half up (the money rule)."""
    return D(value).quantize(TWO, rounding=ROUND_HALF_UP)


def qty(value) -> Decimal:
    return D(value).quantize(SIX, rounding=ROUND_HALF_UP)


def s(value) -> str:
    """Store/serialise money and quantities as an exact string."""
    return str(money(value))


def q(value) -> str:
    return str(qty(value))


def hq(value) -> str:
    """Quantities for humans: 1.000000 -> '1', 2.500000 -> '2.5'."""
    d = qty(value).normalize()
    text = format(d, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def pct(part, whole) -> Decimal:
    whole = D(whole)
    if whole == 0:
        return Decimal("0")
    return (D(part) / whole * 100).quantize(TWO, rounding=ROUND_HALF_UP)
