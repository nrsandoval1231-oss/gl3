import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, func, select, text
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
    SourceScheduleProgress,
    WorkerHeartbeat,
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
        "schedule_mode": "local_daily",
        "timezone": "America/Chicago",
        "schedule_anchor_time": "07:00:00",
        "enabled": enabled,
    }


def _window_start_utc(now: datetime) -> datetime:
    local_today = now.astimezone(ZoneInfo("America/Chicago")).date()
    local_start = datetime.combine(
        local_today - timedelta(days=6), datetime.min.time(), tzinfo=ZoneInfo("America/Chicago")
    )
    return local_start.astimezone(UTC)


def _record_receipt(session, epoch, scheduled_for, *, disposition="succeeded") -> str:
    import gridlens.jobs.worker as worker

    counts = (
        {
            "new": 0,
            "changed": 0,
            "unchanged": 1,
            "schedule_proof_version": 1,
            "acquisition_started_at": scheduled_for.isoformat(),
            "acquisition_completed_at": (scheduled_for + timedelta(seconds=1)).isoformat(),
        }
        if disposition in {"succeeded", "partial"}
        else {"error_class": "FixtureFailure"}
    )
    job_status = "failed" if disposition == "failed" else "succeeded"
    job = Job(source_id=epoch.source_id, status=job_status, fence=1)
    session.add(job)
    session.flush()
    due_key = worker._due_key(epoch, scheduled_for)
    due = SourceDueCheck(
        due_key=due_key,
        source_id=epoch.source_id,
        epoch_id=epoch.id,
        scheduled_for=scheduled_for,
        local_day=scheduled_for.astimezone(ZoneInfo("America/Chicago")).date(),
        configuration=epoch.configuration,
        job_id=job.id,
    )
    session.add(due)
    session.flush()
    canonical = json.dumps(counts, sort_keys=True, separators=(",", ":"), default=str)
    session.add(
        SourceCheckReceipt(
            due_key=due_key,
            job_id=job.id,
            fence=1,
            disposition=disposition,
            check_counts=counts,
            digest=hashlib.sha256(canonical.encode()).hexdigest(),
            recorded_at=scheduled_for + timedelta(seconds=2),
        )
    )
    return due_key


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


def test_retired_source_enablement_and_refresh_routes_return_not_found():
    from fastapi.testclient import TestClient

    import gridlens.api.app as api
    from gridlens.security import token_for

    client = TestClient(api.app, base_url="https://testserver")
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    assert (
        client.post(
            "/api/sources/synthetic-scheduled-source/enabled", json={"enabled": True}
        ).status_code
        == 404
    )
    assert client.post("/api/refresh", json={}).status_code == 404


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


def test_operator_enable_reconciles_persisted_registry_disable(source_db, monkeypatch):
    import gridlens.api.app as api
    import gridlens.jobs.worker as worker
    from gridlens.jobs.queue import enqueue

    factory = source_db
    registry = [definition(enabled=True)]
    monkeypatch.setattr(api, "SessionLocal", factory)
    monkeypatch.setattr(api, "load_registry", lambda: registry)
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(worker, "load_registry", lambda: registry)
    now = datetime.now(UTC)
    with factory.begin() as session:
        source = session.get(Source, "synthetic-scheduled-source")
        assert source
        source.enabled = True
        source.registry_enabled = False
        source.health = {"status": "Updated", "last_attempt": now.isoformat()}
        session.add(
            SourceScheduleEpoch(
                source_id=source.id,
                registry_enabled=False,
                operator_enabled=True,
                effective_from=now - timedelta(days=10),
                cadence_hours=24,
                schedule_mode="local_daily",
                timezone="America/Chicago",
                anchor={
                    "local_date": (now - timedelta(days=10))
                    .astimezone(ZoneInfo("America/Chicago"))
                    .date()
                    .isoformat(),
                    "local_time": "03:00",
                },
                configuration=definition(enabled=False),
                history_known=True,
            )
        )
        session.add(Job(source_id=source.id, status="queued"))

    before = api.health()["sources"][0]
    assert before["enabled"] is False
    assert before["freshness"] == "DISABLED"
    with factory.begin() as session:
        with pytest.raises(ValueError, match="disabled"):
            enqueue(session, "synthetic-scheduled-source")
    with factory.begin() as session:
        assert lease_one(session, "disabled-source-worker") is None

    worker.set_source_enabled("synthetic-scheduled-source", True)
    assert api.health()["sources"][0]["enabled"] is True
    with factory.begin() as session:
        assert enqueue(session, "synthetic-scheduled-source")
    with factory.begin() as session:
        assert lease_one(session, "reconciled-registry-worker") is not None


@pytest.mark.parametrize("drift", ["registry_disabled", "endpoint_changed"])
def test_operator_transition_reconciles_unsynced_registry_drift(source_db, monkeypatch, drift):
    import gridlens.api.app as api
    import gridlens.jobs.worker as worker
    from gridlens.jobs.queue import enqueue

    factory = source_db
    registry = [definition()]
    monkeypatch.setattr(api, "SessionLocal", factory)
    monkeypatch.setattr(api, "load_registry", lambda: registry)
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(worker, "load_registry", lambda: registry)
    worker.sync_registry()

    def load_registry_while_target_locked():
        with factory.begin() as session:
            lock_available = session.scalar(
                text("SELECT pg_try_advisory_xact_lock(hashtextextended(:source_id, 0))"),
                {"source_id": "synthetic-scheduled-source"},
            )
            assert lock_available is False
        return registry

    monkeypatch.setattr(worker, "load_registry", load_registry_while_target_locked)
    with factory.begin() as session:
        source = session.get(Source, "synthetic-scheduled-source")
        assert source
        original_epoch = session.scalar(select(SourceScheduleEpoch))
        assert original_epoch and original_epoch.history_known
        original_epoch_id = original_epoch.id
        source.health = {"status": "Updated", "last_attempt": datetime.now(UTC).isoformat()}
        session.add(Job(source_id=source.id, status="queued"))

    current = definition(enabled=drift != "registry_disabled")
    if drift == "endpoint_changed":
        current["endpoint"] = "https://example.invalid/changed"
    registry[0] = current
    worker.set_source_enabled("synthetic-scheduled-source", True)
    expected_enabled = drift == "endpoint_changed"

    with factory() as session:
        source = session.get(Source, "synthetic-scheduled-source")
        old_epoch = session.get(SourceScheduleEpoch, original_epoch_id)
        epochs = session.scalars(
            select(SourceScheduleEpoch).where(
                SourceScheduleEpoch.source_id == "synthetic-scheduled-source"
            )
        ).all()
        current_epoch = next(epoch for epoch in epochs if epoch.effective_until is None)
        assert source and source.registry_enabled is expected_enabled and source.enabled
        assert old_epoch and not old_epoch.history_known
        assert current_epoch.history_known
        assert current_epoch.registry_enabled is expected_enabled
        assert current_epoch.configuration["endpoint"] == current["endpoint"]
        assert len(epochs) == 2
    health = api.health()["sources"][0]
    assert health["enabled"] is expected_enabled
    assert health["freshness"] == ("UNKNOWN" if expected_enabled else "DISABLED")

    with factory.begin() as session:
        if expected_enabled:
            assert enqueue(session, "synthetic-scheduled-source")
        else:
            with pytest.raises(ValueError, match="disabled"):
                enqueue(session, "synthetic-scheduled-source")
    with factory.begin() as session:
        leased = lease_one(session, "operator-drift-worker")
        assert bool(leased) is expected_enabled


def test_unchanged_registry_operator_transition_is_idempotent_and_sticky(source_db, monkeypatch):
    import gridlens.jobs.worker as worker

    factory = source_db
    registry = [definition()]
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(worker, "load_registry", lambda: registry)
    worker.sync_registry()
    worker.set_source_enabled("synthetic-scheduled-source", False)

    def assert_known_operator_epoch(expected_count):
        with factory() as session:
            source = session.get(Source, "synthetic-scheduled-source")
            epochs = session.scalars(
                select(SourceScheduleEpoch).where(
                    SourceScheduleEpoch.source_id == "synthetic-scheduled-source"
                )
            ).all()
            assert source and not source.enabled and source.registry_enabled
            assert len(epochs) == expected_count
            assert all(epoch.history_known for epoch in epochs)
            open_epochs = [epoch for epoch in epochs if epoch.effective_until is None]
            assert len(open_epochs) == 1
            assert not open_epochs[0].operator_enabled

    assert_known_operator_epoch(2)
    worker.set_source_enabled("synthetic-scheduled-source", False)
    assert_known_operator_epoch(2)
    worker.sync_registry()
    assert_known_operator_epoch(2)


def test_invalid_live_registry_leaves_operator_transition_atomic(source_db, monkeypatch):
    import gridlens.jobs.worker as worker

    factory = source_db
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(worker, "load_registry", lambda: [definition()])
    worker.sync_registry()
    with factory() as session:
        before_source = session.get(Source, "synthetic-scheduled-source")
        before_epoch = session.scalar(select(SourceScheduleEpoch))
        assert before_source and before_epoch
        before = (
            before_source.enabled,
            before_source.registry_enabled,
            before_source.endpoint,
            before_epoch.id,
            before_epoch.history_known,
        )

    def invalid_registry():
        raise ValueError("invalid source registry")

    monkeypatch.setattr(worker, "load_registry", invalid_registry)
    with pytest.raises(ValueError, match="invalid source registry"):
        worker.set_source_enabled("synthetic-scheduled-source", False)
    with factory() as session:
        source = session.get(Source, "synthetic-scheduled-source")
        epoch = session.scalar(select(SourceScheduleEpoch))
        assert source and epoch
        assert (
            source.enabled,
            source.registry_enabled,
            source.endpoint,
            epoch.id,
            epoch.history_known,
        ) == before


def test_stopped_worker_cannot_look_fresh_with_unreconciled_due_slots(source_db, monkeypatch):
    import gridlens.api.app as api
    import gridlens.jobs.worker as worker

    factory = source_db
    now = datetime.now(UTC)
    monkeypatch.setattr(api, "SessionLocal", factory)
    monkeypatch.setattr(api, "load_registry", lambda: [definition()])
    with factory.begin() as session:
        source = session.get(Source, "synthetic-scheduled-source")
        assert source
        source.health = {"status": "Updated", "last_attempt": now.isoformat()}
        epoch_start = now - timedelta(days=10)
        epoch = SourceScheduleEpoch(
            source_id=source.id,
            registry_enabled=True,
            operator_enabled=True,
            effective_from=epoch_start,
            cadence_hours=24,
            schedule_mode="local_daily",
            timezone="America/Chicago",
            anchor={
                "local_date": epoch_start.astimezone(ZoneInfo("America/Chicago"))
                .date()
                .isoformat(),
                "local_time": "03:00",
            },
            configuration=definition(),
            history_known=True,
        )
        session.add(epoch)
        session.flush()
        expected_slots = list(
            worker._scheduled_instants(epoch, now, not_before=_window_start_utc(now))
        )
        assert len(expected_slots) >= 6
        _record_receipt(session, epoch, expected_slots[0])
        session.add(
            WorkerHeartbeat(
                worker_id="stopped-source-worker",
                last_seen_at=now - timedelta(minutes=10),
            )
        )

    status = api.health()
    source_status = status["sources"][0]
    assert source_status["freshness"] == "OVERDUE"
    assert source_status["due_checks_7d"] == len(expected_slots)
    assert source_status["verified_successes_7d"] == 1
    assert status["worker_liveness"] == "STALE"
    assert status["collection_freshness"] == "OVERDUE"
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(SourceDueCheck)) == 1
        assert session.scalar(select(func.count()).select_from(Job)) == 1
        assert session.scalar(select(func.count()).select_from(SourceCheckReceipt)) == 1


def test_expected_schedule_enumeration_is_bounded_to_health_window():
    import gridlens.jobs.worker as worker

    now = datetime.now(UTC)
    epoch_start = now - timedelta(days=3650)
    epoch = SourceScheduleEpoch(
        source_id="old-hourly-source",
        effective_from=epoch_start,
        effective_until=None,
        cadence_hours=1,
        schedule_mode="utc_hourly",
        timezone="America/Chicago",
        anchor={"utc": epoch_start.isoformat()},
    )
    slots = list(worker._scheduled_instants(epoch, now, not_before=_window_start_utc(now)))

    assert len(slots) <= 168
    assert slots
    assert slots[0] >= _window_start_utc(now)


def test_bounded_local_daily_enumeration_preserves_anchor_phase():
    import gridlens.jobs.worker as worker

    now = datetime(2026, 10, 12, 12, tzinfo=UTC)
    epoch = SourceScheduleEpoch(
        source_id="every-other-day-source",
        effective_from=datetime(2026, 10, 1, 8, tzinfo=UTC),
        effective_until=None,
        cadence_hours=48,
        schedule_mode="local_daily",
        timezone="America/Chicago",
        anchor={"local_date": "2026-10-01", "local_time": "03:00"},
    )
    slots = list(worker._scheduled_instants(epoch, now, not_before=_window_start_utc(now)))
    local_days = [slot.astimezone(ZoneInfo("America/Chicago")).date().isoformat() for slot in slots]

    assert local_days == ["2026-10-07", "2026-10-09", "2026-10-11"]


@pytest.mark.parametrize("cadence", [36, True])
def test_local_daily_scheduler_rejects_unrepresentable_cadence(cadence):
    import gridlens.jobs.worker as worker

    now = datetime(2026, 10, 12, 12, tzinfo=UTC)
    epoch = SourceScheduleEpoch(
        source_id="invalid-local-cadence-source",
        effective_from=datetime(2026, 10, 1, 8, tzinfo=UTC),
        effective_until=None,
        cadence_hours=cadence,
        schedule_mode="local_daily",
        timezone="America/Chicago",
        anchor={"local_date": "2026-10-01", "local_time": "03:00"},
    )
    with pytest.raises(ValueError, match="cadence"):
        list(worker._scheduled_instants(epoch, now))


def test_missing_schedule_history_never_claims_fresh(source_db, monkeypatch):
    import gridlens.api.app as api

    monkeypatch.setattr(api, "SessionLocal", source_db)
    monkeypatch.setattr(api, "load_registry", lambda: [definition()])
    with source_db.begin() as session:
        source = session.get(Source, "synthetic-scheduled-source")
        assert source
        now = datetime.now(UTC)
        source.health = {"status": "Updated", "last_attempt": now.isoformat()}

    status = api.health()

    assert status["sources"][0]["freshness"] == "UNKNOWN"
    assert status["sources"][0]["due_checks_7d"] == 0
    assert status["collection_freshness"] == "UNKNOWN"


@pytest.mark.parametrize("tamper", ["receipt_digest", "job_fence"])
def test_freshness_requires_matching_fenced_complete_receipt(source_db, monkeypatch, tamper):
    import gridlens.api.app as api
    import gridlens.jobs.worker as worker

    factory = source_db
    now = datetime.now(UTC)
    monkeypatch.setattr(api, "SessionLocal", factory)
    monkeypatch.setattr(api, "load_registry", lambda: [definition()])
    with factory.begin() as session:
        source = session.get(Source, "synthetic-scheduled-source")
        assert source
        source.health = {"status": "Updated", "last_attempt": now.isoformat()}
        epoch_start = now - timedelta(days=10)
        epoch = SourceScheduleEpoch(
            source_id=source.id,
            registry_enabled=True,
            operator_enabled=True,
            effective_from=epoch_start,
            cadence_hours=24,
            schedule_mode="local_daily",
            timezone="America/Chicago",
            anchor={
                "local_date": epoch_start.astimezone(ZoneInfo("America/Chicago"))
                .date()
                .isoformat(),
                "local_time": "03:00",
            },
            configuration=definition(),
            history_known=True,
        )
        session.add(epoch)
        session.flush()
        scheduled_slots = list(
            worker._scheduled_instants(epoch, now, not_before=_window_start_utc(now))
        )
        due_key = _record_receipt(session, epoch, scheduled_slots[0])

    with factory.begin() as session:
        receipt = session.scalar(
            select(SourceCheckReceipt).where(SourceCheckReceipt.due_key == due_key)
        )
        assert receipt
        if tamper == "receipt_digest":
            receipt.digest = "0" * 64
        else:
            job = session.get(Job, receipt.job_id)
            assert job
            job.fence += 1

    status = api.health()

    assert status["sources"][0]["freshness"] == "UNKNOWN"
    assert status["sources"][0]["verified_successes_7d"] == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cadence_hours", 0),
        ("cadence_hours", 36),
        ("timezone", "Invalid/Zone"),
        ("anchor", {"local_date": "2026-10-01", "local_time": "not-a-time"}),
    ],
)
def test_invalid_schedule_parameters_keep_health_unknown(source_db, monkeypatch, field, value):
    import gridlens.api.app as api

    factory = source_db
    now = datetime.now(UTC)
    monkeypatch.setattr(api, "SessionLocal", factory)
    monkeypatch.setattr(api, "load_registry", lambda: [definition()])
    with factory.begin() as session:
        source = session.get(Source, "synthetic-scheduled-source")
        assert source
        source.health = {"status": "Updated", "last_attempt": now.isoformat()}
        epoch_start = now - timedelta(days=10)
        epoch = SourceScheduleEpoch(
            source_id=source.id,
            registry_enabled=True,
            operator_enabled=True,
            effective_from=epoch_start,
            cadence_hours=24,
            schedule_mode="local_daily",
            timezone="America/Chicago",
            anchor={
                "local_date": epoch_start.astimezone(ZoneInfo("America/Chicago"))
                .date()
                .isoformat(),
                "local_time": "03:00",
            },
            configuration=definition(),
            history_known=True,
        )
        setattr(epoch, field, value)
        session.add(epoch)

    status = api.health()
    assert status["sources"][0]["freshness"] == "UNKNOWN"
    assert status["collection_freshness"] == "UNKNOWN"


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
        completed_slots = list(
            worker._scheduled_instants(epoch, now, not_before=_window_start_utc(now))
        )
        assert len(completed_slots) >= 6
        for scheduled_for in completed_slots:
            _record_receipt(session, epoch, scheduled_for)

    complete_status = api.health()
    assert complete_status["sources"][0]["freshness"] == "FRESH"
    assert complete_status["sources"][0]["due_checks_7d"] >= 6
    assert (
        complete_status["sources"][0]["verified_successes_7d"]
        == complete_status["sources"][0]["due_checks_7d"]
    )
    registry = [{**definition(), "endpoint": "https://example.invalid/revised"}]
    with factory() as session:
        due_count_before_drift = session.scalar(select(func.count()).select_from(SourceDueCheck))
        epoch_count_before_drift = session.scalar(
            select(func.count()).select_from(SourceScheduleEpoch)
        )
    unobserved_drift_status = api.health()
    assert unobserved_drift_status["sources"][0]["freshness"] == "UNKNOWN"
    assert unobserved_drift_status["sources"][0]["enabled"] is True
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(SourceDueCheck)) == (
            due_count_before_drift
        )
        assert session.scalar(select(func.count()).select_from(SourceScheduleEpoch)) == (
            epoch_count_before_drift
        )
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
        assert session.scalar(
            select(func.count())
            .select_from(SourceDueCheck)
            .where(SourceDueCheck.epoch_id == epochs[0].id)
        ) == len(completed_slots)
        assert (
            session.scalar(
                select(func.count())
                .select_from(SourceDueCheck)
                .where(SourceDueCheck.epoch_id == epochs[1].id)
            )
            >= 1
        )
    status = api.health()
    assert status["sources"][0]["freshness"] == "UNKNOWN"
    assert status["collection_freshness"] == "UNKNOWN"


@pytest.mark.parametrize(
    ("drift", "expected"),
    [
        ("industries_removed", "UNKNOWN"),
        ("cadence_removed", "UNKNOWN"),
        ("stored_timezone_missing", "UNKNOWN"),
        ("documented_schedule_defaults", "FRESH"),
    ],
)
def test_live_registry_comparison_does_not_hide_omitted_fields(
    source_db, monkeypatch, drift, expected
):
    import gridlens.api.app as api
    import gridlens.jobs.worker as worker

    factory = source_db
    now = datetime.now(UTC)
    original = definition()
    if drift == "cadence_removed":
        original["cadence_hours"] = 1
        original["schedule_mode"] = "utc_hourly"
    registry = [original]
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
        if epoch.schedule_mode == "utc_hourly":
            epoch.anchor = {
                "utc": (now - timedelta(days=10))
                .replace(minute=0, second=0, microsecond=0)
                .isoformat()
            }
        else:
            epoch.anchor = {
                "local_date": (now - timedelta(days=10))
                .astimezone(ZoneInfo("America/Chicago"))
                .date()
                .isoformat(),
                "local_time": "03:00",
            }
        if drift == "stored_timezone_missing":
            epoch.configuration = dict(epoch.configuration)
            epoch.configuration.pop("timezone")
        source.health = {"status": "Updated", "last_attempt": now.isoformat()}
        scheduled_slots = list(
            worker._scheduled_instants(epoch, now, not_before=_window_start_utc(now))
        )
        assert scheduled_slots
        for scheduled_for in scheduled_slots:
            _record_receipt(session, epoch, scheduled_for)

    assert api.health()["sources"][0]["freshness"] == "FRESH"
    if drift == "industries_removed":
        current = dict(original)
        current.pop("industries")
    elif drift == "cadence_removed":
        current = dict(original)
        current.pop("cadence_hours")
        current.pop("schedule_mode")
    elif drift == "documented_schedule_defaults":
        current = dict(original)
        for field in (
            "cadence_hours",
            "schedule_mode",
            "timezone",
            "schedule_anchor_time",
        ):
            current.pop(field)
    else:
        current = {**original, "timezone": "America/New_York"}
    registry[0] = current
    with factory() as session:
        due_count_before = session.scalar(select(func.count()).select_from(SourceDueCheck))
        epoch_count_before = session.scalar(select(func.count()).select_from(SourceScheduleEpoch))

    status = api.health()

    assert status["sources"][0]["freshness"] == expected, status
    assert status["collection_freshness"] == expected
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(SourceDueCheck)) == due_count_before
        assert session.scalar(select(func.count()).select_from(SourceScheduleEpoch)) == (
            epoch_count_before
        )


@pytest.mark.parametrize("omitted", ["cadence", "industries", "both"])
def test_validator_accepted_optional_registry_fields_sync_and_operator(
    source_db, monkeypatch, tmp_path, omitted
):
    import gridlens.api.app as api
    import gridlens.jobs.worker as worker
    from gridlens.ingestion.registry import load_registry

    factory = source_db
    source = next(item for item in load_registry() if item["id"] == "federal-register-eis")
    declared_industries = source["industries"]
    if omitted in {"cadence", "both"}:
        source.pop("cadence_hours")
    if omitted in {"industries", "both"}:
        source.pop("industries")
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"version": 1, "sources": [source]}), encoding="utf-8")
    registry = load_registry(path)

    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(worker, "load_registry", lambda: registry)
    monkeypatch.setattr(api, "SessionLocal", factory)
    monkeypatch.setattr(api, "load_registry", lambda: registry)

    worker.sync_registry()
    with factory() as session:
        row = session.get(Source, "federal-register-eis")
        epoch = session.scalar(
            select(SourceScheduleEpoch).where(
                SourceScheduleEpoch.source_id == "federal-register-eis",
                SourceScheduleEpoch.effective_until.is_(None),
            )
        )
        assert row and epoch
        assert row.cadence_hours == 24
        expected_industries = [] if omitted in {"industries", "both"} else declared_industries
        assert row.industries == expected_industries
        assert epoch.configuration.get("cadence_hours") == 24
        assert ("industries" in epoch.configuration) is ("industries" in source)

    with factory.begin() as session:
        epoch = session.scalar(
            select(SourceScheduleEpoch).where(
                SourceScheduleEpoch.source_id == "federal-register-eis",
                SourceScheduleEpoch.effective_until.is_(None),
            )
        )
        assert epoch
        # Prior accepted declarations could omit this default from the snapshot.
        epoch.configuration = dict(epoch.configuration)
        epoch.configuration.pop("cadence_hours", None)

    worker.sync_registry()
    with factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(SourceScheduleEpoch)
                .where(SourceScheduleEpoch.source_id == "federal-register-eis")
            )
            == 1
        )

    worker.set_source_enabled("federal-register-eis", False)
    health_source = api.health()["sources"][0]
    assert health_source["enabled"] is False

    worker.set_source_enabled("federal-register-eis", True)
    assert api.health()["sources"][0]["enabled"] is True

    with factory() as session:
        count_before_noop = session.scalar(
            select(func.count())
            .select_from(SourceScheduleEpoch)
            .where(SourceScheduleEpoch.source_id == "federal-register-eis")
        )
        current = session.scalar(
            select(SourceScheduleEpoch).where(
                SourceScheduleEpoch.source_id == "federal-register-eis",
                SourceScheduleEpoch.effective_until.is_(None),
            )
        )
        assert current and current.configuration.get("cadence_hours") == 24
        assert ("industries" in current.configuration) is ("industries" in source)

    worker.set_source_enabled("federal-register-eis", True)
    with factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(SourceScheduleEpoch)
                .where(SourceScheduleEpoch.source_id == "federal-register-eis")
            )
            == count_before_noop
        )


@pytest.mark.parametrize("previous_industries", [["environment"], []])
def test_omitted_industries_is_epoch_drift_but_omitted_cadence_is_equivalent(
    source_db, monkeypatch, tmp_path, previous_industries
):
    import gridlens.api.app as api
    import gridlens.jobs.worker as worker
    from gridlens.ingestion.registry import load_registry

    factory = source_db
    original = next(item for item in load_registry() if item["id"] == "federal-register-eis")
    original["industries"] = previous_industries
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps({"version": 1, "sources": [original]}), encoding="utf-8")
    registry = load_registry(registry_path)
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(api, "SessionLocal", factory)
    monkeypatch.setattr(worker, "load_registry", lambda: registry)
    monkeypatch.setattr(api, "load_registry", lambda: registry)
    worker.sync_registry()

    # An omitted default cadence is the same declaration as explicit 24 hours.
    registry[0].pop("cadence_hours")
    worker.sync_registry()
    with factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(SourceScheduleEpoch)
                .where(SourceScheduleEpoch.source_id == "federal-register-eis")
            )
            == 1
        )

    # Industries are different: absence is preserved in the epoch declaration.
    registry[0].pop("industries")
    worker.set_source_enabled("federal-register-eis", True)
    with factory() as session:
        epochs = session.scalars(
            select(SourceScheduleEpoch)
            .where(SourceScheduleEpoch.source_id == "federal-register-eis")
            .order_by(SourceScheduleEpoch.effective_from)
        ).all()
        assert len(epochs) == 2
        assert epochs[0].history_known is False
        assert epochs[1].history_known is True
        assert "industries" not in epochs[1].configuration
        assert epochs[1].configuration["cadence_hours"] == 24
        source = session.get(Source, "federal-register-eis")
        assert source and source.industries == [] and source.cadence_hours == 24

    worker.sync_registry()
    worker.set_source_enabled("federal-register-eis", True)
    with factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(SourceScheduleEpoch)
                .where(SourceScheduleEpoch.source_id == "federal-register-eis")
            )
            == 2
        )
        epochs = session.scalars(
            select(SourceScheduleEpoch)
            .where(SourceScheduleEpoch.source_id == "federal-register-eis")
            .order_by(SourceScheduleEpoch.effective_from)
        ).all()
        assert epochs[0].history_known is False
        assert epochs[1].history_known is True


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
        import gridlens.jobs.worker as worker

        scheduled_for = next(
            worker._scheduled_instants(epoch, now, not_before=_window_start_utc(now))
        )
        _record_receipt(session, epoch, scheduled_for, disposition=disposition)

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
    monkeypatch.setattr(pursuits, "process_research_job", lambda *args: research_calls.append(args))
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

    def process(session, job_id, worker_id, fence, source_definition, **_bounds):
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


def test_scheduler_advances_old_backlog_in_bounded_restarts(source_db):
    import gridlens.jobs.worker as worker

    factory = source_db
    now = datetime.now(UTC)
    old_start = now - timedelta(days=3650)
    with factory.begin() as session:
        session.add(
            SourceScheduleEpoch(
                source_id="synthetic-scheduled-source",
                registry_enabled=True,
                operator_enabled=True,
                effective_from=old_start,
                cadence_hours=1,
                schedule_mode="utc_hourly",
                timezone="UTC",
                anchor={"utc": old_start.isoformat()},
                configuration=definition(),
            )
        )
    with factory.begin() as session:
        first = worker._reconcile_due(session, now)
    assert 0 < first <= worker._SCHEDULE_RECENT_CAP + worker._SCHEDULE_HISTORY_CAP
    with factory() as session:
        progress = session.scalar(select(SourceScheduleProgress))
        assert progress and progress.history_cursor and progress.last_planned_at
        first_cursor = progress.history_cursor
        first_due_count = session.scalar(select(func.count()).select_from(SourceDueCheck))
        assert first_due_count == first
    with factory.begin() as session:
        second = worker._reconcile_due(session, now)
    with factory() as session:
        progress = session.scalar(select(SourceScheduleProgress))
        assert progress and progress.history_cursor > first_cursor
        assert second > 0 and second <= worker._SCHEDULE_HISTORY_CAP
        assert session.scalar(select(func.count()).select_from(SourceDueCheck)) == (
            first_due_count + second
        )


def test_ineligible_epochs_do_not_fill_bounded_planner_frontier(source_db, monkeypatch):
    import gridlens.jobs.worker as worker

    factory = source_db
    now = datetime.now(UTC)
    monkeypatch.setattr(worker, "_SCHEDULE_EPOCH_CAP", 1)
    with factory.begin() as session:
        source_id = "synthetic-scheduled-source"
        for index in range(70):
            epoch_start = now - timedelta(days=100 + index)
            session.add(
                SourceScheduleEpoch(
                    source_id=source_id,
                    registry_enabled=False,
                    operator_enabled=False,
                    effective_from=epoch_start,
                    effective_until=epoch_start + timedelta(days=1),
                    cadence_hours=24,
                    schedule_mode="local_daily",
                    timezone="America/Chicago",
                    anchor={"local_date": epoch_start.date().isoformat(), "local_time": "03:00"},
                    configuration=definition(enabled=False),
                    history_known=False,
                )
            )
        active_start = now - timedelta(days=2)
        active = SourceScheduleEpoch(
            source_id=source_id,
            registry_enabled=True,
            operator_enabled=True,
            effective_from=active_start,
            cadence_hours=24,
            schedule_mode="local_daily",
            timezone="America/Chicago",
            anchor={
                "local_date": active_start.astimezone(ZoneInfo("America/Chicago"))
                .date()
                .isoformat(),
                "local_time": "03:00",
            },
            configuration=definition(),
            history_known=True,
        )
        session.add(active)

    with factory.begin() as session:
        created = worker._reconcile_due(session, now)
    with factory() as session:
        progress = session.scalar(
            select(SourceScheduleProgress).where(SourceScheduleProgress.epoch_id == active.id)
        )
        assert created > 0
        assert progress and progress.last_planned_at


def test_assignment_ignores_stale_and_disabled_due_flood(source_db, monkeypatch):
    import gridlens.jobs.worker as worker

    factory = source_db
    now = datetime.now(UTC)
    source_id = "synthetic-scheduled-source"
    monkeypatch.setattr(worker, "load_registry", lambda: [definition()])
    with factory.begin() as session:
        active_start = now - timedelta(days=10)
        active = SourceScheduleEpoch(
            source_id=source_id,
            registry_enabled=True,
            operator_enabled=True,
            effective_from=active_start,
            cadence_hours=24,
            schedule_mode="local_daily",
            timezone="America/Chicago",
            anchor={
                "local_date": active_start.astimezone(ZoneInfo("America/Chicago"))
                .date()
                .isoformat(),
                "local_time": "03:00",
            },
            configuration=definition(),
            history_known=True,
        )
        session.add(active)
        session.flush()
        active_slots = list(worker._scheduled_instants(active, now))
        current_slot = active_slots[-1]
        old_end = now - timedelta(days=2)
        old = SourceScheduleEpoch(
            source_id=source_id,
            registry_enabled=True,
            operator_enabled=True,
            effective_from=now - timedelta(days=12),
            effective_until=old_end,
            cadence_hours=1,
            schedule_mode="utc_hourly",
            timezone="UTC",
            anchor={"utc": (now - timedelta(days=12)).isoformat()},
            configuration=definition(),
            history_known=True,
        )
        session.add(old)
        session.flush()
        old_slots = list(worker._scheduled_instants(old, old_end))[-101:]
        for slot in old_slots:
            due_key = worker._due_key(old, slot)
            session.add(
                SourceDueCheck(
                    due_key=due_key,
                    source_id=source_id,
                    epoch_id=old.id,
                    scheduled_for=slot,
                    local_day=slot.date(),
                    configuration=old.configuration,
                )
            )
        active_due_key = worker._due_key(active, current_slot)
        session.add(
            SourceDueCheck(
                due_key=active_due_key,
                source_id=source_id,
                epoch_id=active.id,
                scheduled_for=current_slot,
                local_day=current_slot.astimezone(ZoneInfo("America/Chicago")).date(),
                configuration=active.configuration,
            )
        )
        for index in range(101):
            disabled_id = f"disabled-scheduled-source-{index:03d}"
            disabled = Source(
                id=disabled_id,
                publisher="Fixture",
                endpoint="https://example.invalid/disabled",
                family="synthetic",
                geography="US",
                industries=[],
                retrieval_method="test",
                cadence_hours=24,
                enabled=False,
                registry_enabled=True,
                health={},
            )
            session.add(disabled)
            disabled_epoch = SourceScheduleEpoch(
                source_id=disabled_id,
                registry_enabled=True,
                operator_enabled=True,
                effective_from=active_start,
                cadence_hours=24,
                schedule_mode="local_daily",
                timezone="America/Chicago",
                anchor={"local_date": active_start.date().isoformat(), "local_time": "03:00"},
                configuration={"id": disabled_id},
                history_known=True,
            )
            session.add(disabled_epoch)
            session.flush()
            session.add(
                SourceDueCheck(
                    due_key=f"{index:064x}",
                    source_id=disabled_id,
                    epoch_id=disabled_epoch.id,
                    scheduled_for=now - timedelta(days=2),
                    local_day=(now - timedelta(days=2)).date(),
                    configuration=disabled_epoch.configuration,
                )
            )

    with factory.begin() as session:
        assigned = worker._assign_due_jobs(session)
    with factory.begin() as session:
        assigned_again = worker._assign_due_jobs(session)
    with factory() as session:
        active_due = session.get(SourceDueCheck, active_due_key)
        assert assigned == 1 and assigned_again == 0
        assert active_due and active_due.job_id
        old_rows = session.scalars(
            select(SourceDueCheck).where(SourceDueCheck.epoch_id == old.id)
        ).all()
        disabled_rows = session.scalars(
            select(SourceDueCheck).where(
                SourceDueCheck.source_id.like("disabled-scheduled-source-%")
            )
        ).all()
        assert len(old_rows) == 101 and all(row.job_id is None for row in old_rows)
        assert len(disabled_rows) == 101 and all(row.job_id is None for row in disabled_rows)


def test_assignment_uses_due_epoch_until_its_transition(source_db, monkeypatch):
    import gridlens.jobs.worker as worker

    factory = source_db
    now = datetime.now(UTC)
    source_id = "synthetic-scheduled-source"
    monkeypatch.setattr(worker, "load_registry", lambda: [definition()])
    with factory.begin() as session:
        epoch_start = now - timedelta(days=3)
        transition = now + timedelta(hours=1)
        epoch = SourceScheduleEpoch(
            source_id=source_id,
            registry_enabled=True,
            operator_enabled=True,
            effective_from=epoch_start,
            effective_until=transition,
            cadence_hours=24,
            schedule_mode="local_daily",
            timezone="America/Chicago",
            anchor={
                "local_date": epoch_start.astimezone(ZoneInfo("America/Chicago"))
                .date()
                .isoformat(),
                "local_time": "07:00:00",
            },
            configuration=definition(),
            history_known=True,
        )
        session.add(epoch)
        session.flush()
        scheduled_for = list(worker._scheduled_instants(epoch, now))[-1]
        due = SourceDueCheck(
            due_key=worker._due_key(epoch, scheduled_for),
            source_id=source_id,
            epoch_id=epoch.id,
            scheduled_for=scheduled_for,
            local_day=scheduled_for.astimezone(ZoneInfo("America/Chicago")).date(),
            configuration=epoch.configuration,
        )
        session.add(due)
        due_key = due.due_key

    with factory.begin() as session:
        assert worker._assign_due_jobs(session) == 1
    with factory() as session:
        due = session.get(SourceDueCheck, due_key)
        assert due and due.job_id


def test_epoch_planning_round_robin_prevents_source_starvation(source_db, monkeypatch):
    import gridlens.jobs.worker as worker

    factory = source_db
    now = datetime.now(UTC)
    monkeypatch.setattr(worker, "_SCHEDULE_EPOCH_CAP", 1)
    with factory.begin() as session:
        session.add(
            Source(
                id="second-scheduled-source",
                publisher="Fixture",
                endpoint="https://example.invalid/second",
                family="synthetic",
                geography="US",
                industries=[],
                retrieval_method="test",
                cadence_hours=24,
                enabled=True,
                registry_enabled=True,
                health={"status": "Overdue"},
            )
        )
        for source_id in ("synthetic-scheduled-source", "second-scheduled-source"):
            session.add(
                SourceScheduleEpoch(
                    source_id=source_id,
                    registry_enabled=True,
                    operator_enabled=True,
                    effective_from=now - timedelta(days=2),
                    cadence_hours=24,
                    schedule_mode="local_daily",
                    timezone="America/Chicago",
                    anchor={
                        "local_date": (now - timedelta(days=2))
                        .astimezone(ZoneInfo("America/Chicago"))
                        .date()
                        .isoformat(),
                        "local_time": "03:00",
                    },
                    configuration=definition(),
                )
            )
    for _ in range(2):
        with factory.begin() as session:
            worker._reconcile_due(session, now)
    with factory() as session:
        source_ids = set(session.scalars(select(SourceDueCheck.source_id)).all())
        assert source_ids == {"synthetic-scheduled-source", "second-scheduled-source"}


def test_assignment_never_binds_due_to_running_job(source_db, monkeypatch):
    import gridlens.jobs.worker as worker

    factory = source_db
    now = datetime.now(UTC)
    monkeypatch.setattr(worker, "load_registry", lambda: [definition()])
    with factory.begin() as session:
        source = session.get(Source, "synthetic-scheduled-source")
        assert source
        epoch = SourceScheduleEpoch(
            source_id=source.id,
            registry_enabled=True,
            operator_enabled=True,
            effective_from=now - timedelta(days=1),
            cadence_hours=24,
            schedule_mode="local_daily",
            timezone="America/Chicago",
            anchor={
                "local_date": (now - timedelta(days=1)).date().isoformat(),
                "local_time": "03:00",
            },
            configuration=definition(),
        )
        session.add(epoch)
        session.flush()
        due = SourceDueCheck(
            due_key="a" * 64,
            source_id=source.id,
            epoch_id=epoch.id,
            scheduled_for=now - timedelta(seconds=10),
            local_day=now.date(),
            configuration=definition(),
        )
        session.add(due)
        running = Job(
            source_id=source.id,
            status="running",
            lease_owner="worker",
            lease_until=now + timedelta(minutes=1),
        )
        session.add(running)
        session.flush()
        due_id = due.due_key

    with factory.begin() as session:
        assert worker._assign_due_jobs(session) == 0
    with factory() as session:
        assert session.get(SourceDueCheck, due_id).job_id is None


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


def test_planner_claim_serializes_worker_replicas(source_db, monkeypatch):
    import gridlens.jobs.worker as worker

    monkeypatch.setattr(worker, "SessionLocal", source_db)
    worker._PLANNER_RETRY_MONOTONIC.clear()
    worker._PLANNER_FAILURES.clear()
    entered_action = Event()
    finish_action = Event()
    calls = []

    def slow_action():
        calls.append("ran")
        entered_action.set()
        assert finish_action.wait(timeout=5)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_replica = pool.submit(worker._run_planner, "cross_replica", slow_action)
        assert entered_action.wait(timeout=5)

        # A second replica has no shared process-local retry state. It must be
        # held off by the PostgreSQL planner claim while the first action runs.
        worker._PLANNER_RETRY_MONOTONIC.clear()
        second_replica = pool.submit(
            worker._run_planner, "cross_replica", lambda: calls.append("duplicate")
        )
        assert second_replica.result(timeout=5) is False
        assert calls == ["ran"]
        finish_action.set()
        assert first_replica.result(timeout=5) is True

    # The session lock is explicitly released, but the successful planner
    # cadence still prevents an immediate duplicate cycle.
    assert worker._run_planner("cross_replica", lambda: calls.append("too_soon")) is False
    assert calls == ["ran"]


def test_planner_connection_failure_recovers_on_later_poll(source_db, monkeypatch):
    import gridlens.jobs.worker as worker

    factory = source_db
    engine = factory.kw["bind"]
    original_connect = engine.connect
    connection_attempts = []
    calls = []

    def fail_first_connect():
        connection_attempts.append("attempt")
        if len(connection_attempts) == 1:
            raise OSError("synthetic planner connection outage")
        return original_connect()

    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(engine, "connect", fail_first_connect)
    worker._PLANNER_RETRY_MONOTONIC.clear()
    worker._PLANNER_FAILURES.clear()

    assert not worker._run_planner("connection_recovery", lambda: calls.append("unexpected"))
    with factory.begin() as session:
        state = session.get(PlannerState, "connection_recovery")
        assert state and state.consecutive_failures == 1
        state.next_retry_at = datetime.now(UTC) - timedelta(seconds=1)

    worker._PLANNER_RETRY_MONOTONIC.clear()
    assert worker._run_planner("connection_recovery", lambda: calls.append("recovered"))
    assert calls == ["recovered"]


@pytest.mark.parametrize("cleanup_failure", ["rollback", "unlock", "close"])
def test_planner_cleanup_failure_does_not_block_a_later_cycle(
    source_db, monkeypatch, cleanup_failure
):
    import gridlens.jobs.worker as worker

    factory = source_db
    original_connect = worker._connect_planner_claim
    calls = []

    class FaultyConnection:
        def __init__(self, connection):
            self.connection = connection
            self.failed = False

        def scalar(self, statement, parameters=None):
            if cleanup_failure == "unlock" and "pg_advisory_unlock" in str(statement):
                self.failed = True
                raise OSError("synthetic unlock failure")
            return self.connection.scalar(statement, parameters)

        def commit(self):
            return self.connection.commit()

        def rollback(self):
            if cleanup_failure == "rollback" and not self.failed:
                self.failed = True
                raise OSError("synthetic rollback failure")
            return self.connection.rollback()

        def in_transaction(self):
            if cleanup_failure == "rollback" and not self.failed:
                return True
            return self.connection.in_transaction()

        def invalidate(self):
            return self.connection.invalidate()

        def close(self):
            self.connection.close()
            if cleanup_failure == "close" and not self.failed:
                self.failed = True
                raise OSError("synthetic close failure")

    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(
        worker,
        "_connect_planner_claim",
        lambda: FaultyConnection(original_connect()),
    )
    worker._PLANNER_RETRY_MONOTONIC.clear()
    worker._PLANNER_FAILURES.clear()

    assert not worker._run_planner("cleanup_recovery", lambda: calls.append("first"))
    with factory.begin() as session:
        state = session.get(PlannerState, "cleanup_recovery")
        assert state and state.last_success_at and state.next_retry_at
        state.next_retry_at = datetime.now(UTC) - timedelta(seconds=1)

    monkeypatch.setattr(worker, "_connect_planner_claim", original_connect)
    assert worker._run_planner("cleanup_recovery", lambda: calls.append("next_tick"))
    assert calls == ["first", "next_tick"]


def test_planner_lane_survives_unexpected_cycle_exception(monkeypatch):
    import gridlens.jobs.worker as worker

    stop_event = Event()
    cycles = []

    def fail_once(_planner_key, _action):
        cycles.append("attempt")
        if len(cycles) == 1:
            raise OSError("synthetic escaped cycle failure")
        stop_event.set()

    monkeypatch.setattr(worker, "_run_planner", fail_once)
    monkeypatch.setattr(worker, "_PLANNER_POLL_SECONDS", 0)
    worker._planner_lane(stop_event, "lane_recovery", lambda: None)
    assert cycles == ["attempt", "attempt"]
