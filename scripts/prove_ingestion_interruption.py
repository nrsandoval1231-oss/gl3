"""Crash/restart proof against an explicitly isolated, fresh local recovery DB.

The interrupt stage exits immediately after the first actual evidence commit.
The resume stage simulates lease expiry in that disposable DB, then uses the
ordinary fenced worker. Replay performs another real source check.
"""

import argparse
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from dotenv import dotenv_values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("interrupt", "resume", "replay"))
    parser.add_argument("--env", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for key, value in dotenv_values(args.env).items():
        if value is not None:
            os.environ[key] = value
    for key in ("OPENAI_API_KEY", "TYPESAFE_API_KEY", "FIRECRAWL_API_KEY"):
        os.environ.pop(key, None)
    from sqlalchemy import event, func, select
    from sqlalchemy.engine import make_url

    from gridlens.ingestion.registry import load_registry
    from gridlens.jobs.worker import run_one, sync_registry
    from gridlens.persistence.database import SessionLocal
    from gridlens.persistence.models import (
        Evidence,
        Job,
        Observation,
        PowerNeed,
        Project,
    )
    from gridlens.settings import settings

    target = make_url(settings.database_url)
    if (
        target.host != "127.0.0.1"
        or not target.database
        or not target.database.endswith("_recovery_app")
    ):
        raise RuntimeError(
            "Refusing interruption outside disposable loopback *_recovery_app"
        )
    args.output.mkdir(parents=True, exist_ok=True)
    marker = args.output / "interrupted-job.json"
    definitions = {item["id"]: item for item in load_registry()}
    source_id = "texas-tceq-nsr-pending"
    sync_registry()

    def counts():
        with SessionLocal() as session:
            return {
                model.__tablename__: session.scalar(
                    select(func.count()).select_from(model)
                )
                for model in (Observation, Evidence, Project, PowerNeed)
            }

    before = counts()
    if args.stage == "interrupt" and any(before.values()):
        raise RuntimeError("Interrupt proof requires a fresh empty recovery DB")
    with SessionLocal.begin() as session:
        if args.stage == "resume":
            job_id = UUID(json.loads(marker.read_text())["job_id"])
            job = session.get(Job, job_id)
            assert job.status == "running" and job.fence == 1
            job.lease_until = datetime.now(UTC) - timedelta(seconds=1)
        else:
            replay_receipt = args.output / "replay.json"
            previous = (
                json.loads(replay_receipt.read_text())
                if replay_receipt.exists()
                else None
            )
            if args.stage == "replay" and previous and previous["status"] == "queued":
                job = session.get(Job, UUID(previous["job_id"]))
                assert job is not None and job.status == "queued" and job.attempts == 0
            else:
                job = Job(
                    source_id=source_id,
                    available_at=datetime.now(UTC) - timedelta(seconds=1),
                )
                session.add(job)
            session.flush()
            job_id = job.id
    if args.stage == "interrupt":
        marker.write_text(
            json.dumps(
                {
                    "job_id": str(job_id),
                    "before": before,
                    "status": "AWAITING_FIRST_EVIDENCE_COMMIT",
                },
                indent=2,
            )
        )

        @event.listens_for(SessionLocal, "after_flush")
        def saw_evidence(session, unused):
            if any(isinstance(row, Evidence) for row in session.new):
                session.info["crash_after_evidence"] = True

        @event.listens_for(SessionLocal, "after_commit")
        def crash(session):
            if session.info.pop("crash_after_evidence", False):
                marker.write_text(
                    json.dumps(
                        {
                            "job_id": str(job_id),
                            "before": before,
                            "status": "EXIT_AFTER_REAL_EVIDENCE_COMMIT",
                            "at": datetime.now(UTC).isoformat(),
                        },
                        indent=2,
                    )
                )
                os._exit(77)

    attempted = run_one(definitions, job_ids=[job_id])
    with SessionLocal() as session:
        job = session.get(Job, job_id)
        state = {
            "attempted": attempted,
            "job_id": str(job.id),
            "status": job.status,
            "fence": job.fence,
            "attempts": job.attempts,
            "error": job.error,
        }
    state.update(before=before, after=counts())
    (args.output / f"{args.stage}.json").write_text(
        json.dumps(state, default=str, indent=2)
    )
    print(json.dumps(state))
    if state["status"] != "succeeded":
        raise SystemExit(1)
    if args.stage == "replay" and state["before"] != state["after"]:
        raise SystemExit(
            "Replay changed durable counts; inspect versions before acceptance"
        )


if __name__ == "__main__":
    main()
