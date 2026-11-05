"""Horsepower and driver evidence from a Federal Register / GovInfo notice excerpt.

Reuses the permit-document narrative rules, lexicon and exact-span verifier unchanged. A rating
is attached to equipment only when the notice's own words put the rating and an equipment noun
in one phrase; electric drive counts only when the same phrase states it. A rating without a
stated driver is kept as ``drive: unknown`` supply context, never as electrical demand, and a
compressor rating is never turned into a motor rating (the West Edmond trap: a driven
compressor's rated hp is not the electric motor's).

Input is the bounded excerpt produced by ``govinfo_pdf.retrieve_companion``: page fragments
joined as ``[GovInfo PDF page N] text``. Output rows carry the verbatim quote, the PDF page and
the character span inside that excerpt, re-checked before the row is returned. Nothing here
touches the network or the database. Unknown is never zero: an excerpt with no verified row
returns an explicit abstention.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from gridlens.ingestion.parsers.permit_docs.models import ExtractedRow, Route
from gridlens.ingestion.parsers.permit_docs.narrative import extract_narrative
from gridlens.ingestion.parsers.permit_docs.notice_post_rating import (
    post_rating_problem,
    post_rating_rows,
)
from gridlens.ingestion.parsers.permit_docs.router import route_page
from gridlens.ingestion.parsers.permit_docs.text_layer import CanonicalText
from gridlens.ingestion.parsers.permit_docs.verifier import VERIFIER, verify_rows

VERSION = "fr-notice-hp-driver-v1"
MAX_EXCERPT_CHARS = 128_000
MAX_ROWS = 50
_MARKER = re.compile(r"\[GovInfo PDF page (\d{1,4})\]\s?")
# Equipment types whose electric drive is electrical demand when explicitly evidenced.
ELECTRIC_DEMAND_TYPES = frozenset({"compressor", "pump", "motor"})
ELECTRIC_DEMAND_UNITS = frozenset({"hp", "kW", "MW"})


@dataclass(slots=True)
class NoticeHpResult:
    version: str = VERSION
    verifier: str = VERIFIER
    pages: int = 0
    rows: list[dict[str, Any]] = field(default_factory=list)
    rejected: int = 0
    abstain: dict[str, str] | None = None

    def as_json(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "verifier": self.verifier,
            "pages": self.pages,
            "rows": self.rows,
            "rejected": self.rejected,
            "abstain": self.abstain,
        }


def _split_pages(excerpt: str) -> list[tuple[int, int, str]]:
    """(pdf page, offset of the page text inside the excerpt, page text) per marker."""
    markers = list(_MARKER.finditer(excerpt))
    pages: list[tuple[int, int, str]] = []
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(excerpt)
        pages.append((int(marker.group(1)), marker.end(), excerpt[marker.end() : end]))
    return pages


def _row_json(
    row: ExtractedRow, canon: CanonicalText, offsets: list[int], pdf_pages: list[int]
) -> dict[str, Any] | None:
    fields: dict[str, dict[str, Any]] = {}
    for name, ev in row.evidence.items():
        if name == "id":
            continue
        index = ev.page - 1
        start = offsets[index] + (ev.start - canon.page_starts[index])
        end = start + (ev.end - ev.start)
        fields[name] = {
            "value": ev.value,
            "quote": ev.quote,
            "page": pdf_pages[index],
            "start": start,
            "end": end,
        }
    electric = (
        row.drive == "electric"
        and row.equipment_type in ELECTRIC_DEMAND_TYPES
        and row.unit in ELECTRIC_DEMAND_UNITS
        and "drive" in fields
        and row.state not in {"retired"}
    )
    return {
        "equipment_type": row.equipment_type,
        "drive": row.drive,
        "rating": str(row.rating),
        "unit": row.unit,
        "count": row.count,
        "state": row.state,
        "evidence": fields,
        # Explicit electric-drive wording in the rating's own phrase is required; a rating
        # alone, or a rating beside a non-electric driver, is supply context only.
        "electric_demand_evidenced": electric,
        # A post-rating phrase ("2 units ... with a rating of N hp") does not say whether N is
        # per unit or the total; the pre-rating shape ("two 2,500-hp motors") is per unit.
        "rating_basis": (
            "unstated_per_unit_or_total"
            if row.group == "post-rating" and row.count not in (None, 1)
            else "per_unit_as_stated"
        ),
        "role": "demand_claim" if electric else "supply_other",
    }


def extract_notice_hp_driver(excerpt: str) -> NoticeHpResult:
    """Verified hp ratings and drivers from a bounded notice excerpt."""
    result = NoticeHpResult()
    if not isinstance(excerpt, str) or not excerpt.strip():
        result.abstain = {"reason": "empty notice text", "note": "unknown is not zero"}
        return result
    if len(excerpt) > MAX_EXCERPT_CHARS:
        result.abstain = {"reason": "notice text over size bound", "note": "unknown is not zero"}
        return result
    pages = _split_pages(excerpt)
    result.pages = len(pages)
    if not pages:
        result.abstain = {"reason": "no page markers in notice text", "note": "unknown is not zero"}
        return result
    canon = CanonicalText.from_page_texts([text for _, _, text in pages])
    pdf_pages = [page for page, _, _ in pages]
    offsets = [offset for _, offset, _ in pages]
    routes: dict[int, Route] = {p.page: route_page(p.text, p.chars) for p in canon.pages}
    rows, _issues = extract_narrative(canon, routes)
    report = verify_rows(rows, canon)
    result.rejected = len(report.rejected)
    verified = list(report.verified)
    for post_row in post_rating_rows(canon):
        if post_rating_problem(post_row, canon) is None:
            verified.append(post_row)
        else:
            result.rejected += 1
    seen: Counter[tuple[object, ...]] = Counter()
    for row in verified[:MAX_ROWS]:
        item = _row_json(row, canon, offsets, pdf_pages)
        if item is None:
            continue
        # The final guard: every quote must be the excerpt's own text at the stated span.
        if any(
            " ".join(excerpt[v["start"] : v["end"]].split()) != " ".join(v["quote"].split())
            for v in item["evidence"].values()
        ):
            result.rejected += 1
            continue
        # Dedupe by the rating's own span only: two stations that state the same rating are two
        # rows. (Both shapes matching one phrase gives the same span, kept once.)
        key = (item["evidence"]["rating"]["page"], item["evidence"]["rating"]["start"])
        seen[key] += 1
        if seen[key] > 1:
            continue
        result.rows.append(item)
    if not result.rows:
        result.abstain = {
            "reason": "no verified rating-with-equipment phrase",
            "note": "abstention, not zero demand: unknown is not zero",
        }
    return result
