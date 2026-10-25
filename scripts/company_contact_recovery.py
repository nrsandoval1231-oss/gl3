"""Bounded retained-contact recovery and explicit-denominator coverage.

Default is read-only. Apply queues existing retained-evidence jobs only: no web
crawl or paid provider. Cursor = (tier priority, project UUID); preserve the
reported cursor for the next page. Coverage is over current eligible accounts,
not a sample of opportunity rows. Run with an otherwise idle local/test worker.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))
from backfill_retained_buying_chain import _database_session_factory  # noqa: E402
from sqlalchemy import case, func, select  # noqa: E402

from gridlens.intelligence.buying_chain import (  # noqa: E402
    _retained,
    enqueue_retained_buying_chain_research,
)
from gridlens.intelligence.company_contacts import (
    company_contacts,
    relevant_named_contact,
)  # noqa: E402
from gridlens.intelligence.customer_accounts import _current_customer_claims  # noqa: E402
from gridlens.persistence.models import PowerNeed, Project  # noqa: E402


def coverage(session):
    eligible = dict(
        session.execute(
            select(Project.id, func.array_agg(PowerNeed.tier))
            .join(PowerNeed, PowerNeed.project_id == Project.id)
            .where(Project.region_status == "ELIGIBLE", PowerNeed.active.is_(True))
            .group_by(Project.id)
        ).all()
    )
    companies = {}
    for company, project, _ in _current_customer_claims(
        session, project_ids=set(eligible)
    ):
        companies.setdefault(company, set()).update(eligible[project])
    rows = []
    for company, tiers in companies.items():
        result = company_contacts(session, company)
        methods = [m for c in result.contacts for m in c.methods]
        named = any(relevant_named_contact(c) for c in result.contacts)
        rows.append(
            dict(
                company_id=str(company),
                tiers=sorted(tiers),
                verified_work_email=any(m["kind"] == "email" for m in methods),
                verified_business_phone=any(
                    m["kind"] in {"phone", "telephone"} for m in methods
                ),
                named_relevant_buyer=named,
                generic_only=bool(methods) and not named,
                research_required=result.research_required,
            )
        )

    def summarize(items):
        denominator = len(items)
        return {
            "eligible_companies": denominator,
            "metrics": {
                key: {
                    "count": sum(r[key] for r in items),
                    "denominator": denominator,
                    "percent": round(100 * sum(r[key] for r in items) / denominator, 2)
                    if denominator
                    else None,
                }
                for key in (
                    "verified_work_email",
                    "verified_business_phone",
                    "named_relevant_buyer",
                    "generic_only",
                    "research_required",
                )
            },
        }

    return {
        "scope": "Active region-eligible company identities with current customer claims; not the saved visible browse cohort",
        "unresolved_project_count": len(
            set(eligible)
            - {
                p
                for _, p, _ in _current_customer_claims(
                    session, project_ids=set(eligible)
                )
            }
        ),
        "overall": summarize(rows),
        "by_tier": {
            tier: summarize([r for r in rows if tier in r["tiers"]])
            for tier in ("Lead", "Prospect", "Signal")
        },
        "notes": [
            "Source verified does not mean deliverability or call reachability tested.",
            "Named relevant buyer means sourced role; purchasing authority unconfirmed.",
            "Companies can occur in multiple tiers; tier denominators are distinct companies.",
            "Zero denominator percentages are null, never 0%.",
        ],
        "companies": rows,
    }


def recover(session, *, limit, cursor=None, apply=False):
    priority = func.min(
        case((PowerNeed.tier == "Lead", 0), (PowerNeed.tier == "Prospect", 1), else_=2)
    ).label("priority")
    scope = (
        select(Project.id.label("project_id"), priority)
        .join(PowerNeed, PowerNeed.project_id == Project.id)
        .where(Project.region_status == "ELIGIBLE", PowerNeed.active.is_(True))
        .group_by(Project.id)
        .subquery()
    )
    query = select(scope).order_by(scope.c.priority, scope.c.project_id).limit(limit)
    if cursor:
        rank, project_id = cursor.split(":", 1)
        query = query.where(
            (scope.c.priority > int(rank))
            | (
                (scope.c.priority == int(rank))
                & (scope.c.project_id > UUID(project_id))
            )
        )
    rows = session.execute(query).all()
    outcomes = []
    for project_id, rank in rows:
        project = session.get(Project, project_id)
        evidence = next(iter(_retained(session, project)), None)
        job = (
            enqueue_retained_buying_chain_research(
                session, project_id, evidence.id, evidence.content_hash
            )
            if apply and evidence
            else None
        )
        outcomes.append(
            {
                "project_id": str(project_id),
                "priority": rank,
                "status": job.status
                if job
                else "planned"
                if evidence
                else "research_required",
                "job_id": str(job.id) if job else None,
            }
        )
    return {
        "scanned": len(rows),
        "limit": limit,
        "outcomes": outcomes,
        "next_cursor": f"{rows[-1][1]}:{rows[-1][0]}" if rows else None,
        "provider_requests": 0,
        "provider_cost_usd": "0.00",
        "failure_rate": None,
        "failure_rate_denominator": 0,
        "failure_rate_note": "This command plans/enqueues; job completion is not asserted.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-target", choices=("test", "application"), default="test"
    )
    parser.add_argument("--expected-database-name")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--cursor")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--coverage", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.limit <= 100:
        parser.error("--limit must be 1..100")
    if args.apply and not args.expected_database_name:
        parser.error("--apply requires --expected-database-name")
    engine, factory = _database_session_factory(
        args.database_target, args.expected_database_name
    )
    try:
        with factory.begin() as session:
            report = recover(
                session, limit=args.limit, cursor=args.cursor, apply=args.apply
            )
            if args.coverage:
                report["coverage"] = coverage(session)
            report["mode"] = "enqueue" if args.apply else "read-only"
        print(json.dumps(report, indent=2))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
