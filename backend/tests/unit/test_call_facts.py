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


def test_disjoint_timing_and_expiring_supply_conflict_with_current_source_lead():
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
    source = {**source, "semantic_hash": "a" * 64, "evidence_hash": "b" * 64}
    timing = _row(
        "timing",
        {"start_date": "2026-11-01", "end_date": "2026-11-01", "duration_days": 31},
        need_id=need_id,
        project_id=project_id,
    )
    timing.effective_until = datetime(2026, 12, 3, tzinfo=UTC)
    supply = _row(
        "suitable_supply",
        {"mw_min": "25", "mw_max": "30", "quality": "suitable"},
        need_id=need_id,
        project_id=project_id,
    )
    supply.effective_until = datetime(2026, 12, 3, tzinfo=UTC)

    result = qualification_from_facts(source, [timing, supply], need=need, project=project)

    assert result and result.get("qualification_conflict") is True
    assert not result.get("closed_by_fact")
    assert result["tier"] == "Prospect"
    assert "qualified_remaining_gap" not in result
    assert "start_window" not in result and "duration" not in result
    assert "source timing report" in result["reason"]


def test_timing_correction_marker_requires_both_current_source_hashes_and_reason():
    marker = {
        "start_date": "2026-11-01",
        "end_date": "2026-11-01",
        "duration_days": 31,
        "corrects_source_semantic_hash": "a" * 64,
        "corrects_source_evidence_hash": "b" * 64,
        "basis": "Owner confirmed the reported start window was outdated.",
    }
    cleaned = validate_fact("timing", marker)
    assert cleaned == marker
    for invalid in (
        {**marker, "corrects_source_evidence_hash": "bad"},
        {key: value for key, value in marker.items() if key != "corrects_source_semantic_hash"},
        {**marker, "basis": " "},
    ):
        with pytest.raises(ValueError):
            validate_fact("timing", invalid)


def _current_lead_with_november_timing_correction(need_id, project_id):
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
    source = {**source, "semantic_hash": "a" * 64, "evidence_hash": "b" * 64}
    timing_value = validate_fact(
        "timing",
        {
            "start_date": "2026-11-01",
            "end_date": "2026-11-01",
            "duration_days": 31,
            "corrects_source_semantic_hash": "a" * 64,
            "corrects_source_evidence_hash": "b" * 64,
            "basis": "Owner confirmed the current reported window was outdated.",
        },
    )
    timing = _row("timing", timing_value, need_id=need_id, project_id=project_id)
    timing.effective_until = datetime(2026, 12, 3, tzinfo=UTC)
    return source, timing


def test_explicit_disjoint_timing_without_applicable_supply_clears_stale_source_lead():
    need_id, project_id = uuid4(), uuid4()
    need = SimpleNamespace(id=need_id, project_id=project_id, activity_key="construction")
    project = SimpleNamespace(id=project_id, location="Test City")
    source, correction = _current_lead_with_november_timing_correction(need_id, project_id)

    result = qualification_from_facts(source, [correction], need=need, project=project)

    assert result and result["tier"] == "Prospect"
    assert result["closed_by_fact"] is False
    assert "qualified_remaining_gap" not in result
    assert "start_window" not in result and "duration" not in result
    assert str(correction.id) in result["reason"]
    assert correction.content_hash in result["reason"]
    assert "2026-11-01" in result["reason"]
    assert "2027-01-01 to 2027-02-01" in result["reason"]

    correction.effective_until = datetime(2026, 11, 15, tzinfo=UTC)
    partially_effective = qualification_from_facts(
        source, [correction], need=need, project=project
    )
    assert partially_effective and partially_effective["tier"] == "Prospect"
    assert "fact_derived_timing" not in partially_effective

    source_without_shortage = {**source, "supply_quote": None}
    unsupported_shortage = qualification_from_facts(
        source_without_shortage,
        [_current_lead_with_november_timing_correction(need_id, project_id)[1]],
        need=need,
        project=project,
    )
    assert unsupported_shortage and unsupported_shortage["tier"] == "Signal"
    assert "qualified_remaining_gap" not in unsupported_shortage


def test_explicit_disjoint_timing_with_partial_supply_uses_corrected_lead_dates():
    need_id, project_id = uuid4(), uuid4()
    need = SimpleNamespace(id=need_id, project_id=project_id, activity_key="construction")
    project = SimpleNamespace(id=project_id, location="Test City")
    source, correction = _current_lead_with_november_timing_correction(need_id, project_id)
    supply = _row(
        "suitable_supply",
        {"mw_min": "10", "mw_max": "15", "quality": "suitable"},
        need_id=need_id,
        project_id=project_id,
    )
    supply.effective_until = datetime(2026, 12, 3, tzinfo=UTC)

    result = qualification_from_facts(
        source, [correction, supply], need=need, project=project
    )

    assert result and result["tier"] == "Lead"
    assert result["start_window"] == "2026-11-01 to 2026-11-01"
    assert result["duration"] == "31 days"
    gap = result["qualified_remaining_gap"]
    assert (gap["remaining_mw_min"], gap["remaining_mw_max"]) == ("5", "15")
    assert gap["timing_fact_id"] == str(correction.id)
    assert gap["timing_fact_hash"] == correction.content_hash
    assert gap["timing_resolution"] == "explicit_source_correction"
    assert gap["selected_activity_interval_start"] == "2026-11-01T00:00:00+00:00"
    assert gap["selected_activity_interval_end_exclusive"] == "2026-12-02T00:00:00+00:00"
    assert gap["source_reported_start_window"] == source["start_window"]
    assert gap["source_reported_duration"] == source["duration"]


def test_compatible_timing_narrowing_closes_with_timing_version_provenance():
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
    source = {**source, "semantic_hash": "a" * 64, "evidence_hash": "b" * 64}
    source_gap_before = dict(source["qualified_remaining_gap"])
    timing = _row(
        "timing",
        {"start_date": "2027-01-10", "end_date": "2027-01-20", "duration_days": 40},
        need_id=need_id,
        project_id=project_id,
    )
    timing.effective_until = datetime(2027, 3, 1, tzinfo=UTC)
    supply = _row(
        "suitable_supply",
        {"mw_min": "25", "mw_max": "30", "quality": "suitable"},
        need_id=need_id,
        project_id=project_id,
    )
    supply.effective_until = datetime(2027, 3, 1, tzinfo=UTC)

    result = qualification_from_facts(source, [timing, supply], need=need, project=project)

    assert result and result["closed_by_fact"] is True
    basis = result["closure_basis"]
    assert basis["activity_interval_start"] == "2027-01-10T00:00:00+00:00"
    assert basis["activity_interval_end_exclusive"] == "2027-03-01T00:00:00+00:00"
    assert basis["timing_fact_id"] == str(timing.id)
    assert basis["timing_fact_hash"] == timing.content_hash
    assert basis["timing_resolution"] == "compatible_narrowing"
    assert basis["timing_source_semantic_hash"] == "a" * 64
    assert basis["timing_source_evidence_hash"] == "b" * 64

    partial_supply = _row(
        "suitable_supply",
        {"mw_min": "10", "mw_max": "15", "quality": "suitable"},
        need_id=need_id,
        project_id=project_id,
    )
    partial_supply.effective_until = datetime(2027, 3, 1, tzinfo=UTC)
    revised = qualification_from_facts(
        source, [timing, partial_supply], need=need, project=project
    )
    assert revised and revised["tier"] == "Lead"
    gap = revised["qualified_remaining_gap"]
    assert gap["timing_fact_id"] == str(timing.id)
    assert gap["timing_fact_hash"] == timing.content_hash
    assert gap["timing_resolution"] == "compatible_narrowing"
    assert gap["selected_activity_interval_start"] == "2027-01-10T00:00:00+00:00"
    assert gap["selected_activity_interval_end_exclusive"] == "2027-03-01T00:00:00+00:00"
    assert revised["start_window"] == "2027-01-10 to 2027-01-20"
    assert revised["duration"] == "40 days"
    assert gap["start_window"] == revised["start_window"]
    assert gap["duration"] == revised["duration"]
    assert gap["source_reported_start_window"] == source["start_window"]
    assert gap["source_reported_duration"] == source["duration"]

    narrowed_without_new_supply = qualification_from_facts(
        source, [timing], need=need, project=project
    )
    assert narrowed_without_new_supply and narrowed_without_new_supply["tier"] == "Lead"
    assert narrowed_without_new_supply["start_window"] == "2027-01-10 to 2027-01-20"
    assert narrowed_without_new_supply["duration"] == "40 days"
    gap = narrowed_without_new_supply["qualified_remaining_gap"]
    assert gap["start_window"] == "2027-01-10 to 2027-01-20"
    assert gap["duration"] == "40 days"
    assert gap["selected_activity_interval_start"] == "2027-01-10T00:00:00+00:00"
    assert gap["selected_activity_interval_end_exclusive"] == "2027-03-01T00:00:00+00:00"
    assert gap["source_reported_start_window"] == "2027-01-01 to 2027-02-01"
    assert gap["source_reported_duration"] == "31 to 62 days"
    assert source["qualified_remaining_gap"] == source_gap_before


def test_explicit_current_source_timing_correction_can_replace_disjoint_window():
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
    source = {**source, "semantic_hash": "a" * 64, "evidence_hash": "b" * 64}
    correction_value = validate_fact(
        "timing",
        {
            "start_date": "2026-11-01",
            "end_date": "2026-11-01",
            "duration_days": 31,
            "corrects_source_semantic_hash": "a" * 64,
            "corrects_source_evidence_hash": "b" * 64,
            "basis": "Owner confirmed the current reported window was outdated.",
        },
    )
    timing = _row("timing", correction_value, need_id=need_id, project_id=project_id)
    timing.effective_until = datetime(2026, 12, 3, tzinfo=UTC)
    supply = _row(
        "suitable_supply",
        {"mw_min": "25", "mw_max": "30", "quality": "suitable"},
        need_id=need_id,
        project_id=project_id,
    )
    supply.effective_until = datetime(2026, 12, 3, tzinfo=UTC)

    corrected = qualification_from_facts(source, [timing, supply], need=need, project=project)

    assert corrected and corrected["closed_by_fact"] is True
    basis = corrected["closure_basis"]
    assert basis["activity_interval_start"] == "2026-11-01T00:00:00+00:00"
    assert basis["activity_interval_end_exclusive"] == "2026-12-02T00:00:00+00:00"
    assert basis["timing_resolution"] == "explicit_source_correction"
    assert basis["timing_fact_id"] == str(timing.id)
    assert basis["timing_fact_hash"] == timing.content_hash
    assert basis["timing_source_semantic_hash"] == "a" * 64
    assert basis["timing_source_evidence_hash"] == "b" * 64
    assert basis["source_reported_start_window"] == source["start_window"]
    assert basis["source_reported_duration"] == source["duration"]


def test_stale_timing_correction_and_partial_overlap_fail_closed():
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
    source = {**source, "semantic_hash": "a" * 64, "evidence_hash": "b" * 64}
    stale = _row(
        "timing",
        validate_fact(
            "timing",
            {
                "start_date": "2026-11-01",
                "end_date": "2026-11-01",
                "duration_days": 31,
                "corrects_source_semantic_hash": "c" * 64,
                "corrects_source_evidence_hash": "b" * 64,
                "basis": "This correction targets an older source version.",
            },
        ),
        need_id=need_id,
        project_id=project_id,
    )
    stale_supply = _row(
        "suitable_supply",
        {"mw_min": "25", "mw_max": "30", "quality": "suitable"},
        need_id=need_id,
        project_id=project_id,
    )
    stale_supply.effective_until = datetime(2028, 1, 1, tzinfo=UTC)
    stale_result = qualification_from_facts(
        source, [stale, stale_supply], need=need, project=project
    )
    assert stale_result and stale_result["qualification_conflict"]
    assert not stale_result.get("closed_by_fact")
    assert stale_result["tier"] == "Prospect"

    partial = _row(
        "timing",
        {"start_date": "2027-01-20", "end_date": "2027-02-10", "duration_days": 40},
        need_id=need_id,
        project_id=project_id,
    )
    partial_supply = _row(
        "suitable_supply",
        {"mw_min": "25", "mw_max": "30", "quality": "suitable"},
        need_id=need_id,
        project_id=project_id,
    )
    partial_result = qualification_from_facts(
        source, [partial, partial_supply], need=need, project=project
    )
    assert partial_result and partial_result["qualification_conflict"]
    assert not partial_result.get("closed_by_fact")
    assert partial_result["tier"] == "Prospect"


def test_timing_correction_cannot_replace_unreplayable_source_lead_window():
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
    source = {**source, "semantic_hash": "a" * 64, "evidence_hash": "b" * 64}
    source.pop("start_window")
    source.pop("duration")
    timing = _row(
        "timing",
        validate_fact(
            "timing",
            {
                "start_date": "2026-11-01",
                "end_date": "2026-11-01",
                "duration_days": 31,
                "corrects_source_semantic_hash": "a" * 64,
                "corrects_source_evidence_hash": "b" * 64,
                "basis": "The source timing cannot be replayed; do not assume replacement.",
            },
        ),
        need_id=need_id,
        project_id=project_id,
    )
    supply = _row(
        "suitable_supply",
        {"mw_min": "25", "mw_max": "30", "quality": "suitable"},
        need_id=need_id,
        project_id=project_id,
    )
    result = qualification_from_facts(source, [timing, supply], need=need, project=project)
    assert result and result["qualification_conflict"]
    assert result["tier"] == "Prospect"
    assert not result.get("closed_by_fact")
    assert "reported window None" in result["reason"]


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
        "timing_fact_id": str(facts[2].id),
        "timing_fact_hash": facts[2].content_hash,
        "timing_resolution": "operator_timing",
        "timing_basis": None,
        "timing_source_semantic_hash": None,
        "timing_source_evidence_hash": None,
        "start_window": "2027-01-01 to 2027-02-01",
        "duration": "30 days",
        "selected_activity_interval_start": "2027-01-01T00:00:00+00:00",
        "selected_activity_interval_end_exclusive": "2027-03-03T00:00:00+00:00",
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
