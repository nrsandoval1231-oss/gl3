"""Run selected existing sources through the real fenced worker in a local clone.

Requires explicit loopback *_app database and no paid-provider credentials. Each
selected source gets a scoped job; inherited jobs and operator switches are left
untouched. Receipts are private local JSON, never proof of production deployment.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dotenv import dotenv_values


def configure(args):
    for key, value in dotenv_values(args.env).items():
        if value is not None:
            os.environ[key] = value
    for key in ("OPENAI_API_KEY", "TYPESAFE_API_KEY", "FIRECRAWL_API_KEY"):
        os.environ.pop(key, None)
    os.environ["WORKER_AUTO_REFRESH"] = "false"
    sys.path.insert(0, str(args.root.resolve() / "backend" / "src"))


def run_source(source_id, *, resume_job_id=None):
    from sqlalchemy import func, select
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
        Source,
    )
    from gridlens.settings import settings

    target = make_url(settings.database_url)
    if (
        target.host != "127.0.0.1"
        or not target.database
        or not target.database.endswith("_app")
    ):
        raise RuntimeError("Live proof requires a disposable loopback *_app database")
    definitions = {item["id"]: item for item in load_registry()}
    if not definitions.get(source_id, {}).get("enabled"):
        raise ValueError("Select an existing enabled source")
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
    with SessionLocal.begin() as session:
        if resume_job_id is not None:
            from uuid import UUID

            job = session.get(Job, UUID(resume_job_id))
            resumable = job is not None and (
                job.status == "queued"
                or (
                    job.status == "running"
                    and job.lease_until is not None
                    and job.lease_until < datetime.now(UTC)
                )
            )
            if not resumable or job.source_id != source_id:
                raise ValueError(
                    "Only a known queued or expired verification job can resume"
                )
        else:
            # Avoid a sub-millisecond DB/application clock skew leaving this
            # newly created proof job ineligible for its immediate scoped lease.
            job = Job(
                source_id=source_id,
                available_at=datetime.now(UTC) - timedelta(seconds=1),
            )
            session.add(job)
        session.flush()
        job_id = job.id
    start = time.perf_counter()
    attempted = run_one(definitions, job_ids=[job_id])
    duration = time.perf_counter() - start
    after = counts()
    with SessionLocal() as session:
        job = session.get(Job, job_id)
        source = session.get(Source, source_id)
        result = {
            "source_id": source_id,
            "attempted": attempted,
            "job_id": str(job_id),
            "status": job.status,
            "attempts": job.attempts,
            "error": job.error,
            "checkpoint": job.checkpoint,
            "health": source.health,
        }
    result.update(
        captured_at=datetime.now(UTC).isoformat(),
        elapsed_seconds=duration,
        counts_before=before,
        counts_after=after,
        retained_delta={key: after[key] - before[key] for key in before},
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--env", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", action="append")
    parser.add_argument("--one")
    parser.add_argument(
        "--resume-job", help="Resume a known queued or expired local proof job"
    )
    args = parser.parse_args()
    configure(args)
    args.output.mkdir(parents=True, exist_ok=True)
    if args.one:
        receipt = args.output / f"{args.one}.json"
        previous = json.loads(receipt.read_text()) if receipt.exists() else None
        resume = args.resume_job or (
            previous["job_id"] if previous and previous["status"] == "queued" else None
        )
        if previous:
            receipt.with_suffix(".previous.json").write_text(
                json.dumps(previous, indent=2)
            )
        result = run_source(args.one, resume_job_id=resume)
        receipt.write_text(json.dumps(result, default=str, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    key: result[key]
                    for key in (
                        "source_id",
                        "status",
                        "error",
                        "elapsed_seconds",
                        "retained_delta",
                    )
                }
            )
        )
        return
    from gridlens.ingestion.registry import load_registry

    selected = args.source or [
        item["id"] for item in load_registry() if item["enabled"]
    ]
    for source_id in selected:
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--root",
            str(args.root.resolve()),
            "--env",
            str(args.env.resolve()),
            "--output",
            str(args.output.resolve()),
            "--one",
            source_id,
        ]
        start = time.perf_counter()
        try:
            process = subprocess.run(
                command, capture_output=True, text=True, timeout=660
            )
            print(process.stdout.strip(), flush=True)
            if process.returncode:
                # Preserve diagnostics privately; don't echo possible SQL data.
                (args.output / f"{source_id}.failure.txt").write_text(
                    process.stderr, encoding="utf-8"
                )
                print(
                    json.dumps(
                        {"source_id": source_id, "exit_code": process.returncode}
                    ),
                    flush=True,
                )
        except subprocess.TimeoutExpired:
            (args.output / f"{source_id}.interrupted.json").write_text(
                json.dumps(
                    {
                        "status": "UNKNOWN",
                        "reason": "verification_process_deadline",
                        "elapsed_seconds": time.perf_counter() - start,
                    }
                ),
                encoding="utf-8",
            )
            raise SystemExit(
                "Interrupted effects retained as UNKNOWN; inspect before resuming"
            ) from None


if __name__ == "__main__":
    main()
