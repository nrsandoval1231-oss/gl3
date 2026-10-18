from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.integrations.logical_calls import (
    cancel_call,
    complete_call,
    mark_dispatched,
    reconcile_call,
    reserve_call,
)
from gridlens.persistence.database import Base
from gridlens.persistence.models import Job, LogicalCall, LogicalCallBudget, Source
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
                for scope in ("global", "provider", "model")
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
