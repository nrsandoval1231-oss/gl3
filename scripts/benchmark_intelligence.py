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


def benchmark(session, *, limit: int = 25) -> dict:
    from gridlens.intelligence.company_contacts import company_contacts, relevant_named_contact
    from gridlens.intelligence.company_graph import company_graph
    from gridlens.intelligence.customer_accounts import _current_customer_claims
    from gridlens.intelligence.project_enrichment import project_power_enrichment
    from gridlens.persistence.models import BrowseGeneration, BrowseRow, PowerNeed, Project
    from sqlalchemy import select

    started = time.monotonic()
    generation = session.scalar(
        select(BrowseGeneration).order_by(BrowseGeneration.built_at.desc()).limit(1)
    )
    query = select(Project).where(
        Project.region_status == "ELIGIBLE",
        select(PowerNeed.id)
        .where(PowerNeed.project_id == Project.id, PowerNeed.active.is_(True))
        .exists(),
    )
    if generation:
        query = (
            query.join(BrowseRow, BrowseRow.project_id == Project.id)
            .where(BrowseRow.generation_id == generation.id)
            .order_by(BrowseRow.rank_score.desc(), Project.id)
        )
    else:
        query = query.order_by(Project.id)
    projects = list(session.scalars(query.limit(limit)).unique())
    identities: dict = {}
    for identity_id, project_id, _claim in _current_customer_claims(
        session, project_ids={p.id for p in projects}
    ):
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
    return {
        "kind": "retained_evidence_existing_project_benchmark",
        "measured_at": datetime.now(UTC).isoformat(),
        "selection": "latest browse priority descending, stable project UUID tiebreak"
        if generation
        else "no browse priority available; stable eligible project UUID order",
        "requested_projects": limit,
        "projects_measured": count,
        "unique_companies": len(company_cache),
        "company_identity_coverage": sum(r["company_identity_resolved"] for r in rows),
        "published_contact_coverage": sum(r["published_method_count"] > 0 for r in rows),
        "relevant_named_contact_coverage": sum(r["relevant_named_contact"] for r in rows),
        "independently_verified_mailbox_coverage": "UNKNOWN",
        "company_match_accuracy": "UNKNOWN: requires independent labels",
        "project_match_accuracy": "UNKNOWN: requires independent labels",
        "false_positive_contact_matches": "UNKNOWN: requires independent adjudication",
        "commercial_actionability": "Recommended actions supplied; sales outcome unmeasured",
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
    engine = create_engine(url)
    try:
        with Session(engine) as session:
            session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            from sqlalchemy import text

            session.execute(text("SET TRANSACTION READ ONLY"))
            result = benchmark(session)
    finally:
        engine.dispose()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Measured {result['projects_measured']} existing projects; report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
