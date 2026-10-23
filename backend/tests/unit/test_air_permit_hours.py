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
    excluded = re.compile(rule["power_generation_exclusion_pattern"], re.IGNORECASE)
    for sample in (
        "diesel generator",
        "emergency generator",
        "standby generator",
        "electric generator",
        "power generator",
        "natural gas generator",
        "natural-gas-fired generator",
        "diesel engine generator",
        "genset",
        "gen-set",
        "generator set",
        "turbine",
        "electric generation",
        "power generation",
    ):
        assert power.search(sample), sample
        assert excluded.search(sample) is None, sample
    for sample in (
        "generator",
        "generators",
        "portable generator",
        "engine",
        "engines",
        "engine-driven crusher",
        "engine-driven pump",
        "engine-driven generator",
        "hazardous waste generator",
        "steam generator",
        "waste generator",
        "small quantity generator",
        "gas generator",
        "process gas generator",
        "gas-fired generator",
        "ozone generator",
    ):
        assert power.search(sample) is None, sample
    for sample in (
        "hazardous waste generator",
        "steam generator",
        "waste generator",
        "small quantity generator",
        "gas generator",
        "ozone generator",
        "nitrogen generator",
        "oxygen generator",
        "hydrogen generator",
    ):
        assert excluded.search(sample), sample


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
    bare_generator = classify_operating_hours("a portable generator on a trailer")
    assert bare_generator["classification"] is None
    assert bare_generator["evidence"] == []
    assert (
        classify_operating_hours("a portable diesel generator on a trailer")["classification"]
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
        "a portable generator on a trailer",
        "temporary permit for the generator",
        "a portable engine-driven generator",
        "temporary permit for the engine-driven generator",
        "The crusher holds a temporary permit. A later temporary permit covers the generator.",
        "temporary permit for the hazardous waste generator",
        "portable steam generator",
        "trailer-mounted waste generator",
        "temporary permit for a small quantity generator",
        "temporary permit for the gas generator that supplies process gas",
        "temporary permit for the gas-fired generator",
        "portable ozone generator",
        "trailer-mounted nitrogen generator",
    )
    for text in negatives:
        result = classify_operating_hours(text)
        assert result["classification"] is None, text
        assert result["evidence"] == [], text
        assert result["conflict"] is False

    positives = (
        "a portable diesel generator on a trailer",
        "trailer-mounted turbine for the yard",
        "portable genset beside the pad",
        "trailer-mounted gen-set",
        "portable electric generation for the site",
        "trailer-mounted power generation",
        "a portable engine-driven diesel generator",
        "temporary permit for the emergency generator",
        "expiring permit for a genset",
        "temporary permit for electric generation",
        "The expiring permit authorizes power generation at the site.",
        "temporary permit for the turbine",
        "temporary permit for the standby generator",
        (
            "The crusher holds a temporary permit. "
            "A later temporary permit covers the diesel generator."
        ),
        "portable natural gas generator",
        "trailer-mounted natural-gas-fired generator",
        "temporary permit for the generator set",
        "portable electric generator",
        "portable power generator",
        "trailer-mounted emergency diesel engine generator",
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


def test_non_electric_generator_phrases_are_not_power_context():
    """Bare and non-electric generator uses do not tag. Qualified ones still do."""
    negatives = (
        "temporary permit for the hazardous waste generator",
        "portable steam generator",
        "trailer-mounted waste generator",
        "temporary permit for a small quantity generator",
        "temporary permit for the gas generator that supplies process gas",
        "portable ozone generator",
        "trailer-mounted nitrogen generator",
        "temporary permit for the oxygen generator",
        "portable hydrogen generator",
        "a portable generator on a trailer",
        "temporary permit for the generator",
        "emergency hazardous waste generator on a trailer",
        "portable emergency steam generator",
    )
    for text in negatives:
        result = classify_operating_hours(text)
        assert result["classification"] is None, text
        assert result["evidence"] == [], text
        assert result["conflict"] is False, text

    positives = (
        "temporary permit for the diesel generator",
        "portable emergency generator",
        "trailer-mounted natural gas generator",
        "portable natural-gas-fired generator",
        "portable standby generator",
        "temporary permit for the electric generator",
        "portable power generator",
        "trailer-mounted emergency diesel generator",
        "diesel engine generator under a temporary permit",
        "temporary permit for the generator set",
        "portable genset",
        "The site is a small quantity generator. A temporary permit covers the diesel generator.",
        "temporary permit for the hazardous waste generator and the emergency generator",
    )
    for text in positives:
        result = classify_operating_hours(text)
        assert result["classification"] == "bridge_temporary", text
        assert result["conflict"] is False, text
        assert result["evidence"], text


def test_power_negation_stays_inside_the_clause():
    """A negated power phrase blocks bridge, backup, and behind-the-meter in that sentence."""
    suppressed = (
        "This is a temporary permit with no power generation.",
        "The portable unit is not used for power generation.",
        "trailer-mounted equipment that does not generate electricity",
        "This is a temporary permit without generators.",
        "temporary permit without a diesel generator",
        "portable emergency generator but no power generation",
        "The boiler is limited to 2,000 hours per year and is not used for power generation.",
        "limited to 500 hours per year and does not generate electricity.",
        "The turbines may operate 8,760 hours per year for onsite use only without generators.",
        "No. 5 is a label. This temporary permit has no power generation.",
    )
    for text in suppressed:
        result = classify_operating_hours(text)
        assert result["classification"] is None, text
        assert result["conflict"] is False, text
        assert any(item["clause"] == "negated_power" for item in result["evidence"]), text

    no_power = classify_operating_hours("This is a temporary permit with no power generation.")
    assert no_power["evidence"] == [{"clause": "negated_power", "quote": "no power generation"}]
    not_used = classify_operating_hours(
        "The boiler is limited to 2,000 hours per year and is not used for power generation."
    )
    assert not_used["hours_per_year"] == [2000]
    assert not_used["evidence"][0] == {
        "clause": "unclassified_hours",
        "quote": "2,000 hours per year",
    }
    assert {"clause": "negated_power", "quote": "not used for power generation"} in not_used[
        "evidence"
    ]
    does_not = classify_operating_hours(
        "limited to 500 hours per year and does not generate electricity."
    )
    assert does_not["classification"] is None
    assert {"clause": "negated_power", "quote": "does not generate electricity"} in does_not[
        "evidence"
    ]
    without = classify_operating_hours("This is a temporary permit without generators.")
    assert without["evidence"] == [{"clause": "negated_power", "quote": "without generators"}]

    # The next sentence is a new clause. Negating something else does not suppress hours.
    backup = classify_operating_hours(
        "The engines are limited to 500 hours per year. The boiler does not generate electricity."
    )
    assert backup["classification"] == "backup"
    bridge = classify_operating_hours(
        "authorized for 2,000 hours per year. There is no power generation at the quarry."
    )
    assert bridge["classification"] == "bridge_temporary"
    btm = classify_operating_hours(
        "The turbines may operate 8,760 hours per year for onsite use only. "
        "No power generation is proposed."
    )
    assert btm["classification"] == "btm"
    later = classify_operating_hours(
        "There is no power generation at the shop. A temporary permit covers the standby generator."
    )
    assert later["classification"] == "bridge_temporary"
    other = classify_operating_hours(
        "The engines are not older than 2015 and are limited to 500 hours per year."
    )
    assert other["classification"] == "backup"
    labeled = classify_operating_hours("temporary permit for diesel generator No. 5")
    assert labeled["classification"] == "bridge_temporary"
    same_sentence = classify_operating_hours(
        "temporary permit for the emergency generator and the diesel tank"
    )
    assert same_sentence["classification"] == "bridge_temporary"


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
