"""Bound automatic collection jobs while retaining PostgreSQL progress and retries."""

import hashlib
import json
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.ingestion.registry import load_registry
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    Job,
    Source,
    SourceCheckReceipt,
    SourceCollectionProgress,
    SourceDueCheck,
    SourceScheduleEpoch,
)
from gridlens.settings import settings


@pytest.fixture
def chain_db(monkeypatch, request):
    import gridlens.jobs.worker as worker

    target, application = make_url(settings.test_database_url), make_url(settings.database_url)
    assert target.database and target.database.endswith("_test")
    assert (target.host, target.port, target.database) != (
        application.host,
        application.port,
        application.database,
    )
    engine = create_engine(settings.test_database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    class NoopRenewer:
        def __init__(self, *_args):
            pass

        def start(self):
            return self

        def stop(self):
            pass

    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(worker, "WORKER_ID", "collection-chain-test")
    monkeypatch.setattr(worker, "try_public_acquisition_admission", lambda *_: nullcontext(True))
    monkeypatch.setattr(worker, "FencedLeaseRenewer", NoopRenewer)
    source_id = getattr(request, "param", "austin-building-permits")
    definition = next(x for x in load_registry() if x["id"] == source_id)
    with factory.begin() as session:
        session.add(
            Source(
                **{
                    key: definition[key]
                    for key in (
                        "id",
                        "publisher",
                        "endpoint",
                        "family",
                        "geography",
                        "industries",
                        "retrieval_method",
                        "cadence_hours",
                    )
                },
                enabled=True,
                registry_enabled=True,
                health={"status": "Updated", "last_success": "prior-success", "parse_failures": 0},
            )
        )
        session.flush()
        session.add(
            SourceScheduleEpoch(
                source_id=definition["id"],
                registry_enabled=True,
                operator_enabled=True,
                effective_from=datetime.now(UTC) - timedelta(days=2),
                cadence_hours=24,
                schedule_mode="fixed",
                timezone="UTC",
                anchor={},
                configuration={},
                history_known=True,
            )
        )
    try:
        yield factory, definition
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _job(factory, definition, checkpoint=None, *, attempts=0):
    with factory.begin() as session:
        job = Job(
            source_id=definition["id"],
            kind="ingestion",
            status="queued",
            checkpoint=checkpoint,
            attempts=attempts,
            available_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        session.add(job)
        session.flush()
        return job.id


def _run(factory, definition, job_id):
    import gridlens.jobs.worker as worker

    with factory.begin() as session:
        job = session.get(Job, job_id)
        assert job is not None
        job.available_at = datetime.now(UTC) - timedelta(seconds=1)
        if session.scalar(select(SourceDueCheck).where(SourceDueCheck.job_id == job_id)) is None:
            epoch = session.scalar(select(SourceScheduleEpoch))
            session.add(
                SourceDueCheck(
                    due_key=hashlib.sha256(str(job_id).encode()).hexdigest(),
                    source_id=definition["id"],
                    epoch_id=epoch.id,
                    scheduled_for=datetime.now(UTC) - timedelta(minutes=1),
                    local_day=datetime.now(UTC).date(),
                    configuration={},
                    job_id=job_id,
                )
            )
    return worker.run_one({definition["id"]: definition}, job_ids=[job_id])


def _counts(*, complete=False):
    return {
        "new": 0,
        "changed": 0,
        "unchanged": 0,
        "signals": 0,
        "latest_publication_date": None,
        "parse_failures": 0,
        "collection_status": "COMPLETE" if complete else "PARTIAL",
        "collection_continuation": not complete,
        "collection_current_complete": complete,
        "partial": not complete,
    }


def _receipt(session, job_id):
    return session.scalar(
        select(SourceCheckReceipt)
        .where(SourceCheckReceipt.job_id == job_id)
        .order_by(SourceCheckReceipt.fence.desc())
    ).check_counts


def test_two_job_chain_pauses_with_cursor_and_new_schedule_resumes(chain_db, monkeypatch):
    import gridlens.ingestion.service as service

    factory, definition = chain_db
    calls = []

    def segment(_definition, lane, _start, _end, cursor, *_args, **_kwargs):
        calls.append((lane, dict(cursor)))
        return {
            "records": [],
            "cursor": {"synthetic_offset": cursor.get("synthetic_offset", 0) + 1},
            "partial": False,
            "window_complete": False,
            "observed_count": 0,
        }

    monkeypatch.setattr(service, "retrieve_collection_segment", segment)
    first = _job(factory, definition, json.dumps({"collection_jobs_remaining": 2}))
    assert _run(factory, definition, first)
    with factory() as session:
        tail = session.scalar(select(Job).where(Job.status == "queued"))
        assert json.loads(tail.checkpoint) == {
            "collection_continuation": True,
            "collection_jobs_remaining": 1,
        }
        second = tail.id
        assert _receipt(session, first)["collection_continuation"] is True
    assert _run(factory, definition, second)
    with factory() as session:
        assert len(session.scalars(select(Job)).all()) == 2
        assert session.scalar(select(Job).where(Job.status == "queued")) is None
        health = session.get(Source, definition["id"]).health
        assert health["status"] == "Partial" and health["last_success"] == "prior-success"
        assert health["collection_paused_for_budget"] is True
        assert health["collection_jobs_remaining"] == 0 and health["parse_failures"] == 0
        counts = _receipt(session, second)
        assert counts["collection_paused_for_budget"] is True
        assert counts["collection_jobs_remaining"] == 0
        assert counts["collection_continuation"] is False and counts.get("parse_failures", 0) == 0
        progress = session.scalars(select(SourceCollectionProgress)).all()
        saved = {p.lane: dict(p.cursor) for p in progress}
        assert all(p.status == "incomplete" and p.completed_through is None for p in progress)
        assert len(calls) == 2
        assert sum(bool(cursor) for cursor in saved.values()) == 2
    # A normal scheduled job has no inherited chain marker or budget. Lane fairness
    # may select any pending lane; compare the cursor for the lane actually selected.
    fresh = _job(factory, definition)
    assert _run(factory, definition, fresh)
    assert len(calls) == 3 and calls[-1][1] == saved[calls[-1][0]]
    with factory() as session:
        tail = session.scalar(select(Job).where(Job.status == "queued"))
        assert json.loads(tail.checkpoint)["collection_jobs_remaining"] == 7
        health = session.get(Source, definition["id"]).health
        assert health["collection_paused_for_budget"] is False
        assert health["collection_jobs_remaining"] == 7


@pytest.mark.parametrize("checkpoint", [None, '{"collection_continuation": true}'])
def test_default_and_legacy_marker_allow_exactly_eight_jobs(chain_db, monkeypatch, checkpoint):
    import gridlens.jobs.worker as worker

    factory, definition = chain_db
    monkeypatch.setattr(worker, "process_job", lambda *_a, **_k: _counts())
    job_id = _job(factory, definition, checkpoint)
    for remaining in range(7, -1, -1):
        assert _run(factory, definition, job_id)
        with factory() as session:
            counts = _receipt(session, job_id)
            assert counts["collection_jobs_remaining"] == remaining
            assert counts["collection_continuation"] is (remaining > 0)
            assert counts["collection_paused_for_budget"] is (remaining == 0)
            tail = session.scalar(select(Job).where(Job.status == "queued"))
            if remaining:
                assert json.loads(tail.checkpoint)["collection_jobs_remaining"] == remaining
                job_id = tail.id
            else:
                assert tail is None
                assert len(session.scalars(select(Job)).all()) == 8


def test_invalid_budgets_and_checkpoint_shapes_fail_before_dispatch(chain_db, monkeypatch):
    import gridlens.jobs.worker as worker

    factory, definition = chain_db

    def forbidden(*_args, **_kwargs):
        pytest.fail("Invalid collection budget reached acquisition")

    monkeypatch.setattr(worker, "process_job", forbidden)
    invalid = [
        json.dumps({"collection_jobs_remaining": value})
        for value in (0, -1, 9, True, False, "2", 1.5, None)
    ]
    invalid += [
        "[]",
        '"text"',
        "null",
        "true",
        "false",
        "1.5",
        "{broken",
        "A" * 129,
        "2025-155325\tEP",
        "2025-155325\nEP",
        "2025-155325  EP",
        " ALT123",
        "ALT123 ",
    ]
    for checkpoint in invalid:
        job_id = _job(factory, definition, checkpoint, attempts=4)
        assert _run(factory, definition, job_id)
        with factory() as session:
            job = session.get(Job, job_id)
            assert job.status == "failed" and job.attempts == 5
            assert job.lease_owner is None and job.lease_until is None
            assert job.checkpoint == checkpoint
            assert session.scalar(select(Job).where(Job.status == "queued")) is None
    exhausted = _job(factory, definition, '{"collection_jobs_remaining": 1}', attempts=5)
    assert _run(factory, definition, exhausted) is False


def test_last_job_complete_does_not_report_budget_pause(chain_db, monkeypatch):
    import gridlens.jobs.worker as worker

    factory, definition = chain_db
    with factory.begin() as session:
        source = session.get(Source, definition["id"])
        source.health = {**source.health, "collection_paused_for_budget": True}
    monkeypatch.setattr(worker, "process_job", lambda *_a, **_k: _counts(complete=True))
    job_id = _job(factory, definition, '{"collection_jobs_remaining": 1}')
    assert _run(factory, definition, job_id)
    with factory() as session:
        counts = _receipt(session, job_id)
        assert counts["collection_status"] == "COMPLETE" and counts["partial"] is False
        assert counts["collection_paused_for_budget"] is False
        assert counts["collection_jobs_remaining"] == 0
        health = session.get(Source, definition["id"]).health
        assert (
            health["status"] == "Checked\u2014No Change"
            and health["last_success"] != "prior-success"
        )
        assert health["collection_paused_for_budget"] is False and health["error"] is None
        assert (
            session.scalar(select(Job).where(Job.kind == "ingestion", Job.status == "queued"))
            is None
        )


@pytest.mark.parametrize(
    ("chain_db", "legacy_id"),
    [
        ("austin-building-permits", "ALT123"),
        ("austin-building-permits", "N2990649"),
        ("austin-building-permits", "100123"),
        ("austin-building-permits", "N2990649"),
        ("austin-building-permits", "2025-155325 EP"),
    ],
    indirect=["chain_db"],
)
def test_legacy_record_checkpoint_resumes_durable_progress(chain_db, monkeypatch, legacy_id):
    import gridlens.ingestion.service as service
    from gridlens.ingestion.structured_collection import prepare_collection_progress

    factory, definition = chain_db
    with factory.begin() as session:
        prepare_collection_progress(session, definition)
        progress = session.scalars(select(SourceCollectionProgress)).all()
        # Every lane has resumable state; fairness, not the test, chooses the lane.
        for row in progress:
            row.cursor = {"synthetic_offset": 5, "lane": row.lane}
            row.status = "incomplete"
    job_id = _job(factory, definition, legacy_id, attempts=1)
    calls = []

    def segment(_definition, lane, _start, _end, cursor, *_args, **_kwargs):
        assert cursor == {"synthetic_offset": 5, "lane": lane}
        with factory() as session:
            saved = json.loads(session.get(Job, job_id).checkpoint)
            assert saved == {"last_record_external_id": legacy_id, "collection_jobs_remaining": 8}
        calls.append(lane)
        return {
            "records": [],
            "cursor": {"synthetic_offset": 6, "lane": lane},
            "partial": False,
            "window_complete": False,
            "observed_count": 0,
        }

    monkeypatch.setattr(service, "retrieve_collection_segment", segment)
    assert _run(factory, definition, job_id)
    assert len(calls) == 1
    with factory() as session:
        job = session.get(Job, job_id)
        assert job.status == "succeeded" and job.attempts == 2
        assert json.loads(job.checkpoint)["last_record_external_id"] == legacy_id
        resumed = session.scalar(
            select(SourceCollectionProgress).where(SourceCollectionProgress.lane == calls[0])
        )
        assert resumed.cursor == {"synthetic_offset": 6, "lane": calls[0]}
        tail = session.scalar(select(Job).where(Job.status == "queued"))
        assert json.loads(tail.checkpoint)["collection_jobs_remaining"] == 7


@pytest.mark.parametrize("continuation", [False, True])
def test_retry_preserves_budget_through_service_record_checkpoint(
    chain_db, monkeypatch, continuation
):
    import gridlens.ingestion.service as service
    import gridlens.jobs.worker as worker

    factory, definition = chain_db
    checkpoint = {"collection_jobs_remaining": 2}
    if continuation:
        checkpoint["collection_continuation"] = True
    job_id = _job(factory, definition, json.dumps(checkpoint))
    calls = []

    def segment(*_args, **_kwargs):
        calls.append(True)
        return {
            "records": [{"document_number": "synthetic-permit-id"}],
            "cursor": {"synthetic_offset": len(calls)},
            "partial": False,
            "window_complete": False,
            "observed_count": 1,
        }

    # Keep actual service evidence/checkpoint/progress commit sequencing. Only row
    # interpretation is stubbed: no LLM, provider, or synthetic evidence side effects.
    monkeypatch.setattr(service, "retrieve_collection_segment", segment)
    monkeypatch.setattr(service, "process_records", lambda *_a, **_k: _counts())
    real_process = service.process_job

    def fail_after_durable_progress(*args, **kwargs):
        real_process(*args, **kwargs)
        raise RuntimeError("Synthetic crash after service commit")

    monkeypatch.setattr(worker, "process_job", fail_after_durable_progress)
    assert _run(factory, definition, job_id)
    with factory.begin() as session:
        job = session.get(Job, job_id)
        source = session.get(Source, definition["id"])
        assert job.status == "queued" and job.attempts == 1
        saved = json.loads(job.checkpoint)
        assert saved["collection_jobs_remaining"] == 2
        assert saved["last_record_external_id"] == "synthetic-permit-id"
        assert saved.get("collection_continuation", False) is continuation
        assert len(session.scalars(select(Job)).all()) == 1
        assert source.health["retry_state"] == "scheduled"
        retry_at = datetime.fromisoformat(source.health["retry_at"])
        assert retry_at > datetime.now(UTC)
        assert job.available_at == retry_at
    monkeypatch.setattr(worker, "process_job", real_process)
    assert not _run(factory, definition, job_id)
    with factory.begin() as session:
        job = session.get(Job, job_id)
        source = session.get(Source, definition["id"])
        assert job.status == "queued" and job.attempts == 1
        assert json.loads(job.checkpoint) == saved
        assert source.health["retry_state"] == "scheduled"
        assert datetime.fromisoformat(source.health["retry_at"]) > datetime.now(UTC)
        cooldown_boundary = datetime.now(UTC) - timedelta(seconds=1)
        source.health = {
            **source.health,
            "retry_at": cooldown_boundary.isoformat(),
        }
        job.available_at = cooldown_boundary
    assert len(calls) == 1  # The held run did not make another acquisition call.
    assert _run(factory, definition, job_id)
    assert len(calls) == 2  # Retries are dispatches within the same chain job.
    with factory() as session:
        job = session.get(Job, job_id)
        assert job.status == "succeeded" and job.attempts == 2
        assert json.loads(job.checkpoint)["collection_jobs_remaining"] == 2
        tail = session.scalar(select(Job).where(Job.status == "queued"))
        assert json.loads(tail.checkpoint)["collection_jobs_remaining"] == 1
        assert _receipt(session, job_id)["collection_jobs_remaining"] == 1


@pytest.mark.parametrize("chain_db", ["boston-building-permits"], indirect=True)
def test_boston_job_is_parked_without_an_acquisition_attempt(chain_db, monkeypatch):
    import gridlens.ingestion.service as service

    factory, definition = chain_db
    job_id = _job(factory, definition)
    monkeypatch.setattr(
        service,
        "retrieve_collection_segment",
        lambda *_a, **_k: pytest.fail("disabled Boston source reached acquisition"),
    )
    assert _run(factory, definition, job_id)
    with factory() as session:
        job = session.get(Job, job_id)
        source = session.get(Source, definition["id"])
        assert job.status == "queued" and job.attempts == 0
        assert job.lease_owner is None and job.lease_until is None
        assert "disabled before acquisition" in job.error
        assert source.health["status"] == "Disabled"
