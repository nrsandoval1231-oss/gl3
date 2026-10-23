from datetime import date

from gridlens.domain.air_permit_hours import classify_operating_hours, load_hours_rule
from gridlens.domain.permit_interpretation import assess_permit

TODAY = date(2026, 10, 23)


def test_hours_rule_thresholds_stay_in_config():
    rule = load_hours_rule()
    assert rule["rule_id"] == "air-permit-operating-hours-v1"
    assert rule["backup_max_hours_per_year"] == 500
    assert (rule["bridge_min_hours_per_year"], rule["bridge_max_hours_per_year"]) == (2000, 6000)
    assert rule["btm_hours_per_year"] == 8760
    assert rule["btm_phrase"] == "onsite use only"


def _record(description: str) -> dict:
    classified = classify_operating_hours(description)
    return {
        "event_date": "2026-10-01",
        "event_date_label": "fixture",
        "html_url": "https://www2.tceq.texas.gov/airperm/index.cfm",
        "permit": {
            "source_type": "texas-tceq-egu-registrations",
            "row_id": "TCEQ-EGU-HOURS",
            "applicant": "Fixture Power LLC",
            "facility": "Fixture Generating Unit",
            "description": description,
            "location": "Taylor, Williamson County, TX",
            "power_signals": [],
            "data_center": False,
            "operating_hours": classified,
            "source_fields": {},
            "document_links": {},
        },
    }


def test_hour_phrasings_and_onsite_clause():
    phrasings = (
        "500 hours of operation per year",
        "500 hours of operation annually",
        "500 hours annually",
        "500 hrs annually",
        "500 hr/yr",
        "500 h/yr",
        "1,000 hours of operation / year",
    )
    for phrasing in phrasings:
        result = classify_operating_hours(f"The engines are limited to {phrasing}.")
        assert result["hours_per_year"], phrasing
        assert result["evidence"][0]["quote"] == phrasing
    assert (
        classify_operating_hours("limited to 500 hours of operation per year.")["classification"]
        == "backup"
    )
    assert (
        classify_operating_hours("limited to 500 hours of operation annually.")["classification"]
        == "backup"
    )
    assert classify_operating_hours("limited to 500 hours annually.")["classification"] == "backup"
    assert classify_operating_hours("limited to 500 hrs annually.")["classification"] == "backup"
    assert classify_operating_hours("limited to 500 hr/yr.")["classification"] == "backup"
    assert classify_operating_hours("limited to 500 h/yr.")["classification"] == "backup"
    assert classify_operating_hours("limited to 501 hours annually.")["classification"] is None
    assert classify_operating_hours("limited to 1,999 h/yr.")["classification"] is None
    assert (
        classify_operating_hours("authorized for 2,000 hr/yr.")["classification"]
        == "bridge_temporary"
    )
    assert (
        classify_operating_hours("authorized for 6,000 hours of operation per year.")[
            "classification"
        ]
        == "bridge_temporary"
    )
    assert (
        classify_operating_hours("authorized for 6,001 hours of operation annually.")[
            "classification"
        ]
        is None
    )
    assert (
        classify_operating_hours("The turbines may operate 8,760 hours annually.")["classification"]
        is None
    )
    same_sentence = classify_operating_hours(
        "The turbines may operate 8,760 hours per year for onsite use only."
    )
    assert same_sentence["classification"] == "btm"
    assert same_sentence["evidence"][1] == {"clause": "onsite_use_only", "quote": "onsite use only"}
    hyphen = classify_operating_hours(
        "Unit 2 is limited to 8,760 h/yr and is for on-site use only."
    )
    assert hyphen["classification"] == "btm"
    assert hyphen["hours_per_year"] == [8760]
    wrapped = classify_operating_hours(
        "The turbines may operate 8,760 hours of operation per year\nfor onsite use only."
    )
    assert wrapped["classification"] == "btm"
    other_paragraph = classify_operating_hours(
        "The generators may operate 8,760 hours per year.\n\n"
        "The warehouse lighting is for onsite use only."
    )
    assert other_paragraph["classification"] is None
    assert other_paragraph["hours_per_year"] == [8760]
    assert other_paragraph["evidence"] == [
        {"clause": "unclassified_hours", "quote": "8,760 hours per year"}
    ]
    other_sentence = classify_operating_hours(
        "The generators may operate 8,760 hours annually. "
        "A separate note says the yard is for onsite use only."
    )
    assert other_sentence["classification"] is None
    assert other_sentence["hours_per_year"] == [8760]
    same_clause = classify_operating_hours("8,760 h/yr; onsite use only")
    assert same_clause["classification"] == "btm"
    assert same_clause["hours_per_year"] == [8760]
    united_states = classify_operating_hours(
        "The turbines may operate 8,760 hours per year at the U.S. site for on-site use only."
    )
    assert united_states["classification"] == "btm"
    decimal = classify_operating_hours("The engines are limited to 1.5 hours per year.")
    assert decimal["classification"] == "backup"
    assert decimal["hours_per_year"] == [1.5]
    assert 5 not in decimal["hours_per_year"]
    half_over = classify_operating_hours("limited to 500.5 hours per year")
    assert half_over["classification"] is None
    assert half_over["hours_per_year"] == [500.5]
    assert (
        classify_operating_hours("authorized for 2,000.0 hr/yr.")["classification"]
        == "bridge_temporary"
    )
    assert classify_operating_hours("authorized for 2,000.0 hr/yr.")["hours_per_year"] == [2000]
    exact_btm = classify_operating_hours(
        "The turbines may operate 8,760.0 hours per year for onsite use only."
    )
    assert exact_btm["classification"] == "btm"
    assert exact_btm["hours_per_year"] == [8760]
    assert classify_operating_hours("200 cubic yards per hour of concrete.")["evidence"] == []
    assert classify_operating_hours("hours of operation per year")["evidence"] == []


def test_operating_hour_boundaries_and_conflicts():
    backup = classify_operating_hours("The engines are limited to 500 hours per year.")
    assert backup["classification"] == "backup"
    assert backup["hours_per_year"] == [500]
    assert backup["evidence"][0]["quote"] == "500 hours per year"
    assert backup["rule_id"] == "air-permit-operating-hours-v1"
    assert classify_operating_hours("limited to 100 hrs/year")["classification"] == "backup"
    assert classify_operating_hours("limited to 501 hours per year")["classification"] is None
    assert classify_operating_hours("limited to 1,999 hours/year")["classification"] is None
    bridge = classify_operating_hours("authorized for 2,000 hours per year")
    assert bridge["classification"] == "bridge_temporary"
    assert classify_operating_hours("authorized for 6,000 hrs/yr")["classification"] == (
        "bridge_temporary"
    )
    assert classify_operating_hours("authorized for 6,001 hours per year")["classification"] is None
    assert (
        classify_operating_hours("The turbines may operate 8,760 hours per year.")["classification"]
        is None
    )
    btm = classify_operating_hours(
        "The turbines may operate 8,760 hours per year for onsite use only."
    )
    assert btm["classification"] == "btm"
    assert classify_operating_hours("on-site use only, 8760 hours/year")["classification"] == "btm"
    portable = classify_operating_hours("portable units on trailers")
    assert portable["classification"] is None
    assert portable["hours_per_year"] == []
    assert portable["evidence"] == []
    assert (
        classify_operating_hours("a portable generator on a trailer")["classification"]
        == "bridge_temporary"
    )
    assert (
        classify_operating_hours("trailer-mounted engine for the yard")["classification"]
        == "bridge_temporary"
    )
    assert (
        classify_operating_hours(
            "A portable crusher works the pit. The generator is in another sentence."
        )["classification"]
        is None
    )
    assert (
        classify_operating_hours("trailer-mounted turbines, 6001 hours per year")["classification"]
        == "bridge_temporary"
    )
    assert classify_operating_hours("This is a temporary permit.")["classification"] == (
        "bridge_temporary"
    )
    assert (
        classify_operating_hours("The expiring permit covers the laydown yard.")["classification"]
        == "bridge_temporary"
    )
    conflict = classify_operating_hours("500 hours per year and portable turbines")
    assert conflict["classification"] is None
    assert conflict["conflict"] is True
    assert classify_operating_hours("gas engines at the substation")["evidence"] == []


def test_assessment_records_the_hours_rule_and_does_not_treat_backup_as_a_signal():
    backup = assess_permit(_record("Emergency engines limited to 500 hours per year."), as_of=TODAY)
    assert backup["decision"] == "rejected"
    assert backup["operating_hours"]["classification"] == "backup"
    assert "air-permit-operating-hours-v1" in backup["reason"]
    bridge = assess_permit(_record("portable turbines for the construction yard"), as_of=TODAY)
    assert bridge["decision"] == "accepted"
    assert bridge["power_activity"] == "temporary-power"
    assert bridge["operating_hours"]["classification"] == "bridge_temporary"
    data_center = _record("500 hours per year")
    data_center["permit"]["description"] = "Example Data Center emergency engines, 500 hours/year"
    data_center["permit"]["data_center"] = True
    data_center["permit"]["operating_hours"] = classify_operating_hours(
        data_center["permit"]["description"]
    )
    accepted = assess_permit(data_center, as_of=TODAY)
    assert accepted["decision"] == "accepted"
    assert accepted["power_activity"] == "facility-expansion"
    assert accepted["operating_hours"]["classification"] == "backup"
