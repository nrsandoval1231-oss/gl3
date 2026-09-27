from datetime import date

import pytest

from gridlens.domain.permit_interpretation import EVALUATOR_VERSION, assess_permit


def permit(description: str, status: str = "Issued") -> dict:
    return {
        "event_date": date.today().isoformat(),
        "html_url": "https://data.example/row/1",
        "permit": {
            "row_id": "1",
            "address": "1 Main St",
            "city": "Chicago",
            "state": "IL",
            "description": description,
            "status": status,
            "source_fields": {"description": "work_description"},
        },
    }


@pytest.mark.parametrize(
    "description",
    [
        "Major remodel of existing manufacturing facility, 128,000 square feet.",
        "Interior remodel to existing manufacturing facility, 20,000 SF.",
        "Convert existing office tower into a data center with new power and cooling systems.",
        "Change use from office to laboratory and lab support; construct tenant improvements.",
        (
            "Foundation for proposed addition to existing F-1 industrial building "
            "for new warehouse use."
        ),
        (
            "New construction of hospital building with associated mechanical electrical "
            "and plumbing work."
        ),
    ],
)
def test_assess_permit_accepts_supported_major_facility_activity(description):
    assessment = assess_permit(permit(description))
    assert assessment["decision"] == "accepted"
    assert assessment["tier"] == "Signal"
    assert assessment["subject"] == "Chicago permit 1"
    assert "investigate construction or commissioning power" in assessment["reason"]
    assert assessment["missing_facts"]


@pytest.mark.parametrize(
    "description,status",
    [
        (
            "Evaluate marijuana processing facility to determine if it is still code compliant.",
            "Issued",
        ),
        ("Install new RTU cooling unit at existing tortilla manufacturing facility.", "Issued"),
        ("Replace lighting in laboratory. TYPE IA CONSTRUCTION.", "Issued"),
        ("New grease interceptor in food processing facility.", "Issued"),
        ("Interior buildout for hospital executive suite office.", "Issued"),
        ("Construct alterations to convert warehouse to restaurant and occupy per plan.", "Issued"),
        ("New racking system and floor striping in existing warehouse.", "Issued"),
        ("Change of use: Office/Business to Adult Care Services; no construction.", "Issued"),
        ("Temporary building activation for cocktail sampling event.", "Issued"),
        ("Complete interior renovation of existing house with detached garage.", "Issued"),
        ("Convert existing office and warehouse space to offices.", "Issued"),
        ("Construct tenant improvements in a warehouse for a commercial tenant.", "Issued"),
        ("Construct site alterations for a named manufacturing plant.", "Issued"),
        ("Construct tenant improvements at an existing hospital level.", "Issued"),
        ("Construct new data center.", "Completed"),
        ("Proposed industrial plant addition.", "Withdrawn"),
    ],
)
def test_assess_permit_rejects_incidental_or_unsupported_work(description, status):
    assessment = assess_permit(permit(description, status))
    assert assessment["decision"] == "rejected"
    assert assessment["tier"] is None
    assert assessment["subject"] is None


def test_assessment_preserves_official_date_and_unknowns():
    assessment = assess_permit(permit("New construction of manufacturing plant."))
    assert EVALUATOR_VERSION == "permit-project-v7"
    assert assessment["issue_date"] == date.today().isoformat()
    assert (
        assessment["issue_date_label"]
        == "Official permit issue date; source publication date unknown"
    )
    assert assessment["power_activity"] == "facility-expansion"


@pytest.mark.parametrize(
    "description,activity,category",
    [
        (
            "Replace natural gas generator and ATS at existing telecom shelter.",
            "backup-power",
            "equipment_continuity",
        ),
        (
            "Temporary rental generator for construction power during utility energization delay.",
            "temporary-power",
            "temporary_power",
        ),
        (
            "Utility service delayed; provide bridge power until energization.",
            "bridge-power",
            "bridge_power",
        ),
        (
            "Festival concert stage, food vendors and powered production October 2-4, 2026.",
            "event-power",
            "powered_event",
        ),
        (
            "Hospital surgery and PACU remodel with electrical system replacement.",
            "backup-power",
            "healthcare_continuity",
        ),
        (
            "Maintenance only: temporary rental generator during switchgear repair; no new construction.",  # noqa: E501
            "temporary-power",
            "temporary_power",
        ),
        (
            "2026/10/02 - 2026/10/04 | Music stages food vendors & hospitality programs.",
            "event-power",
            "powered_event",
        ),
        (
            "Music event October 2-4, 2026 with food vendors; no DJ stage or amplified sound.",
            "event-power",
            "powered_event",
        ),
        (
            "PACU hospital remodel with above and below ceiling/floor work.",
            "backup-power",
            "healthcare_continuity",
        ),
    ],
)
def test_assess_permit_accepts_supported_rental_hypotheses(description, activity, category):
    result = assess_permit(permit(description))
    assert result["decision"] == "accepted"
    assert result["power_activity"] == activity
    assert result["rental_category"] == category
    assert result["rental_hypothesis"].startswith("Inferred;")


@pytest.mark.parametrize(
    "description,status",
    [
        ("Replace lighting in laboratory. TYPE IA CONSTRUCTION.", "Issued"),
        ("Replace light bulbs only; no generator or temporary power.", "Issued"),
        ("Replace generator; temporary power not needed.", "Issued"),
        ("Replace generator; rental generator power is provided.", "Issued"),
        ("Festival tent permit, no electrical or powered event use.", "Issued"),
        ("Permanent generator for stand-alone power plant construction.", "Issued"),
        ("Generator replacement at site.", "Final"),
        ("Replace generator; rental generator power is provided.", "Withdrawn"),
        ("Roof replacement at office; utility service delayed.", "Issued"),
        ("Temporary generator for festival stage September 4-7, 2026.", "Issued"),
        (
            "Temporary activation October 2-11, 2026. Cocktail sampling only; there will not be a DJ stage or amplified sound.",  # noqa: E501
            "Issued",
        ),
    ],
)
def test_assess_permit_rejects_incidental_negated_or_secured_rental_claims(description, status):
    result = assess_permit(permit(description, status))
    assert result["decision"] == "rejected"
    assert result["rental_hypothesis"] is None


@pytest.mark.parametrize(
    "description",
    [
        "Rental generator installed and supplying construction loads.",
        "Temporary generator already installed and operational.",
        "Temporary genset was operating for construction loads.",
    ],
)
def test_assess_permit_rejects_affirmed_operating_temporary_supply(description):
    result = assess_permit(permit(description))
    assert result["decision"] == "rejected"
    assert result["rental_category"] == "secured_supply"
    assert result["rental_hypothesis"] is None


def test_installed_but_not_operational_temporary_generation_remains_open():
    result = assess_permit(
        permit("Generator installed but not operational; temporary rental power still required.")
    )
    assert result["decision"] == "accepted"
    assert result["power_activity"] == "temporary-power"


@pytest.mark.parametrize(
    "description",
    [
        "Temporary generator is not yet installed; rental power required for construction.",
        "Proposed temporary generator will be installed for construction power.",
        "Permanent backup power is available; separate construction power still required.",
        (
            "Temporary generator installed and supplying construction loads; "
            "additional construction power required."
        ),
        (
            "Temporary generator installed and supplying construction loads; "
            "unserved construction load requires rental power."
        ),
    ],
)
def test_assess_permit_preserves_open_temporary_need(description):
    result = assess_permit(permit(description))
    assert result["decision"] == "accepted"
    assert result["power_activity"] == "temporary-power"
    assert result["rental_category"] == "temporary_power"


@pytest.mark.parametrize(
    "description",
    [
        "Temporary generator installed and supplying construction loads; no rental power required.",
        (
            "Temporary generator installed and supplying construction loads; "
            "no additional rental power required."
        ),
        (
            "Temporary generator installed and supplying construction loads; "
            "rental power no longer required."
        ),
        (
            "Temporary power required for construction; rental generator installed "
            "and supplying those construction loads."
        ),
    ],
)
def test_assess_permit_does_not_reopen_fulfilled_or_negated_temporary_need(description):
    result = assess_permit(permit(description))
    assert result["decision"] == "rejected"
    assert result["rental_category"] == "secured_supply"
    assert result["rental_hypothesis"] is None


@pytest.mark.parametrize(
    "description,expected_clause",
    [
        (
            "Temporary generator installed and supplying phase 1; no additional rental power "
            "required for phase 1. Separate construction power required for phase 2.",
            "Separate construction power required for phase 2",
        ),
        (
            "Temporary generator installed and supplying phase 1; no additional rental power "
            "required for phase 1. Unserved construction load requires rental power for phase 2.",
            "Unserved construction load requires rental power for phase 2",
        ),
    ],
)
def test_assess_permit_binds_distinct_remaining_clause_to_rationale(description, expected_clause):
    result = assess_permit(permit(description))
    assert result["decision"] == "accepted"
    assert expected_clause in result["reason"]


def test_distinct_remaining_need_does_not_claim_permanent_backup_is_temporary_supply():
    result = assess_permit(
        permit(
            "Permanent backup power is available; "
            "separate construction rental power still required."
        )
    )
    assert result["decision"] == "accepted"
    assert "separate construction rental power still required" in result["reason"]
    assert "supplied temporary power" not in result["reason"]


def test_event_date_not_permit_issue_or_expiry_controls_current_signal():
    old_event = permit("Permit expires 10/31/2026. Music festival stage, September 4-7, 2026.")
    old_event["event_date"] = "2026-09-26"
    result = assess_permit(old_event, as_of=date(2026, 9, 27))
    assert result["decision"] == "rejected"
    assert result["activity_end_date"] == "2026-09-07"

    future_event = permit("Permit expires 10/31/2026. Music stages food vendors October 2-4, 2026.")
    future_event["event_date"] = "2026-09-26"
    result = assess_permit(future_event, as_of=date(2026, 9, 27))
    assert result["decision"] == "accepted"
    assert result["activity_end_date"] == "2026-10-04"

    final_day = assess_permit(future_event, as_of=date(2026, 10, 4))
    next_day = assess_permit(future_event, as_of=date(2026, 10, 5))
    assert final_day["decision"] == "accepted"
    assert next_day["decision"] == "rejected"
