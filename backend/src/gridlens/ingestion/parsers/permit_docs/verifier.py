"""Exact-span verifier: every field must be recomputable from its verbatim quote.

For each field of each candidate row the verifier checks that the quote sits at the stated
character span on the stated page of the canonical text (whitespace runs may differ, nothing
else), then recomputes the value from the quote alone with the shared lexicon and requires
it to equal the extracted value. A row with any failing field is rejected as a whole and the
rejection is counted and reported. There is no fuzzy matching.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from gridlens.ingestion.parsers.permit_docs.lexicon import (
    count_from_text,
    drive_from_text,
    parse_number,
    state_from_text,
    type_from_text,
    unit_from_text,
)
from gridlens.ingestion.parsers.permit_docs.models import (
    OPTIONAL_FIELDS,
    REQUIRED_FIELDS,
    ExtractedRow,
    FieldEvidence,
)
from gridlens.ingestion.parsers.permit_docs.narrative import SENTENCE_END, count_is_countable
from gridlens.ingestion.parsers.permit_docs.text_layer import CanonicalText

VERIFIER = "exact-span-v1"
_SYNTHETIC_ID = re.compile(r"N(\d+)-(\d+)\Z")
_ID_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/\-]{0,39}\Z")
_GROUP_TITLE_AT_LINE_START = re.compile(r"^[ \t]*EUG[- ]?\d+", re.I | re.M)


@dataclass(slots=True)
class VerificationReport:
    verified: list[ExtractedRow] = field(default_factory=list)
    rejected: list[tuple[ExtractedRow, str]] = field(default_factory=list)


def _ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _span_problem(ev: FieldEvidence, canon: CanonicalText) -> str | None:
    if not ev.quote.strip():
        return "empty quote"
    if not 1 <= ev.page <= len(canon.pages):
        return "page out of range"
    lo, hi = canon.page_span(ev.page)
    if not (lo <= ev.start < ev.end <= hi):
        return "span outside stated page"
    if _ws(canon.text[ev.start : ev.end]) != _ws(ev.quote):
        return "quote does not match canonical text at span"
    return None


def _recompute_problem(ev: FieldEvidence, row: ExtractedRow) -> str | None:
    quote = ev.quote
    if ev.field == "id":
        synthetic = _SYNTHETIC_ID.fullmatch(ev.value)
        if synthetic is not None:
            ok = (
                row.origin == "narrative"
                and int(synthetic.group(1)) == ev.page
                and int(synthetic.group(2)) == ev.start
            )
            return None if ok else "synthetic id does not match its span"
        ok = quote.strip() == ev.value and _ID_TOKEN.fullmatch(ev.value) is not None
        return None if ok else "id not equal to quoted token"
    if ev.field == "type":
        return None if type_from_text(quote) == ev.value else "type not stated by quote"
    if ev.field == "rating":
        try:
            expected = Decimal(ev.value)
        except InvalidOperation:
            return "rating value is not a decimal"
        return None if parse_number(quote) == expected else "rating differs from quote"
    if ev.field == "unit":
        return None if unit_from_text(quote) == ev.value else "unit not stated by quote"
    if ev.field == "count":
        return None if str(count_from_text(quote)) == ev.value else "count differs from quote"
    if ev.field == "drive":
        return None if drive_from_text(quote) == ev.value else "drive not stated by quote"
    if ev.field == "state":
        return None if state_from_text(quote) == ev.value else "state not stated by quote"
    return f"unknown field {ev.field!r}"


def _line_span(text: str, offset: int) -> tuple[int, int]:
    lo = text.rfind("\n", 0, offset) + 1
    hi = text.find("\n", offset)
    return lo, len(text) if hi < 0 else hi


def _tokens(line: str) -> set[str]:
    return {t.strip("(),;:") for t in line.split()}


def _inside(ev: FieldEvidence, span: tuple[int, int]) -> bool:
    return span[0] <= ev.start and ev.end <= span[1]


def _narrative_association(row: ExtractedRow, canon: CanonicalText) -> str | None:
    """Type and drive must sit in the rating's own phrase: after it, same line, same sentence."""
    text = canon.text
    rating = row.evidence["rating"]
    for name in ("type", "drive"):
        ev = row.evidence.get(name)
        if ev is None:
            continue
        if ev.page != rating.page or ev.start < rating.end:
            return f"{name} quote is not after the rating"
        gap = text[rating.end : ev.start]
        if "\n" in gap or SENTENCE_END.search(gap + " "):
            return f"{name} quote is not in the rating's phrase"
    count = row.evidence.get("count")
    if count is not None:
        gap = text[count.end : rating.start]
        if gap.strip(" \t") or count.page != rating.page:
            return "count quote does not abut the rating"
        sentence = text[max(0, count.start - 200) : count.start]
        cut = [m.end() for m in SENTENCE_END.finditer(sentence)]
        sentence = sentence[cut[-1] :] if cut else sentence
        if not count_is_countable(sentence + count.quote, len(sentence), count.quote):
            return "bare (n) count is a list number, not a count"
    state = row.evidence.get("state")
    if state is not None:
        if state.page != rating.page or state.end > rating.start:
            return "state cue is not before the rating"
        if SENTENCE_END.search(text[state.end : rating.start] + " "):
            return "state cue is in another sentence"
    return None


def _table_association(
    row: ExtractedRow, canon: CanonicalText, capacity_ids: set[str]
) -> str | None:
    """Type, drive and state must come from the row's own line, its own group title, or (for
    capacity tables) an adjacent line that does not belong to another capacity row."""
    text = canon.text
    line = _line_span(text, row.evidence["id"].start)
    for name in ("rating",):
        if not _inside(row.evidence[name], line):
            return f"{name} quote is not on the row line"
    if row.group == "capacity-table" and not _inside(row.evidence["unit"], line):
        return "unit quote is not on the row line"
    others = capacity_ids - {row.equipment_id}
    for name in ("type", "drive", "state"):
        ev = row.evidence.get(name)
        if ev is None or _inside(ev, line):
            continue
        if row.group == "capacity-table" and name != "state":
            neighbors = [
                _line_span(text, line[0] - 1) if line[0] > 0 else None,
                _line_span(text, line[1] + 1) if line[1] < len(text) else None,
            ]
            for span in neighbors:
                if span is not None and _inside(ev, span):
                    neighbor_tokens = _tokens(text[span[0] : span[1]])
                    owns = row.equipment_id in neighbor_tokens
                    if neighbor_tokens & blocking_ids(others, owns):
                        return f"{name} quote sits on another capacity row's line"
                    break
            else:
                return f"{name} quote is not on or beside the row line"
            continue
        if row.group_span is None or not _inside(ev, row.group_span):
            return f"{name} quote is neither on the row line nor in its group title"
        between = text[row.group_span[1] : line[0]]
        if _GROUP_TITLE_AT_LINE_START.search(between):
            return f"{name} quote is in a group title that is not this row's"
    return None


def _row_problem(row: ExtractedRow, canon: CanonicalText, capacity_ids: set[str]) -> str | None:
    for name in REQUIRED_FIELDS:
        if name not in row.evidence:
            return f"missing evidence for {name}"
    declared = {
        "id": row.equipment_id,
        "type": row.equipment_type,
        "rating": str(row.rating),
        "unit": row.unit,
        "count": None if row.count is None else str(row.count),
        "drive": None if row.drive == "unknown" else row.drive,
        "state": None if row.state == "unknown" else row.state,
    }
    for name in OPTIONAL_FIELDS:
        if declared[name] is not None and name not in row.evidence:
            return f"{name} asserted without evidence"
        if declared[name] is None and name in row.evidence:
            return f"{name} evidence present for an unknown value"
    for name, ev in row.evidence.items():
        if name not in declared:
            return f"unknown evidence key {name!r}"
        if ev.field != name or ev.value != declared[name]:
            return f"{name} evidence disagrees with row value"
        problem = _span_problem(ev, canon) or _recompute_problem(ev, row)
        if problem is not None:
            return f"{name}: {problem}"
    if row.origin == "narrative":
        return _narrative_association(row, canon)
    return _table_association(row, canon, capacity_ids)


def verify_rows(rows: list[ExtractedRow], canon: CanonicalText) -> VerificationReport:
    report = VerificationReport()
    capacity_ids = {r.equipment_id for r in rows if r.group == "capacity-table"}
    for row in rows:
        problem = _row_problem(row, canon, capacity_ids)
        if problem is None:
            report.verified.append(row)
        else:
            report.rejected.append((row, problem))
    return report
