"""Bounded, verbatim generator schedule facts; never a rental-demand estimate."""

import re
from decimal import Decimal
from typing import Any

VERSION = "generator-excerpts-v4"
MAX_FACTS = 24
MAX_QUOTE = 600
_GENERATOR = re.compile(r"\b(?:generators?|gensets?|engines?)\b", re.I)
_TECHNICAL = re.compile(
    r"\b(?:\d[\d,.]*\s*(?:kW|MW|bhp|hp|hours?)|diesel|natural gas|"
    r"emergency|standby|non-emergency|maintenance|testing|load bank)\b",
    re.I,
)
_REGULATORY = re.compile(
    r"emissions? (?:standards?|limits?|rates?|factors?)|"
    r"maximum engine power|\bsubpart\b|\bCFR\b|"
    r"engines? (?:with|greater|less|below|above)",
    re.I,
)
_RATING = re.compile(r"\b(\d+(?:,\d{3})*(?:\.\d+)?)\s*(kW|MW)\b", re.I)


def extract_generator_facts(pages: list[tuple[int, str]], url: str) -> dict[str, Any]:
    facts: list[dict[str, Any]] = []
    seen: set[str] = set()
    total = 0
    for page, text in pages:
        # Keep decimal points intact. PDF tables remain verbatim contextual
        # excerpts; do not infer count × rating from flattened table columns.
        for sentence in re.split(r"(?<=[.;])\s+(?=[A-Z(\d])", text):
            if not (_GENERATOR.search(sentence) and _TECHNICAL.search(sentence)):
                continue
            match = _GENERATOR.search(sentence)
            assert match is not None
            start = max(0, match.start() - 220)
            quote = sentence[start : start + MAX_QUOTE].strip()
            if quote in seen:
                continue
            seen.add(quote)
            total += 1
            if len(facts) >= MAX_FACTS:
                continue
            quantities = [
                {
                    "source_value": value,
                    "basis": "regulatory context"
                    if _REGULATORY.search(quote)
                    else "unassigned power quantity",
                    "source_unit": unit,
                    "mw": str(
                        Decimal(value.replace(",", ""))
                        / (Decimal(1000) if unit.casefold() == "kw" else Decimal(1))
                    ),
                    "scope": (
                        "Unassigned quantity; not established equipment, campus, "
                        "supply or rental MW"
                    ),
                }
                for value, unit in _RATING.findall(quote)
            ]
            facts.append(
                {
                    "quote": quote,
                    "page": page,
                    "url": url,
                    "label": "Reported equipment context; not rental demand",
                    "power_quantities": quantities,
                }
            )
    return {"facts": facts, "omitted": max(0, total - MAX_FACTS), "version": VERSION}
