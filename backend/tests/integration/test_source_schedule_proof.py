import hashlib
import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from db_reset import reset_test_database
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.persistence.models import (
    Job,
    Source,
    SourceCheckReceipt,
    SourceDueCheck,
    SourceScheduleEpoch,
)
from gridlens.settings import settings


@pytest.fixture
def source_proof_db(monkeypatch):
    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and target.database.endswith("_test")
    assert (target.host, target.port, target.database) != (
        application.host,
        application.port,
        application.database,
    )
    engine = create_engine(settings.test_database_url)
    reset_test_database(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    import gridlens.api.app as api
    import gridlens.ingestion.registry as registry

    monkeypatch.setattr(api, "SessionLocal", factory)
    monkeypatch.setattr(api, "load_registry", lambda: [source_definition()])
    monkeypatch.setattr(registry, "load_registry", lambda: [source_definition()])
    with factory.begin() as session:
        session.add(
            Source(
                id="proof-source",
                publisher="Synthetic",
                endpoint="https://example.invalid/records",
                family="synthetic",
                geography="US",
                industries=[],
                retrieval_method="test",
                cadence_hours=24,
                health={
                    "status": "Overdue",
                    "last_meaningful_update": "2026-10-20T12:00:00+00:00",
                    "last_valid_record": "2026-10-20T11:00:00+00:00",
                    "fetched_records": 12,
                    "accepted_records": 8,
                    "rejected_records": 4,
                    "retry_at": "2026-10-22T12:00:00+00:00",
                },
            )
        )
    yield factory
    engine.dispose()


def source_definition():
    return {
        "id": "proof-source",
        "publisher": "Synthetic",
        "endpoint": "https://example.invalid/records",
        "family": "synthetic",
        "geography": "US",
        "industries": [],
        "retrieval_method": "test",
        "cadence_hours": 24,
        "schedule_mode": "local_daily",
        "timezone": "America/Chicago",
        "schedule_anchor_time": "03:00:00",
        "enabled": True,
    }


def insert_success(session, epoch, scheduled_for, counts, recorded_at):
    job = Job(source_id="proof-source", status="succeeded", fence=1)
    session.add(job)
    session.flush()
    due_key = hashlib.sha256(
        f"proof-source|{epoch.id}|{scheduled_for.isoformat()}".encode()
    ).hexdigest()
    due = SourceDueCheck(
        due_key=due_key,
        source_id="proof-source",
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
            disposition="succeeded",
            check_counts=counts,
            digest=hashlib.sha256(canonical.encode()).hexdigest(),
            recorded_at=recorded_at,
        )
    )


@pytest.mark.parametrize(
    "proof",
    [
        None,
        {
            "schedule_proof_version": 1,
            "acquisition_started_at": "2026-10-17T08:00:00",
            "acquisition_completed_at": "2026-10-17T08:01:00+00:00",
        },
        {
            "schedule_proof_version": 1,
            "acquisition_started_at": "2026-10-18T08:01:00+00:00",
            "acquisition_completed_at": "2026-10-18T08:00:00+00:00",
        },
        {
            "schedule_proof_version": 1,
            "acquisition_started_at": "2026-10-17T08:00:00+00:00",
            "acquisition_completed_at": "2026-10-19T08:00:00+00:00",
        },
    ],
)
def test_health_and_operations_reject_legacy_or_invalid_intervals(source_proof_db, proof):
    import gridlens.api.app as api
    from gridlens.intelligence.intelligence_operations import operations_view

    now = datetime.now(UTC)
    start = now - timedelta(days=2)
    epoch = SourceScheduleEpoch(
        source_id="proof-source",
        registry_enabled=True,
        operator_enabled=True,
        effective_from=start,
        cadence_hours=24,
        schedule_mode="local_daily",
        timezone="America/Chicago",
        anchor={
            "local_date": start.astimezone(ZoneInfo("America/Chicago")).date().isoformat(),
            "local_time": "03:00",
        },
        configuration=source_definition(),
        history_known=True,
    )
    with source_proof_db.begin() as session:
        session.add(epoch)
        session.flush()
        from gridlens.jobs.worker import _scheduled_instants

        scheduled_for = next(_scheduled_instants(epoch, now, not_before=now - timedelta(days=6)))
        counts = {"new": 0, "changed": 0, "unchanged": 1}
        if proof:
            counts.update(proof)
        insert_success(session, epoch, scheduled_for, counts, now)

    source_status = api.health()["sources"][0]
    with source_proof_db() as session:
        source_metrics = operations_view(session)["sources"][0]
    assert source_status["verified_successes_7d"] == 0
    assert source_status["freshness"] == "UNKNOWN"
    assert source_metrics["verified_success_30d"] == 0
    assert source_metrics["unverified_30d"] == 1
    assert source_metrics["freshness_30d"] == "UNKNOWN"


def test_verified_interval_is_counted_by_health_and_operations(source_proof_db):
    import gridlens.api.app as api
    from gridlens.intelligence.intelligence_operations import operations_view
    from gridlens.jobs.worker import _scheduled_instants

    now = datetime.now(UTC)
    start = now - timedelta(days=40)
    epoch = SourceScheduleEpoch(
        source_id="proof-source",
        registry_enabled=True,
        operator_enabled=True,
        effective_from=start,
        cadence_hours=24,
        schedule_mode="local_daily",
        timezone="America/Chicago",
        anchor={
            "local_date": start.astimezone(ZoneInfo("America/Chicago")).date().isoformat(),
            "local_time": "03:00",
        },
        configuration=source_definition(),
        history_known=True,
    )
    with source_proof_db.begin() as session:
        session.add(epoch)
        session.flush()
        slots = list(_scheduled_instants(epoch, now, not_before=now - timedelta(days=30)))
        for slot in slots:
            counts = {
                "new": 0,
                "changed": 0,
                "unchanged": 1,
                "schedule_proof_version": 1,
                "acquisition_started_at": (slot + timedelta(seconds=1)).isoformat(),
                "acquisition_completed_at": (slot + timedelta(seconds=2)).isoformat(),
            }
            insert_success(session, epoch, slot, counts, slot + timedelta(seconds=3))

    source_status = api.health()["sources"][0]
    with source_proof_db() as session:
        source_metrics = operations_view(session)["sources"][0]
    assert source_status["freshness"] == "FRESH"
    assert source_status["verified_successes_7d"] == source_status["due_checks_7d"]
    assert source_metrics["freshness_30d"] == "FRESH"
    assert source_metrics["verified_success_30d"] == len(slots)
    assert source_metrics["unverified_30d"] == 0


def test_health_loads_schedule_epochs_in_one_bulk_query(source_proof_db):
    import gridlens.api.app as api

    with source_proof_db.begin() as session:
        for index in range(5):
            session.add(
                Source(
                    id=f"proof-source-{index}",
                    publisher="Synthetic",
                    endpoint="https://example.invalid/records",
                    family="synthetic",
                    geography="US",
                    industries=[],
                    retrieval_method="test",
                    cadence_hours=24,
                    health={"status": "Unknown"},
                )
            )

    statements = []
    bind = source_proof_db.kw["bind"]

    def record_schedule_query(_conn, _cursor, statement, _parameters, _context, _many):
        if "source_schedule_epochs" in statement.lower():
            statements.append(statement)

    event.listen(bind, "before_cursor_execute", record_schedule_query)
    try:
        payload = api.health()
    finally:
        event.remove(bind, "before_cursor_execute", record_schedule_query)

    assert len(payload["sources"]) == 6
    assert len(statements) == 1
    source = next(item for item in payload["sources"] if item["id"] == "proof-source")
    assert source["cadence_hours"] == 24
    assert source["last_meaningful_update"] == "2026-10-20T12:00:00+00:00"
    assert source["last_valid_record"] == "2026-10-20T11:00:00+00:00"
    assert (source["fetched_records"], source["accepted_records"], source["rejected_records"]) == (
        12,
        8,
        4,
    )
    assert source["retry_at"] == "2026-10-22T12:00:00+00:00"
    assert source["backlog"] == 0
