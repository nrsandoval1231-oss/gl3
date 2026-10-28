from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.persistence.database import Base
from gridlens.persistence.models import Job, Source, SourceCollectionProgress
from gridlens.settings import settings


@pytest.fixture
def health_db(monkeypatch):
    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and target.database.endswith("_test")
    assert (target.host, target.port, target.database) != (
        application.host,
        application.port,
        application.database,
    )
    engine = create_engine(settings.test_database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    import gridlens.api.app as api
    import gridlens.ingestion.registry as registry

    monkeypatch.setattr(api, "SessionLocal", factory)
    definitions = [source_definition()]
    monkeypatch.setattr(api, "load_registry", lambda: definitions)
    monkeypatch.setattr(registry, "load_registry", lambda: definitions)
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
                health={"status": "Unknown"},
            )
        )
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


def source_definition():
    return {
        "id": "proof-source",
        "publisher": "Synthetic",
        "endpoint": "https://example.invalid/records",
        "family": "synthetic",
        "geography": "US",
        "industries": [],
        "retrieval_method": "socrata-permits",
        "cadence_hours": 24,
        "schedule_mode": "local_daily",
        "timezone": "America/Chicago",
        "schedule_anchor_time": "03:00:00",
        "enabled": True,
    }


def test_health_reports_processing_backlog_and_collection_progress(health_db, monkeypatch):
    import gridlens.api.app as api
    import gridlens.ingestion.structured_collection as structured_collection
    from gridlens.ingestion.structured_collection import collection_policy_digest

    today = datetime.now(UTC).date()
    definition = source_definition()
    definition["query"] = {"window_days": 7}
    disabled_definition = {**definition, "id": "disabled-source", "enabled": False}
    disabled_definition["retrieval_method"] = "test"
    import gridlens.ingestion.registry as registry

    monkeypatch.setattr(api, "load_registry", lambda: [definition, disabled_definition])
    monkeypatch.setattr(registry, "load_registry", lambda: [definition, disabled_definition])
    monkeypatch.setattr(
        structured_collection,
        "collection_lanes",
        lambda _: ("issue_recent", "issue_history"),
    )
    digest = collection_policy_digest(definition)
    with health_db.begin() as session:
        source = session.get(Source, "proof-source")
        source.health = {
            "status": "Partial",
            "last_success": "2026-10-20T12:00:00+00:00",
            "last_success_counts": {"new_records": 4},
            "collection_status": "PARTIAL",
            "collection_lane": "issue_recent",
            "collection_current_complete": True,
            "collection_window_start": "2026-10-01",
            "collection_window_end": "2026-10-20",
            "collection_jobs_remaining": 3,
            "collection_paused_for_budget": True,
        }
        session.add(
            Source(
                id="disabled-source",
                publisher="Synthetic",
                endpoint="https://example.invalid/disabled",
                family="synthetic",
                geography="US",
                industries=[],
                retrieval_method="test",
                cadence_hours=24,
                enabled=False,
                health={"status": "Disabled"},
            )
        )
        session.flush()
        session.add_all(
            [
                Job(id=uuid4(), source_id="proof-source", status="queued"),
                Job(id=uuid4(), source_id="proof-source", status="running"),
                Job(id=uuid4(), source_id="proof-source", status="failed"),
                Job(id=uuid4(), source_id="disabled-source", status="queued"),
                SourceCollectionProgress(
                    source_id="proof-source",
                    lane="issue_recent",
                    policy_digest=digest,
                    status="complete",
                    window_start=datetime(2026, 10, 1, tzinfo=UTC),
                    window_end=datetime(2026, 10, 20, tzinfo=UTC),
                    completed_through=datetime.combine(today, datetime.min.time(), UTC),
                ),
                SourceCollectionProgress(
                    source_id="proof-source",
                    lane="issue_history",
                    policy_digest=digest,
                    status="incomplete",
                ),
            ]
        )

    payload = api.health()
    sources = {item["id"]: item for item in payload["sources"]}
    assert payload["backlog"] == 2
    assert sources["proof-source"]["backlog"] == 2
    assert sources["proof-source"]["terminal_failed_jobs"] == 1
    assert sources["disabled-source"]["backlog"] == 0
    assert sources["disabled-source"]["terminal_failed_jobs"] == 0
    assert sources["proof-source"]["last_success"] == "2026-10-20T12:00:00+00:00"
    assert sources["proof-source"]["collection_status"] == "PARTIAL"
    assert sources["proof-source"]["collection_lane"] == "issue_recent"
    assert sources["proof-source"]["collection_current_complete"] is True
    assert sources["proof-source"]["collection_jobs_remaining"] == 3
    assert sources["proof-source"]["collection_paused_for_budget"] is True
    assert sources["proof-source"]["pending_collection_lanes"] == ["issue_history"]


def test_health_reports_pending_lane_when_complete_window_has_not_reached_policy_end(
    health_db, monkeypatch
):
    import gridlens.api.app as api
    import gridlens.ingestion.structured_collection as structured_collection
    from gridlens.ingestion.structured_collection import collection_policy_digest

    today = datetime.now(UTC).date()
    definition = source_definition()
    definition["id"] = "austin-building-permits"
    definition["query"] = {"data_center_backfill": {"start": "2026-10-01", "end": "2026-10-30"}}
    import gridlens.ingestion.registry as registry

    monkeypatch.setattr(api, "load_registry", lambda: [definition])
    monkeypatch.setattr(registry, "load_registry", lambda: [definition])
    monkeypatch.setattr(
        structured_collection,
        "collection_lanes",
        lambda _: ("issue_recent", "issue_history", "issue_backfill"),
    )
    digest = collection_policy_digest(definition)
    with health_db.begin() as session:
        source = session.get(Source, "proof-source")
        source.id = "austin-building-permits"
        session.add_all(
            [
                SourceCollectionProgress(
                    source_id="austin-building-permits",
                    lane=lane,
                    policy_digest=digest,
                    status="complete",
                    completed_through=datetime.combine(through, datetime.min.time(), UTC),
                )
                for lane, through in (
                    ("issue_recent", today),
                    ("issue_history", today),
                    ("issue_backfill", date(2026, 10, 20)),
                )
            ]
        )
    result = next(
        item for item in api.health()["sources"] if item["id"] == "austin-building-permits"
    )
    assert result["pending_collection_lanes"] == ["issue_backfill"]


def test_health_reports_empty_when_all_lanes_are_caught_up(health_db, monkeypatch):
    import gridlens.api.app as api
    import gridlens.ingestion.structured_collection as structured_collection
    from gridlens.ingestion.structured_collection import collection_policy_digest

    today = datetime.now(UTC).date()
    definition = source_definition()
    definition["query"] = {"window_days": 7}
    import gridlens.ingestion.registry as registry

    monkeypatch.setattr(api, "load_registry", lambda: [definition])
    monkeypatch.setattr(registry, "load_registry", lambda: [definition])
    monkeypatch.setattr(
        structured_collection,
        "collection_lanes",
        lambda _: ("issue_recent", "issue_history"),
    )
    digest = collection_policy_digest(definition)
    with health_db.begin() as session:
        session.add_all(
            [
                SourceCollectionProgress(
                    source_id="proof-source",
                    lane=lane,
                    policy_digest=digest,
                    status="complete",
                    completed_through=datetime.combine(today, datetime.min.time(), UTC),
                )
                for lane in ("issue_recent", "issue_history")
            ]
        )
    result = next(item for item in api.health()["sources"] if item["id"] == "proof-source")
    assert result["pending_collection_lanes"] == []


def test_health_ignores_stale_policy_progress_and_disabled_lanes(health_db, monkeypatch):
    import gridlens.api.app as api
    import gridlens.ingestion.structured_collection as structured_collection
    from gridlens.ingestion.structured_collection import collection_policy_digest

    definition = source_definition()
    definition["query"] = {"window_days": 7}
    disabled = {**definition, "id": "disabled-source", "enabled": False}
    import gridlens.ingestion.registry as registry

    monkeypatch.setattr(api, "load_registry", lambda: [definition, disabled])
    monkeypatch.setattr(registry, "load_registry", lambda: [definition, disabled])
    monkeypatch.setattr(
        structured_collection,
        "collection_lanes",
        lambda _: ("issue_recent", "issue_history"),
    )
    digest = collection_policy_digest(definition)
    with health_db.begin() as session:
        session.add(
            Source(
                id="disabled-source",
                publisher="Synthetic",
                endpoint="https://example.invalid/disabled",
                family="synthetic",
                geography="US",
                industries=[],
                retrieval_method="test",
                cadence_hours=24,
                enabled=False,
                health={"status": "Disabled"},
            )
        )
        session.add_all(
            [
                SourceCollectionProgress(
                    source_id="proof-source",
                    lane="issue_recent",
                    policy_digest="0" * 64,
                    status="incomplete",
                ),
                SourceCollectionProgress(
                    source_id="disabled-source",
                    lane="issue_recent",
                    policy_digest=digest,
                    status="incomplete",
                ),
            ]
        )
    sources = {item["id"]: item for item in api.health()["sources"]}
    assert sources["proof-source"].get("pending_collection_lanes") is None
    assert sources["disabled-source"].get("pending_collection_lanes") is None


def test_health_collection_progress_is_unknown_without_metadata(health_db):
    import gridlens.api.app as api

    source = next(item for item in api.health()["sources"] if item["id"] == "proof-source")
    assert source.get("collection_status") is None
    assert source.get("collection_lane") is None
    assert source.get("collection_current_complete") is None
    assert source.get("collection_jobs_remaining") is None
    assert source.get("collection_paused_for_budget") is None
    assert source.get("pending_collection_lanes") is None


def test_unknown_schedule_proof_does_not_inherit_healthy_from_historical_success(health_db):
    import gridlens.api.app as api

    with health_db.begin() as session:
        source = session.get(Source, "proof-source")
        assert source is not None
        source.health = {
            "status": "Updated",
            "last_attempt": datetime.now(UTC).isoformat(),
            "last_success": "2026-10-20T12:00:00+00:00",
        }

    result = next(item for item in api.health()["sources"] if item["id"] == "proof-source")

    assert result["enabled"] is True
    assert result["freshness"] == "UNKNOWN"
    assert result["last_success"] == "2026-10-20T12:00:00+00:00"
    assert result["operational_status"] == "Unknown"
