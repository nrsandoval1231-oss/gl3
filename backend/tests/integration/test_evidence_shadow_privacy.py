"""Historical unsafe evidence jobs withhold before reserving provider work."""

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from test_evidence_shadow_storage import seed_accepted, shadow_db  # noqa: F401
from test_jev_live_storage import _enable_live_ledger

from gridlens.intelligence.evidence_shadow import run_shadow
from gridlens.persistence.models import (
    Evidence,
    EvidenceJudgeRun,
    Job,
    LogicalCall,
    Observation,
)


def test_queued_historical_contact_evidence_abstains_without_call_or_evidence_mutation(
    shadow_db,  # noqa: F811
    monkeypatch,  # noqa: F811
):
    seed_accepted(shadow_db)
    unsafe_abstract = "Applicant: Jordan Example, jordan@example.com; four chillers planned."
    with shadow_db.begin() as session:
        observation = session.scalar(select(Observation))
        evidence = session.scalar(select(Evidence))
        observation.abstract = evidence.abstract = unsafe_abstract
        evidence_snapshot = (evidence.id, evidence.content_hash, evidence.abstract)

    _enable_live_ledger(monkeypatch, "routing")
    provider_calls = []

    # Queue the exact historical evidence context, then execute it through the real
    # worker and ledger boundary with a transport sentinel that must remain untouched.
    from gridlens.integrations import intelligence_provider
    from gridlens.intelligence.jev_live import accepted_labels

    monkeypatch.setattr(
        intelligence_provider,
        "call_typesafe",
        lambda **kwargs: provider_calls.append(kwargs),
    )
    from test_jev_live_storage import _admit

    _admit(shadow_db)
    with shadow_db() as session:
        queued = run_shadow(session, limit=1)
        assert queued["attempted"] == 1
        job = session.scalar(select(Job).where(Job.kind == "evidence_shadow"))
        assert job is not None
        # The production queue relies on PostgreSQL's server-side default. Set
        # an explicit due time using the lease owner's clock for this fixture.
        job.available_at = datetime.now(UTC) - timedelta(seconds=1)
        queued_id = job.id
        checkpoint = json.loads(job.checkpoint)
        assert "jordan@example.com" in checkpoint["request_context"]["evidence"]["abstract"]
        session.commit()

    with shadow_db() as session:
        job = session.get(Job, queued_id)
        assert job is not None
        assert job.status == "queued" and job.attempts == 0
        assert job.available_at <= datetime.now(UTC)

    from test_intelligence_worker_integration import _wire_worker

    from gridlens.integrations import legacy_calls

    worker = _wire_worker(shadow_db, monkeypatch)
    monkeypatch.setattr(worker, "WORKER_ID", "fixture-privacy-worker")
    monkeypatch.setattr(legacy_calls, "SessionLocal", shadow_db)
    monkeypatch.setattr(
        intelligence_provider,
        "call_typesafe",
        lambda **kwargs: provider_calls.append(kwargs),
    )
    assert worker.run_one({}, job_ids=[queued_id]) is True

    with shadow_db() as session:
        attempt = session.scalar(select(EvidenceJudgeRun))
        job = session.get(Job, queued_id)
        evidence = session.get(Evidence, evidence_snapshot[0])
        observation = session.get(Observation, evidence.observation_id)
        calls = list(session.scalars(select(LogicalCall)))
        assert attempt.status == "failed"
        assert attempt.error_class == "ProviderPrivacyError"
        assert attempt.result is None
        assert attempt.deterministic["failure_reason"] == "ProviderPrivacyError"
        live = attempt.deterministic["live"]
        assert live["outcome"] == "abstained" and live["labels"] == []
        assert accepted_labels({"live": live}) == {}
        assert job.status == "succeeded" and job.error == "ProviderPrivacyError"
        assert job.lease_owner is None and job.lease_until is None
        assert (evidence.id, evidence.content_hash, evidence.abstract) == evidence_snapshot
        assert observation.abstract == unsafe_abstract
        assert calls == []
    assert provider_calls == []

    # A repeated bounded scan sees the same input key and does not enqueue an
    # unbounded retry of the privacy-withheld historical job.
    with shadow_db() as session:
        replay = run_shadow(session, limit=1)
    assert replay["attempted"] == 0
    with shadow_db() as session:
        assert len(list(session.scalars(select(EvidenceJudgeRun)))) == 1
        assert len(list(session.scalars(select(Job).where(Job.kind == "evidence_shadow")))) == 1
        assert list(session.scalars(select(LogicalCall))) == []
    assert provider_calls == []
