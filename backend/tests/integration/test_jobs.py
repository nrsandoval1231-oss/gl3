import json
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


def test_health_reports_unknown_when_source_has_no_health_status(db, monkeypatch):
    _, factory = db
    with factory.begin() as session:
        source = session.get(Source, "synthetic-test-source")
        assert source is not None
        source.health = {}

    from fastapi.testclient import TestClient

    import gridlens.api.app as api
    from gridlens.security import token_for

    monkeypatch.setattr(api, "SessionLocal", factory)
    monkeypatch.setattr(
        api,
        "load_registry",
        lambda: [{"id": "synthetic-test-source", "enabled": True}],
    )
    client = TestClient(api.app, raise_server_exceptions=False)
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    response = client.get("/api/health")
    assert response.status_code == 200
    source_health = response.json()["sources"][0]
    assert source_health["status"] == "Unknown"
    assert source_health["freshness"] == "UNKNOWN"


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


def test_managed_scheduler_delegates_to_due_ledger(db, monkeypatch):
    import gridlens.jobs.refresh_sources as scheduler
    import gridlens.jobs.worker as worker

    values = iter((1, 0))
    monkeypatch.setattr(worker, "refresh_due", lambda: next(values))
    assert scheduler.enqueue_daily_sources() == 1
    assert scheduler.enqueue_daily_sources() == 0


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
    monkeypatch.setattr(
        worker,
        "load_registry",
        lambda: [{"id": "synthetic-test-source", "enabled": True}],
    )
    monkeypatch.setattr(api, "SessionLocal", factory)
    monkeypatch.setattr(
        api,
        "load_registry",
        lambda: [{"id": "synthetic-test-source", "enabled": True}],
    )
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
    # Unreviewed parser text is never persisted; only the allowlisted message is.
    assert source["error"] == "Acquisition source response could not be parsed"
    assert source["last_success"] == "retained"
    assert source["new_records"] == 0
    with factory() as session:
        assert session.scalar(select(Job.status)) == "failed"


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


def test_bounded_routing_rank_is_policy_bound_and_preserves_age_fairness(db, monkeypatch):
    _, factory = db
    monkeypatch.setattr(settings, "intelligence_mode", "bounded_routing")
    monkeypatch.setattr(settings, "intelligence_enabled", True)
    monkeypatch.setattr(settings, "intelligence_research_enabled", True)
    monkeypatch.setattr(settings, "intelligence_typesafe_enabled", True)
    monkeypatch.setattr(settings, "intelligence_routing_policy_id", "policy-reviewed-7")
    monkeypatch.setattr(settings, "intelligence_routing_policy_evaluated", True)
    monkeypatch.setattr(settings, "intelligence_bounded_routing_authorized", True)
    monkeypatch.setattr(settings, "intelligence_max_active_calls", 1)
    monkeypatch.setattr(settings, "intelligence_max_call_usd", 1)
    for scope in ("global", "provider", "model", "source", "project"):
        for period in ("daily", "monthly"):
            monkeypatch.setattr(settings, f"intelligence_{scope}_{period}_calls", 1)
            monkeypatch.setattr(settings, f"intelligence_{scope}_{period}_usd", 1)
    now = datetime.now(UTC)

    def checkpoint(rank: int, policy_id: str) -> str:
        return json.dumps(
            {
                "task_type": "RESEARCH_PRIORITY_V1",
                "status": "queued",
                "routing_priority": {
                    "rank": rank,
                    "policy_id": policy_id,
                    "evaluated": True,
                    "authorized": True,
                    "evaluation_job_id": "00000000-0000-0000-0000-000000000001",
                    "evaluation_call_id": "00000000-0000-0000-0000-000000000002",
                    "request_digest": "d" * 64,
                },
            }
        )

    with factory.begin() as session:
        aged = Job(
            source_id="synthetic-test-source",
            kind="ingestion",
            status="queued",
            available_at=now,
            created_at=now - timedelta(days=2),
        )
        ordinary = Job(
            source_id="synthetic-test-source",
            kind="intelligence_process",
            status="queued",
            checkpoint=checkpoint(1, "wrong-policy"),
            available_at=now,
            created_at=now - timedelta(seconds=3),
        )
        lower_rank = Job(
            source_id="synthetic-test-source",
            kind="intelligence_process",
            status="queued",
            checkpoint=checkpoint(4, "policy-reviewed-7"),
            available_at=now,
            created_at=now - timedelta(seconds=2),
        )
        higher_rank = Job(
            source_id="synthetic-test-source",
            kind="intelligence_process",
            status="queued",
            checkpoint=checkpoint(1, "policy-reviewed-7"),
            available_at=now,
            created_at=now - timedelta(seconds=1),
        )
        legacy_cursor = Job(
            source_id="synthetic-test-source",
            kind="ingestion",
            status="queued",
            checkpoint="legacy cursor is not JSON",
            available_at=now,
            created_at=now - timedelta(seconds=4),
        )
        malformed_rank = Job(
            source_id="synthetic-test-source",
            kind="intelligence_process",
            status="queued",
            checkpoint=json.dumps(
                {
                    "routing_priority": {
                        "rank": "oops",
                        "policy_id": "policy-reviewed-7",
                        "evaluated": "true",
                        "authorized": True,
                        "evaluation_job_id": "job",
                        "evaluation_call_id": "call",
                        "request_digest": "d" * 64,
                    }
                }
            ),
            available_at=now,
            created_at=now + timedelta(seconds=1),
        )
        fractional_rank = Job(
            source_id="synthetic-test-source",
            kind="intelligence_process",
            status="queued",
            checkpoint=json.dumps(
                {
                    "routing_priority": {
                        "rank": 2.5,
                        "policy_id": "policy-reviewed-7",
                        "evaluated": True,
                        "authorized": True,
                        "evaluation_job_id": "job",
                        "evaluation_call_id": "call",
                        "request_digest": "d" * 64,
                    }
                }
            ),
            available_at=now,
            created_at=now + timedelta(seconds=2),
        )
        session.add_all(
            [
                aged,
                ordinary,
                lower_rank,
                higher_rank,
                legacy_cursor,
                malformed_rank,
                fractional_rank,
            ]
        )
        session.flush()
        expected_ids = [
            aged.id,
            higher_rank.id,
            lower_rank.id,
            legacy_cursor.id,
            ordinary.id,
            malformed_rank.id,
            fractional_rank.id,
        ]
    actual_ids = []
    for worker_number in range(len(expected_ids)):
        with factory.begin() as session:
            leased, _ = lease_one(session, f"rank-worker-{worker_number}")
            actual_ids.append(leased.id)
    assert actual_ids == expected_ids


def test_bounded_routing_hint_is_ignored_when_provider_killed(db, monkeypatch):
    _, factory = db
    monkeypatch.setattr(settings, "intelligence_mode", "bounded_routing")
    monkeypatch.setattr(settings, "intelligence_enabled", True)
    monkeypatch.setattr(settings, "intelligence_research_enabled", True)
    monkeypatch.setattr(settings, "intelligence_typesafe_enabled", False)
    monkeypatch.setattr(settings, "intelligence_openai_enabled", False)
    monkeypatch.setattr(settings, "intelligence_routing_policy_id", "policy-reviewed-7")
    monkeypatch.setattr(settings, "intelligence_routing_policy_evaluated", True)
    monkeypatch.setattr(settings, "intelligence_bounded_routing_authorized", True)
    monkeypatch.setattr(settings, "intelligence_max_active_calls", 1)
    monkeypatch.setattr(settings, "intelligence_max_call_usd", 1)
    for scope in ("global", "provider", "model", "source", "project"):
        for period in ("daily", "monthly"):
            monkeypatch.setattr(settings, f"intelligence_{scope}_{period}_calls", 1)
            monkeypatch.setattr(settings, f"intelligence_{scope}_{period}_usd", 1)
    now = datetime.now(UTC)

    def checkpoint(rank: int) -> str:
        return json.dumps(
            {
                "routing_priority": {
                    "rank": rank,
                    "policy_id": "policy-reviewed-7",
                    "evaluated": True,
                    "authorized": True,
                    "evaluation_job_id": "job",
                    "evaluation_call_id": "call",
                    "request_digest": "d" * 64,
                }
            }
        )

    with factory.begin() as session:
        older_rank_4 = Job(
            source_id="synthetic-test-source",
            kind="intelligence_process",
            status="queued",
            checkpoint=checkpoint(4),
            available_at=now,
            created_at=now - timedelta(seconds=2),
        )
        newer_rank_1 = Job(
            source_id="synthetic-test-source",
            kind="intelligence_process",
            status="queued",
            checkpoint=checkpoint(1),
            available_at=now,
            created_at=now - timedelta(seconds=1),
        )
        session.add_all([older_rank_4, newer_rank_1])
        session.flush()
        expected_id = older_rank_4.id
    with factory.begin() as session:
        leased, _ = lease_one(session, "provider-kill-worker")
    assert leased.id == expected_id


def test_scoped_worker_leaves_other_jobs_and_expired_leases_untouched(db):
    _, factory = db
    with factory.begin() as session:
        selected = Job(
            source_id="synthetic-test-source",
            available_at=datetime.now(UTC) - timedelta(seconds=1),
        )
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
    import httpx

    def fail(*args, **kwargs):
        raise httpx.ConnectError("synthetic temporary network failure")

    monkeypatch.setattr(worker, "process_job", fail)
    with factory.begin() as session:
        job_id = enqueue(session, definition["id"])
        queued = session.get(Job, job_id)
        assert queued is not None
        queued.available_at = datetime.now(UTC) - timedelta(seconds=1)
    first = runtime.check_sources([definition["id"], definition["id"]])
    assert len(first["checks"]) == 1
    assert first["all_succeeded"] is False
    assert first["checks"][0]["health"]["last_success"] == "retained"
    assert first["checks"][0]["health"]["error"] == ("Source acquisition failed: network_error")
    assert first["checks"][0]["health"]["error_code"] == "network_error"
    deferred = runtime.check_sources([definition["id"]])
    assert deferred["all_succeeded"] is False
    assert deferred["checks"][0]["attempted"] is False
    assert deferred["checks"][0]["attempts"] == 1
    with factory.begin() as session:
        job = session.scalar(select(Job))
        assert job is not None
        job.available_at = datetime.now(UTC) - timedelta(seconds=1)
        source = session.get(Source, definition["id"])
        assert source is not None
        source.health = {**source.health, "retry_at": "2000-01-01T00:00:00+00:00"}
    monkeypatch.setattr(
        worker,
        "process_job",
        lambda *args, **kwargs: {
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
