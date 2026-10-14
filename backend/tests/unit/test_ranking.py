from datetime import date
from uuid import uuid4

from gridlens.domain.ranking import RANKING_VERSION, WEIGHTS, rank_opportunity

TODAY = date(2026, 10, 14)


def item(**overrides):
    base = {
        "id": uuid4(),
        "project_id": uuid4(),
        "name": "Test project",
        "location": "Unknown",
        "tier": "Signal",
        "activity": "facility-expansion",
        "asset_type": "unknown",
        "lifecycle_state": None,
        "start_window": None,
        "conflict_state": "Not assessed",
        "signal_evidence_state": "active_evidence",
        "title_company": None,
        "evidence": [],
    }
    base.update(overrides)
    return base


def test_weights_sum_to_100_and_version_is_published():
    assert sum(WEIGHTS.values()) == 100
    result = rank_opportunity(item(), None, TODAY)
    assert result["rank_version"] == RANKING_VERSION
    assert 0 <= result["rank_score"] <= 100


def test_dfw_data_center_construction_outranks_distant_unknown_activity():
    strong = item(
        name="Example data center",
        asset_type="data_center",
        lifecycle_state="construction",
        location="Midlothian, TX",
        title_company="Example GC",
        evidence=[{"event_date": "2026-10-01", "title": "building permit", "abstract": ""}],
    )
    weak = item(location="Boston, Massachusetts")
    strong_rank = rank_opportunity(strong, None, TODAY)
    weak_rank = rank_opportunity(weak, None, TODAY)
    assert strong_rank["rank_score"] > weak_rank["rank_score"]
    assert strong_rank["rank_reasons"][0] == "Data-center construction phase"
    assert len(strong_rank["rank_reasons"]) <= 3


def test_strong_non_data_center_can_outrank_weak_data_center():
    # PRD scenario: a valuable non-data-center opportunity can outrank a distant data center.
    oil_and_gas = item(
        tier="Prospect",
        name="Example gas compressor station",
        activity="temporary-power",
        location="Houston, TX",
        start_window="2026-12",
        title_company="Example Midstream",
        evidence=[{"event_date": "2026-10-10", "title": "temporary power", "abstract": ""}],
    )
    distant_dc = item(name="Example data center", asset_type="data_center", location="Ohio")
    assert (
        rank_opportunity(oil_and_gas, None, TODAY)["rank_score"]
        > rank_opportunity(distant_dc, None, TODAY)["rank_score"]
    )


def test_conflict_and_listing_review_reduce_evidence_points():
    clean = rank_opportunity(item(), None, TODAY)["rank_score"]
    conflict = rank_opportunity(item(conflict_state="CONFLICT"), None, TODAY)["rank_score"]
    absent = rank_opportunity(
        item(signal_evidence_state="source_listing_absent"), None, TODAY
    )["rank_score"]
    assert conflict < clean and absent < clean


def test_responsible_contractor_counts_but_unknown_category_does_not():
    chain = {
        "candidates": [
            {"category": "unknown", "organization_relationship": "DIRECT", "organization": "X"},
            {
                "category": "general_contractor",
                "organization_relationship": "DIRECT",
                "organization": "Example GC",
            },
        ]
    }
    ranked = rank_opportunity(item(), chain, TODAY)
    assert ranked["rank_score"] == rank_opportunity(item(), None, TODAY)["rank_score"] + 10
    unknown_only = {"candidates": chain["candidates"][:1]}
    assert (
        rank_opportunity(item(), unknown_only, TODAY)["rank_score"]
        == rank_opportunity(item(), None, TODAY)["rank_score"]
    )


def test_tier_raises_evidence_but_rank_never_changes_tier():
    signal, lead = item(), item(tier="Lead")
    assert rank_opportunity(lead, None, TODAY)["rank_score"] > rank_opportunity(
        signal, None, TODAY
    )["rank_score"]
    assert signal["tier"] == "Signal" and "rank_score" not in signal


def test_priority_geography_adds_its_weight():
    dfw = rank_opportunity(item(location="Plano, TX"), None, TODAY)
    elsewhere = rank_opportunity(item(location="Boston, Massachusetts"), None, TODAY)
    assert dfw["rank_score"] - elsewhere["rank_score"] == WEIGHTS["geography"]
    assert "Priority geography: DFW" in dfw["rank_reasons"]
