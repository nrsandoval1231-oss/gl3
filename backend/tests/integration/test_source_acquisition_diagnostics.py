"""Persist safe acquisition diagnostics using only an explicit isolated PostgreSQL DB."""

import hashlib
import json
import pickle
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from db_reset import reset_test_database
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.ingestion.adapters.bounded_http import _safe_acquisition_error
from gridlens.ingestion.adapters.diagnostics import acquisition_stage
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.registry import load_registry
from gridlens.persistence.models import (
    Job,
    Source,
    SourceCheckReceipt,
    SourceCollectionProgress,
    SourceDueCheck,
    SourceScheduleEpoch,
)
from gridlens.settings import settings

PRIOR_SUCCESS = "2026-10-14T18:16:13+00:00"
# Deliberately synthetic canaries, never runtime credentials or real private data.
PRIVATE_CANARY = "synthetic-diagnostic-secret-canary"
PRIVATE_URL = "https://epd.georgia.gov/document/document/fixture/download?token=" + PRIVATE_CANARY


@pytest.fixture
def diagnostics_db(monkeypatch):
    import gridlens.jobs.worker as worker

    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and target.database.endswith("_test"), (
        "Refusing schema reset without an explicit *_test database"
    )
    assert (target.host, target.port, target.database) != (
        application.host,
        application.port,
        application.database,
    ), "TEST_DATABASE_URL must differ from DATABASE_URL"
    engine = create_engine(settings.test_database_url)
    reset_test_database(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    class NoopRenewer:
        def __init__(self, *_args):
            pass

        def start(self):
            return self

        def stop(self):
            pass

    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(worker, "WORKER_ID", "source-diagnostics-test")
    monkeypatch.setattr(worker, "try_public_acquisition_admission", lambda *_: nullcontext(True))
    monkeypatch.setattr(worker, "FencedLeaseRenewer", NoopRenewer)
    try:
        yield factory
    finally:
        engine.dispose()


def _scheduled_job(factory, source_id):
    definition = next(item for item in load_registry() if item["id"] == source_id)
    now = datetime.now(UTC)
    old_health = {
        "status": "Updated",
        "last_success": PRIOR_SUCCESS,
        "new_records": 9331,
        "changed_records": 77,
        "unchanged_records": 18,
        "retrieved_records": 9426,
        "parsed_records": 9426,
        "records_scanned": 9426,
        "permit_accepted": 300,
        "permit_rejected": 9126,
        "parse_failures": 0,
    }
    with factory.begin() as session:
        session.add(
            Source(
                id=definition["id"],
                publisher=definition["publisher"],
                endpoint=definition["endpoint"],
                family=definition["family"],
                geography=definition["geography"],
                industries=definition["industries"],
                retrieval_method=definition["retrieval_method"],
                cadence_hours=definition["cadence_hours"],
                enabled=True,
                registry_enabled=True,
                health=old_health,
            )
        )
        session.flush()
        job = Job(
            source_id=source_id,
            kind="ingestion",
            status="queued",
            attempts=4,
            available_at=now - timedelta(minutes=1),
        )
        epoch = SourceScheduleEpoch(
            source_id=source_id,
            registry_enabled=True,
            operator_enabled=True,
            effective_from=now - timedelta(days=2),
            cadence_hours=24,
            schedule_mode="fixed",
            timezone="UTC",
            anchor={},
            configuration={},
            history_known=True,
        )
        session.add_all([job, epoch])
        session.flush()
        session.add(
            SourceDueCheck(
                due_key=hashlib.sha256(source_id.encode()).hexdigest(),
                source_id=source_id,
                epoch_id=epoch.id,
                scheduled_for=now - timedelta(minutes=10),
                local_day=now.date(),
                configuration={},
                job_id=job.id,
            )
        )
        job_id = job.id
    return definition, job_id


def _wrapped_georgia_forbidden():
    request = httpx.Request("GET", PRIVATE_URL, headers={"authorization": PRIVATE_CANARY})
    response = httpx.Response(
        403,
        request=request,
        headers={"set-cookie": PRIVATE_CANARY},
        text="Synthetic challenge body " + PRIVATE_CANARY,
    )
    try:
        with acquisition_stage("georgia_document"):
            response.raise_for_status()
    except httpx.HTTPError as cause:
        try:
            # Match Georgia's outer request wrapper while also proving that arbitrary
            # wrapper text cannot enter persisted health, job errors or receipts.
            raise SourceParseError("Georgia source request failed: " + PRIVATE_CANARY) from cause
        except SourceParseError as wrapped:
            # Exercise the actual sanitizer and exception pickle transport used by
            # acquisition isolation, without starting a child or making a request.
            return pickle.loads(pickle.dumps(_safe_acquisition_error(wrapped)))
    raise AssertionError("Synthetic HTTP403 did not raise")


def _assert_private_details_absent(job, source, receipts):
    persisted = json.dumps(
        {
            "job_error": job.error,
            "job_checkpoint": job.checkpoint,
            "health": source.health,
            "receipts": [receipt.check_counts for receipt in receipts],
        }
    )
    for forbidden in (
        PRIVATE_CANARY,
        PRIVATE_URL,
        "epd.georgia.gov",
        "set-cookie",
        "authorization",
    ):
        assert forbidden not in persisted


def test_wrapped_http_403_persists_safe_diagnostics_and_success_clears_health(
    diagnostics_db,
    monkeypatch,
):
    import gridlens.ingestion.service as service
    import gridlens.jobs.worker as worker

    factory = diagnostics_db
    definition, job_id = _scheduled_job(factory, "federal-register-eis")

    def fail_retrieval(*_args, **_kwargs):
        raise _wrapped_georgia_forbidden()

    monkeypatch.setattr(service, "retrieve_source", fail_retrieval)
    assert worker.run_one({definition["id"]: definition}, job_ids=[job_id]) is True
    with factory.begin() as session:
        job = session.get(Job, job_id)
        source = session.get(Source, definition["id"])
        receipts = session.scalars(
            select(SourceCheckReceipt).where(
                SourceCheckReceipt.job_id == job_id,
            )
        ).all()
        assert job is not None and source is not None
        assert job.status == "failed" and job.attempts == 5
        assert job.error == "Source acquisition failed: http_status_403 [georgia_document]"
        assert source.health["status"] == "Failed"
        assert source.health["last_success"] == PRIOR_SUCCESS
        assert source.health["parse_failures"] == 1
        assert len(receipts) == 1 and receipts[0].disposition == "failed"
        for persisted in (source.health, receipts[0].check_counts):
            assert persisted["error_code"] == "http_status_403"
            assert persisted["error_stage"] == "georgia_document"
            assert persisted["http_status"] == 403
        _assert_private_details_absent(job, source, receipts)
        failed_receipt_id, failed_counts = receipts[0].id, dict(receipts[0].check_counts)
        # A subsequent successful attempt must clear active errors while retaining
        # the earlier immutable failure receipt and its safe diagnostics.
        job.status, job.attempts = "queued", 0
        job.available_at = datetime.now(UTC) - timedelta(minutes=1)

    monkeypatch.setattr(service, "retrieve_source", lambda *_args, **_kwargs: [])
    assert worker.run_one({definition["id"]: definition}, job_ids=[job_id]) is True
    with factory() as session:
        job = session.get(Job, job_id)
        source = session.get(Source, definition["id"])
        receipts = session.scalars(
            select(SourceCheckReceipt)
            .where(
                SourceCheckReceipt.job_id == job_id,
            )
            .order_by(SourceCheckReceipt.fence)
        ).all()
        assert job is not None and job.status == "succeeded" and job.error is None
        assert source is not None and source.health["status"] == "Checked—No Change"
        assert source.health["last_success"] != PRIOR_SUCCESS
        assert source.health["parse_failures"] == 0
        for field in ("error", "error_code", "error_stage", "http_status"):
            assert source.health[field] is None
        assert len(receipts) == 2 and receipts[-1].disposition == "succeeded"
        assert receipts[0].id == failed_receipt_id and receipts[0].check_counts == failed_counts
        _assert_private_details_absent(job, source, receipts)


def test_structured_parse_failure_persists_partial_diagnostics_and_zero_attempt_counts(
    diagnostics_db,
    monkeypatch,
):
    import gridlens.ingestion.service as service
    import gridlens.jobs.worker as worker

    factory = diagnostics_db
    definition, job_id = _scheduled_job(factory, "austin-building-permits")

    def fail_segment(*_args, **_kwargs):
        with acquisition_stage("public_acquisition"):
            raise SourceParseError("Permit segment rows are out of stable key order")

    # Leave process_job/process_records and the worker real: the parser boundary
    # alone is synthetic, so service-to-receipt diagnostic transport is exercised.
    monkeypatch.setattr(service, "retrieve_collection_segment", fail_segment)
    assert worker.run_one({definition["id"]: definition}, job_ids=[job_id]) is True
    with factory() as session:
        job = session.get(Job, job_id)
        source = session.get(Source, definition["id"])
        receipt = session.scalar(
            select(SourceCheckReceipt).where(
                SourceCheckReceipt.job_id == job_id,
            )
        )
        progress = session.scalar(
            select(SourceCollectionProgress).where(
                SourceCollectionProgress.source_id == definition["id"],
                SourceCollectionProgress.lane == "issue_recent",
            )
        )
        assert job is not None and job.status == "succeeded"
        assert source is not None and source.health["status"] == "Partial"
        assert source.health["last_success"] == PRIOR_SUCCESS
        assert source.health["error_code"] == "permit_row_order"
        assert source.health["error_stage"] == "public_acquisition"
        assert source.health["http_status"] is None
        assert receipt is not None and receipt.disposition == "partial"
        counts = receipt.check_counts
        assert counts["collection_error_code"] == "permit_row_order"
        assert counts["collection_error_stage"] == "public_acquisition"
        assert counts["collection_http_status"] is None
        assert counts["collection_continuation"] is False
        assert counts["collection_observed_count"] == 0
        for health_key, count_key in (
            ("new_records", "new"),
            ("changed_records", "changed"),
            ("unchanged_records", "unchanged"),
            ("retrieved_records", "retrieved_records"),
            ("parsed_records", "parsed_records"),
            ("records_scanned", "records_scanned"),
            ("permit_accepted", "permit_accepted"),
            ("permit_rejected", "permit_rejected"),
        ):
            assert source.health[health_key] == counts[count_key] == 0
        assert progress is not None and progress.completed_through is None
        assert progress.cursor == {} and progress.error_class == "SourceParseError"
