from datetime import date, timedelta

import pytest

from gridlens.domain.project_research import (
    FIELDS,
    _project_claim_accumulator,
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
    "text,field,value",
    [
        ("Orion Data Center facility electrical demand is 12 MW.", "facility_demand_mw", "12"),
        (
            "Orion Data Center construction temporary power fuel is available.",
            "fuel_availability",
            "available",
        ),
        (
            "Orion Data Center construction temporary power voltage requirement is 480 V, 3 phase.",
            "voltage",
            "480 V, 3 phase",
        ),
        (
            "Orion Data Center construction load profile is continuous.",
            "load_profile",
            "continuous",
        ),
        (
            "Orion Data Center construction temporary power procurement is delayed.",
            "procurement_status",
            "delayed",
        ),
        (
            "Orion Data Center construction utility interconnection is blocked.",
            "utility_obstacle",
            "blocked",
        ),
    ],
)
def test_explicit_electrical_and_procurement_reports_are_typed(text, field, value):
    row = next(c for c in claims(text) if c["field"] == field)
    assert row["value"] == value
    if field != "facility_demand_mw":
        assert row["reported_activity"] == "construction"
    assert row["quote"] == text


@pytest.mark.parametrize(
    "text",
    [
        "Orion Data Center campus capacity is 196 MW.",
        "Orion Data Center facility demand is expected to be 12 MW.",
        "Orion Data Center construction fuel may be available.",
        "Orion Data Center construction voltage is 480 V, 3 phase.",
        "Orion Data Center construction load profile is usually continuous.",
        "Orion Data Center construction temporary power procurement is not started.",
        "Other Data Center construction utility interconnection is blocked.",
    ],
)
def test_new_electrical_fields_reject_inference_ambiguity_and_wrong_scope(text):
    assert claims(text) == []


def test_new_field_conflicts_and_age_rules_keep_values_unknown():
    rows = [
        {"field": "facility_demand_mw", "value": "12", "as_of": TODAY.isoformat()},
        {"field": "facility_demand_mw", "value": "14", "as_of": TODAY.isoformat()},
        {"field": "fuel_availability", "value": "available", "as_of": TODAY.isoformat()},
        {"field": "fuel_availability", "value": "unavailable", "as_of": TODAY.isoformat()},
        {"field": "load_profile", "value": "continuous", "as_of": "2026-01-01"},
    ]
    state = project_claim_state(rows, today=TODAY)
    assert state["facility_demand_mw"]["status"] == "CONFLICT"
    assert state["fuel_availability"]["status"] == "CONFLICT"
    assert state["load_profile"]["status"] == "UNKNOWN"
    assert qualification_veto(state) is None


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


def test_compact_claim_accumulator_matches_full_age_conflict_and_order_rules():
    rows = [
        {"field": "permanent_service", "value": "pending", "as_of": TODAY.isoformat()},
        {
            "field": "phase",
            "value": "completed",
            "as_of": (TODAY - timedelta(days=120)).isoformat(),
        },
        {
            "field": "permanent_service",
            "value": "pending",
            "as_of": (TODAY - timedelta(days=90)).isoformat(),
        },
        {"field": "permanent_service", "value": "energized", "as_of": "2026-01-01"},
        {"field": "phase", "value": "production_started", "as_of": TODAY.isoformat()},
        {"field": "phase", "value": "cancelled", "as_of": "2026-10-05"},
        {"field": "supply_adequacy", "value": "adequate", "as_of": "2025-01-01"},
        {"field": "unknown_field", "value": "ignored", "as_of": TODAY.isoformat()},
    ]
    full = project_claim_state(rows, today=TODAY)
    compact = _project_claim_accumulator(today=TODAY)
    for row in rows:
        compact.add(row)
    compact_state = compact.finish()
    assert {field: (state["status"], state["value"]) for field, state in full.items()} == {
        field: (state["status"], state["value"]) for field, state in compact_state.items()
    }
    assert full["permanent_service"]["claims"] == [rows[0], rows[2]]
    assert full["phase"]["claims"] == [rows[1], rows[4]]
    assert qualification_veto(full) == qualification_veto(compact_state)
    assert len(compact._claims) == len(FIELDS)
    assert sum(map(len, compact._claims.values())) == 0


def test_compact_claim_accumulator_residency_does_not_grow_with_claim_count():
    accumulator = _project_claim_accumulator(today=TODAY)
    claim = {"field": "phase", "value": "construction_active", "as_of": TODAY.isoformat()}
    for _ in range(10_000):
        accumulator.add(claim)
    state = accumulator.finish()
    assert state["phase"]["status"] == "SUPPORTED"
    assert state["phase"]["value"] == "construction_active"
    assert sum(map(len, accumulator._claims.values())) == 0
    assert len(accumulator._values) == len(FIELDS)


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


def test_facility_scale_and_voltage_conflicts_do_not_change_qualification():
    rows = [
        {"field": "facility_scale_mw", "value": "196", "as_of": TODAY.isoformat()},
        {"field": "facility_scale_mw", "value": "200", "as_of": TODAY.isoformat()},
        {"field": "voltage", "value": "208 V, 1 phase", "as_of": TODAY.isoformat()},
        {"field": "voltage", "value": "480 V, 3 phase", "as_of": TODAY.isoformat()},
    ]
    state = project_claim_state(rows, today=TODAY)
    assert state["facility_scale_mw"]["status"] == "CONFLICT"
    assert state["voltage"]["status"] == "CONFLICT"
    assert qualification_veto(state) is None


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


def test_fort_worth_facility_total_is_typed_separately_from_activity_demand():
    from gridlens.domain.project_research import extract_retained_permit_claims

    text = (
        "Project: Edged Energy Outpost Building 2\n"
        "Work description: 488,628 SF 196MW data center\n"
        "Owner of record: not stated"
    )
    rows = extract_retained_permit_claims(
        "fort-worth-development-permits",
        text,
        activity_key="facility-expansion",
        as_of=TODAY,
        today=TODAY,
    )
    assert [(row["field"], row["value"], row["quote"]) for row in rows] == [
        ("facility_scale_mw", "196", "Work description: 488,628 SF 196MW data center")
    ]
    assert not any(row["field"] in {"activity_load_mw", "facility_demand_mw"} for row in rows)


def test_boston_temporary_electrical_constraints_keep_voltage_without_computing_mw():
    from gridlens.domain.project_research import extract_retained_permit_claims

    text = (
        "Description: Electrical\n"
        "Comments: Provide temporary electrical work required to support Boss steel "
        "Office trailer 100A 208v 1Ph $5000"
    )
    rows = extract_retained_permit_claims(
        "boston-building-permits",
        text,
        activity_key="temporary-power",
        as_of=TODAY,
        today=TODAY,
    )
    assert [(row["field"], row["value"]) for row in rows] == [("voltage", "208 V, 1 phase")]
    assert "100A 208v 1Ph" in rows[0]["quote"]
    assert (
        extract_retained_permit_claims(
            "boston-building-permits",
            text,
            activity_key="facility-expansion",
            as_of=TODAY,
            today=TODAY,
        )
        == []
    )


def test_retained_permit_claims_require_a_valid_source_date_and_current_value():
    from gridlens.domain.project_research import extract_retained_permit_claims

    assert (
        extract_retained_permit_claims(
            "fort-worth-development-permits",
            "Work description: 196 MW data center",
            activity_key="facility-expansion",
            as_of=None,
            today=TODAY,
        )
        == []
    )
    stale = extract_retained_permit_claims(
        "fort-worth-development-permits",
        "Work description: 196 MW data center",
        activity_key="facility-expansion",
        as_of=date(2026, 1, 1),
        today=TODAY,
    )
    assert project_claim_state(stale, today=TODAY)["facility_scale_mw"]["status"] == "UNKNOWN"


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
