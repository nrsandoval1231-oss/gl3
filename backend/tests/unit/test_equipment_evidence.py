from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from gridlens.domain.equipment_evidence import (
    EvidenceContext,
    EvidenceReference,
    validate_evidence_reference,
)


def reference_values():
    return {
        "source_id": "tx-permits",
        "observation_id": UUID("58bb8f9a-67ec-4ff1-a151-b2921ed48bf5"),
        "evidence_id": UUID("8fce83b7-c011-4626-bc76-b2127920de28"),
        "evidence_hash": "a" * 64,
        "source_url": "https://agency.example/permit/123",
        "observed_at": datetime(2026, 10, 28, 12, tzinfo=UTC),
        "retrieved_at": datetime(2026, 10, 28, 13, tzinfo=UTC),
        "published_at": date(2026, 10, 27),
        "extraction_location": "abstract paragraph 2",
        "extractor_version": "equipment-extract-v1",
        "quote": "Electric motor-driven compressor, 1,200 hp.",
    }


def context_for(values=None, *, source_text=None):
    values = values or reference_values()
    reference = EvidenceReference(**values)
    return EvidenceContext(
        project_id=UUID("aff1a621-9b4a-469d-84fa-70f267b96410"),
        need_id=UUID("a83021ee-70dc-4551-b20e-d7158dcb94a6"),
        reference=reference,
        source_text=source_text or f"Facility scope. {values['quote']} Additional context.",
    )


def test_valid_reference_binds_exact_snapshot_and_preserves_quote_and_hash():
    values = reference_values()
    values["quote"] = "  Electric motor-driven compressor, 1,200 hp. "
    context = context_for(values)

    result = validate_evidence_reference(values, context=context)

    assert result == context.reference
    assert result.quote == values["quote"]
    assert result.evidence_hash == "a" * 64
    assert result.evidence_hash != __import__("hashlib").sha256(result.quote.encode()).hexdigest()


def test_json_model_dump_roundtrip_is_accepted_without_coercion():
    values = reference_values()
    reference = EvidenceReference(**values)
    context = EvidenceContext(
        project_id=UUID("aff1a621-9b4a-469d-84fa-70f267b96410"),
        need_id=UUID("a83021ee-70dc-4551-b20e-d7158dcb94a6"),
        reference=reference,
        source_text=f"Facility scope. {reference.quote} Additional context.",
    )

    result = validate_evidence_reference(
        reference.model_dump(mode="json"), context=context.model_validate(context.model_dump())
    )

    assert result == reference


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("source_id", "other-source"),
        ("observation_id", uuid4()),
        ("evidence_id", uuid4()),
        ("evidence_hash", "b" * 64),
        ("source_url", "https://agency.example/permit/999"),
        ("observed_at", datetime(2026, 10, 28, 12, 1, tzinfo=UTC)),
        ("retrieved_at", datetime(2026, 10, 28, 13, 1, tzinfo=UTC)),
        ("published_at", date(2026, 10, 26)),
        ("extraction_location", "title"),
        ("extractor_version", "other-version"),
        ("quote", "Compressor, 1,200 hp."),
    ],
)
def test_reference_must_match_supplied_retained_snapshot(field, replacement):
    context = context_for()
    candidate = reference_values()
    candidate[field] = replacement

    with pytest.raises(ValueError):
        validate_evidence_reference(candidate, context=context)


def test_quote_must_be_nonblank_exact_substring_and_is_not_rewritten():
    values = reference_values()
    values["quote"] = "  Electric motor-driven compressor, 1,200 hp. "
    context = context_for(values)
    assert validate_evidence_reference(values, context=context).quote == values["quote"]

    for quote in ("", " \n ", "Electric compressor"):
        candidate = dict(values, quote=quote)
        with pytest.raises(ValueError):
            validate_evidence_reference(candidate, context=context)


def test_rejects_naive_datetimes_and_invalid_chronology():
    context = context_for()
    values = reference_values()
    values["observed_at"] = datetime(2026, 10, 28, 12)
    with pytest.raises(ValueError):
        validate_evidence_reference(values, context=context)

    values = reference_values()
    values["retrieved_at"] = values["observed_at"] - timedelta(seconds=1)
    with pytest.raises(ValueError):
        validate_evidence_reference(values, context=context)

    values = reference_values()
    values["published_at"] = date(2026, 10, 29)
    with pytest.raises(ValueError):
        validate_evidence_reference(values, context=context)


def test_rejects_malformed_hash_urls_missing_and_extra_fields():
    context = context_for()
    values = reference_values()
    values["evidence_hash"] = "not-a-sha256"
    with pytest.raises(ValueError):
        validate_evidence_reference(values, context=context)

    for url in (
        "ftp://agency.example/permit/123",
        "https://user:secret@agency.example/permit/123",
        "https://agency.example/other",
    ):
        candidate = dict(reference_values(), source_url=url)
        with pytest.raises(ValueError):
            validate_evidence_reference(candidate, context=context)

    for candidate in (
        {key: value for key, value in reference_values().items() if key != "quote"},
        dict(reference_values(), unsupported="value"),
    ):
        with pytest.raises(ValueError):
            validate_evidence_reference(candidate, context=context)


def test_reference_and_context_are_frozen():
    values = reference_values()
    reference = EvidenceReference(**values)
    with pytest.raises(ValidationError):
        reference.source_id = "mutated"
    context = context_for(values)
    with pytest.raises(ValidationError):
        context.source_text = "mutated"


def test_model_construct_cannot_bypass_reference_or_context_validation():
    values = reference_values()
    reference = EvidenceReference.model_construct(**dict(values, quote="not in source"))
    context = EvidenceContext.model_construct(
        project_id=UUID("aff1a621-9b4a-469d-84fa-70f267b96410"),
        need_id=UUID("a83021ee-70dc-4551-b20e-d7158dcb94a6"),
        reference=reference,
        source_text="retained excerpt",
    )

    with pytest.raises(ValueError):
        validate_evidence_reference(reference, context=context)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("observation_id", "58BB8F9A-67EC-4FF1-A151-B2921ED48BF5"),
        ("observed_at", "2026-10-28T12:00:00"),
        ("retrieved_at", "2026-10-28T13:00:00Z "),
        ("published_at", "2026-10-27T00:00:00"),
    ],
)
def test_rejects_noncanonical_or_naive_serialized_values(field, value):
    context = context_for()
    candidate = dict(reference_values(), **{field: value})

    with pytest.raises(ValueError):
        validate_evidence_reference(candidate, context=context)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_id", 7),
        ("observation_id", True),
        ("evidence_id", 1),
        ("evidence_hash", True),
        ("source_url", 3),
        ("observed_at", 1),
        ("retrieved_at", False),
        ("published_at", True),
        ("extraction_location", 2),
        ("extractor_version", False),
        ("quote", 99),
    ],
)
def test_rejects_boolean_and_numeric_coercion(field, value):
    context = context_for()
    candidate = dict(reference_values(), **{field: value})

    with pytest.raises(ValueError):
        validate_evidence_reference(candidate, context=context)
