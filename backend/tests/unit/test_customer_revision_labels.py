"""Commercial revision labels preserve the source's event type."""

import pytest

from gridlens.intelligence.saved_browse import _customer_revision_summary


@pytest.mark.parametrize(
    ("event_type", "expected"),
    [
        ("operational_target", "Operational target revised"),
        ("full_operational_target", "Operational target revised"),
        ("ready_for_service", "Ready-for-service target revised"),
        ("actual_construction_start", "Construction schedule revised"),
        ("announced_construction_start", "Construction schedule revised"),
        ("phase_energization", "Energization schedule revised"),
        ("expected_first_energization", "Energization schedule revised"),
        ("unknown", "Project schedule revised"),
    ],
)
def test_timing_revision_does_not_upgrade_the_event_type(event_type, expected):
    unchanged = {"event_type": "actual_construction_start", "start": "2025-01-01"}
    before = {"event_type": event_type, "start": "2027-01-01", "precision": "year"}
    after = {**before, "start": "2028-01-01"}
    assert (
        _customer_revision_summary(
            {
                "field_name": "build_timing",
                "prior_state": {"value": {"claims": [unchanged, before]}},
                "new_state": {"value": {"claims": [unchanged, after]}},
            }
        )
        == expected
    )


def test_mixed_or_untyped_timing_revision_keeps_a_general_label():
    for before, after in (
        ("Q1 2027", "Q2 2027"),
        (
            {"claims": [{"event_type": "operational_target", "start": "2027"}]},
            {"claims": [{"event_type": "expected_first_energization", "start": "2028"}]},
        ),
    ):
        assert (
            _customer_revision_summary(
                {
                    "field_name": "build_timing",
                    "prior_state": {"value": before},
                    "new_state": {"value": after},
                }
            )
            == "Project schedule revised"
        )
