"""Durable, capped logical-call reservations. This module never performs network I/O."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gridlens.persistence.models import (
    Job,
    LogicalCall,
    LogicalCallBudget,
    LogicalCallSettlement,
)

MAX_USD = Decimal("100.000000")
MAX_BUDGET_USD = Decimal("100000.000000")
MAX_ACTUAL_USD = Decimal("1000000.000000")
MAX_RESULT_BYTES = 65_536
PROVIDER_QUARANTINE_PREFIX = "BILLING_QUARANTINE:"


def _provider_lock(session: Session, provider: str) -> None:
    """Serialize provider reservations, dispatches, quarantine, and reconciliation."""
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
        {"lock_key": f"gridlens:logical-call-provider:{provider}"},
    )


def _provider_quarantined(session: Session, provider: str) -> bool:
    return (
        session.scalar(
            select(LogicalCall.id)
            .where(
                LogicalCall.provider == provider,
                LogicalCall.status == "SENT_OUTCOME_UNKNOWN",
                LogicalCall.blocked_reason.like(f"{PROVIDER_QUARANTINE_PREFIX}%"),
            )
            .limit(1)
        )
        is not None
    )


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
    estimated_cost_usd: Decimal | str | int | float | None = 0,
    max_cost_usd: Decimal | str | int | float | None = 0,
    financial_budget_mode: str = "finite",
    financial_authorization_ref: str | None = None,
    unlimited_contracts: str = "",
    unlimited_providers: str = "",
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
    if financial_budget_mode not in {"finite", "owner_unlimited"}:
        raise ValueError("unsupported financial_budget_mode")
    unlimited = financial_budget_mode == "owner_unlimited"
    if unlimited and not (financial_authorization_ref and financial_authorization_ref.strip()):
        session.rollback()
        return ReservationResult(None, False, "BLOCKED", "FINANCIAL_AUTHORIZATION_REQUIRED")
    if unlimited and (
        task_type
        not in {value.strip() for value in unlimited_contracts.split(",") if value.strip()}
        or provider
        not in {value.strip() for value in unlimited_providers.split(",") if value.strip()}
    ):
        session.rollback()
        return ReservationResult(None, False, "BLOCKED", "UNLIMITED_CONTRACT_NOT_AUTHORIZED")
    cost = (
        None
        if estimated_cost_usd is None
        else _money(estimated_cost_usd, name="estimated_cost_usd")
    )
    max_cost = None if unlimited else _money(max_cost_usd or 0, name="max_cost_usd")
    if not unlimited and cost is not None and cost > (max_cost or Decimal("0")):
        raise ValueError("estimated call cost exceeds max_cost_usd")
    if fence_token < 0:
        raise ValueError("fence_token must be nonnegative")
    _provider_lock(session, provider)
    if _provider_quarantined(session, provider):
        session.rollback()
        return ReservationResult(None, False, "BLOCKED", "PROVIDER_BILLING_QUARANTINED")
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
    policy_context = context_digest
    if unlimited:
        policy_context = hashlib.sha256(
            json.dumps(
                {
                    "context_digest": context_digest,
                    "financial_budget_mode": financial_budget_mode,
                    "financial_authorization_ref": financial_authorization_ref,
                    "unlimited_contracts": unlimited_contracts,
                    "unlimited_providers": unlimited_providers,
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()
    fingerprint = fingerprint_call(
        task_type=task_type,
        task_key=task_key,
        evidence_digest=evidence_digest,
        context_digest=policy_context,
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
        # A completed semantic call is immutable reusable output. A fresh job
        # may read its result without inheriting the old job lease or reserving
        # budget again; only the original lease can mutate the call.
        if prior.status == "COMPLETED":
            session.commit()
            return ReservationResult(
                prior.id, True, prior.status, prior.blocked_reason, prior.fence_token
            )
        if (
            prior.status == "NOT_SENT"
            and lease_authority == "job"
            and job_id is not None
            and prior.job_id == job_id
            and _assert_job_fence(session, job_id, worker_id or "", fence_token)
        ):
            # The current lease is the only live fence for this job. Rebinding a
            # never-dispatched reservation is safe and preserves its budget
            # reservation; a sent/unknown call can never take this path.
            prior.worker_id = worker_id
            prior.fence_token = fence_token
            session.commit()
            return ReservationResult(prior.id, True, prior.status, None, prior.fence_token)
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
    if not unlimited and (cost is None or max_cost is None or cost <= 0 or max_cost <= 0):
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
            if usd_limit <= 0 and not unlimited:
                session.rollback()
                return ReservationResult(
                    None, False, "BLOCKED", f"{scope_type.upper()}_{period.upper()}_USD_CAP_ZERO"
                )
            if not unlimited and max_cost is not None and max_cost > usd_limit:
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
        context_digest=policy_context,
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
        financial_budget_mode=financial_budget_mode,
        financial_authorization_ref=financial_authorization_ref,
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
                    cost_usd=Decimal("0") if is_active or unlimited else max_cost,
                    active_count=1,
                )
                .on_conflict_do_update(
                    constraint="uq_call_budget_scope_period",
                    set_={
                        "call_count": LogicalCallBudget.call_count + (0 if is_active else 1),
                        "cost_usd": LogicalCallBudget.cost_usd
                        + (Decimal("0") if is_active or unlimited else max_cost),
                        "active_count": LogicalCallBudget.active_count + 1,
                    },
                    where=(LogicalCallBudget.active_count < limit)
                    if is_active
                    else (LogicalCallBudget.call_count < limit)
                    & (
                        True
                        if unlimited
                        else LogicalCallBudget.cost_usd + (max_cost or 0) <= usd_limit
                    ),
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
            select(LogicalCall).where(LogicalCall.fingerprint == fingerprint).with_for_update()
        )
        if duplicate is not None:
            if duplicate.source_id != source_id or duplicate.project_id != project_id:
                session.rollback()
                return ReservationResult(
                    duplicate.id,
                    True,
                    duplicate.status,
                    "IDENTITY_SCOPE_MISMATCH",
                    duplicate.fence_token,
                )
            if not enabled:
                session.rollback()
                return ReservationResult(
                    duplicate.id,
                    True,
                    duplicate.status,
                    "INTELLIGENCE_DISABLED",
                    duplicate.fence_token,
                )
            if (
                duplicate.status == "NOT_SENT"
                and lease_authority == "job"
                and job_id is not None
                and duplicate.job_id == job_id
                and _assert_job_fence(session, job_id, worker_id or "", fence_token)
            ):
                duplicate.worker_id = worker_id
                duplicate.fence_token = fence_token
                session.commit()
                return ReservationResult(
                    duplicate.id, True, duplicate.status, None, duplicate.fence_token
                )
            if duplicate.status != "COMPLETED" and (
                duplicate.lease_authority != lease_authority
                or duplicate.job_id != job_id
                or duplicate.worker_id != worker_id
            ):
                session.rollback()
                return ReservationResult(
                    duplicate.id,
                    True,
                    duplicate.status,
                    "IDENTITY_LEASE_MISMATCH",
                    duplicate.fence_token,
                )
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
    provider = session.scalar(select(LogicalCall.provider).where(LogicalCall.id == call_id))
    if provider is None:
        session.rollback()
        return ReservationResult(call_id, False, "BLOCKED", "CALL_NOT_FOUND")
    _provider_lock(session, provider)
    if _provider_quarantined(session, provider):
        session.rollback()
        return ReservationResult(call_id, False, "BLOCKED", "PROVIDER_BILLING_QUARANTINED")
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


def quarantine_call(
    session: Session,
    call_id: UUID,
    *,
    fence_token: int,
    expected_model: str,
    actual_model: Any,
    reason: str,
    response_payload: dict[str, Any],
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    conservative_exposure_usd: Decimal | str | int | float | None = None,
    exposure_basis: str | None = None,
    exposure_status: str | None = None,
) -> ReservationResult:
    """Durably quarantine a response without completing or releasing its reservation."""
    if not expected_model or not expected_model.strip() or len(expected_model) > 200:
        raise ValueError("expected_model is required and limited to 200 characters")
    if not reason or not reason.strip():
        raise ValueError("quarantine reason is required")
    for name, value in (("input_tokens", input_tokens), ("output_tokens", output_tokens)):
        if value is not None and (type(value) is not int or value < 0 or value > 2**63 - 1):
            raise ValueError(f"{name} must be a nonnegative finite integer")
    provider = session.scalar(select(LogicalCall.provider).where(LogicalCall.id == call_id))
    if provider is None:
        session.rollback()
        return ReservationResult(call_id, False, "BLOCKED", "CALL_NOT_FOUND")
    _provider_lock(session, provider)
    call = session.scalar(select(LogicalCall).where(LogicalCall.id == call_id).with_for_update())
    if call is None:
        session.rollback()
        return ReservationResult(call_id, False, "BLOCKED", "CALL_NOT_FOUND")
    if call.fence_token != fence_token or not _call_fence_is_current(session, call):
        session.rollback()
        return ReservationResult(call_id, False, call.status, "STALE_FENCE", call.fence_token)
    if call.status != "SENT_OUTCOME_UNKNOWN":
        session.rollback()
        return ReservationResult(call_id, False, call.status, "NOT_SENT_OR_ALREADY_TERMINAL")

    reason = reason[:120]
    quarantine_reason = f"{PROVIDER_QUARANTINE_PREFIX}{reason}"
    old_payload = call.result_payload if isinstance(call.result_payload, dict) else {}
    old_quarantine = old_payload.get("billing_quarantine")
    if isinstance(old_quarantine, dict):
        # Never replace first-response evidence. The provider remains frozen until
        # an explicitly authorized reconciliation closes this call.
        session.commit()
        return ReservationResult(call_id, True, call.status, call.blocked_reason, call.fence_token)

    exposure = None
    measured_exposure_status = exposure_status or (
        "BOUNDED" if conservative_exposure_usd is not None else "UNKNOWN"
    )
    if measured_exposure_status not in {"BOUNDED", "UNBOUNDED", "UNKNOWN"}:
        measured_exposure_status = "UNKNOWN"
    if exposure_basis is not None:
        exposure_basis = exposure_basis[:200]
    if conservative_exposure_usd is not None:
        try:
            exposure = _money(
                conservative_exposure_usd,
                name="conservative_exposure_usd",
                maximum=MAX_ACTUAL_USD,
            )
        except (ValueError, ArithmeticError):
            # Retain the provider freeze and original reservation. Never clamp a
            # larger estimate into a misleading bounded amount.
            exposure = None
            measured_exposure_status = "UNBOUNDED"
    prior_budgeted = call.max_cost_usd or Decimal("0")
    if isinstance(old_quarantine, dict):
        try:
            prior_budgeted = max(
                prior_budgeted,
                _money(
                    old_quarantine.get("budgeted_exposure_usd", call.max_cost_usd or 0),
                    name="budgeted_exposure_usd",
                    maximum=MAX_ACTUAL_USD,
                ),
            )
        except ValueError:
            prior_budgeted = call.max_cost_usd or Decimal("0")
    target_exposure = max(prior_budgeted, exposure or Decimal("0"))
    overage = (
        Decimal("0")
        if call.financial_budget_mode == "owner_unlimited"
        else max(Decimal("0"), target_exposure - (call.max_cost_usd or Decimal("0")))
    )
    if overage > 0:
        for scope_period in call.budget_scopes:
            if scope_period["period"] not in {"daily", "monthly"}:
                continue
            updated = session.execute(
                update(LogicalCallBudget)
                .where(
                    LogicalCallBudget.scope == scope_period["scope"],
                    LogicalCallBudget.period == scope_period["period"],
                    LogicalCallBudget.period_key == scope_period["period_key"],
                )
                .values(cost_usd=LogicalCallBudget.cost_usd + overage)
            )
            if updated.rowcount != 1:
                session.rollback()
                raise ValueError("original budget row missing during quarantine")

    quarantine = {
        "reason": reason[:120],
        "expected_model": expected_model[:200],
        "actual_model": actual_model[:200] if isinstance(actual_model, str) else None,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        "response": response_payload,
        "conservative_exposure_usd": str(exposure) if exposure is not None else None,
        "exposure_basis": exposure_basis,
        "exposure_status": measured_exposure_status,
        "budgeted_exposure_usd": (
            str(target_exposure) if call.financial_budget_mode == "finite" else None
        ),
        "financial_budget_mode": call.financial_budget_mode,
        "financial_authorization_ref": call.financial_authorization_ref,
        "max_cost_usd": str(call.max_cost_usd) if call.max_cost_usd is not None else None,
    }
    result = {"billing_quarantine": quarantine}

    def encode_result() -> bytes | None:
        try:
            return json.dumps(
                result,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError, RecursionError, OverflowError):
            return None

    encoded = encode_result()
    if encoded is None or len(encoded) > MAX_RESULT_BYTES:
        safe_identity: dict[str, Any] = {}
        if isinstance(response_payload, dict):
            for key, limit in (("provider_response_id", 256), ("model", 200)):
                scalar = response_payload.get(key)
                if isinstance(scalar, str):
                    safe_identity[key] = scalar[:limit]
        safe_identity["usage"] = {"input_tokens": input_tokens, "output_tokens": output_tokens}
        identity_bytes = json.dumps(
            safe_identity, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        bounded_response: dict[str, Any] = {
            "omitted": "UNSAFE_OR_OVERSIZED_RESPONSE",
            "identity_sha256": hashlib.sha256(identity_bytes).hexdigest(),
            **safe_identity,
        }
        quarantine["response"] = bounded_response
        quarantine["reason"] = "RESPONSE_TOO_LARGE"
        quarantine["expected_model"] = expected_model[:200]
        quarantine["actual_model"] = actual_model[:200] if isinstance(actual_model, str) else None
        quarantine["exposure_basis"] = exposure_basis[:200] if exposure_basis else None
        quarantine_reason = f"{PROVIDER_QUARANTINE_PREFIX}RESPONSE_TOO_LARGE"
        encoded = encode_result()
        if encoded is None or len(encoded) > MAX_RESULT_BYTES:
            # Scalar evidence and token fields have strict bounds; this minimal
            # payload must remain serializable even for hostile direct callers.
            result = {
                "billing_quarantine": {
                    "reason": "RESPONSE_TOO_LARGE",
                    "expected_model": expected_model[:200],
                    "actual_model": actual_model[:200] if isinstance(actual_model, str) else None,
                    "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
                    "response": {"omitted": "UNSAFE_OR_OVERSIZED_RESPONSE"},
                    "conservative_exposure_usd": str(exposure) if exposure is not None else None,
                    "exposure_basis": exposure_basis[:200] if exposure_basis else None,
                    "exposure_status": measured_exposure_status,
                    "budgeted_exposure_usd": (
                        str(target_exposure) if call.financial_budget_mode == "finite" else None
                    ),
                    "financial_budget_mode": call.financial_budget_mode,
                    "financial_authorization_ref": call.financial_authorization_ref,
                    "max_cost_usd": (
                        str(call.max_cost_usd) if call.max_cost_usd is not None else None
                    ),
                }
            }
            encoded = json.dumps(
                result, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
            ).encode("utf-8")
    call.result_payload = result
    call.result_digest = hashlib.sha256(encoded).hexdigest()
    call.input_tokens = input_tokens
    call.output_tokens = output_tokens
    call.blocked_reason = quarantine_reason
    # Keep SENT_OUTCOME_UNKNOWN, finished_at, actual_cost_usd, and active budget
    # count untouched. Only explicit billing reconciliation may release it.
    session.commit()
    return ReservationResult(call_id, False, call.status, quarantine_reason, call.fence_token)


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
    provider = session.scalar(select(LogicalCall.provider).where(LogicalCall.id == call_id))
    if provider is None:
        session.rollback()
        return ReservationResult(call_id, False, "BLOCKED", "CALL_NOT_FOUND")
    _provider_lock(session, provider)
    if result_payload is not None:
        if not isinstance(result_payload, dict):
            raise ValueError("result_payload must be a JSON object")
        try:
            encoded_result = json.dumps(
                result_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("result_payload must contain finite JSON values") from exc
        if len(encoded_result) > MAX_RESULT_BYTES:
            raise ValueError(f"result_payload exceeds {MAX_RESULT_BYTES} bytes")
        canonical_digest = hashlib.sha256(encoded_result).hexdigest()
        if result_digest is not None and result_digest != canonical_digest:
            raise ValueError("result_digest does not match canonical result_payload")
        result_digest = canonical_digest
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
    has_billing_quarantine = isinstance(call.result_payload, dict) and isinstance(
        call.result_payload.get("billing_quarantine"), dict
    )
    if has_billing_quarantine and not allow_reconcile_override:
        session.rollback()
        return ReservationResult(
            call_id,
            False,
            call.status,
            "BILLING_QUARANTINE_RECONCILIATION_REQUIRED",
            call.fence_token,
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
        measured_cost = _money(actual_cost_usd, name="actual_cost_usd", maximum=MAX_ACTUAL_USD)
        if (
            allow_reconcile_override
            and call.actual_cost_usd is not None
            and (call.actual_cost_usd != measured_cost)
        ):
            session.rollback()
            raise ValueError("actual_cost_usd conflicts with previously settled billing evidence")
        call.actual_cost_usd = measured_cost
        prior_budgeted = call.max_cost_usd or Decimal("0")
        old_quarantine = (
            call.result_payload.get("billing_quarantine")
            if isinstance(call.result_payload, dict)
            else None
        )
        if isinstance(old_quarantine, dict):
            try:
                prior_budgeted = max(
                    prior_budgeted,
                    _money(
                        old_quarantine.get("budgeted_exposure_usd", call.max_cost_usd or 0),
                        name="budgeted_exposure_usd",
                        maximum=MAX_ACTUAL_USD,
                    ),
                )
            except ValueError:
                prior_budgeted = call.max_cost_usd or Decimal("0")
        target_budgeted = max(prior_budgeted, measured_cost)
        delta = max(Decimal("0"), target_budgeted - prior_budgeted)
        if call.financial_budget_mode == "finite" and measured_cost > (call.max_cost_usd or 0):
            blocked_reason = blocked_reason or "ACTUAL_COST_EXCEEDED_RESERVED_MAXIMUM"
        if delta > 0 and call.financial_budget_mode == "finite":
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
        if isinstance(old_quarantine, dict):
            if isinstance(call.result_payload, dict):
                updated_quarantine = dict(old_quarantine)
                updated_quarantine["budgeted_exposure_usd"] = (
                    str(target_budgeted) if call.financial_budget_mode == "finite" else None
                )
                updated_quarantine["reconciled_actual_cost_usd"] = str(measured_cost)
                updated_payload = dict(call.result_payload)
                updated_payload["billing_quarantine"] = updated_quarantine
                call.result_payload = updated_payload
                call.result_digest = hashlib.sha256(
                    json.dumps(
                        updated_payload,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=True,
                        allow_nan=False,
                    ).encode("utf-8")
                ).hexdigest()
    for name, value in (("input_tokens", input_tokens), ("output_tokens", output_tokens)):
        if allow_reconcile_override and value is None and getattr(call, name) is not None:
            continue
        if value is not None and (type(value) is not int or value < 0 or value > 2**63 - 1):
            session.rollback()
            raise ValueError(f"{name} must be a nonnegative finite integer")
        setattr(call, name, value)
    if allow_reconcile_override and isinstance(call.result_payload, dict):
        existing_quarantine = call.result_payload.get("billing_quarantine")
        if isinstance(existing_quarantine, dict):
            if result_payload is None:
                result_payload = call.result_payload
                result_digest = call.result_digest
            else:
                result_payload = {
                    "billing_quarantine": existing_quarantine,
                    "reconciliation_result": result_payload,
                }
                encoded_result = json.dumps(
                    result_payload,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                    allow_nan=False,
                ).encode("utf-8")
                if len(encoded_result) > MAX_RESULT_BYTES:
                    session.rollback()
                    raise ValueError("reconciled result exceeds logical-call result bound")
                result_digest = hashlib.sha256(encoded_result).hexdigest()
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
    conclusive_response_ref: str | None = None,
) -> ReservationResult:
    # A sent request without a conclusive provider response remains UNKNOWN;
    # releasing its active budget slot would permit an unsafe blind retry.
    if conclusive_response_ref is not None and not conclusive_response_ref.strip():
        raise ValueError("conclusive_response_ref must be nonempty")
    if conclusive_response_ref is not None and len(conclusive_response_ref) > 200:
        raise ValueError("conclusive_response_ref is limited to 200 characters")
    call = session.get(LogicalCall, call_id)
    if call is not None and call.status == "SENT_OUTCOME_UNKNOWN" and not conclusive_response_ref:
        session.rollback()
        return ReservationResult(
            call_id, False, call.status, "CONCLUSIVE_RESPONSE_REQUIRED", call.fence_token
        )
    return _transition(
        session,
        call_id,
        fence_token=fence_token,
        status="FAILED",
        blocked_reason=blocked_reason,
        actual_cost_usd=actual_cost_usd,
        result_payload=(
            {"provider_response_ref": conclusive_response_ref}
            if conclusive_response_ref is not None
            else None
        ),
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
    provider = session.scalar(select(LogicalCall.provider).where(LogicalCall.id == call_id))
    if provider is None:
        session.rollback()
        raise ValueError("logical call not found")
    _provider_lock(session, provider)
    quarantined_call = session.scalar(
        select(LogicalCall).where(LogicalCall.id == call_id).with_for_update()
    )
    if (
        quarantined_call is not None
        and isinstance(quarantined_call.result_payload, dict)
        and isinstance(quarantined_call.result_payload.get("billing_quarantine"), dict)
        and actual_cost_usd is None
        and quarantined_call.actual_cost_usd is None
    ):
        session.rollback()
        raise ValueError("billing quarantine requires attributable actual-cost evidence")
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


def settle_call(
    session: Session,
    call_id: UUID,
    *,
    actor: str,
    receipt_ref: str,
    actual_cost_usd: Decimal | str | int | float | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> tuple[LogicalCallSettlement, bool]:
    """Append billing evidence and fill only previously unknown call measurements."""
    if not actor.strip() or len(actor) > 120:
        raise ValueError("actor is required and limited to 120 characters")
    if not receipt_ref.strip() or len(receipt_ref) > 200:
        raise ValueError("receipt_ref is required and limited to 200 characters")
    if all(value is None for value in (actual_cost_usd, input_tokens, output_tokens)):
        raise ValueError("at least one measured field is required")
    cost = None
    if actual_cost_usd is not None:
        try:
            exact_cost = Decimal(str(actual_cost_usd))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("actual_cost_usd must be a finite decimal") from exc
        if not exact_cost.is_finite() or exact_cost.quantize(Decimal("0.000001")) != exact_cost:
            raise ValueError("actual_cost_usd must have at most six decimal places")
        cost = _money(exact_cost, name="actual_cost_usd", maximum=MAX_ACTUAL_USD)
    for name, value in (("input_tokens", input_tokens), ("output_tokens", output_tokens)):
        if value is not None and (type(value) is not int or value < 0 or value > 2**63 - 1):
            raise ValueError(f"{name} must be a nonnegative finite integer")

    provider = session.scalar(select(LogicalCall.provider).where(LogicalCall.id == call_id))
    if provider is None:
        session.rollback()
        raise ValueError("logical call not found")
    _provider_lock(session, provider)
    call = session.scalar(select(LogicalCall).where(LogicalCall.id == call_id).with_for_update())
    if call is None:
        session.rollback()
        raise ValueError("logical call not found")
    if call.status not in {"SENT_OUTCOME_UNKNOWN", "COMPLETED", "FAILED", "RECONCILED"}:
        session.rollback()
        raise ValueError("settlement requires a dispatched logical call")
    prior = session.scalar(
        select(LogicalCallSettlement).where(
            LogicalCallSettlement.call_id == call_id,
            LogicalCallSettlement.receipt_ref == receipt_ref,
        )
    )
    values = (cost, input_tokens, output_tokens)
    if prior is not None:
        prior_values = (prior.actual_cost_usd, prior.input_tokens, prior.output_tokens)
        if prior.actor != actor or prior_values != values:
            session.rollback()
            raise ValueError("receipt reference already exists with different settlement data")
        session.commit()
        return prior, True

    for name, settlement_value in (
        ("actual_cost_usd", cost),
        ("input_tokens", input_tokens),
        ("output_tokens", output_tokens),
    ):
        known = getattr(call, name)
        if settlement_value is not None and known is not None and known != settlement_value:
            session.rollback()
            raise ValueError(f"{name} is already settled with a different value")

    receipt = LogicalCallSettlement(
        call_id=call_id,
        actor=actor,
        receipt_ref=receipt_ref,
        actual_cost_usd=cost,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    session.add(receipt)
    if cost is not None and call.actual_cost_usd is None:
        call.actual_cost_usd = cost
        prior_budgeted = call.max_cost_usd or Decimal("0")
        quarantine = (
            call.result_payload.get("billing_quarantine")
            if isinstance(call.result_payload, dict)
            else None
        )
        if isinstance(quarantine, dict):
            try:
                prior_budgeted = max(
                    prior_budgeted,
                    _money(
                        quarantine.get("budgeted_exposure_usd", call.max_cost_usd or 0),
                        name="budgeted_exposure_usd",
                        maximum=MAX_ACTUAL_USD,
                    ),
                )
            except ValueError:
                prior_budgeted = call.max_cost_usd or Decimal("0")
        target_budgeted = max(prior_budgeted, cost)
        delta = max(Decimal("0"), target_budgeted - prior_budgeted)
        if delta > 0 and call.financial_budget_mode == "finite":
            for scope_period in call.budget_scopes:
                if scope_period["period"] not in {"daily", "monthly"}:
                    continue
                updated = session.execute(
                    update(LogicalCallBudget)
                    .where(
                        LogicalCallBudget.scope == scope_period["scope"],
                        LogicalCallBudget.period == scope_period["period"],
                        LogicalCallBudget.period_key == scope_period["period_key"],
                    )
                    .values(cost_usd=LogicalCallBudget.cost_usd + delta)
                )
                if updated.rowcount != 1:
                    session.rollback()
                    raise ValueError("original budget row missing during overage settlement")
        if isinstance(quarantine, dict):
            if isinstance(call.result_payload, dict):
                updated_quarantine = dict(quarantine)
                updated_quarantine["budgeted_exposure_usd"] = (
                    str(target_budgeted) if call.financial_budget_mode == "finite" else None
                )
                updated_quarantine["reconciled_actual_cost_usd"] = str(cost)
                updated_payload = dict(call.result_payload)
                updated_payload["billing_quarantine"] = updated_quarantine
                call.result_payload = updated_payload
                call.result_digest = hashlib.sha256(
                    json.dumps(
                        updated_payload,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=True,
                        allow_nan=False,
                    ).encode("utf-8")
                ).hexdigest()
    if input_tokens is not None and call.input_tokens is None:
        call.input_tokens = input_tokens
    if output_tokens is not None and call.output_tokens is None:
        call.output_tokens = output_tokens
    session.commit()
    session.refresh(receipt)
    return receipt, False
