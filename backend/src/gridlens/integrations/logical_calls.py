"""Durable, capped logical-call reservations. This module never performs network I/O."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gridlens.persistence.models import Job, LogicalCall, LogicalCallBudget

MAX_USD = Decimal("100.000000")
MAX_BUDGET_USD = Decimal("100000.000000")
MAX_ACTUAL_USD = Decimal("1000000.000000")


@dataclass(frozen=True)
class ReservationResult:
    call_id: UUID | None
    reused: bool
    status: str
    blocked_reason: str | None = None
    fence_token: int | None = None


def fingerprint_call(
    *,
    task_type: str,
    task_key: str,
    evidence_digest: str,
    context_digest: str,
    prompt_contract: str,
    provider: str,
    model: str,
    policy_version: str,
) -> str:
    """Return stable SHA256 identity over every input that changes call meaning."""
    payload = {
        "task_type": task_type,
        "task_key": task_key,
        "evidence_digest": evidence_digest,
        "context_digest": context_digest,
        "prompt_contract": prompt_contract,
        "provider": provider,
        "model": model,
        "policy_version": policy_version,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _money(value: Decimal | str | int | float, *, name: str, maximum: Decimal = MAX_USD) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be a finite decimal") from exc
    if not parsed.is_finite() or parsed < 0 or parsed > maximum:
        raise ValueError(f"{name} must be between 0 and {maximum}")
    return parsed.quantize(Decimal("0.000001"), rounding=ROUND_CEILING)


def reserve_call(
    session: Session,
    *,
    task_type: str,
    task_key: str,
    evidence_digest: str,
    context_digest: str,
    prompt_contract: str,
    provider: str,
    model: str,
    policy_version: str,
    source_id: str | None = None,
    project_id: UUID | None = None,
    lease_authority: str | None = None,
    job_id: UUID | None = None,
    worker_id: str | None = None,
    enabled: bool = False,
    estimated_cost_usd: Decimal | str | int | float = 0,
    max_cost_usd: Decimal | str | int | float = 0,
    caps: dict[str, dict[str, int | Decimal | str | float]] | None = None,
    max_active: int = 1,
    fence_token: int = 0,
) -> ReservationResult:
    """Reuse existing intent or atomically reserve every daily/monthly scope cap.

    A dedicated session is required; each call commits or rolls back its own short transaction.
    Job-bound calls require a live `(job_id, worker_id, fence_token)` lease. Standalone
    operator/test use must explicitly set `lease_authority="standalone"`.
    `caps` maps scope labels (`global`, `provider`, `model`, `source`, `project`) to
    `{daily, monthly}` finite integer caps. Missing/zero caps fail closed. This
    function owns its transaction boundary and commits before returning.
    """
    cost = _money(estimated_cost_usd, name="estimated_cost_usd")
    max_cost = _money(max_cost_usd, name="max_cost_usd")
    if cost > max_cost:
        raise ValueError("estimated call cost exceeds max_cost_usd")
    if fence_token < 0:
        raise ValueError("fence_token must be nonnegative")
    if lease_authority == "job":
        if job_id is None or not worker_id:
            raise ValueError("job authority requires job_id and worker_id")
        if not _assert_job_fence(session, job_id, worker_id, fence_token):
            session.rollback()
            return ReservationResult(None, False, "BLOCKED", "STALE_FENCE")
    elif lease_authority == "standalone":
        if job_id is not None or worker_id is not None:
            raise ValueError("standalone authority cannot include a job lease")
    else:
        session.rollback()
        raise ValueError("explicit job or standalone lease authority required")
    fingerprint = fingerprint_call(
        task_type=task_type,
        task_key=task_key,
        evidence_digest=evidence_digest,
        context_digest=context_digest,
        prompt_contract=prompt_contract,
        provider=provider,
        model=model,
        policy_version=policy_version,
    )
    prior = session.scalar(select(LogicalCall).where(LogicalCall.fingerprint == fingerprint))
    if prior is not None:
        if prior.source_id != source_id or prior.project_id != project_id:
            session.rollback()
            return ReservationResult(
                prior.id, True, prior.status, "IDENTITY_SCOPE_MISMATCH", prior.fence_token
            )
        if not enabled:
            session.rollback()
            return ReservationResult(
                prior.id, True, prior.status, "INTELLIGENCE_DISABLED", prior.fence_token
            )
        if (
            prior.lease_authority != lease_authority
            or prior.job_id != job_id
            or prior.worker_id != worker_id
        ):
            session.rollback()
            return ReservationResult(
                prior.id, True, prior.status, "IDENTITY_LEASE_MISMATCH", prior.fence_token
            )
        session.commit()
        return ReservationResult(
            prior.id, True, prior.status, prior.blocked_reason, prior.fence_token
        )
    if not enabled:
        session.rollback()
        return ReservationResult(None, False, "BLOCKED", "INTELLIGENCE_DISABLED")
    if cost <= 0 or max_cost <= 0:
        session.rollback()
        return ReservationResult(None, False, "BLOCKED", "FINITE_COST_BOUND_REQUIRED")

    now = datetime.now(UTC)
    now_day, now_month = now.date().isoformat(), now.strftime("%Y-%m")
    scopes = [
        ("global", "global"),
        ("provider", provider),
        ("model", f"{provider}:{model}"),
    ]
    if source_id is not None:
        scopes.append(("source", source_id))
    if project_id is not None:
        scopes.append(("project", str(project_id)))
    if (
        isinstance(max_active, bool)
        or not isinstance(max_active, int)
        or not 1 <= max_active <= 100_000
    ):
        session.rollback()
        raise ValueError("max_active must be a finite positive integer")
    requested: list[tuple[str, str, str, int, Decimal]] = []
    supplied = caps or {}
    for scope_type, scope_value in scopes:
        limits = supplied.get(scope_type, {})
        for period, _key in (("daily", now_day), ("monthly", now_month)):
            limit = limits.get(period, 0)
            usd_limit = limits.get(f"{period}_usd", 0)
            if (
                isinstance(limit, bool)
                or not isinstance(limit, int)
                or limit < 0
                or limit > 1_000_000
            ):
                session.rollback()
                raise ValueError(f"invalid {scope_type} {period} cap")
            try:
                usd_limit = _money(
                    usd_limit, name=f"{scope_type} {period} usd cap", maximum=MAX_BUDGET_USD
                )
            except ValueError:
                session.rollback()
                raise
            if limit == 0:
                session.rollback()
                return ReservationResult(
                    None, False, "BLOCKED", f"{scope_type.upper()}_{period.upper()}_CAP_ZERO"
                )
            if usd_limit <= 0:
                session.rollback()
                return ReservationResult(
                    None, False, "BLOCKED", f"{scope_type.upper()}_{period.upper()}_USD_CAP_ZERO"
                )
            if max_cost > usd_limit:
                session.rollback()
                return ReservationResult(
                    None, False, "BLOCKED", f"{scope_type.upper()}_{period.upper()}_USD_CAP_REACHED"
                )
            requested.append((scope_type, scope_value, period, limit, usd_limit))
        requested.append((scope_type, scope_value, "active", max_active, Decimal("0")))

    call = LogicalCall(
        fingerprint=fingerprint,
        task_type=task_type,
        task_key=task_key,
        evidence_digest=evidence_digest,
        context_digest=context_digest,
        prompt_contract=prompt_contract,
        provider=provider,
        model=model,
        policy_version=policy_version,
        source_id=source_id,
        project_id=project_id,
        lease_authority=lease_authority,
        job_id=job_id,
        worker_id=worker_id,
        status="NOT_SENT",
        fence_token=fence_token,
        estimated_cost_usd=cost,
        max_cost_usd=max_cost,
        budget_scopes=[
            {
                "scope": kind + ":" + value,
                "period": period,
                "period_key": (
                    now_day if period == "daily" else now_month if period == "monthly" else "active"
                ),
            }
            for kind, value, period, _, _ in requested
        ],
    )
    session.add(call)
    try:
        session.flush()
        for _scope_type, scope_value, period, limit, usd_limit in requested:
            period_key = (
                now_day if period == "daily" else now_month if period == "monthly" else "active"
            )
            scope = _scope_type + ":" + scope_value
            is_active = period == "active"
            stmt = (
                insert(LogicalCallBudget)
                .values(
                    scope=scope,
                    period=period,
                    period_key=period_key,
                    call_count=0 if is_active else 1,
                    cost_usd=Decimal("0") if is_active else max_cost,
                    active_count=1,
                )
                .on_conflict_do_update(
                    constraint="uq_call_budget_scope_period",
                    set_={
                        "call_count": LogicalCallBudget.call_count + (0 if is_active else 1),
                        "cost_usd": LogicalCallBudget.cost_usd
                        + (Decimal("0") if is_active else max_cost),
                        "active_count": LogicalCallBudget.active_count + 1,
                    },
                    where=(LogicalCallBudget.active_count < limit)
                    if is_active
                    else (LogicalCallBudget.call_count < limit)
                    & (LogicalCallBudget.cost_usd + max_cost <= usd_limit),
                )
                .returning(LogicalCallBudget.id)
            )
            if session.scalar(stmt) is None:
                session.rollback()
                return ReservationResult(
                    None, False, "BLOCKED", f"{_scope_type.upper()}_{period.upper()}_CAP_REACHED"
                )
        session.commit()
    except IntegrityError:
        session.rollback()
        duplicate = session.scalar(
            select(LogicalCall).where(LogicalCall.fingerprint == fingerprint)
        )
        if duplicate is not None:
            session.commit()
            return ReservationResult(
                duplicate.id,
                True,
                duplicate.status,
                duplicate.blocked_reason,
                duplicate.fence_token,
            )
        raise
    except Exception:
        session.rollback()
        raise
    return ReservationResult(call.id, False, call.status, None, call.fence_token)


def _assert_job_fence(session: Session, job_id: UUID, worker_id: str, fence_token: int) -> bool:
    job = session.scalar(select(Job).where(Job.id == job_id).with_for_update())
    return bool(
        job is not None
        and job.status == "running"
        and job.lease_owner == worker_id
        and job.fence == fence_token
        and job.lease_until is not None
        and job.lease_until > datetime.now(UTC)
    )


def _call_fence_is_current(session: Session, call: LogicalCall) -> bool:
    if call.lease_authority == "standalone":
        return True
    return bool(
        call.job_id is not None
        and call.worker_id is not None
        and _assert_job_fence(session, call.job_id, call.worker_id, call.fence_token)
    )


def mark_dispatched(
    session: Session, call_id: UUID, *, fence_token: int, enabled: bool = False
) -> ReservationResult:
    """Commit SENT_OUTCOME_UNKNOWN before a caller starts its network request."""
    call = session.scalar(select(LogicalCall).where(LogicalCall.id == call_id).with_for_update())
    if call is None:
        session.rollback()
        return ReservationResult(call_id, False, "BLOCKED", "CALL_NOT_FOUND")
    if call.fence_token != fence_token:
        session.rollback()
        return ReservationResult(call_id, False, call.status, "STALE_FENCE", call.fence_token)
    if not enabled:
        session.rollback()
        return ReservationResult(
            call_id, False, call.status, "INTELLIGENCE_DISABLED", call.fence_token
        )
    if not _call_fence_is_current(session, call):
        session.rollback()
        return ReservationResult(call_id, False, call.status, "STALE_FENCE", call.fence_token)
    if call.status != "NOT_SENT":
        session.commit()
        return ReservationResult(
            call_id, True, call.status, "ALREADY_DISPATCHED_OR_TERMINAL", call.fence_token
        )
    call.status = "SENT_OUTCOME_UNKNOWN"
    call.dispatched_at = datetime.now(UTC)
    session.commit()
    return ReservationResult(call_id, False, call.status, None, call.fence_token)


def _transition(
    session: Session,
    call_id: UUID,
    *,
    fence_token: int,
    status: str,
    actual_cost_usd: Decimal | str | int | float | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    result_digest: str | None = None,
    result_payload: dict[str, Any] | None = None,
    blocked_reason: str | None = None,
    allow_reconcile_override: bool = False,
    reconciliation_actor: str | None = None,
    reconciliation_ref: str | None = None,
) -> ReservationResult:
    call = session.scalar(select(LogicalCall).where(LogicalCall.id == call_id).with_for_update())
    if call is None:
        session.rollback()
        return ReservationResult(call_id, False, "BLOCKED", "CALL_NOT_FOUND")
    if call.fence_token != fence_token:
        session.rollback()
        return ReservationResult(call_id, False, call.status, "STALE_FENCE", call.fence_token)
    if not allow_reconcile_override and not _call_fence_is_current(session, call):
        session.rollback()
        return ReservationResult(call_id, False, call.status, "STALE_FENCE", call.fence_token)
    if allow_reconcile_override and status != "RECONCILED":
        session.rollback()
        return ReservationResult(
            call_id, False, call.status, "RECONCILE_ONLY_OVERRIDE", call.fence_token
        )
    if call.status in {"CANCELLED", "COMPLETED", "FAILED", "RECONCILED"}:
        session.commit()
        return ReservationResult(call_id, True, call.status, "TERMINAL", call.fence_token)
    if status == "CANCELLED" and call.status == "SENT_OUTCOME_UNKNOWN":
        session.commit()
        return ReservationResult(
            call_id, False, call.status, "DISPATCH_OUTCOME_UNKNOWN", call.fence_token
        )
    if status in {"COMPLETED", "FAILED", "RECONCILED"} and call.status != "SENT_OUTCOME_UNKNOWN":
        session.commit()
        return ReservationResult(call_id, False, call.status, "NOT_DISPATCHED", call.fence_token)
    if actual_cost_usd is not None:
        call.actual_cost_usd = _money(
            actual_cost_usd, name="actual_cost_usd", maximum=MAX_ACTUAL_USD
        )
        if call.actual_cost_usd > call.max_cost_usd:
            blocked_reason = "ACTUAL_COST_EXCEEDED_RESERVED_MAXIMUM"
            delta = call.actual_cost_usd - call.max_cost_usd
            for scope_period in call.budget_scopes:
                if scope_period["period"] in {"daily", "monthly"}:
                    session.execute(
                        update(LogicalCallBudget)
                        .where(
                            LogicalCallBudget.scope == scope_period["scope"],
                            LogicalCallBudget.period == scope_period["period"],
                            LogicalCallBudget.period_key == scope_period["period_key"],
                        )
                        .values(cost_usd=LogicalCallBudget.cost_usd + delta)
                    )
    for name, value in (("input_tokens", input_tokens), ("output_tokens", output_tokens)):
        if value is not None and (isinstance(value, bool) or value < 0 or value > 2**63 - 1):
            session.rollback()
            raise ValueError(f"{name} must be a nonnegative finite integer")
        setattr(call, name, value)
    call.result_digest = result_digest
    call.result_payload = result_payload
    call.reconciled_by = reconciliation_actor
    call.reconciliation_ref = reconciliation_ref
    call.status = status
    call.blocked_reason = blocked_reason
    call.finished_at = datetime.now(UTC)
    if status in {"CANCELLED", "COMPLETED", "FAILED", "RECONCILED"}:
        for scope_period in call.budget_scopes:
            stmt = (
                update(LogicalCallBudget)
                .where(
                    LogicalCallBudget.scope == scope_period["scope"],
                    LogicalCallBudget.period == scope_period["period"],
                    LogicalCallBudget.period_key == scope_period["period_key"],
                    LogicalCallBudget.active_count > 0,
                )
                .values(active_count=LogicalCallBudget.active_count - 1)
            )
            session.execute(stmt)
    session.commit()
    return ReservationResult(call_id, False, status, blocked_reason, call.fence_token)


def complete_call(
    session: Session,
    call_id: UUID,
    *,
    fence_token: int,
    actual_cost_usd: Decimal | str | int | float | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    result_digest: str | None = None,
    result_payload: dict[str, Any] | None = None,
) -> ReservationResult:
    return _transition(
        session,
        call_id,
        fence_token=fence_token,
        status="COMPLETED",
        actual_cost_usd=actual_cost_usd,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        result_digest=result_digest,
        result_payload=result_payload,
    )


def fail_call(
    session: Session,
    call_id: UUID,
    *,
    fence_token: int,
    blocked_reason: str | None = None,
    actual_cost_usd: Decimal | str | int | float | None = None,
) -> ReservationResult:
    return _transition(
        session,
        call_id,
        fence_token=fence_token,
        status="FAILED",
        blocked_reason=blocked_reason,
        actual_cost_usd=actual_cost_usd,
    )


def cancel_call(session: Session, call_id: UUID, *, fence_token: int) -> ReservationResult:
    return _transition(session, call_id, fence_token=fence_token, status="CANCELLED")


def reconcile_call(
    session: Session,
    call_id: UUID,
    *,
    fence_token: int,
    actual_cost_usd: Decimal | str | int | float | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    result_digest: str | None = None,
    result_payload: dict[str, Any] | None = None,
    reconciliation_actor: str,
    reconciliation_ref: str,
) -> ReservationResult:
    """Record explicit operator reconciliation after the original lease has ended.

    The caller must authenticate/authorize the operator before invoking this function.
    Actor and ticket/evidence reference are persisted; no dispatch or retry is possible.
    """
    if not reconciliation_actor.strip() or len(reconciliation_actor) > 120:
        raise ValueError("reconciliation_actor is required and limited to 120 characters")
    if not reconciliation_ref.strip() or len(reconciliation_ref) > 200:
        raise ValueError("reconciliation_ref is required and limited to 200 characters")
    return _transition(
        session,
        call_id,
        fence_token=fence_token,
        status="RECONCILED",
        actual_cost_usd=actual_cost_usd,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        result_digest=result_digest,
        result_payload=result_payload,
        allow_reconcile_override=True,
        reconciliation_actor=reconciliation_actor,
        reconciliation_ref=reconciliation_ref,
    )
