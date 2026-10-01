"""Inspect and recover an existing runtime without resetting data or retry backoff."""

import argparse
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, text

from gridlens.ingestion.registry import load_registry
from gridlens.jobs.queue import enqueue
from gridlens.jobs.worker import run_one, sync_registry
from gridlens.persistence.database import SessionLocal
from gridlens.persistence.models import Evidence, Job, Observation, PowerNeed, Project, Source

REGISTRY_FIELDS = (
    "publisher",
    "endpoint",
    "family",
    "geography",
    "industries",
    "retrieval_method",
    "cadence_hours",
    "enabled",
)


def inspect_runtime() -> dict[str, Any]:
    """Report registry/data readiness using an explicitly read-only transaction."""
    definitions = {item["id"]: item for item in load_registry()}
    with SessionLocal() as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        rows = {row.id: row for row in session.scalars(select(Source))}
        sources = []
        for source_id, definition in sorted(definitions.items()):
            row = rows.get(source_id)
            sources.append(
                {
                    "id": source_id,
                    "registry_enabled": definition["enabled"],
                    "persisted": row is not None,
                    "registry_drift": [
                        key
                        for key in REGISTRY_FIELDS
                        if row is not None and getattr(row, key) != definition[key]
                    ],
                    "health": row.health if row else None,
                }
            )
        return {
            "checked_at": datetime.now(UTC).isoformat(),
            "registry_sources": len(definitions),
            "registry_enabled": sum(bool(item["enabled"]) for item in definitions.values()),
            "persisted_sources": len(rows),
            "unregistered_sources": sorted(set(rows) - set(definitions)),
            "sources": sources,
            "content_counts": {
                model.__tablename__: session.scalar(select(func.count()).select_from(model))
                for model in (Observation, Evidence, Project, PowerNeed)
            },
            "jobs": {
                status: count
                for status, count in session.execute(
                    select(Job.status, func.count()).group_by(Job.status)
                )
            },
            "limitations": "Runtime data only; uptime and scheduled execution remain unverified.",
        }


def check_sources(source_ids: list[str]) -> dict[str, Any]:
    """Attempt each selected job once through the normal fenced worker.

    Existing active jobs are reused. Backoff and live leases are never shortened;
    unrelated queued or abandoned jobs are not processed by this invocation.
    """
    definitions = {item["id"]: item for item in load_registry()}
    selected = list(dict.fromkeys(source_ids))
    if not selected or any(
        source_id not in definitions or not definitions[source_id]["enabled"]
        for source_id in selected
    ):
        raise ValueError("Select at least one known enabled registry source")
    sync_registry()
    results = []
    for source_id in selected:
        with SessionLocal.begin() as session:
            job_id = enqueue(session, source_id)
        attempted = run_one(definitions, job_ids=[job_id])
        with SessionLocal() as session:
            job = session.get(Job, job_id)
            source = session.get(Source, source_id)
            assert job is not None and source is not None
            results.append(
                {
                    "source_id": source_id,
                    "job_id": str(job_id),
                    "attempted": attempted,
                    "job_status": job.status,
                    "attempts": job.attempts,
                    "available_at": job.available_at.isoformat(),
                    "health": source.health,
                }
            )
    return {
        "checks": results,
        "all_succeeded": all(
            item["attempted"] and item["job_status"] == "succeeded" for item in results
        ),
        "limitations": "One attempt per selected source; deferred retries remain queued. "
        "A successful check does not establish scheduled daily operation.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="Inspect persisted registry, health, jobs and counts")
    commands.add_parser(
        "reconcile", help="Sync versioned registry without deleting source/data rows"
    )
    check = commands.add_parser("check", help="Attempt selected sources once; honor leases/backoff")
    check.add_argument("--source", action="append", required=True)
    args = parser.parse_args()
    try:
        if args.command == "check":
            result = check_sources(args.source)
            code = 0 if result["all_succeeded"] else 1
        else:
            if args.command == "reconcile":
                sync_registry()
            result = inspect_runtime()
            code = 0
    except ValueError as exc:
        parser.error(str(exc))
    except Exception as exc:
        # Database exceptions can contain credentials or SQL parameters.
        print(
            json.dumps(
                {
                    "error": type(exc).__name__,
                    "message": "Runtime command failed; check database access and migrations.",
                }
            )
        )
        raise SystemExit(2) from None
    print(json.dumps(result, indent=2, ensure_ascii=False))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
