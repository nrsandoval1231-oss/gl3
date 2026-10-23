"""Classify air-permit power role from permitted operating hours.

The thresholds live in config/sources/air-permit-hours.v1.json. A record keeps
the matched evidence and the rule id. Conflicting clauses stay unclassified.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

_CONFIG_PATH = (
    Path(__file__).resolve().parents[4] / "config" / "sources" / "air-permit-hours.v1.json"
)
# Number first, then the unit, then the year. "of operation" may sit between them.
# h/yr, hr/yr, hrs/year, hours annually, and hours of operation per year all match.
_HOURS = re.compile(
    r"(?P<hours>\d{1,3}(?:,\d{3})*|\d+)\s*"
    r"(?:hours?|hrs?|h)(?:\s+of\s+operation)?"
    r"\s*(?:(?:/|per)\s*(?:year|yr)|annually)\b",
    re.IGNORECASE,
)
_ONSITE = re.compile(r"on-?site use only", re.IGNORECASE)
# A sentence or clause. A single newline is a PDF line wrap, not a new clause.
_CLAUSE_BOUNDARY = re.compile(r"[.!?;]|\n\s*\n")


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


def _clause(text: str, start: int, end: int) -> str:
    """Return the sentence or clause that contains the hours match."""
    previous = 0
    for boundary in _CLAUSE_BOUNDARY.finditer(text, 0, start):
        previous = boundary.end()
    following = _CLAUSE_BOUNDARY.search(text, end)
    stop = following.start() if following else len(text)
    return text[previous:stop]


def classify_operating_hours(text: str) -> dict[str, Any]:
    """Apply the configured hours rule and keep every matched quote."""
    rule = load_hours_rule()
    classes: list[str] = []
    evidence: list[dict[str, str]] = []
    hours: list[int] = []
    for match in _HOURS.finditer(text):
        value = int(match.group("hours").replace(",", ""))
        hours.append(value)
        onsite = _ONSITE.search(_clause(text, match.start(), match.end()))
        if value <= rule["backup_max_hours_per_year"]:
            kind = "backup"
        elif rule["bridge_min_hours_per_year"] <= value <= rule["bridge_max_hours_per_year"]:
            kind = "bridge_temporary"
        elif value == rule["btm_hours_per_year"] and onsite:
            kind = "btm"
        else:
            kind = ""
        if kind:
            classes.append(kind)
        evidence.append({"clause": kind or "unclassified_hours", "quote": match.group(0)})
        if kind == "btm" and onsite:
            evidence.append({"clause": "onsite_use_only", "quote": onsite.group(0)})
    for clause, pattern in (
        ("portable_or_trailer_mounted", rule["bridge_unit_pattern"]),
        ("expiring_or_temporary_permit", rule["bridge_permit_pattern"]),
    ):
        found = re.search(pattern, text, re.IGNORECASE)
        if found:
            classes.append("bridge_temporary")
            evidence.append({"clause": clause, "quote": found.group(0)})
    unique = list(dict.fromkeys(classes))
    conflict = len(unique) > 1
    return {
        "rule_id": rule["rule_id"],
        "classification": None if conflict or not unique else unique[0],
        "conflict": conflict,
        "hours_per_year": hours,
        "evidence": evidence,
    }
