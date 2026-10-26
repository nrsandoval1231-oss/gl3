"""Measure a ranked existing-project cohort using retained evidence, with no paid calls.

This is a retained-evidence benchmark, not a fresh contact discovery experiment or
an independently adjudicated identity-accuracy measurement.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))


def select_projects(session, *, limit: int = 25):
    """Select distinct projects from the currently usable published generation."""
    from fastapi import HTTPException
    from sqlalchemy import func, select

    from gridlens.intelligence.saved_browse import current_generation
    from gridlens.persistence.models import BrowseRow, PowerNeed, Project

    if not 1 <= limit <= 100:
        raise ValueError("Benchmark limit must be between 1 and 100")
    try:
        generation = current_generation(session)
    except HTTPException as exc:
        if exc.status_code != 503:
            raise
        return [], None, "QUALIFICATION_PENDING"
    ranked = (
        select(BrowseRow.project_id, func.max(BrowseRow.rank_score).label("rank_score"))
        .where(BrowseRow.generation_id == generation.id)
        .group_by(BrowseRow.project_id)
        .subquery()
    )
    query = (
        select(Project)
        .join(ranked, ranked.c.project_id == Project.id)
        .where(
            Project.region_status == "ELIGIBLE",
            select(PowerNeed.id)
            .where(PowerNeed.project_id == Project.id, PowerNeed.active.is_(True))
            .exists(),
        )
        .order_by(ranked.c.rank_score.desc(), Project.id)
        .limit(limit)
    )
    return list(session.scalars(query)), generation.id, "CURRENT"


def benchmark(
    session,
    *,
    limit: int = 25,
    dataset_kind: str = "unspecified",
    source_reference: str = "",
) -> dict:
    from gridlens.intelligence.company_contacts import (
        company_contacts,
        relevant_named_contact,
    )
    from gridlens.intelligence.company_graph import company_graph
    from gridlens.intelligence.customer_accounts import _current_customer_claims
    from gridlens.intelligence.project_enrichment import project_power_enrichment
    from gridlens.persistence.models import Job
    from sqlalchemy import func, select

    started = time.monotonic()
    projects, generation_id, selection_status = select_projects(session, limit=limit)
    identities: dict = {}
    claims = (
        _current_customer_claims(session, project_ids={p.id for p in projects})
        if projects
        else []
    )
    for identity_id, project_id, _claim in claims:
        identities.setdefault(project_id, set()).add(identity_id)
    rows = []
    company_cache: dict = {}
    for project in projects:
        companies = identities.get(project.id, set())
        contacts = []
        graph_evidence = 0
        for company in companies:
            if company not in company_cache:
                company_cache[company] = (
                    company_contacts(session, company),
                    company_graph(session, company),
                )
            contact_set, graph = company_cache[company]
            contacts.extend(contact_set.contacts)
            graph_evidence += len(graph.get("evidence", []))
        methods = [method for contact in contacts for method in contact.methods]
        power = project_power_enrichment(session, project.id)
        has_direct = any(relevant_named_contact(contact) for contact in contacts)
        action = (
            "Confirm project purchasing authority and power scope with the published contact"
            if has_direct
            else "Ask the published company route for the project energy or facilities buyer"
            if methods
            else "Research the canonical company and establish a published business contact route"
        )
        rows.append(
            {
                "project_id": str(project.id),
                "canonical_company_ids": sorted(str(c) for c in companies),
                "company_identity_resolved": bool(companies),
                "published_method_count": len(methods),
                "relevant_named_contact": has_direct,
                "graph_evidence_count": graph_evidence,
                "power_status": power.status if power else "NO_EVIDENCE",
                "power_scenarios": len(power.scenarios) if power else 0,
                "recommended_next_action": action,
                "buying_authority": "UNKNOWN",
            }
        )
    count = len(rows)
    outcomes = (
        dict(
            session.execute(
                select(Job.status, func.count())
                .where(
                    Job.kind == "company_contact_discovery",
                    Job.target_id.in_(company_cache),
                )
                .group_by(Job.status)
            ).all()
        )
        if company_cache
        else {}
    )
    return {
        "kind": "retained_evidence_existing_project_benchmark",
        "dataset_kind": dataset_kind,
        "source_reference": source_reference,
        "selection_status": selection_status,
        "generation_id": str(generation_id) if generation_id else None,
        "cohort_complete": count == limit,
        "commercial_acceptance": "NOT_TESTED",
        "retained_company_job_outcomes": outcomes,
        "job_outcome_note": "Historical workflow outcomes are not verified contact yield.",
        "duplicate_project_rate": "UNKNOWN: requires independent site reconciliation",
        "duplicate_company_rate": "UNKNOWN: requires independent identity reconciliation",
        "api_performance": "NOT_TESTED: processing_seconds measures local projections only",
        "measured_at": datetime.now(UTC).isoformat(),
        "selection": "current published generation; maximum need priority per distinct project, UUID tiebreak",
        "requested_projects": limit,
        "projects_measured": count,
        "unique_companies": len(company_cache),
        "company_identity_coverage": sum(r["company_identity_resolved"] for r in rows),
        "published_contact_coverage": sum(
            r["published_method_count"] > 0 for r in rows
        ),
        "relevant_named_contact_coverage": sum(
            r["relevant_named_contact"] for r in rows
        ),
        "independently_verified_mailbox_coverage": "UNKNOWN",
        "company_match_accuracy": "UNKNOWN: requires independent labels",
        "project_match_accuracy": "UNKNOWN: requires independent labels",
        "false_positive_contact_matches": "UNKNOWN: requires independent adjudication",
        "commercial_actionability": "NOT_TESTED: requires independent review of actual opportunities",
        "new_live_research_executed": False,
        "additional_provider_calls": 0,
        "additional_api_cost_usd": 0,
        "processing_seconds": round(time.monotonic() - started, 3),
        "projects": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-database-name", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--dataset-kind",
        choices=("retained", "synthetic", "local-acquisition"),
        required=True,
    )
    parser.add_argument("--source-reference", required=True)
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()
    from gridlens.settings import settings
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session

    url = make_url(settings.database_url)
    if url.host not in {"127.0.0.1", "localhost", "::1"} or (
        url.database != args.expected_database_name
    ):
        parser.error("benchmark requires an exact loopback database identity")
    if not 1 <= args.limit <= 100:
        parser.error("limit must be between 1 and 100")
    if args.output.exists():
        parser.error("Refusing to overwrite a prior benchmark receipt")
    engine = create_engine(url)
    try:
        with Session(engine) as session:
            session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            from sqlalchemy import text

            session.execute(text("SET TRANSACTION READ ONLY"))
            result = benchmark(
                session,
                limit=args.limit,
                dataset_kind=args.dataset_kind,
                source_reference=args.source_reference,
            )
    finally:
        engine.dispose()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        f"Measured {result['projects_measured']} existing projects; report: {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
