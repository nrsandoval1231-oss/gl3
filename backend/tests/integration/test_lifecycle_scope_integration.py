from datetime import UTC, date, datetime

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
    assert target.database == "gl3audit_lifecycle_test"
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
                "evidence_hash": content_hash,
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
            event
            and event.event_type == "building_permit_issued"
            and event.state == "permitting"
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
        assert apply_lifecycle_observation(session, project, observation, evidence_a)
        assert session.get(ProjectLifecycle, project_id).current_state == "permitting"
        evidence_b = Evidence(
            observation_id=observation.id,
            content_hash="b" * 64,
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
        observation.content_hash = evidence_b.content_hash
        interpretation.content_hash = evidence_b.content_hash
        interpretation.assessment = {
            "decision": "accepted",
            "evidence_hash": evidence_b.content_hash,
            "project_identity_key": project.identity_key,
        }
        assert not apply_lifecycle_observation(session, project, observation, evidence_b)
        session.flush()
        assert session.get(ProjectLifecycle, project_id) is None
        interpretation.content_hash = evidence_a.content_hash
        observation.content_hash = evidence_a.content_hash
        interpretation.assessment = {
            "decision": "accepted",
            "evidence_hash": evidence_a.content_hash,
            "project_identity_key": project.identity_key,
        }
        assert not apply_lifecycle_observation(session, project, observation, evidence_a)
        assert session.get(ProjectLifecycle, project_id).current_state == "permitting"
        assert session.scalar(select(func.count()).select_from(LifecycleEvent)) == 1
        assert session.get(PowerNeed, need_id).tier == "Signal"
