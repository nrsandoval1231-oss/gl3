import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from gridlens.intelligence.company_contact_discovery import _contact_planner_due


def job(status, checkpoint, created_at):
    return SimpleNamespace(
        id=uuid4(),
        status=status,
        checkpoint=json.dumps(checkpoint),
        created_at=created_at,
    )


def test_contact_planner_refreshes_completed_searches_every_30_days():
    now = datetime(2026, 10, 26, tzinfo=UTC)
    completed = job(
        "succeeded",
        {"status": "complete", "completed_at": (now - timedelta(days=29)).isoformat()},
        now - timedelta(days=30),
    )
    assert not _contact_planner_due([completed], now)
    completed.checkpoint = json.dumps(
        {"status": "complete", "completed_at": (now - timedelta(days=30)).isoformat()}
    )
    assert _contact_planner_due([completed], now)


def test_contact_planner_obeys_persisted_unresolved_retry_after():
    now = datetime(2026, 10, 26, tzinfo=UTC)
    unresolved = job(
        "succeeded",
        {
            "status": "unresolved",
            "reason": "no_current_source_backed_company_claim",
            "planned_at": now.isoformat(),
            "retry_after": (now + timedelta(days=7)).isoformat(),
        },
        now,
    )
    assert not _contact_planner_due([unresolved], now + timedelta(days=6))
    assert _contact_planner_due([unresolved], now + timedelta(days=7))


def test_contact_planner_retries_failed_calls_with_backoff_then_refreshes():
    now = datetime(2026, 10, 26, tzinfo=UTC)
    first = job(
        "failed",
        {"status": "failed", "request_digest": "same"},
        now - timedelta(minutes=30),
    )
    assert not _contact_planner_due([first], now)
    assert _contact_planner_due([first], now + timedelta(hours=1))
    second = job(
        "failed",
        {"status": "failed", "request_digest": "same"},
        now - timedelta(days=29),
    )
    first.created_at = now - timedelta(days=29)
    assert not _contact_planner_due([first, second], now)
    assert _contact_planner_due([first, second], now + timedelta(days=1))
