"""Bounded, read-only operations summaries for authenticated operators."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from gridlens.persistence.models import (
    ChangeEvent,
    Job,
    LogicalCall,
    PursuitCallNote,
    PursuitResearchQuestion,
    Source,
    SourceCheckReceipt,
    SourceDueCheck,
)
from gridlens.settings import settings


def operations_view(session: Session) -> dict[str, Any]:
    """Summarize persisted queue/provider/source data without probing providers."""
    now = datetime.now(UTC)
    since = now - timedelta(days=30)
    sources = session.scalars(select(Source).order_by(Source.id).limit(200)).all()
    due_rows = session.execute(
        select(SourceDueCheck, SourceCheckReceipt)
        .outerjoin(SourceCheckReceipt, SourceCheckReceipt.due_key == SourceDueCheck.due_key)
        .where(SourceDueCheck.scheduled_for >= since)
        .order_by(SourceDueCheck.scheduled_for.desc(), SourceCheckReceipt.fence.desc())
        .limit(20000)
    ).all()
    source_cycle: dict[str, dict[str, Any]] = {}
    for source in sources:
        source_cycle[source.id] = {
            "source_id": source.id,
            "enabled": bool(source.enabled and source.registry_enabled),
            "last_attempt_at": (source.health or {}).get("last_attempt"),
            "last_success_at": (source.health or {}).get("last_success"),
            "last_good_preserved": bool((source.health or {}).get("last_success")),
            "checked_30d": 0,
            "failed_30d": 0,
            "partial_30d": 0,
            "parse_failures_30d": 0,
            "due_30d": 0,
        }
    latest_receipt: dict[str, tuple[SourceDueCheck, SourceCheckReceipt | None]] = {}
    for due, receipt in due_rows:
        current = latest_receipt.get(due.due_key)
        if current is None or (
            receipt is not None
            and (current[1] is None or (receipt.fence, receipt.recorded_at, str(receipt.id)) >
                 (current[1].fence, current[1].recorded_at, str(current[1].id)))
        ):
            latest_receipt[due.due_key] = (due, receipt)
    for due, receipt in latest_receipt.values():
        item = source_cycle.get(due.source_id)
        if item is None:
            continue
        item["due_30d"] += 1
        if receipt is not None:
            disposition = str(receipt.disposition).lower()
            item["checked_30d"] += int(
                disposition in {
                    "complete",
                    "completed",
                    "success",
                    "succeeded",
                    "partial",
                    "failed",
                    "error",
                }
            )
            item["failed_30d"] += int(disposition in {"failed", "error"})
            item["partial_30d"] += int(disposition == "partial")
            counts = receipt.check_counts if isinstance(receipt.check_counts, dict) else {}
            item["parse_failures_30d"] += int(counts.get("parse_failures") or 0)

    queue_rows = session.execute(
        select(Job.kind, Job.status, func.count())
        .where(Job.created_at >= since)
        .group_by(Job.kind, Job.status)
        .limit(200)
    ).all()
    queue: dict[str, dict[str, int]] = {}
    for kind, status, count in queue_rows:
        queue.setdefault(kind, {})[status] = int(count)
    oldest = session.scalar(select(func.min(Job.created_at)).where(Job.status == "queued"))
    retry_count = int(
        session.scalar(
            select(func.count()).select_from(Job).where(Job.attempts > 1, Job.created_at >= since)
        )
        or 0
    )
    deadletter_count = int(
        session.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.status == "failed", Job.attempts >= 3, Job.created_at >= since)
        )
        or 0
    )

    calls = (
        session.execute(
            select(LogicalCall)
            .where(LogicalCall.created_at >= since)
            .order_by(LogicalCall.created_at.desc())
            .limit(5000)
        )
        .scalars()
        .all()
    )
    provider_stats: dict[str, dict[str, Any]] = {}
    reserved_total = 0.0
    known_cost_total = 0.0
    known_cost_calls = 0
    unknown_cost_calls = 0
    uncertain_count = 0
    for call in calls:
        stat = provider_stats.setdefault(
            call.provider,
            {
                "provider": call.provider,
                "called": 0,
                "completed": 0,
                "accepted": None,
                "models": {},
                "actual_cost_usd": None,
                "reserved_cost_usd": 0.0,
                "uncertain": 0,
                "failed": 0,
                "unknown_cost_calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "usage_known_calls": 0,
                "usage_unknown_calls": 0,
                "measured_latency_ms": [],
            },
        )
        dispatched = call.dispatched_at is not None
        stat["called"] += int(dispatched)
        stat["completed"] += int(call.status == "COMPLETED")
        stat["failed"] += int(call.status == "FAILED")
        stat["uncertain"] += int(call.status == "SENT_OUTCOME_UNKNOWN")
        uncertain_count += int(call.status == "SENT_OUTCOME_UNKNOWN")
        model = stat["models"].setdefault(
            call.model,
            {"called": 0, "completed": 0, "pinned_model": call.model, "actual_models": {}},
        )
        model["called"] += int(dispatched)
        model["completed"] += int(call.status == "COMPLETED")
        actual_model = (
            call.result_payload.get("actual_model")
            if isinstance(call.result_payload, dict)
            else None
        )
        if isinstance(actual_model, str) and actual_model:
            actual_models = model["actual_models"]
            actual_models[actual_model] = actual_models.get(actual_model, 0) + 1
        if call.actual_cost_usd is not None:
            amount = float(call.actual_cost_usd)
            stat["actual_cost_usd"] = (stat["actual_cost_usd"] or 0.0) + amount
            known_cost_total += amount
            known_cost_calls += 1
        elif call.status in {"COMPLETED", "SENT_OUTCOME_UNKNOWN", "NOT_SENT"}:
            stat["unknown_cost_calls"] += 1
            unknown_cost_calls += 1
        if call.input_tokens is not None and call.output_tokens is not None:
            stat["input_tokens"] += int(call.input_tokens)
            stat["output_tokens"] += int(call.output_tokens)
            stat["usage_known_calls"] += 1
        else:
            stat["usage_unknown_calls"] += 1
        if call.status in {"NOT_SENT", "SENT_OUTCOME_UNKNOWN"} or (
            call.status == "COMPLETED" and call.actual_cost_usd is None
        ):
            amount = float(call.max_cost_usd or call.estimated_cost_usd or 0)
            stat["reserved_cost_usd"] += amount
            reserved_total += amount
        latency = None
        if isinstance(call.result_payload, dict):
            latency = call.result_payload.get("latency_ms")
        if isinstance(latency, int | float) and latency >= 0:
            stat["measured_latency_ms"].append(float(latency))
    for stat in provider_stats.values():
        values = sorted(stat.pop("measured_latency_ms"))
        stat["latency_p50_ms"] = (
            values[min(len(values) - 1, int((len(values) - 1) * 0.50))] if values else None
        )
        stat["latency_p95_ms"] = (
            values[min(len(values) - 1, int((len(values) - 1) * 0.95))] if values else None
        )

    question_outcomes = session.execute(
        select(PursuitResearchQuestion.status, func.count())
        .where(PursuitResearchQuestion.created_at >= since)
        .group_by(PursuitResearchQuestion.status)
        .limit(30)
    ).all()
    review_notes = (
        session.scalar(
            select(func.count())
            .select_from(PursuitCallNote)
            .where(PursuitCallNote.created_at >= since)
        )
        or 0
    )
    material_changes = int(
        session.scalar(
            select(func.count()).select_from(ChangeEvent).where(
                ChangeEvent.material.is_(True), ChangeEvent.created_at >= since
            )
        )
        or 0
    )
    outstanding_uncertain = int(
        session.scalar(
            select(func.count())
            .select_from(LogicalCall)
            .where(LogicalCall.status == "SENT_OUTCOME_UNKNOWN")
        )
        or 0
    )
    known_cost = round(known_cost_total, 6) if known_cost_calls else None
    return {
        "window_days": 30,
        "sources": list(source_cycle.values()),
        "queue": {
            "by_kind_status": queue,
            "oldest_queued_at": oldest,
            "retried_jobs_30d": retry_count,
            "failed_after_three_attempts_30d": deadletter_count,
        },
        "providers": {
            "configured": {
                "openai": bool(settings.openai_api_key),
                "typesafe": bool(settings.typesafe_api_key),
            },
            "enabled": {
                "openai": bool(
                    settings.intelligence_enabled and settings.intelligence_openai_enabled
                ),
                "typesafe": bool(
                    settings.intelligence_enabled
                    and settings.intelligence_typesafe_enabled
                    and settings.jev_enabled
                ),
            },
            "by_provider": list(provider_stats.values()),
            "reserved_cost_usd": round(reserved_total, 6),
            "known_cost_usd": known_cost,
            "known_cost_calls": known_cost_calls,
            "unknown_cost_calls_30d": unknown_cost_calls,
            "outstanding_uncertain_calls_all_time": outstanding_uncertain,
            "uncertain_calls": uncertain_count,
            "accepted": None,
            "accepted_reason": (
                "Candidate acceptance is owner-reviewed; provider completion is not acceptance."
            ),
        },
        "questions": {"outcomes_30d": {str(name): int(count) for name, count in question_outcomes}},
        "material_changes_30d": material_changes,
        "reviewed_signals": None,
        "independent_leads": None,
        "backup": "UNKNOWN",
        "restore": "UNKNOWN",
        "owner_review_notes_30d": int(review_notes),
    }
