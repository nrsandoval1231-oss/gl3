import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from time import monotonic
from uuid import UUID

import httpx
import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.registry import load_registry
from gridlens.ingestion.service import process_job
from gridlens.jobs.queue import lease_one
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    ChangeEvent,
    Evidence,
    Interpretation,
    Job,
    LifecycleEvent,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    ProjectLifecycle,
    ProjectMatchDecision,
    Source,
)
from gridlens.settings import settings


def federal_register_source():
    return next(source for source in load_registry() if source["id"] == "federal-register-eis")


@pytest.fixture
def db():
    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and (target.database == "test" or target.database.endswith("_test")), (
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
    with factory.begin() as session:
        session.add(
            Source(
                id="federal-register-eis",
                publisher="Federal Register",
                endpoint="https://www.federalregister.gov/api/v1/documents.json",
                family="structured-government",
                geography="US",
                industries=["mining"],
                retrieval_method="json-api",
                health={},
            )
        )
        session.flush()
        job = Job(
            source_id="federal-register-eis",
            status="running",
            lease_owner="test",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        job_id = job.id
    yield engine, factory, job_id
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(autouse=True)
def synthetic_structured_segment_for_ingestion_semantics(monkeypatch):
    """Keep permit-domain tests on explicit synthetic rows, not adapter HTTP behavior."""
    import gridlens.ingestion.service as service

    original_segment = service.retrieve_collection_segment

    def synthetic_segment(source, lane, start, end, cursor, client=None, *, deadline=None):
        if source.get("retrieval_method") not in {"socrata-permits", "boston-ckan-permits"}:
            return original_segment(source, lane, start, end, cursor, client, deadline=deadline)
        records = service.retrieve_source(source, client)
        return {
            "records": records,
            "cursor": {},
            "partial": False,
            "window_complete": True,
            "expected_count": len(records),
            "observed_count": len(records),
        }

    monkeypatch.setattr(service, "retrieve_collection_segment", synthetic_segment)


def response_for(row: dict):
    return {"total_pages": 1, "count": 1, "results": [row]}


def record(abstract: str):
    return {
        "document_number": "TEST-0001",
        "title": "Silver Ridge Mine: Synthetic Test Notice",
        "abstract": abstract,
        "publication_date": "2026-09-14",
        "html_url": "https://www.federalregister.gov/documents/2026/09/14/TEST-0001/synthetic-test-notice",
    }


def run(factory, job_id, row):
    definition = federal_register_source()
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response_for(row)))
    )
    with factory() as session:
        return process_job(session, job_id, "test", 1, definition, client)


def test_replay_versions_and_withdrawal_preserve_evidence(db):
    _, factory, job_id = db
    initial = record(
        "The proposed Mine Plan of Operations would develop the mine, with dewatering "
        "and ventilation shafts."
    )
    assert run(factory, job_id, initial)["signals"] == 0
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Observation)) == 1
        retained = session.scalar(select(Evidence))
        assert retained is not None
        assert retained.extraction_location == "title and abstract"
    assert run(factory, job_id, initial)["unchanged"] == 1
    changed = record(initial["abstract"] + " Construction access roads will also be required.")
    assert run(factory, job_id, changed)["changed"] == 1
    assert run(factory, job_id, initial)["changed"] == 1
    negative = record("The proposed development was canceled and will not proceed.")
    run(factory, job_id, negative)
    run(factory, job_id, negative)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Observation)) == 1
        assert session.scalar(select(func.count()).select_from(Project)) == 0
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 0
        assert session.scalar(select(func.count()).select_from(Evidence)) == 3
        assert session.scalar(select(func.count()).select_from(NeedObservation)) == 0
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == 0
        assert session.scalar(select(Observation.published_at)) == datetime(2026, 9, 14).date()
        assert session.scalar(select(PowerNeed.active)) is None
        assert session.scalar(select(Interpretation.status)) == "rejected"


def test_linked_negative_correction_locks_project_before_need(db):
    engine, factory, job_id = db
    initial = record(
        "The proposed Mine Plan of Operations would develop the mine, with dewatering "
        "and ventilation shafts."
    )
    run(factory, job_id, initial)
    with factory.begin() as session:
        observation = session.scalar(select(Observation))
        assert observation is not None
        project = Project(
            identity_key="legacy-project-identity-differs-from-correction",
            name="Legacy linked project",
            location="Silver Ridge, Nevada",
            source_id=observation.source_id,
            external_id="legacy-project-id",
        )
        session.add(project)
        session.flush()
        identity_project = Project(
            identity_key="federal-register-eis:TEST-0001",
            name="Correction-key project",
            location="Unrelated site, Nevada",
            source_id=observation.source_id,
            external_id=observation.external_id,
        )
        session.add(identity_project)
        session.flush()
        need = PowerNeed(
            project_id=project.id,
            activity_key="facility-expansion",
            tier="Signal",
            rationale="Previously linked supported need.",
            active=True,
        )
        session.add(need)
        session.flush()
        session.add(NeedObservation(need_id=need.id, observation_id=observation.id))

    statements = []

    def capture_for_update(_conn, _cursor, statement, _parameters, _context, _many):
        if "for update" in statement.casefold():
            statements.append(statement.casefold())

    event.listen(engine, "before_cursor_execute", capture_for_update)
    try:
        negative = record("The proposed development was canceled and will not proceed.")
        run(factory, job_id, negative)
    finally:
        event.remove(engine, "before_cursor_execute", capture_for_update)
    project_lock = next(i for i, sql in enumerate(statements) if "from projects" in sql)
    need_lock = next(i for i, sql in enumerate(statements) if "from power_needs" in sql)
    assert project_lock < need_lock, statements
    with factory() as session:
        need = session.scalar(select(PowerNeed))
        assert need is not None and not need.active


def test_linked_negative_correction_does_not_hold_need_while_waiting_for_project(db):
    engine, factory, job_id = db
    initial = record(
        "The proposed Mine Plan of Operations would develop the mine, with dewatering "
        "and ventilation shafts."
    )
    run(factory, job_id, initial)
    with factory.begin() as session:
        observation = session.scalar(select(Observation))
        assert observation is not None
        project = Project(
            identity_key="legacy-project-identity-differs-from-correction",
            name="Legacy linked project",
            location="Silver Ridge, Nevada",
            source_id=observation.source_id,
            external_id="legacy-project-id",
        )
        session.add(project)
        session.flush()
        session.add(
            Project(
                identity_key="federal-register-eis:TEST-0001",
                name="Correction-key project",
                location="Unrelated site, Nevada",
                source_id=observation.source_id,
                external_id=observation.external_id,
            )
        )
        session.flush()
        need = PowerNeed(
            project_id=project.id,
            activity_key="facility-expansion",
            tier="Signal",
            rationale="Previously linked supported need.",
            active=True,
        )
        session.add(need)
        session.flush()
        session.add(NeedObservation(need_id=need.id, observation_id=observation.id))
        project_id, need_id = project.id, need.id

    project_lock_attempted = Event()
    worker_done = Event()

    def observe_wait_point(conn, _cursor, statement, _parameters, _context, _many):
        if (
            conn.info.get("linked_negative_worker")
            and "for update" in statement.casefold()
            and "from projects" in statement.casefold()
            and "projects.id" in statement.casefold()
        ):
            project_lock_attempted.set()

    event.listen(engine, "before_cursor_execute", observe_wait_point)

    def correction():
        definition = federal_register_source()
        client = httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json=response_for(
                        record("The proposed development was canceled and will not proceed.")
                    ),
                )
            )
        )
        with factory() as session:
            session.connection().info["linked_negative_worker"] = True
            try:
                return process_job(session, job_id, "test", 1, definition, client)
            finally:
                worker_done.set()

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            with factory.begin() as lock_holder:
                lock_holder.execute(text("SET LOCAL lock_timeout = '1500ms'"))
                lock_holder.scalar(
                    select(Project.id).where(Project.id == project_id).with_for_update()
                )
                lock_holder.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:project_id, 0))"),
                    {"project_id": str(project_id)},
                )
                future = executor.submit(correction)
                reached_project = project_lock_attempted.wait(2)
                # The worker is blocked on the project row. It must not already
                # own the need row, so the lock holder can acquire it and commit.
                need_available = False
                if reached_project:
                    need_available = (
                        lock_holder.scalar(
                            select(PowerNeed.id).where(PowerNeed.id == need_id).with_for_update()
                        )
                        == need_id
                    )
            result = future.result(6)
            assert worker_done.is_set()
            assert reached_project and need_available
            assert result["changed"] == 1
    finally:
        event.remove(engine, "before_cursor_execute", observe_wait_point)
    with factory() as session:
        need = session.get(PowerNeed, need_id)
        assert need is not None and not need.active


def test_permit_assessment_replay_correction_and_deactivation(db):
    _, factory, _ = db
    from datetime import date

    definition = next(row for row in load_registry() if row["id"] == "austin-building-permits")
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
                cadence_hours=24,
                health={},
            )
        )
        session.flush()
        job = Job(
            source_id=definition["id"],
            status="running",
            lease_owner="test",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        job_id = job.id
    row = {
        "permit_number": "2026-SYN-1",
        "issue_date": "2020-05-10",
        "statusdate": date.today().isoformat(),
        "description": "Replace natural gas generator and ATS at existing telecom shelter.",
        "permit_class_mapped": "Commercial",
        "work_class": "New",
        "permit_type_desc": "Building Permit",
        "status_current": "Active",
        "original_address1": "100 Factory Way",
        "original_city": "AUSTIN",
        "original_state": "TX",
        "project_id": "SYN-1",
        "link": {"url": "https://abc.austintexas.gov/permit/1"},
    }

    def run():
        def handler(request):
            params = dict(request.url.params)
            assert "statusdate >=" in params["$where"]
            return httpx.Response(200, json=[{"row_count": "1"}] if "$select" in params else [row])

        with factory() as session:
            return process_job(
                session,
                job_id,
                "test",
                1,
                definition,
                httpx.Client(transport=httpx.MockTransport(handler)),
            )

    assert run()["signals"] == 1
    assert run()["unchanged"] == 1
    row["description"] = "Rental generator installed and supplying construction loads."
    assert run()["changed"] == 1
    with factory() as session:
        interpretation = session.scalar(
            select(Interpretation)
            .join(Observation)
            .where(Observation.source_id == definition["id"])
        )
        assert interpretation is not None
        assert interpretation.status == "rejected"
        assert interpretation.assessment["rental_category"] == "secured_supply"
        assert interpretation.assessment["previous_decisions"]
        assert (
            session.scalar(
                select(PowerNeed.active).join(Project).where(Project.source_id == definition["id"])
            )
            is False
        )
    with factory.begin() as session:
        interpretation = session.scalar(
            select(Interpretation)
            .join(Observation)
            .where(Observation.source_id == definition["id"])
        )
        assert interpretation is not None
        interpretation.evaluator_version = "permit-project-v4"
        close_event_count = session.scalar(select(func.count()).select_from(ChangeEvent))
    assert run()["unchanged"] == 1
    with factory() as session:
        interpretation = session.scalar(
            select(Interpretation)
            .join(Observation)
            .where(Observation.source_id == definition["id"])
        )
        assert interpretation is not None
        assert interpretation.status == "rejected"
        assert interpretation.assessment["rental_category"] == "secured_supply"
        assert interpretation.assessment["evaluator_version"] == "permit-project-v8"
        assert (
            interpretation.assessment["previous_decisions"][-1]["evaluator_version"]
            == "permit-project-v4"
        )
        assert (
            session.scalar(
                select(PowerNeed.active).join(Project).where(Project.source_id == definition["id"])
            )
            is False
        )
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == close_event_count
        history_count = len(interpretation.assessment["previous_decisions"])
        evidence_count = session.scalar(select(func.count()).select_from(Evidence))
    assert run()["unchanged"] == 1
    with factory() as session:
        interpretation = session.scalar(
            select(Interpretation)
            .join(Observation)
            .where(Observation.source_id == definition["id"])
        )
        assert interpretation is not None
        assert len(interpretation.assessment["previous_decisions"]) == history_count
        assert session.scalar(select(func.count()).select_from(Evidence)) == evidence_count
    row["status_current"] = "Withdrawn"
    assert run()["changed"] == 1
    with factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(Observation)
                .where(Observation.source_id == definition["id"])
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(Evidence)
                .join(Observation)
                .where(Observation.source_id == definition["id"])
            )
            == 3
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(Project)
                .where(Project.source_id == definition["id"])
            )
            == 1
        )
        assert (
            session.scalar(
                select(PowerNeed.active).join(Project).where(Project.source_id == definition["id"])
            )
            is False
        )
        assert (
            session.scalar(
                select(Interpretation.status)
                .join(Observation)
                .where(Observation.source_id == definition["id"])
            )
            == "rejected"
        )


def test_permit_v5_rejected_to_v6_clause_recovery_and_replay(db):
    _, factory, _ = db
    from datetime import date

    definition = next(row for row in load_registry() if row["id"] == "austin-building-permits")
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
                cadence_hours=24,
                health={},
            )
        )
        session.flush()
        job = Job(
            source_id=definition["id"],
            status="running",
            lease_owner="test",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        job_id = job.id
    row = {
        "permit_number": "2026-SYN-009",
        "issue_date": date.today().isoformat(),
        "description": (
            "Temporary generator installed and supplying phase 1; no additional rental power "
            "required for phase 1. Separate construction power required for phase 2."
        ),
        "permit_class_mapped": "Commercial",
        "work_class": "New",
        "permit_type_desc": "Building Permit",
        "status_current": "Active",
        "original_address1": "100 Factory Way",
        "original_city": "AUSTIN",
        "original_state": "TX",
        "project_id": "SYN-009",
        "link": {"url": "https://abc.austintexas.gov/permit/9"},
    }

    def run():
        def handler(request):
            return httpx.Response(
                200, json=[{"row_count": "1"}] if "$select" in dict(request.url.params) else [row]
            )

        with factory() as session:
            return process_job(
                session,
                job_id,
                "test",
                1,
                definition,
                httpx.Client(transport=httpx.MockTransport(handler)),
            )

    assert run()["signals"] == 1
    with factory.begin() as session:
        interpretation = session.scalar(
            select(Interpretation)
            .join(Observation)
            .where(Observation.source_id == definition["id"])
        )
        assert interpretation is not None
        prior = dict(interpretation.assessment)
        prior.update(
            {
                "decision": "rejected",
                "tier": None,
                "reason": (
                    "Permit reports temporary power as provided or secured; "
                    "no open rental need is asserted."
                ),
                "subject": None,
                "action": None,
                "rental_category": "secured_supply",
                "reported_claim": None,
                "rental_hypothesis": None,
            }
        )
        interpretation.status = "rejected"
        interpretation.evaluator_version = "permit-project-v5"
        interpretation.assessment = prior
        temporary_need = session.scalar(
            select(PowerNeed).join(Project).where(Project.source_id == definition["id"])
        )
        assert temporary_need is not None
        temporary_need.active = False
    assert run()["unchanged"] == 1
    assert run()["unchanged"] == 1
    with factory() as session:
        needs = session.scalars(
            select(PowerNeed).join(Project).where(Project.source_id == definition["id"])
        ).all()
        active = [need for need in needs if need.active]
        assert len(active) == 1 and active[0].activity_key == "temporary-power"
        interpretation = session.scalar(
            select(Interpretation)
            .join(Observation)
            .where(Observation.source_id == definition["id"])
        )
        assert interpretation is not None and interpretation.assessment["previous_decisions"]
        assert interpretation.assessment["evaluator_version"] == "permit-project-v8"
        assert (
            interpretation.assessment["previous_decisions"][-1]["evaluator_version"]
            == "permit-project-v5"
        )
        event_count = session.scalar(select(func.count()).select_from(ChangeEvent))
        link_count = session.scalar(select(func.count()).select_from(NeedObservation))
    row["status_current"] = "Withdrawn"
    assert run()["changed"] == 1
    with factory() as session:
        assert not session.scalar(
            select(PowerNeed.active).join(Project).where(Project.source_id == definition["id"])
        )
        # Legacy closure plus an evidence-bound power-state material delta.
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == event_count + 2
        assert session.scalar(select(func.count()).select_from(NeedObservation)) == link_count


def test_event_signal_closes_after_explicit_end_date_on_same_hash_replay(db, monkeypatch):
    _, factory, _ = db
    from datetime import date as RealDate

    import gridlens.ingestion.service as service
    from gridlens.domain.permit_interpretation import assess_permit

    definition = next(row for row in load_registry() if row["id"] == "austin-building-permits")
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
                cadence_hours=24,
                health={},
            )
        )
        session.flush()
        job = Job(
            source_id=definition["id"],
            status="running",
            lease_owner="test",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        job_id = job.id

    row = {
        "permit_number": "2026-EVENT-1",
        "issue_date": "2026-09-27",
        "description": "Concert stage with food vendors October 2-4, 2026.",
        "permit_class_mapped": "Commercial",
        "work_class": "Temporary",
        "permit_type_desc": "Event Permit",
        "status_current": "Active",
        "original_address1": "1 Festival Way",
        "original_city": "AUSTIN",
        "original_state": "TX",
        "project_id": "EVENT-1",
        "link": {"url": "https://abc.austintexas.gov/permit/event-1"},
    }
    as_of = [RealDate(2026, 10, 4)]

    class FrozenDate(RealDate):
        @classmethod
        def today(cls):
            return as_of[0]

    original_assess = assess_permit

    def assess_at_frozen_date(record):
        return original_assess(record, as_of=as_of[0])

    monkeypatch.setattr(service, "date", FrozenDate)
    monkeypatch.setattr(service, "assess_permit", assess_at_frozen_date)

    def run():
        def handler(request):
            payload = [{"row_count": "1"}] if "$select" in dict(request.url.params) else [row]
            return httpx.Response(200, json=payload)

        with factory() as session:
            return process_job(
                session,
                job_id,
                "test",
                1,
                definition,
                httpx.Client(transport=httpx.MockTransport(handler)),
            )

    assert run()["permit_accepted"] == 1
    with factory() as session:
        observation = session.scalar(select(Observation))
        interpretation = session.scalar(select(Interpretation))
        need = session.scalar(select(PowerNeed))
        assert observation is not None and interpretation is not None and need is not None
        assert interpretation.status == "accepted"
        assert interpretation.assessment["activity_end_date"] == "2026-10-04"
        assert interpretation.assessment["review_after"] == "2026-10-04"
        assert need.active is True and need.activity_key == "event-power"
        source_hash = observation.content_hash
        first_snapshot = (
            observation.content_hash,
            interpretation.status,
            json.dumps(interpretation.assessment, sort_keys=True),
            need.active,
            session.scalar(select(func.count()).select_from(ChangeEvent)),
            session.scalar(select(func.count()).select_from(NeedObservation)),
        )
    assert run()["unchanged"] == 1
    with factory() as session:
        observation = session.scalar(select(Observation))
        interpretation = session.scalar(select(Interpretation))
        need = session.scalar(select(PowerNeed))
        assert observation is not None and interpretation is not None and need is not None
        repeated_end_day = (
            observation.content_hash,
            interpretation.status,
            json.dumps(interpretation.assessment, sort_keys=True),
            need.active,
            session.scalar(select(func.count()).select_from(ChangeEvent)),
            session.scalar(select(func.count()).select_from(NeedObservation)),
        )
        assert repeated_end_day == first_snapshot

    as_of[0] = RealDate(2026, 10, 5)
    assert run()["permit_rejected"] == 1
    with factory() as session:
        observation = session.scalar(select(Observation))
        interpretation = session.scalar(select(Interpretation))
        need = session.scalar(select(PowerNeed))
        assert observation is not None and interpretation is not None and need is not None
        assert observation.content_hash == source_hash
        assert interpretation.status == "rejected"
        assert interpretation.assessment["rental_category"] == "past_event"
        assert need.active is False
        closed_snapshot = (
            observation.content_hash,
            interpretation.status,
            json.dumps(interpretation.assessment, sort_keys=True),
            need.active,
            session.scalar(select(func.count()).select_from(ChangeEvent)),
            session.scalar(select(func.count()).select_from(NeedObservation)),
        )
        # Legacy closure plus an evidence-bound power-state material delta.
        assert closed_snapshot[-2] == first_snapshot[-2] + 2
    assert run()["unchanged"] == 1
    with factory() as session:
        observation = session.scalar(select(Observation))
        interpretation = session.scalar(select(Interpretation))
        need = session.scalar(select(PowerNeed))
        assert observation is not None and interpretation is not None and need is not None
        repeated_next_day = (
            observation.content_hash,
            interpretation.status,
            json.dumps(interpretation.assessment, sort_keys=True),
            need.active,
            session.scalar(select(func.count()).select_from(ChangeEvent)),
            session.scalar(select(func.count()).select_from(NeedObservation)),
        )
        assert repeated_next_day == closed_snapshot


def test_interpretation_failure_is_durable_and_retried_on_replay(db, monkeypatch):
    _, factory, job_id = db
    import gridlens.ingestion.service as service

    original = service.interpret
    monkeypatch.setattr(
        service, "interpret", lambda row: (_ for _ in ()).throw(RuntimeError("transient"))
    )
    row = record(
        "The proposed Mine Plan of Operations would develop the mine, with dewatering "
        "infrastructure."
    )
    run(factory, job_id, row)
    with factory() as session:
        assert session.scalar(select(Interpretation.status)) == "failed"
        assert session.scalar(select(func.count()).select_from(Evidence)) == 1
    monkeypatch.setattr(service, "interpret", original)
    run(factory, job_id, row)
    with factory() as session:
        assert session.scalar(select(Interpretation.status)) == "accepted"
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 0


def test_pdf_representation_is_companion_evidence_not_a_second_discovery(db, monkeypatch):
    _, factory, job_id = db
    import gridlens.ingestion.service as service

    row = record(
        "The proposed Mine Plan of Operations would develop the mine, with dewatering "
        "and ventilation shafts."
    )
    row["document_number"] = "2099-01001"
    row["title"] = "Forest District; Arizona; Silver Ridge Mine Project"
    row["html_url"] = "https://www.federalregister.gov/documents/2099/01/01/2099-01001/synthetic"
    row["pdf_url"] = "https://www.govinfo.gov/content/pkg/FR-2099-01-01/pdf/2099-01001.pdf"
    pdf_hash = ["a" * 64]
    monkeypatch.setattr(
        service,
        "retrieve_companion",
        lambda *_args: [
            {
                "content_hash": pdf_hash[0],
                "title": row["title"],
                "abstract": "Silver Ridge Mine Project; dewatering wells.",
                "url": row["pdf_url"],
                "published_at": row["publication_date"],
                "extraction_location": "GovInfo PDF page 1",
            }
        ],
    )
    assert run(factory, job_id, row)["signals"] == 0
    assert run(factory, job_id, row)["unchanged"] == 1
    pdf_hash[0] = "d" * 64
    assert run(factory, job_id, row)["unchanged"] == 1
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Observation)) == 1
        assert session.scalar(select(func.count()).select_from(Project)) == 0
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 0
        assert session.scalar(select(func.count()).select_from(Evidence)) == 3
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == 0
        locations = set(session.scalars(select(Evidence.extraction_location)))
        assert "GovInfo PDF page 1" in locations


def test_pdf_is_not_downloaded_for_non_signal_records(db, monkeypatch):
    _, factory, job_id = db
    import gridlens.ingestion.service as service

    row = record("The agency announces a general grant and employment policy update.")
    row["pdf_url"] = "https://www.govinfo.gov/content/pkg/FR-2099-01-01/pdf/2099-01001.pdf"
    monkeypatch.setattr(
        service,
        "retrieve_companion",
        lambda *_args: (_ for _ in ()).throw(AssertionError("PDF should not be fetched")),
    )
    counts = run(factory, job_id, row)
    assert counts["pdf_candidates"] == 1
    assert counts["pdf_skipped_not_signal"] == 1
    assert counts["pdf_enriched"] == 0


def test_pdf_evidence_and_interpretation_failure_remain_durable(db, monkeypatch):
    _, factory, job_id = db
    import gridlens.ingestion.service as service

    row = record(
        "The proposed Mine Plan of Operations would develop the mine, with dewatering "
        "and ventilation shafts."
    )
    row["pdf_url"] = "https://www.govinfo.gov/content/pkg/FR-2099-01-01/pdf/2099-01001.pdf"
    monkeypatch.setattr(
        service,
        "retrieve_companion",
        lambda *_args: [
            {
                "content_hash": "e" * 64,
                "title": row["title"],
                "abstract": "Silver Ridge Mine Project; dewatering wells.",
                "url": row["pdf_url"],
                "published_at": row["publication_date"],
                "extraction_location": "GovInfo PDF page 1",
            }
        ],
    )
    monkeypatch.setattr(
        service,
        "interpret",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("transient")),
    )
    run(factory, job_id, row)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Observation)) == 1
        assert session.scalar(select(func.count()).select_from(Evidence)) == 2
        assert session.scalar(select(Interpretation.status)) == "failed"


def test_nonmaterial_source_revision_retains_new_evidence_without_today_change(db, monkeypatch):
    _, factory, job_id = db
    import gridlens.ingestion.service as service

    initial = record(
        "The proposed Mine Plan of Operations would develop the mine, with dewatering "
        "and ventilation shafts."
    )
    initial["source_hash"] = "b" * 64
    current = [initial]
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: current)
    assert run(factory, job_id, initial)["signals"] == 0
    replay = dict(initial)
    replay["source_hash"] = "c" * 64  # Body/footer revision outside retained excerpt.
    current[0] = replay
    assert run(factory, job_id, replay)["unchanged"] == 1
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Observation)) == 1
        assert session.scalar(select(func.count()).select_from(Project)) == 0
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 0
        assert session.scalar(select(func.count()).select_from(Evidence)) == 2
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == 0


def test_prior_candidate_hash_replays_without_a_migration_or_duplicate_evidence(db):
    _, factory, job_id = db
    row = record(
        "The proposed Mine Plan of Operations would develop the mine, with dewatering "
        "and ventilation shafts."
    )
    assert run(factory, job_id, row)["signals"] == 0
    prior_hash = hashlib.sha256(
        json.dumps(
            {**row, "pdf_url": None},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    with factory.begin() as session:
        observation = session.scalar(select(Observation))
        evidence = session.scalar(select(Evidence))
        assert observation and evidence
        observation.content_hash = prior_hash
        evidence.content_hash = prior_hash
    assert run(factory, job_id, row)["unchanged"] == 1
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Evidence)) == 1
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == 0


def test_lifecycle_projection_is_evidence_version_bound_and_never_uses_publication_date(db):
    _, factory, _ = db
    from gridlens.intelligence.lifecycle_service import (
        apply_lifecycle_observation,
        lifecycle_event_supported,
        refresh_lifecycle_projection,
    )

    with factory.begin() as session:
        project = Project(
            identity_key="lifecycle:test",
            name="Test well",
            location="Oklahoma",
            source_id="federal-register-eis",
            external_id="lifecycle-test",
            asset_type="unknown",
        )
        observation = Observation(
            source_id="federal-register-eis",
            external_id="lifecycle-test",
            title="Spud reported at Test well",
            abstract=None,
            published_at=datetime(2026, 9, 20).date(),
            url="https://example.test/well",
            content_hash="b" * 64,
        )
        session.add_all([project, observation])
        session.flush()
        evidence = Evidence(
            observation_id=observation.id,
            content_hash=observation.content_hash,
            title="Spud reported at Test well",
            abstract=None,
            url=observation.url,
            published_at=observation.published_at,
            extraction_location="title",
            event_date=datetime(2026, 9, 10).date(),
            event_date_label="Permit issue date",
        )
        session.add(evidence)
        session.flush()
        session.add(
            Interpretation(
                observation_id=observation.id,
                content_hash=evidence.content_hash,
                status="accepted",
                evaluator_version="test",
                assessment={
                    "semantic_hash": observation.content_hash,
                    "evidence_hash": evidence.content_hash,
                    "evidence": {"id": str(evidence.id)},
                    "project_identity_key": project.identity_key,
                },
            )
        )
        session.flush()
        apply_lifecycle_observation(session, project, observation, evidence)
        event = session.scalar(select(LifecycleEvent))
        projection = session.get(ProjectLifecycle, project.id)
        assert event is not None and event.occurred_on is None
        assert projection is not None and projection.current_state == "spud"
        from gridlens.intelligence.lifecycle_replay import replay_accepted_lifecycle

        assert replay_accepted_lifecycle(session)["events_added"] == 0
        assert replay_accepted_lifecycle(session)["events_added"] == 0
        hash_a, hash_b = evidence.content_hash, "c" * 64
        corrected = Evidence(
            observation_id=observation.id,
            content_hash=hash_b,
            title="Routine regional operations update",
            abstract=None,
            url=observation.url,
            published_at=observation.published_at,
            extraction_location="title",
        )
        session.add(corrected)
        session.flush()
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == observation.id)
        )
        assert interpretation is not None
        interpretation.content_hash = hash_b
        interpretation.assessment = {
            "semantic_hash": hash_b,
            "evidence_hash": corrected.content_hash,
            "evidence": {"id": str(corrected.id)},
            "project_identity_key": project.identity_key,
        }
        observation.content_hash = hash_b
        interpretation.status = "accepted"
        apply_lifecycle_observation(session, project, observation, corrected)
        assert session.scalar(select(func.count()).select_from(LifecycleEvent)) == 1
        assert session.get(ProjectLifecycle, project.id) is None
        assert project.asset_type == "unknown"

        # A correction may return to a retained accepted evidence version. Its event
        # must become current again, and the existing-event path restores asset type.
        observation.content_hash = hash_a
        interpretation.content_hash = hash_a
        interpretation.status = "accepted"
        interpretation.assessment = {
            "semantic_hash": hash_a,
            "evidence_hash": hash_a,
            "evidence": {"id": str(evidence.id)},
            "project_identity_key": project.identity_key,
        }
        assert apply_lifecycle_observation(session, project, observation, evidence) is False
        projection = session.get(ProjectLifecycle, project.id)
        assert projection is not None and projection.current_state == "spud"
        assert project.asset_type == "upstream_well"

        observation.content_hash = hash_b
        assert not lifecycle_event_supported("spud", evidence, interpretation, project, "spud")
        refresh_lifecycle_projection(session, project)
        session.flush()
        assert session.get(ProjectLifecycle, project.id) is None
        observation.content_hash = hash_a
        interpretation.content_hash = hash_b
        assert not lifecycle_event_supported("spud", evidence, interpretation, project, "spud")
        interpretation.content_hash = hash_a
        interpretation.assessment["evidence_hash"] = hash_b
        assert not lifecycle_event_supported("spud", evidence, interpretation, project, "spud")
        interpretation.assessment["evidence_hash"] = hash_a
        assert apply_lifecycle_observation(session, project, observation, evidence) is False
        assert session.get(ProjectLifecycle, project.id).current_state == "spud"


def test_identity_match_requires_corroborated_site_and_keeps_ambiguous_candidates_separate(
    db, monkeypatch
):
    _, factory, job_id = db
    import gridlens.ingestion.service as service

    definition = federal_register_source()
    first = {
        "document_number": "FIRST",
        "title": "Same Facility",
        "abstract": "123 Main Street, Austin, TX",
        "publication_date": "2026-09-14",
        "html_url": "https://example.test/first",
    }
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [first])
    monkeypatch.setattr(
        service,
        "interpret",
        lambda row: {
            "name": row["title"],
            "activity_key": "mine-development",
            "rationale": "Specific construction evidence",
            "location": row["abstract"],
        },
    )
    with factory() as session:
        process_job(session, job_id, "test", 1, definition, None)
    with factory.begin() as session:
        session.add(
            Source(
                id="second-source",
                publisher="Test Publisher",
                endpoint=definition["endpoint"],
                family="test",
                geography="US",
                industries=["industrial"],
                retrieval_method="json-api",
                health={},
            )
        )
        session.flush()
        job = Job(
            source_id="second-source",
            status="running",
            lease_owner="test",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        second_job_id = job.id
    second = {**first, "document_number": "SECOND", "html_url": "https://example.test/second"}
    second_definition = {**definition, "id": "second-source", "retrieval_method": "json-api"}
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [second])
    with factory() as session:
        process_job(session, second_job_id, "test", 1, second_definition, None)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Project)) == 0
        assert session.scalar(select(func.count()).select_from(NeedObservation)) == 0
        assert session.scalar(select(func.count()).select_from(Observation)) == 2
    second["abstract"] = "500 Different Avenue, Austin, TX"
    second["html_url"] = "https://example.test/second-corrected"
    with factory() as session:
        process_job(session, second_job_id, "test", 1, second_definition, None)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Evidence)) == 3
        assert session.scalar(select(func.count()).select_from(ProjectMatchDecision)) == 0
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 0


def test_city_only_location_does_not_match_even_when_names_are_equal(db, monkeypatch):
    _, factory, job_id = db
    import gridlens.ingestion.service as service

    rows = [
        {
            "document_number": "CITY-1",
            "title": "Same Facility",
            "abstract": "Austin, TX",
            "publication_date": "2026-09-14",
            "html_url": "https://example.test/city1",
        }
    ]
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: rows)
    monkeypatch.setattr(
        service,
        "interpret",
        lambda row: {
            "name": row["title"],
            "activity_key": "mine-development",
            "rationale": "Specific construction evidence",
            "location": row["abstract"],
        },
    )
    definition = federal_register_source()
    with factory() as session:
        process_job(session, job_id, "test", 1, definition, None)
    rows[0]["document_number"] = "CITY-2"
    rows[0]["html_url"] = "https://example.test/city2"
    with factory() as session:
        process_job(session, job_id, "test", 1, definition, None)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Project)) == 0
        assert session.scalar(select(func.count()).select_from(Observation)) == 2
        assert session.scalar(select(func.count()).select_from(ProjectMatchDecision)) == 0


def test_multiple_supported_identity_candidates_remain_separate_with_reasons(db, monkeypatch):
    _, factory, job_id = db
    import gridlens.ingestion.service as service
    from gridlens.persistence.models import ProjectMatchDecision

    with factory.begin() as session:
        for suffix in ("a", "b"):
            session.add(
                Project(
                    identity_key=f"candidate:{suffix}",
                    name="Same Facility",
                    location="123 Main Street, Austin, TX",
                    source_id="federal-register-eis",
                    external_id=suffix,
                    identity_facts={
                        "project_name": "Same Facility",
                        "site": "123 Main Street, Austin, TX",
                    },
                )
            )
    row = {
        "document_number": "AMBIGUOUS",
        "title": "Same Facility",
        "abstract": "123 Main Street, Austin, TX",
        "publication_date": "2026-09-14",
        "html_url": "https://example.test/ambiguous",
    }
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [row])
    monkeypatch.setattr(
        service,
        "interpret",
        lambda value: {
            "name": value["title"],
            "activity_key": "mine-development",
            "rationale": "Specific construction evidence",
            "location": value["abstract"],
        },
    )
    with factory() as session:
        process_job(session, job_id, "test", 1, federal_register_source(), None)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Project)) == 2
        assert session.scalar(select(func.count()).select_from(ProjectMatchDecision)) == 0
        assert session.scalar(select(func.count()).select_from(Observation)) == 1
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 0


def test_unapproved_lifecycle_source_preserves_versions_without_opportunity_admission(
    db, monkeypatch
):
    _, factory, _ = db
    from fastapi.testclient import TestClient

    import gridlens.api.app as api
    import gridlens.ingestion.service as service
    from gridlens.security import token_for

    source_ids = ("synthetic-well-permit", "synthetic-well-spud", "synthetic-well-completion")
    jobs = {}
    with factory.begin() as session:
        for source_id in source_ids:
            session.add(
                Source(
                    id=source_id,
                    publisher="Synthetic lifecycle fixture",
                    endpoint="https://example.test/feed",
                    family="test",
                    geography="US",
                    industries=["industrial"],
                    retrieval_method="json-api",
                    health={},
                )
            )
            session.flush()
            job = Job(
                source_id=source_id,
                status="running",
                lease_owner="test",
                fence=1,
                lease_until=datetime.now(UTC) + timedelta(minutes=10),
            )
            session.add(job)
            session.flush()
            jobs[source_id] = job.id

    def row(source_id, external_id, title, event_date, label, abstract="Source-reported milestone"):
        return {
            "document_number": external_id,
            "title": title,
            "abstract": abstract,
            "publication_date": "2026-09-20",
            "event_date": event_date,
            "event_date_label": label,
            "html_url": f"https://example.test/{source_id}/{external_id}",
        }

    permit = row(
        source_ids[0],
        "P-1",
        "Operator begins construction after a well permit at Site A",
        "2026-06-10",
        "Permit issue date",
    )
    completion = row(
        source_ids[2],
        "C-1",
        "Operator begins construction after well completion at Site A",
        "2026-07-24",
        "Completion date",
    )
    spud_a = row(
        source_ids[1],
        "S-1",
        "Operator begins construction after spud at Site A",
        "2026-07-12",
        "Spud date",
    )
    rows = {source_ids[0]: [permit], source_ids[1]: [spud_a], source_ids[2]: [completion]}
    monkeypatch.setattr(
        service, "retrieve_source", lambda definition, _client: rows[definition["id"]]
    )
    monkeypatch.setattr(
        service,
        "interpret",
        lambda _record: {
            "name": "Atlas Mesa Well",
            "activity_key": "facility-expansion",
            "rationale": "Synthetic upstream lifecycle fixture; not a power requirement.",
            "location": "123 Main Street, Austin, TX",
        },
    )

    def ingest(source_id):
        with factory() as session:
            return process_job(
                session,
                jobs[source_id],
                "test",
                1,
                {"id": source_id, "retrieval_method": "json-api"},
            )

    # An arbitrary lifecycle feed is research context, even when its text says
    # permit. Source authority cannot be manufactured by a mock interpretation.
    for source_id in source_ids:
        assert ingest(source_id)["signals"] == 0
        assert ingest(source_id)["unchanged"] == 1
    rows[source_ids[1]] = [
        row(
            source_ids[1],
            "S-1",
            "Operator begins construction after spud at Site A",
            "2026-07-13",
            "Spud date",
        )
    ]
    assert ingest(source_ids[1])["unchanged"] == 1
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Observation)) == 3
        assert session.scalar(select(func.count()).select_from(Evidence)) == 4
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 0
        dates = set(session.scalars(select(Evidence.event_date)))
        assert datetime(2026, 7, 12).date() in dates
        assert datetime(2026, 7, 13).date() in dates
    monkeypatch.setattr(api, "SessionLocal", factory)
    client = TestClient(api.app)
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    response = client.get("/api/opportunities?tier=Signal")
    assert response.status_code == 200 and response.json() == []


def test_similar_project_names_at_different_sites_remain_distinct_and_unknown(db, monkeypatch):
    _, factory, job_id = db
    import gridlens.ingestion.service as service

    abstract = (
        "The proposed Mine Plan of Operations would develop the mine with dewatering "
        "infrastructure."
    )
    rows = [
        {
            **record(abstract),
            "document_number": "2099-01011",
            "title": "Forest District; Arizona; Silver Ridge Mine Project",
            "html_url": "https://www.federalregister.gov/documents/2099/01/01/2099-01011/synthetic",
        },
        {
            **record(abstract),
            "document_number": "2099-01012",
            "title": "Forest District; Nevada; Silver Ridge Mine Project",
            "html_url": "https://www.federalregister.gov/documents/2099/01/01/2099-01012/synthetic",
        },
    ]
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: rows)
    counts = run(factory, job_id, rows[0])
    assert counts["signals"] == 0
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Project)) == 0
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 0
        observations = session.scalars(select(Observation)).all()
        assert len(observations) == 2
        assert any("Arizona" in row.title for row in observations)
        assert any("Nevada" in row.title for row in observations)


def test_same_version_reclassification_deactivates_unsupported_need_idempotently(db, monkeypatch):
    _, factory, job_id = db
    import gridlens.ingestion.service as service

    row = record(
        "The proposed Mine Plan of Operations would develop the mine, with dewatering "
        "and ventilation shafts."
    )
    original = service.interpret
    states = [original, lambda _row: None, lambda _row: None]
    monkeypatch.setattr(service, "interpret", lambda value: states.pop(0)(value))
    assert run(factory, job_id, row)["signals"] == 0
    assert run(factory, job_id, row)["unchanged"] == 1
    with factory() as session:
        need = session.scalar(select(PowerNeed))
        assert need is None
        assert session.scalar(select(Interpretation.status)) == "rejected"
        assert session.scalar(select(func.count()).select_from(Evidence)) == 1
        assert session.scalar(select(func.count()).select_from(NeedObservation)) == 0
        events = session.scalars(select(ChangeEvent).order_by(ChangeEvent.id)).all()
        assert [event.kind for event in events] == []
        event_count = len(events)
    assert run(factory, job_id, row)["unchanged"] == 1
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == event_count
        assert session.scalar(select(func.count()).select_from(Evidence)) == 1
        assert session.scalar(select(PowerNeed.active)) is None


def test_houston_sold_event_correction_clears_legacy_publication_date(db, monkeypatch):
    """Correct the existing row projection while retaining its old evidence version."""
    _, factory, _ = db
    definition = next(row for row in load_registry() if row["id"] == "houston-weekly-permits")
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
                cadence_hours=24,
                health={},
            )
        )
        session.flush()
        job = Job(
            source_id=definition["id"],
            status="running",
            lease_owner="test",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        job_id = job.id

    row = {
        "document_number": "26051624:Building Pmt:2026-09-02",
        "title": "Houston sold permit 26051624 — Building Pmt",
        "abstract": (
            "row: 26051624\nevent: Sold\ndate: 2026-09-02\nstatus: Unknown\n"
            "type: Building Pmt\naddress: 8930 GULF FWY A\n"
            "description: 2,765 SQ. FT. CONVERT TO LABORATORY"
        ),
        "publication_date": "2026-09-02",
        "event_date": "2026-09-02",
        "event_date_label": "Permit date",
        "html_url": "https://www.houstonpermittingcenter.org/weekly.xlsx",
        "extraction_location": "Old workbook parser",
        "permit": {
            "source_type": "houston-weekly-permits",
            "city": "Houston",
            "state": "TX",
            "address": "8930 GULF FWY A",
            "description": "2,765 SQ. FT. CONVERT TO LABORATORY",
            "type": "Building Pmt",
            "status": "Unknown",
            "issuance_event": "issued",
            "project": "26051624",
            "row_id": "26051624:Building Pmt:2026-09-02",
        },
    }
    import gridlens.ingestion.service as service

    current = [row]
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: current)

    def ingest():
        with factory() as session:
            return service.process_job(session, job_id, "test", 1, definition)

    ingest()
    corrected = {
        **row,
        "publication_date": None,
        "event_date_label": "Permit sale date (weekly Sold Permits report)",
        "abstract": row["abstract"].replace(
            "event: Sold", "event: Sold (weekly report; issued permit event)"
        ),
        "permit": {**row["permit"], "issuance_event": "sold"},
        "extraction_location": "Official weekly report 2026-09-01 through 2026-09-08; sheet1 row 6",
    }
    current[0] = corrected
    assert ingest()["changed"] == 1
    assert ingest()["unchanged"] == 1
    with factory() as session:
        observation = session.scalar(select(Observation))
        assert observation is not None
        assert observation.published_at is None
        assert session.scalar(select(func.count()).select_from(Observation)) == 1
        evidence = list(session.scalars(select(Evidence)))
        assert len(evidence) == 2
        old = next(item for item in evidence if item.extraction_location == "Old workbook parser")
        current = next(
            item for item in evidence if item.extraction_location.startswith("Official weekly")
        )
        assert old.published_at.isoformat() == "2026-09-02"
        assert old.event_date_label == "Permit date"
        assert old.event_date.isoformat() == "2026-09-02"
        assert current.published_at is None
        assert current.event_date_label == "Permit sale date (weekly Sold Permits report)"
        assert current.event_date.isoformat() == "2026-09-02"


def test_same_version_context_reinterpretation_preserves_source_display_fields(db):
    _, factory, job_id = db

    row = record(
        "The proposed Mine Plan of Operations would develop the mine, with dewatering "
        "and ventilation shafts."
    )
    row["title"] = "Forest District; New Mexico; Roca Honda Mine Project"
    assert run(factory, job_id, row)["signals"] == 0
    assert run(factory, job_id, row)["unchanged"] == 1
    with factory() as session:
        assert session.scalar(select(Project)) is None
        observation = session.scalar(select(Observation))
        assert observation and observation.title == row["title"]
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == 0


def test_source_parse_failure_preserves_prior_accepted_context(db):
    _, factory, job_id = db
    row = record(
        "The proposed Mine Plan of Operations would develop the mine, with dewatering "
        "and ventilation shafts."
    )
    assert run(factory, job_id, row)["signals"] == 0

    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200, text="<html><body>unexpected login page</body></html>"
            )
        )
    )
    with factory() as session, pytest.raises(SourceParseError):
        process_job(session, job_id, "test", 1, federal_register_source(), client)
    client.close()

    with factory() as session:
        observation = session.scalar(select(Observation))
        project = session.scalar(select(Project))
        need = session.scalar(select(PowerNeed))
        assert observation is not None
        assert observation.published_at.isoformat() == row["publication_date"]
        assert session.scalar(select(func.count()).select_from(Observation)) == 1
        assert session.scalar(select(func.count()).select_from(Evidence)) == 1
        assert project is None
        assert session.scalar(select(func.count()).select_from(Project)) == 0
        assert need is None
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 0


def test_reclaimed_fence_blocks_stale_pdf_and_interpretation_writes(db, monkeypatch):
    _, factory, job_id = db
    import gridlens.ingestion.service as service

    initial = record(
        "The proposed Mine Plan of Operations would develop the mine, with dewatering "
        "and ventilation shafts."
    )
    replacement = dict(initial)
    replacement["abstract"] += " Construction access roads will also be required."
    retrieved = [initial, replacement]

    def retrieve_rows(*_args):
        return retrieved.pop(0)

    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [retrieve_rows()])
    calls = 0
    new_worker_result = {}

    def pdf_citation(row, _client):
        nonlocal calls
        calls += 1
        citation = {
            "content_hash": ("b" if calls > 1 else "a") * 64,
            "title": row["title"],
            "abstract": "Synthetic companion excerpt",
            "url": "https://www.govinfo.gov/content/pkg/FR-2099-01-01/pdf/2099-01001.pdf",
            "published_at": row["publication_date"],
            "extraction_location": "GovInfo PDF page 1",
        }
        if calls == 1:
            with factory.begin() as session:
                job = session.get(Job, job_id)
                assert job is not None
                job.lease_until = datetime.now(UTC) - timedelta(seconds=1)
            with factory() as session:
                lease = lease_one(session, "replacement", lease_seconds=600)
                assert lease is not None
                _, replacement_fence = lease
                session.commit()
            with factory() as replacement_session:
                new_worker_result.update(
                    process_job(
                        replacement_session,
                        job_id,
                        "replacement",
                        replacement_fence,
                        federal_register_source(),
                    )
                )
        return [citation]

    monkeypatch.setattr(service, "retrieve_companion", pdf_citation)
    initial["pdf_url"] = replacement["pdf_url"] = (
        "https://www.govinfo.gov/content/pkg/FR-2099-01-01/pdf/2099-01001.pdf"
    )
    with factory() as old_session, pytest.raises(RuntimeError, match="fence lost"):
        process_job(old_session, job_id, "test", 1, federal_register_source())
        old_session.rollback()

    assert new_worker_result["changed"] == 1
    assert calls == 2
    with factory() as session:
        observation = session.scalar(select(Observation))
        interpretation = session.scalar(select(Interpretation))
        project = session.scalar(select(Project))
        need = session.scalar(select(PowerNeed))
        assert observation is not None
        assert observation.content_hash == service._hash(replacement)
        assert interpretation is not None and interpretation.status == "accepted"
        assert interpretation.content_hash == service._hash(replacement)
        assert project is None
        assert need is None
        evidence_hashes = set(session.scalars(select(Evidence.content_hash)))
        assert "a" * 64 not in evidence_hashes
        assert "b" * 64 in evidence_hashes
        assert len(evidence_hashes) == 3  # Old/new raw versions plus replacement PDF.
        events = session.scalars(select(ChangeEvent)).all()
        assert events == []


@pytest.mark.parametrize(
    "candidate_sites,matched",
    [
        (["123 Main Street, Austin, TX"], True),
        (["Austin, TX"], False),
        (["123 Main Street, Austin, TX", "123 Main Street, Austin, TX"], False),
    ],
)
def test_authoritative_permit_identity_requires_one_exact_site_candidate(
    db, monkeypatch, candidate_sites, matched
):
    engine, factory, _ = db
    import gridlens.ingestion.service as service

    definition = next(s for s in load_registry() if s["id"] == "austin-building-permits")
    with factory.begin() as session:
        session.add(
            Source(
                id=definition["id"],
                publisher=definition["publisher"],
                endpoint=definition["endpoint"],
                family=definition["family"],
                geography=definition["geography"],
                industries=[],
                retrieval_method=definition["retrieval_method"],
                health={},
            )
        )
        session.flush()
        for index, site in enumerate(candidate_sites):
            session.add(
                Project(
                    identity_key=f"synthetic:site:{index}",
                    name="Synthetic Atlas campus",
                    source_id=definition["id"],
                    external_id=f"prior-{index}",
                    location=site,
                    identity_facts={"site": site, "project_aliases": ["Synthetic Atlas campus"]},
                )
            )
        job = Job(
            source_id=definition["id"],
            status="running",
            lease_owner="test",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        job_id = job.id
    permit = {
        "document_number": "SYNTHETIC-ID-1",
        "title": "Synthetic construction permit",
        "abstract": "Construction of a new data center at 123 Main Street, Austin, TX.",
        "publication_date": "2026-09-20",
        "event_date": "2026-09-20",
        "html_url": "https://abc.austintexas.gov/permit/synthetic",
        "permit": {
            "row_id": "SYNTHETIC-ID-1",
            "description": "Construction of a new data center.",
            "status": "Active",
            "address": "123 Main Street",
            "city": "Austin",
            "state": "TX",
            "project": "Synthetic Atlas campus",
            "source_fields": {},
        },
    }
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [permit])
    locks = []

    def capture_project_locks(_conn, _cursor, statement, _parameters, _context, _many):
        sql = statement.casefold()
        if "from projects" in sql and "for update" in sql:
            locks.append(sql)

    event.listen(engine, "before_cursor_execute", capture_project_locks)
    try:
        with factory() as session:
            first = process_job(session, job_id, "test", 1, definition)
            replay = process_job(session, job_id, "test", 1, definition)
    finally:
        event.remove(engine, "before_cursor_execute", capture_project_locks)
    assert first["signals"] == 1 and replay["unchanged"] == 1
    # The old implementation emitted `FROM projects FOR UPDATE` here. The
    # structured path now discovers first and locks each candidate by UUID.
    assert locks and any("where projects.id" in statement for statement in locks), locks
    assert not any("from projects for update" in statement for statement in locks), locks
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Project)) == (
            len(candidate_sites) + (0 if matched else 1)
        )
        need = session.scalar(select(PowerNeed))
        assert need and need.active and need.tier == "Signal" and need.required_mw is None
        decisions = session.scalars(select(ProjectMatchDecision)).all()
        assert decisions
        assert {d.decision for d in decisions} == ({"matched"} if matched else {"separate"})
        assert all(d.evidence_id is not None for d in decisions)
        if len(candidate_sites) > 1:
            assert all("Multiple supported" in d.reason for d in decisions)


def test_structured_ingestion_locks_candidates_in_news_compatible_uuid_order(db, monkeypatch):
    engine, factory, _ = db
    import gridlens.ingestion.service as service
    from gridlens.intelligence.change_detection import lock_project

    definition = next(
        source for source in load_registry() if source["id"] == "austin-building-permits"
    )
    lower_id, higher_id = UUID(int=1), UUID(int=2)
    with factory.begin() as session:
        session.add(
            Source(
                id=definition["id"],
                publisher=definition["publisher"],
                endpoint=definition["endpoint"],
                family=definition["family"],
                geography=definition["geography"],
                industries=[],
                retrieval_method=definition["retrieval_method"],
                health={},
            )
        )
        session.flush()
        # Both are real identity candidates for this permit. Insert higher
        # first; the worker must still request the lower project lock first.
        for project_id in (higher_id, lower_id):
            session.add(
                Project(
                    id=project_id,
                    identity_key=f"synthetic:{project_id}",
                    name="New synthetic campus",
                    source_id=definition["id"],
                    external_id=str(project_id),
                    location="123 Main Street, Austin, TX",
                    identity_facts={"site": "123 Main Street, Austin, TX"},
                )
            )
        session.flush()
        job = Job(
            source_id=definition["id"],
            status="running",
            lease_owner="test",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        job_id = job.id
    permit = {
        "document_number": "ORDER-1",
        "title": "Synthetic construction permit",
        "abstract": "Construction of a new data center at 123 Main Street, Austin, TX.",
        "publication_date": "2026-09-20",
        "event_date": "2026-09-20",
        "html_url": "https://example.test/permit/order-1",
        "permit": {
            "row_id": "ORDER-1",
            "description": "Construction of a new data center.",
            "status": "Active",
            "address": "123 Main Street",
            "city": "Austin",
            "state": "TX",
            "project": "New synthetic campus",
            "source_fields": {},
        },
    }
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [permit])
    requested_lower, worker_done = Event(), Event()
    worker_pid = []

    def observe_lock(conn, _cursor, statement, parameters, _context, _many):
        values = parameters.values() if isinstance(parameters, dict) else parameters or []
        if (
            conn.info.get("structured_order_worker")
            and "from projects" in statement.casefold()
            and "where projects.id" in statement.casefold()
            and "for update" in statement.casefold()
            and lower_id in values
        ):
            worker_pid.append(conn.connection.driver_connection.info.backend_pid)
            requested_lower.set()

    def worker():
        with factory() as session:
            session.connection().info["structured_order_worker"] = True
            try:
                return process_job(session, job_id, "test", 1, definition)
            finally:
                worker_done.set()

    event.listen(engine, "before_cursor_execute", observe_lock)
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            with factory.begin() as holder:
                lock_project(holder, lower_id)
                holder_pid = holder.scalar(text("SELECT pg_backend_pid()"))
                future = executor.submit(worker)
                assert requested_lower.wait(2)
                assert worker_pid
                # before_cursor_execute runs before PostgreSQL receives the
                # query. Wait for PostgreSQL's own blocker view rather than
                # treating that pre-send marker as proof of contention.
                deadline = monotonic() + 2
                blocked = False
                while monotonic() < deadline:
                    blocked = bool(
                        holder.scalar(
                            text("SELECT :holder = ANY(pg_blocking_pids(:worker))"),
                            {"holder": holder_pid, "worker": worker_pid[0]},
                        )
                    )
                    if blocked:
                        break
                    assert not worker_done.is_set()
                    worker_done.wait(0.02)
                assert blocked
                assert (
                    holder.scalar(
                        select(Project.id)
                        .where(Project.id == higher_id)
                        .with_for_update(nowait=True)
                    )
                    == higher_id
                )
            result = future.result(6)
            assert worker_done.is_set() and result["signals"] == 1
        with factory() as session:
            candidate_ids = set(
                session.scalars(
                    select(ProjectMatchDecision.candidate_project_id).where(
                        ProjectMatchDecision.candidate_project_id.in_((lower_id, higher_id))
                    )
                ).all()
            )
            assert candidate_ids == {lower_id, higher_id}
    finally:
        event.remove(engine, "before_cursor_execute", observe_lock)


def test_structured_ingestion_does_not_wait_on_unrelated_project_lock(db, monkeypatch):
    _, factory, _ = db
    import gridlens.ingestion.service as service
    from gridlens.intelligence.change_detection import lock_project

    definition = next(
        source for source in load_registry() if source["id"] == "austin-building-permits"
    )
    with factory.begin() as session:
        session.add(
            Source(
                id=definition["id"],
                publisher=definition["publisher"],
                endpoint=definition["endpoint"],
                family=definition["family"],
                geography=definition["geography"],
                industries=[],
                retrieval_method=definition["retrieval_method"],
                health={},
            )
        )
        session.flush()
        unrelated = Project(
            identity_key="unrelated-dallas-project",
            name="Different Dallas Facility",
            source_id=definition["id"],
            external_id="unrelated-dallas",
            location="Dallas, TX",
            identity_facts={"site": "Dallas, TX"},
        )
        relevant = Project(
            identity_key="relevant-austin-project",
            name="New synthetic campus",
            source_id=definition["id"],
            external_id="relevant-austin",
            location="123 Main Street, Austin, TX",
            identity_facts={"site": "123 Main Street, Austin, TX"},
        )
        session.add_all([unrelated, relevant])
        job = Job(
            source_id=definition["id"],
            status="running",
            lease_owner="test",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        unrelated_id, relevant_id, job_id = unrelated.id, relevant.id, job.id
    permit = {
        "document_number": "UNRELATED-LOCK-1",
        "title": "Synthetic construction permit",
        "abstract": "Construction of a new data center at 123 Main Street, Austin, TX.",
        "publication_date": "2026-09-20",
        "event_date": "2026-09-20",
        "html_url": "https://example.test/permit/unrelated-lock-1",
        "permit": {
            "row_id": "UNRELATED-LOCK-1",
            "description": "Construction of a new data center.",
            "status": "Active",
            "address": "123 Main Street",
            "city": "Austin",
            "state": "TX",
            "project": "New synthetic campus",
            "source_fields": {},
        },
    }
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [permit])
    actual_lock_project = service.lock_project
    requested_project_ids = []

    def only_relevant_project_locks(session, project_id):
        requested_project_ids.append(project_id)
        assert project_id != unrelated_id, "Unrelated project was locked during structured ingest"
        return actual_lock_project(session, project_id)

    monkeypatch.setattr(service, "lock_project", only_relevant_project_locks)

    def process():
        with factory() as session:
            session.execute(text("SET LOCAL lock_timeout = '700ms'"))
            return process_job(session, job_id, "test", 1, definition)

    with factory.begin() as holder:
        lock_project(holder, unrelated_id)
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(process).result(timeout=3)["signals"] == 1
    assert relevant_id in requested_project_ids


def test_rrc_amendment_rollover_history_no_duplicate_asset_or_inferred_production(db, monkeypatch):
    import gridlens.api.app as api
    import gridlens.ingestion.service as service
    from gridlens.ingestion.adapters.rrc_drilling import PORTAL

    _, factory, _ = db
    monkeypatch.setattr(api, "SessionLocal", factory)
    definition = next(row for row in load_registry() if row["id"] == "texas-rrc-drilling-permits")
    with factory.begin() as session:
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
                    )
                },
                health={},
            )
        )
        session.flush()
        job = Job(
            source_id=definition["id"],
            status="running",
            lease_owner="test",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        job_id = job.id

    def row(sequence, status="Approved", application_type="01"):
        digest = hashlib.sha256(f"{sequence}:{status}:{application_type}".encode()).hexdigest()
        return {
            "document_number": "9999999",
            "title": "Drilling permit 9999999",
            "abstract": (
                f"amendment_sequence: {sequence}\noperator: EXAMPLE OPERATOR LLC"
                f"\nlease: Example\nwell: 1H\nstatus: {status}"
                f"\napplication_type: {application_type}"
            ),
            "publication_date": "2026-09-01",
            "event_date": "2026-09-01",
            "html_url": PORTAL,
            "source_hash": digest,
            "extraction_location": "Synthetic OGA049M fixture",
            "permit": {
                "source_type": definition["id"],
                "project": "9999999",
                "row_id": "9999999",
                "lease": "Example",
                "well": "1H",
                "operator": "EXAMPLE OPERATOR LLC",
                "location": "RRC county code 001, Texas",
                "state": "TX",
                "status": status,
                "description": "Drilling permit 9999999",
                "application_type": application_type,
                "sequence": sequence,
            },
        }

    incoming = [row(98)]
    monkeypatch.setattr(service, "retrieve_source", lambda *_: incoming)

    def run():
        with factory() as session:
            return process_job(session, job_id, "test", 1, definition)

    assert run()["signals"] == 1
    assert run()["unchanged"] == 1
    from gridlens.intelligence.buying_chain import enrich_buying_chain

    fetched = []

    def forbidden_refetch(url):
        fetched.append(url)
        raise AssertionError("Native permit facts must not need a portal refetch")

    with factory.begin() as session:
        project = session.scalar(select(Project))
        result = enrich_buying_chain(session, project.id, fetcher=forbidden_refetch)
        assert fetched == []
        assert result["candidates"][0]["organization"] == "EXAMPLE OPERATOR LLC"
        assert result["candidates"][0]["person_name"] is None
    incoming[:] = [row(99)]  # Older filing returning in a rollover snapshot.
    assert run()["older_amendments_retained"] == 1
    run()
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Project)) == 1
        assert session.scalar(select(func.count()).select_from(Observation)) == 1
        assert session.scalar(select(func.count()).select_from(Evidence)) == 2
        assert "amendment_sequence: 98" in session.scalar(select(Observation.abstract))
        projection = session.scalar(select(ProjectLifecycle))
        assert projection.current_state == "drilling_permit"
        assert projection.time_to_power_start is None and projection.time_to_power_end is None
        need = session.scalar(select(PowerNeed))
        assert need.tier == "Signal" and need.required_mw is None
    incoming[:] = [row(97, application_type="14")]
    run()
    with factory() as session:
        assert session.scalar(select(ProjectLifecycle)) is None
        assert session.scalar(select(Project.asset_type)) == "upstream_well"
        active = session.scalars(select(PowerNeed).where(PowerNeed.active.is_(True))).all()
        assert len(active) == 1 and active[0].activity_key == "well-permit"
    assert [item["activity"] for item in api.opportunities(tier="Signal")] == ["well-permit"]
    incoming[:] = [row(96, "Cancelled")]
    run()
    with factory() as session:
        assert session.scalar(select(PowerNeed.active)) is False
        assert session.scalar(select(func.count()).select_from(Project)) == 1
        assert session.scalar(select(func.count()).select_from(Evidence)) == 4
    assert api.opportunities(tier="Signal") == []


def test_interconnection_history_survives_real_rejected_correction(db):
    import importlib.util
    from copy import deepcopy
    from datetime import date
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy.exc import DBAPIError

    from gridlens.intelligence.interconnection import (
        attach_interconnection_facts,
        current_interconnection_state,
    )
    from gridlens.persistence.models import InterconnectionFactVersion

    _, factory, job_id = db
    initial = record("Study completed for the synthetic mine interconnection request.")
    run(factory, job_id, initial)
    with factory.begin() as session:
        observation = session.scalar(select(Observation))
        evidence = session.scalar(select(Evidence))
        interpretation = session.scalar(select(Interpretation))
        project = Project(
            identity_key="retained-synthetic-request",
            name="Synthetic mine",
            source_id=observation.source_id,
            external_id="retained-request",
        )
        session.add(project)
        session.flush()
        migration_path = (
            Path(__file__).resolve().parents[2]
            / "migrations"
            / "versions"
            / "0018_interconnection_fact_versions.py"
        )
        spec = importlib.util.spec_from_file_location("interconnection_migration", migration_path)
        assert spec is not None and spec.loader is not None
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        connection = session.connection()
        connection.execute(
            text(
                """CREATE OR REPLACE FUNCTION reject_immutable_history_mutation()
            RETURNS trigger AS $$ BEGIN
            RAISE EXCEPTION 'append-only history cannot be updated or deleted';
            END; $$ LANGUAGE plpgsql"""
            )
        )
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()  # Remove only the new, still-empty metadata-created table.
            migration.upgrade()
        assert session.scalar(select(func.count()).select_from(Evidence)) == 1
        assert session.scalar(select(func.count()).select_from(Project)) == 1
        # Seed an explicitly reviewed prior acceptance; exercise actual ingestion below.
        interpretation.status = "accepted"
        interpretation.assessment = {
            "decision": "accepted",
            "project_identity_key": project.identity_key,
            "semantic_hash": observation.content_hash,
            "evidence_hash": evidence.content_hash,
        }
        session.flush()
        attach_interconnection_facts(
            session,
            project.id,
            evidence.id,
            request_id="request-1",
            facts=[{"field": "study_state", "value": "completed", "quote": "Study completed"}],
            today=date(2026, 10, 9),
        )
        project_id = project.id
        version = session.scalar(select(InterconnectionFactVersion))
        version_id, payload = version.id, deepcopy(version.payload)
        for statement in (
            "UPDATE interconnection_fact_versions SET payload = '{}'::jsonb WHERE id = :id",
            "DELETE FROM interconnection_fact_versions WHERE id = :id",
        ):
            with pytest.raises(DBAPIError, match="append-only history"):
                with session.begin_nested():
                    session.execute(text(statement), {"id": version_id})
    correction = record("The proposed development was canceled and will not proceed.")
    run(factory, job_id, correction)
    run(factory, job_id, correction)
    with factory() as session:
        assert session.scalar(select(Interpretation.status)) == "rejected"
        assert session.get(InterconnectionFactVersion, version_id).payload == payload
        assert session.scalar(select(func.count()).select_from(InterconnectionFactVersion)) == 1
        assert session.scalar(select(func.count()).select_from(Evidence)) == 2
        assert (
            current_interconnection_state(session, project_id, today=date(2026, 10, 9))["requests"]
            == []
        )


@pytest.mark.parametrize(
    "provider_response",
    ["authentication_failed", "provider_unavailable", "malformed_response"],
)
def test_source_ingestion_queues_jev_without_calling_provider(db, monkeypatch, provider_response):
    from pydantic import SecretStr

    from gridlens.intelligence import signal_adjudication as jev
    from gridlens.persistence.models import SignalDecision

    # Force the optional adjudication path independently of the deterministic display policy.
    monkeypatch.setattr(jev, "deterministic_override", lambda *a: None)
    monkeypatch.setattr(jev.time, "sleep", lambda _: None)
    monkeypatch.setattr(settings, "typesafe_api_key", SecretStr("synthetic-key"))
    provider_calls = []

    def post(url, **kwargs):
        provider_calls.append((url, kwargs))
        return httpx.Response(
            {"authentication_failed": 401, "provider_unavailable": 503}.get(provider_response, 200),
            json={"model": "invalid"},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(jev.httpx, "post", post)
    _, factory, _ = db
    from datetime import date

    definition = next(row for row in load_registry() if row["id"] == "austin-building-permits")
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
                cadence_hours=24,
                health={},
            )
        )
        session.flush()
        job = Job(
            source_id=definition["id"],
            status="running",
            lease_owner="test",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        job_id = job.id
    row = {
        "permit_number": "2026-SYN-1",
        "issue_date": "2020-05-10",
        "statusdate": date.today().isoformat(),
        "description": "Replace natural gas generator and ATS at existing telecom shelter.",
        "permit_class_mapped": "Commercial",
        "work_class": "New",
        "permit_type_desc": "Building Permit",
        "status_current": "Active",
        "original_address1": "100 Factory Way",
        "original_city": "AUSTIN",
        "original_state": "TX",
        "project_id": "SYN-1",
        "link": {"url": "https://abc.austintexas.gov/permit/1"},
    }

    def run():
        def handler(request):
            params = dict(request.url.params)
            assert "statusdate >=" in params["$where"]
            return httpx.Response(200, json=[{"row_count": "1"}] if "$select" in params else [row])

        with factory() as session:
            return process_job(
                session,
                job_id,
                "test",
                1,
                definition,
                httpx.Client(transport=httpx.MockTransport(handler)),
            )

    assert run()["signals"] == 1
    with factory() as session:
        decision = session.scalar(select(SignalDecision))
        assert decision is not None and decision.decision == "REVIEW"
        assert decision.dimensions["status"] == "queued_for_shared_ledger"
        assert decision.source == "jev_pending"
        queued = session.scalar(select(Job).where(Job.kind == "signal_adjudication"))
        assert queued is not None and queued.status == "queued"
        checkpoint = json.loads(queued.checkpoint)
        assert checkpoint["content_hash"] == decision.content_hash
        assert checkpoint["evidence_id"]
        assert checkpoint["policy_version"]
        assert (
            session.scalar(
                select(func.count()).select_from(Job).where(Job.kind == "signal_adjudication")
            )
            == 1
        )
        assert session.scalar(select(func.count()).select_from(Evidence)) == 1
        assert session.scalar(select(Interpretation.status)) == "accepted"
        assert session.scalar(select(PowerNeed.tier)) == "Signal"
        assert session.get(Job, job_id).checkpoint is not None
    assert provider_calls == []
    assert run()["unchanged"] == 1


def test_out_of_region_permit_keeps_evidence_but_never_creates_active_need(db):
    import gridlens.ingestion.service as service

    _, factory, _ = db
    definition = next(row for row in load_registry() if row["id"] == "austin-building-permits")
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
                health={},
            )
        )
        session.flush()
        job = Job(
            source_id=definition["id"],
            status="running",
            lease_owner="test",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        job_id = job.id

    permit = {
        "source_type": "austin-building-permits",
        "row_id": "2026-GA-SCOPE-1",
        "status": "Issued",
        "description": (
            "Texas headquarters announces a concert stage with food vendors November 2-4, 2026."
        ),
        "address": "1 Festival Way",
        "city": "Atlanta",
        "state": "GA",
    }
    record_value = {
        "document_number": permit["row_id"],
        "title": "Texas headquarters event application",
        "abstract": permit["description"],
        "publication_date": "2026-09-27",
        "html_url": "https://abc.austintexas.gov/permit/ga-scope-1",
        "extraction_location": "permit fields",
        "event_date": "2026-09-27",
        "event_date_label": "Permit issue date",
        "permit": permit,
    }
    with factory() as session:
        counts = service.process_records(
            session,
            job_id,
            "test",
            1,
            definition,
            [record_value],
            allow_model=False,
        )
    assert counts["regional_excluded"] == 1
    assert counts["permit_accepted"] == 0
    with factory() as session:
        observation = session.scalar(select(Observation))
        evidence = session.scalar(select(Evidence))
        interpretation = session.scalar(select(Interpretation))
        project = session.scalar(select(Project))
        assert observation is not None and evidence is not None and interpretation is not None
        assert project is not None and project.region_status == "EXCLUDED"
        assert interpretation.assessment["regional_scope"]["reason"] == (
            "project_site_outside_region"
        )
        assert interpretation.assessment["regional_scope"]["state"] == "GA"
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 0


def test_site_reclassification_holds_active_need_and_preserves_evidence_history(db):
    import gridlens.ingestion.service as service

    _, factory, _ = db
    definition = next(row for row in load_registry() if row["id"] == "austin-building-permits")
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
                health={},
            )
        )
        session.flush()
        job = Job(
            source_id=definition["id"],
            status="running",
            lease_owner="test",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        job_id = job.id

    def permit_record(city: str, state: str, description: str) -> dict:
        permit = {
            "source_type": "austin-building-permits",
            "row_id": "2026-SITE-RECLASS-1",
            "status": "Issued",
            "description": description,
            "address": "1 Festival Way",
            "city": city,
            "state": state,
        }
        return {
            "document_number": permit["row_id"],
            "title": "Festival application",
            "abstract": description,
            "publication_date": "2026-09-27",
            "html_url": "https://abc.austintexas.gov/permit/site-reclass-1",
            "extraction_location": "permit fields",
            "event_date": "2026-09-27",
            "event_date_label": "Permit issue date",
            "permit": permit,
        }

    initial = permit_record(
        "Austin",
        "TX",
        "Texas headquarters announces a concert stage with food vendors November 2-4, 2026.",
    )
    with factory() as session:
        first = service.process_records(
            session, job_id, "test", 1, definition, [initial], allow_model=False
        )
    assert first["permit_accepted"] == 1
    with factory.begin() as session:
        project = session.scalar(select(Project))
        assert project is not None and project.region_status == "ELIGIBLE"
        project.identity_facts = {**project.identity_facts, "site": "Dallas, TX"}
        need = session.scalar(select(PowerNeed))
        assert need is not None and need.active

    revised = permit_record(
        "Santa Clara",
        "CA",
        "Texas headquarters revises its event filing for a concert stage with food vendors "
        "November 2-4, 2026.",
    )
    with factory() as session:
        second = service.process_records(
            session, job_id, "test", 1, definition, [revised], allow_model=False
        )
    assert second["regional_held"] == 1
    with factory() as session:
        interpretation = session.scalar(select(Interpretation))
        need = session.scalar(select(PowerNeed))
        assert interpretation is not None and need is not None
        assert interpretation.assessment["regional_scope"]["status"] == "HOLD"
        assert interpretation.assessment["regional_scope"]["reason"] == (
            "conflicting_project_site_states"
        )
        assert need.active is False
        assert session.scalar(select(func.count()).select_from(Project)) == 1
        assert session.scalar(select(func.count()).select_from(Evidence)) == 2


def test_tdlr_parser_refresh_recovers_owner_fields_and_preserves_prior_evidence(db):
    import copy
    from pathlib import Path

    from gridlens.ingestion.adapters.tdlr_tabs import (
        parse_project as parse_tdlr_project,
    )
    from gridlens.ingestion.adapters.tdlr_tabs import (
        record as tdlr_record,
    )

    _, factory, _ = db
    definition = next(row for row in load_registry() if row["id"] == "texas-tdlr-tabs-data-centers")
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
                health={},
            )
        )
        session.flush()
        job = Job(
            source_id=definition["id"],
            status="running",
            lease_owner="test",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        job_id = job.id

    page = (
        Path(__file__)
        .parents[1]
        .joinpath("fixtures", "tdlr-tabs-project-TABS2026009183-excerpt.html")
        .read_bytes()
    )
    page = page.replace(
        b"<dd>Dan Yamagishi</dd>",
        b"<dd>Dan Yamagishi</dd><dt>Owner Phone:</dt><dd>(214) 555-0100</dd>",
    )
    current_project = parse_tdlr_project(page, "TABS2026009183")
    current = tdlr_record(current_project)

    # Reproduce the old parser projection: Contact Name was in its hash, but
    # record() omitted it from retained text and permit metadata.
    old_project = copy.deepcopy(current_project)
    for key in ("owner_phone", "owner_email", "owner_contact_phone", "owner_contact_email"):
        old_project.pop(key, None)
    old = tdlr_record(old_project)
    old_field_prefixes = (
        "Owner contact:",
        "Owner phone:",
        "Owner email:",
        "Owner contact phone:",
        "Owner contact email:",
    )
    old["abstract"] = "\n".join(
        line for line in old["abstract"].splitlines() if not line.startswith(old_field_prefixes)
    )
    assert not any(line.startswith(old_field_prefixes) for line in old["abstract"].splitlines())
    for key in (
        "owner_contact",
        "owner_phone",
        "owner_email",
        "owner_contact_phone",
        "owner_contact_email",
    ):
        old["permit"]["source_fields"].pop(key, None)

    import gridlens.ingestion.service as service

    with factory() as session:
        initial = service.process_records(
            session, job_id, "test", 1, definition, [old], allow_model=False
        )
    assert initial["new"] == 1
    with factory() as session:
        prior = session.scalar(select(Evidence))
        assert prior is not None
        historical_abstract = prior.abstract
        historical_hash = prior.content_hash

    with factory() as session:
        refreshed = service.process_records(
            session, job_id, "test", 1, definition, [current], allow_model=False
        )
    assert refreshed["changed"] == 1
    with factory() as session:
        replay = service.process_records(
            session, job_id, "test", 1, definition, [current], allow_model=False
        )
    assert replay["unchanged"] == 1
    with factory() as session:
        evidence = list(session.scalars(select(Evidence)))
        observation = session.scalar(select(Observation))
        assert len(evidence) == 2
        assert observation is not None and observation.external_id == "TABS-TABS2026009183"
        historical = next(row for row in evidence if row.content_hash == historical_hash)
        latest = next(row for row in evidence if row.content_hash != historical_hash)
        assert historical.abstract == historical_abstract
        assert "Owner contact: Dan Yamagishi" in latest.abstract
        assert "Owner phone: (214) 555-0100" in latest.abstract


def test_tdlr_exact_refetch_receipt_refreshes_only_fetched_retained_contact_source(db, monkeypatch):
    from pathlib import Path

    from gridlens.ingestion.adapters.tdlr_tabs import parse_project, record
    from gridlens.intelligence.buying_chain import buying_chain_view, enrich_buying_chain
    from gridlens.persistence.models import BuyingChainEvidence

    _, factory, _ = db
    definition = next(row for row in load_registry() if row["id"] == "texas-tdlr-tabs-data-centers")
    page_a = (
        (
            Path(__file__)
            .parents[1]
            .joinpath("fixtures", "tdlr-tabs-project-TABS2026009183-excerpt.html")
            .read_bytes()
        )
        .replace(
            b"<dd>Dan Yamagishi</dd>",
            b"<dd>Dan Yamagishi</dd><dt>Owner Phone:</dt><dd>(214) 555-0100</dd>",
        )
        .replace(b"1/5/2026", b"10/20/2026")
    )
    page_b = (
        page_a.replace(b"TABS2026009183", b"TABS2026009184")
        .replace(b"Databank Red Oak - DFW13", b"Acme Red Oak - DFW14")
        .replace(b"Stainback Rd,", b"Landmark St,")
    )
    page_c = (
        page_b.replace(b"TABS2026009184", b"TABS2026009185")
        .replace(b"Acme Red Oak - DFW14", b"Other Red Oak - DFW15")
        .replace(b"Landmark St,", b"Other St,")
    )
    record_a = record(parse_project(page_a, "TABS2026009183"))
    record_b = record(parse_project(page_b, "TABS2026009184"))
    record_c = record(parse_project(page_c, "TABS2026009185"))
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
                health={},
            )
        )
        session.flush()
        job = Job(
            source_id=definition["id"],
            status="running",
            lease_owner="tdlr-fetch-receipt-test",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        job_id = job.id
    import gridlens.ingestion.service as service

    with factory() as session:
        service.process_records(
            session,
            job_id,
            "tdlr-fetch-receipt-test",
            1,
            definition,
            [record_a, record_b, record_c],
            allow_model=False,
        )
    now = datetime.now(UTC)
    stale_since = now - timedelta(days=31)
    with factory.begin() as session:
        projects = {
            item.external_id: item
            for item in session.scalars(
                select(Project).where(
                    Project.source_id == definition["id"],
                    Project.external_id.in_(
                        [
                            record_a["document_number"],
                            record_b["document_number"],
                            record_c["document_number"],
                        ]
                    ),
                )
            )
        }
        evidence = {
            item["document_number"]: session.scalar(
                select(Evidence)
                .join(Observation)
                .where(
                    Observation.source_id == definition["id"],
                    Observation.external_id == item["document_number"],
                    Evidence.content_hash == item["source_hash"],
                )
            )
            for item in (record_a, record_b, record_c)
        }
        for item in evidence.values():
            item.observed_at = stale_since
        from gridlens.intelligence.buying_chain import _retained_evidence_current_for_project

        assert _retained_evidence_current_for_project(
            session, projects[record_a["document_number"]], evidence[record_a["document_number"]]
        )
        old_evidence_metadata = {
            external_id: (
                evidence[external_id].id,
                evidence[external_id].content_hash,
                evidence[external_id].observed_at,
                evidence[external_id].abstract,
            )
            for external_id in projects
        }
        for item in (record_a, record_b):
            enrich_buying_chain(
                session,
                projects[item["document_number"]].id,
                retained_only=True,
                now=now,
            )
        b_receipt = session.scalar(
            select(BuyingChainEvidence).where(
                BuyingChainEvidence.project_id == projects[record_b["document_number"]].id,
                BuyingChainEvidence.retained_evidence_id
                == evidence[record_b["document_number"]].id,
            )
        )
        assert b_receipt is not None and b_receipt.last_seen_at == stale_since
        b_view = buying_chain_view(session, projects[record_b["document_number"]].id, now=now)
        b_owner = next(item for item in b_view["candidates"] if item["person_name"] is None)
        b_phone = next(item for item in b_owner["evidence"] if item["supports"] == "public_contact")
        assert b_phone["contact_stale"] is True
        assert (
            session.scalar(
                select(BuyingChainEvidence).where(
                    BuyingChainEvidence.project_id == projects[record_c["document_number"]].id
                )
            )
            is None
        )
        a_view = buying_chain_view(session, projects[record_a["document_number"]].id, now=now)
        a_owner = next(item for item in a_view["candidates"] if item["person_name"] is None)
        a_phone = next(item for item in a_owner["evidence"] if item["supports"] == "public_contact")
        assert a_phone["contact_stale"] is True

    # The exact adapter retrieval returns a stale existing source and a source
    # with no BuyingChainEvidence row. Both receipts are scoped to returned pages.
    source_calls = []

    def tdlr_handler(request):
        source_calls.append(str(request.url))
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "recordsFiltered": 2,
                    "data": [
                        {
                            "ProjectNumber": "TABS2026009183",
                            "ProjectName": "Databank Red Oak - DFW13",
                        },
                        {
                            "ProjectNumber": "TABS2026009185",
                            "ProjectName": "Other Red Oak - DFW15",
                        },
                    ],
                },
            )
        if str(request.url) == record_a["html_url"]:
            return httpx.Response(200, content=page_a)
        assert str(request.url) == record_c["html_url"]
        return httpx.Response(200, content=page_c)

    with httpx.Client(transport=httpx.MockTransport(tdlr_handler)) as client:
        with factory() as session:
            counts = service.process_job(
                session,
                job_id,
                "tdlr-fetch-receipt-test",
                1,
                definition,
                client,
            )
            session.commit()
    assert source_calls.count("https://www.tdlr.texas.gov/TABS/Search/SearchProjects") == 2
    assert set(source_calls[-2:]) == {record_a["html_url"], record_c["html_url"]}
    assert counts["retrieved_records"] == 2
    assert counts["retained_source_refresh_receipts"] == 2
    with factory.begin() as session:
        project_a = projects[record_a["document_number"]]
        a_receipt = session.scalar(
            select(BuyingChainEvidence).where(
                BuyingChainEvidence.project_id == project_a.id,
                BuyingChainEvidence.retained_evidence_id
                == evidence[record_a["document_number"]].id,
            )
        )
        b_receipt = session.scalar(
            select(BuyingChainEvidence).where(
                BuyingChainEvidence.project_id == projects[record_b["document_number"]].id,
                BuyingChainEvidence.retained_evidence_id
                == evidence[record_b["document_number"]].id,
            )
        )
        c_receipt = session.scalar(
            select(BuyingChainEvidence).where(
                BuyingChainEvidence.project_id == projects[record_c["document_number"]].id,
                BuyingChainEvidence.retained_evidence_id
                == evidence[record_c["document_number"]].id,
            )
        )
        assert a_receipt is not None, list(
            session.scalars(
                select(BuyingChainEvidence).where(BuyingChainEvidence.project_id == project_a.id)
            )
        )
        assert a_receipt.last_seen_at > stale_since
        assert b_receipt is not None and b_receipt.last_seen_at == stale_since
        assert c_receipt is not None and c_receipt.last_seen_at > stale_since
        for _external_id, original in old_evidence_metadata.items():
            current_evidence = session.get(Evidence, original[0])
            assert current_evidence is not None
            assert (
                current_evidence.content_hash,
                current_evidence.observed_at,
                current_evidence.abstract,
            ) == original[1:]
        enrich_buying_chain(session, project_a.id, retained_only=True, now=now)
        enrich_buying_chain(
            session,
            projects[record_b["document_number"]].id,
            retained_only=True,
            now=now,
        )
        enrich_buying_chain(
            session,
            projects[record_c["document_number"]].id,
            retained_only=True,
            now=now,
        )
        refreshed_a = session.scalar(
            select(BuyingChainEvidence).where(
                BuyingChainEvidence.project_id == project_a.id,
                BuyingChainEvidence.retained_evidence_id
                == evidence[record_a["document_number"]].id,
            )
        )
        refreshed_b = session.scalar(
            select(BuyingChainEvidence).where(
                BuyingChainEvidence.project_id == projects[record_b["document_number"]].id,
                BuyingChainEvidence.retained_evidence_id
                == evidence[record_b["document_number"]].id,
            )
        )
        refreshed_c = session.scalar(
            select(BuyingChainEvidence).where(
                BuyingChainEvidence.project_id == projects[record_c["document_number"]].id,
                BuyingChainEvidence.retained_evidence_id
                == evidence[record_c["document_number"]].id,
            )
        )
        assert refreshed_a is not None and refreshed_a.last_seen_at == a_receipt.last_seen_at
        assert refreshed_b is not None and refreshed_b.last_seen_at == stale_since
        assert refreshed_c is not None and refreshed_c.last_seen_at == c_receipt.last_seen_at
        a_view = buying_chain_view(session, project_a.id, now=now)
        a_owner = next(item for item in a_view["candidates"] if item["person_name"] is None)
        a_phone = next(item for item in a_owner["evidence"] if item["supports"] == "public_contact")
        assert a_phone["contact_stale"] is False
        c_view = buying_chain_view(session, projects[record_c["document_number"]].id, now=now)
        c_owner = next(item for item in c_view["candidates"] if item["person_name"] is None)
        c_phone = next(item for item in c_owner["evidence"] if item["supports"] == "public_contact")
        assert c_phone["contact_stale"] is False

    # A lease stolen after records are processed must block the exact-fetch
    # receipt write; it cannot turn the refreshed content into trusted freshness.
    with factory.begin() as session:
        stale_a = session.scalar(
            select(BuyingChainEvidence).where(
                BuyingChainEvidence.project_id == project_a.id,
                BuyingChainEvidence.retained_evidence_id
                == evidence[record_a["document_number"]].id,
            )
        )
        assert stale_a is not None
        stale_a.last_seen_at = stale_since
    original_process_records = service.process_records

    def steal_after_records(*args, **kwargs):
        result = original_process_records(*args, **kwargs)
        with factory.begin() as session:
            leased = session.get(Job, job_id)
            assert leased is not None
            leased.lease_owner = "replacement-worker"
            leased.fence = 2
            leased.lease_until = datetime.now(UTC) + timedelta(minutes=5)
        return result

    monkeypatch.setattr(service, "process_records", steal_after_records)
    with httpx.Client(transport=httpx.MockTransport(tdlr_handler)) as client:
        with factory() as session:
            with pytest.raises(RuntimeError, match="Worker lease fence lost"):
                service.process_job(
                    session,
                    job_id,
                    "tdlr-fetch-receipt-test",
                    1,
                    definition,
                    client,
                )
            session.rollback()
    with factory() as session:
        stale_a = session.scalar(
            select(BuyingChainEvidence).where(
                BuyingChainEvidence.project_id == project_a.id,
                BuyingChainEvidence.retained_evidence_id
                == evidence[record_a["document_number"]].id,
            )
        )
        assert stale_a is not None and stale_a.last_seen_at == stale_since
