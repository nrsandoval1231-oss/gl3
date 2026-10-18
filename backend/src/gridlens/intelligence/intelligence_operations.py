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
    SourceScheduleEpoch,
)
from gridlens.settings import settings


def operations_view(session: Session) -> dict[str, Any]:
    """Summarize persisted queue/provider/source data without probing providers."""
    now = datetime.now(UTC)
    since = now - timedelta(days=30)
    sources = session.scalars(select(Source).order_by(Source.id).limit(200)).all()
    from gridlens.jobs.source_schedule_proof import verified_schedule_success
    from gridlens.jobs.worker import _due_key, _scheduled_instants, _source_registry_drift

    latest_fence = (
        select(
            SourceCheckReceipt.due_key.label("due_key"),
            func.max(SourceCheckReceipt.fence).label("max_fence"),
        )
        .group_by(SourceCheckReceipt.due_key)
        .subquery()
    )
    receipt_alias = aliased(SourceCheckReceipt)
    due_status_by_source: dict[str, dict[str, tuple[Any, Any, Any, Any, bool]]] = {}
    schedule_rows = session.execute(
        select(SourceDueCheck, SourceScheduleEpoch, receipt_alias, Job)
        .join(SourceScheduleEpoch, SourceScheduleEpoch.id == SourceDueCheck.epoch_id)
        .outerjoin(latest_fence, latest_fence.c.due_key == SourceDueCheck.due_key)
        .outerjoin(
            receipt_alias,
            (receipt_alias.due_key == SourceDueCheck.due_key)
            & (receipt_alias.fence == latest_fence.c.max_fence),
        )
        .outerjoin(Job, Job.id == receipt_alias.job_id)
        .where(SourceDueCheck.scheduled_for >= since)
        .order_by(SourceDueCheck.scheduled_for)
        .limit(20_000)
    ).all()
    source_due_totals: dict[str, dict[str, int]] = {}
    for due, epoch, receipt_row, job in schedule_rows:
        metrics = source_due_totals.setdefault(
            due.source_id,
            {
                "due": 0,
                "checked": 0,
                "failed": 0,
                "partial": 0,
                "parse_failures": 0,
                "parse_success": 0,
                "parse_supported": 0,
                "verified_success": 0,
                "unverified": 0,
            },
        )
        metrics["due"] += 1
        disposition = receipt_row.disposition if receipt_row is not None else None
        counts = receipt_row.check_counts if receipt_row is not None else {}
        if disposition:
            metrics["checked"] += 1
            metrics["failed"] += int(disposition in {"failed", "error"})
            metrics["partial"] += int(disposition == "partial")
            metrics["parse_failures"] += int(counts.get("parse_failures", 0) or 0)
            metrics["parse_supported"] += int("parse_failures" in counts)
        next_due = None
        try:
            horizon = epoch.effective_until or (due.scheduled_for + timedelta(days=400))
            next_due = next(
                _scheduled_instants(
                    epoch, horizon, not_before=due.scheduled_for + timedelta(microseconds=1)
                ),
                None,
            )
            if epoch.effective_until and (next_due is None or epoch.effective_until < next_due):
                next_due = epoch.effective_until
        except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
            pass
        verified = bool(
            receipt_row is not None
            and verified_schedule_success(
                due=due,
                receipt=receipt_row,
                job=job,
                next_scheduled_for=next_due,
            )
        )
        if disposition == "succeeded":
            if verified:
                metrics["verified_success"] += 1
                if "parse_failures" in counts and not counts.get("parse_failures"):
                    metrics["parse_success"] += 1
            else:
                metrics["unverified"] += 1
        due_status_by_source.setdefault(due.source_id, {})[due.due_key] = (
            due,
            epoch,
            receipt_row,
            job,
            verified,
        )
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
            "schedule_history_30d": "UNKNOWN",
            "verified_success_30d": 0,
            "unverified_30d": 0,
            "freshness_30d": "UNKNOWN",
        }
    for source_id, totals in source_due_totals.items():
        item = source_cycle.get(source_id)
        if item is None:
            continue
        item["checked_30d"] = totals["checked"]
        item["failed_30d"] = totals["failed"]
        item["partial_30d"] = totals["partial"]
        item["parse_failures_30d"] = totals["parse_failures"]
        item["parse_success_30d"] = totals["parse_success"] if totals["parse_supported"] else None
        item["verified_success_30d"] = totals["verified_success"]
        item["unverified_30d"] = totals["unverified"]
    from gridlens.ingestion.registry import load_registry

    definitions = {entry["id"]: entry for entry in load_registry()}
    expected_since = now - timedelta(days=30)
    for source in sources:
        item = source_cycle[source.id]
        epochs = session.scalars(
            select(SourceScheduleEpoch)
            .where(
                SourceScheduleEpoch.source_id == source.id,
                SourceScheduleEpoch.effective_from < now,
                (SourceScheduleEpoch.effective_until.is_(None))
                | (SourceScheduleEpoch.effective_until > expected_since),
            )
            .order_by(SourceScheduleEpoch.effective_from)
        ).all()
        definition = definitions.get(source.id)
        history_known = bool(epochs and definition)
        covered_until = expected_since
        expected: dict[str, tuple[SourceScheduleEpoch, datetime]] = {}
        if epochs and definition:
            latest_epoch = max(epochs, key=lambda epoch: epoch.effective_from)
            try:
                if (
                    latest_epoch.effective_until is None
                    and latest_epoch.history_known
                    and _source_registry_drift(definition, source, latest_epoch)
                ):
                    history_known = False
            except (AttributeError, KeyError, TypeError, ValueError):
                history_known = False
            for epoch in epochs:
                epoch_start = max(epoch.effective_from, expected_since)
                epoch_end = min(epoch.effective_until or now, now)
                if epoch_start > covered_until or not epoch.history_known:
                    history_known = False
                if epoch_start <= covered_until and epoch_end > covered_until:
                    covered_until = epoch_end
                if not (epoch.history_known and epoch.registry_enabled and epoch.operator_enabled):
                    continue
                try:
                    for scheduled_for in _scheduled_instants(epoch, now, not_before=expected_since):
                        expected[_due_key(epoch, scheduled_for)] = (epoch, scheduled_for)
                except (AttributeError, KeyError, OverflowError, TypeError, ValueError):
                    history_known = False
        if covered_until < now:
            history_known = False
        item["due_30d"] = len(expected)
        item["schedule_history_30d"] = "KNOWN" if history_known else "UNKNOWN"
        failed = partial = missing = invalid = unverified = False
        source_statuses = due_status_by_source.get(source.id, {})
        for due_key, (epoch, scheduled_for) in expected.items():
            status_entry = source_statuses.get(due_key)
            if status_entry is None:
                missing = True
                continue
            due, stored_epoch, receipt, job, verified = status_entry
            if (
                due.source_id != source.id
                or due.epoch_id != epoch.id
                or due.scheduled_for != scheduled_for
                or due.configuration != epoch.configuration
                or stored_epoch.id != epoch.id
            ):
                invalid = True
                continue
            if receipt is None:
                missing = True
            elif receipt.disposition in {"failed", "error"}:
                failed = True
            elif receipt.disposition == "partial":
                partial = True
            elif receipt.disposition == "succeeded" and not verified:
                unverified = True
            elif receipt.disposition not in {"succeeded", "success", "complete", "completed"}:
                missing = True
        item["freshness_30d"] = (
            "UNKNOWN"
            if not history_known or invalid or unverified
            else "FAILED"
            if failed
            else "PARTIAL"
            if partial
            else "OVERDUE"
            if missing
            else "FRESH"
            if expected
            else "UNKNOWN"
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
                                LogicalCall.status.in_(["COMPLETED", "FAILED", "RECONCILED"]),
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
                            [
                                "NOT_SENT",
                                "SENT_OUTCOME_UNKNOWN",
                                "COMPLETED",
                                "FAILED",
                                "RECONCILED",
                            ]
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
    overage_by_provider: dict[str, Any] = {}
    for provider, overage in session.execute(
        select(
            LogicalCall.provider,
            func.sum(
                case(
                    (
                        LogicalCall.actual_cost_usd > LogicalCall.max_cost_usd,
                        LogicalCall.actual_cost_usd - LogicalCall.max_cost_usd,
                    ),
                    else_=0,
                )
            ),
        )
        .where(LogicalCall.actual_cost_usd.is_not(None))
        .group_by(LogicalCall.provider)
    ).all():
        overage_by_provider[provider] = overage
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
            "overage_cost_usd": round(float(overage_by_provider.get(provider) or 0), 6),
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
                "input_token_known_calls": 0,
                "output_token_known_calls": 0,
                "input_token_unknown_calls": 0,
                "output_token_unknown_calls": 0,
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
        elif call.status in {
            "COMPLETED",
            "FAILED",
            "RECONCILED",
            "SENT_OUTCOME_UNKNOWN",
            "NOT_SENT",
        }:
            stat["unknown_cost_calls"] += 1
        if call.input_tokens is not None:
            stat["input_tokens"] += int(call.input_tokens)
            stat["input_token_known_calls"] += 1
        else:
            stat["input_token_unknown_calls"] += 1
        if call.output_tokens is not None:
            stat["output_tokens"] += int(call.output_tokens)
            stat["output_token_known_calls"] += 1
        else:
            stat["output_token_unknown_calls"] += 1
        if call.input_tokens is not None and call.output_tokens is not None:
            stat["usage_known_calls"] += 1
        else:
            stat["usage_unknown_calls"] += 1
        if call.status in {"NOT_SENT", "SENT_OUTCOME_UNKNOWN"} or (
            call.status in {"COMPLETED", "FAILED", "RECONCILED"} and call.actual_cost_usd is None
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
    for provider, provider_totals in all_provider_stats.items():
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
                "input_token_known_calls": 0,
                "output_token_known_calls": 0,
                "input_token_unknown_calls": 0,
                "output_token_unknown_calls": 0,
                "usage_known_calls": 0,
                "usage_unknown_calls": 0,
                "measured_latency_ms": [],
            },
        )
        stat.update(provider_totals)
        if provider_totals["reserved_unknown"]:
            stat["reserved_cost_usd"] = None
    known_cost_total = sum(
        float(item["actual_cost_usd"] or 0) for item in all_provider_stats.values()
    )
    known_cost_calls = sum(
        int(item["known_cost_calls"] or 0) for item in all_provider_stats.values()
    )
    overage_cost_total = sum(
        float(item["overage_cost_usd"] or 0) for item in all_provider_stats.values()
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
            "overage_cost_usd": round(overage_cost_total, 6),
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
