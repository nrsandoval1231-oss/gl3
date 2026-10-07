from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.jobs.queue import lease_one
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    Job,
    PlannerState,
    Source,
    SourceCheckReceipt,
    SourceDueCheck,
    SourceScheduleEpoch,
)
from gridlens.settings import settings


@pytest.fixture
def source_db():
    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and target.database.endswith("_test"), (
        "Refusing to reset a database without an explicit disposable *_test name"
    )
    assert (target.host, target.port, target.database) != (
        application.host,
        application.port,
        application.database,
    )
    engine = create_engine(settings.test_database_url, pool_size=5)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(
            Source(
                id="synthetic-scheduled-source",
                publisher="Fixture",
                endpoint="https://example.invalid/current",
                family="synthetic",
                geography="US",
                industries=["mining"],
                retrieval_method="test",
                cadence_hours=24,
                enabled=True,
                registry_enabled=True,
                health={},
            )
        )
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


def definition(*, enabled=True, endpoint="https://example.invalid/current"):
    return {
        "id": "synthetic-scheduled-source",
        "publisher": "Fixture",
        "endpoint": endpoint,
        "family": "synthetic",
        "geography": "US",
        "industries": ["mining"],
        "retrieval_method": "test",
        "cadence_hours": 24,
        "enabled": enabled,
    }


def test_disabled_ingestion_jobs_remain_inspectable_and_unleased(source_db):
    factory = source_db
    with factory.begin() as session:
        source = session.get(Source, "synthetic-scheduled-source")
        assert source
        source.enabled = False
        queued = Job(source_id=source.id, status="queued", attempts=2)
        expired = Job(
            source_id=source.id,
            status="running",
            attempts=3,
            lease_owner="old-worker",
            fence=3,
            lease_until=datetime.now(UTC) - timedelta(seconds=1),
        )
        session.add_all([queued, expired])
        session.flush()
        queued_id, expired_id = queued.id, expired.id
    with factory.begin() as session:
        assert lease_one(session, "new-worker") is None
    with factory() as session:
        queued, expired = session.get(Job, queued_id), session.get(Job, expired_id)
        assert queued and (queued.status, queued.attempts) == ("queued", 2)
        assert expired and (expired.status, expired.attempts, expired.lease_owner) == (
            "running",
            3,
            "old-worker",
        )


def test_registry_sync_keeps_operator_disable_and_explicit_reenable_is_effective(
    source_db, monkeypatch
):
    import gridlens.jobs.worker as worker

    factory = source_db
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(worker, "load_registry", lambda: [definition()])
    with factory.begin() as session:
        session.get(Source, "synthetic-scheduled-source").enabled = False
    worker.sync_registry()
    with factory() as session:
        source = session.get(Source, "synthetic-scheduled-source")
        assert source and not source.enabled and source.registry_enabled
        assert not session.scalar(
            select(SourceScheduleEpoch).where(
                SourceScheduleEpoch.source_id == source.id,
                SourceScheduleEpoch.effective_until.is_(None),
            )
        ).operator_enabled
        assert session.scalar(
            select(SourceScheduleEpoch).where(
                SourceScheduleEpoch.source_id == source.id,
                SourceScheduleEpoch.effective_until.is_(None),
            )
        ).history_known
    worker.set_source_enabled("synthetic-scheduled-source", True)
    with factory() as session:
        source = session.get(Source, "synthetic-scheduled-source")
        assert source and source.enabled and source.registry_enabled
        current = session.scalar(
            select(SourceScheduleEpoch).where(
                SourceScheduleEpoch.source_id == source.id,
                SourceScheduleEpoch.effective_until.is_(None),
            )
        )
        assert current and current.operator_enabled and current.registry_enabled
        assert current.history_known


def test_unobserved_registry_drift_keeps_seven_day_freshness_unknown(source_db, monkeypatch):
    import gridlens.api.app as api
    import gridlens.jobs.worker as worker

    factory = source_db
    now = datetime.now(UTC)
    registry = [definition()]
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(api, "SessionLocal", factory)
    monkeypatch.setattr(worker, "load_registry", lambda: registry)
    monkeypatch.setattr(api, "load_registry", lambda: registry)
    worker.sync_registry()
    with factory.begin() as session:
        epoch = session.scalar(select(SourceScheduleEpoch))
        source = session.get(Source, "synthetic-scheduled-source")
        assert epoch and source
        epoch.effective_from = now - timedelta(days=10)
        epoch.anchor = {
            "local_date": (now - timedelta(days=10))
            .astimezone(ZoneInfo("America/Chicago"))
            .date()
            .isoformat(),
            "local_time": "03:00",
        }
        source.health = {"status": "Updated", "last_attempt": now.isoformat()}
        job = Job(source_id=source.id, status="succeeded")
        session.add(job)
        session.flush()
        due = SourceDueCheck(
            due_key="a" * 64,
            source_id=source.id,
            epoch_id=epoch.id,
            scheduled_for=now - timedelta(days=1),
            local_day=(now - timedelta(days=1))
            .astimezone(ZoneInfo("America/Chicago"))
            .date(),
            configuration=epoch.configuration,
            job_id=job.id,
        )
        session.add(due)
        session.flush()
        session.add(
            SourceCheckReceipt(
                due_key=due.due_key,
                job_id=job.id,
                fence=1,
                disposition="succeeded",
                check_counts={"checked": 1},
                digest="b" * 64,
            )
        )

    assert api.health()["sources"][0]["freshness"] == "FRESH"
    registry = [{**definition(), "endpoint": "https://example.invalid/revised"}]
    worker.sync_registry()
    with factory() as session:
        epochs = session.scalars(
            select(SourceScheduleEpoch).order_by(SourceScheduleEpoch.effective_from)
        ).all()
        assert len(epochs) == 2
        assert not epochs[0].history_known
        assert epochs[1].history_known
    with factory.begin() as session:
        worker._reconcile_due(session, datetime.now(UTC) + timedelta(days=2))
        assert (
            session.scalar(
                select(func.count()).select_from(SourceDueCheck).where(
                    SourceDueCheck.epoch_id == epochs[0].id
                )
            )
            == 1
        )
        assert session.scalar(
            select(func.count()).select_from(SourceDueCheck).where(
                SourceDueCheck.epoch_id == epochs[1].id
            )
        ) >= 1
    status = api.health()
    assert status["sources"][0]["freshness"] == "UNKNOWN"
    assert status["collection_freshness"] == "UNKNOWN"


@pytest.mark.parametrize(
    ("disposition", "expected"), [("failed", "FAILED"), ("partial", "PARTIAL")]
)
def test_non_success_receipt_never_counts_as_fresh(source_db, monkeypatch, disposition, expected):
    import gridlens.api.app as api

    factory = source_db
    now = datetime.now(UTC)
    monkeypatch.setattr(api, "SessionLocal", factory)
    monkeypatch.setattr(api, "load_registry", lambda: [definition()])
    with factory.begin() as session:
        source = session.get(Source, "synthetic-scheduled-source")
        assert source
        source.health = {"status": "Updated", "last_attempt": now.isoformat()}
        epoch = SourceScheduleEpoch(
            source_id=source.id,
            registry_enabled=True,
            operator_enabled=True,
            effective_from=now - timedelta(days=10),
            cadence_hours=24,
            schedule_mode="local_daily",
            timezone="America/Chicago",
            anchor={
                "local_date": (now - timedelta(days=10)).date().isoformat(),
                "local_time": "03:00",
            },
            configuration=definition(),
            history_known=True,
        )
        session.add(epoch)
        session.flush()
        job = Job(source_id=source.id, status="failed")
        session.add(job)
        session.flush()
        due = SourceDueCheck(
            due_key=("d" if disposition == "failed" else "e") * 64,
            source_id=source.id,
            epoch_id=epoch.id,
            scheduled_for=now - timedelta(days=1),
            local_day=(now - timedelta(days=1))
            .astimezone(ZoneInfo("America/Chicago"))
            .date(),
            configuration=epoch.configuration,
            job_id=job.id,
        )
        session.add(due)
        session.flush()
        session.add(
            SourceCheckReceipt(
                due_key=due.due_key,
                job_id=job.id,
                fence=1,
                disposition=disposition,
                check_counts={"observed": 1},
                digest="f" * 64,
            )
        )

    assert api.health()["sources"][0]["freshness"] == expected


def test_disabled_after_lease_is_parked_without_provider_request(source_db, monkeypatch):
    import gridlens.jobs.worker as worker

    factory = source_db
    with factory.begin() as session:
        job = Job(
            source_id="synthetic-scheduled-source",
            status="queued",
            available_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        session.add(job)
        session.flush()
        job_id = job.id
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(worker, "WORKER_ID", "disable-check-worker")
    registry_reads = iter(([definition(enabled=True)], [definition(enabled=False)]))
    monkeypatch.setattr(worker, "load_registry", lambda: next(registry_reads))
    calls = []
    monkeypatch.setattr(worker, "process_job", lambda *args, **kwargs: calls.append(args))

    assert worker.run_one({"synthetic-scheduled-source": {"endpoint": "https://stale.invalid"}})
    assert calls == []
    with factory() as session:
        job = session.get(Job, job_id)
        source = session.get(Source, "synthetic-scheduled-source")
        assert job and job.status == "queued" and job.attempts == 0
        assert job.error and "no provider request" in job.error
        assert source and source.health["status"] == "Disabled"


def test_invalid_registry_defers_ingestion_but_ready_research_job_runs(source_db, monkeypatch):
    import gridlens.intelligence.pursuits as pursuits
    import gridlens.jobs.worker as worker

    factory = source_db
    with factory.begin() as session:
        ingestion = Job(
            source_id="synthetic-scheduled-source",
            kind="ingestion",
            status="queued",
            available_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        research = Job(
            source_id="synthetic-scheduled-source",
            kind="pursuit_research",
            status="queued",
            available_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        session.add_all([ingestion, research])
        session.flush()
        ingestion_id, research_id = ingestion.id, research.id

    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(worker, "WORKER_ID", "registry-failure-worker")

    def invalid_registry():
        raise ValueError("invalid registry fixture")

    monkeypatch.setattr(worker, "load_registry", invalid_registry)
    network_calls = []
    monkeypatch.setattr(worker, "process_job", lambda *args, **kwargs: network_calls.append(args))
    assert worker.run_one({}, job_ids=[ingestion_id])
    with factory() as session:
        deferred = session.get(Job, ingestion_id)
        assert deferred and deferred.status == "queued" and deferred.attempts == 0
        assert deferred.error and "no provider request" in deferred.error
    assert network_calls == []

    research_calls = []
    monkeypatch.setattr(
        pursuits, "process_research_job", lambda *args: research_calls.append(args)
    )
    assert worker.run_one({}, job_ids=[research_id])
    assert research_calls and research_calls[0][0] == research_id


def test_worker_uses_fresh_registry_and_records_success_for_one_due_slot(source_db, monkeypatch):
    import gridlens.jobs.worker as worker

    factory = source_db
    now = datetime.now(UTC)
    with factory.begin() as session:
        epoch = SourceScheduleEpoch(
            source_id="synthetic-scheduled-source",
            registry_enabled=True,
            operator_enabled=True,
            effective_from=now - timedelta(days=1),
            cadence_hours=24,
            schedule_mode="local_daily",
            timezone="America/Chicago",
            anchor={
                "local_date": (now - timedelta(days=1))
                .astimezone(ZoneInfo("America/Chicago"))
                .date()
                .isoformat(),
                "local_time": "03:00:00",
            },
            configuration=definition(),
        )
        session.add(epoch)
        session.flush()
        job = Job(
            source_id="synthetic-scheduled-source",
            status="queued",
            available_at=now - timedelta(seconds=1),
        )
        session.add(job)
        session.flush()
        due = SourceDueCheck(
            due_key="f" * 64,
            source_id="synthetic-scheduled-source",
            epoch_id=epoch.id,
            scheduled_for=now - timedelta(seconds=2),
            local_day=now.astimezone(ZoneInfo("America/Chicago")).date(),
            configuration=definition(),
            job_id=job.id,
        )
        session.add(due)
        job_id = job.id

    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(worker, "WORKER_ID", "fresh-registry-worker")
    current = definition(endpoint="https://example.invalid/current")
    monkeypatch.setattr(worker, "load_registry", lambda: [current])
    received = []

    def process(session, job_id, worker_id, fence, source_definition):
        received.append(source_definition["endpoint"])
        return {"new": 1, "changed": 0, "unchanged": 0, "latest_publication_date": None}

    monkeypatch.setattr(worker, "process_job", process)
    assert worker.run_one(
        {"synthetic-scheduled-source": definition(endpoint="https://stale.invalid")}
    )
    assert received == ["https://example.invalid/current"]
    with factory() as session:
        receipts = session.scalars(select(SourceCheckReceipt)).all()
        due_rows = session.scalars(select(SourceDueCheck)).all()
        assert len(due_rows) == 1 and due_rows[0].job_id == job_id
        assert len(receipts) == 1 and receipts[0].disposition == "succeeded"
        assert len(receipts[0].digest) == 64


def test_disable_during_dispatched_request_keeps_fenced_outcome(source_db, monkeypatch):
    import gridlens.jobs.worker as worker

    factory = source_db
    now = datetime.now(UTC)
    with factory.begin() as session:
        epoch = SourceScheduleEpoch(
            source_id="synthetic-scheduled-source",
            registry_enabled=True,
            operator_enabled=True,
            effective_from=now - timedelta(days=1),
            cadence_hours=24,
            schedule_mode="local_daily",
            timezone="America/Chicago",
            anchor={
                "local_date": (now - timedelta(days=1))
                .astimezone(ZoneInfo("America/Chicago"))
                .date()
                .isoformat(),
                "local_time": "03:00:00",
            },
            configuration=definition(),
        )
        session.add(epoch)
        session.flush()
        job = Job(
            source_id="synthetic-scheduled-source",
            status="queued",
            available_at=now - timedelta(seconds=1),
        )
        session.add(job)
        session.flush()
        session.add(
            SourceDueCheck(
                due_key="c" * 64,
                source_id="synthetic-scheduled-source",
                epoch_id=epoch.id,
                scheduled_for=now - timedelta(seconds=1),
                local_day=now.astimezone(ZoneInfo("America/Chicago")).date(),
                configuration=definition(),
                job_id=job.id,
            )
        )
        job_id = job.id

    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(worker, "WORKER_ID", "inflight-disable-worker")
    monkeypatch.setattr(worker, "load_registry", lambda: [definition()])
    started, finish_provider, disable_started, disable_finished = Event(), Event(), Event(), Event()
    acquisitions = []

    def process(*_args, **_kwargs):
        acquisitions.append("started")
        started.set()
        assert finish_provider.wait(timeout=5)
        return {"new": 1, "changed": 0, "unchanged": 0, "latest_publication_date": None}

    monkeypatch.setattr(worker, "process_job", process)

    def disable_source():
        disable_started.set()
        worker.set_source_enabled("synthetic-scheduled-source", False)
        disable_finished.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        running = pool.submit(worker.run_one, {})
        assert started.wait(timeout=5)
        disabling = pool.submit(disable_source)
        assert disable_started.wait(timeout=5)
        assert not disable_finished.wait(timeout=0.05)
        finish_provider.set()
        assert running.result(timeout=5)
        disabling.result(timeout=5)
        assert disable_finished.is_set()

    assert acquisitions == ["started"]
    with factory() as session:
        job = session.get(Job, job_id)
        source = session.get(Source, "synthetic-scheduled-source")
        due = session.get(SourceDueCheck, "c" * 64)
        receipt = session.scalar(select(SourceCheckReceipt))
        assert job and job.status == "succeeded" and job.attempts == 1
        assert source and not source.enabled
        assert due and due.job_id == job_id
        assert receipt and receipt.job_id == job_id and receipt.fence == job.fence
        assert receipt.disposition == "succeeded"


def test_concurrent_due_reconciliation_has_one_identity_per_occurrence(source_db):
    import gridlens.jobs.worker as worker

    factory = source_db
    now = datetime.now(UTC)
    with factory.begin() as session:
        session.add(
            SourceScheduleEpoch(
                source_id="synthetic-scheduled-source",
                registry_enabled=True,
                operator_enabled=True,
                effective_from=now - timedelta(days=3),
                cadence_hours=24,
                schedule_mode="local_daily",
                timezone="America/Chicago",
                anchor={
                    "local_date": (now - timedelta(days=3))
                    .astimezone(ZoneInfo("America/Chicago"))
                    .date()
                    .isoformat(),
                    "local_time": "03:00:00",
                },
                configuration=definition(),
            )
        )
    barrier = Barrier(2)

    def reconcile():
        barrier.wait(timeout=5)
        with factory.begin() as session:
            return worker._reconcile_due(session, now)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: reconcile(), range(2)))
    with factory() as session:
        keys = session.scalars(select(SourceDueCheck.due_key)).all()
        assert keys and len(keys) == len(set(keys))
        assert session.scalar(select(func.count()).select_from(SourceDueCheck)) == len(keys)


def test_concurrent_registry_sync_keeps_one_open_schedule_epoch(source_db, monkeypatch):
    import gridlens.jobs.worker as worker

    factory = source_db
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(worker, "load_registry", lambda: [definition()])
    barrier = Barrier(2)

    def synchronize():
        barrier.wait(timeout=5)
        return worker.sync_registry()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: synchronize(), range(2)))
    assert all(len(result) == 1 for result in results)
    with factory() as session:
        epochs = session.scalars(
            select(SourceScheduleEpoch).where(
                SourceScheduleEpoch.source_id == "synthetic-scheduled-source",
                SourceScheduleEpoch.effective_until.is_(None),
            )
        ).all()
        assert len(epochs) == 1


@pytest.mark.parametrize(
    ("local_day", "local_time", "expected_utc"),
    [
        ("2026-03-08", "03:00:00", "2026-03-08T08:00:00+00:00"),
        ("2026-11-01", "03:00:00", "2026-11-01T09:00:00+00:00"),
        # 02:30 does not exist on spring-forward day; resolve forward to 03:30.
        ("2026-03-08", "02:30:00", "2026-03-08T08:30:00+00:00"),
    ],
)
def test_daily_occurrence_maps_dst_deterministically(local_day, local_time, expected_utc):
    import gridlens.jobs.worker as worker

    zone = ZoneInfo("America/Chicago")
    effective = datetime.fromisoformat(local_day).replace(tzinfo=zone)
    epoch = SourceScheduleEpoch(
        source_id="dst-source",
        effective_from=effective,
        effective_until=None,
        cadence_hours=24,
        schedule_mode="local_daily",
        timezone="America/Chicago",
        anchor={"local_date": local_day, "local_time": local_time},
    )
    limit = datetime.fromisoformat(local_day).replace(tzinfo=UTC) + timedelta(days=1)
    instants = list(worker._scheduled_instants(epoch, limit))
    assert instants[0].isoformat() == expected_utc


def test_planner_failure_is_persisted_and_retried_with_backoff(source_db, monkeypatch):
    import gridlens.jobs.worker as worker

    factory = source_db
    monkeypatch.setattr(worker, "SessionLocal", factory)
    calls = []

    def broken():
        calls.append("failed")
        raise RuntimeError("synthetic planner failure")

    assert not worker._run_planner("sources", broken)
    with factory() as session:
        state = session.get(PlannerState, "sources")
        assert state and state.consecutive_failures == 1
        assert state.last_attempt_at and state.next_retry_at
        assert state.last_success_at is None and state.error_class == "RuntimeError"
    assert not worker._run_planner("sources", lambda: calls.append("unexpected"))
    assert calls == ["failed"]
    assert worker._run_planner("pursuit_questions", lambda: calls.append("independent"))
    assert calls[-1] == "independent"
