import re
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
    power = re.compile(rule["power_generation_pattern"], re.IGNORECASE)
    for sample in (
        "generator",
        "genset",
        "gen-set",
        "turbine",
        "electric generation",
        "power generation",
    ):
        assert power.search(sample), sample
    for sample in ("engine", "engines", "engine-driven crusher", "engine-driven pump"):
        assert power.search(sample) is None, sample


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
    trailer_engine = classify_operating_hours("trailer-mounted engine for the yard")
    assert trailer_engine["classification"] is None
    assert trailer_engine["evidence"] == []
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
    temporary = classify_operating_hours("This is a temporary permit.")
    assert temporary["classification"] is None
    assert temporary["evidence"] == []
    expiring = classify_operating_hours("The expiring permit covers the laydown yard.")
    assert expiring["classification"] is None
    assert expiring["evidence"] == []
    conflict = classify_operating_hours("500 hours per year and portable turbines")
    assert conflict["classification"] is None
    assert conflict["conflict"] is True
    assert classify_operating_hours("gas engines at the substation")["evidence"] == []


def test_engine_and_temporary_wording_need_power_generation_in_the_same_clause():
    negatives = (
        "a portable engine-driven crusher",
        "trailer-mounted engine-driven pump",
        "portable engine for the crusher",
        "engine-driven crusher at the pit",
        "engine-driven pump on a skid",
        "This is a temporary permit.",
        "temporary permit for the concrete batch plant",
        "temporary permit for the rock crusher and its engine-driven pump",
        "The expiring permit covers the laydown yard.",
        "This is a temporary permit. The generator is described in the next sentence.",
        "A portable crusher works the pit. The generator is in another sentence.",
        "A portable engine-driven pump serves the pad. Power generation is a separate sentence.",
    )
    for text in negatives:
        result = classify_operating_hours(text)
        assert result["classification"] is None, text
        assert result["evidence"] == [], text
        assert result["conflict"] is False

    positives = (
        "a portable generator on a trailer",
        "trailer-mounted turbine for the yard",
        "portable genset beside the pad",
        "trailer-mounted gen-set",
        "portable electric generation for the site",
        "trailer-mounted power generation",
        "a portable engine-driven generator",
        "temporary permit for the generator",
        "expiring permit for a genset",
        "temporary permit for electric generation",
        "The expiring permit authorizes power generation at the site.",
        "temporary permit for the turbine",
        "temporary permit for the engine-driven generator",
        "The crusher holds a temporary permit. A later temporary permit covers the generator.",
    )
    for text in positives:
        result = classify_operating_hours(text)
        assert result["classification"] == "bridge_temporary", text
        assert result["conflict"] is False, text
        assert result["evidence"], text

    hours_only = classify_operating_hours(
        "temporary permit for the engine-driven crusher, limited to 2,000 hours per year"
    )
    assert hours_only["classification"] == "bridge_temporary"
    assert hours_only["evidence"] == [
        {"clause": "bridge_temporary", "quote": "2,000 hours per year"}
    ]
    assert "expiring_or_temporary_permit" not in {item["clause"] for item in hours_only["evidence"]}


def test_hour_ranges_keep_both_endpoints():
    hyphen = classify_operating_hours("limited to 12-500 hours per year")
    assert hyphen["hours_per_year"] == [12, 500]
    assert hyphen["hours_per_year"] != [500]
    assert hyphen["classification"] == "backup"
    assert hyphen["evidence"] == [{"clause": "backup", "quote": "12-500 hours per year"}]
    en_dash = classify_operating_hours("limited to 12\u2013500 hours per year")
    assert en_dash["hours_per_year"] == [12, 500]
    assert en_dash["evidence"][0]["quote"] == "12\u2013500 hours per year"
    assert en_dash["classification"] == "backup"
    spaced = classify_operating_hours("limited to 12 - 500 hours of operation per year")
    assert spaced["hours_per_year"] == [12, 500]
    assert spaced["classification"] == "backup"
    word = classify_operating_hours("limited to 12 to 500 hours per year")
    assert word["hours_per_year"] == [12, 500]
    assert word["classification"] == "backup"
    assert word["evidence"][0]["quote"] == "12 to 500 hours per year"
    em_dash = classify_operating_hours("limited to 12\u2014500 hrs/yr")
    assert em_dash["hours_per_year"] == [12, 500]
    assert em_dash["classification"] == "backup"
    decimal = classify_operating_hours("The engines are limited to 1.5-2.5 hours per year.")
    assert decimal["hours_per_year"] == [1.5, 2.5]
    assert decimal["classification"] == "backup"
    assert 5 not in decimal["hours_per_year"]
    assert 2.5 in decimal["hours_per_year"]
    one_decimal = classify_operating_hours("limited to 12-500.5 hours per year")
    assert one_decimal["hours_per_year"] == [12, 500.5]
    assert one_decimal["classification"] is None
    assert one_decimal["evidence"][0]["clause"] == "unclassified_hours"
    crossed = classify_operating_hours("limited to 12-2,000 hours per year")
    assert crossed["hours_per_year"] == [12, 2000]
    assert crossed["hours_per_year"] != [2000]
    assert crossed["classification"] is None
    assert crossed["conflict"] is False
    bridge = classify_operating_hours("authorized for 2,000-6,000 hours per year")
    assert bridge["hours_per_year"] == [2000, 6000]
    assert bridge["classification"] == "bridge_temporary"
    assert bridge["evidence"][0]["quote"] == "2,000-6,000 hours per year"
    exact = classify_operating_hours("authorized for 2,000.0 to 6,000.0 hours annually")
    assert exact["hours_per_year"] == [2000, 6000]
    assert exact["classification"] == "bridge_temporary"
    over = classify_operating_hours("authorized for 2,000 to 6,001 hours annually")
    assert over["hours_per_year"] == [2000, 6001]
    assert over["classification"] is None
    cap = classify_operating_hours("operate up to 500 hours per year")
    assert cap["hours_per_year"] == [500]
    assert cap["classification"] == "backup"
    single = classify_operating_hours("The engines are limited to 1.5 hours per year.")
    assert single["hours_per_year"] == [1.5]
    assert single["classification"] == "backup"
    bare = classify_operating_hours("limited to 12-500 hours")
    assert bare["hours_per_year"] == []
    assert bare["evidence"] == []
    wrapped = classify_operating_hours("authorized for 4,380\n \nhours\n \nper\n \nyear")
    assert wrapped["hours_per_year"] == [4380]
    assert wrapped["classification"] == "bridge_temporary"
    same_band_btm = classify_operating_hours(
        "The turbines may operate 8,760-8,760 hours per year for onsite use only."
    )
    assert same_band_btm["hours_per_year"] == [8760, 8760]
    assert same_band_btm["classification"] == "btm"
    crossed_btm = classify_operating_hours(
        "The turbines may operate 8,000-8,760 hours per year for onsite use only."
    )
    assert crossed_btm["hours_per_year"] == [8000, 8760]
    assert crossed_btm["classification"] is None
    conflict = classify_operating_hours("2,000-6,000 hours per year and also 500 hours per year")
    assert conflict["hours_per_year"] == [2000, 6000, 500]
    assert conflict["classification"] is None
    assert conflict["conflict"] is True


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
