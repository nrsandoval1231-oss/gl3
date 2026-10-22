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
    Evidence,
    Interpretation,
    Job,
    Observation,
    PowerNeed,
    Project,
    Source,
)
from gridlens.settings import settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


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

    raw = (FIXTURES / "taylor-newsflash-2079-3442.html").read_bytes()
    record = _article(
        raw,
        "https://taylortx.gov/m/NewsFlash/Archive/Item/2079?arcId=3442",
        "2079",
        "3442",
    )
    record["source_geography"] = "Taylor, Texas"
    return record


def test_real_comal_article_is_research_context_and_replay_is_idempotent(db, monkeypatch):
    factory, job_id = db
    import gridlens.ingestion.service as service

    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [_comal_record()])
    source = {"id": "taylor-development-newsflash", "retrieval_method": "taylor-newsflash"}
    with factory() as session:
        first = process_job(session, job_id, "test", 1, source)
    with factory() as session:
        replay = process_job(session, job_id, "test", 1, source)
        observation = session.scalar(select(Observation))
        need = session.scalar(select(PowerNeed))
        assert session.scalar(select(func.count()).select_from(Evidence)) == 1
        assert observation is not None and observation.external_id == "2032"
        assert need is None
        assessment = session.scalar(select(Interpretation)).assessment
        assert assessment["decision"] == "context_only"
        assert assessment["admission_origin"] == "Official planning context"
        assert session.scalar(select(func.count()).select_from(Project)) == 0
    assert first["signals"] == 0
    assert replay["unchanged"] == 1


def test_replay_and_new_revision_preserve_evidence_without_false_power_claims(db, monkeypatch):
    factory, job_id = db
    import gridlens.ingestion.service as service

    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [_record()])
    source = {"id": "taylor-development-newsflash", "retrieval_method": "taylor-newsflash"}
    with factory() as session:
        first = process_job(session, job_id, "test", 1, source)
    assert first["signals"] == 0
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
        assert session.scalar(select(func.count()).select_from(Project)) == 0
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 0
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
        assert result["signals"] == 0
        assert session.scalar(select(func.count()).select_from(Observation)) == 2
        assert session.scalar(select(func.count()).select_from(Evidence)) == 2
        assert session.scalar(select(func.count()).select_from(Project)) == 0
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 0


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
        assert session.scalar(select(func.count()).select_from(Project)) == 0
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 0
        interpretation = session.scalar(
            select(Interpretation)
            .join(Observation)
            .where(Observation.external_id == "2079:arcId=3435")
        )
        assert interpretation is not None
        assert interpretation.status == "accepted"
        assert interpretation.assessment["decision"] == "context_only"


def test_changed_same_external_id_project_conflict_preserves_context_evidence(db, monkeypatch):
    factory, job_id = db
    import gridlens.ingestion.service as service

    source = {"id": "taylor-development-newsflash", "retrieval_method": "taylor-newsflash"}
    original = _direct_article()
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [original])
    with factory() as session:
        first = process_job(session, job_id, "test", 1, source)
        assert first["signals"] == 0
        assert session.scalar(select(Project)) is None
        assert session.scalar(select(PowerNeed)) is None

    conflicting = _direct_article(project="Other", body_suffix="Project Other was substituted.")
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [conflicting])
    with factory() as session:
        result = process_job(session, job_id, "test", 1, source)
        observation = session.scalar(select(Observation).where(Observation.external_id == "2091"))
        interpretation = session.scalar(select(Interpretation))
        evidence = session.scalars(select(Evidence).order_by(Evidence.observed_at)).all()
        assert result["changed"] == 1
        assert result["signals"] == 0
        assert observation is not None and "Other" in observation.title
        assert (
            interpretation is not None and interpretation.assessment["decision"] == "context_only"
        )
        assert interpretation.assessment["previous_decisions"][0]["decision"] == "context_only"
        assert len(evidence) == 2
        assert any("Mustang" in item.title for item in evidence)
        assert any("Other" in item.title for item in evidence)
        assert session.scalar(select(func.count()).select_from(Project)) == 0
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 0
        assert session.scalar(select(func.count()).select_from(Project)) == 0


def test_changed_same_external_id_nonconflicting_update_replays_as_context(db, monkeypatch):
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
        assert session.scalar(select(func.count()).select_from(Project)) == 0
    assert changed["changed"] == 1
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [updated])
    with factory() as session:
        replay = process_job(session, job_id, "test", 1, source)
        assert replay["unchanged"] == 1
        assert session.scalar(select(func.count()).select_from(Evidence)) == 2
        assert session.scalar(select(func.count()).select_from(Project)) == 0
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 0
        assert session.scalar(select(func.count()).select_from(Project)) == 0
        interpretation = session.scalar(select(Interpretation))
        assert (
            interpretation is not None and interpretation.assessment["decision"] == "context_only"
        )


def _assert_planning_context_has_no_opportunity(factory, monkeypatch):
    import importlib

    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Project)) == 0
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 0
        assessments = session.scalars(select(Interpretation)).all()
        assert assessments
        assert all(
            row.assessment.get("decision") in {"context_only", "unknown"}
            or row.assessment.get("admission_status") == "context_only"
            for row in assessments
        )
    api_module = importlib.import_module("gridlens.api.app")
    monkeypatch.setattr(api_module, "SessionLocal", factory)
    assert api_module.opportunities() == []


def test_withdrawn_revision_evidence_is_visible_from_prior_signal(db, monkeypatch):
    factory, job_id = db
    import gridlens.ingestion.service as service

    source = {"id": "taylor-development-newsflash", "retrieval_method": "taylor-newsflash"}
    monkeypatch.setattr(
        service, "retrieve_source", lambda *_args: [{**_record(), "publication_date": "2026-08-07"}]
    )
    with factory() as session:
        first = process_job(session, job_id, "test", 1, source)
    assert first["signals"] == 0
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [_withdrawn_archive_record()])
    with factory() as session:
        withdrawn_result = process_job(session, job_id, "test", 1, source)
        withdrawn = session.scalar(
            select(Observation).where(Observation.external_id == "2079:arcId=3442")
        )
        assert withdrawn_result["signals"] == 0
        assert withdrawn is not None and "WITHDRAWN" in withdrawn.title
        assert session.scalar(select(func.count()).select_from(Evidence)) == 2
        assert session.scalar(select(func.count()).select_from(Project)) == 0
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 0
        assert session.scalar(select(func.count()).select_from(Interpretation)) == 2
    _assert_planning_context_has_no_opportunity(factory, monkeypatch)


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
        assert withdrawn is not None
        assert session.scalar(select(func.count()).select_from(Evidence)) == 2
        assert session.scalar(select(func.count()).select_from(Project)) == 0
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 0
        assert (
            session.scalar(
                select(Interpretation).where(Interpretation.observation_id == withdrawn.id)
            ).assessment["decision"]
            == "unknown"
        )
    _assert_planning_context_has_no_opportunity(factory, monkeypatch)


def test_current_page_notice_links_later_archive_withdrawal_after_window_rolls(db, monkeypatch):
    factory, job_id = db
    import gridlens.ingestion.service as service

    source = {"id": "taylor-development-newsflash", "retrieval_method": "taylor-newsflash"}
    monkeypatch.setattr(
        service,
        "retrieve_source",
        lambda *_args: [{**_direct_article("2079"), "publication_date": "2026-08-07"}],
    )
    with factory() as session:
        process_job(session, job_id, "test", 1, source)
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [_withdrawn_archive_record()])
    with factory() as session:
        process_job(session, job_id, "test", 1, source)
        before = tuple(
            session.scalar(select(func.count()).select_from(model))
            for model in (Observation, Evidence, Project, PowerNeed, Interpretation)
        )
        process_job(session, job_id, "test", 1, source)
        after = tuple(
            session.scalar(select(func.count()).select_from(model))
            for model in (Observation, Evidence, Project, PowerNeed, Interpretation)
        )
        assert before == after
        assert before[:2] == (2, 2)
    _assert_planning_context_has_no_opportunity(factory, monkeypatch)


def test_same_id_supported_withdrawal_updates_stored_state_and_replays(db, monkeypatch):
    factory, job_id = db
    import gridlens.ingestion.service as service
    from gridlens.intelligence.change_detection import record_material_diff, seed_material_state
    from gridlens.intelligence.project_state import project_state
    from gridlens.persistence.models import (
        ChangeEvent,
        LifecycleEvent,
        NeedObservation,
        ProjectLifecycle,
    )

    source = {"id": "taylor-development-newsflash", "retrieval_method": "taylor-newsflash"}
    initial = _direct_article()
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [initial])
    with factory() as session:
        process_job(session, job_id, "test", 1, source)
    with factory.begin() as session:
        observation = session.scalar(select(Observation).where(Observation.external_id == "2091"))
        assert observation is not None
        initial_evidence = session.scalar(
            select(Evidence).where(Evidence.observation_id == observation.id)
        )
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == observation.id)
        )
        assert initial_evidence is not None and interpretation is not None
        project = Project(
            source_id=observation.source_id,
            external_id=observation.external_id,
            name="Mustang Data Center",
            location="Taylor, Texas",
            identity_key="supported-taylor-withdrawal",
            asset_type="data_center",
            identity_facts={"project_aliases": ["Mustang Data Center"], "site": "Taylor, Texas"},
        )
        session.add(project)
        session.flush()
        interpretation.status = "accepted"
        interpretation.assessment = {
            "decision": "accepted",
            "semantic_hash": observation.content_hash,
            "evidence_hash": initial_evidence.content_hash,
            "subject": project.name,
            "location": project.location,
            "project_identity_key": project.identity_key,
            "power_activity": "facility-expansion",
        }
        need = PowerNeed(
            project_id=project.id,
            activity_key="facility-expansion",
            tier="Signal",
            rationale="Supported same-article planning signal.",
            supply="Unknown",
            active=True,
        )
        session.add_all(
            [
                need,
                ProjectLifecycle(project_id=project.id, current_state="construction"),
                LifecycleEvent(
                    project_id=project.id,
                    observation_id=observation.id,
                    evidence_id=initial_evidence.id,
                    event_type="construction",
                    state="construction",
                ),
            ]
        )
        session.flush()
        session.add(NeedObservation(need_id=need.id, observation_id=observation.id))
        seed_material_state(session, project)
    withdrawn = {**initial, "title": "WITHDRAWN - " + initial["title"], "disposition": "withdrawn"}
    withdrawn["source_hash"] = hashlib.sha256(withdrawn["title"].encode()).hexdigest()
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [withdrawn])
    with factory() as session:
        process_job(session, job_id, "test", 1, source)
        observation = session.scalar(select(Observation).where(Observation.external_id == "2091"))
        assert observation is not None
        assert session.scalar(select(func.count()).select_from(Evidence)) == 2
        withdrawal_evidence = session.scalar(
            select(Evidence).where(
                Evidence.observation_id == observation.id,
                Evidence.content_hash == withdrawn["source_hash"],
            )
        )
        assert withdrawal_evidence is not None
        current_interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == observation.id)
        )
        assert current_interpretation is not None
        assert current_interpretation.assessment["semantic_hash"] == observation.content_hash
        assert (
            current_interpretation.assessment["evidence_hash"] == withdrawal_evidence.content_hash
        )
        assert observation.content_hash != withdrawal_evidence.content_hash
        assert current_interpretation.assessment["project_identity_key"] == project.identity_key
        withdrawal_change = session.scalar(
            select(ChangeEvent).where(
                ChangeEvent.field_name == "phase",
                ChangeEvent.evidence_id == withdrawal_evidence.id,
            )
        )
        assert withdrawal_change is not None, {
            "material_events": [
                (event.field_name, event.prior_state, event.new_state, event.evidence_id)
                for event in session.scalars(select(ChangeEvent)).all()
            ],
            "assessment": session.scalar(
                select(Interpretation).where(Interpretation.observation_id == observation.id)
            ).assessment,
        }
        assert withdrawal_change.new_state == {"value": "planning_application_withdrawn"}
        lifecycle = project_state(session, project.id)["state"]["lifecycle"]
        assert lifecycle["status"] == "SUPPORTED"
        assert lifecycle["value"]["state"] == "planning_application_withdrawn"
        assert [row["id"] for row in lifecycle["evidence"]] == [str(withdrawal_evidence.id)]
        before = tuple(
            session.scalar(select(func.count()).select_from(model))
            for model in (Observation, Evidence, Project, PowerNeed, Interpretation)
        )
        process_job(session, job_id, "test", 1, source)
        after = tuple(
            session.scalar(select(func.count()).select_from(model))
            for model in (Observation, Evidence, Project, PowerNeed, Interpretation)
        )
        assert before == after
        unrelated_observation = Observation(
            source_id=observation.source_id,
            external_id="unrelated-after-withdrawal",
            title="Unrelated Taylor project update",
            abstract="A distinct project with no supported lifecycle transition.",
            published_at=datetime(2026, 9, 30, tzinfo=UTC),
            url="https://example.test/unrelated-taylor-update",
            content_hash="unrelated-taylor-semantic-hash",
        )
        session.add(unrelated_observation)
        session.flush()
        unrelated_evidence = Evidence(
            observation_id=unrelated_observation.id,
            content_hash="unrelated-taylor-evidence-hash",
            title=unrelated_observation.title,
            abstract=unrelated_observation.abstract,
            url=unrelated_observation.url,
            published_at=unrelated_observation.published_at,
        )
        session.add(unrelated_evidence)
        session.flush()
        baseline = seed_material_state(session, project)
        existing_events = session.scalar(select(func.count()).select_from(ChangeEvent))
        assert record_material_diff(session, project, unrelated_evidence, baseline) == []
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == existing_events
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Project)) == 1
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(ChangeEvent)
                .where(ChangeEvent.field_name == "phase")
            )
            == 1
        )


def test_conflict_after_supported_same_id_withdrawal_returns_to_unknown(db, monkeypatch):
    factory, job_id = db
    import gridlens.ingestion.service as service

    source = {"id": "taylor-development-newsflash", "retrieval_method": "taylor-newsflash"}
    initial = _direct_article()
    withdrawn = {**initial, "title": "WITHDRAWN - " + initial["title"], "disposition": "withdrawn"}
    withdrawn["source_hash"] = hashlib.sha256(withdrawn["title"].encode()).hexdigest()
    conflicting = _direct_article(project="Other", body_suffix="Project Other is at 9900 FM 112.")
    conflicting["title"] = "WITHDRAWN - " + conflicting["title"]
    conflicting["disposition"] = "withdrawn"
    for record in (initial, withdrawn, conflicting):
        monkeypatch.setattr(service, "retrieve_source", lambda *_args, row=record: [row])
        with factory() as session:
            process_job(session, job_id, "test", 1, source)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Evidence)) == 3
        assert session.scalar(select(func.count()).select_from(Project)) == 0
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 0
        assert session.scalar(select(func.count()).select_from(Interpretation)) == 1
    _assert_planning_context_has_no_opportunity(factory, monkeypatch)


def test_conflicting_withdrawal_at_same_external_id_keeps_status_unknown(db, monkeypatch):
    factory, job_id = db
    import gridlens.ingestion.service as service

    source = {"id": "taylor-development-newsflash", "retrieval_method": "taylor-newsflash"}
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [_direct_article()])
    with factory() as session:
        process_job(session, job_id, "test", 1, source)
    conflicting = _direct_article(project="Other", body_suffix="Project Other is at 9900 FM 112.")
    conflicting["title"] = "WITHDRAWN - " + conflicting["title"]
    conflicting["disposition"] = "withdrawn"
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [conflicting])
    with factory() as session:
        process_job(session, job_id, "test", 1, source)
        observation = session.scalar(select(Observation).where(Observation.external_id == "2091"))
        assert observation is not None
        assert session.scalar(select(func.count()).select_from(Evidence)) == 2
        assert session.scalar(select(func.count()).select_from(Project)) == 0
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 0
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == observation.id)
        )
        assert interpretation is not None
        assert interpretation.assessment["decision"] in {"context_only", "unknown"}
    _assert_planning_context_has_no_opportunity(factory, monkeypatch)
