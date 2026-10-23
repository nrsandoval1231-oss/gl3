import hashlib
from datetime import UTC, datetime

import pytest

from gridlens.ingestion.compare_acquisition import (
    compare_case,
    recover_facts,
    report_complete,
    validate_capture,
)


def case(media_type="text/html"):
    return {
        "case_id": "one",
        "source_id": "source",
        "external_id": "42",
        "url": "https://example.gov/record",
        "media_type": media_type,
        "identity_kind": "native_record_id",
        "max_bytes": 2000000,
        "recovery_terms": ["Permit 42", "MW"],
    }


def capture(text="Permit 42 approved\nMW unknown"):
    digest = hashlib.sha256(text.encode()).hexdigest()
    return {
        "case_id": "one",
        "source_id": "source",
        "external_id": "42",
        "capture_id": "adapter-capture-1",
        "capture_hash": digest,
        "capture_kind": "RECORD_EXCERPT",
        "evidence_id": "12345678-1234-4234-8234-123456789abc",
        "evidence_content_hash": "a" * 64,
        "url": "https://example.gov/record",
        "content_type": "text/html",
        "title": "Record",
        "text": text,
        "observed_at": datetime.now(UTC).isoformat(),
        "content_hash": digest,
    }


def test_capture_preserves_evidence_and_capture_hashes_separately_and_recovers_only_text():
    row = compare_case(case(), capture())
    native = row["native"]
    assert native["evidence_content_hash"] == "a" * 64
    assert native["capture_hash"] == native["content_hash"]
    assert native["capture_kind"] == "RECORD_EXCERPT"
    assert native["field_recovery"] == {"Permit 42": ["Permit 42 approved"], "MW": ["MW unknown"]}


@pytest.mark.parametrize(
    "change",
    [
        {"url": "https://example.gov/other"},
        {"capture_hash": "0" * 64},
        {"text": ""},
        {"observed_at": "2026-10-23T12:00:00"},
        {"capture_kind": "TRUNCATED"},
    ],
)
def test_capture_rejects_identity_hash_completeness_and_timestamp_violations(change):
    payload = capture()
    payload.update(change)
    with pytest.raises(ValueError):
        validate_capture(case(), payload)


def test_capture_media_type_must_match_manifest():
    payload = capture()
    payload["content_type"] = "application/pdf"
    with pytest.raises(ValueError, match="media type"):
        validate_capture(case("text/html; charset=utf-8"), payload)


def test_pdf_or_csv_capture_is_not_needed_for_firecrawl():
    payload = capture()
    payload["content_type"] = "text/csv"
    row = compare_case(case("text/csv"), payload)
    assert row["firecrawl"]["status"] == "NOT_NEEDED"


def test_incomplete_five_case_report_never_passes():
    row = compare_case(case(), capture(), firecrawl={"status": "UNKNOWN"})
    assert not report_complete([row])
    rows = [compare_case(case(), capture(), firecrawl={"status": "COMPLETED"})]
    rows.extend(
        {"case_id": str(i), "native": {"status": "INCOMPLETE"}, "firecrawl": {"status": "NOT_RUN"}}
        for i in range(4)
    )
    assert not report_complete(rows)


def test_fact_recovery_requires_literal_values_and_reports_unverified_transform():
    result = recover_facts(
        "Permit 42 received 10/23/2026",
        {"permit": "Permit 42", "received": "2026-10-23"},
        ["permit", "received"],
    )
    assert result["status"] == "EVALUATED"
    assert result["matches"] == 1
    assert result["denominator"] == 2
    assert [item["status"] for item in result["facts"]] == ["MATCH", "UNVERIFIED"]
