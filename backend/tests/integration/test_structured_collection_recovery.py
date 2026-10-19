import json
from datetime import UTC, datetime, time, timedelta

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.registry import load_registry
from gridlens.ingestion.service import process_job
from gridlens.ingestion.structured_collection import (
    collection_lanes,
    collection_policy_digest,
    prepare_collection_progress,
)
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
def structured_db():
    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and target.database.endswith("_test"), (
        "Refusing destructive setup without an explicit *_test database"
    )
    assert (target.host, target.port, target.database) != (
        application.host,
        application.port,
        application.database,
    ), "TEST_DATABASE_URL must differ from DATABASE_URL"
    engine = create_engine(settings.test_database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


def _chicago_row(issue_date: str, modified_at: str) -> dict:
    row = {
        "id": "420001",
        "issue_date": f"{issue_date}T00:00:00.000",
        "work_description": "Electrical work at commercial facility",
        "work_type": "Electrical Work",
        "permit_type": "PERMIT - RENOVATION/ALTERATION",
        "permit_status": "Issued",
        "street_number": "100",
        "street_direction": "N",
        "street_name": "MAIN ST",
        "permit_": "420001",
        "reported_cost": "10000",
        "pin_list": "123456789",
        ":updated_at": modified_at,
        "application_start_date": None,
        "permit_milestone": "Issued",
    }
    for index in range(1, 16):
        row[f"contact_{index}_type"] = None
        row[f"contact_{index}_name"] = None
    return row


def test_process_job_resumes_modified_history_after_long_outage(structured_db):
    factory = structured_db
    source_definition = next(
        item for item in load_registry() if item["id"] == "chicago-building-permits"
    )
    today = datetime.now(UTC).date()
    older_completed_through = today - timedelta(days=16)
    next_modified_day = older_completed_through + timedelta(days=1)
    digest = collection_policy_digest(source_definition)
    lanes = collection_lanes(source_definition)

    with factory.begin() as session:
        session.add(
            Source(
                id=source_definition["id"],
                publisher=source_definition["publisher"],
                endpoint=source_definition["endpoint"],
                family=source_definition["family"],
                geography=source_definition["geography"],
                industries=source_definition["industries"],
                retrieval_method=source_definition["retrieval_method"],
                cadence_hours=source_definition["cadence_hours"],
                enabled=True,
                registry_enabled=True,
                health={"status": "Overdue", "last_success": "retained"},
            )
        )
        session.flush()
        job = Job(
            source_id=source_definition["id"],
            status="running",
            lease_owner="test",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
            checkpoint=json.dumps({"collection_continuation": True}),
        )
        session.add(job)
        for lane in lanes:
            through = older_completed_through if lane == "modified_history" else today
            session.add(
                SourceCollectionProgress(
                    source_id=source_definition["id"],
                    lane=lane,
                    policy_digest=digest,
                    window_start=datetime.combine(through - timedelta(days=6), time.min, UTC),
                    window_end=datetime.combine(through, time.min, UTC),
                    cursor={},
                    completed_through=datetime.combine(through, time.min, UTC),
                    status="complete",
                )
            )
        session.flush()
        job_id = job.id

    requests: list[httpx.Request] = []
    historical_row = _chicago_row("2017-04-02", f"{next_modified_day.isoformat()}T10:15:30.123Z")

    with factory() as session:
        before = session.scalars(select(SourceCollectionProgress)).all()
        assert len(before) == len(lanes), [
            (row.lane, row.status, row.completed_through) for row in before
        ]
        assert next(row for row in before if row.lane == "modified_history").completed_through
        progress, _, _ = prepare_collection_progress(session, source_definition)
        assert progress.lane == "modified_history"
        session.rollback()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.params.get("$select") == "count(*) AS row_count":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json=[{"row_count": 1}],
            )
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json=[historical_row],
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client, factory() as session:
        counts = process_job(
            session, job_id, "test", 1, source_definition, client
        )

    assert counts["collection_lane"] == "modified_history"
    assert counts["collection_window_start"] == next_modified_day.isoformat()
    assert counts["collection_continuation"] is True
    assert counts["collection_status"] == "PARTIAL"
    assert counts["retrieved_records"] == 1
    started = datetime.fromisoformat(counts["acquisition_started_at"])
    completed = datetime.fromisoformat(counts["acquisition_completed_at"])
    assert started.tzinfo is not None and completed.tzinfo is not None
    assert completed >= started
    assert f"{next_modified_day.isoformat()}T00:00:00.000Z" in requests[0].url.params["$where"]
    assert "issue_date IS NOT NULL" in requests[0].url.params["$where"]
    with factory.begin() as session:
        progress = session.scalar(
            select(SourceCollectionProgress).where(
                SourceCollectionProgress.source_id == source_definition["id"],
                SourceCollectionProgress.lane == "modified_history",
                SourceCollectionProgress.policy_digest == digest,
            )
        )
        assert progress is not None
        assert progress.status == "incomplete"
        assert progress.cursor["day"] == (next_modified_day + timedelta(days=1)).isoformat()
        source = session.get(Source, source_definition["id"])
        assert source is not None
        assert source.health["last_success"] == "retained"
        job = session.get(Job, job_id)
        assert job is not None
        assert json.loads(job.checkpoint) == {
            "collection_continuation": True,
            "last_record_external_id": "420001",
        }
        restarted_job = Job(
            source_id=source_definition["id"],
            status="running",
            lease_owner="test",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(restarted_job)
        session.flush()
        restarted_job_id = restarted_job.id

    def empty_day_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("$select") == "count(*) AS row_count"
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json=[{"row_count": 0}],
        )

    with (
        httpx.Client(transport=httpx.MockTransport(empty_day_handler)) as client,
        factory() as session,
    ):
        resumed = process_job(
            session, restarted_job_id, "test", 1, source_definition, client
        )
    assert resumed["collection_lane"] == "modified_history"
    assert resumed["collection_continuation"] is True
    with factory() as session:
        progress = session.scalar(
            select(SourceCollectionProgress).where(
                SourceCollectionProgress.source_id == source_definition["id"],
                SourceCollectionProgress.lane == "modified_history",
                SourceCollectionProgress.policy_digest == digest,
            )
        )
        assert progress is not None
        assert progress.cursor["day"] == (next_modified_day + timedelta(days=2)).isoformat()


@pytest.mark.parametrize("disabled,stored_fence", [(True, 1), (False, 2)])
def test_process_job_rejects_disabled_source_or_stale_fence_before_fetch(
    structured_db, disabled, stored_fence
):
    factory = structured_db
    source_definition = next(
        item for item in load_registry() if item["id"] == "chicago-building-permits"
    )
    with factory.begin() as session:
        session.add(
            Source(
                id=source_definition["id"],
                publisher=source_definition["publisher"],
                endpoint=source_definition["endpoint"],
                family=source_definition["family"],
                geography=source_definition["geography"],
                industries=source_definition["industries"],
                retrieval_method=source_definition["retrieval_method"],
                cadence_hours=source_definition["cadence_hours"],
                enabled=not disabled,
                registry_enabled=True,
                health={},
            )
        )
        session.flush()
        job = Job(
            source_id=source_definition["id"],
            status="running",
            lease_owner="test",
            fence=stored_fence,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        job_id = job.id

    requests: list[httpx.Request] = []
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: requests.append(request) or httpx.Response(200, json=[])
        )
    ) as client, factory() as session:
        if disabled:
            with pytest.raises(SourceParseError, match="disabled or changed"):
                process_job(session, job_id, "test", 1, source_definition, client)
        else:
            with pytest.raises(RuntimeError, match="lease fence lost"):
                process_job(session, job_id, "test", 1, source_definition, client)
    assert requests == []


def test_worker_marks_partial_health_and_queues_transactional_continuation(
    structured_db, monkeypatch
):
    import gridlens.jobs.worker as worker

    factory = structured_db
    source_definition = next(
        item for item in load_registry() if item["id"] == "chicago-building-permits"
    )
    with factory.begin() as session:
        session.add(
            Source(
                id=source_definition["id"],
                publisher=source_definition["publisher"],
                endpoint=source_definition["endpoint"],
                family=source_definition["family"],
                geography=source_definition["geography"],
                industries=source_definition["industries"],
                retrieval_method=source_definition["retrieval_method"],
                cadence_hours=source_definition["cadence_hours"],
                enabled=True,
                registry_enabled=True,
                health={"last_success": "prior-good", "new_records": 7},
            )
        )
        session.flush()
        job = Job(
            source_id=source_definition["id"],
            kind="ingestion",
            status="queued",
            available_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        session.add(job)
        session.flush()
        job_id = job.id
        epoch = SourceScheduleEpoch(
            source_id=source_definition["id"],
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
        session.add(epoch)
        session.flush()
        session.add(
            SourceDueCheck(
                due_key="a" * 64,
                source_id=source_definition["id"],
                epoch_id=epoch.id,
                scheduled_for=datetime.now(UTC) - timedelta(minutes=10),
                local_day=datetime.now(UTC).date(),
                configuration={},
                job_id=job_id,
            )
        )

    class Admitted:
        def __enter__(self):
            return True

        def __exit__(self, *_args):
            return False

    class NoopRenewer:
        def __init__(self, *_args):
            pass

        def start(self):
            return self

        def stop(self):
            pass

    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(worker, "WORKER_ID", "test-worker")
    monkeypatch.setattr(worker, "try_public_acquisition_admission", lambda *_args: Admitted())
    monkeypatch.setattr(worker, "FencedLeaseRenewer", NoopRenewer)
    monkeypatch.setattr(
        worker,
        "process_job",
        lambda *_args, **_kwargs: {
            "new": 0,
            "changed": 0,
            "unchanged": 0,
            "signals": 0,
            "partial": True,
            "parse_failures": 1,
            "collection_status": "PARTIAL",
            "collection_lane": "modified_history",
            "collection_current_complete": False,
            "collection_continuation": True,
            "collection_window_start": "2026-10-01",
            "collection_window_end": "2026-10-07",
            "collection_error_class": "ResultCountChanged",
        },
    )

    assert worker.run_one({source_definition["id"]: source_definition}) is True
    with factory() as session:
        finished = session.get(Job, job_id)
        source = session.get(Source, source_definition["id"])
        queued = session.scalars(
            select(Job).where(
                Job.source_id == source_definition["id"],
                Job.id != job_id,
                Job.status == "queued",
            )
        ).all()
        assert finished is not None and finished.status == "succeeded"
        assert source is not None
        assert source.health["status"] == "Partial"
        assert source.health["last_success"] == "prior-good"
        assert source.health["new_records"] == 7
        receipt = session.scalar(
            select(SourceCheckReceipt).where(SourceCheckReceipt.job_id == job_id)
        )
        assert receipt is not None
        assert receipt.disposition == "partial"
        assert len(queued) == 1
        assert json.loads(queued[0].checkpoint) == {"collection_continuation": True}
