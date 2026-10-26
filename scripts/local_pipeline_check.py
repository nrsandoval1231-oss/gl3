"""Run real enabled sources through the ordinary worker on a fresh isolated database."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from gridlens.jobs.queue import enqueue  # noqa: E402
from gridlens.jobs.worker import run_one, sync_registry  # noqa: E402
from gridlens.persistence.database import SessionLocal  # noqa: E402
from gridlens.persistence.models import (  # noqa: E402
    ChangeEvent,
    Evidence,
    Interpretation,
    Job,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Source,
)
from gridlens.settings import settings  # noqa: E402

CONTENT_MODELS = {
    "observations": Observation,
    "evidence": Evidence,
    "projects": Project,
    "needs": PowerNeed,
    "need_observations": NeedObservation,
    "changes": ChangeEvent,
    "interpretations": Interpretation,
}
OPERATIONAL_INTERPRETATION_FIELDS = {"attempts", "updated_at"}


def _json_value(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def _digest_rows(table_name: str, rows: list[dict[str, Any]]) -> dict[str, str]:
    operational_encoded = json.dumps(
        rows, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    semantic_rows = rows
    if table_name == "interpretations":
        semantic_rows = [
            {
                key: value
                for key, value in row.items()
                if key not in OPERATIONAL_INTERPRETATION_FIELDS
            }
            for row in rows
        ]
    semantic_encoded = json.dumps(
        semantic_rows, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return {
        "sha256": hashlib.sha256(semantic_encoded.encode()).hexdigest(),
        "operational_sha256": hashlib.sha256(operational_encoded.encode()).hexdigest(),
    }


def _content_snapshot_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return left.keys() == right.keys() and all(
        left[name]["count"] == right[name]["count"]
        and left[name]["sha256"] == right[name]["sha256"]
        for name in left
    )


def _operational_snapshot_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return left.keys() == right.keys() and all(
        left[name]["operational_sha256"] == right[name]["operational_sha256"]
        for name in left
    )


def _successful_job(item: dict[str, Any]) -> bool:
    return (
        item.get("attempted") is True
        and item.get("job_status") == "succeeded"
        and item.get("failed_jobs") == 0
        and item.get("failed_interpretations") == 0
        and item.get("pending_interpretations") == 0
    )


def _replays_unchanged(
    first_pass: list[dict[str, Any]], replay: list[dict[str, Any]]
) -> bool:
    if len(first_pass) != len(replay) or not first_pass:
        return False
    if not all(_successful_job(item) for item in first_pass):
        return False
    return all(
        _successful_job(item)
        and item.get("content_digest_unchanged") is True
        and item.get("counts_unchanged") is True
        and item.get("morning_changes_before", {}).get("sha256")
        == item.get("morning_changes_after", {}).get("sha256")
        for item in replay
    )


def _ensure_output_available(output: Path) -> None:
    if output.exists():
        raise FileExistsError(
            f"Refusing to overwrite existing verification receipt: {output}"
        )


def _table_snapshot(session) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, model in CONTENT_MODELS.items():
        rows = session.scalars(select(model)).all()
        rows.sort(
            key=lambda row: tuple(
                str(getattr(row, key.name)) for key in model.__table__.primary_key
            )
        )
        encoded = [
            {
                column.name: _json_value(getattr(row, column.name))
                for column in model.__table__.columns
            }
            for row in rows
        ]
        result[name] = {"count": len(rows), **_digest_rows(name, encoded)}
    return result


def _morning_changes() -> dict[str, Any]:
    from gridlens.api.app import changes

    items = changes()
    encoded = json.dumps(
        items, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return {
        "count": len(items),
        "sha256": hashlib.sha256(encoded.encode()).hexdigest(),
        "items": items,
    }


def _db_counts(session) -> dict[str, int]:
    return {
        name: int(session.scalar(select(func.count()).select_from(model)) or 0)
        for name, model in CONTENT_MODELS.items()
    }


def _source_counts(session, source_id: str) -> dict[str, int]:
    project_ids = select(Project.id).where(Project.source_id == source_id)
    observation_ids = select(Observation.id).where(Observation.source_id == source_id)
    return {
        "observations": int(
            session.scalar(
                select(func.count())
                .select_from(Observation)
                .where(Observation.source_id == source_id)
            )
            or 0
        ),
        "evidence": int(
            session.scalar(
                select(func.count())
                .select_from(Evidence)
                .where(Evidence.observation_id.in_(observation_ids))
            )
            or 0
        ),
        "projects": int(
            session.scalar(
                select(func.count())
                .select_from(Project)
                .where(Project.source_id == source_id)
            )
            or 0
        ),
        "needs": int(
            session.scalar(
                select(func.count())
                .select_from(PowerNeed)
                .where(PowerNeed.project_id.in_(project_ids))
            )
            or 0
        ),
        "changes": int(
            session.scalar(
                select(func.count())
                .select_from(ChangeEvent)
                .where(ChangeEvent.observation_id.in_(observation_ids))
            )
            or 0
        ),
        "failed_interpretations": int(
            session.scalar(
                select(func.count())
                .select_from(Interpretation)
                .join(Observation, Interpretation.observation_id == Observation.id)
                .where(
                    Observation.source_id == source_id,
                    Interpretation.status == "failed",
                )
            )
            or 0
        ),
        "pending_interpretations": int(
            session.scalar(
                select(func.count())
                .select_from(Interpretation)
                .join(Observation, Interpretation.observation_id == Observation.id)
                .where(
                    Observation.source_id == source_id,
                    Interpretation.status == "pending",
                )
            )
            or 0
        ),
    }


def _ensure_fresh_verification_database() -> str:
    name = make_url(settings.database_url).database
    if not name or not name.startswith("gridlens_verify_") or name.endswith("_test"):
        raise RuntimeError(
            "Refusing source run: DATABASE_URL must name gridlens_verify_* app database"
        )
    with SessionLocal() as session:
        dirty = {table: count for table, count in _db_counts(session).items() if count}
        jobs = int(session.scalar(select(func.count()).select_from(Job)) or 0)
    if dirty or jobs:
        raise RuntimeError(
            f"Refusing source run: verification database is not fresh; content={dirty}, jobs={jobs}"
        )
    return name


def _overdue(source: Source, definition: dict[str, Any], now: datetime) -> bool:
    last_success = source.health.get("last_success")
    if not last_success:
        return True
    checked = datetime.fromisoformat(last_success)
    if checked.tzinfo is None:
        checked = checked.replace(tzinfo=UTC)
    return checked <= now - timedelta(hours=int(definition["cadence_hours"]))


def _run_source(
    source_id: str,
    definitions: dict[str, dict[str, Any]],
    *,
    retry_wait: bool = False,
) -> dict[str, Any]:
    definition = definitions[source_id]
    now = datetime.now(UTC)
    with SessionLocal.begin() as session:
        source = session.get(Source, source_id)
        assert source is not None
        overdue_before = _overdue(source, definition, now)
        job_id = enqueue(session, source_id)
        target = session.get(Job, job_id)
        assert target is not None
        target_attempts_before = target.attempts
        if retry_wait and target.status == "queued" and target.available_at > now:
            wait_seconds = (target.available_at - now).total_seconds()
            if wait_seconds > 125:
                raise RuntimeError(
                    f"Retry backoff exceeds bounded replay wait: {wait_seconds:.1f}s"
                )
    incidental: list[dict[str, Any]] = []
    deadline = time.monotonic() + (130 if retry_wait else 300)
    attempted = False
    ran = False
    while time.monotonic() < deadline:
        before_attempts: dict[str, tuple[int, str, str]] = {}
        with SessionLocal() as session:
            jobs = session.scalars(select(Job)).all()
            before_attempts = {
                str(job.id): (job.attempts, job.source_id, job.status) for job in jobs
            }
            target = session.get(Job, job_id)
            assert target is not None
            due_at = target.available_at
            current_status = target.status
        if current_status in {"succeeded", "failed"}:
            break
        now = datetime.now(UTC)
        if current_status == "queued" and due_at > now:
            remaining = (due_at - now).total_seconds()
            if not retry_wait or remaining > 125:
                break
            time.sleep(min(remaining, 1.0))
            continue
        ran = run_one(definitions)
        if not ran:
            time.sleep(0.25)
            continue
        with SessionLocal() as session:
            changed_jobs = session.scalars(select(Job)).all()
            for job in changed_jobs:
                previous = before_attempts.get(str(job.id))
                if previous and job.attempts > previous[0]:
                    attempt = {
                        "source_id": job.source_id,
                        "job_id": str(job.id),
                        "attempt": job.attempts,
                        "job_status": job.status,
                    }
                    other_source = session.get(Source, job.source_id)
                    if other_source:
                        attempt["source_status"] = other_source.health.get("status")
                        attempt["error"] = other_source.health.get("error")
                        succeeded = job.status == "succeeded"
                        attempt["retrieved_records"] = (
                            other_source.health.get("retrieved_records")
                            if succeeded
                            else None
                        )
                        attempt["parsed_records"] = (
                            other_source.health.get("parsed_records")
                            if succeeded
                            else None
                        )
                    if str(job.id) == str(job_id):
                        attempted = job.attempts > target_attempts_before
                    else:
                        incidental.append(attempt)
        if attempted:
            break

    with SessionLocal() as session:
        source = session.get(Source, source_id)
        job = session.get(Job, job_id)
        assert source is not None
        health = dict(source.health)
        succeeded = attempted and bool(job and job.status == "succeeded")
        final_overdue = _overdue(source, definition, datetime.now(UTC))
        source_state = _source_counts(session, source_id)

    result: dict[str, Any] = {
        "source_id": source_id,
        "publisher": definition["publisher"],
        "attempted": bool(ran and attempted),
        "status": health.get("status", "UNKNOWN"),
        "overdue_before_run": overdue_before,
        "overdue_after_run": final_overdue,
        "last_success": health.get("last_success"),
        "parse_failures": health.get("parse_failures") if not succeeded else 0,
        "retrieved_records": health.get("retrieved_records") if succeeded else None,
        "parsed_records": health.get("parsed_records") if succeeded else None,
        "new_records": health.get("new_records") if succeeded else None,
        "changed_records": health.get("changed_records") if succeeded else None,
        "unchanged_records": health.get("unchanged_records") if succeeded else None,
        "failed_jobs": 0 if succeeded else (1 if attempted else None),
        "failed_records": (
            source_state["failed_interpretations"]
            + source_state["pending_interpretations"]
            if succeeded
            else None
        ),
        "failed_interpretations": source_state["failed_interpretations"],
        "pending_interpretations": source_state["pending_interpretations"],
        "pipeline_status": (
            "PASS"
            if succeeded
            and source_state["failed_interpretations"] == 0
            and source_state["pending_interpretations"] == 0
            else "FAIL"
        ),
        "error": None
        if succeeded
        else health.get("error") or "worker did not complete this source job",
        "source_database_counts": source_state,
        "job_status": job.status if job else "UNKNOWN",
        "job_attempts": job.attempts if job else None,
        "incidental_attempts": incidental,
    }
    return result


def run_check(output: Path, *, source_ids: list[str] | None = None) -> dict[str, Any]:
    started = datetime.now(UTC)
    output = output.resolve()
    _ensure_output_available(output)
    db_name = _ensure_fresh_verification_database()
    definitions_list = sync_registry()
    definitions = {row["id"]: row for row in definitions_list if row["enabled"]}
    if source_ids:
        unknown = set(source_ids) - definitions.keys()
        if unknown:
            raise ValueError(
                f"Sources are unknown or disabled: {', '.join(sorted(unknown))}"
            )
        definitions = {key: definitions[key] for key in sorted(set(source_ids))}
    if not definitions:
        raise RuntimeError("Source registry has no enabled sources")
    with SessionLocal() as session:
        initial_counts = _db_counts(session)
        initial_snapshot = _table_snapshot(session)
    receipt = {
        "schema_version": 1,
        "status": "running",
        "objective": "fresh real-source ordinary-worker ingestion and replay",
        "database_name": db_name,
        "started_at_utc": started.isoformat(),
        "execution": "ordinary worker; provider usage must be read from actual call records",
        "requested_source_ids": sorted(source_ids) if source_ids else None,
        "source_count": len(definitions),
        "digest_policy": {
            "content_digest": (
                "All retained columns except Interpretation.attempts and "
                "Interpretation.updated_at, "
                "which are retry bookkeeping."
            ),
            "operational_digest": "Full row content, including retry counters and timestamps.",
            "excluded_from_semantic_content": {
                "interpretations": sorted(OPERATIONAL_INTERPRETATION_FIELDS)
            },
        },
        "initial_database_counts": initial_counts,
        "initial_database_digests": initial_snapshot,
        "initial_morning_changes": _morning_changes(),
        "first_pass": [],
        "replay": [],
        "limitations": [
            "A failed worker job retains UNKNOWN record counts; it is not reported as zero.",
            "Failed or pending record interpretations are reported and fail "
            "the source pipeline gate.",
            "Replay uses the ordinary worker and honors its queued retry backoff.",
            "This local check does not establish cloud, national coverage, or Lead qualification.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as reserved:
        reserved.write("{}\n")

    def persist() -> None:
        receipt["updated_at_utc"] = datetime.now(UTC).isoformat()
        output.write_text(
            json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    persist()
    try:
        for source_id in sorted(definitions):
            result = _run_source(source_id, definitions)
            receipt["first_pass"].append(result)
            persist()
            print(
                f"ingest {source_id}: {result['status']} (failed jobs={result['failed_jobs']})"
            )

        with SessionLocal() as session:
            post_ingest_counts = _db_counts(session)
            post_ingest_snapshot = _table_snapshot(session)
        receipt["post_ingestion_database_counts"] = post_ingest_counts
        receipt["post_ingestion_database_digests"] = post_ingest_snapshot
        receipt["post_ingestion_morning_changes"] = _morning_changes()
        persist()

        for first in receipt["first_pass"]:
            source_id = first["source_id"]
            with SessionLocal() as session:
                before_counts = _db_counts(session)
                before_snapshot = _table_snapshot(session)
            before_changes = _morning_changes()
            item = _run_source(source_id, definitions, retry_wait=True)
            with SessionLocal() as session:
                after_counts = _db_counts(session)
                after_snapshot = _table_snapshot(session)
            after_changes = _morning_changes()
            replay_result = {
                **item,
                "before_database_counts": before_counts,
                "before_database_digests": before_snapshot,
                "after_database_counts": after_counts,
                "after_database_digests": after_snapshot,
                "content_digest_unchanged": _content_snapshot_equal(
                    before_snapshot, after_snapshot
                ),
                "operational_digest_unchanged": _operational_snapshot_equal(
                    before_snapshot, after_snapshot
                ),
                "counts_unchanged": before_counts == after_counts,
                "morning_changes_before": {
                    "count": before_changes["count"],
                    "sha256": before_changes["sha256"],
                },
                "morning_changes_after": {
                    "count": after_changes["count"],
                    "sha256": after_changes["sha256"],
                },
            }
            receipt["replay"].append(replay_result)
            persist()
            print(
                f"replay {source_id}: {item['status']} (failed jobs={item['failed_jobs']})"
            )

        with SessionLocal() as session:
            receipt["final_database_counts"] = _db_counts(session)
            receipt["final_database_digests"] = _table_snapshot(session)
        receipt["final_morning_changes"] = _morning_changes()
        receipt["all_replays_unchanged"] = _replays_unchanged(
            receipt["first_pass"], receipt["replay"]
        )
        receipt["status"] = "passed" if receipt["all_replays_unchanged"] else "failed"
    except Exception as exc:
        receipt["status"] = "interrupted"
        receipt["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        finished = datetime.now(UTC)
        receipt["finished_at_utc"] = finished.isoformat()
        receipt["duration_seconds"] = round((finished - started).total_seconds(), 3)
        persist()
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--source",
        action="append",
        dest="source_ids",
        help="Enabled source ID to verify (repeatable); omitted means all enabled sources.",
    )
    args = parser.parse_args()
    output = args.output or (
        ROOT
        / ".artifacts"
        / "GL3-013"
        / f"local-pipeline-check-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}.json"
    )
    receipt = run_check(output, source_ids=args.source_ids)
    print(f"Receipt: {output}")
    print(f"Status: {receipt['status']}")
    print(f"All replay digests unchanged: {receipt.get('all_replays_unchanged')}")
    if receipt["status"] != "passed" or not receipt.get("all_replays_unchanged"):
        sys.exit(1)


if __name__ == "__main__":
    main()
