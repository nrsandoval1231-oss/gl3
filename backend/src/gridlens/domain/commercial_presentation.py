"""Presentation rules for the inclusive minimum commercial project size."""

from __future__ import annotations

import re
from decimal import Decimal

_POWER = re.compile(
    r"(?P<low>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?P<unit>kW|MW)?"
    r"(?:\s*(?:-|–|to)\s*"
    r"(?P<high>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*"
    r"(?P<highunit>kW|MW))?",
    re.IGNORECASE,
)
_OUT_OF_SCOPE = re.compile(
    r"\b(?:campus|nameplate|operating load|eventual|facility total|total campus)\b",
    re.IGNORECASE,
)
_ACTIVITY_SCOPE = re.compile(
    r"\b(?:activity|load|power need|requirement|generator replacement|replacement work)\b",
    re.IGNORECASE,
)
_UNCERTAIN_QUANTITY = re.compile(
    r"\b(?:over|more than|at least|greater than|above|up to|under|less than|"
    r"approximately|approx\.?|about|around|each|per unit)\b|[<>~]|\b\d+\s*[x×]\s*\d",
    re.IGNORECASE,
)
_FLOOR_MW = Decimal("0.3")


def canonical_mw_claim(value: object) -> object:
    """Compare exact single power quantities without collapsing bounds or estimates."""
    if not isinstance(value, str):
        return value
    original = value.strip()
    spelled_unit = re.sub(r"\bmegawatts?\b", "MW", original, flags=re.IGNORECASE)
    match = _POWER.fullmatch(spelled_unit)
    if match is None or match["unit"] is None or match["high"] is not None:
        return original
    amount = Decimal(match["low"].replace(",", ""))
    if match["unit"].casefold() == "kw":
        amount *= Decimal("0.001")
    return f"{format(amount.normalize(), 'f')} MW"


def commercial_size_status(
    required_mw: str | None,
    activity: str,
    supported_action: str | None,
    reported_power_facts: list[str],
    *,
    remaining_gap: dict | None = None,
) -> str:
    """Return below_floor, at_or_above_floor, or unknown from in-scope evidence only."""
    if remaining_gap is not None:
        # Caller supplies only the replayed effective Lead gap. Gross demand stays
        # visible, but the open commercial opportunity is the remaining interval.
        try:
            low = Decimal(str(remaining_gap["remaining_mw_min"]))
            high = Decimal(str(remaining_gap["remaining_mw_max"]))
            if not low.is_finite() or not high.is_finite() or low < 0 or high < low:
                return "unknown"
        except (KeyError, TypeError, ValueError, ArithmeticError):
            return "unknown"
        if high < _FLOOR_MW:
            return "below_floor"
        return "at_or_above_floor" if low >= _FLOOR_MW else "unknown"
    if required_mw is not None:
        # required_mw is already an admitted activity quantity. Preserve its units
        # and interval; qualifiers and arbitrary prose never become exact loads.
        match = _POWER.fullmatch(required_mw.strip())
        if match is None:
            return "unknown"
        low_unit = (match["unit"] or match["highunit"] or "mw").casefold()
        high_unit = (match["highunit"] or match["unit"] or "mw").casefold()
        low = Decimal(match["low"].replace(",", "")) * (Decimal("0.001") if low_unit == "kw" else 1)
        high = Decimal((match["high"] or match["low"]).replace(",", "")) * (
            Decimal("0.001") if high_unit == "kw" else 1
        )
        if high < low:
            return "unknown"
        if high < _FLOOR_MW:
            return "below_floor"
        return "at_or_above_floor" if low >= _FLOOR_MW else "unknown"

    facts = list(reported_power_facts)
    if supported_action and re.search(r"\bgenerator\s+replacement\b", supported_action, re.I):
        facts.append(supported_action)
    limits: list[tuple[Decimal, Decimal]] = []
    for fact in facts:
        if _OUT_OF_SCOPE.search(fact):
            continue
        if _UNCERTAIN_QUANTITY.search(fact):
            return "unknown"
        if not (_ACTIVITY_SCOPE.search(fact) or re.search(r"\bgenerator\b", fact, re.I)):
            continue
        for match in _POWER.finditer(fact):
            low_unit = (match["unit"] or match["highunit"] or "").casefold()
            high_unit = (match["highunit"] or match["unit"] or "").casefold()
            if not low_unit:
                continue
            low_multiplier = Decimal("0.001") if low_unit == "kw" else Decimal(1)
            high_multiplier = Decimal("0.001") if high_unit == "kw" else Decimal(1)
            low = Decimal(match["low"].replace(",", "")) * low_multiplier
            high_text = (match["high"] or match["low"]).replace(",", "")
            high = Decimal(high_text) * high_multiplier
            limits.append((low, high))
    if not limits:
        return "unknown"
    if all(high < _FLOOR_MW for _, high in limits):
        return "below_floor"
    if all(low >= _FLOOR_MW for low, _ in limits):
        return "at_or_above_floor"
    return "unknown"
