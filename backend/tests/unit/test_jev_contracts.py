import pytest

from gridlens.intelligence.jev_contracts import CONTRACTS, validate_answer


def test_catalog_is_exact_and_advisory():
    assert set(CONTRACTS) == {
        "SOURCE_RELEVANCE_V1",
        "EVENT_CLASS_V1",
        "MATCH_ADVISORY_V1",
        "MATERIALITY_V1",
        "POWER_ACTIVITY_HINT_V1",
        "RESEARCH_PRIORITY_V1",
        "BUYER_ROLE_HINT_V1",
        "LLM_ROUTE_V1",
    }
    assert "IRRELEVANT" in CONTRACTS["SOURCE_RELEVANCE_V1"].choices
    assert {"FORMATION", "ENERGIZATION", "PROCUREMENT"}.issubset(
        CONTRACTS["EVENT_CLASS_V1"].choices
    )
    assert validate_answer("RESEARCH_PRIORITY_V1", {"choice": "4"}).choice == "4"
    with pytest.raises(ValueError, match="one of"):
        validate_answer("MATCH_ADVISORY_V1", {"choice": "GUESS"})
    with pytest.raises(ValueError, match="Extra inputs"):
        validate_answer("MATCH_ADVISORY_V1", {"choice": "SAME", "authority": "WRITE"})


def test_probability_distribution_is_bounded():
    with pytest.raises(ValueError, match="sum to one"):
        validate_answer(
            "SOURCE_RELEVANCE_V1", {"choice": "RELEVANT", "probabilities": {"yes": 0.5}}
        )
