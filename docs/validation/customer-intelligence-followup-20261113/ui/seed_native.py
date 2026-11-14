from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[4]
BACKEND = ROOT / "backend"
ALLOWED_DATABASE = re.compile(r"gl3_ui_followup_(?:before|after)_[a-f0-9]{8}_test\Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed native retained sources into one disposable UI test database.")
    parser.add_argument("--mode", choices=("before", "after"), required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, default=ROOT / "eval/customer-commercial-v1")
    args = parser.parse_args()
    if not ALLOWED_DATABASE.fullmatch(args.database):
        raise SystemExit("Database must be a fresh gl3_ui_followup_{before|after}_<8hex>_test name")
    if args.manifest.exists():
        raise SystemExit("Refusing to overwrite the native UI manifest")

    base = make_url(os.environ["TEST_DATABASE_URL"])
    if base.host not in {"127.0.0.1", "localhost", "::1"} or not base.database or not base.database.endswith("_test"):
        raise SystemExit("TEST_DATABASE_URL must use loopback and a disposable *_test database name")
    application = make_url(os.environ["DATABASE_URL"])
    target = base.set(database=args.database)
    if application == target:
        raise SystemExit("The disposable test database must differ from DATABASE_URL")

    admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{args.database}"'))
    admin.dispose()

    target_text = target.render_as_string(hide_password=False)
    environment = os.environ.copy()
    environment["DATABASE_URL"] = target_text
    environment["SAVED_BROWSE_ENABLED"] = "true"
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        env=environment,
        check=True,
    )
    os.environ["DATABASE_URL"] = target_text
    if not os.environ.get("GRID_SAVED_BROWSE_OVERLAY"):
        sys.path.insert(0, str(BACKEND / "src"))

    from gridlens.ingestion.adapters.retained_company_projects import (
        FAMILY,
        RETRIEVAL_METHOD,
        SOURCE_ID,
        interpret_retained_company_project,
        retained_records,
    )
    from gridlens.ingestion.service import process_records
    from gridlens.intelligence.buying_chain import enrich_buying_chain
    from gridlens.intelligence.customer_results import groups
    from gridlens.intelligence.saved_browse import rebuild
    from gridlens.persistence.models import (
        BrowseCustomerMembership,
        Evidence,
        Job,
        PowerNeed,
        Project,
        Source,
    )

    all_records, held = retained_records(args.corpus)
    selected = [
        record
        for record in all_records
        if {"sources/databank.json", "sources/cyrusone.json"}
        & set(record["retained_company_project"]["source_files"])
    ]
    if len(selected) != 2 or any(interpret_retained_company_project(record) is None for record in selected):
        raise SystemExit("Expected the two current native DataBank/CyrusOne retained adapter records")

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
    from sqlalchemy import create_engine as engine_factory
    from sqlalchemy.orm import sessionmaker

    engine = engine_factory(target)
    factory = sessionmaker(engine, expire_on_commit=False)
    worker = "ui-followup-native-source-seeder"
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
        ingestion = process_records(session, job_id, worker, 1, source_definition, selected, allow_model=False)
    with factory.begin() as session:
        projects = session.scalars(select(Project).order_by(Project.name)).all()
        evidence_rows = session.scalars(select(Evidence).order_by(Evidence.url)).all()
        for project in projects:
            evidence = next(
                (
                    item
                    for item in evidence_rows
                    if item.provenance.get("retained_company_project", {}).get("project_name") == project.name
                ),
                None,
            )
            if evidence is not None:
                enrich_buying_chain(
                    session,
                    project.id,
                    retained_only=True,
                    retained_target_evidence_id=evidence.id,
                )

    saved_browse = rebuild(factory)
    if saved_browse.get("status") != "published":
        raise RuntimeError(f"Native retained-source browse did not publish: {saved_browse}")
    with factory() as session:
        result = groups(session, sector="data_centers", limit=25, offset=0, shortlist=False, canonical_only=True)
        if result["total"] != 2:
            raise AssertionError(f"Expected two canonical groups, got {result['total']}")
        names = {item["name"] for item in result["items"]}
        if names != {"DataBank", "CyrusOne"}:
            raise AssertionError(f"Native adapter produced unexpected account names: {sorted(names)}")
        logical_calls = session.scalar(text("SELECT count(*) FROM logical_calls"))
        projects_count = session.scalar(select(func.count()).select_from(Project))
        needs_count = session.scalar(select(func.count()).select_from(PowerNeed))
        membership_count = session.scalar(select(func.count()).select_from(BrowseCustomerMembership))
        accounts = []
        for group in result["items"]:
            intelligence = group.get("commercial_intelligence") or {}
            project = group.get("featured_project") or {}
            brief = project.get("commercial_brief") or {}
            contacts = (group.get("account_contact_project") or {}).get("contact") or []
            accounts.append(
                {
                    "name": group["name"],
                    "group_kind": group.get("group_kind"),
                    "project_count": group.get("project_count"),
                    "recent_developments": [
                        {"summary": item.get("summary"), "source_date": item.get("source_date")}
                        for item in intelligence.get("recent_developments", [])
                    ],
                    "capacity_totals": [
                        {
                            "basis": item.get("basis"),
                            "value_mw": item.get("value_mw"),
                            "status": item.get("status"),
                            "qualifier": item.get("qualifier"),
                        }
                        for item in (intelligence.get("capacity") or {}).get("totals", [])
                    ],
                    "power_amount_class": (brief.get("power_need") or {}).get("amount_class", "unknown"),
                    "permitted_contact_route_count": len(contacts),
                }
            )
    engine.dispose()

    sources = {}
    for source_name in ("databank.json", "cyrusone.json"):
        path = args.corpus / "sources" / source_name
        sources[f"eval/customer-commercial-v1/sources/{source_name}"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {
        "mode": args.mode,
        "database_name": args.database,
        "fixture": "native retained adapter + process_records + buying-chain enrichment + saved browse rebuild",
        "source_selection": ["DataBank", "CyrusOne"],
        "source_artifact_sha256": sources,
        "source_records_ingested": ingestion,
        "held_documents_in_full_fixture": len(held),
        "reference_labels_used": False,
        "provider_calls": int(logical_calls or 0),
        "project_rows": projects_count,
        "need_rows": needs_count,
        "account_memberships": membership_count,
        "generation_id": result.get("generation_id"),
        "accounts": accounts,
        "saved_browse_status": saved_browse.get("status"),
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in manifest.items() if key not in {"accounts", "source_artifact_sha256"}}))


if __name__ == "__main__":
    main()
