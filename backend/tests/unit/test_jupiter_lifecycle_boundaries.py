"""Mixed campus/facility reports preserve independently achieved milestones."""

import pytest

from gridlens.domain.lifecycle import classify_event


@pytest.mark.parametrize("permit", ["air permit", "air-permit", "air quality permit"])
def test_procedural_air_permit_event_does_not_establish_campus_formation(permit):
    assert classify_event(
        f"Hearing officer appointed for Project Jupiter data center {permit}."
    ) is None


@pytest.mark.parametrize(
    "milestone,event_type,state",
    [
        ("construction has begun", "construction", "construction"),
        ("utility service is energized", "utility_service", "utility_energization"),
        ("building permit was issued", "building_permit_issued", "permitting"),
    ],
)
@pytest.mark.parametrize("permit", ["air permit", "air quality permit"])
def test_separate_campus_milestone_survives_adjacent_procedure(milestone, event_type, state, permit):
    result = classify_event(
        f"Project Jupiter data center campus {milestone}. "
        f"The adjacent microgrid {permit} remains pending."
    )
    assert result is not None
    assert result.event_type == event_type
    assert result.state == state
