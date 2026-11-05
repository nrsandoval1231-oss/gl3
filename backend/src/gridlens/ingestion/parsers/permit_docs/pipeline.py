"""Public entry points: PDF bytes (or per-page text) -> verified rows + v4 schedule text."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
from typing import Any

from gridlens.domain.equipment_demand import EquipmentClaim
from gridlens.ingestion.parsers.permit_docs.models import TEXT_LAYER, ExtractedRow, Route
from gridlens.ingestion.parsers.permit_docs.narrative import extract_narrative
from gridlens.ingestion.parsers.permit_docs.proposals import (
    EquipmentProposer,
    OcrOutcome,
    PageForProposal,
    PageOcr,
    ProposerOutcome,
    rows_from_proposals,
)
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
    ocr_retained_rows: list[ExtractedRow] = field(default_factory=list)
    demand_rows: list[ExtractedRow] = field(default_factory=list)
    schedule_text: str = ""
    provenance: dict[int, dict[str, Any]] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    # Optional passes. Empty dicts mean the pass did not run (the default).
    ocr: dict[str, Any] = field(default_factory=dict)
    proposer: dict[str, Any] = field(default_factory=dict)


def _dedupe(rows: list[ExtractedRow]) -> tuple[list[ExtractedRow], int]:
    """Drop repeated mentions so one unit is never counted twice (undercount > overcount).

    A repeated narrative mention keeps the first row, upgraded to a later one only when the
    later mention is the one that states lifecycle state.
    """
    index: dict[tuple[object, ...], int] = {}
    kept: list[ExtractedRow] = []
    for row in rows:
        if row.origin in ("narrative", "llm"):
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
        matches = table_index.get(key(row)) if row.origin != "table" else None
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


def _stamp_text_source(rows: list[ExtractedRow], canon: CanonicalText) -> list[ExtractedRow]:
    """Carry each row's text source: any OCR page among its quotes makes it OCR-sourced."""
    stamped: list[ExtractedRow] = []
    for row in rows:
        sources = {canon.pages[ev.page - 1].source for ev in row.evidence.values()}
        ocr = sorted(source for source in sources if source != TEXT_LAYER)
        stamped.append(replace(row, text_source=ocr[0]) if ocr else row)
    return stamped


def _run_ocr(
    canon: CanonicalText, document_hash: str, ocr: PageOcr, result: PermitExtractionResult
) -> CanonicalText:
    pages = canon.scanned_pages
    try:
        outcome = ocr.ocr_pages(pages, document_hash=document_hash)
    except Exception as exc:  # noqa: BLE001 - an optional pass must never lose the rule rows
        outcome = OcrOutcome("failed", type(exc).__name__)
    result.ocr = {
        "status": outcome.status,
        "reason": outcome.reason,
        "pages_requested": pages,
        "pages_read": [],
        "text_source": outcome.source,
        **outcome.detail,
    }
    if outcome.status != "ok" or not outcome.source:
        result.issues.append(f"OCR pass did not run ({outcome.status}: {outcome.reason}).")
        return canon
    texts = {page: text for page, text in outcome.texts.items() if page in pages and text.strip()}
    merged = canon.with_ocr_pages(texts, outcome.source)
    result.ocr["pages_read"] = sorted(texts)
    return merged


def _eligible_proposer_pages(
    routes: dict[int, Route], verified: list[ExtractedRow], rejected: list[ExtractedRow]
) -> list[int]:
    """Table/narrative pages where the rules found nothing, or where they rejected a row."""
    found = {row.evidence["rating"].page for row in verified}
    doubtful = {row.evidence["rating"].page for row in rejected if "rating" in row.evidence}
    return [
        page
        for page, route in sorted(routes.items())
        if route in ("table", "narrative") and (page not in found or page in doubtful)
    ]


def _one_row_per_rating(
    proposed: list[ExtractedRow], rule_rows: list[ExtractedRow]
) -> tuple[list[ExtractedRow], int]:
    """At most one proposed row per rating span, and never over a rule-verified rating.

    Proposed rows whose rating spans overlap are one claimed unit: identical rows collapse,
    rows that disagree are all dropped (fail closed). A span that a rule row already holds
    belongs to the rule row.
    """
    taken = [
        (r.evidence["rating"].page, r.evidence["rating"].start, r.evidence["rating"].end)
        for r in rule_rows
    ]
    taken_keys = {
        (r.evidence["rating"].page, r.rating, r.unit, r.equipment_type) for r in rule_rows
    }
    groups: list[list[ExtractedRow]] = []
    for row in proposed:
        rating = row.evidence["rating"]
        span = (rating.page, rating.start, rating.end)
        if (
            any(_overlap(span, t) for t in taken)
            or (
                rating.page,
                row.rating,
                row.unit,
                row.equipment_type,
            )
            in taken_keys
        ):
            continue
        for group in groups:
            other = group[0].evidence["rating"]
            if _overlap(span, (other.page, other.start, other.end)):
                group.append(row)
                break
        else:
            groups.append([row])
    kept: list[ExtractedRow] = []
    conflicts = 0
    for group in groups:
        first = group[0]
        same = all(
            (r.equipment_type, r.drive, r.rating, r.unit, r.count, r.state, r.in_service_date)
            == (
                first.equipment_type,
                first.drive,
                first.rating,
                first.unit,
                first.count,
                first.state,
                first.in_service_date,
            )
            for r in group
        )
        if same:
            kept.append(first)
        else:
            conflicts += len(group)
    return kept, conflicts


def _overlap(a: tuple[int, int, int], b: tuple[int, int, int]) -> bool:
    return a[0] == b[0] and a[1] < b[2] and b[1] < a[2]


def _run_proposer(
    canon: CanonicalText,
    routes: dict[int, Route],
    document_hash: str,
    proposer: EquipmentProposer,
    verified: list[ExtractedRow],
    rejected: list[ExtractedRow],
    result: PermitExtractionResult,
) -> list[ExtractedRow]:
    pages = _eligible_proposer_pages(routes, verified, rejected)
    result.proposer = {"status": "not_needed", "eligible_pages": pages}
    if not pages:
        return []
    page_texts = [PageForProposal(page, canon.pages[page - 1].text) for page in pages]
    try:
        outcome = proposer.propose(page_texts, document_hash=document_hash)
    except Exception as exc:  # noqa: BLE001 - an optional pass must never lose the rule rows
        outcome = ProposerOutcome("failed", type(exc).__name__)
    result.proposer = {
        "status": outcome.status,
        "reason": outcome.reason,
        "label": outcome.label,
        "eligible_pages": pages,
        "pages_sent": outcome.pages_sent,
        **outcome.detail,
    }
    if outcome.status != "ok":
        result.issues.append(f"Model proposer did not run ({outcome.status}: {outcome.reason}).")
        return []
    try:
        built = rows_from_proposals(outcome.units, canon, outcome.label)
        checked = verify_rows(built.rows, canon)
    except Exception as exc:  # noqa: BLE001 - never lose the rule rows
        result.proposer.update(status="failed", reason=type(exc).__name__)
        result.issues.append(f"Model proposals could not be checked ({type(exc).__name__}).")
        return []
    accepted, conflicts = _one_row_per_rating(_stamp_text_source(checked.verified, canon), verified)
    if conflicts:
        result.issues.append(f"{conflicts} proposed unit(s) disagreed about one rating; dropped.")
    result.proposer.update(
        proposed=len(outcome.units),
        unlocatable=len(built.dropped),
        standby_dropped=built.standby_dropped,
        verifier_rejected=len(checked.rejected),
        verified=len(accepted),
        conflicting_dropped=conflicts,
        rejection_reasons=[why for _row, why in checked.rejected][:20],
        drop_reasons=[why for _i, why in built.dropped][:20],
    )
    return accepted


def extract_from_canonical(
    canon: CanonicalText,
    *,
    document_hash: str,
    company: str | None = None,
    facility: str | None = None,
    as_of: str | None = None,
    ocr: PageOcr | None = None,
    proposer: EquipmentProposer | None = None,
    allow_ocr_demand: bool = False,
) -> PermitExtractionResult:
    """Rules first; with ``ocr``/``proposer`` supplied, two optional passes (both off by default).

    ``ocr`` reads scanned pages and labels them; ``proposer`` asks a model to propose rows
    for pages where the rules found nothing, and the exact-span verifier decides. Neither
    changes what the rules alone would return for text-layer pages.
    """
    result = PermitExtractionResult(pages=len(canon.pages))
    routes: dict[int, Route] = {p.page: route_page(p.text, p.chars) for p in canon.pages}
    result.routes = dict(Counter(routes.values()))
    result.needs_ocr_pages = [p for p, r in routes.items() if r == "scan"]
    result.scanned_pages = len(result.needs_ocr_pages)
    if ocr is not None and result.needs_ocr_pages:
        canon = _run_ocr(canon, document_hash, ocr, result)
        routes = {p.page: route_page(p.text, p.chars) for p in canon.pages}
        result.routes = dict(Counter(routes.values()))
        result.needs_ocr_pages = [p for p, r in routes.items() if r == "scan"]
    table_rows, table_issues = extract_tables(canon, routes)
    narrative_rows, narrative_issues = extract_narrative(
        canon, routes, _row_lines(canon, table_rows)
    )
    result.issues.extend(table_issues + narrative_issues)
    report = verify_rows(table_rows + narrative_rows, canon)
    verified_rows = _stamp_text_source(report.verified, canon)
    if proposer is not None:
        rejected_rows = [row for row, _why in report.rejected]
        verified_rows = verified_rows + _run_proposer(
            canon, routes, document_hash, proposer, verified_rows, rejected_rows, result
        )
    result.verified = len(verified_rows)
    result.rejected = len(report.rejected)
    result.rejection_reasons = [(row.equipment_id, why) for row, why in report.rejected]
    rows, result.duplicates = _dedupe(verified_rows)
    rows, conflicts = _reconcile(rows)
    result.issues.extend(conflicts)
    rows = _link(rows, canon)
    build = build_schedule(
        rows,
        canon,
        document_hash=document_hash,
        company=company,
        facility=facility,
        as_of=as_of,
        allow_ocr_demand=allow_ocr_demand,
    )
    result.issues.extend(build.issues)
    result.claims = build.claims
    result.demand_rows = build.demand_rows
    result.supply_rows = build.supply_rows
    result.ocr_retained_rows = build.ocr_retained_rows
    result.schedule_text = build.text
    result.provenance = build.provenance
    result.rows_by_kind = dict(Counter(r.origin for r in rows))
    result.rows_by_role = {
        "demand_claim": len(build.demand_rows),
        "supply_other": len(build.supply_rows),
    }
    if build.ocr_retained_rows:
        result.rows_by_role["ocr_retained_demand_candidate"] = len(build.ocr_retained_rows)
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
    ocr: PageOcr | None = None,
    proposer: EquipmentProposer | None = None,
    allow_ocr_demand: bool = False,
) -> PermitExtractionResult:
    """Seam for already-extracted (or OCR'd) per-page text."""
    return extract_from_canonical(
        CanonicalText.from_page_texts(page_texts),
        document_hash=document_hash,
        company=company,
        facility=facility,
        as_of=as_of,
        ocr=ocr,
        proposer=proposer,
        allow_ocr_demand=allow_ocr_demand,
    )


def extract_permit_document(
    pdf_bytes: bytes,
    *,
    document_hash: str,
    company: str | None = None,
    facility: str | None = None,
    as_of: str | None = None,
    limits: TextLayerLimits | None = None,
    isolate: bool = True,
    ocr: PageOcr | None = None,
    proposer: EquipmentProposer | None = None,
    allow_ocr_demand: bool = False,
) -> PermitExtractionResult:
    """Offline extraction of a permit PDF. Text-layer failure yields a typed failure result."""
    canon = build_canonical_text(pdf_bytes, limits, isolate=isolate)
    if isinstance(canon, TextLayerFailure):
        return PermitExtractionResult(failure=canon, issues=[f"{canon.code}: {canon.message}"])
    return extract_from_canonical(
        canon,
        document_hash=document_hash,
        company=company,
        facility=facility,
        as_of=as_of,
        ocr=ocr,
        proposer=proposer,
        allow_ocr_demand=allow_ocr_demand,
    )
