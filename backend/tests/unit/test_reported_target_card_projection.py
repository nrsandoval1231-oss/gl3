from copy import deepcopy

import pytest

from gridlens.intelligence.customer_results import _compact_commercial


def payload(kind="reported_timing_proxy", event_type="operational_target"):
    return {
        "capacity": {"status": "unknown", "totals": []},
        "timelines": {"construction_start": None, "expected_energization": None},
        "priority": {
            "version": "customer-commercial-priority-v2",
            "priority_basis": {
                "timing": {
                    "kind": kind,
                    "event_type": event_type,
                    "label": "By Q4 2026",
                    "source": {"quote": "Retained source detail."},
                }
            },
        },
    }


def test_card_preserves_reported_target_without_inventing_energization():
    value = payload()
    original = deepcopy(value)
    result = _compact_commercial(value)
    assert result["timelines"]["expected_energization"] is None
    assert result["timelines"]["construction_start"] is None
    assert result["timelines"]["reported_target"] == {
        "event_type": "operational_target",
        "label": "By Q4 2026",
    }
    assert "priority_basis" not in result["priority"]
    assert value == original


@pytest.mark.parametrize(
    "kind,event_type",
    [("unknown", "operational_target"), ("reported_timing_proxy", "commissioning")],
)
def test_unvalidated_or_different_event_is_not_a_reported_target(kind, event_type):
    assert "reported_target" not in _compact_commercial(payload(kind, event_type))["timelines"]
