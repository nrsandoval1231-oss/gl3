from uuid import uuid4

import pytest

from gridlens.intelligence.grounded_candidates import validate_grounded_candidates


def _payload(evidence_id, evidence_hash, quote, **overrides):
    start = len("Permit ")
    raw = {
        "field": "temporary_load_mw",
        "value": "12.5",
        "unit": "MW",
        "original_value": "12.5",
        "original_unit": "MW",
        "precision": 1,
        "date_precision": None,
        "evidence_id": str(evidence_id),
        "evidence_hash": evidence_hash,
        "quote": quote,
        "section": "abstract",
        "page": None,
        "span_start": start,
        "span_end": start + len(quote),
        "publisher": "County Permit Office",
        "published_date": "2026-10-01",
        "speaker": None,
        "speaker_organization": None,
        "speaker_role": None,
        "support": "direct",
        "status": "candidate",
    }
    raw.update(overrides)
    if raw["field"] != "temporary_load_mw":
        raw.update(original_value=None, original_unit=None, precision=None)
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
        ({"value": "2026-10"}, "Temporary load of 12.5 MW is requested.", "normalization"),
        (
            {"field": "construction_start", "value": "October 2026", "date_precision": "day"},
            "Start October 2026",
            "precision",
        ),
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
        date_precision="day",
        unit=None,
        publisher="Utility",
        span_start=len("Service application\n"),
        span_end=len("Service application\n") + len(quote),
    )
    result = validate_grounded_candidates(output, evidence)
    assert result["candidates"][0]["value"] == "2027-04-01"


@pytest.mark.parametrize(
    ("raw", "normalized", "unit", "precision", "quote"),
    [
        ("300", "0.3", "kW", 0, "The temporary load request is 300 kW for the bridge period."),
        ("0.30", "0.3", "MW", 2, "The temporary load request is 0.30 MW for the bridge period."),
        (
            "200-300",
            "0.2-0.3",
            "kW",
            0,
            "The temporary load request is 200 kW to 300 kW for bridge power.",
        ),
    ],
)
def test_explicit_kw_mw_and_ranges_preserve_source_precision(
    raw, normalized, unit, precision, quote
):
    evidence_id = uuid4()
    digest = "f" * 64
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
    output = _payload(
        evidence_id,
        digest,
        quote,
        value=normalized,
        original_value=raw,
        original_unit=unit,
        precision=precision,
    )
    result = validate_grounded_candidates(output, evidence)
    assert result["candidates"][0]["value"] == normalized
    assert result["candidates"][0]["original_value"] == raw


@pytest.mark.parametrize(
    ("value", "date_precision", "quote"),
    [
        ("2027", "year", "The utility date is expected during 2027."),
        ("2027-04", "month", "The utility date is expected in 2027-04."),
        ("2027-Q3", "quarter", "The utility date is expected in 2027-Q3."),
        ("2027-04-12", "day", "The utility date is expected on 2027-04-12."),
    ],
)
def test_explicit_date_precision_is_preserved(value, date_precision, quote):
    evidence_id = uuid4()
    digest = "1" * 64
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
    output = _payload(
        evidence_id,
        digest,
        quote,
        field="commissioning_window",
        value=value,
        unit=None,
        date_precision=date_precision,
    )
    assert validate_grounded_candidates(output, evidence)["candidates"][0]["value"] == value


def test_page_citation_requires_single_page_location_or_containing_page_segment():
    evidence_id = uuid4()
    digest = "2" * 64
    quote = "The online service date is 2027-Q3 and was confirmed in this filing."
    evidence = [
        {
            "id": str(evidence_id),
            "content_hash": digest,
            "title": "Permit",
            "abstract": quote,
            "publisher": "GovInfo",
            "published_at": "2026-10-01",
            "extraction_location": "GovInfo PDF page 8",
        }
    ]
    output = _payload(
        evidence_id,
        digest,
        quote,
        field="commissioning_window",
        value="2027-Q3",
        date_precision="quarter",
        unit=None,
        page=8,
        publisher="GovInfo",
    )
    assert validate_grounded_candidates(output, evidence)["candidates"][0]["page"] == 8
    evidence[0]["extraction_location"] = "PDF pages 1-12 (inline page markers)"
    with pytest.raises(ValueError, match="page"):
        validate_grounded_candidates(output, evidence)


def test_later_page_excerpt_requires_its_containing_inline_page_marker():
    evidence_id = uuid4()
    digest = "4" * 64
    quote = "Georgia permit reports commissioning during 2028-Q2."
    abstract = f"Page 1: Earlier permit summary.\nPage 6: {quote}\nPage 7: Unrelated appendix."
    evidence = [
        {
            "id": str(evidence_id),
            "content_hash": digest,
            "title": "Permit",
            "abstract": abstract,
            "publisher": "Georgia EPD",
            "published_at": "2026-10-01",
            "extraction_location": "PDF pages 1-7 (inline page markers)",
        }
    ]
    start = len("Permit\n") + abstract.index(quote)
    output = _payload(
        evidence_id,
        digest,
        quote,
        field="commissioning_window",
        value="2028-Q2",
        date_precision="quarter",
        unit=None,
        page=6,
        publisher="Georgia EPD",
        span_start=start,
        span_end=start + len(quote),
    )
    assert validate_grounded_candidates(output, evidence)["candidates"][0]["page"] == 6
    output["candidates"][0]["page"] = 1
    with pytest.raises(ValueError, match="page"):
        validate_grounded_candidates(output, evidence)


def test_partial_speaker_attribution_requires_quote_support_and_remains_nullable():
    evidence_id = uuid4()
    digest = "3" * 64
    quote = "Utility director Maya Chen said service will begin in 2027-Q3."
    evidence = [
        {
            "id": str(evidence_id),
            "content_hash": digest,
            "title": "Permit",
            "abstract": quote,
            "publisher": "Utility",
            "published_at": "2026-10-01",
        }
    ]
    output = _payload(
        evidence_id,
        digest,
        quote,
        field="commissioning_window",
        value="2027-Q3",
        date_precision="quarter",
        unit=None,
        speaker="Maya Chen",
        publisher="Utility",
    )
    assert (
        validate_grounded_candidates(output, evidence)["candidates"][0]["speaker_organization"]
        is None
    )
    output["candidates"][0]["speaker_role"] = "CEO"
    with pytest.raises(ValueError, match="attribution"):
        validate_grounded_candidates(output, evidence)


@pytest.mark.parametrize(
    ("field", "value", "date_precision", "original_value", "original_unit", "quote"),
    [
        (
            "temporary_load_mw",
            "0.3",
            None,
            "300",
            "kW",
            "Temporary load is not 300 kW for this phase.",
        ),
        (
            "commissioning_window",
            "2027-Q3",
            "quarter",
            None,
            None,
            "Utility service is not expected in 2027-Q3.",
        ),
    ],
)
def test_negated_quantity_or_date_cannot_become_candidate(
    field, value, date_precision, original_value, original_unit, quote
):
    evidence_id = uuid4()
    digest = "5" * 64
    evidence = [
        {
            "id": str(evidence_id),
            "content_hash": digest,
            "title": "Permit",
            "abstract": quote,
            "publisher": "Utility",
            "published_at": "2026-10-01",
        }
    ]
    output = _payload(
        evidence_id,
        digest,
        quote,
        field=field,
        value=value,
        date_precision=date_precision,
        unit="MW" if field == "temporary_load_mw" else None,
        original_value=original_value,
        original_unit=original_unit,
        precision=0 if original_value else None,
        publisher="Utility",
    )
    with pytest.raises(ValueError, match="negated"):
        validate_grounded_candidates(output, evidence)


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
