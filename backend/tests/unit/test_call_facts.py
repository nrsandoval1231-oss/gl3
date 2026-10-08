from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from gridlens.domain.call_facts import (
    fact_digest,
    qualification_from_facts,
    validate_fact,
    validate_timezone,
)
from gridlens.domain.power_qualification import qualify_official_power
from gridlens.domain.workflow_status import WORKFLOW_STATUSES, status_view
from gridlens.intelligence.opportunity_browse import cohort_token


def _row(fact_type: str, value: dict, *, need_id=None, project_id=None):
    return SimpleNamespace(
        id=uuid4(),
        need_id=need_id or uuid4(),
        project_id=project_id or uuid4(),
        activity_key="construction",
        facility_scope="Test City",
        fact_type=fact_type,
        value=value,
        content_hash=f"{fact_type}-{value}",
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
        effective_until=datetime(2028, 1, 1, tzinfo=UTC),
    )


def test_fact_values_are_typed_and_reject_invalid_ranges():
    assert validate_fact("demand", {"mw": "12.50", "basis": "confirmed"}) == {
        "mw": "12.5",
        "basis": "confirmed",
    }
    assert (
        validate_fact(
            "timing", {"start_date": "2027-01-01", "end_date": "2027-03-01", "duration_days": 45}
        )["duration_days"]
        == 45
    )
    with pytest.raises(ValueError, match="positive"):
        validate_fact("demand", {"mw": 0})
    with pytest.raises(ValueError, match="buying organization"):
        validate_fact("buyer", {"organization": "Someone", "role": "consultant"})
    with pytest.raises(ValueError, match="unsupported fields"):
        validate_fact("demand", {"mw": "12", "lead": True})
    with pytest.raises(ValueError, match="2000 characters"):
        validate_fact("demand", {"mw": "12", "basis": "x" * 2001})
    with pytest.raises(ValueError, match="timezone"):
        validate_timezone(datetime(2026, 10, 8), "confirmed_at")
    assert validate_timezone(datetime(2026, 10, 8, tzinfo=UTC), "confirmed_at").tzinfo == UTC


def test_exact_mw_fact_ranges_normalize_without_changing_legacy_scalar_shape():
    assert validate_fact("demand", {"mw_min": 20, "mw_max": "25.0"}) == {
        "mw_min": "20",
        "mw_max": "25",
    }
    assert validate_fact("demand", {"mw": "20 to 25 MW"}) == {
        "mw_min": "20",
        "mw_max": "25",
    }
    assert validate_fact("suitable_supply", {"mw": "0 to 5 MW", "quality": "suitable"}) == {
        "mw_min": "0",
        "mw_max": "5",
        "quality": "suitable",
    }
    assert validate_fact("demand", {"mw": "12.50"}) == {"mw": "12.5"}
    with pytest.raises(ValueError, match="positive numeric"):
        validate_fact("unsuitable_supply", {"mw": "5 to 8 MW"})

    for value in (
        {"mw_min": "25", "mw_max": "20"},
        {"mw_min": "1e999", "mw_max": "2e999"},
        {"mw": "about 20 to 25 MW"},
        {"mw": "up to 25 MW"},
        {"mw": "20+ MW"},
        {"mw": "20 to 25 MW approximately"},
        {"mw": "20 to 25"},
        {"mw_min": "-1", "mw_max": "25"},
        {"mw_min": "20", "mw_max": "1000001"},
        {"mw": "20", "mw_min": "20", "mw_max": "25"},
    ):
        with pytest.raises(ValueError):
            validate_fact("demand", value)


def test_source_demand_ranges_intersect_operator_ranges_and_derive_gap_envelope():
    need_id, project_id = uuid4(), uuid4()
    need = SimpleNamespace(id=need_id, project_id=project_id, activity_key="construction")
    project = SimpleNamespace(id=project_id, location="Test City")
    source_claim = qualify_official_power(
        text=(
            "Test City construction requires 20 to 25 MW. "
            "Power supply for Test City construction is insufficient."
        ),
        site="Test City",
        activity_key="construction",
        location="Test City",
    )
    assert source_claim["tier"] == "Prospect"
    assert source_claim["demand_mw"] == "20 to 25 MW"

    def lead_facts(demand=None, suitable=None):
        facts = [
            _row(
                "timing",
                {"start_date": "2027-01-01", "end_date": "2027-02-01", "duration_days": 31},
                need_id=need_id,
                project_id=project_id,
            ),
            _row(
                "suitable_supply",
                suitable or {"mw": "5", "quality": "suitable"},
                need_id=need_id,
                project_id=project_id,
            ),
            _row(
                "buyer",
                {"organization": "Northstar Electric", "role": "electrical contractor"},
                need_id=need_id,
                project_id=project_id,
            ),
        ]
        if demand is not None:
            facts.append(_row("demand", demand, need_id=need_id, project_id=project_id))
        return facts

    source_only = qualification_from_facts(source_claim, lead_facts(), need=need, project=project)
    assert source_only and source_only["tier"] == "Lead"
    assert source_only["demand_mw"] == "20 to 25 MW"
    assert source_only["qualified_remaining_gap"]["remaining_mw_min"] == "15"
    assert source_only["qualified_remaining_gap"]["remaining_mw_max"] == "20"

    point_facts = lead_facts({"mw": "22"})
    point = qualification_from_facts(source_claim, point_facts, need=need, project=project)
    assert point and point["tier"] == "Lead" and not point.get("qualification_conflict")
    assert point["demand_mw"] == "20 to 25 MW"
    assert point["required_mw"] == "22 MW"
    assert point["fact_derived_required_mw"] == "22 MW"
    assert point["qualified_remaining_gap"]["remaining_mw"] == "17"
    assert point["qualified_remaining_gap"]["required_mw_basis"] == "User-confirmed intersection"
    assert point["qualified_remaining_gap"]["source_demand_mw"] == "20 to 25 MW"
    assert point["qualified_remaining_gap"]["user_confirmed_demand_mw"] == "22 MW"
    demand_row = next(row for row in point_facts if row.fact_type == "demand")
    assert point["qualified_remaining_gap"]["demand_fact_id"] == str(demand_row.id)
    assert point["qualified_remaining_gap"]["demand_fact_hash"] == demand_row.content_hash

    short_point_facts = lead_facts({"mw": "22"})
    short_point = next(row for row in short_point_facts if row.fact_type == "demand")
    short_point.effective_until = datetime(2027, 2, 1, tzinfo=UTC)
    short_result = qualification_from_facts(
        source_claim, short_point_facts, need=need, project=project
    )
    assert short_result and short_result["tier"] == "Prospect"
    assert "qualified_remaining_gap" not in short_result
    assert "fact_derived_required_mw" not in short_result

    overlap = qualification_from_facts(
        source_claim,
        lead_facts({"mw_min": "22", "mw_max": "30"}),
        need=need,
        project=project,
    )
    assert overlap and overlap["tier"] == "Lead" and not overlap.get("qualification_conflict")
    assert overlap["required_mw"] == "22 to 25 MW"
    assert overlap["qualified_remaining_gap"]["remaining_mw_min"] == "17"
    assert overlap["qualified_remaining_gap"]["remaining_mw_max"] == "20"

    conflict = qualification_from_facts(
        source_claim,
        lead_facts({"mw_min": "26", "mw_max": "30"}),
        need=need,
        project=project,
    )
    assert conflict and conflict["tier"] == "Signal" and conflict["qualification_conflict"]


@pytest.mark.parametrize(
    ("supply", "expected_tier"),
    [
        ({"mw": "0", "quality": "suitable"}, "Lead"),
        ({"mw_min": "5", "mw_max": "7", "quality": "suitable"}, "Lead"),
        ({"mw_min": "20", "mw_max": "21", "quality": "suitable"}, "Prospect"),
        ({"mw_min": "5", "mw_max": "7", "quality": "unknown"}, "Prospect"),
        ({"mw_min": "5", "mw_max": "7", "quality": "unsuitable"}, "Prospect"),
    ],
)
def test_supply_range_uses_conservative_gap_and_zero_gap_abstention(supply, expected_tier):
    need_id, project_id = uuid4(), uuid4()
    need = SimpleNamespace(id=need_id, project_id=project_id, activity_key="construction")
    project = SimpleNamespace(id=project_id, location="Test City")
    source = {
        "tier": "Prospect",
        "demand_mw": "20 to 25 MW",
        "supply_quote": "Power supply for Test City construction is insufficient.",
    }
    facts = [
        _row(
            "timing",
            {"start_date": "2027-01-01", "end_date": "2027-02-01", "duration_days": 31},
            need_id=need_id,
            project_id=project_id,
        ),
        _row("suitable_supply", supply, need_id=need_id, project_id=project_id),
        _row(
            "buyer",
            {"organization": "Northstar Electric", "role": "electrical contractor"},
            need_id=need_id,
            project_id=project_id,
        ),
    ]
    result = qualification_from_facts(source, facts, need=need, project=project)
    assert result and result["tier"] == expected_tier
    if expected_tier == "Lead":
        gap = result["qualified_remaining_gap"]
        if supply.get("mw") == "0":
            assert (gap["remaining_mw_min"], gap["remaining_mw_max"]) == ("20", "25")
        else:
            assert (gap["remaining_mw_min"], gap["remaining_mw_max"]) == ("13", "20")
    else:
        assert "qualified_remaining_gap" not in result


def test_full_window_adequate_supply_reconciles_source_prospect_to_inactive():
    need_id, project_id = uuid4(), uuid4()
    need = SimpleNamespace(id=need_id, project_id=project_id, activity_key="construction")
    project = SimpleNamespace(id=project_id, location="Test City")
    source = qualify_official_power(
        text=(
            "Test City construction requires 20 to 25 MW. "
            "Power supply for Test City construction is insufficient."
        ),
        site="Test City",
        activity_key="construction",
        location="Test City",
    )
    source = {**source, "semantic_hash": "source-semantic", "evidence_hash": "source-evidence"}
    timing = _row(
        "timing",
        {"start_date": "2027-01-01", "end_date": "2027-02-01", "duration_days": 31},
        need_id=need_id,
        project_id=project_id,
    )
    adequate = _row(
        "suitable_supply",
        {"mw_min": "25", "mw_max": "30", "quality": "suitable"},
        need_id=need_id,
        project_id=project_id,
    )
    adequate.effective_until = datetime(2027, 3, 4, tzinfo=UTC)
    without_window = qualification_from_facts(source, [adequate], need=need, project=project)
    assert without_window and not without_window.get("closed_by_fact")
    result = qualification_from_facts(source, [timing, adequate], need=need, project=project)

    assert result and result["closed_by_fact"] is True
    assert result["closure_basis"]["kind"] == "confirmed_adequate_supply"
    assert result["closure_basis"]["suitable_supply_fact_id"] == str(adequate.id)
    assert result["closure_basis"]["suitable_supply_fact_hash"] == adequate.content_hash
    assert result["closure_basis"]["source_semantic_hash"] == "source-semantic"
    assert result["closure_basis"]["source_evidence_hash"] == "source-evidence"
    assert result["closure_basis"]["activity_interval_end_exclusive"] == (
        "2027-03-04T00:00:00+00:00"
    )
    assert result["tier"] == "Signal"
    assert result["required_mw"] is None
    assert "qualified_remaining_gap" not in result


def test_full_window_adequate_supply_reconciles_source_lead_without_operator_buyer_or_timing():
    need_id, project_id = uuid4(), uuid4()
    need = SimpleNamespace(id=need_id, project_id=project_id, activity_key="construction")
    project = SimpleNamespace(id=project_id, location="Test City")
    source = qualify_official_power(
        text=(
            "Test City construction requires 20 to 25 MW. "
            "Power supply for Test City construction is insufficient. "
            "Test City construction starts between 2027-01-01 and 2027-02-01. "
            "Test City construction lasts 31 to 62 days. "
            "No suitable power supply is available for Test City construction throughout this "
            "start window and duration. The electrical contractor is responsible for power "
            "procurement for Test City construction."
        ),
        site="Test City",
        activity_key="construction",
        location="Test City",
    )
    assert source["tier"] == "Lead"
    source = {**source, "semantic_hash": "lead-semantic", "evidence_hash": "lead-evidence"}
    adequate = _row(
        "suitable_supply",
        {"mw_min": "25", "mw_max": "30", "quality": "suitable"},
        need_id=need_id,
        project_id=project_id,
    )
    adequate.effective_until = datetime(2027, 4, 4, tzinfo=UTC)

    result = qualification_from_facts(source, [adequate], need=need, project=project)

    assert result and result["closed_by_fact"] is True
    assert result["closure_basis"]["kind"] == "confirmed_adequate_supply"
    assert result["closure_basis"]["suitable_supply_fact_id"] == str(adequate.id)
    assert result["closure_basis"]["suitable_supply_fact_hash"] == adequate.content_hash
    assert result["closure_basis"]["source_semantic_hash"] == "lead-semantic"
    assert result["closure_basis"]["source_evidence_hash"] == "lead-evidence"
    assert result["closure_basis"]["activity_interval_end_exclusive"] == (
        "2027-04-04T00:00:00+00:00"
    )
    assert result["tier"] == "Signal"
    assert result["required_mw"] is None
    assert "qualified_remaining_gap" not in result


def test_source_lead_reconciles_partial_and_possible_zero_gap_without_stale_lead():
    need_id, project_id = uuid4(), uuid4()
    need = SimpleNamespace(id=need_id, project_id=project_id, activity_key="construction")
    project = SimpleNamespace(id=project_id, location="Test City")
    source = qualify_official_power(
        text=(
            "Test City construction requires 20 to 25 MW. "
            "Power supply for Test City construction is insufficient. "
            "Test City construction starts between 2027-01-01 and 2027-02-01. "
            "Test City construction lasts 31 to 62 days. "
            "No suitable power supply is available for Test City construction throughout this "
            "start window and duration. The electrical contractor is responsible for power "
            "procurement for Test City construction."
        ),
        site="Test City",
        activity_key="construction",
        location="Test City",
    )
    assert source["tier"] == "Lead"
    assert source["qualified_remaining_gap"]["remaining_mw_min"] == "20"

    partial = _row(
        "suitable_supply",
        {"mw_min": "10", "mw_max": "15", "quality": "suitable"},
        need_id=need_id,
        project_id=project_id,
    )
    recomputed = qualification_from_facts(source, [partial], need=need, project=project)
    assert recomputed and recomputed["tier"] == "Lead"
    assert (recomputed["qualified_remaining_gap"]["remaining_mw_min"],
            recomputed["qualified_remaining_gap"]["remaining_mw_max"]) == ("5", "15")
    assert recomputed["qualified_remaining_gap"]["suitable_supply_fact_id"] == str(partial.id)
    assert (
        recomputed["qualified_remaining_gap"]["suitable_supply_fact_hash"]
        == partial.content_hash
    )

    possible_zero = _row(
        "suitable_supply",
        {"mw_min": "20", "mw_max": "30", "quality": "suitable"},
        need_id=need_id,
        project_id=project_id,
    )
    lower_tier = qualification_from_facts(source, [possible_zero], need=need, project=project)
    assert lower_tier and lower_tier["tier"] == "Prospect"
    assert "qualified_remaining_gap" not in lower_tier
    assert "start_window" not in lower_tier and "duration" not in lower_tier
    assert lower_tier["closed_by_fact"] is False

    incomplete = _row(
        "suitable_supply",
        {"mw_min": "25", "mw_max": "30", "quality": "suitable"},
        need_id=need_id,
        project_id=project_id,
    )
    incomplete.effective_until = datetime(2027, 4, 3, tzinfo=UTC)
    unchanged = qualification_from_facts(source, [incomplete], need=need, project=project)
    assert unchanged and unchanged["tier"] == "Lead"
    assert not unchanged.get("closed_by_fact")
    assert unchanged["qualified_remaining_gap"] == source["qualified_remaining_gap"]

    unknown_quality = _row(
        "suitable_supply",
        {"mw_min": "25", "mw_max": "30", "quality": "unknown"},
        need_id=need_id,
        project_id=project_id,
    )
    not_confirmed = qualification_from_facts(source, [unknown_quality], need=need, project=project)
    assert not_confirmed and not not_confirmed.get("closed_by_fact")
    assert not_confirmed["tier"] == "Lead"


def test_current_signal_can_close_only_with_supported_full_window_need_facts():
    need_id, project_id = uuid4(), uuid4()
    need = SimpleNamespace(id=need_id, project_id=project_id, activity_key="construction")
    project = SimpleNamespace(id=project_id, location="Test City")
    facts = [
        _row("demand", {"mw": "20"}, need_id=need_id, project_id=project_id),
        _row("unsuitable_supply", {"mw": "3"}, need_id=need_id, project_id=project_id),
        _row(
            "timing",
            {"start_date": "2027-01-01", "end_date": "2027-02-01", "duration_days": 31},
            need_id=need_id,
            project_id=project_id,
        ),
        _row(
            "suitable_supply",
            {"mw_min": "20", "mw_max": "24", "quality": "suitable"},
            need_id=need_id,
            project_id=project_id,
        ),
    ]
    base = {
        "tier": "Signal",
        "reason": "Current exact-need support is incomplete.",
        "semantic_hash": "signal-semantic",
        "evidence_hash": "signal-evidence",
    }
    result = qualification_from_facts(base, facts, need=need, project=project)
    assert result and result["closed_by_fact"] is True
    assert result["closure_basis"]["kind"] == "confirmed_adequate_supply"
    assert result["closure_basis"]["demand_fact_id"] == str(facts[0].id)
    assert result["closure_basis"]["source_semantic_hash"] == "signal-semantic"

    # A workflow status is not an input and cannot substitute for a supply fact.
    only_shortage = qualification_from_facts(base, facts[:2], need=need, project=project)
    assert only_shortage and only_shortage["tier"] == "Prospect"
    assert not only_shortage.get("closed_by_fact")


def test_facts_require_exact_scope_and_current_source_base():
    need_id, project_id = uuid4(), uuid4()
    need = SimpleNamespace(id=need_id, project_id=project_id, activity_key="construction")
    project = SimpleNamespace(id=project_id, location="Test City")
    facts = [
        _row("demand", {"mw": "20"}, need_id=need_id, project_id=project_id),
        _row("unsuitable_supply", {"mw": "0.1"}, need_id=need_id, project_id=project_id),
    ]
    assert qualification_from_facts(None, facts, need=need, project=project) is None
    result = qualification_from_facts(
        {"tier": "Signal", "reason": "Current admitted public project evidence."},
        facts,
        need=need,
        project=project,
    )
    assert result and result["tier"] == "Prospect"
    assert result["required_mw"] == "20 MW"
    wrong_site = SimpleNamespace(id=project_id, location="Another City")
    conflict = qualification_from_facts(
        {"tier": "Signal", "reason": "Current source claim."}, facts, need=need, project=wrong_site
    )
    assert conflict and conflict["tier"] == "Signal" and conflict["qualification_conflict"]
    facts[0].activity_key = "operations"
    wrong_activity = qualification_from_facts(
        {"tier": "Signal", "reason": "Current source claim."},
        facts,
        need=need,
        project=project,
    )
    assert wrong_activity and wrong_activity["qualification_conflict"]


def test_lead_requires_current_gap_interval_and_buyer_facts():
    need_id, project_id = uuid4(), uuid4()
    need = SimpleNamespace(id=need_id, project_id=project_id, activity_key="construction")
    project = SimpleNamespace(id=project_id, location="Test City")
    facts = [
        _row("demand", {"mw": "20"}, need_id=need_id, project_id=project_id),
        _row("unsuitable_supply", {"mw": "2"}, need_id=need_id, project_id=project_id),
        _row(
            "timing",
            {"start_date": "2027-01-01", "end_date": "2027-02-01", "duration_days": 30},
            need_id=need_id,
            project_id=project_id,
        ),
        _row(
            "suitable_supply",
            {"mw": "5", "quality": "suitable"},
            need_id=need_id,
            project_id=project_id,
        ),
        _row(
            "buyer",
            {"organization": "Northstar Electric", "role": "electrical contractor"},
            need_id=need_id,
            project_id=project_id,
        ),
    ]
    result = qualification_from_facts(
        {"tier": "Signal", "reason": "Current admitted public source."},
        facts,
        need=need,
        project=project,
    )
    assert result and result["tier"] == "Lead"
    assert result["qualified_remaining_gap"] == {
        "required_mw": "20",
        "available_mw": "5",
        "value_kind": "Derived",
        "suitable_supply_basis": "User-confirmed",
        "suitable_supply_fact_id": str(facts[3].id),
        "suitable_supply_fact_hash": facts[3].content_hash,
        "source_semantic_hash": None,
        "source_evidence_hash": None,
        "source_reported_supply_quote": None,
        "remaining_mw": "15",
    }
    assert "Northstar Electric" in result["qualification_next_action"]
    assert (
        qualification_from_facts(
            {"tier": "Signal", "reason": "Current admitted public source."},
            facts[:-1],
            need=need,
            project=project,
        )["tier"]
        == "Prospect"
    )


def test_official_prospect_can_reach_lead_without_redundant_demand_or_shortage_facts():
    need_id, project_id = uuid4(), uuid4()
    need = SimpleNamespace(id=need_id, project_id=project_id, activity_key="construction")
    project = SimpleNamespace(id=project_id, location="Test City")
    source_text = (
        "Test City construction requires 20 MW. "
        "Power supply for Test City construction is insufficient."
    )
    source_claim = qualify_official_power(
        text=source_text,
        site="Test City",
        activity_key="construction",
        location="Test City",
    )
    assert source_claim["tier"] == "Prospect"
    facts = [
        _row(
            "timing",
            {"start_date": "2027-01-01", "end_date": "2027-02-01", "duration_days": 31},
            need_id=need_id,
            project_id=project_id,
        ),
        _row(
            "suitable_supply",
            {"mw": "5", "quality": "suitable"},
            need_id=need_id,
            project_id=project_id,
        ),
        _row(
            "buyer",
            {"organization": "Northstar Electric", "role": "electrical contractor"},
            need_id=need_id,
            project_id=project_id,
        ),
    ]

    result = qualification_from_facts(source_claim, facts, need=need, project=project)

    assert result and result["tier"] == "Lead"
    assert result["demand_mw"] == "20 MW"
    assert result["qualified_remaining_gap"]["remaining_mw"] == "15"
    assert qualification_from_facts(source_claim, facts[:-1], need=need, project=project)[
        "tier"
    ] == "Prospect"
    unknown_supply = [
        facts[0],
        _row(
            "suitable_supply",
            {"mw": "5", "quality": "unknown"},
            need_id=need_id,
            project_id=project_id,
        ),
        facts[2],
    ]
    assert qualification_from_facts(source_claim, unknown_supply, need=need, project=project)[
        "tier"
    ] == "Prospect"


@pytest.mark.parametrize(
    ("effective_from", "effective_until", "expected_tier"),
    [
        ("2026-01-01T00:00:00+00:00", "2026-10-09T00:00:00+00:00", "Prospect"),
        ("2026-01-01T00:00:00+00:00", "2027-02-01T00:00:00+00:00", "Prospect"),
        # The latest possible activity ends at this exclusive boundary.
        ("2026-01-01T00:00:00+00:00", "2027-03-04T00:00:00+00:00", "Lead"),
        ("2027-01-02T00:00:00+00:00", "2027-04-01T00:00:00+00:00", "Prospect"),
    ],
)
def test_suitable_supply_must_cover_full_activity_window(
    effective_from, effective_until, expected_tier
):
    need_id, project_id = uuid4(), uuid4()
    need = SimpleNamespace(id=need_id, project_id=project_id, activity_key="construction")
    project = SimpleNamespace(id=project_id, location="Test City")
    facts = [
        _row("demand", {"mw": "20"}, need_id=need_id, project_id=project_id),
        _row("unsuitable_supply", {"mw": "2"}, need_id=need_id, project_id=project_id),
        _row(
            "timing",
            {"start_date": "2027-01-01", "end_date": "2027-02-01", "duration_days": 31},
            need_id=need_id,
            project_id=project_id,
        ),
        _row(
            "suitable_supply",
            {"mw": "5", "quality": "suitable"},
            need_id=need_id,
            project_id=project_id,
        ),
        _row(
            "buyer",
            {"organization": "Northstar Electric", "role": "electrical contractor"},
            need_id=need_id,
            project_id=project_id,
        ),
    ]
    suitable = next(row for row in facts if row.fact_type == "suitable_supply")
    suitable.effective_from = datetime.fromisoformat(effective_from)
    suitable.effective_until = datetime.fromisoformat(effective_until)

    result = qualification_from_facts(
        {"tier": "Signal", "reason": "Current admitted public source."},
        facts,
        need=need,
        project=project,
    )

    assert result and result["tier"] == expected_tier
    if expected_tier == "Lead":
        assert result["qualified_remaining_gap"]["remaining_mw"] == "15"
    else:
        assert "qualified_remaining_gap" not in result


@pytest.mark.parametrize(
    ("fact_type", "missing_attribute"),
    [
        (fact_type, attribute)
        for fact_type in ("demand", "unsuitable_supply", "timing", "suitable_supply", "buyer")
        for attribute in ("effective_from", "effective_until")
    ],
)
def test_missing_effective_interval_on_lead_support_fails_closed(fact_type, missing_attribute):
    need_id, project_id = uuid4(), uuid4()
    need = SimpleNamespace(id=need_id, project_id=project_id, activity_key="construction")
    project = SimpleNamespace(id=project_id, location="Test City")
    facts = [
        _row("demand", {"mw": "20"}, need_id=need_id, project_id=project_id),
        _row("unsuitable_supply", {"mw": "2"}, need_id=need_id, project_id=project_id),
        _row(
            "timing",
            {"start_date": "2027-01-01", "end_date": "2027-02-01", "duration_days": 31},
            need_id=need_id,
            project_id=project_id,
        ),
        _row(
            "suitable_supply",
            {"mw": "5", "quality": "suitable"},
            need_id=need_id,
            project_id=project_id,
        ),
        _row(
            "buyer",
            {"organization": "Northstar Electric", "role": "electrical contractor"},
            need_id=need_id,
            project_id=project_id,
        ),
    ]
    delattr(next(row for row in facts if row.fact_type == fact_type), missing_attribute)

    result = qualification_from_facts(
        {"tier": "Signal", "reason": "Current admitted public source."},
        facts,
        need=need,
        project=project,
    )

    assert result and result["tier"] == "Prospect"
    assert "qualified_remaining_gap" not in result


def test_open_ended_accepted_intervals_cover_future_activity():
    need_id, project_id = uuid4(), uuid4()
    need = SimpleNamespace(id=need_id, project_id=project_id, activity_key="construction")
    project = SimpleNamespace(id=project_id, location="Test City")
    facts = [
        _row("demand", {"mw": "20"}, need_id=need_id, project_id=project_id),
        _row("unsuitable_supply", {"mw": "2"}, need_id=need_id, project_id=project_id),
        _row(
            "timing",
            {"start_date": "2027-01-01", "end_date": "2027-02-01", "duration_days": 31},
            need_id=need_id,
            project_id=project_id,
        ),
        _row(
            "suitable_supply",
            {"mw": "5", "quality": "suitable"},
            need_id=need_id,
            project_id=project_id,
        ),
        _row(
            "buyer",
            {"organization": "Northstar Electric", "role": "electrical contractor"},
            need_id=need_id,
            project_id=project_id,
        ),
    ]
    for row in facts:
        row.effective_until = None

    result = qualification_from_facts(
        {"tier": "Signal", "reason": "Current admitted public source."},
        facts,
        need=need,
        project=project,
    )

    assert result and result["tier"] == "Lead"


def test_fact_conflicts_closure_and_digest_are_visible():
    need_id, project_id = uuid4(), uuid4()
    need = SimpleNamespace(id=need_id, project_id=project_id, activity_key="construction")
    project = SimpleNamespace(id=project_id, location="Test City")
    base = {"tier": "Signal", "reason": "Current source support."}
    conflict = [
        _row("demand", {"mw": "10"}, need_id=need_id, project_id=project_id),
        _row("demand", {"mw": "20"}, need_id=need_id, project_id=project_id),
    ]
    result = qualification_from_facts(base, conflict, need=need, project=project)
    assert result and result["tier"] == "Signal" and result["qualification_conflict"]
    closed = qualification_from_facts(
        base,
        [_row("closure", {"state": "adequate_supply"}, need_id=need_id, project_id=project_id)],
        need=need,
        project=project,
    )
    assert closed and closed["tier"] == "Signal" and closed["closed_by_fact"]
    assert fact_digest(conflict) != fact_digest(conflict[:1])


def test_material_current_fact_and_workflow_changes_invalidate_browse_cohort():
    base = {
        "id": "need-1",
        "_cohort_version": "same-need-timestamp",
        "tier": "Signal",
        "project_id": "project-1",
        "_current_fact_digest": "accepted-fact-a",
        "workflow_status": "UNKNOWN",
    }
    first = cohort_token({}, [base], ["group-1"])
    corrected = {**base, "_current_fact_digest": "accepted-fact-b"}
    changed_fact = cohort_token({}, [corrected], ["group-1"])
    changed_status = cohort_token({}, [{**base, "workflow_status": "Investigating"}], ["group-1"])
    assert first != changed_fact
    assert first != changed_status


def test_workflow_status_has_no_implicit_new_and_only_declared_states():
    assert WORKFLOW_STATUSES == {
        "New",
        "Investigating",
        "Contacted",
        "Qualified",
        "Won",
        "Lost",
        "Closed",
    }
    assert status_view([]) == {"status": "UNKNOWN", "version": 0, "events": []}
    events = [
        SimpleNamespace(status="Investigating", version=1),
        SimpleNamespace(status="Closed", version=2),
    ]
    assert status_view(events)["status"] == "Closed"
