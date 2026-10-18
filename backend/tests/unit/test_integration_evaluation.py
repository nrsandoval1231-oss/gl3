from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from gridlens.intelligence.integration_evaluation import (
    ROUTES,
    evaluate,
    freeze_sample,
    validate_operational_receipts,
    verify_frozen_sample,
)


def sample(tmp_path: Path):
    manifest = freeze_sample(
        {
            "cases": [
                {"case_id": "a", "evidence": "source A"},
                {"case_id": "b", "evidence": "source B"},
            ]
        },
        tmp_path / "sample.json",
    )
    labels = {
        "provenance": {
            "author": "independent reviewer",
            "method": "evidence review",
            "created_at": "2026-10-18",
        },
        "labels": [
            {
                "case_id": "a",
                "relevant": "YES",
                "safe_to_merge": "NO",
                "safe_to_promote": "NO",
                "question_expected": True,
            },
            {
                "case_id": "b",
                "relevant": "NO",
                "safe_to_merge": "YES",
                "safe_to_promote": "YES",
                "question_expected": False,
            },
        ],
    }
    pred = {
        "sample_sha256": manifest["sample_sha256"],
        "routes": {
            route: {
                "predictions": [
                    {
                        "case_id": "a",
                        "relevant": "UNKNOWN",
                        "merge_proposed": True,
                        "promotion_proposed": True,
                        "fabricated_claim": True,
                        "latency_ms": 100,
                        "cost": {"status": "UNKNOWN"},
                        "question_resolved": False,
                    },
                    {
                        "case_id": "b",
                        "relevant": "NO",
                        "merge_proposed": False,
                        "promotion_proposed": False,
                        "fabricated_claim": False,
                        "latency_ms": 200,
                        "cost": {"status": "KNOWN", "amount": 0.1},
                        "question_resolved": False,
                    },
                ]
            }
            for route in ROUTES
        },
    }
    return manifest, labels, pred


def test_frozen_evidence_detects_tampering_and_rejects_embedded_labels(tmp_path):
    with pytest.raises(ValueError, match="labels must be authored separately"):
        freeze_sample(
            {"cases": [{"case_id": "x", "labels": {"relevant": "YES"}}]}, tmp_path / "bad.json"
        )
    manifest = freeze_sample(
        {"cases": [{"case_id": "x", "evidence": "retained"}]}, tmp_path / "frozen.json"
    )
    assert verify_frozen_sample(manifest) == []
    manifest["cases"][0]["evidence"] = "changed"
    assert "frozen evidence hash mismatch" in verify_frozen_sample(manifest)


def test_four_route_report_preserves_missing_unknown_and_costs(tmp_path):
    manifest, labels, pred = sample(tmp_path)
    pred["routes"]["rules_fast_extract"]["predictions"].pop()
    result = evaluate(manifest, labels, pred)
    assert result["status"] == "PROPOSED"
    assert result["gates"] == {
        "proposed": True,
        "accepted": False,
        "acceptance_requires_independent_review": True,
    }
    assert result["routes"]["rules"]["relevance"]["recall"] == 0.0
    assert result["routes"]["rules"]["relevance"]["unknown_predictions"] == 1
    assert result["routes"]["rules"]["unsafe_merges"]["count"] == 1
    assert result["routes"]["rules"]["unsafe_promotions"]["count"] == 1
    assert result["routes"]["rules"]["fabricated_claims"]["count"] == 1
    assert result["routes"]["rules"]["latency_ms"] == {"p50": 100.0, "p95": 200.0, "known": 2}
    assert result["routes"]["rules"]["cost"]["known"] == "UNKNOWN"
    assert result["routes"]["rules"]["resolved_question_yield"]["value"] == 0.0
    assert result["routes"]["rules_fast_extract"]["missing_predictions"] == ["b"]
    assert result["routes"]["rules_fast_extract"]["relevance"]["recall"] == 0.0


def test_report_rejects_wrong_sample_route_set_and_missing_independent_label(tmp_path):
    manifest, labels, pred = sample(tmp_path)
    labels["labels"].pop()
    pred["sample_sha256"] = "0" * 64
    pred["routes"].pop("rules_jev_extract_deep")
    result = evaluate(manifest, labels, pred)
    assert result["status"] == "INVALID"
    assert any("missing independent label" in error for error in result["errors"])
    assert any("exactly four" in error for error in result["errors"])
    assert any("sample hash" in error for error in result["errors"])


def test_unrun_route_reports_unknown_not_zero_economics(tmp_path):
    manifest, labels, pred = sample(tmp_path)
    pred["routes"]["rules_jev_advisory"]["predictions"] = []
    result = evaluate(manifest, labels, pred)["routes"]["rules_jev_advisory"]
    assert result["run_state"] == "NOT_RUN"
    assert result["fabricated_claims"] == "UNKNOWN"
    assert result["latency_ms"]["p50"] == "UNKNOWN"
    assert result["cost"] == {
        "known": "UNKNOWN",
        "known_subtotal": "UNKNOWN",
        "uncertain": "UNKNOWN",
        "reserved": "UNKNOWN",
    }


def receipts():
    tz = ZoneInfo("America/Chicago")
    rows = []
    for offset in range(7):
        scheduled = datetime(2026, 10, 12 + offset, 7, 0, tzinfo=tz)
        rows.append(
            {
                "cycle_id": f"cycle-{offset}",
                "scheduled_at": scheduled.isoformat(),
                "started_at": (scheduled + timedelta(minutes=2)).isoformat(),
                "completed_at": (scheduled + timedelta(minutes=15)).isoformat(),
                "source_due": [{"source_id": "feed-1", "status": "SUCCESS"}],
                "evidence": {
                    kind: {"reference": f"vault/{kind}-{offset}", "sha256": str(offset).zfill(64)}
                    for kind in ("pc_off", "runtime")
                },
            }
        )
    return {
        "schedule": {"timezone": "America/Chicago", "time": "07:00"},
        "evidence": {
            kind: {"reference": f"campaign/{kind}", "sha256": "f" * 64}
            for kind in ("backup", "restore", "owner_review")
        },
        "receipts": rows,
    }


def test_seven_real_local_dates_are_structural_only_and_require_evidence_refs():
    result = validate_operational_receipts(receipts(), now=datetime(2026, 10, 19, 12, tzinfo=UTC))
    assert result["status"] == "STRUCTURALLY_VALID"
    assert result["live_proof"] == "UNKNOWN"
    assert result["authenticity"] == "REQUIRES_EXTERNAL_VERIFICATION"
    bad = receipts()
    bad["receipts"][3]["evidence"] = {"pc_off": True}
    assert (
        validate_operational_receipts(bad, now=datetime(2026, 10, 19, 12, tzinfo=UTC))["status"]
        == "INVALID"
    )


def test_receipts_reject_accelerated_duplicate_days_and_invalid_bounds():
    doc = receipts()
    doc["receipts"][1]["scheduled_at"] = doc["receipts"][0]["scheduled_at"]
    doc["receipts"][2]["completed_at"] = doc["receipts"][2]["started_at"]
    doc["receipts"][2]["started_at"] = (
        datetime.fromisoformat(doc["receipts"][2]["started_at"]) + timedelta(minutes=1)
    ).isoformat()
    result = validate_operational_receipts(doc, now=datetime(2026, 10, 19, 12, tzinfo=UTC))
    assert result["status"] == "INVALID"
    assert any(
        "distinct consecutive" in error or "duplicate" in error for error in result["errors"]
    )
    assert any("execution time bounds" in error for error in result["errors"])


def test_operational_gate_checks_ninety_five_percent_and_two_miss_alerts():
    doc = receipts()
    doc["receipts"][2]["source_due"] = [{"source_id": "feed-1", "status": "FAILED"}]
    doc["receipts"][3]["source_due"] = [{"source_id": "feed-1", "status": "FAILED"}]
    result = validate_operational_receipts(doc, now=datetime(2026, 10, 19, 12, tzinfo=UTC))
    assert result["status"] == "INVALID"
    assert any("95%" in error for error in result["errors"])
    assert any("without visible alert" in error for error in result["errors"])
    doc["receipts"][3]["alerts"] = [
        {"source_id": "feed-1", "visible": True, "reference": "alerts/notice", "sha256": "a" * 64}
    ]
    result = validate_operational_receipts(doc, now=datetime(2026, 10, 19, 12, tzinfo=UTC))
    assert not any("without visible alert" in error for error in result["errors"])


def test_configured_schedule_campaign_evidence_and_duplicate_due_sources():
    doc = receipts()
    doc["schedule"] = {"timezone": "America/Denver", "time": "06:00"}
    assert (
        validate_operational_receipts(doc, now=datetime(2026, 10, 19, 12, tzinfo=UTC))["status"]
        == "STRUCTURALLY_VALID"
    )
    doc["evidence"].pop("restore")
    result = validate_operational_receipts(doc, now=datetime(2026, 10, 19, 12, tzinfo=UTC))
    assert any("campaign-level restore" in error for error in result["errors"])
    doc = receipts()
    doc["receipts"][0]["source_due"].append({"source_id": "feed-1", "status": "SUCCESS"})
    result = validate_operational_receipts(doc, now=datetime(2026, 10, 19, 12, tzinfo=UTC))
    assert any("duplicate source_id" in error for error in result["errors"])
    assert result["due_source_success_rate"] == "UNKNOWN"


def test_operational_receipts_reject_future_cycle_timestamps():
    doc = receipts()
    result = validate_operational_receipts(doc, now=datetime(2026, 10, 18, 11, 30, tzinfo=UTC))
    assert any("future receipt timestamps" in error for error in result["errors"])
