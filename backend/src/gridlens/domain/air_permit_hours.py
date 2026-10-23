"""Classify air-permit power role from permitted operating hours.

The thresholds live in config/sources/air-permit-hours.v1.json. A record keeps
the matched evidence and the rule id. Conflicting clauses stay unclassified.

A single annual figure is backup at 500 hours per year or less, bridge/temporary
from 2,000 through 6,000, and behind-the-meter only at exactly 8,760 when the
same clause says "onsite use only". The clause is the sentence. A semicolon does
not end it, and neither does an abbreviation period such as "U.S."

A hyphen, en dash, em dash, or the word "to" between two of those figures is one
range. Both endpoints are kept, in the order written, and a decimal stays on the
endpoint it follows, so "1.5-2.5 hours per year" is 1.5 and 2.5 rather than 5 or
2.5 alone. The range is not replaced by its right-hand number. It takes a class
only when both endpoints fall in the same band, using the same onsite test. A
range that crosses bands, or that has an endpoint in no band, stays unclassified.
"12-500 hours per year" is backup because both ends are at or under 500.
"12-2,000 hours per year" crosses bands and stays unclassified. "2,000-6,000
hours per year" is bridge/temporary. "up to 500 hours per year" is a single cap
of 500, not a range.

Portable or trailer-mounted wording, and an expiring or temporary permit, are
bridge/temporary only when that same clause names power generation: a generator,
genset, turbine, or electric or power generation. The word engine, including an
engine-driven crusher or pump, is not that context.

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
# Number, optional decimal, optional range, then the unit and the year.
# The left guard stops "1.5 hours" from being read as 5. A range consumes both
# endpoints so the right-hand number is not classified by itself. "of operation"
# may sit between the unit and the year.
_NUMBER = r"(?:\d{1,3}(?:,\d{3})*|\d+)"
_HOURS = re.compile(
    r"(?<![\d.,])"
    rf"(?P<hours>{_NUMBER})"
    r"(?P<fraction>\.\d+)?"
    r"(?:"
    r"(?P<range_sep>\s*(?:-|\u2010|\u2011|\u2013|\u2014|\u2212)\s*|\s+to\s+)"
    rf"(?P<high>{_NUMBER})"
    r"(?P<high_fraction>\.\d+)?"
    r")?"
    r"\s*(?:hours?|hrs?|h)(?:\s+of\s+operation)?"
    r"\s*(?:(?:/|per)\s*(?:year|yr)|annually)\b",
    re.IGNORECASE,
)
_ONSITE = re.compile(r"on-?site use only", re.IGNORECASE)
_BLANK_LINE = re.compile(r"\n\s*\n")
# A period after one of these words is an abbreviation, not a sentence end.
_ABBREVIATIONS = frozenset(
    {"approx", "co", "corp", "dr", "etc", "fig", "inc", "ltd", "mr", "mrs", "ms", "no", "st", "vs"}
)
_POWER_SAMPLES = (
    "generator",
    "genset",
    "gen-set",
    "turbine",
    "electric generation",
    "power generation",
)
_NOT_POWER = ("engine", "engines", "engine-driven crusher", "engine-driven pump")


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
        "power_generation_pattern",
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
    power = re.compile(rule["power_generation_pattern"], re.IGNORECASE)
    if any(power.search(sample) is None for sample in _POWER_SAMPLES) or any(
        power.search(sample) for sample in _NOT_POWER
    ):
        raise ValueError("Air-permit power-generation pattern does not match the reviewed context")
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


def _decimal(whole: str, fraction: str | None) -> Decimal:
    return Decimal(whole.replace(",", "") + (fraction or ""))


def _public_hours(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


def _band(
    value: Decimal,
    *,
    onsite: bool,
    backup_max: Decimal,
    bridge_min: Decimal,
    bridge_max: Decimal,
    btm_hours: Decimal,
) -> str:
    if value <= backup_max:
        return "backup"
    if bridge_min <= value <= bridge_max:
        return "bridge_temporary"
    if value == btm_hours and onsite:
        return "btm"
    return ""


def _power_generation(rule: dict[str, Any], clause: str) -> bool:
    return re.search(rule["power_generation_pattern"], clause, re.IGNORECASE) is not None


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
        value = _decimal(match.group("hours"), match.group("fraction"))
        high_whole = match.group("high")
        onsite = _ONSITE.search(_clause(text, match.start(), match.end()))
        hours.append(_public_hours(value))
        if high_whole is None:
            kind = _band(
                value,
                onsite=bool(onsite),
                backup_max=backup_max,
                bridge_min=bridge_min,
                bridge_max=bridge_max,
                btm_hours=btm_hours,
            )
        else:
            high = _decimal(high_whole, match.group("high_fraction"))
            hours.append(_public_hours(high))
            low_band = _band(
                value,
                onsite=bool(onsite),
                backup_max=backup_max,
                bridge_min=bridge_min,
                bridge_max=bridge_max,
                btm_hours=btm_hours,
            )
            high_band = _band(
                high,
                onsite=bool(onsite),
                backup_max=backup_max,
                bridge_min=bridge_min,
                bridge_max=bridge_max,
                btm_hours=btm_hours,
            )
            kind = low_band if low_band and low_band == high_band else ""
        if kind:
            classes.append(kind)
        evidence.append({"clause": kind or "unclassified_hours", "quote": match.group(0)})
        if kind == "btm" and onsite:
            evidence.append({"clause": "onsite_use_only", "quote": onsite.group(0)})
    for match in re.finditer(rule["bridge_unit_pattern"], text, re.IGNORECASE):
        if _power_generation(rule, _clause(text, match.start(), match.end())):
            classes.append("bridge_temporary")
            evidence.append({"clause": "portable_or_trailer_mounted", "quote": match.group(0)})
            break
    for match in re.finditer(rule["bridge_permit_pattern"], text, re.IGNORECASE):
        if _power_generation(rule, _clause(text, match.start(), match.end())):
            classes.append("bridge_temporary")
            evidence.append({"clause": "expiring_or_temporary_permit", "quote": match.group(0)})
            break
    unique = list(dict.fromkeys(classes))
    conflict = len(unique) > 1
    return {
        "rule_id": rule["rule_id"],
        "classification": None if conflict or not unique else unique[0],
        "conflict": conflict,
        "hours_per_year": hours,
        "evidence": evidence,
    }
