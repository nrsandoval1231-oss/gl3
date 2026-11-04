"""Unit, equipment, drive, count and state lexicon shared by extractors and the verifier."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
NUMBER_RE = re.compile(NUMBER)
YEAR_RE = re.compile(r"(?:19|20)\d{2}")

NARRATIVE_UNIT = (
    r"(?:(?i:hp|bhp|horsepower)|kWe?|MW|kVA)(?![\w/]|-hr|\s*/\s*hr)"
)
# Header words that name a rating column, with the canonical unit they imply.
RATING_HEADERS = (
    (re.compile(r"^(?:rated\s+)?horsepower$|^hp$|^bhp$", re.I), "hp"),
    (re.compile(r"^kw$|^kwe$", re.I), "kW"),
    (re.compile(r"^mw$", re.I), "MW"),
    (re.compile(r"^\(?mmbtu/?(?:hr|h)?\)?$|^mmbtuh$|^\(mmbtuh\)$", re.I), "MMBtu/hr"),
)

# Header vocabulary (synonym map): token -> semantic column.
HEADER_SYNONYMS: dict[str, str] = {
    "eu": "id",
    "epn": "id",
    "fin": "id",
    "unit": "id",
    "id": "id",
    "point": "point",
    "description": "description",
    "serial": "serial",
    "number": "serial",
    "#": "serial",
    "const.": "date",
    "construction": "date",
    "manufacture": "date",
    "date": "date",
    "operating": "other",
    "speed": "other",
    "rated": "other",
    "emission": "id",
    "size": "size",
    "heat": "size",
    "input": "size",
    "source": "id",
    "no.": "id",
    "model": "other",
    "make": "other",
}

THRESHOLD_BEFORE = re.compile(
    r"(?:>|<|>=|<=|≥|≤|greater\s+than|less\s+than|more\s+than|fewer\s+than|"
    r"exceed(?:s|ing)?|at\s+least|up\s+to|between|under|over|equal\s+to|below|above|"
    r"in\s+excess\s+of|and\s+less|and\s+greater|from|each\s+of|per|of\s+at\s+least)"
    r"\s*(?:or\s+equal\s+to\s+)?(?:approximately\s+)?[\d,.\s]*$",
    re.I,
)
THRESHOLD_AFTER = re.compile(
    r"^\s*(?:or\s+(?:greater|more|less|fewer)|and\s+(?:greater|above|below|less)|"
    r"(?:to|through|and)\s+\d)",
    re.I,
)

_WORD_NUMBERS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}
COUNT_RE = re.compile(
    r"(?:\b(?P<word>" + "|".join(_WORD_NUMBERS) + r")\s+)?\((?P<digits>\d{1,3})\)", re.I
)


def parse_number(text: str) -> Decimal | None:
    match = NUMBER_RE.search(text)
    if match is None:
        return None
    try:
        return Decimal(match.group(0).replace(",", ""))
    except InvalidOperation:
        return None


def unit_from_text(text: str) -> str | None:
    """Canonical unit named in ``text`` (header word or rating suffix), else None."""
    if re.search(r"mmbtu", text, re.I):
        return "MMBtu/hr"
    if re.search(r"(?i:horsepower|bhp|\bhp)\b", text):
        return "hp"
    if re.search(r"\bkWe?\b", text, re.I):
        return "kW"
    if re.search(r"\bkVA\b", text, re.I):
        return "kVA"
    if re.search(r"\bMW\b", text):
        return "MW"
    return None


def count_from_text(text: str) -> int | None:
    match = COUNT_RE.search(text)
    if match is None:
        return None
    digits = int(match.group("digits"))
    word = match.group("word")
    if word is not None and _WORD_NUMBERS[word.lower()] != digits:
        return None  # "three (4)" is internally inconsistent: refuse.
    return digits if digits > 0 else None


_NEGATED = re.compile(r"(?:\bnon|\bnot|\bno|\bwithout)[\s-]*$", re.I)
_ELECTRIC = re.compile(
    r"electric(?:al(?:ly)?|ally)?[\s-]*(?:motor[\s-]*)?driven"
    r"|electric(?:al)?\s+(?:(?:compressor|pump)\s+)?motors?"
    r"|electrical\s+drivers?|electric\s+inlet\s+compression|motor[\s-]*driven",
    re.I,
)
_GAS_ENGINE = re.compile(r"\bgas(?:[\s-]*fired)?\s+(?:reciprocating\s+)?engines?|\bgas[\s-]*engine", re.I)
_DIESEL = re.compile(r"\bdiesel\b", re.I)
_STEAM = re.compile(r"\bsteam\s+turbines?", re.I)


def drive_from_text(text: str) -> str:
    """Drive stated by ``text``; 'unknown' unless the words explicitly say it."""
    found = {
        label
        for label, pattern in (
            ("electric", _ELECTRIC),
            ("gas_engine", _GAS_ENGINE),
            ("diesel_engine", _DIESEL),
            ("steam", _STEAM),
        )
        for m in pattern.finditer(text)
        if not _NEGATED.search(text[: m.start()])
    }
    return found.pop() if len(found) == 1 else "unknown"


_TYPE_ORDER = (
    ("engine", re.compile(r"\bengines?\b|\bRICE\b", re.I)),
    ("turbine", re.compile(r"\bturbines?\b", re.I)),
    ("generator", re.compile(r"\bgenerators?\b|\bgensets?\b", re.I)),
    ("heater", re.compile(r"\bheaters?\b|\bboilers?\b|\breboilers?\b", re.I)),
    ("compressor", re.compile(r"\bcompressors?\b|\bcompression\b", re.I)),
    ("pump", re.compile(r"\bpumps?\b", re.I)),
    ("flare", re.compile(r"\bflares?\b", re.I)),
    ("motor", re.compile(r"\bmotors?\b", re.I)),
)
_COMPRESSOR_MOTOR = re.compile(r"\b(compressor|pump)\s+motors?\b", re.I)


def type_from_text(text: str) -> str | None:
    """Equipment type named in ``text``; None when nothing (or nothing clear) is named."""
    driven = _COMPRESSOR_MOTOR.search(text)
    if driven is not None and not _TYPE_ORDER[0][1].search(text):
        return driven.group(1).lower()
    for label, pattern in _TYPE_ORDER:
        if pattern.search(text):
            return label
    return None


_EXISTING = re.compile(r"\bexisting\b", re.I)
_PROPOSED = re.compile(r"\b(?:add|adding|install|installing|installation\s+of|propos\w+)\b", re.I)
_NEW = re.compile(r"\bnew\b", re.I)


def state_from_text(text: str) -> str:
    hits = [
        label
        for label, pattern in (("existing", _EXISTING), ("proposed", _PROPOSED), ("new", _NEW))
        if pattern.search(text)
    ]
    return hits[0] if len(hits) == 1 else "unknown"


def state_match(text: str) -> tuple[str, int, int] | None:
    """(state, start, end) of the single state cue in ``text``; None when absent/mixed."""
    found = [
        (label, m.start(), m.end())
        for label, pattern in (("existing", _EXISTING), ("proposed", _PROPOSED), ("new", _NEW))
        for m in pattern.finditer(text)
    ]
    labels = {label for label, _, _ in found}
    return found[0] if len(labels) == 1 else None
