import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.ingestion.service import process_job
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
    ProjectRole,
    ResearchEvidence,
    ResearchJob,
    Source,
)
from gridlens.settings import settings

ARTIFACTS = Path(__file__).resolve().parents[3] / ".agent" / "artifacts" / "GL3-015A"


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
    from sqlalchemy import create_engine

    engine = create_engine(settings.test_database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(
            Source(
                id="taylor-development-newsflash",
                publisher="City of Taylor, Texas",
                endpoint="https://taylortx.gov/m/NewsFlash?cat=30",
                family="municipal-planning-news",
                geography="Taylor, Texas",
                industries=["data centers"],
                retrieval_method="taylor-newsflash",
                cadence_hours=24,
                health={},
            )
        )
        session.flush()
        job = Job(
            source_id="taylor-development-newsflash",
            status="running",
            lease_owner="test",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        job_id = job.id
    yield factory, job_id
    Base.metadata.drop_all(engine)
    engine.dispose()


def _record(arc_id: str = "3434", body_suffix: str = "", article_id: str = "2079"):
    withdrawn = arc_id == "3442"
    text = (
        "Planning and Zoning Commission public hearing for a data center site in Taylor, Texas."
        + body_suffix
    )
    return {
        "document_number": f"{article_id}:arcId={arc_id}",
        "article_id": article_id,
        "archive_revision_id": arc_id,
        "title": (
            "WITHDRAWN - Notice of Public Hearings - Project Mustang data center planning review"
            if withdrawn
            else "Notice of Public Hearings - Project Mustang data center planning review"
        ),
        "abstract": text,
        "publication_date": "2026-09-04",
        "event_date": None,
        "html_url": f"https://taylortx.gov/m/NewsFlash/Archive/Item/{article_id}?arcId={arc_id}",
        "source_hash": hashlib.sha256((arc_id + text).encode()).hexdigest(),
        "extraction_location": "official article and archive row",
        "category": "Development Notices",
        "source_geography": "Taylor, Texas",
        "disposition": "withdrawn" if withdrawn else None,
    }


def _direct_article(article_id: str = "2091", body_suffix: str = "", project: str = "Mustang"):
    text = (
        "Planning and Zoning Commission public hearing for a data center site in Taylor, Texas. "
        + body_suffix
    )
    return {
        "document_number": article_id,
        "article_id": article_id,
        "archive_revision_id": None,
        "title": f"Notice of Public Hearings - Project {project} data center planning review",
        "abstract": text,
        "publication_date": "2026-09-04",
        "event_date": None,
        "html_url": f"https://taylortx.gov/m/NewsFlash/Home/Detail/{article_id}",
        "source_hash": hashlib.sha256((article_id + project + text).encode()).hexdigest(),
        "extraction_location": "header/body; category: Development Notices",
        "category": "Development Notices",
        "source_geography": "Taylor, Texas",
        "disposition": None,
    }


def _comal_record():
    from pathlib import Path

    from gridlens.ingestion.adapters.taylor_newsflash import _article

    path = Path(__file__).resolve().parents[1] / "fixtures" / "taylor-newsflash-2032.html"
    record = _article(
        path.read_bytes(),
        "https://taylortx.gov/m/NewsFlash/Home/Detail/2032",
        "2032",
        None,
    )
    record["source_geography"] = "Taylor, Texas"
    return record


def _withdrawn_archive_record():
    from gridlens.ingestion.adapters.taylor_newsflash import _article

    raw = (ARTIFACTS / "taylortx.gov-m_NewsFlash_Archive_Item_2079.html").read_bytes()
    record = _article(
        raw,
        "https://taylortx.gov/m/NewsFlash/Archive/Item/2079?arcId=3442",
        "2079",
        "3442",
    )
    record["source_geography"] = "Taylor, Texas"
    return record


def test_real_comal_article_creates_signal_and_replay_is_idempotent(db, monkeypatch):
    factory, job_id = db
    import gridlens.ingestion.service as service

    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [_comal_record()])
    source = {"id": "taylor-development-newsflash", "retrieval_method": "taylor-newsflash"}
    with factory() as session:
        first = process_job(session, job_id, "test", 1, source)
        research_job = session.scalar(select(ResearchJob))
        assert research_job is not None and research_job.status == "queued"
        research_job_id = research_job.job_id
    import gridlens.intelligence.research as research
    import gridlens.jobs.worker as worker

    monkeypatch.setattr(
        research,
        "_fetch",
        lambda _: b"""<main><h1>KDC Project Comal</h1>
        <p>KDC Real Estate Development and Investments proposes a data center at
        1051 County Road 401.</p>
        <p>Developer KDC seeks an Employment Center Zoning.</p></main>""",
    )
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(worker, "WORKER_ID", "automatic-research-test")
    assert worker.run_one({}) is True
    with factory() as session:
        replay = process_job(session, job_id, "test", 1, source)
        observation = session.scalar(select(Observation))
        need = session.scalar(select(PowerNeed))
        assert session.scalar(select(func.count()).select_from(Evidence)) == 1
        assert observation is not None and observation.external_id == "2032"
        assert need is not None and need.tier == "Signal"
        assert need.required_mw is None and need.supply == "Unknown"
        research_job = session.get(ResearchJob, research_job_id)
        assert research_job is not None and research_job.status == "completed"
        assert session.scalar(select(func.count()).select_from(ResearchJob)) == 1
        assert session.scalar(select(func.count()).select_from(ResearchEvidence)) == 1
        assert session.scalar(select(func.count()).select_from(ProjectRole)) == 1
    assert first["signals"] == 1
    assert replay["unchanged"] == 1


def test_replay_and_new_revision_preserve_evidence_without_false_power_claims(db, monkeypatch):
    factory, job_id = db
    import gridlens.ingestion.service as service

    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [_record()])
    source = {"id": "taylor-development-newsflash", "retrieval_method": "taylor-newsflash"}
    with factory() as session:
        first = process_job(session, job_id, "test", 1, source)
    assert first["signals"] == 1
    with factory() as session:
        replay = process_job(session, job_id, "test", 1, source)
    assert replay["unchanged"] == 1

    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [_record("3435", " revised")])
    with factory() as session:
        next_revision = process_job(session, job_id, "test", 1, source)
    assert next_revision["new"] == 1
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [_record("3435", " revised")])
    with factory() as session:
        revision_replay = process_job(session, job_id, "test", 1, source)
    assert revision_replay["unchanged"] == 1
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [_withdrawn_archive_record()])
    with factory() as session:
        revision = process_job(session, job_id, "test", 1, source)
    assert revision["new"] == 1
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Observation)) == 3
        assert session.scalar(select(func.count()).select_from(Evidence)) == 3
        assert session.scalar(select(func.count()).select_from(Project)) == 1
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 1
        need = session.scalar(select(PowerNeed))
        assert need is not None and need.tier == "Signal"
        assert need.required_mw is None and need.supply == "Unknown"
        assert session.scalar(select(func.count()).select_from(ResearchJob)) == 0
        withdrawn = session.scalar(
            select(Observation).where(Observation.external_id == "2079:arcId=3442")
        )
        assert withdrawn is not None
        assert "WITHDRAWN" in withdrawn.title
        assert (
            session.scalar(
                select(func.count())
                .select_from(Evidence)
                .where(Evidence.observation_id == withdrawn.id)
            )
            == 1
        )


def test_distinct_article_ids_do_not_merge_by_project_name_and_city(db, monkeypatch):
    factory, job_id = db
    import gridlens.ingestion.service as service

    source = {"id": "taylor-development-newsflash", "retrieval_method": "taylor-newsflash"}
    monkeypatch.setattr(
        service,
        "retrieve_source",
        lambda *_args: [_record("3434", article_id="2079"), _record("3434", article_id="2080")],
    )
    with factory() as session:
        result = process_job(session, job_id, "test", 1, source)
        assert result["signals"] == 2
        assert session.scalar(select(func.count()).select_from(Project)) == 2
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 2
        assert session.scalar(select(func.count()).select_from(ResearchJob)) == 0


def test_one_article_with_conflicting_project_identity_stays_unknown(db, monkeypatch):
    factory, job_id = db
    import gridlens.ingestion.service as service

    source = {"id": "taylor-development-newsflash", "retrieval_method": "taylor-newsflash"}
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [_record("3434")])
    with factory() as session:
        process_job(session, job_id, "test", 1, source)
    conflicting = _record("3435", " Project Comal is a separate data center site in Taylor, Texas.")
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [conflicting])
    with factory() as session:
        process_job(session, job_id, "test", 1, source)
        assert session.scalar(select(func.count()).select_from(Project)) == 1
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 1
        interpretation = session.scalar(
            select(Interpretation)
            .join(Observation)
            .where(Observation.external_id == "2079:arcId=3435")
        )
        assert interpretation is not None
        assert interpretation.status == "rejected"
        assert interpretation.assessment["decision"] == "unknown"
        assert session.scalar(select(func.count()).select_from(ResearchJob)) == 0


def test_changed_same_external_id_project_conflict_preserves_prior_evidence_and_signal(
    db, monkeypatch
):
    factory, job_id = db
    import gridlens.ingestion.service as service

    source = {"id": "taylor-development-newsflash", "retrieval_method": "taylor-newsflash"}
    original = _direct_article()
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [original])
    with factory() as session:
        first = process_job(session, job_id, "test", 1, source)
        original_lifecycle_count = session.scalar(select(func.count()).select_from(LifecycleEvent))
        original_project = session.scalar(select(Project))
        original_need = session.scalar(select(PowerNeed))
        assert first["signals"] == 1
        assert original_project is not None and "Mustang" in original_project.name
        assert original_need is not None and original_need.tier == "Signal"

    conflicting = _direct_article(project="Other", body_suffix="Project Other was substituted.")
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [conflicting])
    with factory() as session:
        result = process_job(session, job_id, "test", 1, source)
        observation = session.scalar(select(Observation).where(Observation.external_id == "2091"))
        project = session.scalar(select(Project))
        need = session.scalar(select(PowerNeed))
        interpretation = session.scalar(select(Interpretation))
        evidence = session.scalars(select(Evidence).order_by(Evidence.observed_at)).all()
        assert result["changed"] == 1
        assert result["signals"] == 0
        assert observation is not None and "Other" in observation.title
        assert project is not None and project.name == original_project.name
        assert need is not None and need.id == original_need.id and need.tier == "Signal"
        assert interpretation is not None and interpretation.assessment["decision"] == "unknown"
        assert interpretation.assessment["previous_assessments"][0]["decision"] == "accepted"
        assert len(evidence) == 2
        assert any("Mustang" in item.title for item in evidence)
        assert any("Other" in item.title for item in evidence)
        assert session.scalar(select(func.count()).select_from(Project)) == 1
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 1
        assert (
            session.scalar(select(func.count()).select_from(LifecycleEvent))
            == original_lifecycle_count
        )


def test_changed_same_external_id_nonconflicting_update_replays_on_same_project(
    db, monkeypatch
):
    factory, job_id = db
    import gridlens.ingestion.service as service

    source = {"id": "taylor-development-newsflash", "retrieval_method": "taylor-newsflash"}
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [_direct_article()])
    with factory() as session:
        process_job(session, job_id, "test", 1, source)
    updated = _direct_article(body_suffix="Additional hearing context was published.")
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [updated])
    with factory() as session:
        changed = process_job(session, job_id, "test", 1, source)
        project_id = session.scalar(select(Project.id))
        need_id = session.scalar(select(PowerNeed.id))
        lifecycle_count = session.scalar(select(func.count()).select_from(LifecycleEvent))
    assert changed["changed"] == 1
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [updated])
    with factory() as session:
        replay = process_job(session, job_id, "test", 1, source)
        assert replay["unchanged"] == 1
        assert session.scalar(select(func.count()).select_from(Evidence)) == 2
        assert session.scalar(select(func.count()).select_from(Project)) == 1
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 1
        assert session.scalar(select(Project.id)) == project_id
        assert session.scalar(select(PowerNeed.id)) == need_id
        assert session.scalar(select(func.count()).select_from(LifecycleEvent)) == lifecycle_count
        interpretation = session.scalar(select(Interpretation))
        assert interpretation is not None and interpretation.assessment["decision"] == "accepted"


def test_withdrawn_revision_evidence_is_visible_from_prior_signal(db, monkeypatch):
    factory, job_id = db
    import gridlens.ingestion.service as service

    source = {"id": "taylor-development-newsflash", "retrieval_method": "taylor-newsflash"}
    monkeypatch.setattr(
        service,
        "retrieve_source",
        lambda *_args: [{**_record(), "publication_date": "2026-08-07"}],
    )
    with factory() as session:
        process_job(session, job_id, "test", 1, source)
        lifecycle_count = session.scalar(select(func.count()).select_from(LifecycleEvent))
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [_withdrawn_archive_record()])
    with factory() as session:
        process_job(session, job_id, "test", 1, source)
        withdrawn = session.scalar(
            select(Observation).where(Observation.external_id == "2079:arcId=3442")
        )
        need = session.scalar(select(PowerNeed))
        assert withdrawn is not None and need is not None
        assert need.active is True
        assert session.scalar(select(func.count()).select_from(LifecycleEvent)) == lifecycle_count
        assert (
            session.scalar(
                select(NeedObservation.id).where(
                    NeedObservation.observation_id == withdrawn.id,
                    NeedObservation.need_id == need.id,
                )
            )
            is not None
        )
        assert session.scalar(
            select(func.count()).select_from(ChangeEvent).where(ChangeEvent.kind == "withdrawn")
        ) == 1
    import importlib

    api_module = importlib.import_module("gridlens.api.app")
    monkeypatch.setattr(api_module, "SessionLocal", factory)
    cards = api_module.opportunities(tier="Signal")
    assert len(cards) == 1
    assert cards[0]["signal_evidence_state"] == "planning_application_withdrawn"
    assert cards[0]["lifecycle_state"] == "planning_application_withdrawn"
    assert cards[0]["expected_next_milestone"] is None
    assert cards[0]["expected_power_event"] is None
    assert cards[0]["lifecycle_timeline"][-1]["event_type"] == "planning_application_withdrawn"
    assert "historical" in cards[0]["rationale"].lower()
    assert len(cards[0]["evidence"]) == 2
    with factory() as session:
        before = tuple(
            session.scalar(select(func.count()).select_from(model))
            for model in (Observation, Evidence, Project, LifecycleEvent, ChangeEvent)
        )
        before_assessments = [
            row.assessment
            for row in session.scalars(select(Interpretation).order_by(Interpretation.id))
        ]
        process_job(session, job_id, "test", 1, source)
        after = tuple(
            session.scalar(select(func.count()).select_from(model))
            for model in (Observation, Evidence, Project, LifecycleEvent, ChangeEvent)
        )
        assert before == after
        assert before_assessments == [
            row.assessment
            for row in session.scalars(select(Interpretation).order_by(Interpretation.id))
        ]


def test_conflicting_withdrawn_revision_does_not_withdraw_prior_project(db, monkeypatch):
    factory, job_id = db
    import gridlens.ingestion.service as service

    source = {"id": "taylor-development-newsflash", "retrieval_method": "taylor-newsflash"}
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [_record()])
    with factory() as session:
        process_job(session, job_id, "test", 1, source)

    conflicting = _record("3442", " Project Other is at 9900 FM 112.")
    conflicting["title"] = conflicting["title"].replace("Mustang", "Other")
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [conflicting])
    with factory() as session:
        process_job(session, job_id, "test", 1, source)
        withdrawn = session.scalar(
            select(Observation).where(Observation.external_id == "2079:arcId=3442")
        )
        need = session.scalar(select(PowerNeed))
        assert withdrawn is not None and need is not None
        assert session.scalar(select(func.count()).select_from(Evidence)) == 2
        assert session.scalar(select(func.count()).select_from(Project)) == 1
        assert session.scalar(select(func.count()).select_from(LifecycleEvent)) == 1
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == 1
        assert (
            session.scalar(
                select(NeedObservation.id).where(
                    NeedObservation.observation_id == withdrawn.id,
                    NeedObservation.need_id == need.id,
                )
            )
            is None
        )
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == withdrawn.id)
        )
        assert interpretation is not None
        assert "conflicting project or site facts" in interpretation.assessment["reason"]

    import importlib

    api_module = importlib.import_module("gridlens.api.app")
    monkeypatch.setattr(api_module, "SessionLocal", factory)
    cards = api_module.opportunities(tier="Signal")
    assert len(cards) == 1
    assert cards[0]["signal_evidence_state"] != "planning_application_withdrawn"
    assert len(cards[0]["evidence"]) == 1

    with factory() as session:
        before = tuple(
            session.scalar(select(func.count()).select_from(model))
            for model in (Observation, Evidence, Project, LifecycleEvent, ChangeEvent)
        )
        process_job(session, job_id, "test", 1, source)
        assert before == tuple(
            session.scalar(select(func.count()).select_from(model))
            for model in (Observation, Evidence, Project, LifecycleEvent, ChangeEvent)
        )


def test_conflicting_withdrawal_at_same_external_id_keeps_status_unknown(db, monkeypatch):
    factory, job_id = db
    import gridlens.ingestion.service as service

    source = {"id": "taylor-development-newsflash", "retrieval_method": "taylor-newsflash"}
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [_direct_article()])
    with factory() as session:
        process_job(session, job_id, "test", 1, source)
        lifecycle_count = session.scalar(select(func.count()).select_from(LifecycleEvent))

    conflicting = _direct_article(project="Other", body_suffix="Project Other is at 9900 FM 112.")
    conflicting["title"] = "WITHDRAWN - " + conflicting["title"]
    conflicting["disposition"] = "withdrawn"
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [conflicting])
    with factory() as session:
        process_job(session, job_id, "test", 1, source)
        observation = session.scalar(select(Observation).where(Observation.external_id == "2091"))
        need = session.scalar(select(PowerNeed))
        assert observation is not None and need is not None
        assert session.scalar(select(func.count()).select_from(Evidence)) == 2
        assert session.scalar(select(func.count()).select_from(Project)) == 1
        assert session.scalar(select(func.count()).select_from(LifecycleEvent)) == lifecycle_count
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == 1
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == observation.id)
        )
        assert interpretation is not None
        assert interpretation.assessment["decision"] == "unknown"
        assert "conflicting project or site facts" in interpretation.assessment["reason"]

    import importlib

    api_module = importlib.import_module("gridlens.api.app")
    monkeypatch.setattr(api_module, "SessionLocal", factory)
    cards = api_module.opportunities(tier="Signal")
    assert len(cards) == 1
    assert cards[0]["signal_evidence_state"] == "planning_status_unknown"
    assert cards[0]["lifecycle_state"] == "planning_status_unknown"
    assert cards[0]["expected_next_milestone"] is None
    assert len(cards[0]["evidence"]) == 2
    assert "UNKNOWN" in cards[0]["rationale"]

    with factory() as session:
        before = tuple(
            session.scalar(select(func.count()).select_from(model))
            for model in (Observation, Evidence, Project, LifecycleEvent, ChangeEvent)
        )
        process_job(session, job_id, "test", 1, source)
        assert before == tuple(
            session.scalar(select(func.count()).select_from(model))
            for model in (Observation, Evidence, Project, LifecycleEvent, ChangeEvent)
        )
