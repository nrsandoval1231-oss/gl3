from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from gridlens.intelligence.enrichment_planner import (
    ResearchCandidate,
    rank_candidate,
    research_digest,
    should_schedule,
)

NOW = datetime(2026, 10, 25, tzinfo=UTC)


def _candidate(
    *,
    tier="Signal",
    start=None,
    mw=None,
    duration=None,
    supply="Unknown",
    completed=None,
    prior=None,
):
    project = SimpleNamespace(id=uuid4())
    need = SimpleNamespace(
        id=uuid4(),
        tier=tier,
        start_window=start,
        required_mw=mw,
        duration=duration,
        supply=supply,
        active=True,
    )
    return ResearchCandidate(uuid4(), (project,), (need,), NOW, completed, prior)


def test_rank_explains_commercial_urgency_missingness_and_cost():
    candidate = _candidate(tier="Prospect", start="2026-Q4")
    rank = rank_candidate(candidate, now=NOW)
    assert rank["score"] > 0
    assert "urgency:0" in rank["reasons"]
    assert "bounded_public_research_cost:-5" in rank["reasons"]
    assert rank["missing_facts"] == ["duration", "required_mw", "supply"]


def test_negative_and_empty_needs_are_not_ranked_as_opportunities():
    candidate = ResearchCandidate(uuid4(), (), (), None, None, None)
    assert rank_candidate(candidate, now=NOW) == {
        "score": 0,
        "reasons": ["no_active_power_need"],
        "missing_facts": [],
    }


def test_urgency_uses_supported_dates_and_missing_facts_remain_researchable():
    urgent = _candidate(start="2026-11-01", mw=None)
    far = _candidate(start="2027-Q4", mw=None)
    urgent_rank = rank_candidate(urgent, now=NOW)
    far_rank = rank_candidate(far, now=NOW)
    assert "commercial_value:0" in urgent_rank["reasons"]
    assert "urgency:18" in urgent_rank["reasons"]
    assert "urgency:0" in far_rank["reasons"]
    assert urgent_rank["score"] > far_rank["score"]
    assert "missing_facts:duration,required_mw,supply" in urgent_rank["reasons"]
    past = _candidate(start="2026-10-01", mw=None)
    assert "urgency:0" in rank_candidate(past, now=NOW)["reasons"]


def test_digest_change_and_staleness_schedule_incrementally():
    candidate = _candidate(completed=NOW - timedelta(days=2), prior="old")
    digest = research_digest(candidate)
    assert should_schedule(candidate, now=NOW, digest=digest) == (
        True,
        "project_or_evidence_changed",
    )
    unchanged = ResearchCandidate(
        candidate.company_id,
        candidate.projects,
        candidate.needs,
        candidate.latest_evidence_at,
        NOW - timedelta(days=2),
        digest,
    )
    assert should_schedule(unchanged, now=NOW, digest=digest) == (
        False,
        "recent_unchanged_research",
    )
    stale = ResearchCandidate(
        candidate.company_id,
        candidate.projects,
        candidate.needs,
        candidate.latest_evidence_at,
        NOW - timedelta(days=31),
        digest,
    )
    assert should_schedule(stale, now=NOW, digest=digest) == (True, "stale_refresh_due")
