"""Driver-phrase rules for equipment named in permit prose.

A rating is attached to equipment only when the permit's own words put the rating and an
equipment noun in one phrase (`(3) 2,500-hp Siemens electric compressor motors`). Electric
drive requires explicit electric-driver wording; nothing is inferred from a table rating.
A motor rating and a driven-compressor rating are separate rows and are never merged.
"""

from __future__ import annotations

import re
from decimal import Decimal

from gridlens.ingestion.parsers.permit_docs.lexicon import (
    COUNT_RE,
    NARRATIVE_UNIT,
    NUMBER,
    THRESHOLD_AFTER,
    THRESHOLD_BEFORE,
    WORD_NUMBERS,
    count_from_text,
    drive_from_text,
    parse_number,
    type_from_text,
    unit_from_text,
)
from gridlens.ingestion.parsers.permit_docs.models import ExtractedRow, FieldEvidence, Route
from gridlens.ingestion.parsers.permit_docs.text_layer import CanonicalText

_RATING = re.compile(rf"(?<![\w./,\-])(?P<num>{NUMBER})\s*-?\s*(?P<unit>{NARRATIVE_UNIT})")
_STOP = (
    r"(?:is|are|was|were|for|to|of|the|and|or|with|that|which|will|be|has|have|from|by|in|on|at|as"
    r"|each|total|combined|rated|capacity)"
)
_MID = rf"(?:(?!{_STOP}\b)[A-Za-z0-9][\w./\-]*\s+){{0,4}}?"
_NOUNS = (
    # (pattern, type group or fixed type) in priority order
    (r"electric(?:ally)?[\s-]+(?:motor[\s-]+)?driven\s+(?P<t0>compressors?|pumps?)", "t0"),
    (r"electric(?:al)?\s+(?P<t1>(?:compressor|pump)\s+motors?)", "t1"),
    (r"electric(?:al)?\s+motors?", "motor"),
    (
        r"(?:(?:natural\s+)?gas[\s-]*fired\s+|diesel\s+|reciprocating\s+|four[\s-]stroke\s+|"
        r"lean[\s-]burn\s+)*(?:internal\s+combustion\s+)?engines?\b|RICE\b",
        "engine",
    ),
    (r"(?:gas\s+|steam\s+)?turbines?", "turbine"),
    (r"(?:emergency\s+)?generators?", "generator"),
    (r"(?:heaters?|boilers?)", "heater"),
    (
        r"compressors?(?!\s+(?:engines?|turbines?|motors?|drivers?|skids?)|\s*\n|\s+\d)",
        "compressor",
    ),
    (r"pumps?(?!\s+(?:engines?|turbines?|motors?|drivers?|skids?)|\s*\n|\s+\d)", "pump"),
)
_NOUN_RE = re.compile(
    rf"^[\s,]*{_MID}(?P<noun>"
    + "|".join(f"(?P<n{i}>{pattern})" for i, (pattern, _) in enumerate(_NOUNS))
    + r")",
    re.I,
)
_RANGE_BEFORE = re.compile(r"\d\s*(?:to|and|through|-|–)\s*$", re.I)
_COUNT_BEFORE = re.compile(
    r"(?:"
    + COUNT_RE.pattern
    + r"|(?<![\w-])(?P<bare>"
    + "|".join(WORD_NUMBERS)
    + r"))\s*(?:approximately\s+)?$",
    re.I,
)
_ASSOCIATED = re.compile(r"associated\s+(?:[a-z]+\s+){0,2}(?P<name>[A-Z][A-Za-z0-9-]+)")
_SENTENCE_END = re.compile(r"[.;:]\s|\n\n")
_STATE_CUE = re.compile(r"(?P<existing>\bexisting\b)|(?P<proposed>\b(?:add|install)\b)", re.I)
_STATE_WINDOW = 70
_NEGATION_BEFORE = re.compile(r"(?:\bnon|\bnot|\bno|\bwithout)[\s-]*$", re.I)


def extract_narrative(
    canon: CanonicalText, routes: dict[int, Route]
) -> tuple[list[ExtractedRow], list[str]]:
    rows: list[ExtractedRow] = []
    issues: list[str] = []
    for page in canon.pages:
        if routes.get(page.page) not in ("table", "narrative"):
            continue
        text = page.text
        base = canon.page_starts[page.page - 1]
        for match in _RATING.finditer(text):
            row = _row_for(match, text, base, page.page, issues)
            if row is not None:
                rows.append(row)
    return rows, issues


def _row_for(
    match: re.Match[str], text: str, base: int, page: int, issues: list[str]
) -> ExtractedRow | None:
    start, end = match.start(), match.end()
    before = text[max(0, start - 200) : start]
    sentence_cut = [m.end() for m in _SENTENCE_END.finditer(before)]
    sentence_before = before[sentence_cut[-1] :] if sentence_cut else before
    after_raw = text[end : end + 140]
    cut = _SENTENCE_END.search(after_raw)
    after = after_raw[: cut.start()] if cut else after_raw
    if THRESHOLD_BEFORE.search(before[-40:]) or _RANGE_BEFORE.search(before[-12:]):
        return None
    if THRESHOLD_AFTER.match(after_raw):
        return None
    noun = _NOUN_RE.match(after)
    if noun is None:
        return None
    kind_index = next(i for i in range(len(_NOUNS)) if noun.group(f"n{i}") is not None)
    _, fixed = _NOUNS[kind_index]
    noun_start = end + noun.start("noun")
    noun_end = end + noun.end("noun")
    noun_text = after[noun.start("noun") : noun.end("noun")]
    if fixed in ("t0", "t1"):
        type_text = noun.group(fixed)
        type_start = end + noun.start(fixed)
    else:
        type_text = noun_text
        type_start = noun_start
    type_value = type_from_text(type_text)
    if type_value is None:
        return None
    unit = unit_from_text(match.group("unit"))
    rating = parse_number(match.group("num"))
    if unit is None or rating is None or rating <= 0:
        return None
    rating_quote = text[start:end]
    rating_start = base + start
    drive = drive_from_text(noun_text)
    if _NEGATION_BEFORE.search(text[max(0, noun_start - 8) : noun_start]):
        drive = "unknown"
    evidence = {
        "id": FieldEvidence(
            "id", f"N{page}-{rating_start}", rating_quote, rating_start, base + end, page
        ),
        "type": FieldEvidence(
            "type",
            type_value,
            type_text,
            base + type_start,
            base + type_start + len(type_text),
            page,
        ),
        "rating": FieldEvidence(
            "rating", str(rating), rating_quote, rating_start, base + end, page
        ),
        "unit": FieldEvidence("unit", unit, rating_quote, rating_start, base + end, page),
    }
    if drive != "unknown":
        evidence["drive"] = FieldEvidence(
            "drive", drive, noun_text, base + noun_start, base + noun_end, page
        )
    count = None
    count_match = _COUNT_BEFORE.search(before)
    if count_match is not None:
        count = count_from_text(count_match.group(0))
        if count is not None:
            quote = count_match.group(0).strip()
            quote = re.sub(r"\s*approximately$", "", quote, flags=re.I).strip()
            offset = base + max(0, start - 200) + count_match.start()
            evidence["count"] = FieldEvidence(
                "count", str(count), quote, offset, offset + len(quote), page
            )
    state = "unknown"
    window = sentence_before[-_STATE_WINDOW:]
    cues = list(_STATE_CUE.finditer(window))
    if cues and len({m.lastgroup for m in cues}) == 1:
        cue = cues[-1]
        state = "existing" if cue.lastgroup == "existing" else "proposed"
        offset = base + start - len(window) + cue.start()
        evidence["state"] = FieldEvidence(
            "state", state, cue.group(0), offset, offset + len(cue.group(0)), page
        )
    hint = _ASSOCIATED.search(after_raw[noun.end("noun") :] + " ")
    return ExtractedRow(
        origin="narrative",
        equipment_id=f"N{page}-{rating_start}",
        equipment_type=type_value,
        drive=drive,
        rating=Decimal(rating),
        unit=unit,
        count=count,
        state=state,
        evidence=evidence,
        link_hint=hint.group("name") if hint else "",
    )
