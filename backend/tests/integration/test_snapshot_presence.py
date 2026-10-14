from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

import gridlens.ingestion.service as service
from gridlens.intelligence.snapshot_presence import (
    ABSENT,
    RETURNED,
    absent_need_ids,
    reconcile_snapshot,
)
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    ChangeEvent,
    Evidence,
    Job,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Source,
)
from gridlens.settings import settings

SOURCE = "georgia-air-draft-title-v"


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
    engine = create_engine(settings.test_database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(
            Source(
                id=SOURCE, publisher="Georgia EPD", endpoint="https://epd.georgia.gov/x",
                family="construction-permits", geography="Georgia", industries=["data centers"],
                retrieval_method="georgia-air-permits", cadence_hours=24, health={},
            )
        )
        session.flush()
        needs = {}
        for key in ("a", "b"):
            observation = Observation(
                source_id=SOURCE, external_id=key, title=f"Filing {key}",
                url=f"https://epd.georgia.gov/{key}", content_hash=f"hash-{key}",
            )
            session.add(observation)
            session.flush()
            session.add(
                Evidence(
                    observation_id=observation.id, content_hash=f"hash-{key}",
                    title=f"Filing {key}", url=f"https://epd.georgia.gov/{key}",
                )
            )
            project = Project(
                identity_key=f"{SOURCE}:{key}", name=f"Project {key}", source_id=SOURCE,
                external_id=key,
            )
            session.add(project)
            session.flush()
            need = PowerNeed(
                project_id=project.id, activity_key="facility-expansion", rationale="r"
            )
            session.add(need)
            session.flush()
            session.add(NeedObservation(need_id=need.id, observation_id=observation.id))
            needs[key] = need.id
        job = Job(
            source_id=SOURCE, status="running", lease_owner="test", fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        job_id = job.id
    yield factory, needs, job_id
    Base.metadata.drop_all(engine)
    engine.dispose()


def kinds(session):
    return [
        (event.kind, event.material)
        for event in session.scalars(select(ChangeEvent).order_by(ChangeEvent.id))
    ]


def test_absence_is_recorded_once_and_return_is_recorded(db):
    factory, needs, _ = db
    with factory.begin() as session:
        assert reconcile_snapshot(session, SOURCE, {"a"})["absent_from_snapshot"] == 1
        assert absent_need_ids(session, list(needs.values())) == {needs["b"]}
    with factory.begin() as session:
        # Replaying the same snapshot adds nothing.
        assert reconcile_snapshot(session, SOURCE, {"a"}) == {
            "absent_from_snapshot": 0, "returned_to_snapshot": 0,
        }
    with factory.begin() as session:
        assert reconcile_snapshot(session, SOURCE, {"a", "b"})["returned_to_snapshot"] == 1
        assert absent_need_ids(session, list(needs.values())) == set()
        assert kinds(session) == [(ABSENT, True), (RETURNED, True)]
    with factory.begin() as session:
        # A second departure is a new, distinct event.
        assert reconcile_snapshot(session, SOURCE, {"a"})["absent_from_snapshot"] == 1
        assert [kind for kind, _ in kinds(session)] == [ABSENT, RETURNED, ABSENT]
        # Evidence, observation and need are retained.
        assert session.get(PowerNeed, needs["b"]).active is True


def test_process_job_reconciles_only_declared_complete_snapshots(db, monkeypatch):
    factory, needs, job_id = db
    seen = []
    monkeypatch.setattr(
        service,
        "retrieve_source",
        lambda *_args: [
            {"document_number": "a"},
            {"document_number": "b", "presence_only": True},
        ],
    )
    monkeypatch.setattr(
        service,
        "process_records",
        lambda _s, _j, _w, _f, _d, records, client=None: seen.append(records) or {"new": 0},
    )
    definition = {"id": SOURCE, "retrieval_method": "georgia-air-permits"}
    with factory() as session:
        service.process_job(session, job_id, "test", 1, definition)
        assert kinds(session) == []
    with factory() as session:
        counts = service.process_job(
            session, job_id, "test", 1, {**definition, "snapshot_complete": True}
        )
        # Presence-only rows are withheld from processing but still count as listed.
        assert seen[-1] == [{"document_number": "a"}]
        assert counts["absent_from_snapshot"] == 0
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [{"document_number": "a"}])
    with factory() as session:
        counts = service.process_job(
            session, job_id, "test", 1, {**definition, "snapshot_complete": True}
        )
        assert counts["absent_from_snapshot"] == 1
        assert absent_need_ids(session, list(needs.values())) == {needs["b"]}
