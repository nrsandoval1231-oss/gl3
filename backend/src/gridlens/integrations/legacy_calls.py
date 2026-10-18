"""Compatibility adapter for paid legacy workers on the shared logical-call ledger."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from gridlens.integrations.logical_calls import (
    complete_call,
    fail_call,
    mark_dispatched,
    quarantine_call,
    reserve_call,
)
from gridlens.intelligence.intelligence_jobs import (
    _billing_policy_identity,
    _bounded_cost_exposure,
    _caps,
    _cost_bound,
    _dispatch_policy,
    _enabled,
    _provider_audit_exceeds_bound,
    _provider_error_quarantine_details,
    _safe_provider_audit,
)
from gridlens.persistence.database import SessionLocal
from gridlens.persistence.models import LogicalCall
from gridlens.settings import settings


class LegacyCallBlocked(RuntimeError):
    """The shared policy does not permit this compatibility call."""


class LegacyCallUnknown(RuntimeError):
    """A previous dispatch has no conclusive response; retry is prohibited."""


@dataclass(frozen=True)
class LegacyCallResult:
    logical_call_id: UUID
    result: dict[str, Any]
    input_tokens: int | None
    output_tokens: int | None
    cached: bool


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def perform_legacy_call(
    *,
    task_type: str,
    task_key: str,
    payload: dict[str, Any],
    source_id: str | None,
    project_id: UUID | None,
    job_id: UUID | None,
    worker_id: str | None,
    fence_token: int,
    invoke: Callable[[], tuple[dict[str, Any], int | None, int | None]],
    before_dispatch: Callable[[UUID], None] | None = None,
) -> LegacyCallResult:
    """Reserve, durably mark uncertain, call once, and complete one provider intent.

    Network exceptions intentionally leave ``SENT_OUTCOME_UNKNOWN`` in the ledger.
    Callers may preserve the same id in their own JSON receipt, but must not retry it.
    """
    enabled, provider, model, reason = _enabled(task_type)
    if not enabled:
        raise LegacyCallBlocked(reason)
    max_cost = _cost_bound(provider, task_type, payload)
    if (
        max_cost <= 0
        or settings.intelligence_max_call_usd <= 0
        or max_cost > settings.intelligence_max_call_usd
        or settings.intelligence_max_active_calls <= 0
    ):
        raise LegacyCallBlocked("FINITE_BUDGET_REQUIRED")
    digest = _digest(payload)
    evidence_digest = _digest(payload.get("evidence", payload.get("evidence_id", digest)))
    billing_policy = _billing_policy_identity(provider, model, task_type)
    context_digest = _digest({"payload": payload, "billing_policy": billing_policy})
    call_caps: dict[str, dict[str, int | Decimal | str | float]] = {
        scope: {name: value for name, value in limits.items()} for scope, limits in _caps().items()
    }
    with SessionLocal() as session:
        reservation = reserve_call(
            session,
            task_type=task_type,
            task_key=task_key[:200],
            evidence_digest=evidence_digest,
            context_digest=context_digest,
            prompt_contract=f"legacy-{task_type.casefold()}-v1",
            provider=provider,
            model=model,
            policy_version="legacy-shared-ledger-v1",
            source_id=source_id,
            project_id=project_id,
            lease_authority="job" if job_id is not None else "standalone",
            job_id=job_id,
            worker_id=worker_id,
            enabled=True,
            estimated_cost_usd=max_cost,
            max_cost_usd=max_cost,
            caps=call_caps,
            max_active=settings.intelligence_max_active_calls,
            fence_token=fence_token,
        )
    if reservation.call_id is None or reservation.blocked_reason:
        raise LegacyCallBlocked(reservation.blocked_reason or "LEDGER_RESERVATION_FAILED")
    call_id = reservation.call_id
    if reservation.status == "COMPLETED":
        with SessionLocal() as session:
            call = session.get(LogicalCall, call_id)
            if call is None or not isinstance(call.result_payload, dict):
                raise LegacyCallUnknown("COMPLETED_RESPONSE_UNAVAILABLE")
            return LegacyCallResult(
                call_id, call.result_payload, call.input_tokens, call.output_tokens, True
            )
    if reservation.status != "NOT_SENT":
        raise LegacyCallUnknown(reservation.status)
    if before_dispatch:
        try:
            before_dispatch(call_id)
        except Exception:
            with SessionLocal() as session:
                from gridlens.integrations.logical_calls import cancel_call

                cancel_call(session, call_id, fence_token=fence_token)
            raise
    enabled, current_provider, current_model, reason = _enabled(task_type)
    policy_ok = bool(enabled and provider == current_provider and model == current_model)
    policy_ok = (
        policy_ok
        and not _dispatch_policy(
            task_type,
            None,
            provider,
            model,
            payload,
            max_cost,
            billing_policy,
        )[1]
    )
    with SessionLocal() as session:
        dispatched = mark_dispatched(session, call_id, fence_token=fence_token, enabled=policy_ok)
    if dispatched.status != "SENT_OUTCOME_UNKNOWN" or dispatched.blocked_reason:
        raise LegacyCallBlocked(reason or dispatched.blocked_reason or "DISPATCH_NOT_AUTHORIZED")
    try:
        result, input_tokens, output_tokens = invoke()
    except Exception as exc:
        error_quarantine = _provider_error_quarantine_details(
            exc, provider=provider, task_type=task_type, expected_model=model
        )
        if error_quarantine is not None:
            with SessionLocal() as session:
                quarantined = quarantine_call(
                    session,
                    call_id,
                    fence_token=fence_token,
                    expected_model=model,
                    actual_model=error_quarantine["actual_model"],
                    reason=error_quarantine["reason"],
                    response_payload=error_quarantine["response_payload"],
                    input_tokens=error_quarantine["input_tokens"],
                    output_tokens=error_quarantine["output_tokens"],
                    conservative_exposure_usd=error_quarantine[
                        "conservative_exposure_usd"
                    ],
                    exposure_basis=error_quarantine["exposure_basis"],
                    exposure_status=error_quarantine["exposure_status"],
                )
            raise LegacyCallUnknown(
                quarantined.blocked_reason or error_quarantine["reason"]
            ) from exc
        response_id = getattr(exc, "request_id", None)
        response_status = getattr(exc, "response_status", None)
        if (
            provider in {"typesafe", "openai"}
            and getattr(exc, "conclusive", False)
            and isinstance(response_status, int)
            and 400 <= response_status < 500
        ):
            response_ref = (
                f"response:{response_id}"
                if response_id
                else f"http-status:{response_status}:{call_id}"
            )
            with SessionLocal() as session:
                fail_call(
                    session,
                    call_id,
                    fence_token=fence_token,
                    blocked_reason=type(exc).__name__,
                    conclusive_response_ref=response_ref,
                )
        raise
    if not isinstance(result, dict):
        raise ValueError("Legacy provider result must be a JSON object")
    if provider in {"typesafe", "openai"}:
        actual_model = result.get("actual_model", result.get("model"))
        raw_usage_present = "usage" in result
        raw_usage = result.get("usage")
        quarantine_reason: str | None = (
            "MODEL_IDENTITY_MISMATCH" if actual_model != model else None
        )
        if quarantine_reason is None and _provider_audit_exceeds_bound(result):
            quarantine_reason = "RESPONSE_TOO_LARGE"
        if (
            quarantine_reason is None
            and raw_usage_present
            and raw_usage is not None
            and not isinstance(raw_usage, dict)
        ):
            quarantine_reason = "INVALID_REPORTED_USAGE"
        if quarantine_reason is None and any(
            value is not None and (type(value) is not int or value < 0 or value > 2**63 - 1)
            for value in (input_tokens, output_tokens)
        ):
            quarantine_reason = "INVALID_REPORTED_USAGE"
        if (
            quarantine_reason is None
            and provider == "typesafe"
            and input_tokens is not None
            and input_tokens > settings.intelligence_typesafe_max_total_billable_input_tokens
        ):
            quarantine_reason = "TOTAL_BILLABLE_INPUT_CEILING_EXCEEDED"
        output_bound = None
        if provider == "openai":
            prefix = "fast" if task_type == "GROUNDED_EXTRACTION" else "reasoning"
            output_bound = getattr(settings, f"intelligence_openai_{prefix}_max_output_tokens")
            if (
                quarantine_reason is None
                and type(output_tokens) is int
                and 0 <= output_tokens <= 2**63 - 1
                and output_tokens > output_bound
            ):
                quarantine_reason = "ENFORCED_OUTPUT_BOUND_EXCEEDED"
        if quarantine_reason:
            exposure = None
            exposure_status = "UNKNOWN"
            exposure_basis = None
            if (
                actual_model == model
                and type(input_tokens) is int
                and 0 <= input_tokens <= 2**63 - 1
            ):
                if provider == "typesafe":
                    exposure, exposure_status = _bounded_cost_exposure(
                        provider, task_type, input_tokens, 0
                    )
                    exposure_basis = "reported_same_model_input_tokens_at_pinned_input_rate"
                elif type(output_tokens) is int and 0 <= output_tokens <= 2**63 - 1:
                    exposure, exposure_status = _bounded_cost_exposure(
                        provider, task_type, input_tokens, output_tokens
                    )
                    exposure_basis = "reported_same_model_usage_at_pinned_rates"
            with SessionLocal() as session:
                quarantined = quarantine_call(
                    session,
                    call_id,
                    fence_token=fence_token,
                    expected_model=model,
                    actual_model=actual_model,
                    reason=quarantine_reason,
                    response_payload=_safe_provider_audit(result),
                    input_tokens=(
                        input_tokens
                        if type(input_tokens) is int and 0 <= input_tokens <= 2**63 - 1
                        else None
                    ),
                    output_tokens=output_tokens
                    if type(output_tokens) is int and 0 <= output_tokens <= 2**63 - 1
                    else None,
                    conservative_exposure_usd=exposure,
                    exposure_basis=exposure_basis,
                    exposure_status=exposure_status,
                )
            raise LegacyCallUnknown(quarantined.blocked_reason or quarantine_reason)
    with SessionLocal() as session:
        completed = complete_call(
            session,
            call_id,
            fence_token=fence_token,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            result_digest=_digest(result),
            result_payload=result,
        )
    if completed.status != "COMPLETED" or completed.blocked_reason:
        raise LegacyCallUnknown(completed.blocked_reason or completed.status)
    return LegacyCallResult(call_id, result, input_tokens, output_tokens, False)
