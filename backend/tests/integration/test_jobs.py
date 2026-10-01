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


def test_permit_queue_priority_and_news_age_fairness(db):
    _, factory = db
    now = datetime.now(UTC)
    with factory.begin() as session:
        session.add_all(
            [
                Source(
                    id="city-permits",
                    publisher="City",
                    endpoint="https://data.example/permits",
                    family="construction-permits",
                    geography="City",
                    industries=["construction"],
                    retrieval_method="socrata-permits",
                    cadence_hours=24,
                    health={},
                ),
                Source(
                    id="daily-news",
                    publisher="Publisher",
                    endpoint="https://news.example/feed",
                    family="news",
                    geography="US",
                    industries=["infrastructure"],
                    retrieval_method="publisher-rss",
                    cadence_hours=1,
                    health={},
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                Job(source_id="daily-news", status="queued", available_at=now, created_at=now),
                Job(source_id="city-permits", status="queued", available_at=now, created_at=now),
            ]
        )
    with factory.begin() as session:
        first, _ = lease_one(session, "priority-worker")
        assert first.source_id == "city-permits"
        news = session.scalar(select(Job).where(Job.source_id == "daily-news"))
        assert news
        news.created_at = now - timedelta(days=2)
        session.add(
            Job(source_id="city-permits", status="queued", available_at=now, created_at=now)
        )
    with factory.begin() as session:
        aged_news, _ = lease_one(session, "fairness-worker")
        assert aged_news.source_id == "daily-news"


def test_scoped_worker_leaves_other_jobs_and_expired_leases_untouched(db):
    _, factory = db
    with factory.begin() as session:
        selected = Job(source_id="synthetic-test-source")
        unrelated = Job(
            source_id="synthetic-test-source",
            status="running",
            attempts=5,
            lease_owner="dead-worker",
            lease_until=datetime.now(UTC) - timedelta(days=1),
        )
        session.add_all([selected, unrelated])
        session.flush()
        selected_id, unrelated_id = selected.id, unrelated.id
    with factory.begin() as session:
        assert lease_one(session, "scoped-worker", job_ids=[]) is None
        leased, _ = lease_one(session, "scoped-worker", job_ids=[selected_id])
        assert leased.id == selected_id
    with factory() as session:
        unrelated = session.get(Job, unrelated_id)
        assert (
            unrelated and unrelated.status == "running" and unrelated.lease_owner == "dead-worker"
        )


def _runtime_fixture(factory, monkeypatch):
    import gridlens.jobs.runtime as runtime
    import gridlens.jobs.worker as worker

    definition = {
        "id": "synthetic-test-source",
        "publisher": "Updated Fixture",
        "endpoint": "https://example.invalid/records",
        "family": "synthetic",
        "geography": "US",
        "industries": ["mining"],
        "retrieval_method": "test",
        "cadence_hours": 24,
        "enabled": True,
    }
    monkeypatch.setattr(runtime, "SessionLocal", factory)
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(runtime, "load_registry", lambda: [definition])
    monkeypatch.setattr(worker, "load_registry", lambda: [definition])
    return runtime, worker, definition


def test_runtime_status_is_read_only_and_reconcile_preserves_health_and_jobs(db, monkeypatch):
    _, factory = db
    runtime, _, definition = _runtime_fixture(factory, monkeypatch)
    with factory.begin() as session:
        job_id = enqueue(session, definition["id"])
    before = runtime.inspect_runtime()
    assert before["sources"][0]["registry_drift"] == ["publisher"]
    with factory() as session:
        source = session.get(Source, definition["id"])
        assert source and source.publisher == "Synthetic Fixture"
    runtime.sync_registry()
    runtime.sync_registry()
    after = runtime.inspect_runtime()
    assert after["sources"][0]["registry_drift"] == []
    assert before["jobs"] == after["jobs"] == {"queued": 1}
    assert before["content_counts"] == after["content_counts"]
    assert before["sources"][0]["health"] == after["sources"][0]["health"]
    with factory() as session:
        assert session.get(Job, job_id) is not None


def test_runtime_recovery_honors_backoff_and_reports_failure_then_recovery(db, monkeypatch):
    _, factory = db
    runtime, worker, definition = _runtime_fixture(factory, monkeypatch)
    from gridlens.ingestion.adapters.federal_register import SourceParseError

    def fail(*args):
        raise SourceParseError("synthetic incomplete snapshot")

    monkeypatch.setattr(worker, "process_job", fail)
    first = runtime.check_sources([definition["id"], definition["id"]])
    assert len(first["checks"]) == 1
    assert first["all_succeeded"] is False
    assert first["checks"][0]["health"]["last_success"] == "retained"
    assert first["checks"][0]["health"]["error"] == "synthetic incomplete snapshot"
    deferred = runtime.check_sources([definition["id"]])
    assert deferred["all_succeeded"] is False
    assert deferred["checks"][0]["attempted"] is False
    assert deferred["checks"][0]["attempts"] == 1
    with factory.begin() as session:
        job = session.scalar(select(Job))
        assert job is not None
        job.available_at = datetime.now(UTC) - timedelta(seconds=1)
    monkeypatch.setattr(
        worker,
        "process_job",
        lambda *args: {
            "new": 0,
            "changed": 0,
            "unchanged": 1,
            "latest_publication_date": None,
        },
    )
    recovered = runtime.check_sources([definition["id"]])
    assert recovered["all_succeeded"] is True
    assert recovered["checks"][0]["job_id"] == first["checks"][0]["job_id"]
    assert recovered["checks"][0]["health"]["error"] is None
    assert recovered["checks"][0]["health"]["status"] == "Checked—No Change"


def test_runtime_rejects_unknown_source_before_registry_mutation(db, monkeypatch):
    _, factory = db
    runtime, _, _ = _runtime_fixture(factory, monkeypatch)
    with pytest.raises(ValueError, match="known enabled"):
        runtime.check_sources(["unknown-source"])
    with factory() as session:
        source = session.get(Source, "synthetic-test-source")
        assert source and source.publisher == "Synthetic Fixture"
        assert session.scalar(select(func.count()).select_from(Job)) == 0
