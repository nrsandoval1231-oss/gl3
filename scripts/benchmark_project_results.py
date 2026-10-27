"""Read-only project-results benchmark of the prospectively frozen real-source cohort."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from sqlalchemy import event, func, select, text
    from sqlalchemy.engine import make_url

    from gridlens.intelligence.project_results import page
    from gridlens.persistence.database import SessionLocal
    from gridlens.persistence.models import (
        Evidence,
        LogicalCall,
        Observation,
        PowerNeed,
        Project,
    )
    from gridlens.settings import settings

    url = make_url(settings.database_url)
    if (
        url.host != "127.0.0.1"
        or url.database != "gridlens_issue128_local"
        or url.query
    ):
        raise RuntimeError("Requires the exact isolated local source-capture database")
    if args.output.exists():
        raise RuntimeError("Refusing to overwrite an existing benchmark")
    manifest = (
        ROOT / "docs/validation/commercial-release-20261026/frozen-native-cohort.json"
    )
    frozen = json.loads(manifest.read_text())
    rows = []
    with SessionLocal() as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        for candidate in frozen["projects"]:
            project = session.scalar(
                select(Project).where(
                    Project.source_id == candidate["source_id"],
                    Project.external_id == candidate["external_id"],
                )
            )
            if project is None:
                rows.append(
                    {
                        "source_id": candidate["source_id"],
                        "external_id": candidate["external_id"],
                        "present": False,
                    }
                )
                continue
            result = page(session, search=candidate["external_id"], limit=50)
            item = next(
                (
                    item
                    for item in result["items"]
                    if str(project.id) in item["project_ids"]
                ),
                None,
            )
            needs = session.scalars(
                select(PowerNeed).where(
                    PowerNeed.project_id == project.id, PowerNeed.active.is_(True)
                )
            ).all()
            rows.append(
                {
                    "source_id": candidate["source_id"],
                    "external_id": candidate["external_id"],
                    "project_id": str(project.id),
                    "present": item is not None,
                    "name": item["name"] if item else project.name,
                    "company": item["company"] if item else None,
                    "location": item["location"] if item else project.location,
                    "event": item["event"] if item else None,
                    "tiers": sorted({need.tier for need in needs}),
                    "required_mw": [need.required_mw for need in needs],
                    "need_start": [need.start_window for need in needs],
                    "contact_routes": item["contact"] if item else [],
                    "named_people": item["contact_people"] if item else [],
                    "power_summary": item["power_summary"] if item else None,
                    "power_summary_kind": item.get("power_summary_kind")
                    if item
                    else None,
                }
            )
        counts = {
            model.__tablename__: session.scalar(select(func.count()).select_from(model))
            for model in (Project, PowerNeed, Observation, Evidence, LogicalCall)
        }
    measures = []
    for label, filters in [
        ("qualified_default", {}),
        ("oil_gas", {"sector": "oil_gas"}),
        ("data_centers", {"sector": "data_centers"}),
        ("pioneer", {"search": "PIONEER"}),
        ("same_well_duplicate_permits", {"search": "WEST SEMINOLE SA UNIT"}),
    ]:
        with SessionLocal() as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            queries = []
            engine = session.get_bind()

            def statement(*_args):
                queries.append(1)

            event.listen(engine, "before_cursor_execute", statement)
            try:
                start = perf_counter()
                result = page(session, limit=25, **filters)
                elapsed = perf_counter() - start
            finally:
                event.remove(engine, "before_cursor_execute", statement)
            measures.append(
                {
                    "case": label,
                    "total_projects": result["total"],
                    "returned_projects": len(result["items"]),
                    "query_count": len(queries),
                    "elapsed_ms": round(elapsed * 1000, 2),
                    "response_bytes": len(json.dumps(result).encode()),
                    "results_scope": result["results_scope"],
                    "items": result["items"]
                    if label == "same_well_duplicate_permits"
                    else None,
                }
            )
    present = [row for row in rows if row["present"]]
    routes = [route for row in present for route in row["contact_routes"]]
    identity_path = (
        ROOT
        / "docs/validation/project-first-20261027/frozen-rrc-identity-comparison.json"
    )
    identity_rows = (
        json.loads(identity_path.read_text()) if identity_path.exists() else []
    )
    identity_matches = sum(
        bool(row.get("identity_fields_match"))
        and all(row["identity_fields_match"].values())
        for row in identity_rows
    )
    tdlr_present = sum(
        row["source_id"] == "texas-tdlr-tabs-data-centers"
        and bool(row["company"] and row["location"])
        for row in present
    )
    result = {
        "kind": "frozen_actual_source_record_benchmark",
        "measured_at": datetime.now(UTC).isoformat(),
        "scope": "isolated source-capture replay, not production or live scheduled-operation proof",
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "selection_frozen_before_outcomes": frozen[
            "selection_frozen_before_contact_research"
        ],
        "requested_projects": 25,
        "source_records_present": len(present),
        "identity_assertions_exact_match": identity_matches + tdlr_present
        if identity_rows
        else None,
        "identity_assertions_denominator": 25,
        "identity_conflicts": [
            {
                "permit": row["permit"],
                "expected": row["expected"],
                "official_row": row["official_row"],
                "identity_fields_match": row["identity_fields_match"],
            }
            for row in identity_rows
            if not all(row.get("identity_fields_match", {}).values())
        ],
        "qualified_projects": sum(
            any(tier in {"Prospect", "Lead"} for tier in row["tiers"])
            for row in present
        ),
        "projects_with_company_routes": sum(
            bool(row["contact_routes"]) for row in present
        ),
        "projects_with_named_people": sum(bool(row["named_people"]) for row in present),
        "projects_with_person_bound_methods": sum(
            any(route.get("name") for route in row["contact_routes"]) for row in present
        ),
        "verified_purchasing_authority": sum(
            any(
                route.get("purchasing_authority_verified") is True
                and route.get("authority_evidence_refs")
                for route in row["contact_routes"]
            )
            for row in present
        ),
        "purchasing_authority_outcomes": dict(
            Counter(
                route.get("purchasing_authority") or "Not established"
                for route in routes
            )
        ),
        "milestone_kinds": dict(
            Counter(row["event"]["kind"] for row in present if row["event"])
        ),
        "unique_company_routes": len({route["href"] for route in routes}),
        "current_spud_or_completion_coverage": sum(
            bool(
                row["event"]
                and row["event"]["kind"]
                in {"spud", "well_completion", "drilling_completion"}
            )
            for row in present
        ),
        "typed_permit_or_planned_milestone_projects": sum(
            bool(row["event"]) for row in present
        ),
        "supported_power_gap_projects": sum(
            row["power_summary_kind"] == "supported_gap" for row in present
        ),
        "qualified_commercial_actionability_projects": sum(
            row["power_summary_kind"] == "supported_gap"
            and bool(row["contact_routes"])
            and any(tier in {"Prospect", "Lead"} for tier in row["tiers"])
            and any(row["need_start"])
            for row in present
        ),
        "commercial_acceptance": "NOT_MET: no supported eligible 300kW temporary-power cohort; source records are Signals",
        "counts": counts,
        "read_measures": measures,
        "projects": rows,
        "outside_cohort": "OXY 0918877/0918878 same-API historical completion/recompletion does not improve frozen25 current milestone coverage",
    }
    args.output.write_text(json.dumps(result, indent=2, default=str) + "\n")
    print(
        json.dumps(
            {
                key: value
                for key, value in result.items()
                if key not in {"projects", "read_measures"}
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
