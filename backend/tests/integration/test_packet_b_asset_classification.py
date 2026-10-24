from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.lifecycle_service import (
    refresh_lifecycle_projection,
    refresh_project_asset_type,
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
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
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
    Base.metadata.drop_all(engine)
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
                    candidate_project_id=project_id,
                    evidence_id=evidence.id,
                    decision="matched",
                    reason="Exact TDLR registration identifier",
                    matched_facts=["TABS registration identifier"],
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

        # Explicitly unmatching the current version retracts its classification too.
        session.add(
            ProjectMatchDecision(
                observation_id=observation_id,
                candidate_project_id=None,
                evidence_id=revised.id,
                decision="unmatched",
                reason="Source revision no longer supports project identity",
                matched_facts=[],
                identity_facts={},
                decided_at=base_time + timedelta(seconds=2),
            )
        )
        session.flush()
        refresh_project_asset_type(session, project)
        assert project.asset_type == "unknown"
