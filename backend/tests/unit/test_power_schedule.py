from copy import deepcopy
from types import SimpleNamespace

import pytest

from gridlens.domain.call_facts import fact_digest, qualification_from_facts, validate_fact
from gridlens.domain.opportunity_intelligence import assemble_card, normalize_gap
from gridlens.domain.power_schedule import project_schedule


def schedule():
    return {
        "basis": "Operator-reported phased work plan",
        "source_quote": "The owner described a January commissioning package.",
        "phases": [
            {
                "phase_id": "commissioning",
                "start_date": "2027-01-01",
                "end_date": "2027-02-01",
                "mw_min": "10",
                "mw_max": "12",
                "basis": "Commissioning package",
                "supply_coverage": "confirmed_complete",
                "coverage_reason": "Owner confirmed complete schedule",
            }
        ],
        "supplies": [
            {
                "supply_id": "utility",
                "start_date": "2027-01-15",
                "end_date": "2027-02-01",
                "mw_min": "4",
                "mw_max": "5",
                "state": "committed",
                "suitability": "suitable",
                "service_ready_date": "2027-01-15",
                "source_kind": "utility_grid",
                "date_basis": "Utility letter",
                "basis": "Committed utility service",
            },
            {
                "supply_id": "rental-option",
                "start_date": "2027-01-01",
                "end_date": "2027-02-01",
                "mw_min": "2",
                "mw_max": "3",
                "state": "proposed",
                "suitability": "suitable",
                "date_basis": "Budgetary proposal",
                "basis": "Uncommitted alternative",
                "source_kind": "onsite",
            },
        ],
    }


def test_staggered_supply_partitions_base_and_alternative_scenario():
    value = validate_fact("power_schedule", schedule())
    fact = {
        "value": value,
        "fact_version_id": "v1",
        "content_hash": "a" * 64,
        "source_reference": "call-1",
        "confirmed_at": "2026-10-20T00:00:00Z",
        "authority": "User-confirmed",
        "reporter_name": "A. Operator",
        "reporter_organization": "Example Owner",
        "reporter_role": "Project Engineer",
    }
    result = project_schedule([fact])
    assert result.status == "SUPPORTED_SCENARIO"
    base = [segment for segment in result.segments if segment.scenario == "base"]
    assert [(segment.start_date, segment.end_date) for segment in base] == [
        ("2027-01-01", "2027-01-15"),
        ("2027-01-15", "2027-02-01"),
    ]
    assert (base[0].residual_min_mw, base[0].residual_max_mw) == ("10", "12")
    assert (base[1].supply_min_mw, base[1].supply_max_mw) == ("4", "5")
    alternatives = [segment for segment in result.segments if segment.scenario == "alternative"]
    assert len(alternatives) == 2
    utility = next(supply for supply in result.supplies if supply.supply_id == "utility")
    assert utility.source_kind == "utility_grid"
    assert utility.service_ready_date == "2027-01-15"
    assert result.fact_refs[0].reporter_name == "A. Operator"
    assert result.fact_refs[0].reporter_organization == "Example Owner"
    assert result.fact_refs[0].reporter_role == "Project Engineer"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda x: x["phases"].append(deepcopy(x["phases"][0])),
        lambda x: x["phases"][0].update(start_date="2027-02-30"),
        lambda x: x["phases"][0].update(mw_min="NaN"),
        lambda x: x["phases"][0].update(end_date="2027-01-01"),
        lambda x: x["supplies"].append(deepcopy(x["supplies"][0])),
    ],
)
def test_invalid_schedule_rejected(mutate):
    value = schedule()
    mutate(value)
    with pytest.raises(ValueError):
        validate_fact("power_schedule", value)


def test_distinct_demand_phases_may_not_overlap():
    value = schedule()
    overlap = deepcopy(value["phases"][0])
    overlap.update(phase_id="startup", start_date="2027-01-31", end_date="2027-03-01")
    value["phases"].append(overlap)
    with pytest.raises(ValueError, match="phases may not overlap"):
        validate_fact("power_schedule", value)


def test_partial_unknown_and_confirmed_zero_do_not_invent_supply():
    value = schedule()
    value["phases"][0].update(
        supply_coverage="partial", coverage_reason="Other supplies unverified"
    )
    result = project_schedule([{"value": validate_fact("power_schedule", value)}])
    assert result.status == "UNRESOLVED"
    assert all(s.residual_min_mw is None for s in result.segments if s.scenario == "base")
    unknown_coverage = schedule()
    unknown_coverage["phases"][0].update(
        supply_coverage="unknown", coverage_reason="Supply extent is unknown"
    )
    unknown_result = project_schedule(
        [{"value": validate_fact("power_schedule", unknown_coverage)}]
    )
    assert unknown_result.status == "UNRESOLVED"
    assert all(
        segment.residual_min_mw is None
        for segment in unknown_result.segments
        if segment.scenario == "base"
    )
    zero = schedule()
    zero["supplies"] = []
    zero["zero_supply_basis"] = "Owner confirmed no supply is available"
    zero_result = project_schedule([{"value": validate_fact("power_schedule", zero)}])
    assert zero_result.segments[0].residual_min_mw == "10"
    assert zero_result.segments[0].supply_min_mw == "0"
    missing_basis = schedule()
    missing_basis["supplies"] = []
    missing_basis.pop("zero_supply_basis", None)
    with pytest.raises(ValueError, match="zero-supply basis"):
        validate_fact("power_schedule", missing_basis)


def test_unknown_suitability_and_duplicate_source_claims_stay_unresolved_or_reject():
    unknown = schedule()
    unknown["supplies"][0]["suitability"] = "unknown"
    projection = project_schedule([{"value": validate_fact("power_schedule", unknown)}])
    assert projection.status == "UNRESOLVED"
    utility_overlap = next(
        segment
        for segment in projection.segments
        if segment.scenario == "base" and segment.start_date == "2027-01-15"
    )
    assert utility_overlap.residual_min_mw is None
    duplicate_source = schedule()
    duplicate_source["supplies"][0]["source_reference"] = "utility-letter-1"
    duplicate = deepcopy(duplicate_source["supplies"][0])
    duplicate.update(
        supply_id="utility-copy", start_date="2027-01-10", end_date="2027-01-20", state="operating"
    )
    duplicate.pop("service_ready_date")
    duplicate_source["supplies"].append(duplicate)
    with pytest.raises(ValueError, match="same source reference"):
        validate_fact("power_schedule", duplicate_source)


def test_current_schedule_conflict_is_card_only_and_digest_excludes_schedule():
    base = schedule()
    left = SimpleNamespace(id="a", content_hash="a" * 64, fact_type="power_schedule")
    right = SimpleNamespace(id="b", content_hash="b" * 64, fact_type="power_schedule")
    assert fact_digest([left]) == fact_digest([left, right])
    assert (
        project_schedule(
            [
                {"value": validate_fact("power_schedule", base)},
                {"value": validate_fact("power_schedule", base)},
            ]
        ).status
        == "CONFLICT"
    )
    need, project = (
        SimpleNamespace(project_id="p", activity_key="construction"),
        SimpleNamespace(location="Dallas"),
    )
    result = qualification_from_facts(
        {"tier": "Lead"},
        [
            SimpleNamespace(
                project_id="p",
                activity_key="construction",
                facility_scope="Dallas",
                fact_type="power_schedule",
                value=base,
            ),
            SimpleNamespace(
                project_id="p",
                activity_key="construction",
                facility_scope="Dallas",
                fact_type="power_schedule",
                value={**base, "basis": "Different schedule"},
            ),
        ],
        need=need,
        project=project,
    )
    assert result["tier"] == "Lead"


def test_card_contains_typed_schedule_and_operator_report_provenance():
    record = {
        "id": "n",
        "project_id": "p",
        "tier": "Lead",
        "qualification_version": "qualified-v1",
        "start_window": "2027-01-01",
        "duration": "30 days",
        "qualified_remaining_gap": {
            "required_mw_min": "10",
            "required_mw_max": "12",
            "available_mw_min": "0",
            "available_mw_max": "0",
            "remaining_mw_min": "10",
            "remaining_mw_max": "12",
        },
        "evidence": [],
        "operator_fact_refs": [
            {
                "fact_type": "power_schedule",
                "value": validate_fact("power_schedule", schedule()),
                "fact_version_id": "version-1",
                "content_hash": "c" * 64,
                "source_reference": "call-1",
                "confirmed_at": "2026-10-20T00:00:00Z",
                "authority": "User-confirmed",
            }
        ],
    }
    qualified_gap = normalize_gap(record)
    card = assemble_card(record, {}, {}, [], research_enabled=False)
    assert card.qualification == "Lead" and card.power_gap == qualified_gap
    assert card.power_schedule.status == "SUPPORTED_SCENARIO"
    assert card.power_schedule.fact_refs[0].source_reference == "call-1"
    assert "owner described" in card.power_schedule.fact_refs[0].source_quote
