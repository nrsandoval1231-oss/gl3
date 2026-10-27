"""Replay actual captured native records into an empty, isolated local database.

This is source-capture replay, not a live ingestion or commercial qualification
claim. No network, model, paid-provider or production execution is permitted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rrc", type=Path, required=True)
    parser.add_argument("--tdlr", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    from sqlalchemy import func, select
    from sqlalchemy.engine import make_url

    from gridlens.ingestion import adapters, service
    from gridlens.jobs.queue import enqueue
    from gridlens.jobs.worker import run_one, sync_registry
    from gridlens.persistence.database import SessionLocal
    from gridlens.persistence.models import (
        Evidence,
        Job,
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
        raise RuntimeError(
            "Requires the exact isolated loopback gridlens_issue128_local database"
        )
    if args.receipt.exists():
        raise RuntimeError("Refusing to overwrite a replay receipt")
    settings.openai_api_key = settings.typesafe_api_key = settings.firecrawl_api_key = (
        None
    )
    settings.autonomous_research_enabled = False
    settings.buying_chain_public_research_enabled = False
    settings.company_contact_discovery_enabled = False
    settings.worker_auto_refresh = False
    settings.saved_browse_enabled = False
    records = {
        "texas-rrc-drilling-permits": json.loads(args.rrc.read_text()),
        "texas-tdlr-tabs-data-centers": json.loads(args.tdlr.read_text()),
    }
    with SessionLocal() as session:
        if session.scalar(select(func.count()).select_from(Observation)):
            raise RuntimeError("Capture replay requires an empty database")
    definitions = {row["id"]: row for row in sync_registry()}

    def captured(source, *_args, **_kwargs):
        if source["id"] not in records:
            raise RuntimeError("No capture for requested source")
        return records[source["id"]]

    # Replace transport only: the normal parser/admission/evidence/worker path
    # receives the exact capture bytes/fields, without fabricated business facts.
    service.retrieve_source = adapters.retrieve_source = captured
    jobs = []
    for source_id in records:
        with SessionLocal.begin() as session:
            job_id = enqueue(session, source_id)
        run_one(definitions, job_ids=[job_id])
        with SessionLocal() as session:
            job = session.get(Job, job_id)
            jobs.append(
                {"source_id": source_id, "status": job.status, "error": job.error}
            )
            if job.status != "succeeded":
                raise RuntimeError(
                    f"Capture ingestion failed: {source_id}: {job.error}"
                )
    with SessionLocal() as session:
        retained_jobs = [
            row.id
            for row in session.scalars(
                select(Job).where(Job.kind == "buying_chain_research")
            )
            if json.loads(row.checkpoint or "{}").get("task_type")
            == "buying_chain_retained"
        ]
    for job_id in retained_jobs:
        run_one(definitions, job_ids=[job_id])
    with SessionLocal() as session:
        counts = {
            model.__tablename__: session.scalar(select(func.count()).select_from(model))
            for model in (Project, PowerNeed, Evidence, Observation, LogicalCall)
        }
        outcomes = dict(
            session.execute(select(Job.status, func.count()).group_by(Job.status)).all()
        )
    receipt = {
        "kind": "actual_native_source_capture_replay",
        "measured_at": datetime.now(UTC).isoformat(),
        "scope": "isolated local database; no production or live-worker acceptance",
        "inputs": {
            source: {
                "records": len(records[source]),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for source, path in (
                ("texas-rrc-drilling-permits", args.rrc),
                ("texas-tdlr-tabs-data-centers", args.tdlr),
            )
        },
        "ingestion_jobs": jobs,
        "retained_jobs_attempted": len(retained_jobs),
        "job_outcomes": outcomes,
        "counts": counts,
        "network_requests_during_replay": 0,
        "qualification": "Signals require independent temporary-demand, power-floor and site adjudication",
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
