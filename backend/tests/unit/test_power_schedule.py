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


def test_alternatives_add_committed_supply_and_remain_independent():
    value = schedule()
    value["phases"][0].update(mw_min="10", mw_max="10", start_date="2027-01-15")
    value["supplies"][1].update(start_date="2027-01-15", mw_min="3", mw_max="3")
    second = deepcopy(value["supplies"][1])
    second.update(supply_id="generator-option", mw_min="2", mw_max="2")
    value["supplies"].append(second)
    result = project_schedule([{"value": validate_fact("power_schedule", value)}])
    alternatives = [s for s in result.segments if s.scenario == "alternative"]
    assert [
        (s.supply_ids, s.supply_min_mw, s.supply_max_mw, s.residual_min_mw, s.residual_max_mw)
        for s in alternatives
    ] == [
        (["utility", "rental-option"], "7", "8", "2", "3"),
        (["utility", "generator-option"], "6", "7", "3", "4"),
    ]


def test_proposed_supply_activates_only_on_service_ready_date():
    value = schedule()
    value["phases"][0].update(start_date="2027-03-01", end_date="2027-04-01")
    value["supplies"] = [
        {
            "supply_id": "future-grid-option",
            "start_date": "2027-03-01",
            "end_date": "2027-04-01",
            "mw_min": "4",
            "mw_max": "5",
            "state": "proposed",
            "suitability": "suitable",
            "source_kind": "utility_grid",
            "service_ready_date": "2027-03-15",
            "date_basis": "Draft utility schedule",
            "basis": "Proposed service",
        }
    ]
    result = project_schedule([{"value": validate_fact("power_schedule", value)}])
    base = [segment for segment in result.segments if segment.scenario == "base"]
    assert [(s.start_date, s.end_date, s.residual_min_mw) for s in base] == [
        ("2027-03-01", "2027-03-15", "10"),
        ("2027-03-15", "2027-04-01", "10"),
    ]
    alternatives = [segment for segment in result.segments if segment.scenario == "alternative"]
    assert [(s.start_date, s.end_date, s.supply_ids) for s in alternatives] == [
        ("2027-03-15", "2027-04-01", ["future-grid-option"]),
    ]
    assert alternatives[0].residual_min_mw == "5"


@pytest.mark.parametrize("state", ["proposed", "hypothetical"])
@pytest.mark.parametrize("ready_date", ["2027-03-15", "2027-03-20", "2027-04-10"])
def test_stored_schedule_does_not_activate_supply_ready_after_its_window(state, ready_date):
    value = schedule()
    value["phases"][0].update(start_date="2027-03-01", end_date="2027-04-01")
    value["supplies"] = [
        {
            "supply_id": "late-grid-option",
            "start_date": "2027-03-01",
            "end_date": "2027-03-15",
            "mw_min": "4",
            "mw_max": "5",
            "state": state,
            "suitability": "suitable",
            "service_ready_date": ready_date,
            "date_basis": "Stored draft schedule",
            "basis": "Hypothetical service",
        }
    ]
    # Project directly to cover previously accepted data that predates stricter validation.
    result = project_schedule([{"value": value}])
    alternatives = [segment for segment in result.segments if segment.scenario == "alternative"]
    assert alternatives == []
    base = [segment for segment in result.segments if segment.scenario == "base"]
    assert all(not segment.supply_ids for segment in base)
    assert all(segment.residual_min_mw == "10" for segment in base)


@pytest.mark.parametrize("state", ["operating", "proposed", "hypothetical"])
@pytest.mark.parametrize("ready_date", ["2027-02-01", "2027-02-02"])
def test_new_schedule_rejects_readiness_on_or_after_supply_end(state, ready_date):
    value = schedule()
    value["supplies"][1].update(state=state, service_ready_date=ready_date)
    with pytest.raises(ValueError, match="service-ready date must precede supply end"):
        validate_fact("power_schedule", value)


@pytest.mark.parametrize(
    "coverage,suitability",
    [("partial", "suitable"), ("confirmed_complete", "unknown")],
)
def test_alternative_remains_unresolved_when_existing_supply_is_unknown(coverage, suitability):
    value = schedule()
    value["phases"][0].update(start_date="2027-01-15", supply_coverage=coverage)
    value["supplies"][0]["suitability"] = suitability
    result = project_schedule([{"value": validate_fact("power_schedule", value)}])
    alternative = next(s for s in result.segments if s.scenario == "alternative")
    assert alternative.supply_min_mw is None
    assert alternative.residual_min_mw is None
    assert alternative.unresolved_reason


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
        "activity": "construction",
        "location": "Dallas, TX",
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
                "need_id": "n",
                "project_id": "p",
                "activity_key": "construction",
                "facility_scope": "Dallas, TX",
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


@pytest.mark.parametrize(
    "mutation",
    [
        {"location": "Austin, TX"},
        {"activity": "temporary_power"},
        {"activity": None},
        {"project_id": "other-project"},
        {"operator_fact_refs": [{"fact_type": "power_schedule", "need_id": "another-need"}]},
        {"operator_fact_refs": [{"fact_type": "power_schedule"}]},
    ],
)
def test_schedule_scope_must_match_current_canonical_need(mutation):
    record = {
        "id": "n",
        "project_id": "p",
        "activity": "construction",
        "location": "Dallas, TX",
        "tier": "Lead",
        "qualification_version": "qualified-v1",
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
                "need_id": "n",
                "project_id": "p",
                "activity_key": "construction",
                "facility_scope": "Dallas, TX",
                "value": validate_fact("power_schedule", schedule()),
                "fact_version_id": "version-1",
                "content_hash": "c" * 64,
            }
        ],
    }
    record.update(mutation)
    result = assemble_card(record, {}, {}, [], research_enabled=False)
    assert result.power_schedule is None
