from gridlens.ingestion.parsers.generator_schedule import extract_generator_facts


def test_ratings_units_and_equipment_context_keep_exact_citations():
    text = (
        "Two diesel emergency generators are rated 2500 kW each. "
        "The generators may operate 100 hours annually for testing. "
        "Campus operating load is 200 MW."
    )
    result = extract_generator_facts([(17, text)], "https://epd.georgia.gov/example")
    assert result["facts"][0]["power_quantities"][0]["mw"] == "2.5"
    assert result["facts"][0]["quote"] in text
    assert result["facts"][0]["page"] == 17
    assert result["facts"][0]["url"] == "https://epd.georgia.gov/example"
    assert "100 hours" in result["facts"][1]["quote"]
    assert len(result["facts"]) == 2
    assert "rental demand" in result["facts"][0]["label"]


def test_schedule_bound_exposes_omissions_and_no_inferred_total():
    pages = [(n, f"Generator {n} is rated 1.25 MW for emergency use.") for n in range(1, 31)]
    result = extract_generator_facts(pages, "https://epd.georgia.gov/example")
    assert len(result["facts"]) == 24
    assert result["omitted"] == 6
    assert result["facts"][0]["power_quantities"][0]["mw"] == "1.25"
    assert "total_mw" not in result


def test_regulatory_threshold_is_not_an_equipment_rating():
    result = extract_generator_facts(
        [
            (
                3,
                "Emission standards for diesel generator engines "
                "with maximum engine power larger than 560 kW.",
            )
        ],
        "https://epd.georgia.gov/example",
    )
    assert result["facts"][0]["power_quantities"][0]["basis"] == "regulatory context"


def test_emission_unit_equipment_table_is_not_a_regulatory_threshold():
    quote = (
        "Updated Equipment List Emission Units Associated Control Devices "
        "EG001–EG229 227 Main Generators & 2 House Generators 2.5 MW CAT 3516C Diesel-fired"
    )
    result = extract_generator_facts([(2, quote)], "https://epd.georgia.gov/example")
    value = result["facts"][0]["power_quantities"][0]
    assert value["basis"] == "unassigned power quantity"
    assert value["mw"] == "2.5"


def test_campus_and_service_quantities_are_not_assigned_to_generator_nameplate():
    for text in [
        "The 200 MW data center campus will be served by diesel emergency generators.",
        "The generators provide standby power while available utility service is 65 MW.",
    ]:
        result = extract_generator_facts([(1, text)], "https://epd.georgia.gov/example")
        value = result["facts"][0]["power_quantities"][0]
        assert value["basis"] == "unassigned power quantity"
        assert "not established equipment" in value["scope"]
    regulatory = extract_generator_facts(
        [(1, "Diesel engines below 560 kW must comply with federal emissions limits.")],
        "https://epd.georgia.gov/example",
    )
    assert regulatory["facts"][0]["power_quantities"][0]["basis"] == "regulatory context"
