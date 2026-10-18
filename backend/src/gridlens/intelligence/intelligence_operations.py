"""Bounded, read-only operations summaries for authenticated operators."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, aliased

from gridlens.intelligence.operational_receipts import load_operational_receipt
from gridlens.persistence.models import (
    ChangeEvent,
    Job,
    LogicalCall,
    LogicalCallBudget,
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
    latest_fence = (
        select(
            SourceCheckReceipt.due_key.label("due_key"),
            func.max(SourceCheckReceipt.fence).label("max_fence"),
        )
        .group_by(SourceCheckReceipt.due_key)
        .subquery()
    )
    receipts = aliased(SourceCheckReceipt)
    due_receipts = (
        select(SourceDueCheck, receipts)
        .outerjoin(latest_fence, latest_fence.c.due_key == SourceDueCheck.due_key)
        .outerjoin(
            receipts,
            (receipts.due_key == SourceDueCheck.due_key)
            & (receipts.fence == latest_fence.c.max_fence),
        )
        .where(SourceDueCheck.scheduled_for >= since)
        .subquery()
    )
    source_due_totals = session.execute(
        select(
            due_receipts.c.source_id,
            func.count(),
            func.sum(case((due_receipts.c.id.is_not(None), 1), else_=0)),
            func.sum(case((due_receipts.c.disposition.in_(["failed", "error"]), 1), else_=0)),
            func.sum(case((due_receipts.c.disposition == "partial", 1), else_=0)),
            func.sum(func.coalesce(due_receipts.c.check_counts["parse_failures"].as_integer(), 0)),
            func.sum(
                case(
                    (
                        due_receipts.c.check_counts.has_key("parse_failures")
                        & (due_receipts.c.disposition == "succeeded")
                        & (
                            func.coalesce(
                                due_receipts.c.check_counts["parse_failures"].as_integer(), 0
                            )
                            == 0
                        ),
                        1,
                    ),
                    else_=0,
                )
            ),
            func.sum(case((due_receipts.c.check_counts.has_key("parse_failures"), 1), else_=0)),
        ).group_by(due_receipts.c.source_id)
    ).all()
    latest_due = (
        select(
            SourceDueCheck.source_id,
            SourceDueCheck.scheduled_for,
            receipts.disposition,
            func.row_number()
            .over(
                partition_by=SourceDueCheck.source_id,
                order_by=SourceDueCheck.scheduled_for.desc(),
            )
            .label("row_num"),
        )
        .outerjoin(latest_fence, latest_fence.c.due_key == SourceDueCheck.due_key)
        .outerjoin(
            receipts,
            (receipts.due_key == SourceDueCheck.due_key)
            & (receipts.fence == latest_fence.c.max_fence),
        )
        .where(SourceDueCheck.scheduled_for >= since)
        .subquery()
    )
    latest_due_rows = session.execute(
        select(latest_due.c.source_id, latest_due.c.scheduled_for, latest_due.c.disposition).where(
            latest_due.c.row_num == 1
        )
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
            "parse_success_30d": None,
            "due_30d": 0,
            "freshness_30d": "UNKNOWN",
        }
    for (
        source_id,
        due,
        checked,
        failed,
        partial,
        parse_failures,
        parse_success,
        parse_supported,
    ) in source_due_totals:
        item = source_cycle.get(source_id)
        if item is None:
            continue
        item["due_30d"] = int(due)
        item["checked_30d"] = int(checked or 0)
        item["failed_30d"] = int(failed or 0)
        item["partial_30d"] = int(partial or 0)
        item["parse_failures_30d"] = int(parse_failures or 0)
        item["parse_success_30d"] = int(parse_success or 0) if parse_supported else None
    sources_by_id = {source.id: source for source in sources}
    for source_id, scheduled_for, disposition in latest_due_rows:
        item = source_cycle.get(source_id)
        source_record = sources_by_id.get(source_id)
        if item is None or source_record is None:
            continue
        status = str(disposition or "unknown").lower()
        if status in {"failed", "error"}:
            item["freshness_30d"] = "FAILED"
        elif status == "partial":
            item["freshness_30d"] = "PARTIAL"
        elif status not in {"succeeded", "success", "complete", "completed"}:
            item["freshness_30d"] = (
                "UNKNOWN"
                if scheduled_for >= now - timedelta(hours=source_record.cadence_hours)
                else "OVERDUE"
            )
        else:
            item["freshness_30d"] = (
                "FRESH"
                if scheduled_for >= now - timedelta(hours=source_record.cadence_hours)
                else "OVERDUE"
            )

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

    # All-time financial exposure is aggregated in SQL so the 5k detail window
    # cannot silently hide outstanding reservations.
    cost_by_provider = session.execute(
        select(
            LogicalCall.provider,
            func.sum(LogicalCall.actual_cost_usd),
            func.count(LogicalCall.actual_cost_usd),
            func.sum(
                case(
                    (
                        LogicalCall.status.in_(["NOT_SENT", "SENT_OUTCOME_UNKNOWN"]),
                        func.coalesce(LogicalCall.max_cost_usd, LogicalCall.estimated_cost_usd, 0),
                    ),
                    (
                        LogicalCall.actual_cost_usd.is_(None),
                        case(
                            (
                                LogicalCall.status.in_(["COMPLETED", "FAILED"]),
                                func.coalesce(
                                    LogicalCall.max_cost_usd, LogicalCall.estimated_cost_usd, 0
                                ),
                            ),
                            else_=0,
                        ),
                    ),
                    else_=0,
                )
            ),
            func.sum(case((LogicalCall.actual_cost_usd.is_(None), 1), else_=0)),
            func.sum(case((LogicalCall.status == "SENT_OUTCOME_UNKNOWN", 1), else_=0)),
            func.sum(case((LogicalCall.status == "FAILED", 1), else_=0)),
            func.sum(
                case(
                    (
                        LogicalCall.status.in_(
                            ["NOT_SENT", "SENT_OUTCOME_UNKNOWN", "COMPLETED", "FAILED"]
                        )
                        & LogicalCall.actual_cost_usd.is_(None)
                        & LogicalCall.max_cost_usd.is_(None)
                        & LogicalCall.estimated_cost_usd.is_(None),
                        1,
                    ),
                    else_=0,
                )
            ),
        ).group_by(LogicalCall.provider)
    ).all()
    daily_calls = session.execute(
        select(
            func.date(func.timezone("UTC", func.now())),
            func.count(LogicalCall.id),
            func.sum(LogicalCall.actual_cost_usd),
            func.count(LogicalCall.actual_cost_usd),
            func.sum(
                case(
                    (
                        LogicalCall.actual_cost_usd.is_(None),
                        func.coalesce(LogicalCall.max_cost_usd, LogicalCall.estimated_cost_usd, 0),
                    ),
                    else_=0,
                )
            ),
            func.sum(
                case(
                    (LogicalCall.actual_cost_usd.is_(None), 1),
                    else_=0,
                )
            ),
            func.sum(
                case(
                    (
                        LogicalCall.actual_cost_usd.is_(None)
                        & LogicalCall.max_cost_usd.is_(None)
                        & LogicalCall.estimated_cost_usd.is_(None),
                        1,
                    ),
                    else_=0,
                )
            ),
        ).where(
            func.date(func.timezone("UTC", LogicalCall.created_at))
            == func.date(func.timezone("UTC", func.now()))
        )
    ).one()
    utc_day = str(daily_calls[0])
    daily_budget_rows = session.execute(
        select(LogicalCallBudget.scope, LogicalCallBudget.call_count, LogicalCallBudget.cost_usd)
        .where(LogicalCallBudget.period == "daily", LogicalCallBudget.period_key == utc_day)
        .order_by(LogicalCallBudget.scope)
    ).all()
    all_provider_stats = {
        provider: {
            "actual_cost_usd": float(actual) if actual_count else None,
            "known_cost_calls": int(actual_count or 0),
            "reserved_cost_usd": float(reserved or 0),
            "reserved_unknown": bool(reservation_unknown),
            "unknown_cost_calls": int(unknown_count or 0),
            "uncertain": int(uncertain or 0),
            "failed": int(failed or 0),
        }
        for (
            provider,
            actual,
            actual_count,
            reserved,
            unknown_count,
            uncertain,
            failed,
            reservation_unknown,
        ) in cost_by_provider
    }
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
    reserved_total = sum(
        float(item["reserved_cost_usd"] or 0) for item in all_provider_stats.values()
    )
    reserved_unknown = any(item["reserved_unknown"] for item in all_provider_stats.values())
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
        elif call.status in {"COMPLETED", "SENT_OUTCOME_UNKNOWN", "NOT_SENT"}:
            stat["unknown_cost_calls"] += 1
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
            select(func.count())
            .select_from(ChangeEvent)
            .where(ChangeEvent.material.is_(True), ChangeEvent.created_at >= since)
        )
        or 0
    )
    outstanding_uncertain = sum(int(item["uncertain"] or 0) for item in all_provider_stats.values())
    # Replace financial counters with complete all-time aggregates; detail
    # metrics (models, latency, recent usage) remain explicitly windowed.
    for provider, totals in all_provider_stats.items():
        stat = provider_stats.setdefault(
            provider,
            {
                "provider": provider,
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
        stat.update(totals)
        if totals["reserved_unknown"]:
            stat["reserved_cost_usd"] = None
    known_cost_total = sum(
        float(item["actual_cost_usd"] or 0) for item in all_provider_stats.values()
    )
    known_cost_calls = sum(
        int(item["known_cost_calls"] or 0) for item in all_provider_stats.values()
    )
    unknown_cost_calls = sum(
        int(item["unknown_cost_calls"] or 0) for item in all_provider_stats.values()
    )
    uncertain_count = outstanding_uncertain
    known_cost = round(known_cost_total, 6) if known_cost_calls else None
    receipt = load_operational_receipt(getattr(settings, "operational_receipt_file", ""))
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
            "utc_day": {
                "date": utc_day,
                "timezone": "UTC",
                "calls": int(daily_calls[1] or 0),
                "known_cost_usd": round(float(daily_calls[2]), 6) if daily_calls[3] else None,
                "reserved_cost_usd": None
                if int(daily_calls[6] or 0)
                else round(float(daily_calls[4] or 0), 6),
                "reserved_known_subtotal_usd": round(float(daily_calls[4] or 0), 6),
                "unknown_cost_calls": int(daily_calls[5] or 0),
                "daily_budget_status": "REPORTED" if daily_budget_rows else "UNKNOWN",
                "daily_budget_limits_usd": {
                    "global": float(settings.intelligence_global_daily_usd),
                    "provider": float(settings.intelligence_provider_daily_usd),
                    "model": float(settings.intelligence_model_daily_usd),
                    "source": float(settings.intelligence_source_daily_usd),
                    "project": float(settings.intelligence_project_daily_usd),
                },
                "daily_budget_limits_calls": {
                    "global": settings.intelligence_global_daily_calls,
                    "provider": settings.intelligence_provider_daily_calls,
                    "model": settings.intelligence_model_daily_calls,
                    "source": settings.intelligence_source_daily_calls,
                    "project": settings.intelligence_project_daily_calls,
                },
                "daily_budget_rows": [
                    {
                        "scope": row.scope,
                        "calls": int(row.call_count),
                        "reserved_usd": float(row.cost_usd),
                    }
                    for row in daily_budget_rows
                ],
            },
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
            "reserved_cost_usd": None if reserved_unknown else round(reserved_total, 6),
            "reserved_known_subtotal_usd": round(reserved_total, 6),
            "known_cost_usd": known_cost,
            "known_cost_calls": known_cost_calls,
            "unknown_cost_calls_all_time": unknown_cost_calls,
            "total_cost_status": "UNKNOWN" if unknown_cost_calls else "KNOWN",
            "detail_rows_30d": len(calls),
            "detail_truncated": len(calls) == 5000,
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
        "backup": receipt.get("backup", "UNKNOWN"),
        "restore": receipt.get("restore", "UNKNOWN"),
        "last_verified_restore_at": receipt.get("last_verified_restore_at"),
        "last_reported_restore_at": receipt.get("last_reported_restore_at"),
        "operational_receipt": receipt,
        "commercial_review_receipt": receipt.get("commercial_review", {}),
        "owner_review_notes_30d": int(review_notes),
    }
