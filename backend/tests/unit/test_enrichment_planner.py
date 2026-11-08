from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from gridlens.intelligence.enrichment_planner import (
    ResearchCandidate,
    rank_candidate,
    research_digest,
    select_research_profile,
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
    assert "known_demand_mw:unknown" in rank["reasons"]
    assert "missing_fact_utility:0" in rank["reasons"]
    assert "bounded_public_research_cost:-5" in rank["reasons"]
    assert rank["missing_facts"] == []


def test_contact_gaps_increase_priority_and_are_part_of_research_digest():
    from dataclasses import replace

    ordinary = _candidate()
    buyer_gap = replace(ordinary, missing_buyer_relevant_method=True)
    method_gap = replace(ordinary, missing_contact_method=True)
    assert (
        rank_candidate(buyer_gap, now=NOW)["score"]
        == rank_candidate(ordinary, now=NOW)["score"] + 12
    )
    assert (
        rank_candidate(method_gap, now=NOW)["score"]
        == rank_candidate(ordinary, now=NOW)["score"] + 6
    )
    assert research_digest(buyer_gap) != research_digest(ordinary)


def test_only_supported_contact_gap_changes_depth_or_rank():
    from dataclasses import replace

    ordinary = _candidate(mw="900 MW", start="2026-11-01")
    buyer_gap = replace(ordinary, missing_buyer_relevant_method=True)
    assert rank_candidate(ordinary, now=NOW)["score"] < rank_candidate(buyer_gap, now=NOW)["score"]
    assert select_research_profile(ordinary, now=NOW) == "contact-depth-v1:standard"
    assert select_research_profile(buyer_gap, now=NOW) == "contact-depth-v1:standard"


def test_contact_priority_uses_observable_power_opportunity_values():
    large = rank_candidate(_candidate(mw="80 MW"), now=NOW)
    small = rank_candidate(_candidate(mw="5 MW"), now=NOW)
    assert large["score"] == small["score"]
    assert "known_demand_mw:observed_not_scored" in large["reasons"]


def test_project_and_need_volume_does_not_increase_research_utility():
    from dataclasses import replace

    single = _candidate(mw=None)
    large = replace(
        single,
        projects=single.projects + tuple(SimpleNamespace(id=uuid4()) for _ in range(12)),
        needs=single.needs
        + tuple(
            SimpleNamespace(
                id=uuid4(), tier="Signal", start_window=None, required_mw=None,
                duration=None, supply="Unknown", active=True,
            )
            for _ in range(30)
        ),
    )
    assert rank_candidate(large, now=NOW)["score"] == rank_candidate(single, now=NOW)["score"]
    assert "missing_fact_utility:0" in rank_candidate(large, now=NOW)["reasons"]


def test_depth_profile_is_stable_across_clock_changes_and_tracks_opportunity_evidence():
    from dataclasses import replace

    low = _candidate(mw=None)
    high = _candidate(mw="80 MW")
    low = ResearchCandidate(
        low.company_id,
        low.projects,
        low.needs,
        low.latest_evidence_at,
        low.completed_at,
        low.prior_digest,
        "source-backed",
        missing_buyer_relevant_method=True,
    )
    high = ResearchCandidate(
        high.company_id,
        high.projects,
        high.needs,
        high.latest_evidence_at,
        high.completed_at,
        high.prior_digest,
        "source-backed",
        missing_buyer_relevant_method=True,
    )
    assert select_research_profile(low, now=NOW) == "contact-depth-v1:standard"
    assert select_research_profile(high, now=NOW) == "contact-depth-v1:standard"
    assert (
        select_research_profile(high, now=NOW + timedelta(days=365))
        == "contact-depth-v1:standard"
    )
    deep = replace(high, research_profile="contact-depth-v1:deep")
    assert research_digest(deep) != research_digest(high)
    assert research_digest(deep) == research_digest(
        ResearchCandidate(
            high.company_id,
            high.projects,
            high.needs,
            high.latest_evidence_at,
            high.completed_at,
            high.prior_digest,
            "source-backed",
            missing_buyer_relevant_method=True,
            research_profile="contact-depth-v1:deep",
        )
    )


def test_negative_and_empty_needs_are_not_ranked_as_opportunities():
    candidate = ResearchCandidate(uuid4(), (), (), None, None, None)
    assert rank_candidate(candidate, now=NOW) == {
        "score": 0,
        "contact_depth_score": 0,
        "reasons": ["no_active_power_need"],
        "missing_facts": [],
    }


def test_facility_timing_and_missing_fields_do_not_inflate_contact_research():
    urgent = _candidate(start="2026-11-01", mw=None)
    far = _candidate(start="2027-Q4", mw=None)
    urgent_rank = rank_candidate(urgent, now=NOW)
    far_rank = rank_candidate(far, now=NOW)
    assert "commercial_value:0" in urgent_rank["reasons"]
    assert "urgency:0" in urgent_rank["reasons"]
    assert urgent_rank["score"] == far_rank["score"]
    assert urgent_rank["missing_facts"] == []
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


def test_demand_explanation_is_not_a_company_contact_priority():
    for demand, expected in (
        (None, "unknown"),
        ("not established", "unknown"),
        ("0 MW", "observed_not_scored"),
        ("12 MW", "observed_not_scored"),
    ):
        rank = rank_candidate(_candidate(mw=demand), now=NOW)
        assert f"known_demand_mw:{expected}" in rank["reasons"]


def test_invalid_quarter_and_extreme_demand_do_not_stop_research_ranking():
    rank = rank_candidate(_candidate(start="0000-Q1", mw="9" * 400 + " MW"), now=NOW)
    assert "days_to_supported_start:unknown" in rank["reasons"]
    assert "known_demand_mw:observed_not_scored" in rank["reasons"]
    bounded = rank_candidate(_candidate(mw="1" + "0" * 308 + " MW"), now=NOW)
    assert "commercial_value:0" in bounded["reasons"]
