from uuid import uuid4

import pytest

from gridlens.intelligence.ocr_transcript import validate_ocr_transcript


def _validate(pages):
    return validate_ocr_transcript(
        {"pages": pages},
        expected_pages=2,
        evidence_id=uuid4(),
        original_document_hash="a" * 64,
        source_url="https://www.govinfo.gov/content/pkg/FR-2026-09-14/pdf/2026-18765.pdf",
        logical_call_id=uuid4(),
        actual_model="configured-test-model",
        provider_response_id="resp_test",
    )


def test_page_indexed_transcript_keeps_unverified_and_call_linkage():
    result = _validate([{"page": 1, "text": "First scanned page."}, {"page": 2, "text": ""}])
    assert result["status"] == "OCR_UNVERIFIED"
    assert result["authority"] == "ADVISORY_ONLY"
    assert result["page_count"] == 2
    assert result["logical_call_id"]
    assert result["original_document_hash"] == "a" * 64
    assert len(result["transcript_hash"]) == 64


@pytest.mark.parametrize(
    "pages",
    [
        [{"page": 1, "text": "First page."}],
        [{"page": 1, "text": "First page."}, {"page": 1, "text": "Duplicate."}],
        [{"page": 2, "text": "Out of order."}, {"page": 1, "text": "Wrong."}],
        [{"page": 1, "text": "First page.", "extra": True}, {"page": 2, "text": "Second."}],
    ],
)
def test_rejects_missing_duplicate_out_of_order_or_extra_pages(pages):
    with pytest.raises(ValueError):
        _validate(pages)


def test_oversized_transcript_is_rejected_without_truncation():
    with pytest.raises(ValueError, match="durable result limit"):
        _validate([{"page": 1, "text": "x" * 40_000}, {"page": 2, "text": "y" * 40_000}])
