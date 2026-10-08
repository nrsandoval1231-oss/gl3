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
    assert result["qualified_remaining_gap"]["remaining_mw"] == "15"
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
