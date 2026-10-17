import pytest

from gridlens.domain.grounding import numbers, ungrounded
from gridlens.intelligence.market_newsletter import (
    render_newsletter,
    validate_claims,
    validate_headline,
)

TEXT = (
    "ERCOT forecasts peak demand of 87,500 MW next summer\n"
    "The Texas grid operator said on Oct. 14 that data center requests reached 200 GW."
)


def test_numbers_normalize_commas_currency_and_decimals():
    assert numbers("$1,200 and 3.5% of 87500, in 2026.") == {"1200", "3.5", "87500", "2026"}


def test_grounded_claim_passes():
    claim = "ERCOT said data center requests reached 200 GW, and peak demand may hit 87500 MW."
    assert ungrounded(claim, TEXT) == []


@pytest.mark.parametrize(
    ("claim", "expected"),
    [
        ("ERCOT said requests reached 250 GW this fall.", "number:250"),
        ("Dominion said requests reached 200 GW this fall.", "name:dominion"),
        ("ERCOT said on October 20 that requests reached 200 GW.", "number:20"),
        ("ERCOT said it expects 20 GW more by 2030.", "number:2030"),
        ("ERCOT cleared the Fermi project at 200 GW.", "name:fermi"),
    ],
)
def test_invented_specifics_are_flagged(claim, expected):
    assert expected in ungrounded(claim, TEXT)


def test_month_day_requires_month_in_cited_text():
    assert ungrounded("The operator spoke on November 14 about ERCOT.", TEXT)
    # "Oct." in the source supports "October 14".
    assert ungrounded("ERCOT spoke on October 14 about demand.", TEXT) == []


def test_sentence_initial_common_words_are_not_names():
    assert ungrounded("According to the operator, ERCOT sees 200 GW.", TEXT) == []


def test_possessives_and_hyphens_match():
    assert ungrounded("ERCOT's data-center requests reached 200 GW.", TEXT) == []


def _items():
    return {
        "a": {
            "id": "a",
            "title": "ERCOT forecasts peak demand of 87,500 MW next summer",
            "excerpt": "The Texas grid operator said data center requests reached 200 GW.",
            "url": "https://www.utilitydive.com/a/",
            "publisher": "Utility Dive",
            "published_at": "2026-10-14",
        },
        "b": {
            "id": "b",
            "title": "PJM capacity prices climb 12% in latest auction",
            "excerpt": "Auction results published for the PJM region.",
            "url": "https://www.utilitydive.com/b/",
            "publisher": "Utility Dive",
            "published_at": "2026-10-13",
        },
    }


def test_validate_claims_drops_ungrounded_and_unknown_ids_without_repairing():
    claims = [
        {"text": "ERCOT said data center requests reached 200 GW.", "evidence_ids": ["a"]},
        {"text": "ERCOT said data center requests reached 900 GW.", "evidence_ids": ["a"]},
        {"text": "ERCOT said data center requests reached 200 GW.", "evidence_ids": ["zzz"]},
        {"text": "PJM capacity prices climbed 12% at auction.", "evidence_ids": ["a"]},
        {"text": "See https://evil.example for ERCOT news at 200 GW.", "evidence_ids": ["a"]},
        {"text": "PJM capacity prices climbed 12% at auction.", "evidence_ids": ["b"]},
    ]
    valid, dropped = validate_claims(claims, _items(), max_claims=6)
    assert [c["evidence_ids"] for c in valid] == [["a"], ["b"]]
    assert dropped == 4


@pytest.mark.parametrize(
    "bad",
    [
        {"text": "ERCOT said data center requests reached 200 GW.", "evidence_ids": []},
        {"text": "ERCOT said data center requests reached 200 GW.", "evidence_ids": ["a", "a"]},
        {"text": "x", "evidence_ids": ["a"], "extra": 1},
        {"text": 5, "evidence_ids": ["a"]},
    ],
)
def test_malformed_claim_shapes_are_hard_errors(bad):
    with pytest.raises(ValueError, match="invalid_schema"):
        validate_claims([bad], _items(), max_claims=3)
    with pytest.raises(ValueError, match="invalid_schema"):
        validate_claims("nope", _items(), max_claims=3)


def test_headline_must_be_grounded_somewhere_in_the_provided_items():
    assert validate_headline("ERCOT demand forecast and PJM auction lead the week", _items())
    with pytest.raises(ValueError, match="invalid_headline"):
        validate_headline("Dominion unveils 400 GW plan for the grid", _items())
    with pytest.raises(ValueError, match="invalid_headline"):
        validate_headline("short", _items())


def test_render_numbers_citations_by_first_use_and_builds_links_server_side():
    top = [{"text": "PJM capacity prices climbed 12% at auction.", "evidence_ids": ["b"]}]
    sections = [
        {
            "key": "ercot:load-growth",
            "label": "ERCOT / Texas: Load growth and data centers",
            "paragraphs": [
                [
                    {
                        "text": "ERCOT said data center requests reached 200 GW.",
                        "evidence_ids": ["a", "b"],
                    }
                ]
            ],
        }
    ]
    result, citations = render_newsletter(
        "Grid week in review: prices and demand", top, sections, _items()
    )
    assert [c["evidence_id"] for c in citations] == ["b", "a"]
    assert result["top_summary"][0]["citations"] == [1]
    assert result["sections"][0]["paragraphs"][0][0]["citations"] == [2, 1]
    md = result["markdown"]
    assert md.startswith("# Grid week in review: prices and demand")
    assert (
        "AI-drafted" in md and "[1][2]" not in md.split("## Sources")[0].split("ERCOT / Texas")[0]
    )
    assert (
        "1. [PJM capacity prices climb 12% in latest auction](https://www.utilitydive.com/b/)" in md
    )
    assert "https://www.utilitydive.com/a/" in md
