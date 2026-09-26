from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.jobs.queue import assert_fence, enqueue, lease_one
from gridlens.persistence.database import Base
from gridlens.persistence.models import Job, Source
from gridlens.settings import settings


@pytest.fixture
def db():
    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and (target.database == "test" or target.database.endswith("_test"))
    assert (target.host, target.port, target.database) != (
        application.host,
        application.port,
        application.database,
    ), "Refusing to reset application database"
    engine = create_engine(settings.test_database_url, pool_size=5)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(
            Source(
                id="synthetic-test-source",
                publisher="Synthetic Fixture",
                endpoint="https://example.invalid/records",
                family="synthetic",
                geography="US",
                industries=["mining"],
                retrieval_method="test",
                cadence_hours=24,
                health={"status": "Checked—No Change", "last_success": "retained"},
            )
        )
    yield engine, factory
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_concurrent_enqueue_serializes_per_source(db):
    _, factory = db
    gate = Barrier(2)

    def submit():
        gate.wait(timeout=5)
        with factory.begin() as session:
            return enqueue(session, "synthetic-test-source")

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _: submit(), range(2)))
    assert ids[0] == ids[1]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 1


def test_managed_scheduler_enqueue_is_idempotent_per_chicago_day(db, monkeypatch):
    _, factory = db
    import gridlens.jobs.refresh_sources as scheduler

    monkeypatch.setattr(scheduler, "SessionLocal", factory)
    monkeypatch.setattr(
        scheduler,
        "sync_registry",
        lambda: [{"id": "synthetic-test-source", "enabled": True}],
    )
    assert scheduler.enqueue_daily_sources() == 1
    assert scheduler.enqueue_daily_sources() == 0
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 1
        source = session.get(Source, "synthetic-test-source")
        assert source and source.health.get("scheduled_day")


def test_expired_lease_reclaims_with_new_fence_and_rejects_stale_worker(db):
    _, factory = db
    with factory.begin() as session:
        job_id = enqueue(session, "synthetic-test-source")
        queued = session.get(Job, job_id)
        assert queued
        queued.available_at = datetime.now(UTC) - timedelta(seconds=1)
    with factory.begin() as session:
        job, old_fence = lease_one(session, "old-worker", lease_seconds=1)
        assert job.id == job_id
        job.lease_until = datetime.now(UTC) - timedelta(seconds=1)
    stale_session = factory()
    stale_job = stale_session.get(Job, job_id)
    assert stale_job and stale_job.fence == old_fence
    stale_session.commit()
    with factory.begin() as session:
        reclaimed, new_fence = lease_one(session, "new-worker", lease_seconds=60)
        assert reclaimed.id == job_id
        assert new_fence == old_fence + 1
    try:
        with pytest.raises(RuntimeError, match="fence lost"):
            assert_fence(stale_session, job_id, "old-worker", old_fence)
    finally:
        stale_session.rollback()
        stale_session.close()
    with factory() as session:
        current = assert_fence(session, job_id, "new-worker", new_fence)
        assert current.attempts == 2


def test_expired_job_at_attempt_limit_is_terminal_and_visible(db):
    _, factory = db
    with factory.begin() as session:
        job = Job(
            source_id="synthetic-test-source",
            status="running",
            attempts=5,
            lease_owner="dead-worker",
            fence=5,
            lease_until=datetime.now(UTC) - timedelta(seconds=1),
        )
        session.add(job)
    with factory.begin() as session:
        assert lease_one(session, "replacement-worker") is None
    with factory() as session:
        job = session.scalar(select(Job))
        source = session.get(Source, "synthetic-test-source")
        assert job and job.status == "failed" and job.lease_owner is None
        assert job.error == "Lease expired after maximum attempts"
        assert source and source.health["status"] == "Failed"
        assert source.health["last_success"] == "retained"


def test_parser_failure_preserves_accepted_health_and_is_visible(db, monkeypatch):
    _, factory = db
    with factory.begin() as session:
        job_id = enqueue(session, "synthetic-test-source")
        queued = session.get(Job, job_id)
        assert queued
        queued.available_at = datetime.now(UTC) - timedelta(seconds=1)

    from fastapi.testclient import TestClient

    import gridlens.api.app as api
    import gridlens.jobs.worker as worker
    from gridlens.ingestion.adapters.federal_register import SourceParseError
    from gridlens.security import token_for

    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(api, "SessionLocal", factory)
    monkeypatch.setattr(
        worker,
        "process_job",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            SourceParseError("synthetic schema mismatch")
        ),
    )
    monkeypatch.setattr(worker, "WORKER_ID", "failure-test-worker")
    assert worker.run_one({"synthetic-test-source": {"id": "synthetic-test-source"}})

    client = TestClient(api.app)
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    response = client.get("/api/health")
    assert response.status_code == 200
    source = response.json()["sources"][0]
    assert source["status"] == "Failed"
    assert source["error"] == "synthetic schema mismatch"
    assert source["last_success"] == "retained"
    assert source["new_records"] == 0
    with factory() as session:
        assert session.scalar(select(Job.status)) == "queued"
