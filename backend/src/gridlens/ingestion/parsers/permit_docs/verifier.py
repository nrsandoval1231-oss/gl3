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
from gridlens.ingestion.parsers.permit_docs.text_layer import CanonicalText

VERIFIER = "exact-span-v1"
_SYNTHETIC_ID = re.compile(r"N(\d+)-(\d+)\Z")
_ID_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/\-]{0,39}\Z")


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


def _row_problem(row: ExtractedRow, canon: CanonicalText) -> str | None:
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
            continue
        if ev.field != name or ev.value != declared[name]:
            return f"{name} evidence disagrees with row value"
        problem = _span_problem(ev, canon) or _recompute_problem(ev, row)
        if problem is not None:
            return f"{name}: {problem}"
    return None


def verify_rows(rows: list[ExtractedRow], canon: CanonicalText) -> VerificationReport:
    report = VerificationReport()
    for row in rows:
        problem = _row_problem(row, canon)
        if problem is None:
            report.verified.append(row)
        else:
            report.rejected.append((row, problem))
    return report
