import json
from datetime import UTC, datetime
from importlib import import_module

from fastapi.testclient import TestClient
from sqlalchemy import select
from test_intelligence_worker_integration import (
    _enable_bounded_typesafe,
    _seed_job,
    _wire_worker,
)

from gridlens.intelligence import intelligence_jobs
from gridlens.intelligence.intelligence_jobs import enqueue_intelligence, intelligence_history
from gridlens.persistence.models import Job, LogicalCall
from gridlens.security import token_for

pytest_plugins = ("test_intelligence_worker_integration",)


def _run(sessions, monkeypatch, response=None, error=None):
    _enable_bounded_typesafe(monkeypatch)
    need_id, _evidence_id, job_id = _seed_job(sessions)
    worker = _wire_worker(sessions, monkeypatch)
    monkeypatch.setattr(worker, "WORKER_ID", "receipt-fixture-worker")
    calls = []

    def provider(**_kwargs):
        calls.append(True)
        if error:
            raise error
        return response or {
            "model": "pinned-fixture-model",
            "provider_response_id": "resp-receipt-fixture",
            "usage": {"input_tokens": 12, "output_tokens": 3},
            "answers": {
                "answer": {
                    "type": "choice",
                    "choice": "RELEVANT",
                    "confidence": 1.0,
                    "probabilities": {"RELEVANT": 1.0, "IRRELEVANT": 0.0, "UNCERTAIN": 0.0},
                }
            },
        }

    monkeypatch.setattr(intelligence_jobs, "call_typesafe", provider)
    assert worker.run_one({}, job_ids=[job_id]) is True
    return need_id, job_id, calls


def test_success_missing_id_and_history_expose_truthful_receipts(sessions, monkeypatch):
    need_id, job_id, calls = _run(sessions, monkeypatch)
    assert calls == [True]
    with sessions() as session:
        job = session.get(Job, job_id)
        checkpoint = json.loads(job.checkpoint)
        history = intelligence_history(session, need_id)
    assert checkpoint["validation_outcome"] == "VALIDATED"
    assert checkpoint["provider_response_id"] == "resp-receipt-fixture"
    assert checkpoint["result"]["provider_response_id"] == "resp-receipt-fixture"
    assert history[0]["validation_outcome"] == "VALIDATED"
    assert history[0]["provider_response_id"] == "resp-receipt-fixture"


def test_missing_provider_id_is_not_invented(sessions, monkeypatch):
    no_id_response = {
        "model": "pinned-fixture-model",
        "usage": {"input_tokens": 12, "output_tokens": 3},
        "answers": {
            "answer": {
                "type": "choice",
                "choice": "RELEVANT",
                "confidence": 1.0,
                "probabilities": {"RELEVANT": 1.0, "IRRELEVANT": 0.0, "UNCERTAIN": 0.0},
            }
        },
    }
    need_id2, job_id2, calls2 = _run(sessions, monkeypatch, response=no_id_response)
    assert calls2 == [True]
    with sessions() as session:
        checkpoint2 = json.loads(session.get(Job, job_id2).checkpoint)
        history2 = intelligence_history(session, need_id2)
    assert checkpoint2["validation_outcome"] == "VALIDATED"
    assert checkpoint2["provider_response_id"] is None
    assert "provider_response_id" not in checkpoint2["result"]
    assert history2[0]["provider_response_id"] is None


def test_invalid_response_receipt_preserves_rejection_reason(sessions, monkeypatch):
    invalid = {
        "model": "pinned-fixture-model",
        "provider_response_id": "resp-invalid-fixture",
        "usage": {"input_tokens": 12, "output_tokens": 3},
        "answers": {"answer": {"type": "choice", "choice": "NOT_ALLOWED"}},
    }
    need_id, job_id, _calls = _run(sessions, monkeypatch, response=invalid)
    with sessions() as session:
        checkpoint = json.loads(session.get(Job, job_id).checkpoint)
        history = intelligence_history(session, need_id)
    assert checkpoint["validation_outcome"] == "REJECTED"
    assert checkpoint["validation_reason"] == "ValueError"
    assert checkpoint["provider_response_id"] == "resp-invalid-fixture"
    assert history[0]["validation_outcome"] == "REJECTED"


def test_quarantine_receipt_preserves_reason_and_provider_id(sessions, monkeypatch):
    mismatch = {
        "model": "unexpected-model",
        "provider_response_id": "resp-quarantined-fixture",
        "usage": {"input_tokens": 12, "output_tokens": 3},
    }
    need_id2, job_id2, _calls2 = _run(sessions, monkeypatch, response=mismatch)
    with sessions() as session:
        checkpoint2 = json.loads(session.get(Job, job_id2).checkpoint)
        call = session.scalar(select(LogicalCall).where(LogicalCall.job_id == job_id2))
        history2 = intelligence_history(session, need_id2)
    assert call and call.status == "SENT_OUTCOME_UNKNOWN"
    assert checkpoint2["validation_outcome"] == "QUARANTINED"
    assert checkpoint2["validation_reason"] == "MODEL_IDENTITY_MISMATCH"
    assert checkpoint2["provider_response_id"] == "resp-quarantined-fixture"
    assert checkpoint2["result"]["validation_outcome"] == "QUARANTINED"
    assert checkpoint2["result"]["provider_response_id"] == "resp-quarantined-fixture"
    assert history2[0]["validation_reason"] == "MODEL_IDENTITY_MISMATCH"


def test_unknown_interruption_is_unconfirmed(sessions, monkeypatch):
    need_id, job_id, calls = _run(sessions, monkeypatch, error=RuntimeError("interrupted"))
    assert calls == [True]
    with sessions() as session:
        checkpoint = json.loads(session.get(Job, job_id).checkpoint)
        assert intelligence_history(session, need_id)[0]["validation_outcome"] == "UNKNOWN"
    assert checkpoint["validation_outcome"] == "UNKNOWN"


def test_cached_replay_inherits_original_success_receipt(sessions, monkeypatch):
    need_id, job_id, calls = _run(sessions, monkeypatch)
    assert calls == [True]
    with sessions.begin() as session:
        original_checkpoint = json.loads(session.get(Job, job_id).checkpoint)
        replay = enqueue_intelligence(session, need_id=need_id, task_type="SOURCE_RELEVANCE_V1")
        replay_id = replay.id
    worker = _wire_worker(sessions, monkeypatch)
    monkeypatch.setattr(worker, "WORKER_ID", "receipt-cached-worker")
    assert worker.run_one({}, job_ids=[replay_id]) is True
    assert calls == [True]
    with sessions() as session:
        cached = json.loads(session.get(Job, replay_id).checkpoint)
    assert original_checkpoint["validation_outcome"] == "VALIDATED"
    assert cached["validation_outcome"] == "VALIDATED"
    assert cached["provider_response_id"] == original_checkpoint["provider_response_id"]
    assert cached["cached"] is True


def test_old_receipt_and_get_do_not_call_provider(sessions, monkeypatch):
    need_id, job_id, _calls = _run(sessions, monkeypatch)

    legacy_id = __import__("uuid").uuid4()
    with sessions.begin() as session:
        original = session.get(Job, job_id)
        session.add(
            Job(
                id=legacy_id,
                source_id=original.source_id,
                kind=original.kind,
                target_id=original.target_id,
                status="succeeded",
                checkpoint=json.dumps({"status": "completed", "result": {"answer": "old"}}),
                created_at=datetime.now(UTC),
            )
        )
        old_need_id = original.target_id

    api = import_module("gridlens.api.app")
    monkeypatch.setattr(api, "SessionLocal", sessions)

    def unexpected_provider_call(**_kwargs):
        raise AssertionError("GET called provider")

    monkeypatch.setattr(intelligence_jobs, "call_typesafe", unexpected_provider_call)
    client = TestClient(api.app, base_url="https://testserver")
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    response = client.get(f"/api/intelligence/needs/{old_need_id}/history")
    assert response.status_code == 200, response.text
    old = next(item for item in response.json()["items"] if item["job_id"] == str(legacy_id))
    assert old["validation_outcome"] == "UNKNOWN"
    assert old["provider_response_id"] is None
