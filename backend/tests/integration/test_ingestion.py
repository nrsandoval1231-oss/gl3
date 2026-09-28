import hashlib
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import create_engine, func, select
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
    assert run(factory, job_id, initial)["signals"] == 1
    assert run(factory, job_id, initial)["unchanged"] == 1
    changed = record(initial["abstract"] + " Construction access roads will also be required.")
    assert run(factory, job_id, changed)["changed"] == 1
    assert run(factory, job_id, initial)["changed"] == 1
    negative = record("The proposed development was canceled and will not proceed.")
    run(factory, job_id, negative)
    run(factory, job_id, negative)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Observation)) == 1
        assert session.scalar(select(func.count()).select_from(Project)) == 1
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 1
        assert session.scalar(select(func.count()).select_from(Evidence)) == 3
        assert session.scalar(select(func.count()).select_from(NeedObservation)) == 1
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == 4
        assert session.scalar(select(Observation.published_at)) == datetime(2026, 9, 14).date()
        assert session.scalar(select(PowerNeed.active)) is False
        assert session.scalar(select(Interpretation.status)) == "rejected"


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
        assert interpretation.assessment["evaluator_version"] == "permit-project-v7"
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
        assert interpretation.assessment["evaluator_version"] == "permit-project-v7"
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
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == event_count + 1
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
        assert closed_snapshot[-2] == first_snapshot[-2] + 1
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
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 1


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
    assert run(factory, job_id, row)["signals"] == 1
    assert run(factory, job_id, row)["unchanged"] == 1
    pdf_hash[0] = "d" * 64
    assert run(factory, job_id, row)["unchanged"] == 1
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Observation)) == 1
        assert session.scalar(select(func.count()).select_from(Project)) == 1
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 1
        assert session.scalar(select(func.count()).select_from(Evidence)) == 3
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == 1
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
    assert run(factory, job_id, initial)["signals"] == 1
    replay = dict(initial)
    replay["source_hash"] = "c" * 64  # Body/footer revision outside retained excerpt.
    current[0] = replay
    assert run(factory, job_id, replay)["unchanged"] == 1
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Observation)) == 1
        assert session.scalar(select(func.count()).select_from(Project)) == 1
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 1
        assert session.scalar(select(func.count()).select_from(Evidence)) == 2
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == 1


def test_prior_candidate_hash_replays_without_a_migration_or_duplicate_evidence(db):
    _, factory, job_id = db
    row = record(
        "The proposed Mine Plan of Operations would develop the mine, with dewatering "
        "and ventilation shafts."
    )
    assert run(factory, job_id, row)["signals"] == 1
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
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == 1


def test_lifecycle_projection_is_evidence_version_bound_and_never_uses_publication_date(db):
    _, factory, _ = db
    from gridlens.intelligence.lifecycle_service import apply_lifecycle_observation

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
            content_hash="a" * 64,
        )
        session.add_all([project, observation])
        session.flush()
        evidence = Evidence(
            observation_id=observation.id,
            content_hash="b" * 64,
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
                content_hash=observation.content_hash,
                status="accepted",
                evaluator_version="test",
                assessment={
                    "evidence_hash": evidence.content_hash,
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
        corrected = Evidence(
            observation_id=observation.id,
            content_hash="c" * 64,
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
        interpretation.status = "rejected"
        interpretation.assessment = {"evidence_hash": corrected.content_hash}
        apply_lifecycle_observation(session, project, observation, corrected)
        assert session.scalar(select(func.count()).select_from(LifecycleEvent)) == 1
        assert session.get(ProjectLifecycle, project.id) is None
        assert project.asset_type == "unknown"

        # A correction may return to a retained accepted evidence version. Its event
        # must become current again, and the existing-event path restores asset type.
        interpretation.status = "accepted"
        interpretation.assessment = {"evidence_hash": evidence.content_hash}
        assert apply_lifecycle_observation(session, project, observation, evidence) is False
        projection = session.get(ProjectLifecycle, project.id)
        assert projection is not None and projection.current_state == "spud"
        assert project.asset_type == "upstream_well"


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
                endpoint="https://example.test",
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
        assert session.scalar(select(func.count()).select_from(Project)) == 1
        assert session.scalar(select(func.count()).select_from(NeedObservation)) == 2
        second_observation = session.scalar(
            select(Observation).where(Observation.source_id == "second-source")
        )
        assert second_observation is not None
        first_decision = session.scalar(
            select(ProjectMatchDecision).where(
                ProjectMatchDecision.observation_id == second_observation.id
            )
        )
        assert first_decision and first_decision.decision == "matched"
        original_evidence_id = first_decision.evidence_id

    # Changing the cited site creates a new version-bound separate decision;
    # the original positive match remains queryable.
    second["abstract"] = "500 Different Avenue, Austin, TX"
    second["html_url"] = "https://example.test/second-corrected"
    with factory() as session:
        process_job(session, second_job_id, "test", 1, second_definition, None)
    with factory() as session:
        second_observation = session.scalar(
            select(Observation).where(Observation.source_id == "second-source")
        )
        assert second_observation is not None
        decisions = session.scalars(
            select(ProjectMatchDecision)
            .where(ProjectMatchDecision.observation_id == second_observation.id)
            .order_by(ProjectMatchDecision.evidence_id)
        ).all()
        candidate_decisions = [row for row in decisions if row.candidate_project_id is not None]
        assert len(candidate_decisions) == 2
        assert {decision.decision for decision in candidate_decisions} == {"matched", "separate"}
        assert original_evidence_id in {decision.evidence_id for decision in candidate_decisions}
        assert all(decision.identity_facts for decision in decisions)


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
        assert session.scalar(select(func.count()).select_from(Project)) == 2
        second_observation = session.scalar(
            select(Observation).where(Observation.external_id == "CITY-2")
        )
        assert second_observation is not None
        decision = session.scalar(
            select(ProjectMatchDecision).where(
                ProjectMatchDecision.observation_id == second_observation.id,
                ProjectMatchDecision.candidate_project_id.is_(None),
            )
        )
        assert decision and decision.candidate_project_id is None
        assert "No single existing project candidate" in decision.reason
        assert decision.identity_facts["project_name"] == "Same Facility"


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
        decisions = session.scalars(select(ProjectMatchDecision)).all()
        assert len(decisions) == 2
        assert {decision.decision for decision in decisions} == {"separate"}
        assert all("Multiple supported" in decision.reason for decision in decisions)


def test_ingested_upstream_versions_replay_and_authenticated_api_attribution(db, monkeypatch):
    _, factory, _ = db
    from fastapi.testclient import TestClient

    import gridlens.api.app as api
    import gridlens.ingestion.service as service
    from gridlens.intelligence.lifecycle_replay import replay_accepted_lifecycle
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

    # Deliberately ingest completion before spud to verify rank-based projection.
    assert ingest(source_ids[0])["signals"] == 1
    assert ingest(source_ids[2])["signals"] == 0
    assert ingest(source_ids[1])["signals"] == 0
    with factory() as session:
        project = session.scalar(select(Project))
        need = session.scalar(select(PowerNeed))
        assert project and project.asset_type == "upstream_well"
        assert need and need.active and need.tier == "Signal"
        assert need.required_mw is None and need.supply == "Unknown"
        assert session.scalar(select(func.count()).select_from(Project)) == 1
        assert session.scalar(select(func.count()).select_from(NeedObservation)) == 3
        assert session.scalar(select(func.count()).select_from(LifecycleEvent)) == 3
        projection = session.get(ProjectLifecycle, project.id)
        assert projection and projection.current_state == "completion"
        assert projection.time_to_power_start.isoformat() == "2026-08-08"
        assert projection.estimate_basis["inputs"]["completion_date"] == "2026-07-24"
        events = session.scalars(select(LifecycleEvent)).all()
        permit_event = next(event for event in events if event.event_type == "drilling_permit")
        assert permit_event.occurred_on.isoformat() == "2026-06-10"

    # A changed reported date appends a retained event version and supersedes A.
    spud_b = row(
        source_ids[1],
        "S-1",
        "Operator begins construction after spud report at Site A",
        "2026-07-13",
        "Spud date",
    )
    rows[source_ids[1]] = [spud_b]
    assert ingest(source_ids[1])["changed"] == 1
    with factory() as session:
        spud_events = session.scalars(
            select(LifecycleEvent).where(LifecycleEvent.event_type == "spud")
        ).all()
        assert {event.occurred_on.isoformat() for event in spud_events} == {
            "2026-07-12",
            "2026-07-13",
        }
        current_hash = session.scalar(
            select(Interpretation.assessment["evidence_hash"])
            .join(Observation)
            .where(Observation.source_id == source_ids[1])
        )
        assert current_hash

    # Correct the currently winning completion anchor. The new estimate must use
    # the corrected completion event while retaining its former evidence version.
    completion_b = row(
        source_ids[2],
        "C-1",
        "Operator begins construction after well completion at Site A",
        "2026-08-02",
        "Completion date",
    )
    rows[source_ids[2]] = [completion_b]
    assert (
        ingest(source_ids[2])["unchanged"] == 1
    )  # Same semantic permit/story row; new bound evidence.
    with factory() as session:
        projection = session.get(ProjectLifecycle, session.scalar(select(Project.id)))
        assert projection and projection.current_state == "completion"
        assert projection.time_to_power_start.isoformat() == "2026-08-17"
        assert projection.estimate_basis["inputs"]["completion_date"] == "2026-08-02"
        completion_events = session.scalars(
            select(LifecycleEvent).where(LifecycleEvent.event_type == "completion")
        ).all()
        assert {event.occurred_on.isoformat() for event in completion_events} == {
            "2026-07-24",
            "2026-08-02",
        }

    # A current but unclassifiable correction withdraws the old event; restoring
    # retained A reactivates that same event instead of letting superseded B mask it.
    no_event = row(
        source_ids[1],
        "S-1",
        "Routine regional operations update at Site A",
        "2026-07-14",
        "Source event date",
        "No lifecycle milestone reported.",
    )
    rows[source_ids[1]] = [no_event]
    monkeypatch.setattr(service, "interpret", lambda _record: None)
    assert ingest(source_ids[1])["changed"] == 1
    with factory() as session:
        spud_interpretation = session.scalar(
            select(Interpretation).join(Observation).where(Observation.source_id == source_ids[1])
        )
        project = session.scalar(select(Project))
        assert spud_interpretation and spud_interpretation.status == "rejected"
        assert project and project.asset_type == "upstream_well"
        assert session.scalar(select(func.count()).select_from(LifecycleEvent)) == 5

    rows[source_ids[1]] = [spud_a]
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
    assert ingest(source_ids[1])["changed"] == 1
    with factory() as session:
        interpretation = session.scalar(
            select(Interpretation).join(Observation).where(Observation.source_id == source_ids[1])
        )
        assert interpretation and interpretation.status == "accepted"
        assert session.scalar(select(func.count()).select_from(Evidence)) == 6
        assert session.scalar(select(func.count()).select_from(LifecycleEvent)) == 5
        replay_before = (
            session.scalar(select(func.count()).select_from(Evidence)),
            session.scalar(select(func.count()).select_from(LifecycleEvent)),
            session.scalar(select(func.count()).select_from(ProjectMatchDecision)),
        )
        assert replay_accepted_lifecycle(session)["events_added"] == 0
        assert replay_accepted_lifecycle(session)["events_added"] == 0
        assert replay_before == (
            session.scalar(select(func.count()).select_from(Evidence)),
            session.scalar(select(func.count()).select_from(LifecycleEvent)),
            session.scalar(select(func.count()).select_from(ProjectMatchDecision)),
        )

    monkeypatch.setattr(api, "SessionLocal", factory)
    client = TestClient(api.app)
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    response = client.get("/api/opportunities?tier=Signal")
    assert response.status_code == 200
    [opportunity] = response.json()
    assert opportunity["tier"] == "Signal"
    assert opportunity["required_mw"] is None and opportunity["supply"] == "Unknown"
    assert opportunity["time_to_power_window"].startswith("2026-08-17 to ")
    assert opportunity["estimate_basis"]["inputs"]["completion_date"] == "2026-08-02"
    assert {item["source_id"] for item in opportunity["evidence"]} == set(source_ids)
    timeline = opportunity["lifecycle_timeline"]
    assert len(timeline) == 5
    spud_rows = [item for item in timeline if item["event_type"] == "spud"]
    assert [item["current"] for item in spud_rows] == [True, False]
    assert spud_rows[0]["published_at"] == "2026-09-20"
    assert spud_rows[0]["date"] == "2026-07-12"
    assert spud_rows[0]["event_date_label"] == "Spud date"
    completion_rows = [item for item in timeline if item["event_type"] == "completion"]
    assert [item["current"] for item in completion_rows] == [False, True]
    assert completion_rows[1]["date"] == "2026-08-02"
    assert timeline[0]["date"] != timeline[0]["published_at"]


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
    assert counts["signals"] == 2
    with factory() as session:
        projects = session.scalars(select(Project).order_by(Project.location)).all()
        needs = session.scalars(select(PowerNeed).order_by(PowerNeed.id)).all()
        assert len(projects) == len(needs) == 2
        assert {project.name for project in projects} == {"Silver Ridge Mine Project"}
        assert {project.location for project in projects} == {"Arizona", "Nevada"}
        assert {need.tier for need in needs} == {"Signal"}
        assert {need.supply for need in needs} == {"Unknown"}
        assert all(need.required_mw is None and need.start_window is None for need in needs)


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
    assert run(factory, job_id, row)["signals"] == 1
    assert run(factory, job_id, row)["unchanged"] == 1
    with factory() as session:
        need = session.scalar(select(PowerNeed))
        assert need is not None and need.active is False
        assert session.scalar(select(Interpretation.status)) == "rejected"
        assert session.scalar(select(func.count()).select_from(Evidence)) == 1
        assert session.scalar(select(func.count()).select_from(NeedObservation)) == 1
        events = session.scalars(select(ChangeEvent).order_by(ChangeEvent.id)).all()
        assert [event.kind for event in events] == ["discovered", "reclassified"]
        event_count = len(events)
    assert run(factory, job_id, row)["unchanged"] == 1
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == event_count
        assert session.scalar(select(func.count()).select_from(Evidence)) == 1
        assert session.scalar(select(PowerNeed.active)) is False


def test_same_version_reinterpretation_refreshes_supported_project_display_fields(db):
    _, factory, job_id = db

    row = record(
        "The proposed Mine Plan of Operations would develop the mine, with dewatering "
        "and ventilation shafts."
    )
    row["title"] = "Forest District; New Mexico; Roca Honda Mine Project"
    assert run(factory, job_id, row)["signals"] == 1
    with factory.begin() as session:
        project = session.scalar(select(Project))
        assert project is not None
        project.name = "stale display label"
        project.location = None
    before = None
    with factory() as session:
        before = session.scalar(select(func.count()).select_from(ChangeEvent))
    assert run(factory, job_id, row)["unchanged"] == 1
    with factory() as session:
        project = session.scalar(select(Project))
        assert project is not None
        assert project.name == "Roca Honda Mine Project"
        assert project.location == "New Mexico"
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == before


def test_source_parse_failure_preserves_prior_accepted_observation_and_signal(db):
    _, factory, job_id = db
    row = record(
        "The proposed Mine Plan of Operations would develop the mine, with dewatering "
        "and ventilation shafts."
    )
    assert run(factory, job_id, row)["signals"] == 1

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
        assert project is not None
        assert session.scalar(select(func.count()).select_from(Project)) == 1
        assert need is not None and need.active is True and need.tier == "Signal"
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 1


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
        assert project is not None
        assert need is not None and need.active is True
        evidence_hashes = set(session.scalars(select(Evidence.content_hash)))
        assert "a" * 64 not in evidence_hashes
        assert "b" * 64 in evidence_hashes
        assert len(evidence_hashes) == 3  # Old/new raw versions plus replacement PDF.
        events = session.scalars(select(ChangeEvent)).all()
        assert len(events) == 1
        assert events[0].content_hash == service._hash(replacement)
