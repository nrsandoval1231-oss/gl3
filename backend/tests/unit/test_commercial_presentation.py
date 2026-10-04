import pytest

from gridlens.domain.commercial_presentation import commercial_size_status


def test_inclusive_floor_and_no_maximum():
    assert commercial_size_status("0.299", "construction", None, []) == "below_floor"
    assert commercial_size_status("0.3", "construction", None, []) == "at_or_above_floor"
    assert commercial_size_status("5000", "construction", None, []) == "at_or_above_floor"


def test_unknown_and_ambiguous_ranges_remain_visible():
    assert commercial_size_status(None, "construction", None, []) == "unknown"
    assert (
        commercial_size_status(
            None, "construction", None, ["Activity power requirement: 250–400 kW"]
        )
        == "unknown"
    )
    assert (
        commercial_size_status(
            None, "construction", None, ["Activity power requirement: 300 to 500 kW"]
        )
        == "at_or_above_floor"
    )


def test_activity_scope_small_generator_is_hidden_but_campus_and_nameplate_are_not_used():
    assert (
        commercial_size_status(None, "backup-power", "35 kW generator replacement", [])
        == "below_floor"
    )
    assert (
        commercial_size_status(
            None,
            "construction",
            None,
            ["Campus nameplate capacity: 35 kW", "Eventual operating load: 80 MW"],
        )
        == "unknown"
    )


def test_small_unqualified_power_quote_without_activity_scope_stays_unknown():
    assert commercial_size_status(None, "construction", None, ["Reported: 35 kW"]) == "unknown"


def test_qualified_and_multiple_equipment_values_do_not_prove_total_below_floor():
    assert (
        commercial_size_status(
            None, "construction", None, ["Activity power requirement: over 200 kW"]
        )
        == "unknown"
    )
    assert (
        commercial_size_status(None, "backup-power", "2 x 200 kW generator replacement", [])
        == "unknown"
    )
    assert (
        commercial_size_status(None, "backup-power", "200 kW generator replacement per unit", [])
        == "unknown"
    )


def test_grouped_thousands_and_invalid_required_mw_are_handled_conservatively():
    assert (
        commercial_size_status(None, "construction", None, ["Activity power requirement: 1,000 kW"])
        == "at_or_above_floor"
    )
    for value in ("NaN", "Infinity", "-0.1"):
        assert (
            commercial_size_status(
                value, "construction", None, ["Activity power requirement: 5 MW"]
            )
            == "unknown"
        )


@pytest.mark.parametrize(
    ("low", "high", "expected"),
    [
        ("0.1", "0.299", "below_floor"),
        ("0.3", "0.3", "at_or_above_floor"),
        ("0.2", "0.4", "unknown"),
        ("NaN", "1", "unknown"),
        ("-1", "1", "unknown"),
        ("1", "0.2", "unknown"),
    ],
)
def test_trusted_remaining_gap_overrides_gross_load_for_commercial_floor(low, high, expected):
    assert (
        commercial_size_status(
            "20 MW",
            "construction",
            None,
            [],
            remaining_gap={"remaining_mw_min": low, "remaining_mw_max": high},
        )
        == expected
    )
