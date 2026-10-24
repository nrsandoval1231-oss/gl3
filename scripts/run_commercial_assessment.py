"""Inspect, execute once, or replay metadata for one exact M3 package assessment."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "backend"))

from gridlens.ingestion.registry import load_registry  # noqa: E402
from gridlens.intelligence.commercial_assessment import digest  # noqa: E402
from gridlens.intelligence.intelligence_jobs import (  # noqa: E402
    COMMERCIAL_ASSESSMENT_TASK,
    _current_payload,
    _request_payload,
    _retained_context,
    enqueue_intelligence,
)
from gridlens.jobs.worker import run_one  # noqa: E402
from gridlens.persistence.database import SessionLocal  # noqa: E402
from gridlens.persistence.models import EvidencePackage, Job, LogicalCall, PowerNeed  # noqa: E402
from gridlens.settings import settings  # noqa: E402


def _safe_database(*, execute: bool) -> None:
    url = make_url(settings.database_url)
    allowed = (
        {"pipeline_test", "pipeline_m4_app", "pipeline_m6_app"}
        if execute
        else {"pipeline_test", "pipeline_m4_app", "pipeline_m6_app"}
    )
    if (
        url.host not in {"127.0.0.1", "localhost", "::1"}
        or url.port != 55443
        or url.database not in allowed
        or url.query
    ):
        raise ValueError("M4 operation requires the exact isolated loopback database")


def _public_result(
    package: EvidencePackage, job: Job | None, call: LogicalCall | None
) -> dict:
    checkpoint = {}
    if job and job.checkpoint:
        try:
            checkpoint = json.loads(job.checkpoint)
        except (ValueError, TypeError):
            checkpoint = {}
    result = (
        call.result_payload
        if call and isinstance(call.result_payload, dict)
        else checkpoint.get("result")
    )
    return {
        "package_id": str(package.id),
        "package_key": package.package_key,
        "package_status": package.processing_status,
        "package_digest": digest(package.payload),
        "document_coverage": package.payload.get("document_coverage"),
        "source_collection_status": package.payload.get("source_collection_status"),
        "fact_fields": sorted(
            {
                str(fact.get("field"))
                for fact in package.payload.get("facts", [])
                if isinstance(fact, dict)
            }
        ),
        "need_id": str(package.need_id),
        "project_id": str(package.project_id),
        "job_id": str(job.id) if job else None,
        "job_status": job.status if job else None,
        "logical_call_id": str(call.id) if call else checkpoint.get("logical_call_id"),
        "call_status": call.status if call else None,
        "model": call.model if call else (result or {}).get("actual_model"),
        "reported_usage": (result or {}).get("reported_usage")
        or (result or {}).get("usage"),
        "actual_service_tier": (result or {}).get("service_tier", "UNKNOWN"),
        "latency_ms": (result or {}).get("latency_ms"),
        "cost_estimate_usd": ((result or {}).get("usage") or {}).get(
            "estimated_cost_usd"
        ),
        "cost_basis": ((result or {}).get("usage") or {}).get("cost_basis", "UNKNOWN"),
        "disposition": (result or {}).get("disposition"),
        "selected_fact_ids": (result or {}).get("selected_fact_ids"),
        "unknown_fields": (result or {}).get("unknown_fields"),
        "next_question_id": (result or {}).get("next_question_id"),
        "next_question": (result or {}).get("next_question"),
        "validation_outcome": (result or {}).get(
            "validation_outcome", checkpoint.get("validation_outcome", "PREPARED")
        ),
        "validation_reason": (result or {}).get(
            "validation_reason", checkpoint.get("validation_reason")
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-id", required=True, type=UUID)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--execute", action="store_true", help="queue and run at most this exact job"
    )
    mode.add_argument(
        "--replay",
        action="store_true",
        help="read the exact prior job/call without dispatch",
    )
    args = parser.parse_args()
    _safe_database(execute=args.execute)
    job_id: UUID | None = None
    with SessionLocal.begin() as session:
        package = session.get(EvidencePackage, args.package_id)
        if package is None or package.processing_status != "COMPLETE_ADVISORY":
            raise ValueError("Exact package must exist and be COMPLETE_ADVISORY")
        if package.project_id is None or package.need_id is None:
            raise ValueError("Package must bind exact project and need")
        need = session.get(PowerNeed, package.need_id)
        if need is None or not need.active or need.project_id != package.project_id:
            raise ValueError("Package need/project is no longer current")
        current_need, project, source, evidence = _retained_context(session, need.id)
        inspect_payload = _request_payload(
            session,
            COMMERCIAL_ASSESSMENT_TASK,
            None,
            current_need,
            project,
            source,
            evidence,
            package.id,
        )
        request_digest = digest(inspect_payload)
        matching: list[Job] = []
        for row in session.scalars(
            select(Job)
            .where(Job.kind == "intelligence_process", Job.target_id == need.id)
            .order_by(Job.created_at.desc())
        ).all():
            try:
                checkpoint = json.loads(row.checkpoint or "{}")
            except (ValueError, TypeError):
                continue
            if (
                checkpoint.get("task_type") == COMMERCIAL_ASSESSMENT_TASK
                and checkpoint.get("package_id") == str(package.id)
                and checkpoint.get("request_digest") == request_digest
            ):
                matching.append(row)
        if len(matching) > 1:
            raise ValueError(
                "Multiple exact M4 jobs exist; refusing ambiguous selection"
            )
        if args.execute and not matching:
            job = enqueue_intelligence(
                session,
                need_id=need.id,
                task_type=COMMERCIAL_ASSESSMENT_TASK,
                package_id=package.id,
                origin="operator",
            )
            job_id = job.id
        elif matching:
            job_id = matching[0].id
        if args.replay and not matching:
            raise ValueError(
                "No exact M4 job exists to replay; replay never creates a job"
            )
        if job_id and matching:
            existing = session.get(Job, job_id)
            if existing is None:
                raise ValueError("Exact M4 job disappeared during inspection")
            checkpoint = json.loads(existing.checkpoint or "{}")
            fresh = _current_payload(session, checkpoint, need.id)
            if digest(fresh) != checkpoint.get("request_digest"):
                raise ValueError("Exact M4 request is stale; no retry attempted")
        call = None
        if job_id:
            selected_job = session.get(Job, job_id)
            if selected_job is None:
                raise ValueError("Exact M4 job disappeared before receipt lookup")
            checkpoint = json.loads(selected_job.checkpoint or "{}")
            raw_call_id = checkpoint.get("logical_call_id")
            call = session.get(LogicalCall, UUID(raw_call_id)) if raw_call_id else None
            if (
                args.replay
                and call is None
                and checkpoint.get("status") in {"completed", "unknown", "stale"}
            ):
                raise ValueError("Terminal M4 job has no exact logical call receipt")
            if call and (
                call.task_type != COMMERCIAL_ASSESSMENT_TASK
                or call.task_key != f"{need.id}:{COMMERCIAL_ASSESSMENT_TASK}"
            ):
                raise ValueError(
                    "Logical call identity does not match the exact M4 need/task"
                )
        output = _public_result(
            package, session.get(Job, job_id) if job_id else None, call
        )
    if args.execute and job_id and output.get("job_status") in {"queued", "running"}:
        run_one({item["id"]: item for item in load_registry()}, job_ids=[job_id])
        with SessionLocal() as session:
            refreshed_package = session.get(EvidencePackage, args.package_id)
            if refreshed_package is None:
                raise ValueError("Exact package disappeared after execution")
            refreshed_job = session.get(Job, job_id)
            if refreshed_job is None:
                raise ValueError("Exact M4 job disappeared after execution")
            checkpoint = json.loads(refreshed_job.checkpoint or "{}")
            raw_call_id = checkpoint.get("logical_call_id")
            call = session.get(LogicalCall, UUID(raw_call_id)) if raw_call_id else None
            output = _public_result(refreshed_package, refreshed_job, call)
    print(json.dumps(output, sort_keys=True))
    return 0 if output.get("validation_outcome") in {"VALIDATED", "PREPARED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
