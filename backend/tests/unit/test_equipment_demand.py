from dataclasses import replace
from datetime import date
from decimal import ROUND_DOWN, Inexact, localcontext
from decimal import Decimal as D

import pytest

from gridlens.domain.equipment_demand import (
    EquipmentClaim,
    calculate_equipment_demand,
)


def claim(**overrides):
    values = {
        "equipment_id": "pump-1",
        "equipment_type": "pump",
        "drive": "electric",
        "rating": D("100"),
        "unit": "hp",
        "rating_basis": "mechanical_output",
        "count": 1,
        "efficiency": D("0.8"),
        "state": "new",
        "role": "duty",
        "operating_count": 1,
        "source_id": "doc-1",
        "quote": "100 hp electric pump",
    }
    values.update(overrides)
    return EquipmentClaim(**values)


def test_hp_mechanical_rating_requires_and_applies_efficiency():
    result = calculate_equipment_demand([claim()])
    row = result.items[0]
    assert row.mechanical_kw == D("74.569987200")
    assert row.electrical_input_kw == D("93.212484000")
    assert result.connected_kw == D("93.212484000")
    assert result.coincident_kw == D("93.212484000")
    assert result.incremental_kw == D("93.212484000")


def test_electrical_input_is_not_divided_by_efficiency_and_converts_units():
    result = calculate_equipment_demand(
        [claim(rating=D("1.5"), unit="MW", rating_basis="electrical_input")]
    )
    assert result.items[0].electrical_input_kw == D("1500.0")
    assert result.items[0].mechanical_kw is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"unit": "hp", "rating_basis": "electrical_input"},
        {"unit": "kVA", "rating_basis": "mechanical_output"},
        {"drive": "gas_engine", "unit": "kW", "rating_basis": "electrical_input"},
    ],
)
def test_incompatible_drive_unit_and_rating_basis_are_rejected(overrides):
    with pytest.raises(ValueError):
        claim(**overrides)


def test_electrical_output_hp_without_efficiency_is_unknown():
    result = calculate_equipment_demand([claim(efficiency=None)])
    assert result.items[0].mechanical_kw == D("74.569987200")
    assert result.items[0].electrical_input_kw is None
    assert result.coincident_kw is None


@pytest.mark.parametrize("drive", ["gas_engine", "diesel_engine", "steam"])
def test_non_electric_drive_has_no_electric_motor_demand(drive):
    result = calculate_equipment_demand([claim(drive=drive)])
    assert result.items[0].electrical_input_kw == D(0)
    assert result.coincident_kw == D(0)
    assert result.incremental_kw == D(0)


def test_unknown_drive_preserves_unknown_demand():
    result = calculate_equipment_demand([claim(drive="unknown")])
    assert result.items[0].electrical_input_kw is None
    assert result.coincident_kw is None


def test_standby_is_connected_but_not_normal_coincident():
    duty = claim(equipment_id="duty", rating=D("1"), unit="MW", rating_basis="electrical_input")
    standby = claim(
        equipment_id="standby",
        rating=D("1"),
        unit="MW",
        rating_basis="electrical_input",
        role="standby",
        operating_count=0,
    )
    result = calculate_equipment_demand([duty, standby])
    assert result.connected_kw == D("2000")
    assert result.coincident_kw == D("1000")


def test_operating_count_drives_coincidence_and_duty_fraction_only_energy():
    equipment = claim(
        rating=D("1"),
        unit="MW",
        rating_basis="electrical_input",
        count=3,
        operating_count=2,
        duty_fraction=D("0.25"),
        period_hours=D("8"),
    )
    result = calculate_equipment_demand([equipment])
    assert result.connected_kw == D("3000")
    assert result.coincident_kw == D("2000")
    assert result.average_kw == D("500.00")
    assert result.energy_mwh == D("4.000")


def test_unknown_count_or_operating_count_keeps_total_unknown():
    unknown_count = calculate_equipment_demand([claim(count=None, operating_count=None)])
    assert unknown_count.connected_kw is None
    assert unknown_count.coincident_kw is None
    partial = calculate_equipment_demand(
        [
            claim(equipment_id="known"),
            claim(equipment_id="unknown", count=None, operating_count=None),
        ]
    )
    assert partial.connected_kw is None
    assert partial.known_connected_subtotal_kw == D("93.212484000")


def test_kva_requires_power_factor():
    result = calculate_equipment_demand(
        [claim(rating=D("100"), unit="kVA", rating_basis="electrical_input", power_factor=None)]
    )
    assert result.items[0].electrical_input_kw is None


def test_invalid_or_unreasonable_inputs_fail_closed():
    with pytest.raises(ValueError):
        claim(rating=D("-1"))
    with pytest.raises(ValueError):
        claim(rating=D("NaN"))
    with pytest.raises(ValueError):
        claim(efficiency=D("1.01"))
    with pytest.raises(ValueError):
        claim(count=1.5)
    with pytest.raises(ValueError):
        claim(count=100_001)
    with pytest.raises(ValueError):
        claim(drive="combustion")
    with pytest.raises(ValueError):
        claim(count=2, operating_count=3)


def test_duplicate_equipment_claims_deduplicate_or_mark_conflict():
    original = claim()
    exact_copy = replace(original, quote="same equipment described again", source_id="doc-2")
    deduplicated = calculate_equipment_demand([original, exact_copy])
    assert len(deduplicated.items) == 1
    assert deduplicated.electrical_input_kw == D("93.212484000")

    conflicting = calculate_equipment_demand([original, replace(original, rating=D("200"))])
    assert conflicting.items[0].status == "conflicted"
    assert conflicting.electrical_input_kw is None
    assert conflicting.known_connected_subtotal_kw is None


def test_duplicate_ids_are_case_insensitive_and_conflict_hash_is_order_independent():
    original = claim(equipment_id="C-1")
    exact_copy = replace(original, equipment_id="c-1", quote="other citation")
    deduplicated = calculate_equipment_demand([original, exact_copy])
    assert len(deduplicated.items) == 1
    assert deduplicated.items[0].equipment_id == "c-1"

    different = replace(original, equipment_id="c-1", rating=D("200"))
    forward = calculate_equipment_demand([original, different])
    reverse = calculate_equipment_demand([different, original])
    assert forward.items[0].status == "conflicted"
    assert forward.items[0].input_hash == reverse.items[0].input_hash


def test_empty_input_totals_are_unknown():
    result = calculate_equipment_demand([])
    assert result.items == ()
    assert result.connected_kw is None
    assert result.coincident_kw is None
    assert result.incremental_kw is None
    assert result.energy_mwh is None
    assert result.known_connected_subtotal_kw is None


def test_decimal_results_do_not_depend_on_callers_decimal_precision():
    equipment = claim(rating=D("123.456789"), efficiency=D("0.87321"))
    ordinary = calculate_equipment_demand([equipment])
    with localcontext() as context:
        context.prec = 4
        constrained = calculate_equipment_demand([equipment])
    assert constrained.items[0].electrical_input_kw == ordinary.items[0].electrical_input_kw


def test_decimal_canonicalization_is_exact_under_low_precision_context():
    original = claim(equipment_id="same", rating=D("123.456789"))
    different = replace(original, rating=D("123.456788"))
    expected = calculate_equipment_demand([original, different])
    with localcontext() as context:
        context.prec = 4
        context.rounding = ROUND_DOWN
        context.traps[Inexact] = True
        result = calculate_equipment_demand([original, different])
    assert result.items[0].status == "conflicted"
    assert result.items[0].input_hash == expected.items[0].input_hash


def test_calculation_ignores_caller_rounding_and_inexact_trap_settings():
    equipment = claim(rating=D("123.456789"), efficiency=D("0.87321"))
    expected = calculate_equipment_demand([equipment])
    with localcontext() as context:
        context.prec = 4
        context.rounding = ROUND_DOWN
        context.traps[Inexact] = True
        actual = calculate_equipment_demand([equipment])
    assert actual.items[0].electrical_input_kw == expected.items[0].electrical_input_kw
    assert actual.items[0].input_hash == expected.items[0].input_hash


@pytest.mark.parametrize("state", ["existing", "installed"])
def test_existing_equipment_is_not_incremental(state):
    result = calculate_equipment_demand([claim(state=state)])
    assert result.connected_kw == D("93.212484000")
    assert result.incremental_kw == D(0)


def test_future_proposed_equipment_retains_planned_capacity_as_of_today():
    future = claim(
        effective_from=date(2030, 1, 1),
        effective_until=date(2031, 1, 1),
        state="proposed",
    )
    result = calculate_equipment_demand([future], as_of=date(2029, 1, 1))
    assert result.items[0].electrical_input_kw == D("93.212484000")
    assert result.connected_kw == D("93.212484000")
    assert result.incremental_kw == D("93.212484000")
    assert result.coincident_kw == D("93.212484000")


def test_standby_cannot_claim_positive_normal_operating_count():
    with pytest.raises(ValueError):
        claim(role="standby", operating_count=1)


def test_nonoverlapping_equipment_windows_withhold_aggregate_coincident_demand():
    first = claim(
        equipment_id="phase-1",
        rating=D("100"),
        unit="kW",
        rating_basis="electrical_input",
        effective_from=date(2030, 1, 1),
        effective_until=date(2030, 12, 31),
        duty_fraction=D("0.5"),
        period_hours=D("100"),
    )
    second = replace(
        first,
        equipment_id="phase-2",
        effective_from=date(2031, 1, 1),
        effective_until=date(2031, 12, 31),
    )
    result = calculate_equipment_demand([first, second])
    assert result.items[0].coincident_kw == D("100")
    assert result.items[1].coincident_kw == D("100")
    assert result.connected_kw == D("200")
    assert result.coincident_kw is None
    assert result.average_kw is None
    assert result.energy_mwh is None
    assert result.unresolved == ("equipment operating windows do not overlap",)


def test_overlapping_equipment_windows_keep_aggregate_coincident_demand():
    first = claim(
        equipment_id="phase-1",
        rating=D("100"),
        unit="kW",
        rating_basis="electrical_input",
        effective_from=date(2030, 1, 1),
        effective_until=date(2031, 12, 31),
    )
    second = replace(
        first,
        equipment_id="phase-2",
        effective_from=date(2031, 1, 1),
        effective_until=date(2032, 12, 31),
    )
    result = calculate_equipment_demand([first, second])
    assert result.coincident_kw == D("200")
    assert result.unresolved == ()


def test_provenance_and_model_version_are_frozen_in_result():
    result = calculate_equipment_demand([claim()])
    assert result.model_id
    assert result.model_version
    assert result.inputs[0].equipment_id == "pump-1"
    assert result.inputs[0].source_id == "doc-1"
