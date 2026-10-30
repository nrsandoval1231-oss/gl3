from copy import deepcopy
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from gridlens.domain.equipment_claims import (
    EquipmentClaim,
    EquipmentRating,
    validate_equipment_claim,
)
from gridlens.domain.equipment_evidence import EvidenceContext, EvidenceReference

PROJECT_ID = UUID("aff1a621-9b4a-469d-84fa-70f267b96410")
NEED_ID = UUID("a83021ee-70dc-4551-b20e-d7158dcb94a6")


def context_for():
    reference = EvidenceReference(
        source_id="tx-permits",
        observation_id=UUID("58bb8f9a-67ec-4ff1-a151-b2921ed48bf5"),
        evidence_id=UUID("8fce83b7-c011-4626-bc76-b2127920de28"),
        evidence_hash="a" * 64,
        source_url="https://agency.example/permit/123",
        observed_at=datetime(2026, 10, 28, 12, tzinfo=UTC),
        retrieved_at=datetime(2026, 10, 28, 13, tzinfo=UTC),
        published_at=date(2026, 10, 27),
        extraction_location="abstract paragraph 2",
        extractor_version="equipment-extract-v1",
        quote="Electric motor-driven compressor, 1,200 hp.",
    )
    return EvidenceContext(
        project_id=PROJECT_ID,
        need_id=NEED_ID,
        reference=reference,
        source_text=f"Facility scope. {reference.quote} Additional context.",
    )


def reference_values(reference):
    if hasattr(reference, "model_dump"):
        return reference.model_dump(mode="python")
    return {name: getattr(reference, name) for name in EvidenceReference.__dataclass_fields__}


def candidate(**overrides):
    value = {
        "schema_version": "equipment-claim-v1",
        "claim_id": str(uuid4()),
        "project_id": str(PROJECT_ID),
        "need_id": str(NEED_ID),
        "equipment_id": "compressor-1",
        "equipment_type": "compressor",
        "drive_type": "unknown",
        "lifecycle_status": "unknown",
        "operating_role": "unknown",
        "count": None,
        "rating": None,
        "evidence": reference_values(context_for().reference),
        "verification_state": "UNVERIFIED",
        "claim_state": "reported",
    }
    value.update(overrides)
    return value


def rating(value="1200", unit="hp", basis="mechanical_output"):
    return {"value": value, "unit": unit, "basis": basis}


def test_valid_candidate_preserves_raw_rating_and_is_frozen_unverified():
    context = context_for()
    result = validate_equipment_claim(
        candidate(
            claim_id=uuid4(),
            project_id=PROJECT_ID,
            need_id=NEED_ID,
            count=2,
            rating=rating("001200.00"),
        ),
        context=context,
    )
    assert isinstance(result.claim_id, UUID)
    assert result.rating.value == "001200.00"
    assert result.verification_state == "UNVERIFIED"
    with pytest.raises((ValidationError, TypeError, AttributeError)):
        result.equipment_id = "changed"


@pytest.mark.parametrize("identifier", [PROJECT_ID, str(PROJECT_ID)])
def test_accepts_uuid_and_canonical_uuid_text(identifier):
    value = validate_equipment_claim(candidate(project_id=identifier), context=context_for())
    assert value.project_id == PROJECT_ID


@pytest.mark.parametrize(
    "identifier",
    ["AFF1A621-9B4A-469D-84FA-70F267B96410", "not-a-uuid", 4, True],
)
def test_rejects_noncanonical_or_wrongly_typed_uuids(identifier):
    with pytest.raises((ValidationError, ValueError, TypeError)):
        validate_equipment_claim(candidate(project_id=identifier), context=context_for())


@pytest.mark.parametrize("field", ["project_id", "need_id"])
def test_rejects_cross_scope(field):
    with pytest.raises((ValidationError, ValueError)):
        validate_equipment_claim(candidate(**{field: str(uuid4())}), context=context_for())


@pytest.mark.parametrize("raw", [1200, 1200.0, True, "NaN", "Infinity", "-Infinity", "0", "-1"])
def test_rating_quantity_must_be_finite_positive_decimal_string(raw):
    with pytest.raises((ValidationError, ValueError)):
        validate_equipment_claim(candidate(rating=rating(raw)), context=context_for())


@pytest.mark.parametrize(
    "raw", ["1_000", " 12", "12 ", "1e999", "١٢", "１２", "+12", "-0.1", "1..2", "."]
)
def test_rating_requires_bounded_ascii_decimal_lexeme(raw):
    with pytest.raises((ValidationError, ValueError)):
        validate_equipment_claim(candidate(rating=rating(raw)), context=context_for())


@pytest.mark.parametrize("raw", [".5", "0012", "12.00", "12."])
def test_rating_preserves_valid_decimal_lexeme(raw):
    result = validate_equipment_claim(candidate(rating=rating(raw)), context=context_for())
    assert result.rating.value == raw


def test_rating_lexeme_is_limited_to_100_characters():
    with pytest.raises((ValidationError, ValueError)):
        validate_equipment_claim(candidate(rating=rating("1" + "0" * 100)), context=context_for())


def test_equipment_id_is_limited_to_200_characters():
    with pytest.raises((ValidationError, ValueError)):
        validate_equipment_claim(candidate(equipment_id="e" * 201), context=context_for())


@pytest.mark.parametrize(
    ("unit", "basis"),
    [
        ("MW", "electrical_input"),
        ("kW", "mechanical_output"),
        ("hp", "generator_output"),
        ("kVA", "unknown"),
    ],
)
def test_rating_accepts_exact_supported_unit_and_basis(unit, basis):
    result = validate_equipment_claim(
        candidate(rating=rating("0.125", unit, basis)), context=context_for()
    )
    assert result.rating.unit == unit
    assert result.rating.value == "0.125"


@pytest.mark.parametrize("raw", [0, -1, 1.5, "2", True])
def test_count_is_null_or_strict_positive_integer(raw):
    with pytest.raises((ValidationError, ValueError)):
        validate_equipment_claim(candidate(count=raw), context=context_for())


@pytest.mark.parametrize(
    ("drive", "role", "status", "rating_value"),
    [
        ("gas_engine", "duty", "installed", rating("1200", "hp", "mechanical_output")),
        ("unknown", "duty", "installed", rating("1200", "hp", "mechanical_output")),
        ("mixed", "duty", "installed", rating("1200", "hp", "mechanical_output")),
        ("electric", "standby", "installed", rating("1200", "hp", "mechanical_output")),
        ("electric", "redundant", "proposed", None),
    ],
)
def test_unknown_gas_standby_and_missing_values_remain_unverified_candidates(
    drive, role, status, rating_value
):
    result = validate_equipment_claim(
        candidate(
            drive_type=drive,
            operating_role=role,
            lifecycle_status=status,
            rating=rating_value,
        ),
        context=context_for(),
    )
    assert result.verification_state == "UNVERIFIED"
    assert result.claim_state == "reported"
    if rating_value is None:
        assert result.rating is None
    else:
        assert result.rating.value == rating_value["value"]
        assert result.rating.unit == rating_value["unit"]
        assert result.rating.basis == rating_value["basis"]
    assert not hasattr(result, "load_mw")
    assert not hasattr(result, "gap_mw")
    assert not hasattr(result, "tier")


@pytest.mark.parametrize("verification", ["VERIFIED", "verified", True, None])
def test_caller_cannot_promote_verification(verification):
    with pytest.raises((ValidationError, ValueError)):
        validate_equipment_claim(candidate(verification_state=verification), context=context_for())


@pytest.mark.parametrize("extra", ["gap_mw", "load_mw", "tier", "confidence", "calculation"])
def test_forbids_derived_or_qualification_fields(extra):
    with pytest.raises((ValidationError, ValueError)):
        validate_equipment_claim(candidate(**{extra: "1.2"}), context=context_for())


def test_forbids_extra_fields_inside_rating():
    value = candidate(rating=rating())
    value["rating"]["electrical_input_kw"] = "900"
    with pytest.raises((ValidationError, ValueError)):
        validate_equipment_claim(value, context=context_for())


def test_revalidates_constructed_nested_rating_instance():
    value = candidate(
        rating=EquipmentRating.model_construct(value="NaN", unit="MW", basis="electrical_input")
    )
    with pytest.raises((ValidationError, ValueError)):
        validate_equipment_claim(value, context=context_for())


def test_evidence_reference_must_validate_against_context():
    value = candidate()
    value["evidence"]["evidence_hash"] = "b" * 64
    with pytest.raises((ValidationError, ValueError)):
        validate_equipment_claim(value, context=context_for())


def test_claim_is_candidate_only_and_does_not_modify_input():
    value = candidate(rating=rating())
    original = deepcopy(value)
    result = validate_equipment_claim(value, context=context_for())
    assert value == original
    assert result.verification_state == "UNVERIFIED"
    assert result.claim_state == "reported"


def test_json_model_dump_roundtrip_is_accepted_without_coercion():
    context = context_for()
    claim = validate_equipment_claim(candidate(rating=rating(".5")), context=context)
    result = validate_equipment_claim(claim.model_dump(mode="json"), context=context)
    assert result.claim_id == claim.claim_id
    assert result.rating.value == ".5"
    assert result.evidence == context.reference
    assert result.verification_state == "UNVERIFIED"


def test_rejects_non_context_mapping():
    with pytest.raises(ValueError, match="EvidenceContext"):
        validate_equipment_claim(candidate(), context=context_for().model_dump(mode="python"))


def test_revalidates_constructed_malformed_context():
    malformed = EvidenceContext.model_construct(
        project_id="not-a-uuid",
        need_id=NEED_ID,
        reference=context_for().reference,
        source_text="Electric motor-driven compressor, 1,200 hp.",
    )
    with pytest.raises(ValueError, match="context"):
        validate_equipment_claim(candidate(), context=malformed)


def test_rejects_constructed_claim_instance_at_mapping_boundary():
    claim = EquipmentClaim.model_construct(**candidate())
    with pytest.raises(ValueError, match="object"):
        validate_equipment_claim(claim, context=context_for())
