"""Render verified rows as the existing v4 equipment-schedule text plus per-line provenance.

Only compressor/pump rows with an explicit stated drive and a demand-model rating unit
become `EquipmentClaim` objects. Engines, turbines, generators, heaters and rows without a
stated drive are retained as supply/other rows: kept with provenance, never fed to demand.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, cast

from gridlens.domain.equipment_demand import (
    Drive,
    EquipmentClaim,
    EquipmentState,
    EquipmentType,
    RatingBasis,
    RatingUnit,
)
from gridlens.ingestion.parsers.permit_docs.models import ExtractedRow
from gridlens.ingestion.parsers.permit_docs.text_layer import CanonicalText
from gridlens.ingestion.parsers.permit_docs.verifier import VERIFIER

VERSION = "permit-doc-extract-v1"
MAX_SCHEDULE_CLAIMS = 120  # equipment.py bounds: 128 claims, 256 lines
CLAIM_TYPES = {"compressor", "pump"}
CLAIM_DRIVES = {"electric", "gas_engine", "diesel_engine", "steam"}
CLAIM_UNITS = {"hp", "kW", "MW", "kVA"}
_DRIVE_TEXT = {
    "electric": "electric",
    "gas_engine": "gas engine",
    "diesel_engine": "diesel engine",
    "steam": "steam",
}
_RENDERABLE_ID = re.compile(r"[A-Z0-9][A-Z0-9._/\-]{0,39}\Z", re.I)
_MAX_PROVENANCE_SPAN = 800


@dataclass(slots=True)
class ScheduleBuild:
    text: str = ""
    claims: list[EquipmentClaim] = field(default_factory=list)
    provenance: dict[int, dict[str, Any]] = field(default_factory=dict)
    demand_rows: list[ExtractedRow] = field(default_factory=list)
    supply_rows: list[ExtractedRow] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


def is_demand_candidate(row: ExtractedRow) -> bool:
    return (
        row.equipment_type in CLAIM_TYPES
        and row.drive in CLAIM_DRIVES
        and row.unit in CLAIM_UNITS
        and _RENDERABLE_ID.fullmatch(row.equipment_id) is not None
    )


def _header_value(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"[\r\n|]+", " ", value).strip()
    return cleaned[:160] or None


def _plain(rating: Any) -> str:
    text = format(rating.normalize(), "f")
    return text


def render_line(row: ExtractedRow) -> str:
    rating = f"{_plain(row.rating)} {row.unit}"
    if row.unit == "hp":
        rating += " mechanical output"
    parts = [
        f"Equipment ID: {row.equipment_id}",
        f"Type: {row.equipment_type}",
        f"Drive: {_DRIVE_TEXT[row.drive]}",
        f"Rating: {rating}",
    ]
    if row.count is not None:
        parts.append(f"Count: {row.count}")
    parts.append(f"State: {row.state}")
    return " | ".join(parts)


def _row_provenance(row: ExtractedRow, canon: CanonicalText, document_hash: str) -> dict[str, Any]:
    rating = row.evidence["rating"]
    near = [
        ev
        for ev in row.evidence.values()
        if ev.page == rating.page and abs(ev.start - rating.start) <= _MAX_PROVENANCE_SPAN
    ]
    start = min(ev.start for ev in near)
    end = max(ev.end for ev in near)
    return {
        "page": rating.page,
        "start": start,
        "end": end,
        "quote": canon.text[start:end],
        "document_hash": document_hash,
        "verifier": VERIFIER,
        "origin": row.origin,
        "stitched": row.stitched,
        "linked_to": list(row.linked_to),
        "fields": {
            name: {
                "value": ev.value,
                "quote": ev.quote,
                "start": ev.start,
                "end": ev.end,
                "page": ev.page,
            }
            for name, ev in row.evidence.items()
        },
    }


def build_schedule(
    verified: list[ExtractedRow],
    canon: CanonicalText,
    *,
    document_hash: str,
    company: str | None,
    facility: str | None,
    as_of: str | None,
) -> ScheduleBuild:
    build = ScheduleBuild()
    lines: list[str] = []
    for label, value in (
        ("Company", _header_value(company)),
        ("Facility", _header_value(facility)),
    ):
        if value:
            lines.append(f"{label}: {value}")
    if as_of:
        try:
            date.fromisoformat(as_of)
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of):
                raise ValueError(as_of)
            lines.append(f"As of: {as_of}")
        except ValueError:
            build.issues.append("as_of is not an ISO date; header omitted.")
    seen_lines: set[str] = set()
    for row in verified:
        if not is_demand_candidate(row):
            build.supply_rows.append(row)
            continue
        if len(build.demand_rows) >= MAX_SCHEDULE_CLAIMS:
            build.issues.append("Schedule claim bound reached; remaining demand rows omitted.")
            build.supply_rows.append(row)
            continue
        line = render_line(row)
        try:
            _make_claim(row, line, 0)
        except ValueError as exc:
            build.issues.append(f"Row {row.equipment_id} rejected by the demand model: {exc}")
            build.supply_rows.append(row)
            continue
        if line in seen_lines:
            build.issues.append(f"Identical schedule line for {row.equipment_id} was skipped.")
            continue
        seen_lines.add(line)
        build.demand_rows.append(row)
        lines.append(line)
        build.provenance[len(lines) - 1] = _row_provenance(row, canon, document_hash)
    build.text = "\n".join(lines) + ("\n" if lines else "")
    cursor = 0
    claim_rows = iter(build.demand_rows)
    for index, raw in enumerate(build.text.splitlines(keepends=True)):
        stripped = raw.rstrip(chr(13) + chr(10))
        if index in build.provenance:
            row = next(claim_rows)
            build.claims.append(_make_claim(row, stripped, cursor))
        cursor += len(raw)
    return build


def _make_claim(row: ExtractedRow, line: str, start: int) -> EquipmentClaim:
    return EquipmentClaim(
        equipment_id=row.equipment_id,
        equipment_type=cast(EquipmentType, row.equipment_type),
        drive=cast(Drive, row.drive),
        rating=row.rating,
        unit=cast(RatingUnit, row.unit),
        rating_basis=cast(RatingBasis, "mechanical_output" if row.unit == "hp" else "unknown"),
        count=row.count,
        state=cast(EquipmentState, row.state),
        quote=line,
        start=start,
        end=start + len(line),
    )
