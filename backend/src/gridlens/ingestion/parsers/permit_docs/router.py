"""Deterministic page router: table | narrative | scan | irrelevant."""

from __future__ import annotations

import re

from gridlens.ingestion.parsers.permit_docs.lexicon import NARRATIVE_UNIT, NUMBER, RATING_HEADERS
from gridlens.ingestion.parsers.permit_docs.models import Route
from gridlens.ingestion.parsers.permit_docs.text_layer import SCAN_CHAR_THRESHOLD

_ID_CUE = re.compile(
    r"\b(?:EU|EPN|FIN|Unit\s+ID|Equipment\s+ID|Emission\s+Unit|Source\s+ID)\b"
    r"|\bEUG[- ]?\d+|\bTable\s+2-A\b",
    re.I,
)
_HEADER_CONTEXT = re.compile(r"description|serial|const|date|rated|unit|point", re.I)
# Control-technology database listings describe OTHER facilities, not this permit's equipment.
_REFERENCE_DB = re.compile(r"RBLC|RACT/BACT/LAER|Clearinghouse")
_CAPACITY_PAIR = re.compile(
    rf"(?<![\w.,]){NUMBER}\s*(HP|hp|kW|KW|MW|MMBtu/hr)\s+{NUMBER}\s*(HP|hp|kW|KW|MW|MMBtu/hr)(?![A-Za-z])"
)
_EQUIPMENT_NOUN = r"(?:compressor|engine|turbine|generator|motor|pump|heater|RICE|driver)s?"
_NARRATIVE_CUE = re.compile(
    rf"{NARRATIVE_UNIT}[\s,-]*(?:[\w.\-]+\s+){{0,4}}?{_EQUIPMENT_NOUN}\b",
    re.I,
)


def header_unit(token: str) -> str | None:
    cleaned = token.strip()
    for pattern, unit in RATING_HEADERS:
        if pattern.match(cleaned):
            return unit
    return None


def has_rating_header(text: str) -> bool:
    for line in text.splitlines():
        tokens = line.split()
        if len(tokens) < 2 or not any(header_unit(t) for t in tokens):
            continue
        if _ID_CUE.search(line) or (len(tokens) <= 8 and _HEADER_CONTEXT.search(line)):
            return True
    return False


def route_page(text: str, chars: int | None = None) -> Route:
    """Route one page. Scanned pages are 'scan' (needs OCR) and never yield rows."""
    measured = chars if chars is not None else sum(1 for c in text if not c.isspace())
    if measured < SCAN_CHAR_THRESHOLD:
        return "scan"
    if _REFERENCE_DB.search(text):
        return "irrelevant"
    if has_rating_header(text) or (
        ("Table 2-A" in text or "Rated Capacity" in text) and _CAPACITY_PAIR.search(text)
    ):
        return "table"
    if _NARRATIVE_CUE.search(text):
        return "narrative"
    return "irrelevant"
