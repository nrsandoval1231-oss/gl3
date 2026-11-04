"""Post-rating shape for Federal Register compressor-station notices.

These notices state the rating after the equipment, in bullets such as
``Install one new electric motor driven compressor unit with a rating of 18,340 hp``. The
permit-narrative rules read rating-then-noun, so this one explicit shape lives here. Every field
is still checked by the shared exact-span and lexicon recomputation, and the association rule
below keeps the rating inside the equipment's own phrase. The words between the equipment
phrase and "with a rating of" may only be a parenthesised unit id or "at <Name> Station"; any
other equipment or driver noun, "and"/"or", or a replace word there rejects the row, as do
threshold wording after the rating ("or greater", "to 6,000 hp") and re-wheel, uprate, increase,
existing, replace or removal wording in the clause. The shape therefore names one unit; it does
not read uprates, re-wheels, thresholds or removals as new equipment.
"""

from __future__ import annotations

import re
from decimal import Decimal

from gridlens.ingestion.parsers.permit_docs.lexicon import (
    NUMBER,
    RETIRED_RE,
    WORD_NUMBERS,
    count_from_text,
    drive_from_text,
    parse_number,
    type_from_text,
    unit_from_text,
)
from gridlens.ingestion.parsers.permit_docs.models import ExtractedRow, FieldEvidence
from gridlens.ingestion.parsers.permit_docs.narrative import SENTENCE_END
from gridlens.ingestion.parsers.permit_docs.text_layer import CanonicalText
from gridlens.ingestion.parsers.permit_docs.verifier import _recompute_problem, _span_problem

_HYPHEN = "-‐‑‒–—―"
_POST_RATING = re.compile(
    r"(?P<noun>electric(?:ally)?[\s-]+(?:motor[\s-]+)?driven[ \t]+(?:compressors?|pumps?)"
    r"(?:[ \t]+units?)?"
    r"|(?:natural[\s-]+)?gas[\s-]+turbine[\s-]+driven[ \t]+compressors?(?:[ \t]+units?)?"
    r"|(?:reciprocating[\s-]+)?engine[\s-]+driven[ \t]+compressors?(?:[ \t]+units?)?)"
    r"(?P<gap>(?:[ \t]+\([A-Za-z0-9 .-]{1,20}\))?"
    r"(?:[ \t]+at[ \t]+(?:[A-Z][\w.-]*[ \t]+){0,3}(?:\(Compressor\)[ \t]+)?Station)?"
    r"[ \t]+with[ \t]+an?[ \t]+(?:rated[ \t]+)?(?:rating|capacity)[ \t]+of[ \t]+)"
    rf"(?P<num>{NUMBER})[ \t]*[{_HYPHEN}]?[ \t]*(?P<unit>horsepower|hp)(?![\w/])",
    re.I,
)
_WORDS = "|".join(WORD_NUMBERS)
_COUNT_BEFORE = re.compile(
    rf"(?P<count>(?:{_WORDS})[ \t]+\(\d{{1,3}}\)|\(\d{{1,3}}\)|\b(?:{_WORDS})\b)"
    r"[ \t]+(?:(?:new|additional|proposed)[ \t]+)*\Z",
    re.I,
)
_ACTION_CUE = re.compile(r"\b(?:add|adding|install|installing)\b", re.I)
# Words that make the clause something other than one new unit with a stated rating.
_CLAUSE_BLOCK = re.compile(
    r"re-?wheel|uprat|increas|existing|replac|retrofit|abandon|remov|decommission|\bnon-?electric",
    re.I,
)
_THRESHOLD_AFTER_RATING = re.compile(
    r"\s*(?:or|and)\s+(?:greater|more|less|fewer|above|below|higher|lower|up)\b"
    r"|\s*(?:to|through|-|\u2013|\u2014)\s*\d",
    re.I,
)
_STATION_WORD = re.compile(r"\(Compressor\)", re.I)
_GAP_BLOCK = re.compile(r"\b(?:and|or|replac\w*)\b", re.I)
_MAX_GAP_CHARS = 120


def post_rating_rows(canon: CanonicalText) -> list[ExtractedRow]:
    """Candidate rows, not yet trusted: ``post_rating_problem`` must accept each one."""
    rows: list[ExtractedRow] = []
    for page in canon.pages:
        if page.scanned:
            continue
        text, base = page.text, canon.page_starts[page.page - 1]
        for match in _POST_RATING.finditer(text):
            noun_text = match.group("noun")
            rating = parse_number(match.group("num"))
            unit = unit_from_text(match.group("unit"))
            type_value = type_from_text(noun_text)
            if rating is None or rating <= 0 or unit is None or type_value is None:
                continue
            gap_text = _STATION_WORD.sub("", match.group("gap"))
            if (
                _GAP_BLOCK.search(gap_text)
                or type_from_text(gap_text) is not None
                or drive_from_text(gap_text) != "unknown"
            ):
                continue
            after_rating = text[match.end("unit") : match.end("unit") + 200]
            end_cut = SENTENCE_END.search(after_rating + " ")
            tail = after_rating[: end_cut.start()] if end_cut else after_rating
            if _THRESHOLD_AFTER_RATING.match(tail) or _CLAUSE_BLOCK.search(tail):
                continue
            drive = drive_from_text(noun_text)
            noun_start = base + match.start("noun")
            noun_end = noun_start + len(noun_text)
            rating_start = base + match.start("num")
            rating_end = base + match.end("unit")
            rating_quote = text[match.start("num") : match.end("unit")]
            ident = f"N{page.page}-{rating_start}"
            evidence = {
                "id": FieldEvidence("id", ident, rating_quote, rating_start, rating_end, page.page),
                "type": FieldEvidence(
                    "type", type_value, noun_text, noun_start, noun_end, page.page
                ),
                "rating": FieldEvidence(
                    "rating", str(rating), rating_quote, rating_start, rating_end, page.page
                ),
                "unit": FieldEvidence(
                    "unit", unit, rating_quote, rating_start, rating_end, page.page
                ),
            }
            if drive != "unknown":
                evidence["drive"] = FieldEvidence(
                    "drive", drive, noun_text, noun_start, noun_end, page.page
                )
            before = text[max(0, match.start("noun") - 120) : match.start("noun")]
            cuts = [m.end() for m in SENTENCE_END.finditer(before)]
            sentence = before[cuts[-1] :] if cuts else before
            if _CLAUSE_BLOCK.search(sentence) or RETIRED_RE.search(sentence):
                continue
            sentence_at = base + match.start("noun") - len(sentence)
            count = None
            counted = _COUNT_BEFORE.search(sentence)
            if counted is not None:
                quote = counted.group("count")
                count = count_from_text(quote)
                if count is not None:
                    offset = sentence_at + counted.start("count")
                    evidence["count"] = FieldEvidence(
                        "count", str(count), quote, offset, offset + len(quote), page.page
                    )
            state = "unknown"
            cue: re.Match[str] | None = None
            removals = list(RETIRED_RE.finditer(sentence))
            actions = list(_ACTION_CUE.finditer(sentence))
            if removals:
                cue, state = removals[-1], "retired"
            elif actions:
                cue, state = actions[-1], "proposed"
            if cue is not None:
                offset = sentence_at + cue.start()
                evidence["state"] = FieldEvidence(
                    "state", state, cue.group(0), offset, offset + len(cue.group(0)), page.page
                )
            rows.append(
                ExtractedRow(
                    origin="narrative",
                    equipment_id=ident,
                    equipment_type=type_value,
                    drive=drive,
                    rating=Decimal(rating),
                    unit=unit,
                    count=count,
                    state=state,
                    evidence=evidence,
                    group="post-rating",
                )
            )
    return rows


def post_rating_problem(row: ExtractedRow, canon: CanonicalText) -> str | None:
    """Field-level exact-span checks plus the rule that the rating sits in the unit's phrase."""
    declared = {
        "id": row.equipment_id,
        "type": row.equipment_type,
        "rating": str(row.rating),
        "unit": row.unit,
        "count": None if row.count is None else str(row.count),
        "drive": None if row.drive == "unknown" else row.drive,
        "state": None if row.state == "unknown" else row.state,
    }
    for name in ("id", "type", "rating", "unit"):
        if name not in row.evidence:
            return f"missing evidence for {name}"
    for name, value in declared.items():
        if (value is None) != (name not in row.evidence):
            return f"{name} evidence and value disagree"
    for name, ev in row.evidence.items():
        if ev.field != name or ev.value != declared[name]:
            return f"{name} evidence disagrees with row value"
        problem = _span_problem(ev, canon) or _recompute_problem(ev, row)
        if problem is not None:
            return f"{name}: {problem}"
    type_ev, rating = row.evidence["type"], row.evidence["rating"]
    drive_ev = row.evidence.get("drive")
    if type_ev.page != rating.page or type_ev.end > rating.start:
        return "equipment phrase is not before the rating"
    if drive_ev is not None and (drive_ev.start, drive_ev.end) != (type_ev.start, type_ev.end):
        return "drive quote is not the equipment phrase"
    gap = canon.text[type_ev.end : rating.start]
    if "\n" in gap or SENTENCE_END.search(gap + " ") or len(gap) > _MAX_GAP_CHARS:
        return "rating is not in the equipment phrase"
    gap = _STATION_WORD.sub("", gap)
    if (
        _GAP_BLOCK.search(gap)
        or type_from_text(gap) is not None
        or drive_from_text(gap) != "unknown"
    ):
        return "another unit or driver sits between the equipment phrase and the rating"
    return None
