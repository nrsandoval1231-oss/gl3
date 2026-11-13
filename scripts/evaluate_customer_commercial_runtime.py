"""Evaluate retained public project sources through native offline GridLens runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FIXTURE = ROOT / "eval" / "customer-commercial-v1"
RUNTIME = FIXTURE / "runtime"
GOLD_SHA256 = "dd061c52a85b0ba05b59aab4229f5dd886bced31145fe6ab315c5ad1cda0b922"
if str(BACKEND / "src") not in sys.path:
    sys.path.insert(0, str(BACKEND / "src"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_immutable_inputs() -> dict[str, Any]:
    gold_path = FIXTURE / "reference-customers.json"
    gold_hash = sha256(gold_path)
    if gold_hash != GOLD_SHA256:
        raise ValueError(f"Reference bytes differ from immutable r2 hash: {gold_hash}")
    manifest = json.loads((FIXTURE / "source-hashes.json").read_text())
    checked = []
    for item in manifest:
        actual = sha256(FIXTURE / item["file"])
        if actual != item["sha256"]:
            raise ValueError(f"Retained source changed: {item['file']}")
        checked.append({"file": item["file"], "sha256": actual})
    return {
        "gold_sha256": gold_hash,
        "source_manifest_sha256": sha256(FIXTURE / "source-hashes.json"),
        "source_artifacts_verified": len(checked),
        "gold_used_as_runtime_input": False,
    }


def _fresh_database_url(base: URL) -> tuple[URL, str]:
    name = f"gl3_customer_runtime_{datetime.now(UTC):%Y%m%d%H%M%S}_{uuid.uuid4().hex[:8]}_test"
    return base.set(database=name), name


def _guard_database(base: URL) -> None:
    if not base.database or not base.database.endswith("_test"):
        raise ValueError(
            "TEST_DATABASE_URL must name a disposable database ending in _test"
        )
    if base.host not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("Runtime evaluation requires loopback PostgreSQL")
    application = os.environ.get("DATABASE_URL")
    if not application:
        raise ValueError("DATABASE_URL must be set to reject it as a runtime target")
    if base == make_url(application):
        raise ValueError("TEST_DATABASE_URL must differ from DATABASE_URL")


def _run_on_database(database_url: URL, name: str) -> dict[str, Any]:
    from gridlens.ingestion.adapters.retained_company_projects import (
        FAMILY,
        RETRIEVAL_METHOD,
        SOURCE_ID,
        interpret_retained_company_project,
        retained_records,
    )
    from gridlens.ingestion.service import process_records
    from fastapi.encoders import jsonable_encoder

    from gridlens.intelligence.customer_accounts import account_queue
    from gridlens.intelligence.customer_results import group_open, groups
    from gridlens.intelligence.saved_browse import rebuild
    from gridlens.persistence.browse_invalidation import install
    from gridlens.persistence.database import Base
    from gridlens.persistence.models import (
        BrowseCustomerMembership,
        BrowseGeneration,
        BuyingChainIdentityLink,
        Evidence,
        EvidencePackage,
        Interpretation,
        Job,
        PowerNeed,
        Project,
        Source,
    )

    records, held = retained_records(FIXTURE)
    for record in records:
        if interpret_retained_company_project(record) is None:
            raise ValueError(
                "Adapter emitted a record that fails fresh source revalidation"
            )
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        install(connection)
    factory = sessionmaker(engine, expire_on_commit=False)
    source_definition = {
        "id": SOURCE_ID,
        "publisher": "retained offline public documents",
        "endpoint": "https://offline.invalid/retained",
        "family": FAMILY,
        "geography": "United States",
        "industries": ["data centers"],
        "retrieval_method": RETRIEVAL_METHOD,
        "cadence_hours": 24,
        "enabled": False,
        "registry_enabled": False,
    }
    worker = "retained-company-runtime-evaluator"
    try:
        with factory.begin() as session:
            session.add(Source(**source_definition))
            session.flush()
            job = Job(
                source_id=SOURCE_ID,
                status="running",
                lease_owner=worker,
                fence=1,
                lease_until=datetime.now(UTC) + timedelta(minutes=10),
            )
            session.add(job)
            session.flush()
            job_id = job.id
        with factory() as session:
            ingestion = process_records(
                session,
                job_id,
                worker,
                1,
                source_definition,
                records,
                allow_model=False,
            )

        from gridlens.intelligence.buying_chain import enrich_buying_chain

        with factory.begin() as session:
            projects = session.scalars(select(Project).order_by(Project.name)).all()
            evidence_rows = session.scalars(
                select(Evidence).order_by(Evidence.url)
            ).all()
            for project in projects:
                linked = next(
                    (row for row in evidence_rows if row.url in project.name), None
                )
                if linked is None:
                    linked = next(
                        (
                            row
                            for row in evidence_rows
                            if row.provenance.get("retained_company_project", {}).get(
                                "project_name"
                            )
                            == project.name
                        ),
                        None,
                    )
                if linked is not None:
                    enrich_buying_chain(
                        session,
                        project.id,
                        retained_only=True,
                        retained_target_evidence_id=linked.id,
                    )

        browse = rebuild(factory)
        if browse.get("status") != "published":
            raise RuntimeError(
                f"Native saved browse generation did not publish: {browse}"
            )

        with factory() as session:
            projects = session.scalars(select(Project).order_by(Project.name)).all()
            needs = session.scalars(select(PowerNeed).order_by(PowerNeed.id)).all()
            evidence_rows = session.scalars(
                select(Evidence).order_by(Evidence.url)
            ).all()
            interpretations = session.scalars(select(Interpretation)).all()
            packages = session.scalars(select(EvidencePackage)).all()
            company_links = session.scalars(
                select(BuyingChainIdentityLink).where(
                    BuyingChainIdentityLink.entity_type == "company",
                    BuyingChainIdentityLink.state == "current",
                )
            ).all()
            generation = session.get(BrowseGeneration, browse["generation_id"])
            assert generation is not None
            browse_accounts = session.scalar(
                select(func.count())
                .select_from(BrowseCustomerMembership)
                .where(BrowseCustomerMembership.generation_id == generation.id)
            )
            account_page = account_queue(session, search=None, limit=25, offset=0)
            account_rows = account_page.get("items", [])
            ordinary_group_page = groups(
                session,
                sector="data_centers",
                sort="priority",
                limit=25,
                offset=0,
                shortlist=False,
            )
            shortlist_group_page = groups(
                session,
                sector="data_centers",
                sort="priority",
                limit=25,
                offset=0,
                shortlist=True,
            )
            ui_group = next(
                iter(shortlist_group_page["items"] or ordinary_group_page["items"]),
                None,
            )
            opened_group = (
                group_open(
                    session,
                    ui_group["id"],
                    sector="data_centers",
                    sort="priority",
                    limit=25,
                    shortlist=bool(shortlist_group_page["items"]),
                )
                if ui_group
                else None
            )
            fact_packages = [
                {
                    "url": evidence.url,
                    "capacity_claims": [
                        {
                            "value_mw": claim.get("value_mw"),
                            "basis": claim.get("basis"),
                            "qualifier": claim.get("qualifier"),
                            "scope_id": claim.get("scope_id"),
                            "phase_id": claim.get("phase_id"),
                            "quote": claim.get("quote"),
                        }
                        for claim in package.payload.get("capacity_claims", [])
                    ],
                    "timeline_claims": [
                        {
                            "event_type": claim.get("event_type"),
                            "label": claim.get("label"),
                            "precision": claim.get("precision"),
                            "quote": claim.get("quote"),
                        }
                        for claim in package.payload.get("timeline_claims", [])
                    ],
                    "commissioning_inputs": len(
                        package.payload.get("commissioning_inputs", [])
                    ),
                    "required_mw": None,
                }
                for package in packages
                for evidence in evidence_rows
                if evidence.id == package.evidence_id
            ]
            return {
                "disposable_database": name,
                "source_admission": {
                    "candidate_records": len(records),
                    "held_documents": len(held),
                    "native_signals": ingestion["signals"],
                    "retrieved_records": ingestion["retrieved_records"],
                    "accepted_source_records": [
                        {
                            "source_url": record["html_url"],
                            "source_hash": record["source_hash"],
                            "source_files": record["retained_company_project"][
                                "source_files"
                            ],
                            "publication_date": record["publication_date"],
                            "project_name": record["retained_company_project"][
                                "project_name"
                            ],
                            "project_location": record["retained_company_project"][
                                "project_location"
                            ],
                            "activity_key": record["retained_company_project"][
                                "activity_key"
                            ],
                            "activity_quote": record["retained_company_project"][
                                "activity_quote"
                            ],
                            "phase": record["retained_company_project"]["phase"],
                            "building_id": record["retained_company_project"][
                                "building_id"
                            ],
                            "project_aliases": record["retained_company_project"][
                                "project_aliases"
                            ],
                            "alias_spans": record["retained_company_project"][
                                "alias_spans"
                            ],
                        }
                        for record in records
                    ],
                    "hold_receipts": [
                        {
                            "source_url": item.get("source_url"),
                            "source_files": item.get("source_files"),
                            "reason": item.get("reason"),
                        }
                        for item in held
                    ],
                    "hold_reasons": [item.get("reason") for item in held],
                },
                "native_runtime": {
                    "project_rows": len(projects),
                    "projects": [
                        {
                            "source_id": project.source_id,
                            "name": project.name,
                            "location": project.location,
                            "region_status": project.region_status,
                            "region_state": project.region_state,
                            "power_need_count": sum(
                                need.project_id == project.id for need in needs
                            ),
                        }
                        for project in projects
                    ],
                    "power_need_rows": len(needs),
                    "needs_with_unknown_mw": sum(
                        need.required_mw is None for need in needs
                    ),
                    "evidence_rows": len(evidence_rows),
                    "accepted_interpretations": sum(
                        item.status == "accepted"
                        and isinstance(item.assessment, dict)
                        and item.assessment.get("decision") == "accepted"
                        for item in interpretations
                    ),
                    "source_backed_fact_packages": fact_packages,
                    "saved_browse_generation": {
                        "status": browse["status"],
                        "generation_id": browse["generation_id"],
                        "rows": browse["row_count"],
                    },
                    "account_projection": {
                        "browse_membership_rows": browse_accounts,
                        "account_api_rows": len(account_rows),
                        "account_cards": [
                            {
                                "name": row["name"],
                                "aliases": row["aliases"],
                                "project_count": row["project_count"],
                                "need_count": row["need_count"],
                                "supporting_evidence_count": row[
                                    "supporting_evidence_count"
                                ],
                                "highest_priority_need": (
                                    {
                                        "project_title": row[
                                            "highest_priority_need"
                                        ].get("project_title"),
                                        "location": row["highest_priority_need"].get(
                                            "location"
                                        ),
                                        "qualification_tier": row[
                                            "highest_priority_need"
                                        ].get("tier"),
                                        "required_mw": row["highest_priority_need"].get(
                                            "required_mw"
                                        ),
                                        "commercial_disposition": row[
                                            "highest_priority_need"
                                        ].get("commercial_disposition"),
                                        "next_action": row["highest_priority_need"].get(
                                            "commercial_next_action"
                                        ),
                                    }
                                    if row.get("highest_priority_need")
                                    else None
                                ),
                                "contact_state": "unavailable_unverified",
                            }
                            for row in account_rows
                        ],
                    },
                    "customer_results_ui": {
                        "api_payloads": jsonable_encoder(
                            {
                                "ordinary_groups": ordinary_group_page,
                                "shortlist_groups": shortlist_group_page,
                                "opened_group": opened_group,
                            }
                        ),
                        "sector": "data_centers",
                        "ordinary_groups": {
                            "total": ordinary_group_page["total"],
                            "items": [
                                {
                                    "id": item["id"],
                                    "name": item["name"],
                                    "role": item["role"],
                                    "group_kind": item["group_kind"],
                                    "identity_count": item["identity_count"],
                                    "project_count": item["project_count"],
                                    "relevant_project_count": item[
                                        "relevant_project_count"
                                    ],
                                    "eligible_need_count": item["eligible_need_count"],
                                    "priority_score": item["priority_score"],
                                }
                                for item in ordinary_group_page["items"]
                            ],
                        },
                        "shortlist_groups": {
                            "total": shortlist_group_page["total"],
                            "items": [
                                {
                                    "id": item["id"],
                                    "name": item["name"],
                                    "role": item["role"],
                                    "group_kind": item["group_kind"],
                                    "identity_count": item["identity_count"],
                                    "project_count": item["project_count"],
                                    "relevant_project_count": item[
                                        "relevant_project_count"
                                    ],
                                    "eligible_need_count": item["eligible_need_count"],
                                    "priority_score": item["priority_score"],
                                    "featured_project": (
                                        {
                                            "name": item["featured_project"].get(
                                                "name"
                                            ),
                                            "location": item["featured_project"].get(
                                                "location"
                                            ),
                                            "required_mw": item["featured_project"].get(
                                                "required_mw"
                                            ),
                                        }
                                        if item.get("featured_project")
                                        else None
                                    ),
                                }
                                for item in shortlist_group_page["items"]
                            ],
                        },
                        "opened_group": (
                            {
                                "id": opened_group["group"]["id"],
                                "name": opened_group["group"]["name"],
                                "role": opened_group["group"]["role"],
                                "group_kind": opened_group["group"]["group_kind"],
                                "eligible_need_count": opened_group["group"][
                                    "eligible_need_count"
                                ],
                                "projects": [
                                    {
                                        "name": item.get("name"),
                                        "location": item.get("location"),
                                        "required_mw": item.get("required_mw"),
                                        "qualification_tier": item.get("tier"),
                                    }
                                    for item in opened_group["projects"]["items"]
                                ],
                            }
                            if opened_group
                            else None
                        ),
                        "opened_group_source": (
                            "shortlist"
                            if shortlist_group_page["items"]
                            else "ordinary_groups"
                            if ordinary_group_page["items"]
                            else None
                        ),
                    },
                    "current_project_scoped_company_links": len(company_links),
                },
                "evaluation_limits": {
                    "identity_accuracy": "not_measured; reference labels were never seeded",
                    "cross_customer_grouping": "not_measured; no independently proven global IDs",
                    "contacts": "unavailable_unverified; no current contact evidence was acquired",
                    "dedupe": "only native ingestion replay keys observed; no identity oracle",
                    "portfolio_mw_rollup": (
                        "not_evaluated; source MW facts do not populate required_mw"
                    ),
                    "ranking_usefulness": (
                        "not_evaluated; browse generation publication is plumbing only"
                    ),
                },
            }
    finally:
        engine.dispose()


def run(database_url: str, output: Path) -> dict[str, Any]:
    if output.exists():
        raise ValueError(f"Refusing to overwrite runtime evaluation receipt: {output}")
    from gridlens.persistence.database import Base  # noqa: F401

    immutable = verify_immutable_inputs()
    base = make_url(database_url)
    _guard_database(base)
    target, target_name = _fresh_database_url(base)
    admin_url = base.set(database="postgres")
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    created = False
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{target_name}"'))
            created = True
        runtime = _run_on_database(target, target_name)
        result = {
            "schema_version": "gridlens-customer-commercial-runtime-v2",
            "captured_at": datetime.now(UTC).isoformat(),
            "immutable_inputs": immutable,
            "runtime": runtime,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
        return result
    finally:
        admin.dispose()
        if created:
            cleanup = create_engine(admin_url, isolation_level="AUTOCOMMIT")
            try:
                with cleanup.connect() as connection:
                    connection.execute(
                        text(f'DROP DATABASE "{target_name}" WITH (FORCE)')
                    )
            finally:
                cleanup.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("TEST_DATABASE_URL"),
        help="Loopback PostgreSQL URL for a base database ending in _test",
    )
    parser.add_argument("--output", type=Path, default=RUNTIME / "latest.json")
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or TEST_DATABASE_URL is required")
    result = run(args.database_url, args.output)
    print(json.dumps(result["runtime"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
