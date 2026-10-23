import pytest

from gridlens.integrations.intelligence_provider import commercial_assessment_request_payload
from gridlens.intelligence.commercial_assessment import (
    ASSESSMENT_SCHEMA,
    digest,
    validate_assessment,
)


def fixture():
    package = {
        "package_key": "a" * 64,
        "processing_status": "COMPLETE_ADVISORY",
        "project_id": "project-1",
        "need_id": "need-1",
        "document_coverage": "RECORD_EXCERPT",
        "source_collection_status": "PARTIAL",
        "source_references": [{"evidence_id": "evidence-1", "evidence_hash": "b" * 64}],
        "facts": [
            {
                "field": "application_stage",
                "value": "Permit application",
                "label": "REPORTED",
                "citation": {
                    "evidence_id": "evidence-1",
                    "evidence_hash": "b" * 64,
                    "excerpt_location": {"field": "abstract", "start": 0, "end": 18},
                },
            }
        ],
    }
    result = {
        "disposition": "UNRESOLVED",
        "reason_code": "EXCERPT_INSUFFICIENT",
        "selected_fact_ids": [],
        "research_dimensions": [
            "REQUIRED_MW",
            "START_WINDOW",
            "BUYER_AUTHORITY",
            "SUPPLY_GAP",
            "DURATION",
            "RENTAL_VS_PERMANENT",
        ],
        "next_question_id": "TEMP_LOAD_MW",
    }
    return package, result


def test_valid_assessment_is_advisory_and_digest_deterministic():
    package, answer = fixture()
    first = validate_assessment(answer, package=package, need_id="need-1", project_id="project-1")
    second = validate_assessment(answer, package=package, need_id="need-1", project_id="project-1")
    assert first["authority"] == "ADVISORY_ONLY"
    assert first["request_digest"] == second["request_digest"]
    assert first["result_digest"] == digest(
        {k: v for k, v in first.items() if k != "result_digest"}
    )
    assert ASSESSMENT_SCHEMA["properties"]["disposition"]["enum"] == [
        "INVESTIGATE",
        "NOT_SUPPORTED",
        "UNRESOLVED",
    ]


def test_rejects_wrong_need_or_unresolved_fact_reference():
    package, answer = fixture()
    try:
        validate_assessment(answer, package=package, need_id="other", project_id="project-1")
    except ValueError as exc:
        assert str(exc) == "PACKAGE_IDENTITY_MISMATCH"
    else:
        raise AssertionError("wrong need accepted")
    answer["selected_fact_ids"] = ["invented"]
    try:
        validate_assessment(answer, package=package, need_id="need-1", project_id="project-1")
    except ValueError as exc:
        assert str(exc) == "FACT_REFERENCE_INVALID"
    else:
        raise AssertionError("invented fact accepted")


def test_package_completion_is_not_full_document_coverage():
    package, answer = fixture()
    result = validate_assessment(answer, package=package, need_id="need-1", project_id="project-1")
    assert package["document_coverage"] == "RECORD_EXCERPT"
    assert package["source_collection_status"] == "PARTIAL"
    assert "BUYER_AUTHORITY" in result["unknown_fields"]


def test_titlecase_unknown_supply_stays_unknown_and_question_is_server_rendered():
    package, answer = fixture()
    result = validate_assessment(
        answer,
        package=package,
        need_id="need-1",
        project_id="project-1",
        current_need={"supply": "Unknown"},
    )
    assert "SUPPLY_GAP" in result["unknown_fields"]
    assert result["next_question_id"] == "TEMP_LOAD_MW"
    assert (
        result["next_question"]
        == "What exact-need evidence establishes temporary electrical load in MW?"
    )


def test_unknown_model_constructed_dimension_is_rejected():
    package, answer = fixture()
    answer["research_dimensions"] = ["INVENTED_FACT"]
    with pytest.raises(ValueError, match="RESEARCH_DIMENSIONS_INVALID"):
        validate_assessment(answer, package=package, need_id="need-1", project_id="project-1")


def test_excerpt_insufficient_reason_requires_unresolved():
    package, answer = fixture()
    answer["disposition"] = "INVESTIGATE"
    answer["reason_code"] = "EXCERPT_INSUFFICIENT"
    with pytest.raises(ValueError, match="PARTIAL_EVIDENCE_MUST_REMAIN_UNRESOLVED"):
        validate_assessment(answer, package=package, need_id="need-1", project_id="project-1")


def test_request_pins_m4_controls_and_separate_schema():
    request = commercial_assessment_request_payload(
        model="gpt-6.1-sol", input_payload={"bounded": True}, schema=ASSESSMENT_SCHEMA
    )
    assert request["service_tier"] == "default"
    assert request["reasoning"] == {"effort": "medium"}
    assert request["prompt_cache_options"] == {"ttl": "30m"}
    assert request["max_output_tokens"] == 6000
    assert request["store"] is False and request["tools"] == []
    assert request["text"]["format"]["name"] == "commercial_assessment_v1"
    with pytest.raises(ValueError, match="pinned model"):
        commercial_assessment_request_payload(
            model="other", input_payload={}, schema=ASSESSMENT_SCHEMA
        )
