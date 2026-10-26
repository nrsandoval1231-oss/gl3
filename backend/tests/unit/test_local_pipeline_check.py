import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.local_pipeline_check import (  # noqa: E402
    _digest_rows,
    _ensure_output_available,
    _morning_changes,
    _replays_unchanged,
)


def _successful_job(source_id: str) -> dict:
    return {
        "source_id": source_id,
        "attempted": True,
        "job_status": "succeeded",
        "failed_jobs": 0,
        "failed_interpretations": 0,
        "pending_interpretations": 0,
    }


def test_interpretation_retry_bookkeeping_changes_operational_but_not_content_digest():
    before = {
        "id": 4,
        "observation_id": "obs-1",
        "content_hash": "a" * 64,
        "assessment": {"decision": "accepted", "tier": "Signal"},
        "status": "accepted",
        "attempts": 2,
        "updated_at": "2026-09-28T00:00:00+00:00",
    }
    after = {
        **before,
        "attempts": 3,
        "updated_at": "2026-09-28T00:01:00+00:00",
    }

    before_hashes = _digest_rows("interpretations", [before])
    after_hashes = _digest_rows("interpretations", [after])

    assert before_hashes["sha256"] == after_hashes["sha256"]
    assert before_hashes["operational_sha256"] != after_hashes["operational_sha256"]
    changed_assessment = {**after, "assessment": {"decision": "rejected"}}
    assert _digest_rows("interpretations", [changed_assessment])["sha256"] != after_hashes["sha256"]


def test_replay_gate_requires_successful_initial_and_replay_jobs_and_stable_evidence():
    initial = [_successful_job("source-1")]
    replay = [
        {
            **_successful_job("source-1"),
            "content_digest_unchanged": True,
            "counts_unchanged": True,
            "morning_changes_before": {"sha256": "same"},
            "morning_changes_after": {"sha256": "same"},
            "operational_digest_unchanged": False,
        }
    ]
    assert _replays_unchanged(initial, replay)
    assert not _replays_unchanged([{**initial[0], "failed_jobs": 1}], replay)
    assert not _replays_unchanged(initial, [{**replay[0], "content_digest_unchanged": False}])
    assert not _replays_unchanged(initial, [{**replay[0], "pending_interpretations": 1}])
    assert not _replays_unchanged([{**initial[0], "failed_interpretations": 1}], replay)


def test_receipt_path_cannot_overwrite_prior_evidence(tmp_path):
    receipt = tmp_path / "receipt.json"
    receipt.write_text("preserved", encoding="utf-8")

    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        _ensure_output_available(receipt)

    assert receipt.read_text(encoding="utf-8") == "preserved"


def test_live_changes_receipt_serializes_database_identity_and_dates(monkeypatch):
    from gridlens.api import app

    identity = UUID("12345678-1234-5678-1234-567812345678")
    observed = datetime(2026, 10, 26, tzinfo=UTC)
    monkeypatch.setattr(app, "changes", lambda: [{"project_id": identity, "at": observed}])
    first = _morning_changes()
    assert first["items"] == [{"project_id": str(identity), "at": observed.isoformat()}]
    assert first["count"] == 1
    assert _morning_changes()["sha256"] == first["sha256"]
