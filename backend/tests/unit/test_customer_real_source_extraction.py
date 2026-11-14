"""Real-source controls for typed electrical capacity extraction."""

from gridlens.domain.customer_intelligence import extract_customer_facts

SOURCE = {
    "url": "https://www.databank.com/resources/press-releases/databank-announces-development-of-480mw-data-center-campus-in-south-dallas/",
    "evidence_id": "databank-red-oak",
    "content_hash": "a" * 64,
    "published_at": "2024-09-10",
    "observed_at": "2026-11-12T00:00:00Z",
    "authority": "primary",
    "verification_status": "verified",
}


def extracted(text: str) -> dict:
    return extract_customer_facts(text, project_id="red-oak", source=SOURCE)


def test_real_substation_rating_is_not_utility_service_capacity():
    quote = (
        "The Phase 1 design of the site will feature 4 buildings and a 400MW sub-station "
        "from Oncor that can deliver up to 240MW of critical IT power with the ability "
        "to increase this in Phase 2 for a total of 480MW across all 8 buildings."
    )

    facts = extracted(quote)

    assert all(claim["quote"] == quote for claim in facts["capacity_claims"])
    assert not any(
        claim["basis"] == "utility_service" and claim["value_mw"] == "400"
        for claim in facts["capacity_claims"]
    )
    assert any(
        claim["basis"] == "it_load"
        and claim["value_mw"] == "240"
        and claim["qualifier"] == "up_to"
        and claim["scope_id"] == "red-oak:phase:1"
        for claim in facts["capacity_claims"]
    )
    assert any(
        claim["basis"] == "it_load"
        and claim["value_mw"] == "480"
        and claim["qualifier"] == "up_to"
        and claim["scope_id"] == "red-oak:site"
        and claim["includes_scope_ids"] == ["red-oak:phase:1", "red-oak:phase:2"]
        for claim in facts["capacity_claims"]
    )


def test_real_utility_supply_statement_remains_typed_as_service_capacity():
    quote = "Mississippi Power will supply approximately 500 megawatts of power to the facility."

    facts = extracted(quote)

    assert [
        (claim["basis"], claim["value_mw"], claim["qualifier"], claim["quote"])
        for claim in facts["capacity_claims"]
    ] == [("utility_service", "500", "approximate", quote)]


def test_real_spelled_out_capacity_keeps_its_lower_bound():
    quote = (
        "The data center will deliver over two gigawatts of compute capacity to train "
        "future open-source large language models — helping Meta unlock historic "
        "innovation and expand American technology leadership."
    )

    facts = extracted(quote)

    assert [
        (claim["basis"], claim["value_mw"], claim["qualifier"], claim["quote"])
        for claim in facts["capacity_claims"]
    ] == [("campus_development", "2000", "more_than", quote)]
