from datetime import date

from gridlens.domain.lifecycle import AssetType, classify_event, estimate_first_production
from gridlens.intelligence.project_identity import decide_project_match


def test_same_permit_has_asset_specific_meaning() -> None:
    data_center = classify_event("Building permit issued for QTS data center construction")
    upstream = classify_event("Drilling permit issued for STACK well API 35-017-12345")
    fixed = classify_event("Permit application for new natural gas compressor station")

    assert data_center and data_center.state == "construction"
    assert "activity not yet established" in data_center.expected_power_event
    assert upstream and upstream.state == "drilling_permit"
    assert upstream.expected_power_event == "production / electrification power"
    assert fixed and fixed.asset_type == AssetType.COMPRESSOR_STATION
    assert fixed.state == "regulatory_environmental_application"


def test_data_center_events_cover_early_and_late_phases_without_inventing_phases() -> None:
    events = [
        classify_event("Rezoning application for Compass data center campus"),
        classify_event("Building permit for Compass data center construction"),
        classify_event("Load bank commissioning package for Compass data center"),
    ]
    assert [event.state for event in events if event] == [
        "site_control_planning",
        "construction",
        "commissioning",
    ]
    assert classify_event("Routine story about cloud software") is None


def test_upstream_estimate_is_auditable_and_updates_with_reported_milestone() -> None:
    permit = estimate_first_production(
        permit_date=date(2026, 1, 10),
        operator="Continental Resources",
        basin="Anadarko",
        county="Blaine",
        well_id="35-011-12345",
        well_count=2,
    )
    assert (permit.window_start, permit.window_end) == (date(2026, 7, 9), date(2027, 7, 4))
    assert permit.value_kind == "derived"
    assert permit.rule_version == "upstream-production-v1"
    assert permit.missing_evidence == ()
    spud = estimate_first_production(permit_date=date(2026, 1, 10), spud_date=date(2026, 4, 1))
    assert (spud.window_start, spud.window_end) == (date(2026, 5, 31), date(2026, 11, 27))
    assert "reported spud date" in spud.basis


def test_company_name_alone_never_merges_projects() -> None:
    assert decide_project_match(same_owner=True).decision == "separate"
    match = decide_project_match(same_address=True, same_project_name=True, same_owner=True)
    assert match.decision == "matched"
    assert "physical address" in match.reason
