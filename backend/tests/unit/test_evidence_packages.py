from uuid import uuid4

import pytest

from gridlens.intelligence.evidence_packages import (
    MODEL,
    PROVIDER,
    QUESTION_CONTRACT,
    SCHEMA_VERSION,
    _digest,
    validate_package,
)


def valid_package():
    evidence_id = str(uuid4())
    observation_id = str(uuid4())
    content_hash = "a" * 64
    url = "https://example.gov/record/1"
    title = "Applicant: ACME Builders"
    package = {
        "schema_version": SCHEMA_VERSION,
        "processing_status": "PREPARED",
        "package_key": "",
        "provider": PROVIDER,
        "model": MODEL,
        "question_contract": QUESTION_CONTRACT,
        "source_references": [
            {
                "evidence_id": evidence_id,
                "evidence_hash": content_hash,
                "observation_id": observation_id,
                "source_id": "example-source",
                "url": url,
                "extraction_location": "record excerpt",
                "field_lengths": {"title": len(title), "abstract": 0},
            }
        ],
        "identity": {"project_id": None, "project_identity_key": None, "need_id": None},
        "extractor_version": "retained-evidence-fields-v1",
        "facts": [
            {
                "field": "applicant",
                "value": "ACME Builders",
                "unit": None,
                "label": "REPORTED",
                "extractor_basis": "explicit retained label Applicant",
                "citation": {
                    "evidence_id": evidence_id,
                    "evidence_hash": content_hash,
                    "url": url,
                    "excerpt_location": {"field": "title", "start": 11, "end": 24},
                },
            }
        ],
        "entity_candidates": [],
        "missing_fields": [
            {"field": "required_mw", "status": "UNKNOWN", "reason": "No labeled source value."}
        ],
        "contradiction_pairs": [],
        "unevaluated_dimensions": ["cross-claim contradictions"],
        "quality_basis": ["Exact retained label and span."],
        "document_coverage": "RECORD_EXCERPT",
        "document_coverage_basis": "Retained text is an excerpt.",
        "jev_input_coverage": {
            "title": "WHOLE_RETAINED_FIELD",
            "title_sent_characters": len(title),
            "abstract": "WHOLE_RETAINED_ABSTRACT",
            "abstract_sent_characters": 0,
            "abstract_omitted_tail_characters": 0,
            "url_sent_characters": len(url),
            "url_omitted_tail_characters": 0,
            "published_at_sent_characters": 7,
            "metadata_fields_sent": ["source_id"],
        },
        "source_collection_status": "PARTIAL",
        "advisory": None,
        "reason": None,
        "logical_call_id": None,
    }
    ref = package["source_references"][0]
    package["package_key"] = _digest(
        {
            "schema_version": package["schema_version"],
            "evidence_id": ref["evidence_id"],
            "evidence_hash": ref["evidence_hash"],
            "observation_id": ref["observation_id"],
            "project_id": None,
            "project_identity_key": None,
            "need_id": None,
            "extractor_version": package["extractor_version"],
            "question_contract": package["question_contract"],
            "provider": package["provider"],
            "model": package["model"],
        }
    )
    return package


def test_valid_package_requires_matching_evidence_citation():
    validate_package(
        valid_package(), evidence_fields={"title": "Applicant: ACME Builders", "abstract": ""}
    )


@pytest.mark.parametrize(
    "change",
    [
        lambda item: item["facts"][0]["citation"].update(evidence_hash="b" * 64),
        lambda item: item["facts"][0]["citation"]["excerpt_location"].update(start=-1),
        lambda item: item["facts"][0]["citation"]["excerpt_location"].update(end=11),
        lambda item: item.update(processing_status="SUCCESS"),
        lambda item: item["facts"][0].update(value="unsupported claim"),
        lambda item: item.pop("missing_fields"),
        lambda item: item.update(document_coverage="FULL_RETAINED_DOCUMENT"),
        lambda item: item.update(package_key="f" * 64),
        lambda item: item["entity_candidates"].append(
            {
                "value": "Unsupported Buyer",
                "unit": None,
                "label": "REPORTED",
                "role": "buyer",
                "extractor_basis": "unsupported role",
                "citation": item["facts"][0]["citation"],
            }
        ),
    ],
)
def test_invalid_package_citation_or_status_is_rejected(change):
    package = valid_package()
    change(package)
    with pytest.raises(ValueError):
        validate_package(
            package, evidence_fields={"title": "Applicant: ACME Builders", "abstract": ""}
        )
