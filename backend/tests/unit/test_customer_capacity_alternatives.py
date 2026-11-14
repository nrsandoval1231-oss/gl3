import pytest

from gridlens.domain.customer_intelligence import extract_customer_facts


@pytest.mark.parametrize("unit", ["megawatts", "gigawatts", "kilowatts", "MW"])
@pytest.mark.parametrize("join", ["or", "to", "through", "–", "and"])
def test_capacity_alternatives_in_every_supported_unit_abstain(unit, join):
    text = f"Alpha campus has IT capacity of 100 {unit} {join} 200 {unit}."
    result = extract_customer_facts(text, project_id="alpha", source={})
    assert result["capacity_claims"] == []


def test_parenthesized_unit_alternatives_abstain():
    result = extract_customer_facts(
        "Alpha campus has IT capacity of 100 megawatts (MW) or 200 megawatts (MW).",
        project_id="alpha",
        source={},
    )
    assert result["capacity_claims"] == []
