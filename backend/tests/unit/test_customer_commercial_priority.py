"""Commercial-priority heuristics keep opportunity and timing evidence distinct."""

from datetime import date

from gridlens.domain.customer_intelligence import (
    FACTS_VERSION,
    PRIORITY_VERSION,
    extract_customer_facts,
    resolve_customer_intelligence,
)

AS_OF = date(2026, 11, 12)


def source(*, published_at="2025-07-30", authority="primary", verification="verified"):
    return {
        "url": "https://owner.example/source",
        "evidence_id": "priority-fixture-evidence",
        "content_hash": "a" * 64,
        "published_at": published_at,
        "observed_at": "2026-11-12T00:00:00Z",
        "authority": authority,
        "verification_status": verification,
    }


def resolved(text: str, *, source_ref=None):
    facts = extract_customer_facts(
        text,
        project_id="priority-fixture-project",
        source=source_ref or source(),
    )
    return resolve_customer_intelligence(
        [{"project_id": "priority-fixture-project", "facts": [facts]}], as_of=AS_OF
    )


def test_supported_upper_bound_capacity_adds_bounded_opportunity_scale_not_demand():
    result = resolved("The campus will have up to 480 MW of IT load.")
    priority = result["priority"]

    assert priority["version"] == PRIORITY_VERSION == "customer-commercial-priority-v2"
    assert priority["components"]["capacity"] == 0
    assert priority["components"]["announced_upper_bound"] == 8
    assert priority["score"] > 0
    assert priority["priority_basis"]["capacity"] == {
        "kind": "announced_upper_bound",
        "basis": "it_load",
        "value_mw": "480",
        "complete": True,
        "claim_ids": [result["capacity"]["totals"][0]["claim_ids"][0]],
        "sources": [
            {
                "fact_id": result["capacity"]["totals"][0]["claim_ids"][0],
                "quote": "The campus will have up to 480 MW of IT load.",
                "source": source(),
                "qualifier": "up_to",
            }
        ],
    }
    assert any("not verified buildout or demand" in text for text in priority["limitations"])
    assert result["capacity"]["total_mw"] is None


def test_supported_capacity_and_larger_upper_bound_do_not_double_count_scale():
    result = resolved("Utility service capacity is 100 MW. IT load is up to 500 MW.")
    priority = result["priority"]

    assert {total["basis"]: total["value_mw"] for total in result["capacity"]["totals"]} == {
        "it_load": "500",
        "utility_service": "100",
    }
    assert priority["components"]["capacity"] == 20
    assert priority["components"]["announced_upper_bound"] == 0
    assert priority["potential"] == 20
    assert priority["priority_basis"]["capacity"]["kind"] == "supported_capacity"
    assert priority["priority_basis"]["capacity"]["basis"] == "utility_service"


def test_operational_target_is_a_research_timing_proxy_not_energization():
    result = resolved("The site is expected to be operational in Q4 2026.")
    priority = result["priority"]

    assert result["timelines"]["expected_energization"] is None
    assert priority["score"] > 0
    assert priority["components"]["timing"] == 12
    assert priority["priority_basis"]["timing"]["kind"] == "reported_timing_proxy"
    assert priority["priority_basis"]["timing"]["event_type"] == "operational_target"
    assert priority["priority_basis"]["timing"]["label"] == "Q4 2026"
    assert "not commissioning or energization" in " ".join(priority["limitations"])


def test_old_construction_does_not_mask_nearby_operational_target_and_timeline_stays_intact():
    result = resolved(
        "Construction began in Q2 2025. The site is expected to be operational in Q4 2026."
    )
    priority = result["priority"]

    assert result["timelines"]["construction_start"]["label"] == "Q2 2025"
    assert result["timelines"]["expected_energization"] is None
    assert priority["priority_basis"]["timing"]["kind"] == "reported_timing_proxy"
    assert priority["priority_basis"]["timing"]["event_type"] == "operational_target"
    assert priority["priority_basis"]["timing"]["source"]["published_at"] == "2025-07-30"
    assert priority["components"]["freshness"] == 0
    assert priority["components"]["phase"] == 0
    assert priority["score"] > 0


def test_ready_for_service_target_is_labeled_as_a_proxy_and_carries_quote_provenance():
    result = resolved("The site has an initial Ready for Service date of Q4-2026.")
    basis = result["priority"]["priority_basis"]["timing"]

    assert basis["kind"] == "reported_timing_proxy"
    assert basis["event_type"] == "ready_for_service"
    assert basis["label"] == "Q4-2026"
    claim = next(
        row for row in result["timelines"]["claims"] if row["fact_id"] == basis["claim_id"]
    )
    assert claim["quote"] == "The site has an initial Ready for Service date of Q4-2026."


def test_actionable_energization_keeps_precedence_over_operational_proxy():
    result = resolved(
        "First energization is expected in Q2 2027. Full operations are targeted for Q4 2027."
    )

    assert result["priority"]["priority_basis"]["timing"]["kind"] == (
        "reported_construction_or_energization"
    )
    assert result["priority"]["priority_basis"]["timing"]["event_type"] == (
        "expected_first_energization"
    )
    assert result["priority"]["components"]["timing"] == 30


def test_future_date_labeled_actual_construction_is_not_an_action_or_phase_bonus():
    from gridlens.domain.customer_intelligence import _priority

    actual = {
        "fact_id": "future-actual",
        "event_type": "actual_construction_start",
        "start": "2027-01-01",
        "end": "2027-01-01",
        "display_label": "2027-01-01",
        "source": source(published_at="2026-10-01"),
    }
    proxy = {
        "fact_id": "reported-operation",
        "event_type": "operational_target",
        "start": "2026-10-01",
        "end": "2026-12-31",
        "display_label": "Q4 2026",
        "source": source(published_at="2025-07-30"),
    }
    result = _priority(
        {"selected_claim_ids": [], "claims": [], "totals": [], "conflicts": []},
        {
            "selected_claim_ids": [actual["fact_id"], proxy["fact_id"]],
            "claims": [actual, proxy],
            "construction_start": actual,
            "expected_energization": None,
            "conflicts": [],
        },
        as_of=AS_OF,
    )

    assert result["priority_basis"]["timing"]["kind"] == "reported_timing_proxy"
    assert result["priority_basis"]["timing"]["event_type"] == "operational_target"
    assert result["components"]["phase"] == 0


def test_future_actual_construction_without_proxy_has_no_timing_priority():
    from gridlens.domain.customer_intelligence import _priority

    actual = {
        "fact_id": "future-actual-only",
        "event_type": "actual_construction_start",
        "start": "2027-01-01",
        "end": "2027-01-01",
        "display_label": "2027-01-01",
        "source": source(published_at="2026-10-01"),
    }
    result = _priority(
        {"selected_claim_ids": [], "claims": [], "totals": [], "conflicts": []},
        {
            "selected_claim_ids": [actual["fact_id"]],
            "claims": [actual],
            "construction_start": actual,
            "expected_energization": None,
            "conflicts": [],
        },
        as_of=AS_OF,
    )

    assert result["components"]["timing"] == 0
    assert result["components"]["phase"] == 0
    assert result["priority_basis"]["timing"]["kind"] == "unknown"


def test_unverified_upper_bound_does_not_beat_small_verified_actionable_project():
    weak_large = resolved(
        "The campus could have up to 1000 MW of IT load.",
        source_ref=source(authority="secondary", verification="unverified"),
    )
    verified_small = resolved(
        "IT load is 80 MW. Construction is expected to start in Q1 2027.",
        source_ref=source(published_at="2026-10-01"),
    )

    assert verified_small["priority"]["score"] > weak_large["priority"]["score"]


def test_absent_or_source_invalid_facts_still_produce_no_priority():
    assert resolved("Plans have been announced.")["priority"]["score"] == 0
    invalid = source()
    invalid["url"] = ""
    facts = extract_customer_facts(
        "Up to 480 MW of IT load is planned.",
        project_id="priority-fixture-project",
        source=invalid,
    )
    result = resolve_customer_intelligence(
        [{"project_id": "priority-fixture-project", "facts": [facts]}], as_of=AS_OF
    )
    assert facts["version"] == FACTS_VERSION
    assert result["priority"]["score"] == 0
