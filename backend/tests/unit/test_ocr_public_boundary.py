from types import SimpleNamespace
from uuid import uuid4

from gridlens.api.app import EvidenceOut
from gridlens.ingestion.adapters.govinfo_scan import CAPTURE_KEY
from gridlens.intelligence.ocr_transcript import (
    public_ocr_grounded_result,
    public_ocr_transcript,
)
from gridlens.intelligence.project_state import _provenance


def test_public_evidence_projection_never_serializes_private_pdf_capture():
    marker = "PRIVATE_CAPTURE_BASE64_SHOULD_NEVER_BE_PUBLIC"
    evidence = SimpleNamespace(
        id=uuid4(),
        url="https://www.govinfo.gov/content/pkg/FR-2026-09-14/pdf/2026-18765.pdf",
        extraction_location="GovInfo PDF page 1",
        event_date=None,
        published_at=None,
        observed_at=None,
        provenance={CAPTURE_KEY: {"data_base64": marker}},
    )

    projected = _provenance(evidence)

    assert set(projected) == {
        "id",
        "url",
        "extraction_location",
        "source_date",
        "retrieved_at",
        "support",
    }
    assert marker not in str(projected)
    assert "provenance" not in EvidenceOut.model_fields


def test_evidence_api_model_drops_unmodeled_provenance_capture():
    marker = "PRIVATE_CAPTURE_BASE64_SHOULD_NEVER_BE_PUBLIC"
    evidence = EvidenceOut.model_validate(
        {
            "id": uuid4(),
            "title": "Federal Register notice",
            "abstract": "A source excerpt.",
            "url": "https://www.govinfo.gov/content/pkg/FR-2026-09-14/pdf/2026-18765.pdf",
            "published_at": None,
            "retrieved_at": "2026-10-18T00:00:00Z",
            "extraction_location": "GovInfo PDF page 1",
            "content_hash": "a" * 64,
            "event_date": None,
            "event_date_label": "",
            "source_id": "fixture-source",
            "document_number": "2026-18765",
            "provenance": {CAPTURE_KEY: {"data_base64": marker}},
        }
    )
    assert marker not in str(evidence.model_dump(mode="json"))
    assert "provenance" not in evidence.model_dump(mode="json")


def test_public_ocr_history_allows_text_but_rejects_capture_bytes():
    result = {
        "schema_version": "scanned-pdf-transcript-v1",
        "status": "OCR_UNVERIFIED",
        "authority": "ADVISORY_ONLY",
        "evidence_id": str(uuid4()),
        "original_document_hash": "a" * 64,
        "source_url": "https://www.govinfo.gov/content/pkg/FR-2026-09-14/pdf/2026-18765.pdf",
        "page_count": 1,
        "pages": [{"page": 1, "text": "Public transcript words."}],
        "transcript_hash": "b" * 64,
        "method": "OpenAI Responses inline PDF input",
        "version": "scanned-pdf-transcript-v1",
        "actual_model": "configured-test-model",
        "provider_response_id": "resp_test",
        "logical_call_id": str(uuid4()),
        "preflight_counted_input_tokens": 42,
        "usage": {
            "input_tokens": 42,
            "output_tokens": 8,
            "counted_input_tokens_are_billable_usage": False,
            "actual_cost_usd": None,
            "data_base64": "PRIVATE_CAPTURE_BASE64_SHOULD_NEVER_BE_PUBLIC",
        },
        CAPTURE_KEY: {"data_base64": "PRIVATE_CAPTURE_BASE64_SHOULD_NEVER_BE_PUBLIC"},
    }

    assert public_ocr_transcript(result) is None
    result.pop(CAPTURE_KEY)
    safe = public_ocr_transcript(result)
    assert safe is not None
    assert safe["pages"] == [{"page": 1, "text": "Public transcript words."}]
    assert "data_base64" not in safe["usage"]


def test_public_grounded_ocr_result_keeps_unverified_status_and_strips_capture():
    result = {
        "schema_version": "grounded-candidates-v2",
        "status": "OCR_UNVERIFIED",
        "authority": "ADVISORY_ONLY",
        "canonical_promotion": "PROHIBITED",
        "independent_source_check": "REQUIRED",
        "candidates": [
            {
                "field": "construction_start",
                "value": "2026",
                "unit": None,
                "original_value": None,
                "original_unit": None,
                "precision": None,
                "date_precision": "year",
                "evidence_id": str(uuid4()),
                "evidence_hash": "a" * 64,
                "quote": "Construction will start in 2026.",
                "section": "abstract",
                "page": 1,
                "span_start": 0,
                "span_end": 32,
                "publisher": "Federal Register",
                "published_date": None,
                "speaker": None,
                "speaker_organization": None,
                "speaker_role": None,
                "support": "direct",
                "status": "candidate",
                "verification_status": "OCR_UNVERIFIED",
                CAPTURE_KEY: {"data_base64": "PRIVATE_CAPTURE_BASE64_SHOULD_NEVER_BE_PUBLIC"},
            }
        ],
        "hypotheses": [],
        "contradictions": [],
        "unresolved_questions": [],
        "candidate_orgs": [],
        "proposed_queries": [],
        "suggested_pursuit": None,
        "ocr_transcript_reference": {
            "logical_call_id": str(uuid4()),
            "transcript_hash": "b" * 64,
            "version": "scanned-pdf-transcript-v1",
        },
        "usage": {
            "input_tokens": 4,
            "output_tokens": 5,
            "counted_input_tokens_are_billable_usage": False,
            "actual_cost_usd": None,
            "capture": "PRIVATE_CAPTURE_BASE64_SHOULD_NEVER_BE_PUBLIC",
        },
        CAPTURE_KEY: {"data_base64": "PRIVATE_CAPTURE_BASE64_SHOULD_NEVER_BE_PUBLIC"},
    }

    safe = public_ocr_grounded_result(result)

    assert safe is not None
    assert safe["status"] == "OCR_UNVERIFIED"
    assert safe["canonical_promotion"] == "PROHIBITED"
    assert safe["candidates"][0]["verification_status"] == "OCR_UNVERIFIED"
    assert "govinfo_ocr_capture_v1" not in str(safe)
    assert "PRIVATE_CAPTURE_BASE64_SHOULD_NEVER_BE_PUBLIC" not in str(safe)
