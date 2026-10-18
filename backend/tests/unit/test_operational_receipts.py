import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from gridlens.intelligence.operational_receipts import load_operational_receipt


def test_missing_receipt_is_unknown():
    assert load_operational_receipt("")["restore"] == "UNKNOWN"


def test_receipt_reports_backup_and_only_attributable_restore(tmp_path):
    path = tmp_path / "receipt.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "recorded_at": datetime.now(UTC).isoformat(),
                "backup_reference": "s3://bucket/object",
            }
        )
    )
    result = load_operational_receipt(str(path))
    assert result["backup"] == "REPORTED"
    assert result["restore"] == "UNKNOWN"
    assert result["authenticity"] == "UNVERIFIED"

    payload = json.loads(path.read_text())
    payload["restore_comparison"] = {"result": "MATCH", "reference": "restore-run-1"}
    path.write_text(json.dumps(payload))
    assert load_operational_receipt(str(path))["restore"] == "UNKNOWN"

    digest = "a" * 64
    payload["restore_comparison"] = {
        "result": "MATCH",
        "reference": "restore-run-1",
        "before_digest": digest,
        "after_digest": digest,
        "tool_version": "1.0",
        "compared_at": datetime.now(UTC).isoformat(),
    }
    path.write_text(json.dumps(payload))
    result = load_operational_receipt(str(path))
    assert result["restore"] == "REPORTED_MATCH"
    assert result["last_verified_restore_at"] is None


def test_malformed_future_and_oversized_receipts_are_unknown(tmp_path):
    path = tmp_path / "receipt.json"
    path.write_text("not json")
    assert load_operational_receipt(str(path))["status"] == "UNKNOWN"
    path.write_text(
        json.dumps(
            {"version": 1, "recorded_at": (datetime.now(UTC) + timedelta(days=1)).isoformat()}
        )
    )
    assert load_operational_receipt(str(path))["reason"] == "invalid_date"
    path.write_text(" " * 16_385)
    assert load_operational_receipt(str(path))["reason"] == "oversized"


def test_commercial_review_is_reported_and_never_promoted_to_accepted(tmp_path):
    path = tmp_path / "receipt.json"
    payload = {
        "version": 1,
        "recorded_at": datetime.now(UTC).isoformat(),
        "commercial_review": {
            "reviewer": "operator-17",
            "reviewed_at": datetime.now(UTC).isoformat(),
            "sample_sha256": "a" * 64,
            "context_sha256": "b" * 64,
            "cases": [
                {
                    "case_id": "case-01",
                    "need_id": str(uuid4()),
                    "evidence_refs": [{"evidence_id": str(uuid4()), "content_hash": "c" * 64}],
                    "decision": "SUPPORTED",
                }
            ],
        },
    }
    path.write_text(json.dumps(payload))
    result = load_operational_receipt(str(path))["commercial_review"]
    assert result["status"] == "REPORTED"
    assert result["reported_case_count"] == 1
    assert result["decision_counts"]["SUPPORTED"] == 1
    assert result["independent_labels"] == "UNKNOWN"
    assert result["quality_verification"] == "UNVERIFIED"
    assert result["acceptance"] == "UNKNOWN"

    payload["commercial_review"]["cases"][0]["evidence_refs"][0]["quote"] = "private raw text"
    path.write_text(json.dumps(payload))
    assert load_operational_receipt(str(path))["commercial_review"]["status"] == "UNKNOWN"
