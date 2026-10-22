import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from gridlens.integrations.logical_calls import (
    cancel_call,
    complete_call,
    mark_dispatched,
    quarantine_call,
    reconcile_call,
    reserve_call,
    settle_call,
)
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    Job,
    LogicalCall,
    LogicalCallBudget,
    LogicalCallSettlement,
    Source,
)
from gridlens.settings import settings


@pytest.fixture
def sessions():
    target = make_url(settings.test_database_url)
    assert target.database and target.database.endswith("_test")
    assert target != make_url(settings.database_url)
    engine = create_engine(settings.test_database_url, pool_size=8)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _reserve(factory, key: str, *, daily: int = 10, max_active: int = 10):
    with factory() as session:
        return reserve_call(
            session,
            task_type="JEV_TEST",
            task_key=key,
            evidence_digest="a" * 64,
            context_digest="b" * 64,
            prompt_contract="v1",
            provider="typesafe",
            model="fixture-model",
            policy_version="policy-v1",
            enabled=True,
            lease_authority="standalone",
            estimated_cost_usd=Decimal("0.01"),
            max_cost_usd=Decimal("0.02"),
            caps={
                scope: {
                    "daily": daily,
                    "monthly": daily,
                    "daily_usd": "1.00",
                    "monthly_usd": "10.00",
                }
                for scope in ("global", "provider", "model") + ("source",)
            },
            max_active=max_active,
            fence_token=7,
        )


def test_reservation_reuse_unknown_dispatch_and_fences(sessions):
    first = _reserve(sessions, "same")
    again = _reserve(sessions, "same")
    assert first.call_id == again.call_id
    assert again.reused and again.status == "NOT_SENT"
    with sessions() as session:
        denied = mark_dispatched(session, first.call_id, fence_token=7)
        assert denied.blocked_reason == "INTELLIGENCE_DISABLED"
    with sessions() as session:
        dispatched = mark_dispatched(session, first.call_id, fence_token=7, enabled=True)
    assert dispatched.status == "SENT_OUTCOME_UNKNOWN"
    with sessions() as session:
        assert (
            cancel_call(session, first.call_id, fence_token=7).blocked_reason
            == "DISPATCH_OUTCOME_UNKNOWN"
        )
    with sessions() as session:
        assert complete_call(session, first.call_id, fence_token=6).blocked_reason == "STALE_FENCE"
    with sessions() as session:
        completed = complete_call(
            session,
            first.call_id,
            fence_token=7,
            input_tokens=None,
            result_payload={"choice": "ADVISORY"},
            actual_cost_usd="0.05",
        )
    assert completed.status == "COMPLETED"
    assert completed.blocked_reason == "ACTUAL_COST_EXCEEDED_RESERVED_MAXIMUM"
    with sessions() as session:
        row = session.scalar(select(LogicalCall).where(LogicalCall.id == first.call_id))
        assert row and row.status == "COMPLETED" and row.input_tokens is None
        assert row.result_payload == {"choice": "ADVISORY"}
        budget = session.scalar(
            select(LogicalCallBudget).where(
                LogicalCallBudget.scope == "global:global", LogicalCallBudget.period == "daily"
            )
        )
        assert budget and budget.call_count == 1 and budget.active_count == 0
        assert budget.cost_usd == Decimal("0.050000")


def test_owner_unlimited_skips_only_usd_reservation_and_keeps_count_caps(sessions):
    caps = {
        scope: {"daily": 2, "monthly": 2, "daily_usd": 0, "monthly_usd": 0}
        for scope in ("global", "provider", "model")
    }
    with sessions() as session:
        denied = reserve_call(
            session,
            task_type="MATERIALITY_V1",
            task_key="missing-auth",
            evidence_digest="a" * 64,
            context_digest="b" * 64,
            prompt_contract="v1",
            provider="typesafe",
            model="jev-1.13.0",
            policy_version="policy-v1",
            enabled=True,
            lease_authority="standalone",
            financial_budget_mode="owner_unlimited",
            unlimited_contracts="MATERIALITY_V1",
            unlimited_providers="typesafe",
            caps=caps,
            max_active=1,
            fence_token=1,
        )
    assert denied.blocked_reason == "FINANCIAL_AUTHORIZATION_REQUIRED"

    with sessions() as session:
        reserved = reserve_call(
            session,
            task_type="MATERIALITY_V1",
            task_key="owner-unlimited",
            evidence_digest="a" * 64,
            context_digest="b" * 64,
            prompt_contract="v1",
            provider="typesafe",
            model="jev-1.13.0",
            policy_version="policy-v1",
            enabled=True,
            lease_authority="standalone",
            estimated_cost_usd=None,
            max_cost_usd=None,
            financial_budget_mode="owner_unlimited",
            financial_authorization_ref="owner-approval-1",
            unlimited_contracts="MATERIALITY_V1",
            unlimited_providers="typesafe",
            caps=caps,
            max_active=1,
            fence_token=1,
        )
    assert reserved.status == "NOT_SENT" and reserved.call_id
    with sessions() as session:
        row = session.get(LogicalCall, reserved.call_id)
        assert row and row.max_cost_usd is None and row.estimated_cost_usd is None
        assert row.financial_budget_mode == "owner_unlimited"
        assert row.financial_authorization_ref == "owner-approval-1"
        global_budget = session.scalar(
            select(LogicalCallBudget).where(
                LogicalCallBudget.scope == "global:global",
                LogicalCallBudget.period == "daily",
            )
        )
        assert global_budget and global_budget.call_count == 1
        assert global_budget.cost_usd == 0 and global_budget.active_count == 1


def test_billing_quarantine_holds_exposure_blocks_provider_and_is_idempotent(sessions):
    sent = _reserve(sessions, "quarantine-sent")
    already_reserved = _reserve(sessions, "quarantine-pre-reserved")
    with sessions() as session:
        assert mark_dispatched(session, sent.call_id, fence_token=7, enabled=True).status == (
            "SENT_OUTCOME_UNKNOWN"
        )
    evidence = {
        "model": "fixture-model",
        "usage": {"input_tokens": 50_000, "output_tokens": 3},
        "output": {"fixture": "raw provider response"},
    }
    with sessions() as session:
        quarantined = quarantine_call(
            session,
            sent.call_id,
            fence_token=7,
            expected_model="fixture-model",
            actual_model="fixture-model",
            reason="TOTAL_BILLABLE_INPUT_CEILING_EXCEEDED",
            response_payload=evidence,
            input_tokens=50_000,
            output_tokens=3,
            conservative_exposure_usd="0.030000",
            exposure_basis="synthetic-fixture-input-rate",
        )
    assert quarantined.status == "SENT_OUTCOME_UNKNOWN"
    assert quarantined.blocked_reason == (
        "BILLING_QUARANTINE:TOTAL_BILLABLE_INPUT_CEILING_EXCEEDED"
    )
    with sessions() as session:
        row = session.get(LogicalCall, sent.call_id)
        global_daily = session.scalar(
            select(LogicalCallBudget).where(
                LogicalCallBudget.scope == "global:global",
                LogicalCallBudget.period == "daily",
            )
        )
        assert row and row.actual_cost_usd is None and row.finished_at is None
        assert row.result_payload["billing_quarantine"]["response"] == evidence
        assert global_daily and global_daily.active_count == 2
        assert global_daily.cost_usd == Decimal("0.050000")
    from gridlens.integrations.logical_calls import fail_call

    for terminalize in (
        lambda session: complete_call(
            session, sent.call_id, fence_token=7, result_payload={"answer": "must not complete"}
        ),
        lambda session: fail_call(
            session,
            sent.call_id,
            fence_token=7,
            blocked_reason="conclusive",
            conclusive_response_ref="synthetic-response",
        ),
    ):
        with sessions() as session:
            blocked_terminal = terminalize(session)
        assert blocked_terminal.blocked_reason == "BILLING_QUARANTINE_RECONCILIATION_REQUIRED"
    with sessions() as session:
        row = session.get(LogicalCall, sent.call_id)
        budget = session.scalar(
            select(LogicalCallBudget).where(
                LogicalCallBudget.scope == "global:global", LogicalCallBudget.period == "daily"
            )
        )
    assert row and row.status == "SENT_OUTCOME_UNKNOWN" and row.finished_at is None
    assert budget and budget.active_count == 2 and budget.cost_usd == Decimal("0.050000")
    with (
        sessions() as session,
        pytest.raises(ValueError, match="requires attributable actual-cost evidence"),
    ):
        reconcile_call(
            session,
            sent.call_id,
            fence_token=7,
            reconciliation_actor="synthetic operator",
            reconciliation_ref="not billing evidence",
        )
    with sessions() as session:
        repeated = quarantine_call(
            session,
            sent.call_id,
            fence_token=7,
            expected_model="fixture-model",
            actual_model="fixture-model",
            reason="TOTAL_BILLABLE_INPUT_CEILING_EXCEEDED",
            response_payload=evidence,
            input_tokens=50_000,
            output_tokens=3,
            conservative_exposure_usd="0.030000",
            exposure_basis="synthetic-fixture-input-rate",
        )
    assert repeated.reused
    with sessions() as session:
        blocked_dispatch = mark_dispatched(
            session, already_reserved.call_id, fence_token=7, enabled=True
        )
    assert blocked_dispatch.blocked_reason == "PROVIDER_BILLING_QUARANTINED"
    new_call = _reserve(sessions, "quarantine-new-call")
    assert new_call.call_id is None and new_call.blocked_reason == "PROVIDER_BILLING_QUARANTINED"

    with sessions() as session:
        _receipt, replayed = settle_call(
            session,
            sent.call_id,
            actor="synthetic-fixture",
            receipt_ref="synthetic-invoice-1",
            actual_cost_usd="0.040000",
            input_tokens=50_000,
        )
    assert not replayed
    with sessions() as session:
        _receipt, replayed = settle_call(
            session,
            sent.call_id,
            actor="synthetic-fixture",
            receipt_ref="synthetic-invoice-1",
            actual_cost_usd="0.040000",
            input_tokens=50_000,
        )
    assert replayed
    with sessions() as session:
        row = session.get(LogicalCall, sent.call_id)
        global_daily = session.scalar(
            select(LogicalCallBudget).where(
                LogicalCallBudget.scope == "global:global",
                LogicalCallBudget.period == "daily",
            )
        )
        assert row and row.status == "SENT_OUTCOME_UNKNOWN"
        assert row.actual_cost_usd == Decimal("0.040000")
        assert global_daily and global_daily.cost_usd == Decimal("0.060000")
        canonical = json.dumps(
            row.result_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
        assert row.result_digest == hashlib.sha256(canonical).hexdigest()
    still_blocked = _reserve(sessions, "quarantine-settled-still-blocked")
    assert still_blocked.call_id is None
    assert still_blocked.blocked_reason == "PROVIDER_BILLING_QUARANTINED"
    with sessions() as session:
        reconciled = reconcile_call(
            session,
            sent.call_id,
            fence_token=7,
            actual_cost_usd="0.040000",
            reconciliation_actor="synthetic operator",
            reconciliation_ref="synthetic invoice review",
        )
    assert reconciled.status == "RECONCILED"
    with sessions() as session:
        row = session.get(LogicalCall, sent.call_id)
        global_daily = session.scalar(
            select(LogicalCallBudget).where(
                LogicalCallBudget.scope == "global:global",
                LogicalCallBudget.period == "daily",
            )
        )
        assert row and row.result_payload["billing_quarantine"]["response"] == evidence
        assert global_daily and global_daily.active_count == 1
        assert global_daily.cost_usd == Decimal("0.060000")
    after_reconcile = _reserve(sessions, "quarantine-reconciled-provider-unfrozen")
    assert after_reconcile.call_id is not None and after_reconcile.status == "NOT_SENT"


def test_quarantine_unrepresentable_estimate_keeps_unknown_provider_freeze(sessions):
    call = _reserve(sessions, "unrepresentable-quarantine-cost")
    with sessions() as session:
        mark_dispatched(session, call.call_id, fence_token=7, enabled=True)
    with sessions() as session:
        quarantined = quarantine_call(
            session,
            call.call_id,
            fence_token=7,
            expected_model="fixture-model",
            actual_model="fixture-model",
            reason="UNBOUNDED_USAGE_COST",
            response_payload={"model": "fixture-model"},
            input_tokens=2**63 - 1,
            conservative_exposure_usd="999999999999999999999999999",
            exposure_basis="x" * 100_000,
            exposure_status="UNBOUNDED" + "x" * 100_000,
        )
    assert quarantined.status == "SENT_OUTCOME_UNKNOWN"
    with sessions() as session:
        row = session.get(LogicalCall, call.call_id)
        budget = session.scalar(
            select(LogicalCallBudget).where(
                LogicalCallBudget.scope == "global:global", LogicalCallBudget.period == "daily"
            )
        )
    assert row and row.actual_cost_usd is None and row.finished_at is None
    quarantine = row.result_payload["billing_quarantine"]
    assert quarantine["exposure_status"] == "UNBOUNDED"
    assert quarantine["conservative_exposure_usd"] is None
    assert len(quarantine["exposure_basis"]) <= 200
    assert budget and budget.active_count == 1


def test_billing_quarantine_rejects_stale_fence_without_mutation(sessions):
    call = _reserve(sessions, "quarantine-stale-fence")
    with sessions() as session:
        mark_dispatched(session, call.call_id, fence_token=7, enabled=True)
    with sessions() as session:
        stale = quarantine_call(
            session,
            call.call_id,
            fence_token=6,
            expected_model="fixture-model",
            actual_model="other-model",
            reason="MODEL_IDENTITY_MISMATCH",
            response_payload={"model": "other-model"},
        )
    assert stale.blocked_reason == "STALE_FENCE"
    with sessions() as session:
        row = session.get(LogicalCall, call.call_id)
        assert row and row.status == "SENT_OUTCOME_UNKNOWN"
        assert row.blocked_reason is None and row.result_payload is None


def test_provider_lock_serializes_quarantine_against_new_reservation(sessions):
    from threading import Event

    from gridlens.integrations.logical_calls import _provider_lock

    dispatched = _reserve(sessions, "quarantine-lock-dispatched")
    with sessions() as session:
        mark_dispatched(session, dispatched.call_id, fence_token=7, enabled=True)
    started = Event()

    def competing_reservation():
        started.set()
        return _reserve(sessions, "quarantine-lock-race")

    with ThreadPoolExecutor(max_workers=1) as pool:
        with sessions() as session:
            _provider_lock(session, "typesafe")
            future = pool.submit(competing_reservation)
            assert started.wait(timeout=5)
            quarantined = quarantine_call(
                session,
                dispatched.call_id,
                fence_token=7,
                expected_model="fixture-model",
                actual_model="other-model",
                reason="MODEL_IDENTITY_MISMATCH",
                response_payload={"model": "other-model"},
            )
            assert quarantined.status == "SENT_OUTCOME_UNKNOWN"
        raced = future.result(timeout=5)
    assert raced.call_id is None
    assert raced.blocked_reason == "PROVIDER_BILLING_QUARANTINED"


def test_completed_result_payload_is_canonical_bounded_and_self_consistent(sessions):
    import hashlib
    import json

    first = _reserve(sessions, "canonical-result")
    with sessions() as session:
        assert mark_dispatched(session, first.call_id, fence_token=7, enabled=True).status == (
            "SENT_OUTCOME_UNKNOWN"
        )
    with pytest.raises(ValueError, match="result_digest"):
        with sessions() as session:
            complete_call(
                session,
                first.call_id,
                fence_token=7,
                result_digest="0" * 64,
                result_payload={"answer": "valid"},
            )
    with pytest.raises(ValueError, match="exceeds"):
        with sessions() as session:
            complete_call(
                session,
                first.call_id,
                fence_token=7,
                result_payload={"answer": "x" * 65_537},
            )
    payload = {"answer": "valid"}
    with sessions() as session:
        assert (
            complete_call(session, first.call_id, fence_token=7, result_payload=payload).status
            == "COMPLETED"
        )
    with sessions() as session:
        row = session.scalar(select(LogicalCall).where(LogicalCall.id == first.call_id))
        assert row is not None
        assert (
            row.result_digest
            == hashlib.sha256(
                json.dumps(
                    payload,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest()
        )


def test_concurrent_reservations_do_not_oversubscribe_daily_cap(sessions):
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda i: _reserve(sessions, f"parallel-{i}", daily=2), range(8)))
    assert sum(result.call_id is not None for result in results) == 2
    assert sum(result.blocked_reason == "GLOBAL_DAILY_CAP_REACHED" for result in results) == 6


def test_disabled_or_missing_caps_fail_closed(sessions):
    with sessions() as session:
        disabled = reserve_call(
            session,
            task_type="x",
            task_key="x",
            evidence_digest="a",
            context_digest="b",
            prompt_contract="v1",
            provider="typesafe",
            model="m",
            policy_version="p",
            lease_authority="standalone",
            estimated_cost_usd="0.01",
            max_cost_usd="0.02",
        )
    assert disabled.blocked_reason == "INTELLIGENCE_DISABLED"
    with sessions() as session:
        no_caps = reserve_call(
            session,
            task_type="x",
            task_key="x",
            evidence_digest="a",
            context_digest="b",
            prompt_contract="v1",
            provider="typesafe",
            model="m",
            policy_version="p",
            lease_authority="standalone",
            enabled=True,
            estimated_cost_usd="0.01",
            max_cost_usd="0.02",
            caps={},
        )
    assert no_caps.blocked_reason == "GLOBAL_DAILY_CAP_ZERO"


def test_unknown_dispatch_holds_global_active_slot(sessions):
    first = _reserve(sessions, "long-lived-unknown", max_active=1)
    with sessions() as session:
        assert (
            mark_dispatched(session, first.call_id, fence_token=7, enabled=True).status
            == "SENT_OUTCOME_UNKNOWN"
        )
    second = _reserve(sessions, "another-call", max_active=1)
    assert second.call_id is None
    assert second.blocked_reason == "GLOBAL_ACTIVE_CAP_REACHED"


def test_old_period_unknown_call_keeps_lifetime_active_slot(sessions):
    with sessions.begin() as session:
        session.add(
            LogicalCallBudget(
                scope="global:global",
                period="active",
                period_key="active",
                call_count=0,
                cost_usd=Decimal("0"),
                active_count=1,
            )
        )
    later_call = _reserve(sessions, "new-period-call", max_active=1)
    assert later_call.call_id is None
    assert later_call.blocked_reason == "GLOBAL_ACTIVE_CAP_REACHED"


def test_job_turnover_fences_old_worker(sessions):
    with sessions.begin() as session:
        session.add(
            Source(
                id="fixture-source",
                publisher="test",
                endpoint="https://example.invalid",
                family="test",
                geography="test",
                industries=[],
                retrieval_method="test",
                health={},
            )
        )
        session.flush()
        job = Job(
            source_id="fixture-source",
            kind="intelligence",
            status="running",
            lease_owner="worker-a",
            fence=7,
            lease_until=datetime.now(UTC) + timedelta(minutes=5),
        )
        session.add(job)
        session.flush()
        job_id = job.id
    with sessions() as session:
        reserved = reserve_call(
            session,
            task_type="job-task",
            task_key="fenced",
            evidence_digest="a" * 64,
            context_digest="b" * 64,
            prompt_contract="v1",
            provider="typesafe",
            model="m",
            policy_version="p",
            enabled=True,
            estimated_cost_usd="0.01",
            max_cost_usd="0.02",
            lease_authority="job",
            job_id=job_id,
            worker_id="worker-a",
            fence_token=7,
            caps={
                scope: {"daily": 4, "monthly": 4, "daily_usd": "1", "monthly_usd": "5"}
                for scope in ("global", "provider", "model")
            },
        )
    with sessions() as session:
        assert (
            mark_dispatched(session, reserved.call_id, fence_token=7, enabled=True).status
            == "SENT_OUTCOME_UNKNOWN"
        )
    with sessions.begin() as session:
        session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                lease_owner="worker-b",
                fence=8,
                lease_until=datetime.now(UTC) + timedelta(minutes=5),
            )
        )
    with sessions() as session:
        denied = mark_dispatched(session, reserved.call_id, fence_token=7, enabled=True)
    assert denied.blocked_reason == "STALE_FENCE"
    with sessions() as session:
        stale_completion = complete_call(session, reserved.call_id, fence_token=7)
    assert stale_completion.blocked_reason == "STALE_FENCE"
    with sessions() as session:
        reconciled = reconcile_call(
            session,
            reserved.call_id,
            fence_token=7,
            reconciliation_actor="operator@example.test",
            reconciliation_ref="incident-123",
            result_payload={"outcome": "verified"},
        )
    assert reconciled.status == "RECONCILED"
    with sessions() as session:
        row = session.scalar(select(LogicalCall).where(LogicalCall.id == reserved.call_id))
        assert row and row.reconciled_by == "operator@example.test"
        assert row.reconciliation_ref == "incident-123"


def test_not_sent_reservation_rebinds_to_new_fence_without_double_budget(sessions):
    with sessions.begin() as session:
        session.add(
            Source(
                id="takeover-source",
                publisher="test",
                endpoint="https://example.invalid",
                family="test",
                geography="test",
                industries=[],
                retrieval_method="test",
                health={},
            )
        )
        session.flush()
        job = Job(
            source_id="takeover-source",
            kind="intelligence",
            status="running",
            lease_owner="worker-a",
            fence=4,
            lease_until=datetime.now(UTC) + timedelta(minutes=5),
        )
        session.add(job)
        session.flush()
        job_id = job.id
    scope_caps = {
        scope: {"daily": 4, "monthly": 4, "daily_usd": "1", "monthly_usd": "5"}
        for scope in ("global", "provider", "model")
    }
    identity = {
        "task_type": "job-task",
        "task_key": "recovery",
        "evidence_digest": "c" * 64,
        "context_digest": "d" * 64,
        "prompt_contract": "v1",
        "provider": "typesafe",
        "model": "m",
        "policy_version": "p",
        "enabled": True,
        "estimated_cost_usd": "0.01",
        "max_cost_usd": "0.02",
        "caps": scope_caps,
        "lease_authority": "job",
        "job_id": job_id,
    }
    with sessions() as session:
        first = reserve_call(session, worker_id="worker-a", fence_token=4, **identity)
    with sessions.begin() as session:
        session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                lease_owner="worker-b",
                fence=5,
                lease_until=datetime.now(UTC) + timedelta(minutes=5),
            )
        )
    with sessions() as session:
        recovered = reserve_call(session, worker_id="worker-b", fence_token=5, **identity)
    assert recovered.call_id == first.call_id
    assert recovered.reused and recovered.status == "NOT_SENT"
    with sessions() as session:
        sent = mark_dispatched(session, first.call_id, fence_token=5, enabled=True)
    assert sent.status == "SENT_OUTCOME_UNKNOWN"
    with sessions() as session:
        row = session.scalar(select(LogicalCall).where(LogicalCall.id == first.call_id))
        budget = session.scalar(
            select(LogicalCallBudget).where(
                LogicalCallBudget.scope == "global:global", LogicalCallBudget.period == "daily"
            )
        )
    assert row and row.worker_id == "worker-b" and row.fence_token == 5
    assert budget and budget.call_count == 1 and budget.active_count == 1


def test_completed_call_is_readable_by_new_job_fence_without_rebilling(sessions):
    # Completed semantic output is immutable and may be read by a new worker,
    # but all mutating transitions remain pinned to the original lease.
    with sessions.begin() as session:
        session.add(
            Source(
                id="cache-source",
                publisher="test",
                endpoint="https://example.invalid",
                family="test",
                geography="test",
                industries=[],
                retrieval_method="test",
                health={},
            )
        )
        session.flush()
        job = Job(
            source_id="cache-source",
            kind="intelligence",
            status="running",
            lease_owner="worker-a",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=5),
        )
        session.add(job)
        session.flush()
        job_id = job.id
    common = {
        "task_type": "job-task",
        "task_key": "cache",
        "evidence_digest": "e" * 64,
        "context_digest": "f" * 64,
        "prompt_contract": "v1",
        "provider": "typesafe",
        "model": "m",
        "policy_version": "p",
        "source_id": "cache-source",
        "enabled": True,
        "estimated_cost_usd": "0.01",
        "max_cost_usd": "0.02",
        "caps": {
            scope: {"daily": 4, "monthly": 4, "daily_usd": "1", "monthly_usd": "5"}
            for scope in ("global", "provider", "model", "source")
        },
        "lease_authority": "job",
        "job_id": job_id,
    }
    with sessions() as session:
        first = reserve_call(session, worker_id="worker-a", fence_token=1, **common)
    with sessions() as session:
        assert mark_dispatched(session, first.call_id, fence_token=1, enabled=True).status == (
            "SENT_OUTCOME_UNKNOWN"
        )
    with sessions() as session:
        complete_call(session, first.call_id, fence_token=1, result_payload={"answer": "cached"})
    with sessions.begin() as session:
        session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                lease_owner="worker-b",
                fence=2,
                lease_until=datetime.now(UTC) + timedelta(minutes=5),
            )
        )
    with sessions() as session:
        cached = reserve_call(session, worker_id="worker-b", fence_token=2, **common)
    assert cached.call_id == first.call_id and cached.status == "COMPLETED"
    with sessions() as session:
        row = session.scalar(select(LogicalCall).where(LogicalCall.id == first.call_id))
        budget = session.scalar(
            select(LogicalCallBudget).where(
                LogicalCallBudget.scope == "global:global", LogicalCallBudget.period == "daily"
            )
        )
    assert row and row.result_payload == {"answer": "cached"}
    assert budget and budget.call_count == 1 and budget.active_count == 0


def test_ambiguous_failure_keeps_unknown_reservation(sessions):
    from gridlens.integrations.logical_calls import fail_call

    call = _reserve(sessions, "ambiguous-failure")
    with sessions() as session:
        mark_dispatched(session, call.call_id, fence_token=7, enabled=True)
    with sessions() as session:
        result = fail_call(
            session,
            call.call_id,
            fence_token=7,
            blocked_reason="timeout",
        )
    assert result.status == "SENT_OUTCOME_UNKNOWN"
    assert result.blocked_reason == "CONCLUSIVE_RESPONSE_REQUIRED"
    with sessions() as session:
        row = session.scalar(select(LogicalCall).where(LogicalCall.id == call.call_id))
        budget = session.scalar(
            select(LogicalCallBudget).where(
                LogicalCallBudget.scope == "global:global", LogicalCallBudget.period == "active"
            )
        )
    assert row and row.status == "SENT_OUTCOME_UNKNOWN"
    assert budget and budget.active_count == 1


def test_late_settlement_preserves_unknown_outcome_and_charges_only_overage(sessions):
    from gridlens.integrations.logical_calls import settle_call

    call = _reserve(sessions, "late-settlement")
    with sessions() as session:
        mark_dispatched(session, call.call_id, fence_token=7, enabled=True)
    with sessions() as session:
        receipt, replayed = settle_call(
            session,
            call.call_id,
            actor="host-operator",
            receipt_ref="invoice:one",
            actual_cost_usd="0.05",
            input_tokens=12,
        )
    assert not replayed and receipt.actual_cost_usd == Decimal("0.050000")
    with sessions() as session:
        row = session.get(LogicalCall, call.call_id)
        daily = session.scalar(
            select(LogicalCallBudget).where(
                LogicalCallBudget.scope == "global:global", LogicalCallBudget.period == "daily"
            )
        )
        active = session.scalar(
            select(LogicalCallBudget).where(
                LogicalCallBudget.scope == "global:global", LogicalCallBudget.period == "active"
            )
        )
        assert row and row.status == "SENT_OUTCOME_UNKNOWN"
        assert row.actual_cost_usd == Decimal("0.050000") and row.input_tokens == 12
        assert row.output_tokens is None and row.result_payload is None and row.finished_at is None
        assert daily and daily.cost_usd == Decimal("0.050000")
        assert active and active.active_count == 1
    with pytest.raises(ValueError, match="six decimal places"):
        with sessions() as session:
            settle_call(
                session,
                call.call_id,
                actor="host-operator",
                receipt_ref="invoice:excess-precision",
                actual_cost_usd="0.0000001",
            )


def test_settlement_replay_conflict_and_concurrent_receipts_charge_once(sessions):
    from gridlens.integrations.logical_calls import settle_call

    call = _reserve(sessions, "settlement-replay")
    with sessions() as session:
        mark_dispatched(session, call.call_id, fence_token=7, enabled=True)

    def settle(ref: str):
        with sessions() as session:
            return settle_call(
                session,
                call.call_id,
                actor="operator",
                receipt_ref=ref,
                actual_cost_usd="0.05",
            )[1]

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(settle, ["receipt-a", "receipt-b", "receipt-a", "receipt-b"]))
    assert results.count(False) == 2 and results.count(True) == 2
    with sessions() as session:
        assert (
            len(
                session.scalars(
                    select(LogicalCallSettlement).where(
                        LogicalCallSettlement.call_id == call.call_id
                    )
                ).all()
            )
            == 2
        )
        daily = session.scalar(
            select(LogicalCallBudget).where(
                LogicalCallBudget.scope == "global:global", LogicalCallBudget.period == "daily"
            )
        )
        assert daily and daily.cost_usd == Decimal("0.050000")
    with pytest.raises(ValueError, match="different settlement data"):
        with sessions() as session:
            settle_call(
                session,
                call.call_id,
                actor="operator",
                receipt_ref="receipt-a",
                actual_cost_usd="0.06",
            )


def test_reconciled_metadata_survives_late_measurement(sessions):
    from gridlens.integrations.logical_calls import reconcile_call, settle_call

    call = _reserve(sessions, "settle-reconciled")
    with sessions() as session:
        mark_dispatched(session, call.call_id, fence_token=7, enabled=True)
    with sessions() as session:
        reconcile_call(
            session,
            call.call_id,
            fence_token=7,
            reconciliation_actor="operator",
            reconciliation_ref="outcome:confirmed",
        )
    with sessions() as session:
        row = session.get(LogicalCall, call.call_id)
        before = (row.result_digest, row.result_payload, row.finished_at, row.fence_token)
        settle_call(
            session,
            call.call_id,
            actor="operator",
            receipt_ref="billing:confirmed",
            output_tokens=8,
        )
    with sessions() as session:
        row = session.get(LogicalCall, call.call_id)
        assert row and row.status == "RECONCILED"
        assert (row.result_digest, row.result_payload, row.finished_at, row.fence_token) == before
        assert row.output_tokens == 8 and row.input_tokens is None


def test_host_cli_requires_fresh_digest_and_applies_only_after_preview(
    sessions, monkeypatch, capsys
):
    import json
    import runpy
    import sys
    from pathlib import Path

    from gridlens.integrations.logical_calls import complete_call

    call = _reserve(sessions, "cli-settlement")
    with sessions() as session:
        mark_dispatched(session, call.call_id, fence_token=7, enabled=True)
    with sessions() as session:
        complete_call(session, call.call_id, fence_token=7, result_payload={"safe": True})
    monkeypatch.setattr(settings, "database_url", settings.test_database_url)
    script = Path(__file__).resolve().parents[2] / "scripts" / "reconcile_logical_call.py"
    cli = runpy.run_path(str(script))
    base_args = [
        str(call.call_id),
        "--action",
        "settle",
        "--actor",
        "host-operator",
        "--receipt-ref",
        "cli-invoice-1",
        "--expected-status",
        "COMPLETED",
        "--actual-cost-usd",
        "0.01",
        "--input-tokens",
        "23",
    ]
    monkeypatch.setattr(sys, "argv", ["reconcile_logical_call.py", *base_args])
    assert cli["main"]() == 0
    digest = json.loads(capsys.readouterr().out)["digest"]
    with sessions.begin() as session:
        session.execute(
            update(LogicalCall).where(LogicalCall.id == call.call_id).values(result_digest="f" * 64)
        )
    monkeypatch.setattr(
        sys,
        "argv",
        ["reconcile_logical_call.py", *base_args, "--apply", "--expect-digest", digest],
    )
    with pytest.raises(SystemExit):
        cli["main"]()
    with sessions() as session:
        assert (
            session.scalar(
                select(LogicalCallSettlement).where(LogicalCallSettlement.call_id == call.call_id)
            )
            is None
        )
    monkeypatch.setattr(sys, "argv", ["reconcile_logical_call.py", *base_args])
    assert cli["main"]() == 0
    fresh_digest = json.loads(capsys.readouterr().out)["digest"]
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "reconcile_logical_call.py",
            *base_args,
            "--apply",
            "--expect-digest",
            fresh_digest,
        ],
    )
    assert cli["main"]() == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["mode"] == "applied" and receipt["status"] == "COMPLETED"


def test_0028_database_trigger_rejects_settlement_edits(monkeypatch):
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import func, text
    from sqlalchemy.orm import Session

    target = make_url(settings.test_database_url)
    assert target.database and target.database.endswith("_test")
    assert target != make_url(settings.database_url)
    schema = "settlement_trigger_" + uuid4().hex
    admin = create_engine(settings.test_database_url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    isolated_url = target.set(query={"options": f"-csearch_path={schema}"})
    monkeypatch.setattr(
        settings, "database_url", isolated_url.render_as_string(hide_password=False)
    )
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[2] / "migrations")
    )
    command.upgrade(config, "head")
    engine = create_engine(isolated_url)
    factory = sessionmaker(engine, expire_on_commit=False)
    call_id = uuid4()
    try:
        with factory.begin() as session:
            session.add(
                LogicalCall(
                    id=call_id,
                    fingerprint="d" * 64,
                    task_type="TEST",
                    task_key="append-only-trigger",
                    evidence_digest="e" * 64,
                    context_digest="c" * 64,
                    prompt_contract="test",
                    provider="local-fixture",
                    model="fixture",
                    policy_version="test",
                    lease_authority="standalone",
                    status="COMPLETED",
                    fence_token=0,
                    estimated_cost_usd=Decimal("0.01"),
                    max_cost_usd=Decimal("0.02"),
                    actual_cost_usd=None,
                    budget_scopes=[],
                )
            )
            session.flush()
            session.add(
                LogicalCallSettlement(
                    call_id=call_id,
                    actor="test-operator",
                    receipt_ref="trigger-check",
                    input_tokens=1,
                )
            )
            session.flush()
        with Session(engine) as session:
            with pytest.raises(DBAPIError, match="append-only"):
                with session.begin_nested():
                    session.execute(
                        update(LogicalCallSettlement)
                        .where(LogicalCallSettlement.call_id == call_id)
                        .values(actor="rewritten")
                    )
        with Session(engine) as session:
            with pytest.raises(DBAPIError, match="append-only"):
                with session.begin_nested():
                    session.execute(
                        LogicalCallSettlement.__table__.delete().where(
                            LogicalCallSettlement.call_id == call_id
                        )
                    )
        with factory() as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(LogicalCallSettlement)
                    .where(LogicalCallSettlement.call_id == call_id)
                )
                == 1
            )
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_nullable_maximum_quarantine_and_reported_actual_settlement(sessions):
    reserved = _reserve(sessions, "nullable-maximum")
    with sessions() as session:
        row = session.get(LogicalCall, reserved.call_id)
        assert row is not None
        row.financial_budget_mode = "owner_unlimited"
        row.financial_authorization_ref = "owner-approved-test-policy"
        row.max_cost_usd = None
        session.commit()
    with sessions() as session:
        assert mark_dispatched(session, reserved.call_id, fence_token=7, enabled=True).status == (
            "SENT_OUTCOME_UNKNOWN"
        )
    with sessions() as session:
        quarantined = quarantine_call(
            session,
            reserved.call_id,
            fence_token=7,
            expected_model="fixture-model",
            actual_model="different-model",
            reason="MODEL_IDENTITY_MISMATCH",
            response_payload={"model": "different-model"},
            exposure_status="UNKNOWN",
        )
        assert quarantined.status == "SENT_OUTCOME_UNKNOWN"
    with sessions() as session:
        row = session.get(LogicalCall, reserved.call_id)
        assert row is not None and row.max_cost_usd is None and row.actual_cost_usd is None
        receipt = row.result_payload["billing_quarantine"]
        assert receipt["exposure_status"] == "UNKNOWN"
        assert receipt["conservative_exposure_usd"] is None
        assert receipt["budgeted_exposure_usd"] is None
    with sessions() as session:
        _settlement, replayed = settle_call(
            session,
            reserved.call_id,
            actor="synthetic-fixture",
            receipt_ref="reported-actual-receipt",
            actual_cost_usd="0.040000",
            input_tokens=12,
            output_tokens=4,
        )
    assert not replayed
    with sessions() as session:
        row = session.get(LogicalCall, reserved.call_id)
        assert row is not None and row.actual_cost_usd == Decimal("0.040000")
        assert row.input_tokens == 12 and row.output_tokens == 4
        receipt = row.result_payload["billing_quarantine"]
        assert receipt["budgeted_exposure_usd"] is None
        assert receipt["reconciled_actual_cost_usd"] == "0.040000"
        assert receipt["financial_budget_mode"] == "owner_unlimited"
        assert receipt["financial_authorization_ref"] == "owner-approved-test-policy"
        assert receipt["max_cost_usd"] is None


def test_unlimited_minimal_quarantine_fallback_preserves_unknown_exposure_and_active_hold(
    sessions, monkeypatch
):
    reserved = _reserve(sessions, "unlimited-minimal-quarantine")
    with sessions() as session:
        row = session.get(LogicalCall, reserved.call_id)
        assert row is not None
        row.financial_budget_mode = "owner_unlimited"
        row.financial_authorization_ref = "owner-approved-test-policy"
        row.max_cost_usd = None
        row.estimated_cost_usd = None
        session.commit()
    with sessions() as session:
        assert mark_dispatched(session, reserved.call_id, fence_token=7, enabled=True).status == (
            "SENT_OUTCOME_UNKNOWN"
        )
    from gridlens.integrations import logical_calls

    monkeypatch.setattr(logical_calls, "MAX_RESULT_BYTES", 1)
    with sessions() as session:
        quarantined = quarantine_call(
            session,
            reserved.call_id,
            fence_token=7,
            expected_model="fixture-model",
            actual_model="different-model",
            reason="MODEL_IDENTITY_MISMATCH",
            response_payload={"model": "different-model", "unknown": object()},
            exposure_status="UNKNOWN",
        )
        assert quarantined.status == "SENT_OUTCOME_UNKNOWN"
    with sessions() as session:
        row = session.get(LogicalCall, reserved.call_id)
        budget = session.scalar(
            select(LogicalCallBudget).where(
                LogicalCallBudget.scope == "global:global",
                LogicalCallBudget.period == "daily",
            )
        )
        assert row is not None
        receipt = row.result_payload["billing_quarantine"]
        assert receipt["exposure_status"] == "UNKNOWN"
        assert receipt["conservative_exposure_usd"] is None
        assert receipt["budgeted_exposure_usd"] is None
        assert receipt["financial_budget_mode"] == "owner_unlimited"
        assert receipt["financial_authorization_ref"] == "owner-approved-test-policy"
        assert receipt["max_cost_usd"] is None
        assert row.actual_cost_usd is None and row.input_tokens is None
        assert budget and budget.active_count == 1
