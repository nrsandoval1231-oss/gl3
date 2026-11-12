import pytest

from gridlens.domain.customer_intelligence import extract_customer_facts
from gridlens.intelligence.customer_intelligence import scope_customer_facts


@pytest.mark.parametrize("location", ["Dallas, TX", "Midland, TX", "Loudoun County, Virginia"])
def test_city_and_county_totals_cannot_become_a_named_project_capacity(location):
    facts = extract_customer_facts(
        f"{location} has 10 GW of IT capacity.", project_id="orion", source={}
    )
    assert facts["capacity_claims"]
    scoped = scope_customer_facts(facts, "Orion Data Center", location)
    assert scoped["capacity_claims"] == []


def test_exact_named_project_remains_supported_without_location_as_subject():
    facts = extract_customer_facts(
        "Orion Data Center has 100 MW of IT capacity.", project_id="orion", source={}
    )
    scoped = scope_customer_facts(facts, "Orion Data Center", "Dallas, TX")
    assert scoped["capacity_claims"][0]["value_mw"] == "100"


@pytest.mark.parametrize("roman,decimal", [("I", "1"), ("II", "2"), ("IV", "4"), ("IX", "9")])
def test_phase_notation_uses_one_scope(roman, decimal):
    def claim(phase):
        return extract_customer_facts(
            f"Alpha campus Phase {phase} has 100 MW of IT capacity.",
            project_id="alpha",
            source={},
        )["capacity_claims"][0]

    assert claim(roman)["scope_id"] == claim(decimal)["scope_id"]
