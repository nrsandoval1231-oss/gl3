"""Classify air-permit power role from permitted operating hours.

The thresholds live in config/sources/air-permit-hours.v1.json. A record keeps
the matched evidence and the rule id. Conflicting clauses stay unclassified.

Only a TCEQ New Source Review plain-language summary carries summary text into
this rule. Construction NOI and electric-generating-unit rows classify the
fields on the row itself and do not fetch a summary.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

_CONFIG_PATH = (
    Path(__file__).resolve().parents[4] / "config" / "sources" / "air-permit-hours.v1.json"
)
# Number first, then an optional decimal, then the unit, then the year.
# The left guard stops "1.5 hours" from being read as 5. "of operation" may
# sit between the unit and the year.
_HOURS = re.compile(
    r"(?<![\d.,])"
    r"(?P<hours>\d{1,3}(?:,\d{3})*|\d+)"
    r"(?P<fraction>\.\d+)?"
    r"\s*(?:hours?|hrs?|h)(?:\s+of\s+operation)?"
    r"\s*(?:(?:/|per)\s*(?:year|yr)|annually)\b",
    re.IGNORECASE,
)
_ONSITE = re.compile(r"on-?site use only", re.IGNORECASE)
_POWER_UNIT = re.compile(r"\b(?:generators?|turbines?|engines?)\b", re.IGNORECASE)
_BLANK_LINE = re.compile(r"\n\s*\n")
# A period after one of these words is an abbreviation, not a sentence end.
_ABBREVIATIONS = frozenset(
    {"approx", "co", "corp", "dr", "etc", "fig", "inc", "ltd", "mr", "mrs", "ms", "no", "st", "vs"}
)


@lru_cache(maxsize=1)
def load_hours_rule() -> dict[str, Any]:
    rule = json.loads(_CONFIG_PATH.read_text())
    required = {
        "rule_id",
        "backup_max_hours_per_year",
        "bridge_min_hours_per_year",
        "bridge_max_hours_per_year",
        "btm_hours_per_year",
        "btm_phrase",
        "bridge_unit_pattern",
        "bridge_permit_pattern",
    }
    if set(rule) != required or rule["btm_phrase"].casefold() != "onsite use only":
        raise ValueError("Air-permit hours rule config is not the reviewed rule")
    if not (
        0
        <= rule["backup_max_hours_per_year"]
        < rule["bridge_min_hours_per_year"]
        <= rule["bridge_max_hours_per_year"]
        < rule["btm_hours_per_year"]
    ):
        raise ValueError("Air-permit hours thresholds are out of order")
    re.compile(rule["bridge_unit_pattern"])
    re.compile(rule["bridge_permit_pattern"])
    return rule


def _sentence_period(text: str, index: int) -> bool:
    """True when the period at index ends a sentence."""
    previous = text[index - 1] if index else ""
    following = text[index + 1] if index + 1 < len(text) else ""
    if previous.isdigit() and following.isdigit():
        return False
    # "U.S." and "e.g." are single-letter abbreviations.
    if previous.isalpha() and (index < 2 or not text[index - 2].isalpha()):
        return False
    letters: list[str] = []
    cursor = index - 1
    while cursor >= 0 and text[cursor].isalpha():
        letters.append(text[cursor])
        cursor -= 1
    return "".join(reversed(letters)).casefold() not in _ABBREVIATIONS


def _boundaries(text: str):
    """Sentence ends and blank lines. A semicolon or a line wrap is not an end."""
    index = 0
    while index < len(text):
        if text[index] in "!?" or (text[index] == "." and _sentence_period(text, index)):
            yield index, index + 1
            index += 1
            continue
        blank = _BLANK_LINE.match(text, index)
        if blank:
            yield blank.start(), blank.end()
            index = blank.end()
            continue
        index += 1


def _clause(text: str, start: int, end: int) -> str:
    """Return the sentence that contains the match. A semicolon stays inside it."""
    previous = 0
    stop = len(text)
    for begin, finish in _boundaries(text):
        if finish <= start:
            previous = finish
        elif begin >= end:
            stop = begin
            break
    return text[previous:stop]


def _hours_value(match: re.Match[str]) -> Decimal:
    return Decimal(match.group("hours").replace(",", "") + (match.group("fraction") or ""))


def classify_operating_hours(text: str) -> dict[str, Any]:
    """Apply the configured hours rule and keep every matched quote."""
    rule = load_hours_rule()
    classes: list[str] = []
    evidence: list[dict[str, str]] = []
    hours: list[int | float] = []
    backup_max = Decimal(rule["backup_max_hours_per_year"])
    bridge_min = Decimal(rule["bridge_min_hours_per_year"])
    bridge_max = Decimal(rule["bridge_max_hours_per_year"])
    btm_hours = Decimal(rule["btm_hours_per_year"])
    for match in _HOURS.finditer(text):
        value = _hours_value(match)
        hours.append(int(value) if value == value.to_integral_value() else float(value))
        onsite = _ONSITE.search(_clause(text, match.start(), match.end()))
        if value <= backup_max:
            kind = "backup"
        elif bridge_min <= value <= bridge_max:
            kind = "bridge_temporary"
        elif value == btm_hours and onsite:
            kind = "btm"
        else:
            kind = ""
        if kind:
            classes.append(kind)
        evidence.append({"clause": kind or "unclassified_hours", "quote": match.group(0)})
        if kind == "btm" and onsite:
            evidence.append({"clause": "onsite_use_only", "quote": onsite.group(0)})
    for match in re.finditer(rule["bridge_unit_pattern"], text, re.IGNORECASE):
        if _POWER_UNIT.search(_clause(text, match.start(), match.end())):
            classes.append("bridge_temporary")
            evidence.append({"clause": "portable_or_trailer_mounted", "quote": match.group(0)})
            break
    permit = re.search(rule["bridge_permit_pattern"], text, re.IGNORECASE)
    if permit:
        classes.append("bridge_temporary")
        evidence.append({"clause": "expiring_or_temporary_permit", "quote": permit.group(0)})
    unique = list(dict.fromkeys(classes))
    conflict = len(unique) > 1
    return {
        "rule_id": rule["rule_id"],
        "classification": None if conflict or not unique else unique[0],
        "conflict": conflict,
        "hours_per_year": hours,
        "evidence": evidence,
    }
