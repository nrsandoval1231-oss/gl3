"""Exercise the real project-state projection using an isolated SQLite fixture."""

from datetime import UTC, date, datetime

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from gridlens.intelligence.project_state import project_state
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    Evidence,
    Interpretation,
    LifecycleEvent,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    ProjectLifecycle,
    Source,
)


@compiles(JSONB, "sqlite")
def sqlite_jsonb(element, compiler, **kw):
    return "JSON"


def test_policy_context_preserves_project_lifecycle_need_and_utility_unknown():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        source = Source(
            id="test-permit",
            publisher="Fixture",
            endpoint="https://example.test",
            family="construction-permits",
            geography="Texas",
            industries=[],
            retrieval_method="socrata-permits",
        )
        session.add(source)
        session.flush()
        project = Project(
            source_id=source.id,
            external_id="a",
            identity_key="a",
            name="Fixture Data Center",
            location="El Paso, TX",
            asset_type="data_center",
        )
        observation = Observation(
            source_id=source.id,
            external_id="a",
            title=project.name,
            url="https://example.test/a",
            content_hash="v1",
            published_at=date(2026, 9, 20),
        )
        session.add_all([project, observation])
        session.flush()
        evidence = Evidence(
            observation_id=observation.id,
            content_hash="v1",
            title=project.name,
            url=observation.url,
            published_at=observation.published_at,
            observed_at=datetime(2026, 10, 7, tzinfo=UTC),
        )
        need = PowerNeed(
            project_id=project.id,
            activity_key="construction",
            tier="Signal",
            rationale="Fixture construction event",
            active=True,
        )
        interpretation = Interpretation(
            observation_id=observation.id,
            content_hash="v1",
            status="accepted",
            assessment={
                "decision": "accepted",
                "evidence_hash": "v1",
                "project_identity_key": "a",
                "subject": project.name,
                "location": project.location,
                "power_activity": "construction",
                "tier": "Signal",
            },
        )
        session.add_all([evidence, need, interpretation])
        session.flush()
        session.add_all(
            [
                NeedObservation(need_id=need.id, observation_id=observation.id),
                LifecycleEvent(
                    project_id=project.id,
                    observation_id=observation.id,
                    evidence_id=evidence.id,
                    event_type="construction",
                    state="construction",
                    occurred_on=date(2026, 9, 20),
                ),
                ProjectLifecycle(project_id=project.id, current_state="construction"),
            ]
        )
        session.flush()
        before = (need.tier, need.active, need.required_mw, need.start_window, need.duration)
        result = project_state(session, project.id)
        assert result["policy_context"][0]["project_applicability"] == "regional_scope_match"
        assert result["policy_context"][0]["project_permit_status"] == "UNKNOWN"
        assert result["state"]["lifecycle"]["value"]["state"] == "construction"
        assert result["state"]["utility_service"]["status"] == "UNKNOWN"
        assert before == (
            need.tier,
            need.active,
            need.required_mw,
            need.start_window,
            need.duration,
        )
        assert not session.dirty
        interpretation.status = "rejected"
        session.flush()
        corrected = project_state(session, project.id)
        assert corrected["state"]["site"]["status"] == "UNKNOWN"
        assert corrected["policy_context"][0]["project_applicability"] == "requires_verification"
    engine.dispose()
