import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.ingestion.adapters.acquisition_runtime import (
    ACQUISITION_SETTLEMENT_GRACE_SECONDS,
    FencedLeaseRenewer,
    try_public_acquisition_admission,
)
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    Job,
    Source,
    SourceCheckReceipt,
    SourceDueCheck,
    SourceScheduleEpoch,
)
from gridlens.settings import settings


@pytest.fixture
def acquisition_runtime_db(monkeypatch):
    import gridlens.jobs.worker as worker

    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and target.database.endswith("_test")
    assert (target.host, target.port, target.database) != (
        application.host,
        application.port,
        application.database,
    )
    engine = create_engine(settings.test_database_url, pool_size=8)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(worker, "WORKER_ID", "c5-acquisition-test")
    try:
        yield factory, engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _definition(source_id: str, *, enabled: bool = True, endpoint: str | None = None) -> dict:
    return {
        "id": source_id,
        "publisher": f"Fixture {source_id}",
        "endpoint": endpoint or f"https://example.test/{source_id}",
        "family": "synthetic",
        "geography": "US",
        "industries": ["mining"],
        "retrieval_method": "json-api",
        "cadence_hours": 24,
        "schedule_mode": "local_daily",
        "timezone": "America/Chicago",
        "schedule_anchor_time": "00:01:00",
        "enabled": enabled,
    }


def _add_source_and_due_epoch(factory, item: dict, *, job: bool) -> UUID | None:
    import gridlens.jobs.worker as worker

    now = datetime.now(UTC)
    with factory.begin() as session:
        session.add(
            Source(
                id=item["id"],
                publisher=item["publisher"],
                endpoint=item["endpoint"],
                family=item["family"],
                geography=item["geography"],
                industries=item["industries"],
                retrieval_method=item["retrieval_method"],
                cadence_hours=item["cadence_hours"],
                enabled=True,
                registry_enabled=True,
                health={},
            )
        )
        session.flush()
        local_day = (now - timedelta(days=3)).astimezone(ZoneInfo(item["timezone"])).date()
        session.add(
            SourceScheduleEpoch(
                source_id=item["id"],
                registry_enabled=True,
                operator_enabled=True,
                effective_from=now - timedelta(days=3),
                cadence_hours=item["cadence_hours"],
                schedule_mode=item["schedule_mode"],
                timezone=item["timezone"],
                anchor={
                    "local_date": local_day.isoformat(),
                    "local_time": item["schedule_anchor_time"],
                },
                configuration=worker._source_configuration(item),
            )
        )
        if not job:
            return None
        row = Job(
            source_id=item["id"],
            kind="ingestion",
            status="queued",
            available_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        session.add(row)
        session.flush()
        return row.id


def test_refresh_due_advances_other_sources_while_ingestion_holds_source_lock(
    acquisition_runtime_db, monkeypatch
):
    import gridlens.ingestion.service as service
    import gridlens.jobs.worker as worker

    factory, _engine = acquisition_runtime_db
    source_a = _definition("c5-active-source")
    source_b = _definition("c5-independent-source")
    job_id = _add_source_and_due_epoch(factory, source_a, job=True)
    _add_source_and_due_epoch(factory, source_b, job=False)
    # Keep the intended job immediately eligible despite test-process/database
    # clock skew; this is not a timeout or a change to worker behavior.
    with factory.begin() as session:
        job = session.get(Job, job_id)
        assert job is not None
        job.available_at = datetime.now(UTC) - timedelta(minutes=1)
    definitions = [source_a, source_b]
    monkeypatch.setattr(worker, "load_registry", lambda: definitions)
    entered, release = Event(), Event()
    network_calls = []

    def blocked_retrieval(*_args, **_kwargs):
        network_calls.append("source-a")
        entered.set()
        assert release.wait(6), "test did not release synthetic public request"
        return []

    monkeypatch.setattr(service, "retrieve_source", blocked_retrieval)
    with ThreadPoolExecutor(max_workers=2) as pool:
        active = pool.submit(
            worker.run_one, {item["id"]: item for item in definitions}, job_ids=[job_id]
        )
        try:
            if not entered.wait(5):
                completed = active.done()
                outcome = active.result(timeout=0) if completed else "still running"
                with factory() as session:
                    failed = session.get(Job, job_id)
                    details = {
                        "done": completed,
                        "outcome": outcome,
                        "status": failed.status if failed else None,
                        "error": failed.error if failed else None,
                        "checkpoint": failed.checkpoint if failed else None,
                    }
                pytest.fail(f"ingestion did not enter mocked retrieval: {details}")
            refresh = pool.submit(worker.refresh_due)
            assert refresh.result(timeout=3) >= 1
            with factory() as session:
                a_due = list(
                    session.scalars(
                        select(SourceDueCheck).where(SourceDueCheck.source_id == source_a["id"])
                    )
                )
                b_due = list(
                    session.scalars(
                        select(SourceDueCheck).where(SourceDueCheck.source_id == source_b["id"])
                    )
                )
                assert a_due and all(row.job_id is None for row in a_due)
                assert b_due and any(row.job_id is not None for row in b_due)
                assert session.scalar(select(func.count()).select_from(SourceCheckReceipt)) == 0
                b_job = session.get(Job, next(row.job_id for row in b_due if row.job_id))
                assert b_job and b_job.status == "queued"
            # The running A job began before this due occurrence was linked. A
            # later terminal result for that job must not be retroactively
            # treated as evidence for the still-unassigned due check.
            assert network_calls == ["source-a"]
        finally:
            release.set()
        assert active.result(timeout=6) is True

    with factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(SourceCheckReceipt)
                .join(Job)
                .where(Job.source_id == source_a["id"])
            )
            == 0
        )

    # Once A is no longer running, a refresh links its pending occurrence to a
    # new queued job. Only that later acquisition can produce its receipt.
    assert worker.refresh_due() >= 1
    with factory() as session:
        a_due = list(
            session.scalars(
                select(SourceDueCheck).where(SourceDueCheck.source_id == source_a["id"])
            )
        )
        linked_due = next((row for row in a_due if row.job_id is not None), None)
        assert linked_due is not None
        assert linked_due.job_id != job_id
        followup_job_id = linked_due.job_id
        followup_job = session.get(Job, followup_job_id)
        assert followup_job and followup_job.status == "queued"
        assert session.scalar(select(func.count()).select_from(SourceCheckReceipt)) == 0

    assert (
        worker.run_one({item["id"]: item for item in definitions}, job_ids=[followup_job_id])
        is True
    )
    assert network_calls == ["source-a", "source-a"]
    worker.sync_registry()
    with factory() as session:
        open_a = list(
            session.scalars(
                select(SourceScheduleEpoch).where(
                    SourceScheduleEpoch.source_id == source_a["id"],
                    SourceScheduleEpoch.effective_until.is_(None),
                )
            )
        )
        assert len(open_a) == 1
        receipts = list(
            session.scalars(
                select(SourceCheckReceipt).join(Job).where(Job.source_id == source_a["id"])
            )
        )
        assert len(receipts) == 1
        receipt = receipts[0]
        assert receipt.job_id == followup_job_id
        assert receipt.due_key == linked_due.due_key
        assert receipt.disposition == "succeeded"
        acquisition_started = datetime.fromisoformat(receipt.check_counts["acquisition_started_at"])
        acquisition_completed = datetime.fromisoformat(
            receipt.check_counts["acquisition_completed_at"]
        )
        assert acquisition_started <= acquisition_completed <= receipt.recorded_at


def test_source_lock_contention_defers_without_consuming_attempt_or_request(
    acquisition_runtime_db, monkeypatch
):
    import gridlens.ingestion.service as service
    import gridlens.jobs.worker as worker

    factory, engine = acquisition_runtime_db
    source = _definition("c5-lock-contention")
    job_id = _add_source_and_due_epoch(factory, source, job=True)
    monkeypatch.setattr(worker, "load_registry", lambda: [source])
    monkeypatch.setattr(
        service, "retrieve_source", lambda *_args, **_kwargs: pytest.fail("request started")
    )

    with try_public_acquisition_admission(engine, source["id"]) as admitted:
        assert admitted is True
        assert worker.run_one({source["id"]: source}, job_ids=[job_id]) is True

    with factory() as session:
        job = session.get(Job, job_id)
        assert job and job.status == "queued"
        assert job.attempts == 0
        assert job.checkpoint is None
        assert job.error == "PUBLIC_ACQUISITION_SLOT_BUSY; deferred before request"


def test_public_admission_uses_global_lock_across_different_sources(acquisition_runtime_db):
    _factory, engine = acquisition_runtime_db
    with try_public_acquisition_admission(engine, "source-one") as first:
        assert first is True
        with try_public_acquisition_admission(engine, "source-two") as second:
            assert second is False


def test_public_admission_releases_global_and_source_locks_after_failure(acquisition_runtime_db):
    _factory, engine = acquisition_runtime_db
    with pytest.raises(RuntimeError, match="fixture failure"):
        with try_public_acquisition_admission(engine, "source-failure") as admitted:
            assert admitted is True
            raise RuntimeError("fixture failure")
    with try_public_acquisition_admission(engine, "source-after-failure") as admitted:
        assert admitted is True


def test_ocr_public_capture_defers_on_shared_admission_before_capture_or_provider(
    acquisition_runtime_db, monkeypatch
):
    import gridlens.intelligence.scanned_pdf_ocr as ocr
    import gridlens.jobs.worker as worker

    factory, engine = acquisition_runtime_db
    source = _definition("c5-ocr-source")
    with factory.begin() as session:
        session.add(
            Source(
                id=source["id"],
                publisher=source["publisher"],
                endpoint=source["endpoint"],
                family=source["family"],
                geography=source["geography"],
                industries=source["industries"],
                retrieval_method=source["retrieval_method"],
                health={},
            )
        )
        session.flush()
        job = Job(
            source_id=source["id"],
            kind="intelligence_process",
            status="queued",
            available_at=datetime.now(UTC) - timedelta(seconds=1),
            checkpoint=json.dumps({"task_type": "OCR_EXTRACTION", "capture_id": "fixture"}),
        )
        session.add(job)
        session.flush()
        job_id = job.id
    calls = []
    monkeypatch.setattr(ocr, "process_scanned_pdf_ocr", lambda *_args: calls.append("process"))
    with try_public_acquisition_admission(engine, source["id"]) as admitted:
        assert admitted is True
        assert worker.run_one({}, job_ids=[job_id]) is True
    with factory() as session:
        job = session.get(Job, job_id)
        assert job and job.status == "queued" and job.attempts == 0
        assert job.checkpoint == json.dumps(
            {"task_type": "OCR_EXTRACTION", "capture_id": "fixture"}
        )
        assert job.error == "PUBLIC_ACQUISITION_SLOT_BUSY; deferred before request"
    assert calls == []


def test_registry_disable_during_active_source_defers_config_and_new_http(
    acquisition_runtime_db, monkeypatch
):
    import gridlens.ingestion.service as service
    import gridlens.jobs.worker as worker

    factory, _engine = acquisition_runtime_db
    enabled = _definition("c5-disable-during-request")
    first_id = _add_source_and_due_epoch(factory, enabled, job=True)
    with factory.begin() as session:
        second = Job(source_id=enabled["id"], kind="ingestion", status="queued")
        session.add(second)
        session.flush()
        second_id = second.id
        for job_id in (first_id, second_id):
            job = session.get(Job, job_id)
            assert job is not None
            job.available_at = datetime.now(UTC) - timedelta(minutes=1)
    current_registry = [enabled]
    monkeypatch.setattr(worker, "load_registry", lambda: current_registry)
    entered, release = Event(), Event()
    calls = []

    def blocked_retrieval(*_args, **_kwargs):
        calls.append("request")
        entered.set()
        assert release.wait(6), "test did not release synthetic public request"
        return []

    monkeypatch.setattr(service, "retrieve_source", blocked_retrieval)
    with ThreadPoolExecutor(max_workers=2) as pool:
        active = pool.submit(worker.run_one, {enabled["id"]: enabled}, job_ids=[first_id])
        try:
            assert entered.wait(5)
            disabled = {**enabled, "enabled": False, "endpoint": "https://example.test/changed"}
            current_registry[:] = [disabled]
            refresh = pool.submit(worker.refresh_due)
            refresh.result(timeout=3)
            assert worker.run_one({enabled["id"]: disabled}, job_ids=[second_id]) is True
            assert calls == ["request"]
            with factory() as session:
                due = list(
                    session.scalars(
                        select(SourceDueCheck).where(SourceDueCheck.source_id == enabled["id"])
                    )
                )
                assert due  # the existing schedule denominator was retained
                assert all(row.job_id is None for row in due)
        finally:
            release.set()
        assert active.result(timeout=6) is True

    worker.sync_registry()
    with factory() as session:
        source = session.get(Source, enabled["id"])
        assert source and source.registry_enabled is False
        epochs = list(
            session.scalars(
                select(SourceScheduleEpoch).where(
                    SourceScheduleEpoch.source_id == enabled["id"],
                    SourceScheduleEpoch.effective_until.is_(None),
                )
            )
        )
        assert len(epochs) == 1
        prior_epochs = list(
            session.scalars(
                select(SourceScheduleEpoch).where(
                    SourceScheduleEpoch.source_id == enabled["id"],
                    SourceScheduleEpoch.effective_until.is_not(None),
                )
            )
        )
        assert prior_epochs and all(not item.history_known for item in prior_epochs)
        assert calls == ["request"]


def test_lease_renewer_caps_extension_at_original_deadline_plus_grace(
    acquisition_runtime_db, monkeypatch
):
    import gridlens.ingestion.adapters.acquisition_runtime as runtime

    factory, _engine = acquisition_runtime_db
    now = datetime.now(UTC)
    with factory.begin() as session:
        session.add(
            Source(
                id="c5-renew-source",
                publisher="Fixture",
                endpoint="https://example.test/c5-renew",
                family="synthetic",
                geography="US",
                industries=["mining"],
                retrieval_method="json-api",
                health={},
            )
        )
        session.flush()
        job = Job(
            source_id="c5-renew-source",
            status="running",
            lease_owner="c5-renewer",
            fence=4,
            lease_until=now + timedelta(seconds=120),
        )
        session.add(job)
        session.flush()
        job_id, original_expiry = job.id, job.lease_until

    fake_clock = [original_expiry - timedelta(seconds=100)]

    class ControlledDateTime:
        @classmethod
        def now(cls, _timezone):
            return fake_clock[0]

    monkeypatch.setattr(runtime, "datetime", ControlledDateTime)
    renewer = FencedLeaseRenewer(
        factory,
        job_id,
        "c5-renewer",
        4,
        original_expiry,
        interval_seconds=0.01,
    ).start()
    try:
        time.sleep(0.04)
        fake_clock[0] = original_expiry - timedelta(seconds=80)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with factory() as session:
                current = session.get(Job, job_id).lease_until
            if current >= original_expiry + timedelta(seconds=ACQUISITION_SETTLEMENT_GRACE_SECONDS):
                break
            time.sleep(0.01)
        assert current == original_expiry + timedelta(seconds=ACQUISITION_SETTLEMENT_GRACE_SECONDS)
        fake_clock[0] = original_expiry + timedelta(
            seconds=ACQUISITION_SETTLEMENT_GRACE_SECONDS + 1
        )
        renewer._thread.join(timeout=1)
        assert not renewer._thread.is_alive()
    finally:
        renewer.stop()
