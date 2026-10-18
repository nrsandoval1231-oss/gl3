from uuid import uuid4

import pytest

from gridlens.intelligence.grounded_candidates import validate_grounded_candidates


def _payload(evidence_id, evidence_hash, quote, **overrides):
    start = len("Permit ")
    raw = {
        "field": "temporary_load_mw",
        "value": "12.5",
        "unit": "MW",
        "evidence_id": str(evidence_id),
        "evidence_hash": evidence_hash,
        "quote": quote,
        "section": "abstract",
        "page": None,
        "span_start": start,
        "span_end": start + len(quote),
        "publisher": "County Permit Office",
        "published_date": "2026-10-01",
        "support": "direct",
        "status": "candidate",
    }
    raw.update(overrides)
    return {
        "candidates": [raw],
        "hypotheses": ["Potential bridge-power demand; verify with buyer."],
        "contradictions": [],
        "unresolved_questions": ["Who controls procurement?"],
        "candidate_orgs": [],
        "proposed_queries": ["County permit application temporary generator MW"],
        "suggested_pursuit": None,
    }


def test_grounded_candidate_accepts_exact_retained_json_span():
    evidence_id = uuid4()
    digest = "a" * 64
    quote = "Temporary load of 12.5 MW is requested."
    evidence = [
        {
            "id": str(evidence_id),
            "content_hash": digest,
            "title": "Permit",
            "abstract": quote,
            "publisher": "County Permit Office",
            "published_at": "2026-10-01",
        }
    ]
    result = validate_grounded_candidates(_payload(evidence_id, digest, quote), evidence)
    assert result["candidates"][0]["evidence_id"] == str(evidence_id)
    assert result["candidates"][0]["status"] == "candidate"
    assert result["suggested_pursuit"] is None


@pytest.mark.parametrize(
    ("overrides", "quote", "message"),
    [
        ({"span_end": 4}, "Temporary load of 12.5 MW is requested.", "span"),
        ({"unit": "kW"}, "Temporary load of 12.5 MW is requested.", "MW"),
        ({"value": "2026-10"}, "Temporary load of 12.5 MW is requested.", "decimal"),
        ({"field": "construction_start", "value": "October 2026"}, "Start October 2026", "date"),
    ],
)
def test_grounded_candidate_rejects_invalid_span_units_values_and_dates(overrides, quote, message):
    evidence_id = uuid4()
    digest = "b" * 64
    evidence = [
        {
            "id": str(evidence_id),
            "content_hash": digest,
            "title": "Permit",
            "abstract": quote,
            "publisher": "County Permit Office",
            "published_at": "2026-10-01",
        }
    ]
    with pytest.raises(ValueError, match=message):
        validate_grounded_candidates(_payload(evidence_id, digest, quote, **overrides), evidence)


def test_grounded_candidate_denies_flare_as_available_fuel():
    evidence_id = uuid4()
    digest = "c" * 64
    quote = "Natural gas is available from the flare stack."
    evidence = [
        {
            "id": str(evidence_id),
            "content_hash": digest,
            "title": "Permit",
            "abstract": quote,
            "publisher": "County Permit Office",
            "published_at": "2026-10-01",
        }
    ]
    with pytest.raises(ValueError, match="flaring"):
        validate_grounded_candidates(
            _payload(
                evidence_id,
                digest,
                quote,
                field="natural_gas_availability",
                value="available",
                unit=None,
            ),
            evidence,
        )


def test_candidate_json_string_dates_and_provider_metadata_are_strict():
    evidence_id = uuid4()
    digest = "d" * 64
    quote = "The utility service is expected online on 2027-04-01."
    evidence = [
        {
            "id": str(evidence_id),
            "content_hash": digest,
            "title": "Service application",
            "abstract": quote,
            "publisher": "Utility",
            "published_at": "2026-10-01",
        }
    ]
    output = _payload(
        evidence_id,
        digest,
        quote,
        field="utility_online_date",
        value="2027-04-01",
        unit=None,
        publisher="Utility",
        span_start=len("Service application\n"),
        span_end=len("Service application\n") + len(quote),
    )
    result = validate_grounded_candidates(output, evidence)
    assert result["candidates"][0]["value"] == "2027-04-01"


def test_untrusted_suggested_queries_cannot_become_urls():
    evidence_id = uuid4()
    digest = "e" * 64
    quote = "Temporary load of 12.5 MW is requested."
    evidence = [
        {
            "id": str(evidence_id),
            "content_hash": digest,
            "title": "Permit",
            "abstract": quote,
            "publisher": "County Permit Office",
            "published_at": "2026-10-01",
        }
    ]
    with pytest.raises(ValueError):
        validate_grounded_candidates(
            _payload(evidence_id, digest, quote, proposed_queries=["https://evil.example/"]),
            evidence,
        )
