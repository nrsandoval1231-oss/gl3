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
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Source,
)
from gridlens.settings import settings


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
    definition = load_registry()[0]
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
        process_job(session, job_id, "test", 1, load_registry()[0], client)
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
                        load_registry()[0],
                    )
                )
        return [citation]

    monkeypatch.setattr(service, "retrieve_companion", pdf_citation)
    initial["pdf_url"] = replacement["pdf_url"] = (
        "https://www.govinfo.gov/content/pkg/FR-2099-01-01/pdf/2099-01001.pdf"
    )
    with factory() as old_session, pytest.raises(RuntimeError, match="fence lost"):
        process_job(old_session, job_id, "test", 1, load_registry()[0])
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
