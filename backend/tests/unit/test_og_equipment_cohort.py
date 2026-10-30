"""Synthetic claim contract checks plus source-backed RRC excerpt limits."""

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from uuid import UUID

import pytest

from gridlens.domain.equipment_claims import validate_equipment_claim
from gridlens.domain.equipment_evidence import EvidenceContext, EvidenceReference

FIXTURE_DIR = Path(__file__).parents[1] / "fixtures"
COHORT_PATH = FIXTURE_DIR / "og_equipment_claims.json"


def cohort():
    return json.loads(COHORT_PATH.read_text(encoding="utf-8"))


def synthetic_context(case):
    config = cohort()["synthetic_context"]
    quote = case["quote"]
    reference = EvidenceReference(
        source_id=config["source_id"],
        observation_id=UUID("4e5dfc89-b8a7-498b-8903-05ff26da7568"),
        evidence_id=UUID("ed27b7e4-86b2-4c67-8a35-835e85d328ea"),
        evidence_hash="a" * 64,
        source_url=config["source_url"],
        observed_at=datetime.fromisoformat(config["observed_at"]),
        retrieved_at=datetime.fromisoformat(config["retrieved_at"]),
        published_at=date.fromisoformat(config["published_at"]),
        extraction_location=config["extraction_location"],
        extractor_version=config["extractor_version"],
        quote=quote,
    )
    return EvidenceContext(
        project_id=UUID(config["project_id"]),
        need_id=UUID(config["need_id"]),
        reference=reference,
        source_text=f"{quote} All assertion text in this context is synthetic test data.",
    )


def claim_for(case, context):
    return {
        "schema_version": "equipment-claim-v1",
        "claim_id": "3c06ebf1-2865-4e49-b327-1806adbfdd00",
        "project_id": str(context.project_id),
        "need_id": str(context.need_id),
        "equipment_id": f"synthetic:{case['name']}",
        "equipment_type": case["equipment_type"],
        "drive_type": case["drive_type"],
        "lifecycle_status": case["lifecycle_status"],
        "operating_role": case["operating_role"],
        "count": case["count"],
        "rating": case["rating"],
        "evidence": context.reference,
        "verification_state": "UNVERIFIED",
        "claim_state": case["claim_state"],
    }


@pytest.mark.parametrize("case", cohort()["synthetic_cases"], ids=lambda case: case["name"])
def test_synthetic_og_equipment_candidates_preserve_unknowns_and_never_qualify(case):
    context = synthetic_context(case)
    result = validate_equipment_claim(claim_for(case, context), context=context)

    assert result.verification_state == "UNVERIFIED"
    assert result.claim_state == case["claim_state"]
    assert result.drive_type == case["drive_type"]
    result_rating = (
        {
            "value": result.rating.value,
            "unit": result.rating.unit,
            "basis": result.rating.basis,
        }
        if result.rating is not None
        else None
    )
    assert result_rating == case["rating"]
    assert not hasattr(result, "required_mw")
    assert not hasattr(result, "power_gap_mw")


def test_candidates_reject_project_or_need_scope_mismatch():
    case = cohort()["synthetic_cases"][0]
    context = synthetic_context(case)
    candidate = claim_for(case, context)
    candidate["project_id"] = "40676335-c8e8-4d6a-a51e-b70f6df572c3"
    with pytest.raises(ValueError):
        validate_equipment_claim(candidate, context=context)

    candidate = claim_for(case, context)
    candidate["need_id"] = "40676335-c8e8-4d6a-a51e-b70f6df572c3"
    with pytest.raises(ValueError):
        validate_equipment_claim(candidate, context=context)


@pytest.mark.parametrize("case", cohort()["synthetic_cases"], ids=lambda case: case["name"])
def test_synthetic_claim_source_quote_is_exact_and_bound_to_test_snapshot(case):
    context = synthetic_context(case)
    candidate = claim_for(case, context)
    candidate["evidence"] = candidate["evidence"].model_dump()
    candidate["evidence"]["source_id"] = "different-synthetic-source"
    with pytest.raises((ValueError, TypeError, AttributeError)):
        validate_equipment_claim(candidate, context=context)


@pytest.mark.parametrize(
    "field,value", [("required_mw", "9"), ("power_gap_mw", "9"), ("qualification", "Lead")]
)
def test_candidate_rejects_injected_qualification_or_derived_mw(field, value):
    case = cohort()["synthetic_cases"][0]
    context = synthetic_context(case)
    candidate = claim_for(case, context)
    candidate[field] = value
    with pytest.raises(ValueError):
        validate_equipment_claim(candidate, context=context)


def test_actual_retained_rrc_completion_fixtures_are_hash_bound_and_have_no_equipment_claim():
    data = cohort()
    manifest_cache = {}
    for sample in data["retained_sources"]:
        source_bytes = (Path(__file__).parents[3] / sample["fixture_path"]).read_bytes()
        # Windows checkout may normalize Git LF content to CRLF; the manifest hashes
        # the canonical LF fixture bytes, so normalize only this transport difference.
        canonical_bytes = source_bytes.replace(b"\r\n", b"\n")
        assert hashlib.sha256(canonical_bytes).hexdigest() == sample["fixture_sha256"]

        manifest_path = Path(__file__).parents[3] / sample["manifest_path"]
        manifest = manifest_cache.setdefault(
            str(manifest_path), json.loads(manifest_path.read_text(encoding="utf-8"))
        )
        source_name = Path(sample["fixture_path"]).name
        assert manifest[source_name]["fixture_sha256"] == sample["fixture_sha256"]
        assert manifest[source_name]["source_host"] == sample["source_host"]

        retained_text = canonical_bytes.decode("ISO-8859-1")
        assert sample["source_excerpt"] in retained_text
        fact_limit = sample["observed_fact_limit"].casefold()
        assert "equipment" in fact_limit and any(
            marker in fact_limit for marker in ("does not identify", "contains no retained")
        )

        # The only permitted project identity in the fixture cohort is the source's
        # historical well/operator identity. Synthetic claims above use other IDs.
        assert "16538299" in retained_text
        assert data["synthetic_context"]["source_id"] == "synthetic-fixture-only"
        lowered_source = retained_text.casefold()
        assert all(
            term not in lowered_source for term in ("compressor", "pump", "horsepower", "motor")
        )


def test_historical_federal_filing_supports_only_unverified_proposed_equipment_claim():
    root = Path(__file__).parents[3]
    excerpt_path = root / "backend/tests/fixtures/ferc-cp24-8-equipment-excerpt.txt"
    provenance_path = root / "backend/tests/fixtures/ferc-cp24-8-equipment-provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    excerpt_bytes = excerpt_path.read_bytes()
    assert hashlib.sha256(excerpt_bytes).hexdigest() == provenance["retained_excerpt_sha256"]
    quote = excerpt_bytes.decode("utf-8").strip("\n")
    assert (
        quote == "Install one new electric motor driven compressor unit with a rating of 18,340 hp."
    )

    # These UUIDs bind a test candidate only; they are not asserted production IDs.
    project_id = UUID("62af1d7d-93c5-4b51-a9d7-d035754ea21a")
    need_id = UUID("c1492405-a164-4d60-b436-71600bf76e64")
    reference = EvidenceReference(
        source_id="us-gpo-federal-register-fixture",
        observation_id=UUID("4052b6ad-9c18-4134-9c6a-c86d21080b43"),
        evidence_id=UUID("b08e3620-fbdc-4992-8d6b-8c46891e1f81"),
        evidence_hash=provenance["original_source_sha256"],
        source_url=provenance["source_url"],
        observed_at=datetime.fromisoformat(provenance["retrieved_at"]),
        retrieved_at=datetime.fromisoformat(provenance["retrieved_at"]),
        published_at=date.fromisoformat(provenance["published_at"]),
        extraction_location="Federal Register HTML; exact retained sentence excerpt",
        extractor_version="manual-retained-excerpt-v1",
        quote=quote,
    )
    context = EvidenceContext(
        project_id=project_id,
        need_id=need_id,
        reference=reference,
        source_text=quote,
    )
    claim = {
        "schema_version": "equipment-claim-v1",
        "claim_id": "63654db3-12b1-4a45-bd07-f120a88202e0",
        "project_id": str(project_id),
        "need_id": str(need_id),
        "equipment_id": "fixture-only:cp24-8:compressor-station-302",
        "equipment_type": provenance["source_assertion"]["equipment_type"],
        "drive_type": provenance["source_assertion"]["drive_type"],
        "lifecycle_status": provenance["source_assertion"]["lifecycle_status"],
        "operating_role": provenance["source_assertion"]["operating_role"],
        "count": provenance["source_assertion"]["count"],
        "rating": {
            "value": provenance["source_assertion"]["rating_value"],
            "unit": provenance["source_assertion"]["rating_unit"],
            "basis": provenance["source_assertion"]["rating_basis"],
        },
        "evidence": reference.model_dump(),
        "verification_state": "UNVERIFIED",
        "claim_state": "reported",
    }

    result = validate_equipment_claim(claim, context=context)

    assert result.drive_type == "electric"
    assert result.equipment_type == "compressor"
    assert result.count == 1
    assert result.lifecycle_status == "proposed"
    assert result.rating.value == "18340"
    assert result.rating.unit == "hp" and result.rating.basis == "unknown"
    assert result.verification_state == "UNVERIFIED"
    assert not hasattr(result, "required_mw")
    assert not hasattr(result, "power_gap_mw")
