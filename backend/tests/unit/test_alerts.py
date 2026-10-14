import httpx
import pytest

from gridlens.jobs import alerts
from gridlens.settings import settings


def health(**overrides):
    payload = {
        "sources": [
            {"id": "a", "enabled": True, "status": "Updated"},
            {"id": "b", "enabled": True, "status": "Failed", "error": "parser broke"},
            {"id": "c", "enabled": True, "status": "Overdue"},
            {"id": "d", "enabled": False, "status": "Failed"},
        ],
        "backlog": 2,
        "pending_interpretations": 0,
        "worker_liveness": "LIVE",
        "collection_freshness": "FRESH",
    }
    payload.update(overrides)
    return payload


def test_summary_lists_enabled_problems_only():
    title, body, urgent = alerts.summarize(health())
    assert urgent and title == "GridLens: 2 problem(s)"
    assert "b: Failed — parser broke" in body and "c: Overdue" in body
    assert "d:" not in body
    assert "1/3 enabled sources healthy" in body


def test_stale_worker_and_overdue_collection_are_problems():
    title, body, urgent = alerts.summarize(
        health(sources=[], worker_liveness="STALE", collection_freshness="OVERDUE")
    )
    assert urgent and "Worker liveness: STALE" in body and "overdue" in body


def test_healthy_run_still_reports():
    title, _, urgent = alerts.summarize(
        health(sources=[{"id": "a", "enabled": True, "status": "Updated"}])
    )
    assert not urgent and title == "GridLens: collection healthy"


def test_send_posts_to_ntfy_with_priority_and_token(monkeypatch):
    monkeypatch.setattr(settings, "ntfy_url", "https://ntfy.example/topic")
    monkeypatch.setattr(settings, "ntfy_token", None)
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200)

    alerts.send("t", "body", True, httpx.Client(transport=httpx.MockTransport(handler)))
    assert str(seen[0].url) == "https://ntfy.example/topic"
    assert seen[0].headers["Priority"] == "high" and seen[0].content == b"body"


def test_send_requires_configuration(monkeypatch):
    monkeypatch.setattr(settings, "ntfy_url", "")
    with pytest.raises(RuntimeError):
        alerts.send("t", "b", False)


def test_terminal_processing_failures_are_urgent():
    title, body, urgent = alerts.summarize(
        health(sources=[{"id": "a", "enabled": True, "status": "Updated"}]),
        {"power_need_brief jobs": 2, "interpretations": 1, "pursuit_question jobs": 0},
    )
    assert urgent and title == "GridLens: 2 problem(s)"
    assert "Failed power_need_brief jobs: 2" in body and "Failed interpretations: 1" in body
    assert "pursuit_question" not in body
