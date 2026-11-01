import json
from datetime import UTC, date, datetime, time, timedelta

import httpx
import pytest
from db_reset import reset_test_database
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
    reset_test_database(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    yield factory
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
        counts = process_job(session, job_id, "test", 1, source_definition, client)

    assert counts["collection_lane"] == "modified_history"
    assert counts["collection_window_start"] == next_modified_day.isoformat()
    assert counts["collection_continuation"] is True
    assert counts["collection_status"] == "PARTIAL"
    assert counts["retrieved_records"] == 1
    started = datetime.fromisoformat(counts["acquisition_started_at"])
    completed = datetime.fromisoformat(counts["acquisition_completed_at"])
    assert started.tzinfo is not None and completed.tzinfo is not None
    assert completed >= started
    lower = f"{next_modified_day.isoformat()}T00:00:00.000Z"
    assert len([r for r in requests if r.url.params.get("$select") == "count(*) AS row_count"]) == 2
    for request in requests:
        where = request.url.params["$where"]
        assert lower in where and ":updated_at <" in where, where
        assert "issue_date IS NOT NULL" in where
    modified = datetime.fromisoformat(historical_row[":updated_at"].replace("Z", "+00:00"))
    assert datetime.combine(next_modified_day, time.min, UTC) <= modified
    with factory.begin() as session:
        progress = session.scalar(
            select(SourceCollectionProgress).where(
                SourceCollectionProgress.source_id == source_definition["id"],
                SourceCollectionProgress.lane == "modified_history",
                SourceCollectionProgress.policy_digest == digest,
            )
        )
        assert progress is not None
        assert progress.status == "complete"
        assert progress.completed_through == progress.window_end
        assert modified < progress.window_end.astimezone(UTC)
        assert progress.cursor == {}
        first_range_end = progress.window_end
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
        resumed = process_job(session, restarted_job_id, "test", 1, source_definition, client)
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
        assert progress.status == "complete"
        assert progress.cursor == {}
        assert progress.completed_through == first_range_end + timedelta(days=7)


def test_rrc_flare_history_resumes_after_completed_interval(structured_db):
    factory = structured_db
    source_definition = next(
        item for item in load_registry() if item["id"] == "texas-rrc-flare-vent-exceptions"
    )
    today = datetime.now(UTC).date()
    digest = collection_policy_digest(source_definition)
    through = today - timedelta(days=31)
    start = through - timedelta(days=6)
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
                health={},
            )
        )
        session.flush()
        row = SourceCollectionProgress(
            source_id=source_definition["id"],
            lane="issue_history",
            policy_digest=digest,
            window_start=datetime.combine(start, time.min, UTC),
            window_end=datetime.combine(through, time.min, UTC),
            completed_through=datetime.combine(through, time.min, UTC),
            cursor={},
            status="complete",
        )
        recent = SourceCollectionProgress(
            source_id=source_definition["id"],
            lane="issue_recent",
            policy_digest=digest,
            window_start=datetime.combine(today - timedelta(days=2), time.min, UTC),
            window_end=datetime.combine(today, time.min, UTC),
            completed_through=datetime.combine(today, time.min, UTC),
            cursor={},
            status="complete",
        )
        session.add_all([row, recent])
        session.flush()
        progress, _, _ = prepare_collection_progress(session, source_definition, today=today)
        assert progress.lane == "issue_history"
        assert progress.window_start.date() == through + timedelta(days=1)
        assert progress.window_end.date() == through + timedelta(days=7)
        assert progress.status == "incomplete"


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
    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda request: requests.append(request) or httpx.Response(200, json=[])
            )
        ) as client,
        factory() as session,
    ):
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
        item for item in load_registry() if item["id"] == "austin-building-permits"
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
            "rejected_records": [
                {
                    "identity": "fixture-row-7",
                    "stage": "public_acquisition",
                    "error_code": "source_parse_error",
                    "selected_fields": ["title"],
                    "omitted_fields": [],
                    "raw": {"title": "Public fixture row"},
                }
            ],
            "attempt_fetched": 1,
            "attempt_processed": 0,
            "attempt_rejected": 1,
            "attempt_new": 0,
            "attempt_changed": 0,
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
        assert source.health["new_records"] == 0
        assert source.health["records_rejected"] == 1
        assert source.health["last_rejected_records"][0]["identity"] == "fixture-row-7"
        assert source.health["attempt_processed"] == 0
        assert source.health["retry_state"] == "not_scheduled"
        receipt = session.scalar(
            select(SourceCheckReceipt).where(SourceCheckReceipt.job_id == job_id)
        )
        assert receipt is not None
        assert receipt.disposition == "partial"
        assert receipt.check_counts["rejected_records"][0]["identity"] == "fixture-row-7"
        assert json.loads(finished.checkpoint)["last_acquisition_rejections"][0]["identity"] == (
            "fixture-row-7"
        )
        assert len(queued) == 1
        assert json.loads(queued[0].checkpoint) == {
            "collection_continuation": True,
            "collection_jobs_remaining": 7,
        }


@pytest.mark.parametrize(
    ("failure", "diagnostics", "expected_job_status", "retry_class"),
    [
        (RuntimeError("fixture"), {"error_code": "network_error"}, "queued", "TRANSIENT"),
        (
            RuntimeError("fixture"),
            {
                "error_code": "http_status_429",
                "http_status": 429,
                "retry_after_seconds": 120,
            },
            "queued",
            "TRANSIENT",
        ),
        (
            RuntimeError("fixture"),
            {"error_code": "http_status_403", "http_status": 403},
            "failed",
            "PERMANENT",
        ),
        (
            SourceParseError("schema changed"),
            {"error_code": "source_parse_error"},
            "failed",
            "PERMANENT",
        ),
    ],
)
def test_worker_retry_policy_preserves_last_success(
    structured_db, monkeypatch, failure, diagnostics, expected_job_status, retry_class
):
    import gridlens.jobs.worker as worker

    factory = structured_db
    source_definition = next(
        item for item in load_registry() if item["id"] == "austin-building-permits"
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
                health={
                    "last_success": "prior-good",
                    "retrieved_records": 12,
                    "parsed_records": 8,
                    "new_records": 3,
                    "changed_records": 2,
                    "permit_accepted": 5,
                    "permit_rejected": 1,
                },
            )
        )
        session.flush()
        job = Job(
            source_id=source_definition["id"],
            status="queued",
            available_at=datetime.now(UTC) - timedelta(seconds=5),
        )
        session.add(job)
        session.flush()
        job_id = job.id

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

    def fail_processing(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(worker, "WORKER_ID", "retry-policy-test")
    monkeypatch.setattr(worker, "load_registry", lambda: [source_definition])
    monkeypatch.setattr(worker, "_park_if_disabled", lambda *_args: False)
    monkeypatch.setattr(worker, "try_public_acquisition_admission", lambda *_args: Admitted())
    monkeypatch.setattr(worker, "FencedLeaseRenewer", NoopRenewer)
    monkeypatch.setattr(worker, "process_job", fail_processing)
    monkeypatch.setattr(worker, "acquisition_diagnostics", lambda _error: diagnostics)

    assert worker.run_one({source_definition["id"]: source_definition}, job_ids=[job_id])
    with factory() as session:
        finished = session.get(Job, job_id)
        source = session.get(Source, source_definition["id"])
        assert finished.status == expected_job_status
        assert source.health["last_success"] == "prior-good"
        assert source.health["retrieved_records"] == 0
        assert source.health["parsed_records"] == 0
        assert source.health["new_records"] == 0
        assert source.health["last_success_counts"] == {
            "retrieved_records": 12,
            "parsed_records": 8,
            "new_records": 3,
            "changed_records": 2,
            "permit_accepted": 5,
            "permit_rejected": 1,
        }
        assert source.health["retry_class"] == retry_class
        assert (source.health.get("retry_at") is not None) == (expected_job_status == "queued")
        if "retry_after_seconds" in diagnostics:
            assert finished.available_at >= datetime.now(UTC) + timedelta(seconds=118)


def test_drilling_history_advances_closed_months_and_stops_at_previous_month(structured_db):
    from gridlens.ingestion.structured_collection import (
        apply_segment_result,
        collection_continuation_needed,
        collection_status,
    )

    definition = next(
        item for item in load_registry() if item["id"] == "texas-rrc-drilling-permits"
    )
    today = date(2026, 11, 1)
    now = datetime(2026, 11, 1, 12, tzinfo=UTC)
    with structured_db.begin() as session:
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
            )
        )
        session.flush()
        recent, digest, lanes = prepare_collection_progress(session, definition, today=today)
        assert recent.lane == "issue_recent"
        apply_segment_result(
            recent, {"window_complete": True, "cursor": {}, "partial": False}, now=now
        )
        for start, end in [
            (date(2026, 8, 1), date(2026, 8, 31)),
            (date(2026, 9, 1), date(2026, 9, 30)),
            (date(2026, 10, 1), date(2026, 10, 31)),
        ]:
            history, _, _ = prepare_collection_progress(session, definition, today=today)
            assert history.lane == "issue_history"
            assert history.window_start.date() == start
            assert history.window_end.date() == end
            apply_segment_result(
                history, {"window_complete": True, "cursor": {}, "partial": False}, now=now
            )
        session.flush()
        assert collection_status(
            session, definition["id"], digest, lanes, today=today, source=definition
        ) == (True, True)
        assert not collection_continuation_needed(
            session, definition["id"], digest, lanes, source=definition, today=today
        )
        # After an outage, history resumes next month rather than rolling forward from today.
        resumed, _, _ = prepare_collection_progress(
            session, definition, today=date(2027, 2, 1), collection_jobs_remaining=6
        )
        assert resumed.lane == "issue_history"
        assert resumed.window_start.date() == date(2026, 11, 1)
        assert resumed.window_end.date() == date(2026, 11, 30)
