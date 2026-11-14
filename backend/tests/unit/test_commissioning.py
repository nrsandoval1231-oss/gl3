"""Engineering scenarios require a scoped, evidenced commissioning plan."""

from copy import deepcopy
from decimal import localcontext

import pytest

from gridlens.domain.commissioning import estimate_commissioning


def block(**changes):
    ref = {
        "url": "https://example.org/project-test-plan.pdf",
        "project_id": "project-1",
        "observed_at": "2026-11-12T00:00:00Z",
        "extraction_method": "reviewed_document",
    }
    result = {
        "project_id": "project-1",
        "block_id": "generator-a",
        "load_scope_id": "load-a",
        "sequence_stage": "stage-1",
        "rating": "2000",
        "unit": "kW",
        "rating_basis": "electrical_output",
        "installed_units": 4,
        "concurrent_units": 2,
        "test_fraction": "0.75",
        "evidence": {key: [deepcopy(ref)] for key in ("rating", "test_fraction", "sequence")},
    }
    result.update(changes)
    return result


def test_campus_announcement_alone_has_no_scenario():
    result = estimate_commissioning([{"project_id": "p", "campus_mw": "1000"}])
    assert result["status"] == "insufficient_data"
    assert result["base_mw"] is None
    assert result["confidence"] == "insufficient"


def test_project_test_sequence_calculates_peak_not_installed_capacity():
    result = estimate_commissioning([block()])
    assert result["status"] == "estimated"
    assert result["base_mw"] == "3"
    assert result["low_mw"] is None and result["high_mw"] is None
    assert result["demand_class"] == "engineering_scenario"
    assert result["verified_customer_demand"] is False
    assert result["input_evidence"]
    assert result["calculation_version"]
    assert result["config_digest"] and result["input_digest"]
    assert result["limitations"] and result["assumptions"]


def test_disjoint_concurrent_blocks_sum_but_sequential_stages_use_maximum():
    result = estimate_commissioning(
        [
            block(),
            block(block_id="b", load_scope_id="b", rating="1", unit="MW", concurrent_units=1),
            block(
                block_id="c",
                load_scope_id="load-a",
                sequence_stage="stage-2",
                rating="8",
                unit="MW",
                concurrent_units=1,
            ),
        ]
    )
    assert result["base_mw"] == "6"
    assert len(result["stage_demands"]) == 2


@pytest.mark.parametrize("field", ["rating", "test_fraction", "sequence"])
def test_missing_input_evidence_abstains(field):
    value = block()
    del value["evidence"][field]
    result = estimate_commissioning([value])
    assert result["status"] == "insufficient_data"
    assert any(field in reason for reason in result["limitations"])


@pytest.mark.parametrize(
    "changes",
    [
        {"rating": "NaN"},
        {"rating": "Infinity"},
        {"rating": "-1"},
        {"test_fraction": "1.01"},
        {"test_fraction": True},
        {"concurrent_units": True},
        {"concurrent_units": 5},
        {"installed_units": 0},
        {"unit": "hp"},
        {"rating_basis": "mechanical_output"},
        {"sequence_stage": ""},
    ],
)
def test_invalid_engineering_inputs_abstain(changes):
    result = estimate_commissioning([block(**changes)])
    assert result["status"] == "insufficient_data"
    assert result["base_mw"] is None


def test_same_load_upstream_and_downstream_is_not_added():
    result = estimate_commissioning([block(), block(block_id="ups-a")])
    assert result["status"] == "insufficient_data"
    assert any("load scope" in reason for reason in result["limitations"])


def test_duplicate_blocks_cannot_double_count():
    result = estimate_commissioning([block(), block(load_scope_id="other")])
    assert result["status"] == "insufficient_data"


def test_independent_projects_are_not_assumed_simultaneous():
    result = estimate_commissioning(
        [block(), block(project_id="other", block_id="b", load_scope_id="b")]
    )
    assert result["status"] == "insufficient_data"


def test_kva_requires_evidenced_power_factor():
    value = block(unit="kVA", power_factor="0.8")
    assert estimate_commissioning([value])["status"] == "insufficient_data"
    value["evidence"]["power_factor"] = deepcopy(value["evidence"]["rating"])
    assert estimate_commissioning([value])["base_mw"] == "2.4"


def test_scenarios_only_with_source_bound_loading_and_concurrency():
    value = block(
        scenarios={
            "low": {"test_fraction": "0.5", "concurrent_units": 1},
            "high": {"test_fraction": "1", "concurrent_units": 4},
        }
    )
    assert estimate_commissioning([value])["status"] == "insufficient_data"
    value["evidence"]["scenarios"] = deepcopy(value["evidence"]["sequence"])
    result = estimate_commissioning([value])
    assert (result["low_mw"], result["base_mw"], result["high_mw"]) == ("1", "3", "8")


def test_reversed_scenario_ranges_abstain():
    value = block(
        scenarios={
            "low": {"test_fraction": "1", "concurrent_units": 4},
            "high": {"test_fraction": "0.5", "concurrent_units": 1},
        }
    )
    value["evidence"]["scenarios"] = deepcopy(value["evidence"]["sequence"])
    assert estimate_commissioning([value])["status"] == "insufficient_data"


def test_evidence_cannot_bind_another_project():
    value = block()
    value["evidence"]["sequence"][0]["project_id"] = "other"
    assert estimate_commissioning([value])["status"] == "insufficient_data"


def test_input_order_and_process_decimal_context_do_not_change_result():
    values = [block(), block(block_id="b", load_scope_id="b", rating="1.23456789", unit="MW")]
    before = deepcopy(values)
    expected = estimate_commissioning(values)
    with localcontext() as context:
        context.prec = 3
        actual = estimate_commissioning(list(reversed(values)))
    assert expected == actual
    assert values == before


def test_config_is_versioned_and_cannot_supply_missing_project_evidence():
    value = block()
    first = estimate_commissioning([value])
    second = estimate_commissioning([value], config={"decimal_places": 3})
    assert first["config_digest"] != second["config_digest"]
    del value["evidence"]["sequence"]
    assert (
        estimate_commissioning([value], config={"decimal_places": 3})["status"]
        == "insufficient_data"
    )
    with pytest.raises(ValueError, match="Unsupported"):
        estimate_commissioning([block()], config={"campus_fraction": "0.1"})


def test_empty_or_partially_valid_plan_does_not_publish_partial_peak():
    assert estimate_commissioning([])["status"] == "insufficient_data"
    result = estimate_commissioning([block(), block(block_id="b", load_scope_id="b", rating=None)])
    assert result["base_mw"] is None


@pytest.mark.parametrize("changes", [{"unit": []}, {"rating_basis": {}}, {"project_id": []}])
def test_malformed_json_values_abstain_without_raising(changes):
    assert estimate_commissioning([block(**changes)])["status"] == "insufficient_data"


def test_generic_engineering_reference_cannot_stand_in_for_project_procedure():
    value = block()
    del value["evidence"]["sequence"][0]["project_id"]
    assert estimate_commissioning([value])["status"] == "insufficient_data"


def test_low_confidence_source_is_not_reported_as_verified():
    assert estimate_commissioning([block()])["confidence"] == "low"
    value = block()
    for references in value["evidence"].values():
        for reference in references:
            reference["verification_status"] = "verified"
    assert estimate_commissioning([value])["confidence"] == "medium"


def test_positive_scenario_below_reporting_precision_is_not_zero():
    result = estimate_commissioning([block(rating="0.000000001")])
    assert result["status"] == "insufficient_data"
    assert result["base_mw"] is None
