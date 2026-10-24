from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.lifecycle_service import (
    apply_lifecycle_observation,
    lifecycle_event_supported,
    refresh_lifecycle_projection,
)
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    Evidence,
    Interpretation,
    LifecycleEvent,
    Observation,
    PowerNeed,
    Project,
    ProjectLifecycle,
    Source,
)
from gridlens.settings import settings


@pytest.fixture
def lifecycle_db():
    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and target.database.endswith("_test")
    assert target.database != application.database
    assert target != application
    engine = create_engine(settings.test_database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(
            Source(
                id="lifecycle-scope-test",
                publisher="Synthetic fixture",
                endpoint="https://example.invalid/lifecycle",
                family="news",
                geography="New Mexico",
                industries=[],
                retrieval_method="fixture",
                health={},
            )
        )
        session.add(
            Source(
                id="georgia-air-draft-title-v",
                publisher="Synthetic fixture",
                endpoint="https://example.invalid/draft-title-v",
                family="permits",
                geography="Georgia",
                industries=[],
                retrieval_method="fixture",
                health={},
            )
        )
        session.add(
            Source(
                id="austin-building-permits",
                publisher="Synthetic fixture",
                endpoint="https://example.invalid/austin-building-permits",
                family="permits",
                geography="Austin",
                industries=[],
                retrieval_method="fixture",
                health={},
            )
        )
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


def add_case(
    factory,
    title: str,
    abstract: str,
    content_hash: str = "a" * 64,
    source_id: str = "lifecycle-scope-test",
    project_name: str = "Project Jupiter campus",
    identity_key: str = "jupiter-camp-us-nm",
    asset_type: str = "unknown",
    event_date: date | None = None,
    event_date_label: str | None = None,
):
    with factory.begin() as session:
        project = Project(
            identity_key=identity_key,
            name=project_name,
            location="New Mexico",
            source_id=source_id,
            external_id="jupiter-campus",
            asset_type=asset_type,
        )
        session.add(project)
        session.flush()
        need = PowerNeed(
            project_id=project.id,
            activity_key="campus-construction",
            tier="Signal",
            rationale="Synthetic fixture only",
            supply="Unknown",
        )
        observation = Observation(
            source_id=source_id,
            external_id="jupiter-update",
            title=title,
            abstract=abstract,
            published_at=date(2026, 10, 1),
            url="https://example.invalid/jupiter-update",
            content_hash=content_hash,
        )
        session.add_all([need, observation])
        session.flush()
        evidence = Evidence(
            observation_id=observation.id,
            content_hash=content_hash,
            title=title,
            abstract=abstract,
            url=observation.url,
            published_at=observation.published_at,
            observed_at=datetime(2026, 10, 2, tzinfo=UTC),
            extraction_location="synthetic test fixture",
            event_date=event_date,
            event_date_label=event_date_label,
        )
        session.add(evidence)
        session.flush()
        interpretation = Interpretation(
            observation_id=observation.id,
            content_hash=content_hash,
            evaluator_version="lifecycle-scope-test",
            status="accepted",
            assessment={
                "decision": "accepted",
                "semantic_hash": observation.content_hash,
                "evidence_hash": content_hash,
                "evidence": {"id": str(evidence.id)},
                "project_identity_key": project.identity_key,
            },
        )
        session.add(interpretation)
        session.flush()
        return project.id, need.id, observation.id, evidence.id


def test_mixed_article_supports_campus_event_and_not_neighbor_permit(lifecycle_db):
    factory = lifecycle_db
    project_id, need_id, observation_id, evidence_id = add_case(
        factory,
        "Project Jupiter data center update",
        "The Project Jupiter data center campus received its building permit. "
        "The separate microgrid air permit remains pending.",
    )
    with factory.begin() as session:
        project = session.get(Project, project_id)
        observation = session.get(Observation, observation_id)
        evidence = session.get(Evidence, evidence_id)
        assert project and observation and evidence
        assert apply_lifecycle_observation(session, project, observation, evidence)
        event = session.scalar(select(LifecycleEvent))
        projection = session.get(ProjectLifecycle, project_id)
        assert event and event.event_type == "building_permit_issued"
        assert event.state == "permitting"
        assert projection and projection.current_state == "permitting"
        assert session.get(PowerNeed, need_id).tier == "Signal"
        assert not apply_lifecycle_observation(session, project, observation, evidence)
        assert session.scalar(select(func.count()).select_from(LifecycleEvent)) == 1


def test_retained_mixed_event_is_not_supported_by_wrong_scope_or_state(lifecycle_db):
    factory = lifecycle_db
    project_id, _, observation_id, evidence_id = add_case(
        factory,
        "Project Jupiter data center update",
        "The Project Jupiter data center campus received its building permit. "
        "The separate microgrid air permit remains pending.",
    )
    with factory.begin() as session:
        project = session.get(Project, project_id)
        evidence = session.get(Evidence, evidence_id)
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == observation_id)
        )
        assert project and evidence and interpretation
        assert not lifecycle_event_supported(
            "utility_service", evidence, interpretation, project, "utility_energization"
        )
        assert lifecycle_event_supported(
            "building_permit_issued", evidence, interpretation, project, "permitting"
        )
        assert not lifecycle_event_supported(
            "building_permit_issued", evidence, interpretation, project, "construction"
        )


def test_opportunity_projection_binds_lifecycle_event_state_and_observation(
    lifecycle_db, monkeypatch
):
    from gridlens.api import app as api

    factory = lifecycle_db
    project_id, _, observation_id, evidence_id = add_case(
        factory,
        "Project Jupiter data center update",
        "Project Jupiter data center campus received its building permit.",
    )
    monkeypatch.setattr(api, "_need_has_current_support", lambda *_args, **_kwargs: True)
    with factory.begin() as session:
        project = session.get(Project, project_id)
        observation = session.get(Observation, observation_id)
        evidence = session.get(Evidence, evidence_id)
        assert project and observation and evidence
        assert apply_lifecycle_observation(session, project, observation, evidence)
        event = session.scalar(select(LifecycleEvent))
        assert event

        card = api.opportunity_projection(session)[0]
        assert card["lifecycle_timeline"][0]["current"] is True

        event.state = "construction"
        card = api.opportunity_projection(session)[0]
        assert card["lifecycle_timeline"][0]["current"] is False

        event.state = "permitting"
        other_observation = Observation(
            source_id=observation.source_id,
            external_id="different-observation-same-project",
            title=observation.title,
            abstract=observation.abstract,
            published_at=observation.published_at,
            url="https://example.invalid/jupiter-other-update",
            content_hash=observation.content_hash,
        )
        session.add(other_observation)
        session.flush()
        event.observation_id = other_observation.id
        card = api.opportunity_projection(session)[0]
        assert card["lifecycle_timeline"][0]["current"] is False


def test_accepted_positive_permit_cannot_be_relabelled_as_withdrawal_without_flag(lifecycle_db):
    factory = lifecycle_db
    project_id, _, observation_id, evidence_id = add_case(
        factory,
        "Project Jupiter data center update",
        "Project Jupiter data center campus received its building permit.",
    )
    with factory.begin() as session:
        project = session.get(Project, project_id)
        evidence = session.get(Evidence, evidence_id)
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == observation_id)
        )
        assert project and evidence and interpretation
        withdrawal = SimpleNamespace(
            project_id=project.id,
            observation_id=observation_id,
            evidence_id=evidence.id,
            event_type="planning_application_withdrawn",
            state="planning_application_withdrawn",
        )
        assert not lifecycle_event_supported(
            withdrawal.event_type,
            evidence,
            interpretation,
            project,
            withdrawal.state,
            event=withdrawal,
        )
        interpretation.assessment["withdrawal_supported"] = True
        assert lifecycle_event_supported(
            withdrawal.event_type,
            evidence,
            interpretation,
            project,
            withdrawal.state,
            event=withdrawal,
        )


def test_other_named_campus_cannot_supply_jupiter_projection(lifecycle_db):
    factory = lifecycle_db
    project_id, _, observation_id, evidence_id = add_case(
        factory,
        "Project Jupiter data center permitting update",
        "Project Atlas data center campus received a building permit. Project Jupiter's campus "
        "permit remains pending; the adjacent microgrid air permit is also pending.",
    )
    with factory.begin() as session:
        project = session.get(Project, project_id)
        observation = session.get(Observation, observation_id)
        evidence = session.get(Evidence, evidence_id)
        assert project and observation and evidence
        assert not apply_lifecycle_observation(session, project, observation, evidence)
        assert session.scalar(select(func.count()).select_from(LifecycleEvent)) == 0
        assert session.get(ProjectLifecycle, project_id) is None


def test_draft_title_v_application_is_not_achieved_campus_construction(lifecycle_db):
    factory = lifecycle_db
    project_id, _, observation_id, evidence_id = add_case(
        factory,
        "QTS ATL3",
        "QTS Atlanta III, LLC proposes to construct a data center. The application was received "
        "for construction and operation of emergency generators; a draft air permit is issued.",
        source_id="georgia-air-draft-title-v",
    )
    with factory.begin() as session:
        project = session.get(Project, project_id)
        observation = session.get(Observation, observation_id)
        evidence = session.get(Evidence, evidence_id)
        assert project and observation and evidence
        assert not apply_lifecycle_observation(session, project, observation, evidence)
        assert session.scalar(select(func.count()).select_from(LifecycleEvent)) == 0
        assert session.get(ProjectLifecycle, project_id) is None


def test_achieved_campus_milestone_survives_draft_title_v_procedure(lifecycle_db):
    factory = lifecycle_db
    project_id, _, observation_id, evidence_id = add_case(
        factory,
        "Project Jupiter data center and air permit update",
        "Project Jupiter's data center campus received its building permit. The draft air permit "
        "authorizes construction and operation of emergency generators.",
        source_id="georgia-air-draft-title-v",
    )
    with factory.begin() as session:
        project = session.get(Project, project_id)
        observation = session.get(Observation, observation_id)
        evidence = session.get(Evidence, evidence_id)
        assert project and observation and evidence
        assert apply_lifecycle_observation(session, project, observation, evidence)
        event = session.scalar(select(LifecycleEvent))
        assert (
            event and event.event_type == "building_permit_issued" and event.state == "permitting"
        )
        assert session.get(ProjectLifecycle, project_id).current_state == "permitting"


def test_ordinary_multi_campus_article_cannot_lend_atlas_permit_to_jupiter(lifecycle_db):
    factory = lifecycle_db
    project_id, need_id, observation_id, evidence_id = add_case(
        factory,
        "Project Jupiter data center update",
        "Project Atlas campus building permit was issued; "
        "Project Jupiter data center development agreement was approved.",
    )
    with factory.begin() as session:
        project = session.get(Project, project_id)
        observation = session.get(Observation, observation_id)
        evidence = session.get(Evidence, evidence_id)
        assert project and observation and evidence
        assert apply_lifecycle_observation(session, project, observation, evidence)
        event = session.scalar(select(LifecycleEvent))
        projection = session.get(ProjectLifecycle, project_id)
        assert event and event.event_type == "project_formation"
        assert event.state == "site_control_planning"
        assert projection and projection.current_state == "site_control_planning"
        assert session.get(PowerNeed, need_id).tier == "Signal"


def test_issued_building_permit_does_not_claim_physical_construction(lifecycle_db):
    factory = lifecycle_db
    project_id, _, observation_id, evidence_id = add_case(
        factory,
        "Building permit issued for Project Jupiter data center campus",
        "The building permit was issued for the Project Jupiter campus.",
    )
    with factory.begin() as session:
        project = session.get(Project, project_id)
        observation = session.get(Observation, observation_id)
        evidence = session.get(Evidence, evidence_id)
        assert project and observation and evidence
        assert apply_lifecycle_observation(session, project, observation, evidence)
        event = session.scalar(select(LifecycleEvent))
        projection = session.get(ProjectLifecycle, project_id)
        assert event and event.event_type == "building_permit_issued"
        assert event.state == "permitting"
        assert projection and projection.current_state == "permitting"


def test_official_dated_electrical_permit_is_retained_at_permitting(lifecycle_db):
    factory = lifecycle_db
    project_id, _, observation_id, evidence_id = add_case(
        factory,
        "Austin building permit 2026-036762 EP — Electrical Permit",
        "row: 2026-036762 EP\ndate: 2026-05-20T00:00:00.000",
        source_id="austin-building-permits",
        project_name="AUSTIN permit 2026-036762 EP",
        identity_key="austin-building-permits:2026-036762-ep",
        asset_type="data_center",
        event_date=date(2026, 5, 20),
        event_date_label="Permit issue date",
    )
    with factory.begin() as session:
        project = session.get(Project, project_id)
        observation = session.get(Observation, observation_id)
        evidence = session.get(Evidence, evidence_id)
        assert project and observation and evidence
        assert apply_lifecycle_observation(session, project, observation, evidence)
        event = session.scalar(select(LifecycleEvent))
        projection = session.get(ProjectLifecycle, project_id)
        assert event and event.event_type == "electrical_permit_issued"
        assert event.state == "permitting" and event.occurred_on == date(2026, 5, 20)
        assert projection and projection.current_state == "permitting"


def test_physical_construction_remains_distinct_from_permit(lifecycle_db):
    factory = lifecycle_db
    project_id, _, observation_id, evidence_id = add_case(
        factory,
        "Project Jupiter data center construction update",
        "Project Jupiter data center construction has started.",
    )
    with factory.begin() as session:
        project = session.get(Project, project_id)
        observation = session.get(Observation, observation_id)
        evidence = session.get(Evidence, evidence_id)
        assert project and observation and evidence
        assert apply_lifecycle_observation(session, project, observation, evidence)
        event = session.scalar(select(LifecycleEvent))
        projection = session.get(ProjectLifecycle, project_id)
        assert event and event.event_type == "construction" and event.state == "construction"
        assert projection and projection.current_state == "construction"


def test_stale_identity_or_evidence_hash_cannot_keep_historical_event(lifecycle_db):
    factory = lifecycle_db
    project_id, _, observation_id, evidence_id = add_case(
        factory,
        "Building permit issued for Project Jupiter data center campus",
        "Campus construction is authorized.",
    )
    with factory.begin() as session:
        project = session.get(Project, project_id)
        observation = session.get(Observation, observation_id)
        evidence = session.get(Evidence, evidence_id)
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == observation_id)
        )
        assert project and observation and evidence and interpretation
        apply_lifecycle_observation(session, project, observation, evidence)
        interpretation.assessment = {
            "decision": "accepted",
            "evidence_hash": evidence.content_hash,
            "project_identity_key": "different-campus",
        }
        refresh_lifecycle_projection(session, project)
        session.flush()
        assert session.get(ProjectLifecycle, project_id) is None
        assert project.asset_type == "unknown"
        interpretation.assessment["project_identity_key"] = project.identity_key
        interpretation.assessment["evidence_hash"] = "b" * 64
        refresh_lifecycle_projection(session, project)
        session.flush()
        assert session.get(ProjectLifecycle, project_id) is None


def test_retained_event_requires_exact_current_observation_interpretation_and_evidence_hash(
    lifecycle_db,
):
    factory = lifecycle_db
    project_id, need_id, observation_id, evidence_id = add_case(
        factory,
        "Building permit issued for Project Jupiter data center campus",
        "Project Jupiter's building permit was issued.",
    )
    with factory.begin() as session:
        project = session.get(Project, project_id)
        observation = session.get(Observation, observation_id)
        evidence = session.get(Evidence, evidence_id)
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == observation_id)
        )
        assert project and observation and evidence and interpretation
        assert apply_lifecycle_observation(session, project, observation, evidence)
        assert session.get(ProjectLifecycle, project_id).current_state == "permitting"

        hash_a, hash_b = evidence.content_hash, "b" * 64
        observation.content_hash = hash_b
        assert not lifecycle_event_supported(
            "building_permit_issued", evidence, interpretation, project, "permitting"
        )
        refresh_lifecycle_projection(session, project)
        session.flush()
        assert session.get(ProjectLifecycle, project_id) is None

        observation.content_hash = hash_a
        interpretation.content_hash = hash_b
        assert not lifecycle_event_supported(
            "building_permit_issued", evidence, interpretation, project, "permitting"
        )
        refresh_lifecycle_projection(session, project)
        session.flush()
        assert session.get(ProjectLifecycle, project_id) is None

        interpretation.content_hash = hash_a
        interpretation.assessment["evidence_hash"] = hash_b
        assert not lifecycle_event_supported(
            "building_permit_issued", evidence, interpretation, project, "permitting"
        )
        refresh_lifecycle_projection(session, project)
        session.flush()
        assert session.get(ProjectLifecycle, project_id) is None

        interpretation.assessment["evidence_hash"] = hash_a
        assert lifecycle_event_supported(
            "building_permit_issued", evidence, interpretation, project, "permitting"
        )
        interpretation.status = "failed"
        assert lifecycle_event_supported(
            "building_permit_issued", evidence, interpretation, project, "permitting"
        )
        interpretation.status = "accepted"
        event = session.scalar(select(LifecycleEvent))
        assert event is not None
        foreign_observation = Observation(
            source_id=observation.source_id,
            external_id="same-hash-other-observation",
            title=observation.title,
            abstract=observation.abstract,
            published_at=observation.published_at,
            url="https://example.invalid/other-observation",
            content_hash=hash_a,
        )
        session.add(foreign_observation)
        session.flush()
        foreign_evidence = Evidence(
            observation_id=foreign_observation.id,
            content_hash=hash_a,
            title=foreign_observation.title,
            abstract=foreign_observation.abstract,
            url=foreign_observation.url,
            published_at=foreign_observation.published_at,
        )
        session.add(foreign_evidence)
        session.flush()
        assert not lifecycle_event_supported(
            event.event_type,
            foreign_evidence,
            interpretation,
            project,
            event.state,
        )
        event_state = event.state
        event.state = "construction"
        assert not lifecycle_event_supported(
            event.event_type,
            evidence,
            interpretation,
            project,
            event.state,
            event=event,
        )
        event.state = event_state
        event_observation_id = event.observation_id
        event.observation_id = uuid4()
        assert not lifecycle_event_supported(
            event.event_type,
            evidence,
            interpretation,
            project,
            event.state,
            event=event,
        )
        event.observation_id = event_observation_id
        event_evidence_id = event.evidence_id
        event.evidence_id = foreign_evidence.id
        assert not lifecycle_event_supported(
            event.event_type,
            foreign_evidence,
            interpretation,
            project,
            event.state,
            event=event,
        )
        event.evidence_id = event_evidence_id
        event_project_id = event.project_id
        event.project_id = uuid4()
        assert not lifecycle_event_supported(
            event.event_type,
            evidence,
            interpretation,
            project,
            event.state,
            event=event,
        )
        event.project_id = event_project_id

        interpretation.assessment["semantic_hash"] = hash_b
        assert not lifecycle_event_supported(
            "building_permit_issued", evidence, interpretation, project, "permitting"
        )
        interpretation.assessment["semantic_hash"] = hash_a
        interpretation.assessment.pop("semantic_hash")
        assert not lifecycle_event_supported(
            "building_permit_issued", evidence, interpretation, project, "permitting"
        )
        interpretation.assessment["semantic_hash"] = hash_a
        interpretation.assessment["evidence"]["id"] = "wrong-evidence-id"
        assert not lifecycle_event_supported(
            "building_permit_issued", evidence, interpretation, project, "permitting"
        )
        interpretation.assessment["evidence"]["id"] = str(evidence.id)
        assert not apply_lifecycle_observation(session, project, observation, evidence)
        assert session.get(ProjectLifecycle, project_id).current_state == "permitting"
        assert session.scalar(select(func.count()).select_from(LifecycleEvent)) == 1
        assert session.get(PowerNeed, need_id).tier == "Signal"


def test_evidence_correction_a_to_b_to_a_restores_only_supported_event(lifecycle_db):
    factory = lifecycle_db
    project_id, need_id, observation_id, evidence_a_id = add_case(
        factory,
        "Building permit issued for Project Jupiter data center campus",
        "Campus construction is authorized.",
    )
    with factory.begin() as session:
        project = session.get(Project, project_id)
        observation = session.get(Observation, observation_id)
        evidence_a = session.get(Evidence, evidence_a_id)
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == observation_id)
        )
        assert project and observation and evidence_a and interpretation
        semantic_hash_a = observation.content_hash
        evidence_hash_a = "f" * 64
        evidence_a.content_hash = evidence_hash_a
        interpretation.assessment["evidence_hash"] = evidence_hash_a
        assert apply_lifecycle_observation(session, project, observation, evidence_a)
        assert session.get(ProjectLifecycle, project_id).current_state == "permitting"
        evidence_b = Evidence(
            observation_id=observation.id,
            content_hash="c" * 64,
            title="Project Jupiter data center update",
            abstract=(
                "The campus construction is only proposed; "
                "the microgrid air permit remains pending."
            ),
            url=observation.url,
            published_at=observation.published_at,
            observed_at=datetime(2026, 10, 3, tzinfo=UTC),
            extraction_location="synthetic corrected fixture",
        )
        session.add(evidence_b)
        session.flush()
        observation.content_hash = "b" * 64
        interpretation.content_hash = observation.content_hash
        interpretation.assessment = {
            "decision": "accepted",
            "semantic_hash": observation.content_hash,
            "evidence_hash": evidence_b.content_hash,
            "evidence": {"id": str(evidence_b.id)},
            "project_identity_key": project.identity_key,
        }
        assert not apply_lifecycle_observation(session, project, observation, evidence_b)
        session.flush()
        assert session.get(ProjectLifecycle, project_id) is None
        interpretation.content_hash = semantic_hash_a
        observation.content_hash = semantic_hash_a
        interpretation.assessment = {
            "decision": "accepted",
            "semantic_hash": observation.content_hash,
            "evidence_hash": evidence_hash_a,
            "evidence": {"id": str(evidence_a.id)},
            "project_identity_key": project.identity_key,
        }
        assert not apply_lifecycle_observation(session, project, observation, evidence_a)
        assert session.get(ProjectLifecycle, project_id).current_state == "permitting"
        assert session.scalar(select(func.count()).select_from(LifecycleEvent)) == 1
        assert session.get(PowerNeed, need_id).tier == "Signal"


def test_current_pending_version_cannot_borrow_prior_accepted_assessment(lifecycle_db):
    factory = lifecycle_db
    project_id, _, observation_id, evidence_a_id = add_case(
        factory,
        "Building permit issued for Project Jupiter data center campus",
        "The Project Jupiter campus received its building permit.",
    )
    with factory.begin() as session:
        project = session.get(Project, project_id)
        observation = session.get(Observation, observation_id)
        evidence_a = session.get(Evidence, evidence_a_id)
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == observation_id)
        )
        assert project and observation and evidence_a and interpretation
        semantic_hash_a = observation.content_hash
        evidence_hash_a = "f" * 64
        evidence_a.content_hash = evidence_hash_a
        interpretation.assessment["evidence_hash"] = evidence_hash_a
        assert apply_lifecycle_observation(session, project, observation, evidence_a)
        assessment_a = dict(interpretation.assessment)
        evidence_b = Evidence(
            observation_id=observation.id,
            content_hash="d" * 64,
            title="Project Jupiter data center update",
            abstract="The campus permit remains pending.",
            url=observation.url,
            published_at=observation.published_at,
        )
        session.add(evidence_b)
        session.flush()
        observation.content_hash = "e" * 64
        interpretation.content_hash = observation.content_hash
        interpretation.status = "pending"
        # Keep A's accepted assessment deliberately stale while B is current.
        assert not lifecycle_event_supported(
            "building_permit_issued", evidence_a, interpretation, project, "permitting"
        )
        refresh_lifecycle_projection(session, project)
        session.flush()
        assert session.get(ProjectLifecycle, project_id) is None

        observation.content_hash = semantic_hash_a
        interpretation.content_hash = semantic_hash_a
        interpretation.status = "accepted"
        interpretation.assessment = assessment_a
        assert not apply_lifecycle_observation(session, project, observation, evidence_a)
        session.flush()
        assert session.get(ProjectLifecycle, project_id).current_state == "permitting"
        assert session.scalar(select(func.count()).select_from(LifecycleEvent)) == 1
