"""Conservative portfolio demand summary over current equipment evidence."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from sqlalchemy import exists, literal_column, select
from sqlalchemy.orm import Session, aliased

from gridlens.intelligence.customer_results import _ASSET_B
from gridlens.intelligence.equipment_intelligence import current_equipment_investigations
from gridlens.intelligence.saved_browse import current_generation
from gridlens.persistence.models import BrowseRow, EvidencePackage, PowerNeed, Project

MAX_CANDIDATES = 500


def summarize(session: Session, sector: str = "all") -> dict:
    generation = current_generation(session)
    if generation is None:
        return _unavailable(sector, "Current canonical browse generation is unavailable.")
    browse = aliased(BrowseRow, name="b")
    raw_rows = session.execute(
        select(PowerNeed, Project, browse.compact, literal_column(_ASSET_B).label("asset_key"))
        .join(Project, Project.id == PowerNeed.project_id)
        .join(browse, browse.need_id == PowerNeed.id)
        .where(browse.generation_id == generation.id)
        .where(PowerNeed.active.is_(True), Project.region_status == "ELIGIBLE")
        .where(
            exists(
                select(1).where(
                    EvidencePackage.need_id == PowerNeed.id,
                    EvidencePackage.schema_version == "equipment-demand-v1",
                    EvidencePackage.question_contract == "equipment-demand-v1",
                )
            )
        )
        .order_by("asset_key", PowerNeed.id)
        .limit(MAX_CANDIDATES + 1)
    ).all()
    # Over budget: partial aggregates would masquerade as full-cohort totals.
    if len(raw_rows) > MAX_CANDIDATES:
        return _unavailable(sector, "Candidate cohort exceeds the supported summary bound.")
    rows = cast(list[tuple[PowerNeed, Project, dict[str, Any], str]], raw_rows)
    by_identity: dict[str, list[tuple[PowerNeed, Project, dict[str, Any], str]]] = defaultdict(list)
    for pair in rows:
        by_identity[pair[3]].append(pair)

    pairs = [(need.id, project.id) for need, project, _compact, _asset in rows]
    projections: dict[str, dict] = {}
    for start in range(0, len(pairs), 50):
        projections.update(current_equipment_investigations(session, pairs[start : start + 50]))

    classes: dict[str, dict[str, Any]] = {
        k: {"mw": Decimal(0), "record_count": 0} for k in ("documented", "calculated", "estimated")
    }
    totals = {
        "identified_records": 0,
        "known_mw_records": 0,
        "unknown_records": 0,
        "conflicted_records": 0,
    }
    source_ids: set[str] = set()
    latest: datetime | None = None
    for _identity, identity_rows in by_identity.items():
        # A project can have multiple active needs. They are not assumed additive.
        scoped = [
            item
            for item in identity_rows
            if sector == "all" or (item[2].get("project_metadata") or {}).get("sector") == sector
        ]
        if not scoped:
            continue
        if len(identity_rows) != 1 or len(scoped) != len(identity_rows):
            if any(str(n.id) in projections for n, _, _, _ in scoped):
                totals["identified_records"] += 1
                totals["conflicted_records"] += 1
            continue
        need, _project, _compact, _asset = scoped[0]
        record = projections.get(str(need.id))
        if not record:
            continue
        totals["identified_records"] += 1
        for ref in record.get("evidence", []):
            if ref.get("source_id"):
                source_ids.add(ref["source_id"])
            stamp = ref.get("retrieved_at")
            if stamp:
                try:
                    parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=UTC)
                    latest = max(latest, parsed) if latest else parsed
                except (ValueError, AttributeError):
                    pass
        if record.get("status") == "ABSTAINED":
            totals["conflicted_records"] += 1
            continue
        demand = record.get("demand") or {}
        # Only incremental equipment input is the portfolio measure. Missing stays unknown.
        raw = demand.get("incremental_kw")
        quantity_type = (record.get("quantity_classification") or {}).get(
            "incremental_kw", "UNKNOWN"
        )
        if raw is None:
            totals["unknown_records"] += 1
            continue
        try:
            mw = Decimal(str(raw)) / Decimal(1000)
        except (InvalidOperation, ValueError, TypeError):
            totals["unknown_records"] += 1
            continue
        if not mw.is_finite() or mw < 0:
            totals["unknown_records"] += 1
            continue
        kind = {
            "DOCUMENTED": "documented",
            "CALCULATED": "calculated",
            "ESTIMATED": "estimated",
        }.get(quantity_type)
        if kind is None:
            totals["unknown_records"] += 1
            continue
        totals["known_mw_records"] += 1
        classes[kind]["mw"] += mw
        classes[kind]["record_count"] += 1
    for entry in classes.values():
        if entry["record_count"] == 0:
            entry["mw"] = None
        else:
            entry["mw"] = float(entry["mw"])
    return {
        "counts_complete": True,
        "availability": "available" if totals["known_mw_records"] else "unavailable",
        "sector": sector,
        "as_of": datetime.now(UTC).isoformat(),
        "totals": totals,
        "classes": classes,
        "provenance": {
            "contract": "equipment-demand-v1",
            "source_count": len(source_ids),
            "latest_evidence_at": latest.isoformat() if latest else None,
        },
        "limitations": [
            "Only current validated equipment-demand-v1 records are included.",
            "Unknown and conflicted demand is excluded from MW totals.",
            "Overlapping active needs for the same project are not added.",
            "Demand values do not imply utility shortage or available supply.",
        ],
    }


def _unavailable(sector: str, limitation: str) -> dict:
    return {
        "counts_complete": False,
        "availability": "unavailable",
        "sector": sector,
        "as_of": datetime.now(UTC).isoformat(),
        "totals": {
            "identified_records": 0,
            "known_mw_records": 0,
            "unknown_records": 0,
            "conflicted_records": 0,
        },
        "classes": {
            k: {"mw": None, "record_count": 0} for k in ("documented", "calculated", "estimated")
        },
        "provenance": {
            "contract": "equipment-demand-v1",
            "source_count": 0,
            "latest_evidence_at": None,
        },
        "limitations": [limitation, "No complete supported MW total is available."],
    }
