from datetime import date

import pytest

from gridlens.domain.project_research import (
    extract_project_claims,
    project_claim_state,
    qualification_veto,
)

TODAY = date(2026, 10, 4)


def claims(text, activity="construction", published=TODAY):
    return extract_project_claims(
        text,
        references=["Orion Data Center"],
        activity_key=activity,
        published_at=published,
        today=TODAY,
    )


@pytest.mark.parametrize(
    "text,field,value",
    [
        ("Orion Data Center construction is underway.", "phase", "construction_active"),
        ("Orion Data Center commissioning has begun.", "phase", "commissioning"),
        ("Orion Data Center project was cancelled.", "phase", "cancelled"),
        ("Orion Data Center permanent service is energized.", "permanent_service", "energized"),
        ("Orion Data Center permanent service remains pending.", "permanent_service", "pending"),
        ("Orion Data Center construction power is adequate.", "supply_adequacy", "adequate"),
        (
            "Orion Data Center construction temporary service is utility-fed.",
            "temporary_supply",
            "utility",
        ),
        ("Orion Data Center construction requires 400 kW.", "activity_load_mw", "0.4"),
        (
            "Orion Data Center construction is scheduled to start on 2026-11-01.",
            "activity_start",
            "2026-11-01",
        ),
        ("Orion Data Center drilling was completed.", "phase", "drilling_completed"),
        ("Orion Data Center production has begun.", "phase", "production_started"),
    ],
)
def test_explicit_dated_reports(text, field, value):
    assert any(c["field"] == field and c["value"] == value for c in claims(text))


@pytest.mark.parametrize(
    "text",
    [
        "Orion Data Center construction permit approved.",
        "Orion Data Center commissioning may have begun.",
        "Orion Data Center commissioning is scheduled.",
        "Other Data Center construction is underway.",
        "Orion Data Center campus capacity requires 400 MW.",
        "Orion Data Center generator nameplate requires 400 kW.",
        "Orion Data Center production requires 400 kW.",
        "Orion Data Center W1 drilling permit approval.",
        "Orion Data Center flare permission issued.",
    ],
)
def test_no_inference_or_wrong_activity(text):
    assert claims(text) == []


def test_undated_never_admitted_and_construction_never_commissioning():
    assert claims("Orion Data Center construction is underway.", published=None) == []
    assert [c["value"] for c in claims("Orion Data Center construction is underway.")] == [
        "construction_active"
    ]


def test_conflict_and_negative_veto_but_energized_alone_not_adequacy():
    rows = claims(
        "Orion Data Center permanent service is energized.\n"
        "Orion Data Center permanent service remains pending."
    )
    state = project_claim_state(rows, today=TODAY)
    assert state["permanent_service"]["status"] == "CONFLICT"
    assert qualification_veto(state)
    assert qualification_veto(project_claim_state(rows[:1], today=TODAY)) is None
    assert qualification_veto(
        project_claim_state(claims("Orion Data Center project was cancelled."), today=TODAY)
    )


def test_supported_phrase_does_not_hide_unparsed_negative_in_same_clause():
    from gridlens.domain.project_research import unparsed_adverse_text

    text = "Orion Data Center construction is underway but temporary scope was cancelled."
    assert "cancelled" in unparsed_adverse_text(text, claims(text))
    explicit = "Orion Data Center project was cancelled."
    assert "cancelled" not in unparsed_adverse_text(explicit, claims(explicit))


def test_mixed_activity_and_speculative_supply_stay_unknown():
    assert claims("Orion Data Center construction requires 400 kW for commissioning.") == []
    assert claims("Orion Data Center construction power may be insufficient.") == []
    assert claims("Orion Data Center construction power is not insufficient.") == []


def test_negative_not_silently_expired_into_positive_qualification():
    old = date(2025, 1, 1)
    negative = project_claim_state(
        claims("Orion Data Center project was cancelled.", published=old), today=TODAY
    )
    assert qualification_veto(negative)
    stale_positive = project_claim_state(
        claims("Orion Data Center construction is underway.", published=old), today=TODAY
    )
    assert stale_positive["phase"]["status"] == "UNKNOWN"


def test_same_clause_opposing_supply_reports_remain_conflict():
    rows = claims("Orion Data Center construction power is adequate but supply is insufficient.")
    assert project_claim_state(rows, today=TODAY)["supply_adequacy"]["status"] == "CONFLICT"


@pytest.mark.parametrize(
    "text",
    [
        "Orion Data Center contractor reports that construction is underway at 900 Other Rd.",
        "Unlike Orion Data Center, Other Data Center construction requires 200 kW.",
        "Orion Data Center construction requires 200 kW at Other Data Center.",
        "Orion Data Center construction is underway at Other Data Center.",
        "Orion Data Center permanent service is energized at Other Data Center.",
        "Orion Data Center contractor says Other Data Center project was cancelled.",
        "Orion Data Center construction is underway if financing closes.",
        "Orion Data Center construction is underway according to an old 2021 report.",
        'Orion Data Center banner quotes "construction is underway" from 2021.',
        "Orion Data Center construction is underway until commissioning has begun.",
        "Orion Data Center construction power is adequate for Other Data Center.",
        "Orion Data Center construction temporary service at Other Data Center is generator-fed.",
        "Orion Data Center construction machinery requires 200 kW.",
        "Orion Data Center construction requires 200 kW for one pump.",
    ],
)
def test_subject_or_scope_transfer_never_becomes_project_fact(text):
    assert claims(text) == []


def test_exact_named_subject_plus_retained_address_and_date():
    rows = extract_project_claims(
        "Orion Data Center at 811 Clayton Ln, Austin, TX "
        "construction is underway as of 2026-10-03.",
        references=["Orion Data Center", "811 Clayton Ln, Austin, TX"],
        activity_key="construction",
        published_at=TODAY,
        today=TODAY,
    )
    assert [(row["field"], row["value"], row["as_of"]) for row in rows] == [
        ("phase", "construction_active", "2026-10-03")
    ]


@pytest.mark.parametrize("prefix", ["Hypothetical example.", "Historical report.", "Quoted text."])
def test_section_framing_does_not_become_current_fact(prefix):
    assert claims(prefix + " Orion Data Center construction is underway.") == []


@pytest.mark.parametrize(
    "prefix",
    [
        "Template for applicants.",
        "2021 project update.",
        "If funding is approved.",
        "Assuming utility approval.",
        "Sample source language.",
    ],
)
def test_independent_review_contextual_headers_stay_unknown(prefix):
    assert claims(prefix + " Orion Data Center construction is underway.") == []


def test_explicit_old_as_of_and_numeric_site_reference_are_not_header_framing():
    rows = extract_project_claims(
        "2021 Clayton Ln project was cancelled as of 2025-01-01.",
        references=["2021 Clayton Ln"],
        activity_key="construction",
        published_at=TODAY,
        today=TODAY,
    )
    assert rows[0]["value"] == "cancelled"
    assert rows[0]["as_of"] == "2025-01-01"


@pytest.mark.parametrize(
    "text",
    [
        "As of 2021-01-01. Orion Data Center construction is underway.",
        "As of 2026-01-01. Orion Data Center construction is underway.",
        "Schedule as of 2021-01-01. Orion Data Center permanent service is energized.",
        "Orion Data Center schedule as of 2021-01-01. Orion Data Center construction is underway.",
    ],
)
def test_standalone_as_of_header_cannot_borrow_publication_date(text):
    assert claims(text) == []
