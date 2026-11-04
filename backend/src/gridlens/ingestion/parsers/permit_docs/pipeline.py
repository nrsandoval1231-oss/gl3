"""Public entry points: PDF bytes (or per-page text) -> verified rows + v4 schedule text."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
from typing import Any

from gridlens.domain.equipment_demand import EquipmentClaim
from gridlens.ingestion.parsers.permit_docs.models import ExtractedRow, Route
from gridlens.ingestion.parsers.permit_docs.narrative import extract_narrative
from gridlens.ingestion.parsers.permit_docs.router import route_page
from gridlens.ingestion.parsers.permit_docs.schedule import VERSION, build_schedule
from gridlens.ingestion.parsers.permit_docs.tables import extract_tables
from gridlens.ingestion.parsers.permit_docs.text_layer import (
    CanonicalText,
    TextLayerFailure,
    TextLayerLimits,
    build_canonical_text,
)
from gridlens.ingestion.parsers.permit_docs.verifier import verify_rows


@dataclass(slots=True)
class PermitExtractionResult:
    version: str = VERSION
    failure: TextLayerFailure | None = None
    pages: int = 0
    scanned_pages: int = 0
    needs_ocr_pages: list[int] = field(default_factory=list)
    routes: dict[str, int] = field(default_factory=dict)
    rows_by_kind: dict[str, int] = field(default_factory=dict)  # verified rows by origin
    rows_by_role: dict[str, int] = field(default_factory=dict)
    verified: int = 0
    rejected: int = 0
    rejection_reasons: list[tuple[str, str]] = field(default_factory=list)
    duplicates: int = 0
    claims: list[EquipmentClaim] = field(default_factory=list)
    supply_rows: list[ExtractedRow] = field(default_factory=list)
    demand_rows: list[ExtractedRow] = field(default_factory=list)
    schedule_text: str = ""
    provenance: dict[int, dict[str, Any]] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)


def _dedupe(rows: list[ExtractedRow]) -> tuple[list[ExtractedRow], int]:
    """Drop repeated mentions so one unit is never counted twice (undercount > overcount).

    A repeated narrative mention keeps the first row, upgraded to a later one only when the
    later mention is the one that states lifecycle state.
    """
    index: dict[tuple[object, ...], int] = {}
    kept: list[ExtractedRow] = []
    for row in rows:
        if row.origin == "narrative":
            key: tuple[object, ...] = (
                "n",
                row.equipment_type,
                row.drive,
                row.rating,
                row.unit,
                row.count,
            )
        else:
            key = ("t", row.equipment_id, row.equipment_type, row.rating, row.unit)
        if key not in index:
            index[key] = len(kept)
            kept.append(row)
        elif kept[index[key]].state == "unknown" and row.state != "unknown":
            kept[index[key]] = row
    return kept, len(rows) - len(kept)


def _row_lines(canon: CanonicalText, rows: list[ExtractedRow]) -> list[tuple[int, int]]:
    """Canonical-text line spans already read as table rows (narrative rules skip them)."""
    spans: list[tuple[int, int]] = []
    for row in rows:
        at = row.evidence["id"].start
        lo = canon.text.rfind("\n", 0, at) + 1
        hi = canon.text.find("\n", at)
        spans.append((lo, len(canon.text) if hi < 0 else hi))
    return spans


def _reconcile(rows: list[ExtractedRow]) -> tuple[list[ExtractedRow], list[str]]:
    """One unit described in prose AND in a table must not become two claims.

    Narrative and table rows with the same type, drive, rating and unit describe the same
    units. When the prose count fits within the table rows (or is unknown) only the table
    rows are kept; when the prose says more units than the table lists, only the prose row
    is kept. Either way the conflict is reported.
    """
    key = lambda r: (r.equipment_type, r.drive, r.rating, r.unit)  # noqa: E731
    table_index: dict[tuple[object, ...], list[int]] = {}
    for index, row in enumerate(rows):
        if row.origin == "table":
            table_index.setdefault(key(row), []).append(index)
    drop: set[int] = set()
    issues: list[str] = []
    for index, row in enumerate(rows):
        matches = table_index.get(key(row)) if row.origin == "narrative" else None
        if not matches or index in drop:
            continue
        if row.count is None or row.count <= len(matches):
            drop.add(index)
            issues.append(
                f"Conflict: prose {row.equipment_id} ({row.equipment_type}, {row.rating}"
                f" {row.unit},"
                f" count {row.count}) repeats {len(matches)} table row(s); kept the table rows."
            )
        else:
            drop.update(matches)
            issues.append(
                f"Conflict: prose {row.equipment_id} states {row.count} units but the table lists"
                f" {len(matches)}; kept the prose row only."
            )
    return [row for index, row in enumerate(rows) if index not in drop], issues


def _link(rows: list[ExtractedRow], canon: CanonicalText) -> list[ExtractedRow]:
    """Link a narrative row to table rows only through a name the permit itself uses."""
    linked: list[ExtractedRow] = []
    tables = [r for r in rows if r.origin == "table"]
    for row in rows:
        if row.origin != "narrative" or not row.link_hint:
            linked.append(row)
            continue
        ids = []
        for table_row in tables:
            at = table_row.evidence["id"].start
            line_start = canon.text.rfind("\n", 0, at) + 1
            line_end = canon.text.find("\n", at)
            line = canon.text[line_start : line_end if line_end >= 0 else None]
            if row.link_hint in line.split():
                ids.append(table_row.equipment_id)
        linked.append(replace(row, linked_to=tuple(ids)) if ids else row)
    return linked


def extract_from_canonical(
    canon: CanonicalText,
    *,
    document_hash: str,
    company: str | None = None,
    facility: str | None = None,
    as_of: str | None = None,
) -> PermitExtractionResult:
    result = PermitExtractionResult(pages=len(canon.pages))
    routes: dict[int, Route] = {p.page: route_page(p.text, p.chars) for p in canon.pages}
    result.routes = dict(Counter(routes.values()))
    result.needs_ocr_pages = [p for p, r in routes.items() if r == "scan"]
    result.scanned_pages = len(result.needs_ocr_pages)
    table_rows, table_issues = extract_tables(canon, routes)
    narrative_rows, narrative_issues = extract_narrative(
        canon, routes, _row_lines(canon, table_rows)
    )
    result.issues.extend(table_issues + narrative_issues)
    report = verify_rows(table_rows + narrative_rows, canon)
    result.verified = len(report.verified)
    result.rejected = len(report.rejected)
    result.rejection_reasons = [(row.equipment_id, why) for row, why in report.rejected]
    rows, result.duplicates = _dedupe(report.verified)
    rows, conflicts = _reconcile(rows)
    result.issues.extend(conflicts)
    rows = _link(rows, canon)
    build = build_schedule(
        rows, canon, document_hash=document_hash, company=company, facility=facility, as_of=as_of
    )
    result.issues.extend(build.issues)
    result.claims = build.claims
    result.demand_rows = build.demand_rows
    result.supply_rows = build.supply_rows
    result.schedule_text = build.text
    result.provenance = build.provenance
    result.rows_by_kind = dict(Counter(r.origin for r in rows))
    result.rows_by_role = {
        "demand_claim": len(build.demand_rows),
        "supply_other": len(build.supply_rows),
    }
    if canon.failed_pages:
        result.issues.append(
            f"Text extraction failed on page(s) {canon.failed_pages}; treated as needing OCR."
        )
    if result.needs_ocr_pages:
        result.issues.append(
            f"{len(result.needs_ocr_pages)} page(s) have no text layer and need OCR; no rows read."
        )
    return result


def extract_from_pages(
    page_texts: list[str],
    *,
    document_hash: str,
    company: str | None = None,
    facility: str | None = None,
    as_of: str | None = None,
) -> PermitExtractionResult:
    """Seam for already-extracted (or OCR'd) per-page text."""
    return extract_from_canonical(
        CanonicalText.from_page_texts(page_texts),
        document_hash=document_hash,
        company=company,
        facility=facility,
        as_of=as_of,
    )


def extract_permit_document(
    pdf_bytes: bytes,
    *,
    document_hash: str,
    company: str | None = None,
    facility: str | None = None,
    as_of: str | None = None,
    limits: TextLayerLimits | None = None,
) -> PermitExtractionResult:
    """Offline extraction of a permit PDF. Text-layer failure yields a typed failure result."""
    canon = build_canonical_text(pdf_bytes, limits)
    if isinstance(canon, TextLayerFailure):
        return PermitExtractionResult(failure=canon, issues=[f"{canon.code}: {canon.message}"])
    return extract_from_canonical(
        canon, document_hash=document_hash, company=company, facility=facility, as_of=as_of
    )
