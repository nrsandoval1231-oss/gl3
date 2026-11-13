"""A refused dispatch must cancel the reservation (release budget), never an unknown send."""

from decimal import Decimal

import pytest
from db_reset import reset_test_database
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.integrations.logical_calls import (
    mark_dispatched,
    quarantine_call,
    reserve_call,
)
from gridlens.intelligence import intelligence_jobs
from gridlens.persistence.models import LogicalCall, LogicalCallBudget
from gridlens.settings import settings

FENCE = 7


@pytest.fixture
def sessions(monkeypatch):
    target = make_url(settings.test_database_url)
    assert target.database and target.database.endswith("_test")
    assert target != make_url(settings.database_url)
    engine = create_engine(settings.test_database_url, pool_size=8)
    reset_test_database(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(intelligence_jobs, "SessionLocal", factory)
    try:
        yield factory
    finally:
        engine.dispose()


def _reserve(factory, key: str):
    with factory() as session:
        return reserve_call(
            session,
            task_type="DISPATCH_RELEASE_TEST",
            task_key=key,
            evidence_digest="a" * 64,
            context_digest="b" * 64,
            prompt_contract="v1",
            provider="openai",
            model="fixture-model",
            policy_version="policy-v1",
            enabled=True,
            lease_authority="standalone",
            estimated_cost_usd=Decimal("0.01"),
            max_cost_usd=Decimal("0.02"),
            caps={
                scope: {"daily": 10, "monthly": 10, "daily_usd": "1.00", "monthly_usd": "10.00"}
                for scope in ("global", "provider", "model", "source")
            },
            max_active=10,
            fence_token=FENCE,
        )


def _status_and_active(factory, call_id):
    with factory() as session:
        call = session.get(LogicalCall, call_id)
        active = [row.active_count for row in session.scalars(select(LogicalCallBudget))]
    return call.status, active


def test_policy_recheck_refusal_cancels_and_releases_active_budget(sessions):
    call = _reserve(sessions, "policy-recheck")
    with sessions() as session:
        dispatched = mark_dispatched(session, call.call_id, fence_token=FENCE, enabled=False)
    assert dispatched.status == "NOT_SENT"
    intelligence_jobs.release_undispatched_call(call.call_id, FENCE, dispatched)
    status, active = _status_and_active(sessions, call.call_id)
    assert status == "CANCELLED" and active and all(count == 0 for count in active)


def test_quarantine_at_dispatch_cancels_the_prereserved_call(sessions):
    sent = _reserve(sessions, "quarantine-sent")
    waiting = _reserve(sessions, "quarantine-waiting")
    with sessions() as session:
        mark_dispatched(session, sent.call_id, fence_token=FENCE, enabled=True)
    with sessions() as session:
        quarantine_call(
            session,
            sent.call_id,
            fence_token=FENCE,
            expected_model="fixture-model",
            actual_model="other-model",
            reason="model_mismatch",
            response_payload={"fixture": "raw"},
        )
    with sessions() as session:
        dispatched = mark_dispatched(session, waiting.call_id, fence_token=FENCE, enabled=True)
    assert dispatched.blocked_reason == "PROVIDER_BILLING_QUARANTINED"
    intelligence_jobs.release_undispatched_call(waiting.call_id, FENCE, dispatched)
    assert _status_and_active(sessions, waiting.call_id)[0] == "CANCELLED"
    # The call that may have been sent stays unknown: never cancelled.
    assert _status_and_active(sessions, sent.call_id)[0] == "SENT_OUTCOME_UNKNOWN"


def test_sent_outcome_unknown_is_never_cancelled(sessions):
    call = _reserve(sessions, "already-sent")
    with sessions() as session:
        first = mark_dispatched(session, call.call_id, fence_token=FENCE, enabled=True)
    assert first.status == "SENT_OUTCOME_UNKNOWN"
    with sessions() as session:
        again = mark_dispatched(session, call.call_id, fence_token=FENCE, enabled=True)
    assert again.status == "SENT_OUTCOME_UNKNOWN" and again.blocked_reason
    intelligence_jobs.release_undispatched_call(call.call_id, FENCE, again)
    assert _status_and_active(sessions, call.call_id)[0] == "SENT_OUTCOME_UNKNOWN"
