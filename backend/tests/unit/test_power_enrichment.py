from copy import deepcopy

import pytest

from gridlens.domain.call_facts import validate_fact
from gridlens.domain.power_enrichment import build_power_enrichment


def _schedule(*, phase_id="construction", start="2027-01-01", end="2027-02-01"):
    return validate_fact(
        "power_schedule",
        {
            "basis": "Attributed activity schedule",
            "source_quote": "Construction package estimate",
            "phases": [
                {
                    "phase_id": phase_id,
                    "start_date": start,
                    "end_date": end,
                    "mw_min": "8",
                    "mw_max": "12",
                    "basis": "Construction-specific demand range",
                    "supply_coverage": "unknown",
                    "coverage_reason": "Supply assessment is not complete",
                }
            ],
            "supplies": [],
        },
    )


def _fact(value, *, need_id="need-construction", activity_key="construction", project_id="p1"):
    return {
        "fact_type": "power_schedule",
        "project_id": project_id,
        "need_id": need_id,
        "activity_key": activity_key,
        "facility_scope": "North campus construction package",
        "value": value,
        "fact_version_id": "fact-v1",
        "content_hash": "a" * 64,
        "source_reference": "meeting-17",
        "source_date": "2026-10-19",
        "confirmed_at": "2026-10-20T12:00:00Z",
        "authority": "User-confirmed",
        "reporter_name": "Project engineer",
        "reporter_organization": "Example operator",
        "reporter_role": "Electrical lead",
    }


def _build(facts, needs=None, **kwargs):
    return build_power_enrichment(
        project={"id": "p1", "facility_demand_mw": 200},
        needs=needs
        or [
            {
                "id": "need-construction",
                "project_id": "p1",
                "activity_key": "construction",
                "facility_scope": "North campus construction package",
            }
        ],
        operator_facts=facts,
        **kwargs,
    )


def test_unknown_supply_is_null_and_campus_total_does_not_become_activity_demand():
    result = _build([_fact(_schedule())])
    scenario = result.scenarios[0]
    assert result.status == "UNRESOLVED"
    assert scenario.activity_kind == "construction"
    assert (scenario.demand_mw_min, scenario.demand_mw_max) == ("8", "12")
    assert scenario.supply_status == "unknown"
    assert scenario.supply_mw_min is None
    assert scenario.supply_mw_max is None
    assert scenario.residual_mw_min is None
    assert scenario.demand_mw_max != "200"
    assert scenario.fuel_status == "unknown"
    assert scenario.sources[0].confirmed_at == "2026-10-20T12:00:00Z"
    assert scenario.sources[0].content_hash == "a" * 64
    assert scenario.sources[0].source_date == "2026-10-19"


def test_activity_scopes_remain_separate_and_mismatched_fact_is_ignored():
    construction = _fact(_schedule())
    commissioning = _fact(
        _schedule(phase_id="commissioning"),
        need_id="need-commissioning",
        activity_key="commissioning",
    )
    commissioning["facility_scope"] = "North campus commissioning package"
    construction["value"] = deepcopy(construction["value"])
    needs = [
        {
            "id": "need-construction",
            "project_id": "p1",
            "activity_key": "construction",
            "facility_scope": "North campus construction package",
        },
        {
            "id": "need-commissioning",
            "project_id": "p1",
            "activity_key": "commissioning",
            "facility_scope": "North campus commissioning package",
        },
    ]
    result = _build([construction, commissioning], needs=needs)
    assert {item.activity_kind for item in result.scenarios} == {"construction", "commissioning"}
    assert {item.need_id for item in result.scenarios} == {
        "need-construction",
        "need-commissioning",
    }


def test_estimated_demand_basis_remains_labeled_as_estimate():
    value = _schedule()
    value["phases"][0]["basis"] = "Estimated construction demand range"
    result = _build([_fact(value)])
    assert result.scenarios[0].evidence_status == "estimate"


@pytest.mark.parametrize(
    "activity_key,expected_kind",
    [
        ("facility-demand", "facility_demand"),
        ("construction", "construction"),
        ("commissioning", "commissioning"),
        ("bridge_temporary", "bridge"),
        ("backup-power", "backup"),
    ],
)
def test_facility_and_activity_scenarios_keep_distinct_activity_kinds(activity_key, expected_kind):
    fact = _fact(_schedule(), activity_key=activity_key)
    need = {
        "id": "need-construction",
        "project_id": "p1",
        "activity_key": activity_key,
        "facility_scope": "North campus construction package",
    }
    result = _build([fact], needs=[need])
    assert result.scenarios[0].activity_kind == expected_kind


def test_unsuperseded_schedules_with_conflicting_dates_are_not_combined():
    first = _fact(_schedule())
    second = _fact(_schedule(start="2027-02-01", end="2027-03-01"))
    second.update(fact_version_id="fact-v2", content_hash="b" * 64)
    result = _build([first, second])
    assert result.status == "CONFLICT"
    assert result.scenarios == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("mw_min", "-1"),
        ("mw_min", "NaN"),
        ("mw_max", "7"),
    ],
)
def test_invalid_or_reversed_demand_range_is_rejected(field, value):
    value_schedule = {
        "basis": "Attributed activity schedule",
        "phases": [
            {
                "phase_id": "construction",
                "start_date": "2027-01-01",
                "end_date": "2027-02-01",
                "mw_min": "8",
                "mw_max": "12",
                "basis": "Construction-specific demand range",
                "supply_coverage": "unknown",
                "coverage_reason": "Supply assessment is not complete",
            }
        ],
        "supplies": [],
    }
    value_schedule["phases"][0][field] = value
    with pytest.raises(ValueError):
        validate_fact("power_schedule", value_schedule)


def test_rental_estimate_requires_explicit_sourced_rate_and_uses_transparent_formula():
    confirmed = _schedule()
    confirmed["phases"][0]["supply_coverage"] = "confirmed_complete"
    confirmed["phases"][0]["coverage_reason"] = "Operator confirms zero suitable supply"
    confirmed["zero_supply_basis"] = "Operator confirmed no supply for this interval"
    result = _build(
        [_fact(confirmed)],
        rental_rate={
            "rate_min_usd_per_mw_day": "100",
            "rate_max_usd_per_mw_day": "200",
            "source_reference": "written-rate-card-4",
            "source_date": "2026-10-01",
        },
    )
    estimate = result.scenarios[0].rental_value
    assert estimate is not None
    assert (estimate.minimum, estimate.maximum) == ("24800", "74400")
    assert estimate.status == "estimate"
    assert estimate.formula.startswith("residual MW × duration days")
    assert estimate.rate_source_reference == "written-rate-card-4"


def test_rental_value_does_not_exist_for_unknown_supply_even_with_rate():
    result = _build(
        [_fact(_schedule())],
        rental_rate={
            "rate_min_usd_per_mw_day": "100",
            "rate_max_usd_per_mw_day": "200",
            "source_reference": "written-rate-card-4",
            "source_date": "2026-10-01",
        },
    )
    assert result.scenarios[0].rental_value is None
