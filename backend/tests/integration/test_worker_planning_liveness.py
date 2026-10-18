import logging
import threading
import time
from datetime import UTC, datetime

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.persistence.database import Base
from gridlens.persistence.models import Job, PlannerState, Source, WorkerHeartbeat
from gridlens.settings import settings


@pytest.fixture
def worker_db(monkeypatch):
    import gridlens.jobs.worker as worker

    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and target.database.endswith("_test")
    assert (target.host, target.port, target.database) != (
        application.host,
        application.port,
        application.database,
    )
    from sqlalchemy import create_engine

    engine = create_engine(settings.test_database_url, pool_size=8)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(worker, "WORKER_ID", "c4-liveness-fixture")
    monkeypatch.setattr(worker, "_PLANNER_RETRY_MONOTONIC", {})
    monkeypatch.setattr(worker, "_PLANNER_FAILURES", {})
    try:
        yield factory
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _await(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    pytest.fail("scheduler state did not advance before timeout")


def test_blocked_acquisition_does_not_block_planners_or_heartbeat(worker_db, monkeypatch, caplog):
    import gridlens.ingestion.service as ingestion
    import gridlens.jobs.worker as worker

    caplog.set_level(logging.ERROR, logger=worker.__name__)
    planner_failure_logged = threading.Event()
    original_exception = worker.logger.exception

    def observe_planner_failure(message, *args, **kwargs):
        if message.startswith("planner %s failed") and args and args[0] == "sources":
            planner_failure_logged.set()
        original_exception(message, *args, **kwargs)

    monkeypatch.setattr(worker.logger, "exception", observe_planner_failure)

    factory = worker_db
    source_id = "c4-liveness-source"
    definition = {
        "id": source_id,
        "publisher": "Synthetic scheduler fixture",
        "endpoint": "https://example.test/c4",
        "family": "synthetic",
        "geography": "US",
        "industries": ["mining"],
        "retrieval_method": "json-api",
        "cadence_hours": 24,
        "enabled": True,
    }
    with factory.begin() as session:
        session.add(
            Source(
                id=source_id,
                publisher=definition["publisher"],
                endpoint=definition["endpoint"],
                family=definition["family"],
                geography=definition["geography"],
                industries=definition["industries"],
                retrieval_method=definition["retrieval_method"],
                cadence_hours=24,
                enabled=True,
                registry_enabled=True,
                health={},
            )
        )
        session.flush()
        job = Job(source_id=source_id, kind="ingestion", status="queued")
        session.add(job)
        session.flush()
        job_id = job.id

    entered = threading.Event()
    release = threading.Event()

    def blocked_retrieval(*_args, **_kwargs):
        entered.set()
        assert release.wait(5), "test did not release blocked acquisition"
        return []

    monkeypatch.setattr(ingestion, "retrieve_source", blocked_retrieval)
    monkeypatch.setattr(worker, "load_registry", lambda: [definition])
    monkeypatch.setattr(settings, "worker_auto_refresh", True)
    monkeypatch.setattr(settings, "autonomous_research_enabled", True)
    monkeypatch.setattr(settings, "monitoring_enabled", False)
    monkeypatch.setattr(worker, "refresh_due", lambda: (_ for _ in ()).throw(ValueError("fixture")))
    monkeypatch.setattr(worker, "plan_pursuit_questions", lambda: 0)
    monkeypatch.setattr(worker, "_HEARTBEAT_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(worker, "_PLANNER_POLL_SECONDS", 0.05)
    monkeypatch.setattr(worker, "_SHUTDOWN_JOIN_SECONDS", 0.1)

    stop = threading.Event()
    controller = threading.Thread(
        target=worker._run_worker_lanes,
        args=(stop, {source_id: definition}),
        name="c4-test-controller",
    )
    controller.start()
    job_thread = None
    try:
        assert entered.wait(5), "job lane did not reach source acquisition"

        def states():
            with factory() as session:
                return (
                    session.get(WorkerHeartbeat, worker.WORKER_ID),
                    session.get(PlannerState, "sources"),
                    session.get(PlannerState, "pursuit_questions"),
                )

        _await(lambda: all(states()))
        first_heartbeat = states()[0].last_seen_at
        _await(lambda: states()[0].last_seen_at > first_heartbeat)
        heartbeat, failed_source_planner, active_pursuit_planner = states()
        assert heartbeat.last_seen_at > first_heartbeat
        assert failed_source_planner.consecutive_failures == 1
        assert failed_source_planner.error_class == "ValueError"
        assert failed_source_planner.next_retry_at > datetime.now(UTC)
        assert active_pursuit_planner.last_success_at is not None
        assert planner_failure_logged.wait(5), "source planner failure was not logged"
        assert "planner sources failed" in caplog.text

        job_thread = next(
            thread for thread in threading.enumerate() if thread.name == "gridlens-job-execution"
        )
        stop.set()
        controller.join(timeout=1)
        assert not controller.is_alive(), "scheduler shutdown exceeded its finite join bound"
        assert job_thread.is_alive(), "blocked job should be reported rather than joined forever"
    finally:
        stop.set()
        release.set()
        controller.join(timeout=5)
        if job_thread is not None:
            job_thread.join(timeout=5)
    assert job_thread is not None and not job_thread.is_alive()
    with factory() as session:
        completed = session.get(Job, job_id)
        assert completed and completed.status == "succeeded"


def test_disabled_planner_flags_do_not_create_planner_lanes(worker_db, monkeypatch):
    import gridlens.jobs.worker as worker

    monkeypatch.setattr(settings, "worker_auto_refresh", False)
    monkeypatch.setattr(settings, "autonomous_research_enabled", True)
    monkeypatch.setattr(settings, "monitoring_enabled", False)
    monkeypatch.setattr(worker, "_HEARTBEAT_INTERVAL_SECONDS", 0.05)
    planner_calls = []
    monkeypatch.setattr(worker, "refresh_due", lambda: planner_calls.append("sources"))
    monkeypatch.setattr(
        worker, "plan_pursuit_questions", lambda: planner_calls.append("pursuit_questions")
    )
    monkeypatch.setattr(
        worker, "plan_monitoring_jobs", lambda: planner_calls.append("project_monitoring")
    )
    monkeypatch.setattr(worker, "run_one", lambda _definitions: False)
    stop = threading.Event()
    lanes = worker._worker_lane_specs(stop, {})
    assert [name for name, _target, _args in lanes] == [
        "gridlens-heartbeat",
        "gridlens-job-execution",
    ]
    controller = threading.Thread(
        target=worker._run_worker_lanes,
        args=(stop, {}),
        name="c4-disabled-test-controller",
    )
    controller.start()
    try:
        _await(
            lambda: _heartbeat_exists(worker_db, worker.WORKER_ID),
        )
    finally:
        stop.set()
        controller.join(timeout=5)
    assert not controller.is_alive()
    assert planner_calls == []
    with worker_db() as session:
        assert session.get(PlannerState, "sources") is None
        assert session.get(PlannerState, "pursuit_questions") is None
        assert session.get(PlannerState, "project_monitoring") is None


def _heartbeat_exists(factory, worker_id):
    with factory() as session:
        return session.get(WorkerHeartbeat, worker_id) is not None
