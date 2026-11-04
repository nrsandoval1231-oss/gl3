"""Seams for optional model passes, and the deterministic gate for model-proposed rows.

Nothing here talks to a network, a model or a database. A proposer or an OCR provider is an
object injected by the caller; this module defines what they return and how a proposal
becomes an ``ExtractedRow`` that the unchanged exact-span verifier then accepts or rejects.

A proposal is only a claim about the canonical text: each value carries a verbatim quote and
a page. The code here locates the quote in the stored canonical text (whitespace runs may
differ, nothing else), builds the evidence, and leaves the verdict to ``verify_rows``, which
recomputes every value from its quote with the shared lexicon. A value the lexicon cannot
reproduce from its quote rejects the whole row. The model never repairs, normalises or
fills in anything, and a missing field stays unknown.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from gridlens.ingestion.parsers.permit_docs.models import ExtractedRow, FieldEvidence
from gridlens.ingestion.parsers.permit_docs.text_layer import CanonicalText
from gridlens.ingestion.parsers.permit_docs.verifier import (
    IN_SERVICE_CUE,
    at_token_boundary,
    sentence_around,
)

MAX_PROPOSED_UNITS = 40
MAX_QUOTE_CHARS = 240
_FIELDS = ("unit_id", "equipment_type", "quantity", "rating", "driver", "status", "in_service_date")
_REQUIRED = ("equipment_type", "rating")
_STATUS_TO_STATE = {
    "new": "new",
    "proposed": "proposed",
    "existing": "existing",
    "removed": "retired",
}
_EVIDENCE_NAME = {
    "unit_id": "id",
    "equipment_type": "type",
    "quantity": "count",
    "driver": "drive",
    "status": "state",
    "in_service_date": "date",
}


@dataclass(frozen=True, slots=True)
class PageForProposal:
    page: int
    text: str


@dataclass(slots=True)
class ProposerOutcome:
    """Typed result of one proposer pass. ``status`` is never inferred from ``units``."""

    status: str  # "ok" | "disabled" | "blocked" | "capped_out" | "unknown" | "failed"
    reason: str = ""
    units: list[dict[str, Any]] = field(default_factory=list)
    label: str = ""  # "llm:<provider>:<model>" of the model that proposed
    pages_sent: list[int] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)


class EquipmentProposer(Protocol):
    def propose(self, pages: list[PageForProposal], *, document_hash: str) -> ProposerOutcome: ...


@dataclass(slots=True)
class OcrOutcome:
    status: str  # "ok" | "disabled" | "blocked" | "capped_out" | "unknown" | "failed"
    reason: str = ""
    texts: dict[int, str] = field(default_factory=dict)
    source: str = ""  # "ocr:<provider>:<model>" label carried into provenance
    detail: dict[str, Any] = field(default_factory=dict)


class PageOcr(Protocol):
    def ocr_pages(self, pages: list[int], *, document_hash: str) -> OcrOutcome: ...


@dataclass(slots=True)
class ProposalReport:
    rows: list[ExtractedRow] = field(default_factory=list)
    dropped: list[tuple[int, str]] = field(default_factory=list)  # (unit index, reason)
    standby_dropped: int = 0


def _flexible(quote: str) -> re.Pattern[str] | None:
    parts = quote.split()
    if not parts or len(quote) > MAX_QUOTE_CHARS:
        return None
    return re.compile(r"\s+".join(re.escape(part) for part in parts))


def _find(canon: CanonicalText, page: int, quote: str) -> list[tuple[int, int]]:
    """Canonical spans of ``quote`` on ``page`` (whitespace-flexible), ascending."""
    pattern = _flexible(quote)
    if pattern is None or not 1 <= page <= len(canon.pages):
        return []
    lo, hi = canon.page_span(page)
    spans = [(lo + m.start(), lo + m.end()) for m in pattern.finditer(canon.text[lo:hi])]
    # A quote must stand alone: "500 hp" is not found inside "1,500 hp", "C-1" not in "C-10".
    return [span for span in spans if at_token_boundary(canon.text, span[0], span[1])]


def _field(unit: dict[str, Any], name: str) -> dict[str, Any] | None:
    value = unit.get(name)
    if value is None:
        return None
    if not isinstance(value, dict) or not isinstance(value.get("quote"), str):
        raise ValueError(f"{name} is not a quote-backed value")
    return value


def _closest(spans: list[tuple[int, int]], anchor: tuple[int, int]) -> tuple[int, int]:
    return min(spans, key=lambda s: (abs(s[0] - anchor[0]), s[0]))


def _evidence(
    canon: CanonicalText, name: str, value: str, span: tuple[int, int], page: int
) -> FieldEvidence:
    return FieldEvidence(name, value, canon.text[span[0] : span[1]], span[0], span[1], page)


def _build_row(unit: dict[str, Any], canon: CanonicalText, label: str) -> ExtractedRow:
    """Raise ``ValueError`` (a drop reason) for anything that cannot be located exactly."""
    fields = {name: _field(unit, name) for name in _FIELDS}
    for name in _REQUIRED:
        if fields[name] is None:
            raise ValueError(f"{name} missing")
    pages = {f.get("page") for f in fields.values() if f is not None}
    if any(type(page) is not int for page in pages):
        raise ValueError("field page is not an integer")
    page_value = unit.get("page")
    if type(page_value) is not int or pages - {page_value}:
        raise ValueError("fields do not share one stated page")
    page = page_value
    rating_f = fields["rating"]
    assert rating_f is not None
    rating_spans = _find(canon, page, rating_f["quote"])
    if len(rating_spans) != 1:
        raise ValueError("rating quote is absent or ambiguous on its page")
    rating_span = rating_spans[0]
    try:
        rating = Decimal(str(rating_f.get("value")))
    except InvalidOperation as exc:
        raise ValueError("rating value is not a decimal") from exc
    if not rating.is_finite() or rating <= 0:
        raise ValueError("rating must be positive")
    unit_name = str(unit.get("rating_unit") or "")
    type_f = fields["equipment_type"]
    assert type_f is not None
    evidence: dict[str, FieldEvidence] = {
        "rating": _evidence(canon, "rating", str(rating), rating_span, page),
        "unit": _evidence(canon, "unit", unit_name, rating_span, page),
    }
    values: dict[str, str] = {}
    lo, hi = canon.page_span(page)
    first, last = sentence_around(canon.text, lo, hi, rating_span[0], rating_span[1])
    in_service_cue = IN_SERVICE_CUE.search(canon.text[first:last]) is not None
    for name in ("equipment_type", "quantity", "driver", "status", "in_service_date", "unit_id"):
        f = fields[name]
        if f is None:
            continue
        if name == "in_service_date" and not in_service_cue:
            continue  # a date without an in-service cue is only a stated date: not kept
        raw = f.get("value")
        if raw is None:
            continue
        spans = _find(canon, page, f["quote"])
        if not spans:
            raise ValueError(f"{name} quote not found on its page")
        span = _closest(spans, rating_span)
        text = str(raw)
        if name == "status":
            if raw == "standby":
                raise ValueError("standby")
            text = _STATUS_TO_STATE.get(str(raw), "")
            if not text:
                raise ValueError("status not recognised")
        elif name == "driver" and raw == "unknown":
            continue  # unknown stays unknown: no evidence, no assertion
        elif name == "quantity":
            if type(raw) is not int or raw <= 0:
                raise ValueError("quantity must be a positive integer")
            text = str(raw)
        values[name] = text
        evidence[_EVIDENCE_NAME[name]] = _evidence(canon, _EVIDENCE_NAME[name], text, span, page)
    if "id" not in evidence:
        synthetic = f"L{page}-{rating_span[0]}"
        evidence["id"] = _evidence(canon, "id", synthetic, rating_span, page)
        values["unit_id"] = synthetic
    count = values.get("quantity")
    return ExtractedRow(
        origin="llm",
        equipment_id=values["unit_id"],
        equipment_type=values["equipment_type"],
        drive=values.get("driver", "unknown"),
        rating=rating,
        unit=unit_name,
        count=int(count) if count is not None else None,
        state=values.get("status", "unknown"),
        evidence=evidence,
        proposed_by=label,
        in_service_date=values.get("in_service_date", ""),
    )


def rows_from_proposals(
    units: list[dict[str, Any]], canon: CanonicalText, label: str
) -> ProposalReport:
    """Turn proposed units into candidate rows. Unlocatable or standby units are dropped."""
    report = ProposalReport()
    for index, unit in enumerate(units[:MAX_PROPOSED_UNITS]):
        try:
            if not isinstance(unit, dict):
                raise ValueError("unit is not an object")
            report.rows.append(_build_row(unit, canon, label))
        except ValueError as exc:
            if str(exc) == "standby":
                report.standby_dropped += 1
            report.dropped.append((index, str(exc)[:120]))
    if len(units) > MAX_PROPOSED_UNITS:
        report.dropped.append((MAX_PROPOSED_UNITS, "proposal count bound reached"))
    return report
