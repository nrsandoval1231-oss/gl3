"""Adversarial real-PostgreSQL checks for structured collection recovery."""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event

import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.registry import load_registry
from gridlens.ingestion.service import process_job
from gridlens.ingestion.structured_collection import collection_lanes, collection_policy_digest
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    Evidence,
    Job,
    Observation,
    Source,
    SourceCollectionProgress,
)
from gridlens.settings import settings


@pytest.fixture
def adversarial_db():
    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert (
        target.host == "127.0.0.1"
        and target.port == 55487
        and target.username == "gl3_intelligence"
        and target.database == "gl3_intelligence_operations_20261018_test"
    ), "Refusing destructive setup outside the exclusive operations test database"
    assert (
        application.host == "127.0.0.1"
        and application.port == 55487
        and application.username == "gl3_intelligence"
        and application.database == "gl3_intelligence_operations_20261018_app"
    ), "Application database identity is not the authorized isolated pair"
    assert (target.host, target.port, target.database) != (
        application.host,
        application.port,
        application.database,
    ), "TEST_DATABASE_URL must differ from the operations application database"
    engine = create_engine(settings.test_database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


def _source_definition() -> dict:
    return next(
        item for item in load_registry() if item["id"] == "chicago-building-permits"
    )


def _chicago_row(row_id: str = "420001", *, issue_date: str | None = None) -> dict:
    day = issue_date or datetime.now(UTC).date().isoformat()
    row = {
        "id": row_id,
        "issue_date": f"{day}T00:00:00.000",
        "work_description": "Electrical work at commercial facility",
        "work_type": "Electrical Work",
        "permit_type": "PERMIT - RENOVATION/ALTERATION",
        "permit_status": "Issued",
        "street_number": "100",
        "street_direction": "N",
        "street_name": "MAIN ST",
        "permit_": row_id,
        "reported_cost": "10000",
        "pin_list": "123456789",
        ":updated_at": f"{day}T10:15:30.123Z",
        "application_start_date": None,
        "permit_milestone": "Issued",
    }
    for index in range(1, 16):
        row[f"contact_{index}_type"] = None
        row[f"contact_{index}_name"] = None
    return row


def _row_for_request(request: httpx.Request) -> dict:
    where = request.url.params.get("$where", "")
    match = re.search(r"issue_date >= '(\d{4}-\d{2}-\d{2})", where)
    assert match is not None, f"Expected bounded Chicago issue-date query, got {where}"
    return _chicago_row(issue_date=match.group(1))


def _make_source_and_job(
    factory,
    source_definition: dict,
    *,
    status: str = "running",
    checkpoint: str | None = None,
):
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
            status=status,
            checkpoint=checkpoint,
            lease_owner="adversarial-test" if status == "running" else None,
            fence=1,
            lease_until=(datetime.now(UTC) + timedelta(minutes=10))
            if status == "running"
            else None,
            available_at=datetime.now(UTC) - timedelta(minutes=1),
            attempts=1,
        )
        session.add(job)
        session.flush()
        return job.id


def _segment_client(*, row: dict | None = None, count: int = 1):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.params.get("$select") == "count(*) AS row_count":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json=[{"row_count": count}],
            )
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json=[row or _row_for_request(request)],
        )

    return httpx.Client(transport=httpx.MockTransport(handler)), requests


def _progress(factory, lane: str | None = None) -> SourceCollectionProgress:
    with factory() as session:
        query = select(SourceCollectionProgress)
        if lane is not None:
            query = query.where(SourceCollectionProgress.lane == lane)
        row = session.scalar(query)
        assert row is not None
        session.expunge(row)
        return row


def _evidence_count(factory) -> int:
    with factory() as session:
        return int(session.scalar(select(func.count()).select_from(Evidence)) or 0)


def _utc_date(value: datetime | None):
    assert value is not None
    return value.astimezone(UTC).date()


def _complete_nonrecent_lanes(factory, definition: dict) -> None:
    today = datetime.now(UTC).date()
    digest = collection_policy_digest(definition)
    with factory.begin() as session:
        for lane in collection_lanes(definition):
            if lane == "issue_recent":
                continue
            session.add(
                SourceCollectionProgress(
                    source_id=definition["id"],
                    lane=lane,
                    policy_digest=digest,
                    window_start=datetime.combine(
                        today - timedelta(days=6), datetime.min.time(), UTC
                    ),
                    window_end=datetime.combine(today, datetime.min.time(), UTC),
                    cursor={},
                    completed_through=datetime.combine(today, datetime.min.time(), UTC),
                    status="complete",
                )
            )


def test_crash_after_evidence_commit_restarts_without_duplicate_evidence(
    adversarial_db, monkeypatch
):
    factory = adversarial_db
    definition = _source_definition()
    job_id = _make_source_and_job(factory, definition)
    _complete_nonrecent_lanes(factory, definition)
    client, requests = _segment_client()
    import gridlens.ingestion.service as service
    import gridlens.ingestion.structured_collection as collection

    original_apply = collection.apply_segment_result
    raised = False

    def crash_once(*args, **kwargs):
        nonlocal raised
        if not raised:
            raised = True
            raise RuntimeError("injected crash after evidence commit")
        return original_apply(*args, **kwargs)

    monkeypatch.setattr(service, "apply_segment_result", crash_once)
    with client:
        with factory() as session, pytest.raises(
            RuntimeError, match="injected crash after evidence commit"
        ):
            process_job(session, job_id, "adversarial-test", 1, definition, client)

        after_crash = _progress(factory, "issue_recent")
        assert after_crash.cursor == {}
        assert after_crash.status != "complete"
        assert _evidence_count(factory) == 1
        with factory() as session:
            evidence = session.scalar(select(Evidence))
            observation = session.scalar(select(Observation))
            assert evidence is not None and observation is not None
            retained_evidence = (
                evidence.id,
                evidence.observed_at,
                evidence.content_hash,
                observation.first_seen_at,
            )

        with factory() as session:
            result = process_job(
                session, job_id, "adversarial-test", 1, definition, client
            )

    assert raised and len(requests) == 6
    assert result["collection_status"] == "PARTIAL"
    assert result["collection_error_class"] is None
    assert _evidence_count(factory) == 1
    with factory() as session:
        observation = session.scalar(select(Observation))
        evidence = session.scalar(select(Evidence))
        progress = session.scalar(
            select(SourceCollectionProgress).where(
                SourceCollectionProgress.lane == "issue_recent"
            )
        )
        assert observation is not None and observation.external_id == "420001"
        assert evidence is not None and evidence.observation_id == observation.id
        assert (
            evidence.id,
            evidence.observed_at,
            evidence.content_hash,
            observation.first_seen_at,
        ) == retained_evidence
        assert progress is not None and progress.status == "incomplete"
        assert progress.cursor.get("day") == (
            datetime.now(UTC).date() - timedelta(days=5)
        ).isoformat()


def test_stale_fence_after_fetch_cannot_write_evidence_or_checkpoint(adversarial_db):
    factory = adversarial_db
    definition = _source_definition()
    job_id = _make_source_and_job(factory, definition)

    def change_fence(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("$select") != "count(*) AS row_count":
            with factory.begin() as session:
                job = session.get(Job, job_id)
                assert job is not None
                job.fence = 2
        if request.url.params.get("$select") == "count(*) AS row_count":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json=[{"row_count": 1}],
            )
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json=[_row_for_request(request)],
        )

    with httpx.Client(transport=httpx.MockTransport(change_fence)) as client:
        with factory() as session, pytest.raises(RuntimeError, match="fence lost"):
            process_job(session, job_id, "adversarial-test", 1, definition, client)
    assert _evidence_count(factory) == 0
    with factory() as session:
        progress = session.scalar(select(SourceCollectionProgress))
        assert progress is not None and progress.cursor == {}
        assert progress.status != "complete"


def test_source_endpoint_change_during_fetch_rejects_segment(adversarial_db):
    factory = adversarial_db
    definition = _source_definition()
    job_id = _make_source_and_job(factory, definition)

    def change_source(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("$select") != "count(*) AS row_count":
            with factory.begin() as session:
                source = session.get(Source, definition["id"])
                assert source is not None
                source.endpoint = "https://changed.invalid/permits"
        if request.url.params.get("$select") == "count(*) AS row_count":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json=[{"row_count": 1}],
            )
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json=[_row_for_request(request)],
        )

    with httpx.Client(transport=httpx.MockTransport(change_source)) as client:
        with factory() as session, pytest.raises(SourceParseError, match="endpoint changed"):
            process_job(session, job_id, "adversarial-test", 1, definition, client)
    assert _evidence_count(factory) == 0
    with factory() as session:
        progress = session.scalar(select(SourceCollectionProgress))
        assert progress is not None and progress.cursor == {}
        assert progress.status != "complete"


def test_concurrent_duplicate_cannot_overwrite_advanced_cursor(adversarial_db):
    factory = adversarial_db
    definition = _source_definition()
    first_job_id = _make_source_and_job(factory, definition)
    _complete_nonrecent_lanes(factory, definition)
    with factory.begin() as session:
        second_job = Job(
            source_id=definition["id"],
            status="running",
            lease_owner="adversarial-test-2",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(second_job)
        session.flush()
        second_job_id = second_job.id
        today = datetime.now(UTC).date()
        issue_day = today - timedelta(days=2)
        session.add(
            SourceCollectionProgress(
                source_id=definition["id"],
                lane="issue_recent",
                policy_digest=collection_policy_digest(definition),
                window_start=datetime.combine(issue_day, datetime.min.time(), UTC),
                window_end=datetime.combine(today, datetime.min.time(), UTC),
                cursor={"day": issue_day.isoformat()},
                status="incomplete",
            )
        )

    first_at_page = Event()
    release_first = Event()

    def first_handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("$select") == "count(*) AS row_count":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json=[{"row_count": 1}],
            )
        first_at_page.set()
        assert release_first.wait(timeout=10), "concurrent test did not release first fetch"
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json=[_chicago_row(issue_date=issue_day.isoformat())],
        )

    def second_handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("$select") == "count(*) AS row_count":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json=[{"row_count": 1}],
            )
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json=[_chicago_row(issue_date=issue_day.isoformat())],
        )

    first_client = httpx.Client(transport=httpx.MockTransport(first_handler))
    second_client = httpx.Client(transport=httpx.MockTransport(second_handler))
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        first = executor.submit(
            _run_process_job,
            factory,
            first_job_id,
            "adversarial-test",
            definition,
            first_client,
        )
        assert first_at_page.wait(timeout=10), "first fetch did not reach the I/O boundary"
        with factory() as session:
            second_result = process_job(
                session, second_job_id, "adversarial-test-2", 1, definition, second_client
            )
        advanced_cursor = _progress(factory, "issue_recent").cursor
        assert advanced_cursor != {}
        release_first.set()
        first_result = first.result(timeout=10)
    finally:
        release_first.set()
        first_client.close()
        second_client.close()
        executor.shutdown(wait=True)

    assert second_result["collection_error_class"] is None
    assert first_result["collection_error_class"] == "CollectionCheckpointChanged"
    assert _progress(factory, "issue_recent").cursor == advanced_cursor
    assert _evidence_count(factory) == 1


def test_window_rollover_invalidates_reused_empty_cursor(adversarial_db):
    factory = adversarial_db
    definition = _source_definition()
    first_job_id = _make_source_and_job(factory, definition)
    _complete_nonrecent_lanes(factory, definition)
    today = datetime.now(UTC).date()
    old_day = today - timedelta(days=1)
    with factory.begin() as session:
        later_jobs = [
            Job(
                source_id=definition["id"],
                status="running",
                lease_owner=f"rollover-worker-{index}",
                fence=1,
                lease_until=datetime.now(UTC) + timedelta(minutes=10),
            )
            for index in ("b", "c")
        ]
        session.add_all(later_jobs)
        session.add(
            SourceCollectionProgress(
                source_id=definition["id"],
                lane="issue_recent",
                policy_digest=collection_policy_digest(definition),
                window_start=datetime.combine(old_day, datetime.min.time(), UTC),
                window_end=datetime.combine(old_day, datetime.min.time(), UTC),
                cursor={},
                status="incomplete",
            )
        )
        session.flush()
        second_job_id, third_job_id = (job.id for job in later_jobs)

    first_at_page = Event()
    release_first = Event()
    third_at_count = Event()
    release_third = Event()

    def first_handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("$select") == "count(*) AS row_count":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json=[{"row_count": 1}],
            )
        if not first_at_page.is_set():
            first_at_page.set()
            assert release_first.wait(timeout=10), "old-window fetch was not released"
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json=[_chicago_row(issue_date=old_day.isoformat())],
        )

    def zero_count(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("$select") == "count(*) AS row_count":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json=[{"row_count": 0}],
            )
        pytest.fail("A zero-count segment must not request page rows")

    def third_handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("$select") == "count(*) AS row_count":
            third_at_count.set()
            assert release_third.wait(timeout=10), "new-window fetch was not released"
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json=[{"row_count": 0}],
            )
        pytest.fail("A zero-count segment must not request page rows")

    first_client = httpx.Client(transport=httpx.MockTransport(first_handler))
    second_client = httpx.Client(transport=httpx.MockTransport(zero_count))
    third_client = httpx.Client(transport=httpx.MockTransport(third_handler))
    executor = ThreadPoolExecutor(max_workers=2)
    try:
        first = executor.submit(
            _run_process_job,
            factory,
            first_job_id,
            "adversarial-test",
            definition,
            first_client,
        )
        assert first_at_page.wait(timeout=10), "old-window fetch did not reach page boundary"
        with factory() as session:
            second_result = process_job(
                session,
                second_job_id,
                "rollover-worker-b",
                1,
                definition,
                second_client,
            )
        completed_old_window = _progress(factory, "issue_recent")
        assert completed_old_window.status == "complete"
        assert _utc_date(completed_old_window.window_start) == old_day
        assert _utc_date(completed_old_window.window_end) == old_day

        third = executor.submit(
            _run_process_job,
            factory,
            third_job_id,
            "rollover-worker-c",
            definition,
            third_client,
        )
        assert third_at_count.wait(timeout=10), "new-window fetch did not reach request boundary"
        rolled_window = _progress(factory, "issue_recent")
        assert rolled_window.cursor == {}
        assert rolled_window.status == "incomplete"
        assert _utc_date(rolled_window.window_start) == today - timedelta(days=6)
        assert _utc_date(rolled_window.window_end) == today

        release_first.set()
        first_result = first.result(timeout=10)
        while_new_window_fetch_is_blocked = _progress(factory, "issue_recent")
        assert while_new_window_fetch_is_blocked.status == "incomplete"
        assert (
            while_new_window_fetch_is_blocked.completed_through
            == completed_old_window.completed_through
        )
        release_third.set()
        third_result = third.result(timeout=10)
    finally:
        release_first.set()
        release_third.set()
        first_client.close()
        second_client.close()
        third_client.close()
        executor.shutdown(wait=True)

    assert second_result["collection_error_class"] is None
    assert first_result["collection_error_class"] == "CollectionCheckpointChanged"
    assert third_result["collection_error_class"] is None
    with factory() as session:
        progress = session.scalar(
            select(SourceCollectionProgress).where(
                SourceCollectionProgress.lane == "issue_recent"
            )
        )
        assert progress is not None
        assert _utc_date(progress.window_start) == today - timedelta(days=6)
        assert progress.status == "incomplete"
        assert progress.cursor.get("day") == (today - timedelta(days=5)).isoformat()


def _run_process_job(factory, job_id, worker_id, definition, client):
    with factory() as session:
        return process_job(session, job_id, worker_id, 1, definition, client)


def test_worker_retry_continues_after_progress_commit_before_job_terminal(
    adversarial_db, monkeypatch
):
    factory = adversarial_db
    definition = _source_definition()
    job_id = _make_source_and_job(
        factory,
        definition,
        status="queued",
        checkpoint=json.dumps({"collection_continuation": True}),
    )
    _complete_nonrecent_lanes(factory, definition)
    import gridlens.ingestion.service as service
    import gridlens.jobs.worker as worker

    count_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal count_calls
        if request.url.params.get("$select") == "count(*) AS row_count":
            count_calls += 1
            count = 1 if count_calls <= 2 else 0
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json=[{"row_count": count}],
            )
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json=[_row_for_request(request)],
        )

    class Admission:
        def __enter__(self):
            return True

        def __exit__(self, *_args):
            return False

    class Renewer:
        def __init__(self, *_args):
            pass

        def start(self):
            return self

        def stop(self):
            pass

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(worker, "WORKER_ID", "c7b-worker")
    monkeypatch.setattr(worker, "try_public_acquisition_admission", lambda *_: Admission())
    monkeypatch.setattr(worker, "FencedLeaseRenewer", Renewer)
    monkeypatch.setattr(
        worker,
        "process_job",
        lambda session, job_id, worker_id, fence, source_definition, **kwargs: service.process_job(
            session,
            job_id,
            worker_id,
            fence,
            source_definition,
            client,
            **kwargs,
        ),
    )
    original_append = worker._append_attempt_receipt
    raised = False

    def fail_terminal_once(*args, **kwargs):
        nonlocal raised
        if not raised:
            raised = True
            raise RuntimeError("injected crash after progress commit")
        return original_append(*args, **kwargs)

    monkeypatch.setattr(worker, "_append_attempt_receipt", fail_terminal_once)
    try:
        assert worker.run_one({definition["id"]: definition}, job_ids=[job_id]) is True
        with factory() as session:
            job = session.get(Job, job_id)
            progress = session.scalar(
                select(SourceCollectionProgress).where(
                    SourceCollectionProgress.lane == "issue_recent"
                )
            )
            assert job is not None and job.status == "queued"
            assert progress is not None and progress.status == "incomplete"
            committed_cursor = dict(progress.cursor)
            assert committed_cursor.get("day") == (
                datetime.now(UTC).date() - timedelta(days=5)
            ).isoformat()

        with factory.begin() as session:
            job = session.get(Job, job_id)
            assert job is not None
            job.available_at = datetime.now(UTC) - timedelta(seconds=1)
        assert worker.run_one({definition["id"]: definition}, job_ids=[job_id]) is True
    finally:
        client.close()

    assert raised
    with factory() as session:
        job = session.get(Job, job_id)
        progress = session.scalar(
            select(SourceCollectionProgress).where(
                SourceCollectionProgress.lane == "issue_recent"
            )
        )
        assert job is not None and job.status == "succeeded"
        assert progress is not None
        assert progress.cursor != committed_cursor
    assert _evidence_count(factory) == 1


@pytest.mark.parametrize(
    ("page_payload", "second_count", "expected_error"),
    [
        ([{"id": "420001"}], 2, "ResultCountChanged"),
        ([], 1, "SourceParseError"),
        ([{"id": "420001", "issue_date": "not-a-date"}], 1, "SourceParseError"),
    ],
    ids=("count-changed", "unexpected-empty-page", "malformed-row"),
)
def test_invalid_or_changed_segment_stays_partial_and_retains_last_good_evidence(
    adversarial_db, page_payload, second_count, expected_error
):
    factory = adversarial_db
    definition = _source_definition()
    job_id = _make_source_and_job(factory, definition)
    day = datetime.now(UTC).date()
    with factory.begin() as session:
        known = Observation(
            source_id=definition["id"],
            external_id="known-last-good",
            title="Previously verified permit",
            abstract="Previously retained fact",
            published_at=day,
            url=definition["endpoint"],
            content_hash="a" * 64,
        )
        session.add(known)
        session.flush()
        session.add(
            Evidence(
                observation_id=known.id,
                content_hash=known.content_hash,
                title=known.title,
                abstract=known.abstract,
                url=known.url,
                published_at=day,
                provenance={"retained": True},
            )
        )

    count_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal count_calls
        if request.url.params.get("$select") == "count(*) AS row_count":
            count_calls += 1
            count = 1 if count_calls == 1 else second_count
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json=[{"row_count": count}],
            )
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json=(
                page_payload
                if expected_error != "ResultCountChanged"
                else [_row_for_request(request)]
            ),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client, factory() as session:
        result = process_job(
            session, job_id, "adversarial-test", 1, definition, client
        )

    assert result["collection_status"] == "PARTIAL"
    assert result["partial"] is True
    assert result["collection_error_class"] == expected_error
    with factory() as session:
        progress = session.scalar(select(SourceCollectionProgress))
        retained = session.scalar(
            select(Observation).where(Observation.external_id == "known-last-good")
        )
        retained_evidence = session.scalar(
            select(Evidence).where(Evidence.content_hash == "a" * 64)
        )
        assert progress is not None and progress.status != "complete"
        assert progress.completed_through is None
        assert retained is not None and retained.abstract == "Previously retained fact"
        assert retained_evidence is not None
    assert _evidence_count(factory) == (2 if expected_error == "ResultCountChanged" else 1)
