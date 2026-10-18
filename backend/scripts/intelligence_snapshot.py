#!/usr/bin/env python3
"""Read-only deterministic metadata snapshot and restore comparison."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from gridlens.intelligence.snapshot_compare import compare
from gridlens.persistence.models import Evidence, Job, LogicalCall, LogicalCallBudget
from gridlens.persistence.watch_models import ProjectMonitorWatch, ProjectMonitorWatchSource
from gridlens.settings import settings

SNAPSHOT_VERSION = 2
TOOL_VERSION = "intelligence-snapshot-v2"


def _digest(rows: Any) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(json.dumps(row, sort_keys=True, separators=(",", ":"), default=str).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def snapshot(session: Session) -> dict[str, Any]:
    tables = {
        # Hash retained payloads and recovery context in-process; only counts and
        # digests leave the database. Never select credential/settings tables.
        "evidence": (
            Evidence,
            [
                Evidence.id,
                Evidence.observation_id,
                Evidence.content_hash,
                Evidence.title,
                Evidence.abstract,
                Evidence.url,
                Evidence.published_at,
                Evidence.observed_at,
                Evidence.extraction_location,
                Evidence.event_date,
                Evidence.event_date_label,
                Evidence.provenance,
            ],
        ),
        "jobs": (
            Job,
            [
                Job.id,
                Job.source_id,
                Job.kind,
                Job.target_id,
                Job.status,
                Job.attempts,
                Job.checkpoint,
                Job.lease_owner,
                Job.fence,
                Job.lease_until,
                Job.available_at,
                Job.created_at,
                Job.error,
            ],
        ),
        "logical_calls": (
            LogicalCall,
            [
                LogicalCall.id,
                LogicalCall.fingerprint,
                LogicalCall.task_type,
                LogicalCall.task_key,
                LogicalCall.evidence_digest,
                LogicalCall.context_digest,
                LogicalCall.prompt_contract,
                LogicalCall.provider,
                LogicalCall.model,
                LogicalCall.policy_version,
                LogicalCall.source_id,
                LogicalCall.project_id,
                LogicalCall.lease_authority,
                LogicalCall.job_id,
                LogicalCall.worker_id,
                LogicalCall.status,
                LogicalCall.blocked_reason,
                LogicalCall.fence_token,
                LogicalCall.estimated_cost_usd,
                LogicalCall.max_cost_usd,
                LogicalCall.actual_cost_usd,
                LogicalCall.input_tokens,
                LogicalCall.output_tokens,
                LogicalCall.created_at,
                LogicalCall.dispatched_at,
                LogicalCall.finished_at,
                LogicalCall.result_digest,
                LogicalCall.result_payload,
                LogicalCall.budget_scopes,
                LogicalCall.reconciled_by,
                LogicalCall.reconciliation_ref,
            ],
        ),
        "budgets": (
            LogicalCallBudget,
            [
                LogicalCallBudget.id,
                LogicalCallBudget.scope,
                LogicalCallBudget.period_key,
                LogicalCallBudget.call_count,
                LogicalCallBudget.cost_usd,
                LogicalCallBudget.active_count,
            ],
        ),
        "monitor_watches": (
            ProjectMonitorWatch,
            [
                ProjectMonitorWatch.id,
                ProjectMonitorWatch.enabled,
                ProjectMonitorWatch.status,
                ProjectMonitorWatch.version,
                ProjectMonitorWatch.need_id,
                ProjectMonitorWatch.question_ids,
                ProjectMonitorWatch.reprocess_revision,
                ProjectMonitorWatch.revision_history,
                ProjectMonitorWatch.unresolved_questions,
                ProjectMonitorWatch.last_good_facts,
                ProjectMonitorWatch.last_good_evidence_refs,
                ProjectMonitorWatch.checkpoint,
                ProjectMonitorWatch.fresh_at,
                ProjectMonitorWatch.updated_at,
            ],
        ),
        "monitor_sources": (
            ProjectMonitorWatchSource,
            [
                ProjectMonitorWatchSource.id,
                ProjectMonitorWatchSource.watch_id,
                ProjectMonitorWatchSource.source_id,
                ProjectMonitorWatchSource.enabled,
                ProjectMonitorWatchSource.next_due_at,
                ProjectMonitorWatchSource.allowed_urls,
                ProjectMonitorWatchSource.record_ids,
                ProjectMonitorWatchSource.policy_snapshot,
                ProjectMonitorWatchSource.applied_version,
                ProjectMonitorWatchSource.cursor,
                ProjectMonitorWatchSource.etag,
                ProjectMonitorWatchSource.last_modified,
                ProjectMonitorWatchSource.last_attempt_at,
                ProjectMonitorWatchSource.last_success_at,
                ProjectMonitorWatchSource.consecutive_failures,
                ProjectMonitorWatchSource.status,
                ProjectMonitorWatchSource.error_class,
                ProjectMonitorWatchSource.checkpoint,
            ],
        ),
    }
    result: dict[str, Any] = {
        "version": SNAPSHOT_VERSION,
        "tool_version": TOOL_VERSION,
        "tables": {},
    }
    for name, (_model, columns) in tables.items():
        rows = session.execute(select(*columns).order_by(*columns[:1])).yield_per(1000)
        digest = hashlib.sha256()
        count = 0
        for row in rows:
            digest.update(
                json.dumps(list(row), sort_keys=True, separators=(",", ":"), default=str).encode()
            )
            digest.update(b"\n")
            count += 1
        result["tables"][name] = {"count": count, "digest": digest.hexdigest()}
    calls = session.execute(
        select(
            LogicalCall.status,
            func.count(),
            func.sum(LogicalCall.actual_cost_usd),
            func.sum(LogicalCall.max_cost_usd),
        ).group_by(LogicalCall.status)
    ).all()
    result["logical_call_exposure"] = [
        {
            "status": status,
            "count": int(count),
            "known_actual_cost_usd": str(actual) if actual is not None else None,
            "reserved_ceiling_usd": str(ceiling) if ceiling is not None else None,
        }
        for status, count, actual, ceiling in calls
    ]
    try:
        result["migration_head"] = session.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    except Exception:
        result["migration_head"] = "UNKNOWN"
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url-env", help="environment variable holding the database URL")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compare", type=Path, help="compare this prior JSON snapshot")
    parser.add_argument("--reference", default="", help="attributable restore rehearsal reference")
    args = parser.parse_args()
    if args.compare and not args.reference:
        parser.error("--compare requires an attributable --reference")
    database_url = (
        os.environ.get(args.database_url_env, "")
        if args.database_url_env
        else settings.database_url
    )
    if not database_url:
        parser.error("database URL is missing")
    url = make_url(database_url)
    if not url.database:
        parser.error("database URL must identify a database")
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            current = snapshot(session)
        output = (
            compare(json.loads(args.compare.read_text(encoding="utf-8")), current, args.reference)
            if args.compare
            else current
        )
        rendered = json.dumps(output, sort_keys=True, indent=2) + "\n"
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
        else:
            sys.stdout.write(rendered)
        return 0 if output.get("result", "MATCH") == "MATCH" else 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
