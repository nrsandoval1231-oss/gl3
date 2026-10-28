from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from db_reset import reset_test_database
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.lifecycle_service import (
    refresh_lifecycle_projection,
    refresh_project_asset_type,
)
from gridlens.persistence.models import (
    Evidence,
    Interpretation,
    Job,
    LifecycleEvent,
    Observation,
    PowerNeed,
    Project,
    ProjectLifecycle,
    ProjectMatchDecision,
    Source,
)
from gridlens.settings import settings


@pytest.fixture
def asset_classification_db():
    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and target.database.endswith("_test")
    assert target.database != application.database
    engine = create_engine(settings.test_database_url)
    reset_test_database(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(
            Source(
                id="texas-tdlr-tabs-data-centers",
                publisher="Texas Department of Licensing and Regulation",
                endpoint="https://example.invalid/tdlr",
                family="permits",
                geography="Texas",
                industries=["data_center"],
                retrieval_method="fixture",
                health={},
            )
        )
    yield factory
    engine.dispose()


def test_asset_projection_is_current_evidence_bound_and_independent_of_milestones(
    asset_classification_db,
):
    factory = asset_classification_db
    project_id, observation_id = uuid4(), uuid4()
    first_hash, second_hash = "a" * 64, "b" * 64
    base_time = datetime(2026, 10, 24, tzinfo=UTC)
    with factory.begin() as session:
        project = Project(
            id=project_id,
            identity_key="TABS:TABS2027002672",
            name="DAL130 - Data Center",
            location="Westlake, TX",
            source_id="texas-tdlr-tabs-data-centers",
            external_id="TABS2027002672",
            asset_type="unknown",
        )
        observation = Observation(
            id=observation_id,
            source_id="texas-tdlr-tabs-data-centers",
            external_id="TABS2027002672",
            title="DAL130 - Data Center",
            abstract="Project registration; scope: new data center building.",
            url="https://example.invalid/tdlr/TABS2027002672",
            content_hash=first_hash,
        )
        need = PowerNeed(
            project_id=project_id,
            activity_key="construction",
            tier="Signal",
            rationale="Explicit project evidence merits investigation.",
            supply="Unknown",
        )
        evidence = Evidence(
            observation_id=observation_id,
            content_hash=first_hash,
            title=observation.title,
            abstract=observation.abstract,
            url=observation.url,
            observed_at=base_time,
            extraction_location="TDLR project page",
        )
        session.add(project)
        session.flush()
        session.add_all([observation, evidence, need])
        session.flush()
        session.add_all(
            [
                Interpretation(
                    observation_id=observation_id,
                    content_hash=first_hash,
                    evaluator_version="fixture-v1",
                    status="accepted",
                    assessment={
                        "decision": "accepted",
                        "semantic_hash": first_hash,
                        "evidence_hash": first_hash,
                        "evidence_id": str(evidence.id),
                        "project_identity_key": project.identity_key,
                    },
                ),
                ProjectMatchDecision(
                    observation_id=observation_id,
                    candidate_project_id=None,
                    evidence_id=evidence.id,
                    decision="separate",
                    reason=(
                        "No existing project candidate; primary TDLR project retained separately"
                    ),
                    matched_facts=[],
                    identity_facts={"external_id": "TABS2027002672"},
                    decided_at=base_time,
                ),
            ]
        )
        session.flush()
        before, after = refresh_project_asset_type(session, project)
        assert (before, after) == ("unknown", "data_center")
        assert session.scalar(select(LifecycleEvent)) is None
        assert session.get(ProjectLifecycle, project_id) is None
        assert need.tier == "Signal"
        assert need.required_mw is None and need.start_window is None and need.duration is None
        refresh_lifecycle_projection(session, project)

        # A newly accepted source version removes the explicit asset phrase.
        observation.title = "DAL130 registration"
        observation.abstract = "Project registration; office infrastructure."
        observation.content_hash = second_hash
        revised = Evidence(
            observation_id=observation_id,
            content_hash=second_hash,
            title=observation.title,
            abstract=observation.abstract,
            url=observation.url,
            observed_at=base_time + timedelta(seconds=1),
            extraction_location="TDLR project page",
        )
        session.add(revised)
        session.flush()
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == observation_id)
        )
        assert interpretation is not None
        interpretation.content_hash = second_hash
        interpretation.assessment = {
            "decision": "accepted",
            "semantic_hash": second_hash,
            "evidence_hash": second_hash,
            "evidence_id": str(revised.id),
            "project_identity_key": project.identity_key,
        }
        session.add(
            ProjectMatchDecision(
                observation_id=observation_id,
                candidate_project_id=project_id,
                evidence_id=revised.id,
                decision="matched",
                reason="Current revised TDLR record",
                matched_facts=["TABS registration identifier"],
                identity_facts={"external_id": "TABS2027002672"},
                decided_at=base_time + timedelta(seconds=1),
            )
        )
        session.flush()
        refresh_project_asset_type(session, project)
        assert project.asset_type == "unknown"


def test_process_records_classifies_primary_tdlr_registration_replay_and_revision(
    asset_classification_db,
):
    """Exercise the ordinary no-candidate ingestion path, including null-candidate separate."""
    import gridlens.ingestion.service as service

    factory = asset_classification_db
    source_id = "texas-tdlr-tabs-data-centers"
    external_id = "TABS2027002672"
    definition = {
        "id": source_id,
        "publisher": "Texas Department of Licensing and Regulation",
        "endpoint": "https://www.tdlr.texas.gov/TABS/Search/SearchProjects",
        "family": "construction-permits",
        "geography": "Texas",
        "industries": ["data_center"],
        "retrieval_method": "tdlr-tabs",
    }
    with factory.begin() as session:
        source = session.get(Source, source_id)
        assert source is not None
        source.family = definition["family"]
        source.retrieval_method = definition["retrieval_method"]
        job = Job(
            source_id=source_id,
            status="running",
            lease_owner="test",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        job_id = job.id

    def registration(description: str) -> dict:
        title = "DAL130 - Data Center"
        return {
            "document_number": external_id,
            "title": title,
            "abstract": f"Project registration; scope: {description}.",
            "publication_date": "2026-10-20",
            "html_url": f"https://www.tdlr.texas.gov/TABS/Search/Project/{external_id}",
            "extraction_location": "TDLR TABS project details page",
            "event_date": "2026-10-20",
            "event_date_label": "TDLR registration date",
            "permit": {
                "source_type": source_id,
                "row_id": external_id,
                "facility": title,
                "description": description,
                "subtype": "New construction",
                "status": "Open",
                "location": "100 Main Street, Dallas, TX 75201",
                "applicant": "DAL130 Development LLC",
            },
        }

    with factory() as session:
        counts = service.process_records(
            session,
            job_id,
            "test",
            1,
            definition,
            [registration("new data center building")],
            allow_model=False,
        )
    assert counts["permit_accepted"] == 1
    with factory() as session:
        replay = service.process_records(
            session,
            job_id,
            "test",
            1,
            definition,
            [registration("new data center building")],
            allow_model=False,
        )
    assert replay["unchanged"] == 1
    with factory() as session:
        project = session.scalar(select(Project))
        observation = session.scalar(select(Observation))
        evidence = session.scalar(select(Evidence))
        interpretation = session.scalar(select(Interpretation))
        assert project is not None and project.source_id == source_id
        assert project.external_id == external_id
        assert project.asset_type == "data_center"
        assert observation is not None and evidence is not None and interpretation is not None
        assert interpretation.status == "accepted"
        assert interpretation.assessment["project_identity_key"] == project.identity_key
        own_decision = session.scalar(
            select(ProjectMatchDecision).where(
                ProjectMatchDecision.observation_id == observation.id,
                ProjectMatchDecision.evidence_id == evidence.id,
                ProjectMatchDecision.candidate_project_id.is_(None),
            )
        )
        assert own_decision is not None and own_decision.decision == "separate"
        assert session.scalar(select(LifecycleEvent)) is None
        need = session.scalar(select(PowerNeed))
        assert need is not None and need.tier == "Signal"
        assert need.required_mw is None and need.start_window is None and need.duration is None

    # A current explicit project-specific unmatched decision overrides the
    # null-candidate primary-record decision; the exact project key cannot
    # bypass a human retraction.
    with factory.begin() as session:
        project = session.scalar(select(Project))
        observation = session.scalar(select(Observation))
        evidence = session.scalar(select(Evidence))
        assert project is not None and observation is not None and evidence is not None
        session.add(
            ProjectMatchDecision(
                observation_id=observation.id,
                candidate_project_id=project.id,
                evidence_id=evidence.id,
                decision="unmatched",
                reason="Reviewer rejected this TDLR record as support for this project",
                matched_facts=[],
                identity_facts={},
                decided_at=datetime.now(UTC) + timedelta(seconds=1),
            )
        )
        session.flush()
        refresh_project_asset_type(session, project)
        assert project.asset_type == "unknown"

    # A new accepted revision becomes current and can restore its explicit
    # classification. The next rejected revision retracts it; dates, MW,
    # qualification and lifecycle remain unknown throughout.
    with factory() as session:
        accepted_revision = service.process_records(
            session,
            job_id,
            "test",
            1,
            definition,
            [registration("new data center building addition")],
            allow_model=False,
        )
    assert accepted_revision["permit_accepted"] == 1
    with factory() as session:
        project = session.scalar(select(Project))
        need = session.scalar(select(PowerNeed))
        assert project is not None and project.asset_type == "data_center"
        assert need is not None and need.tier == "Signal"
        assert need.required_mw is None and need.start_window is None and need.duration is None

    with factory() as session:
        rejected_revision = service.process_records(
            session,
            job_id,
            "test",
            1,
            definition,
            [registration("office building renovation")],
            allow_model=False,
        )
    assert rejected_revision["permit_rejected"] == 1
    with factory() as session:
        project = session.scalar(select(Project))
        interpretation = session.scalar(select(Interpretation))
        need = session.scalar(select(PowerNeed))
        assert project is not None and project.asset_type == "unknown"
        assert interpretation is not None and interpretation.status == "rejected"
        assert need is not None and need.tier == "Signal"
        assert need.required_mw is None and need.start_window is None and need.duration is None
        assert session.scalar(select(LifecycleEvent)) is None


def test_conflicting_industry_keeps_events_and_skips_unknown_lifecycle_rank(
    asset_classification_db,
):
    factory = asset_classification_db
    project_id, tdlr_observation_id = uuid4(), uuid4()
    base_time = datetime(2026, 10, 24, tzinfo=UTC)
    tdlr_hash, event_hash = "c" * 64, "d" * 64
    with factory.begin() as session:
        project = Project(
            id=project_id,
            identity_key="TABS:TABS2027002672",
            name="DAL130 - Data Center",
            location="Dallas, TX",
            source_id="texas-tdlr-tabs-data-centers",
            external_id="TABS2027002672",
            asset_type="unknown",
        )
        tdlr_observation = Observation(
            id=tdlr_observation_id,
            source_id="texas-tdlr-tabs-data-centers",
            external_id="TABS2027002672",
            title="DAL130 - Data Center",
            abstract="Project registration; scope: new data center building.",
            url="https://example.invalid/tdlr/TABS2027002672",
            content_hash=tdlr_hash,
        )
        session.add_all([project, tdlr_observation])
        session.flush()
        tdlr_evidence = Evidence(
            observation_id=tdlr_observation_id,
            content_hash=tdlr_hash,
            title=tdlr_observation.title,
            abstract=tdlr_observation.abstract,
            url=tdlr_observation.url,
            observed_at=base_time,
            extraction_location="TDLR project page",
        )
        conflict_source = Source(
            id="fixture-compressor-lifecycle",
            publisher="Synthetic fixture",
            endpoint="https://example.invalid/compressor",
            family="news",
            geography="Texas",
            industries=[],
            retrieval_method="fixture",
            health={},
        )
        session.add_all([tdlr_evidence, conflict_source])
        session.flush()
        conflict_observation = Observation(
            source_id=conflict_source.id,
            external_id="compressor-event-1",
            title="New natural gas compressor station construction began",
            abstract="Construction is underway.",
            url="https://example.invalid/compressor-event",
            content_hash=event_hash,
        )
        session.add(conflict_observation)
        session.flush()
        conflict_evidence = Evidence(
            observation_id=conflict_observation.id,
            content_hash=event_hash,
            title=conflict_observation.title,
            abstract=conflict_observation.abstract,
            url=conflict_observation.url,
            observed_at=base_time + timedelta(seconds=1),
            extraction_location="Synthetic lifecycle fixture",
        )
        session.add(conflict_evidence)
        session.flush()
        session.add_all(
            [
                Interpretation(
                    observation_id=tdlr_observation_id,
                    content_hash=tdlr_hash,
                    evaluator_version="fixture-v1",
                    status="accepted",
                    assessment={
                        "decision": "accepted",
                        "semantic_hash": tdlr_hash,
                        "evidence_hash": tdlr_hash,
                        "evidence_id": str(tdlr_evidence.id),
                        "project_identity_key": project.identity_key,
                    },
                ),
                Interpretation(
                    observation_id=conflict_observation.id,
                    content_hash=event_hash,
                    evaluator_version="fixture-v1",
                    status="accepted",
                    assessment={
                        "decision": "accepted",
                        "semantic_hash": event_hash,
                        "evidence_hash": event_hash,
                        "evidence_id": str(conflict_evidence.id),
                        "project_identity_key": project.identity_key,
                    },
                ),
                LifecycleEvent(
                    project_id=project_id,
                    observation_id=conflict_observation.id,
                    evidence_id=conflict_evidence.id,
                    event_type="construction",
                    state="construction",
                    value_kind="reported",
                ),
            ]
        )
        session.flush()
        refresh_lifecycle_projection(session, project)
        assert project.asset_type == "unknown"
        assert session.scalar(select(LifecycleEvent)) is not None
        assert session.get(ProjectLifecycle, project_id) is None
