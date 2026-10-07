"""Real ORM projection against isolated SQLite; synthetic evidence only."""

from copy import deepcopy
from datetime import UTC, date, datetime
from importlib import import_module
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from gridlens.persistence.models import Evidence, Interpretation, Observation, Project, Source


@compiles(JSONB, "sqlite")
def sqlite_jsonb(element, compiler, **kw):
    return "JSON"


@pytest.fixture
def retained():
    engine = create_engine("sqlite://")
    tables = [
        Source.__table__,
        Observation.__table__,
        Project.__table__,
        Evidence.__table__,
        Interpretation.__table__,
    ]
    for table in tables:
        table.create(engine)
    with Session(engine) as session:
        source = Source(
            id="synthetic",
            publisher="Synthetic utility",
            endpoint="https://example.test",
            family="utility",
            geography="TX",
            industries=[],
            retrieval_method="test",
        )
        session.add(source)
        session.flush()
        observation = Observation(
            id=uuid4(),
            source_id=source.id,
            external_id="request-1",
            title="Synthetic request",
            abstract="Intermediate agreement executed.",
            published_at=date(2026, 10, 8),
            url="https://example.test/request",
            content_hash="a" * 64,
        )
        project = Project(
            id=uuid4(),
            identity_key="synthetic-site",
            name="Synthetic project",
            source_id=source.id,
            external_id="project-1",
        )
        session.add_all([observation, project])
        session.flush()
        evidence = Evidence(
            id=uuid4(),
            observation_id=observation.id,
            title=observation.title,
            abstract=observation.abstract,
            url=observation.url,
            content_hash=observation.content_hash,
            published_at=observation.published_at,
            observed_at=datetime(2026, 10, 8, tzinfo=UTC),
            extraction_location="page 1",
        )
        interpretation = Interpretation(
            observation_id=observation.id,
            status="accepted",
            content_hash=observation.content_hash,
            assessment={
                "project_identity_key": project.identity_key,
                "evidence_hash": evidence.content_hash,
                "subject": project.name,
                "tier": "Signal",
            },
        )
        session.add_all([evidence, interpretation])
        session.flush()
        yield session, project, observation, evidence, interpretation
    engine.dispose()


def test_attached_facts_are_project_bound_without_changing_tier(retained):
    module = import_module("gridlens.intelligence.interconnection")
    session, project, _, evidence, interpretation = retained
    before = deepcopy(interpretation.assessment)
    module.attach_interconnection_facts(
        session,
        project.id,
        evidence.id,
        request_id="utility-serial-1",
        facts=[
            {
                "field": "intermediate_executed_on",
                "value": "2026-10-08",
                "quote": "Intermediate agreement executed.",
            }
        ],
        today=date(2026, 10, 8),
    )
    view = module.current_interconnection_state(session, project.id, today=date(2026, 10, 8))
    fact = view["requests"][0]["facts"]["intermediate_executed_on"]
    assert fact["status"] == "REPORTED"
    assert fact["claims"][0]["evidence"]["id"] == str(evidence.id)
    assert fact["claims"][0]["evidence"]["publisher"] == "Synthetic utility"
    assert {k: interpretation.assessment[k] for k in before} == before
    assert view["requests"][0]["facts"]["study_state"]["status"] == "UNKNOWN"


@pytest.mark.parametrize("mutation", ["rejected", "hash", "observation", "project", "quote"])
def test_stale_wrong_project_or_unsupported_evidence_cannot_be_attached(retained, mutation):
    module = import_module("gridlens.intelligence.interconnection")
    session, project, observation, evidence, interpretation = retained
    quote = "Intermediate agreement executed."
    if mutation == "rejected":
        interpretation.status = "rejected"
    elif mutation == "hash":
        interpretation.content_hash = "b" * 64
    elif mutation == "observation":
        observation.content_hash = "b" * 64
    elif mutation == "project":
        interpretation.assessment = {**interpretation.assessment, "project_identity_key": "other"}
    else:
        quote = "SLLIA funded."
    with pytest.raises(ValueError):
        module.attach_interconnection_facts(
            session,
            project.id,
            evidence.id,
            request_id="utility-serial-1",
            facts=[{"field": "intermediate_executed_on", "value": "2026-10-08", "quote": quote}],
            today=date(2026, 10, 8),
        )


def test_projection_drops_superseded_evidence_and_replay_does_not_duplicate(retained):
    module = import_module("gridlens.intelligence.interconnection")
    session, project, observation, evidence, interpretation = retained
    args = {
        "request_id": "utility-serial-1",
        "facts": [
            {
                "field": "intermediate_executed_on",
                "value": "2026-10-08",
                "quote": "Intermediate agreement executed.",
            }
        ],
        "today": date(2026, 10, 8),
    }
    module.attach_interconnection_facts(session, project.id, evidence.id, **args)
    saved = deepcopy(interpretation.assessment)
    module.attach_interconnection_facts(session, project.id, evidence.id, **args)
    assert interpretation.assessment == saved
    observation.content_hash = "b" * 64
    assert (
        module.current_interconnection_state(session, project.id, today=date(2026, 10, 8))[
            "requests"
        ]
        == []
    )


def test_different_request_ids_do_not_combine_commitments():
    module = import_module("gridlens.domain.large_load_interconnection")
    records = [
        {
            "request_id": rid,
            "text": "Study completed.",
            "evidence": {
                "id": rid,
                "hash": "a" * 64,
                "url": "https://example.test",
                "published_at": "2026-10-08",
                "retrieved_at": "2026-10-08T00:00:00Z",
                "extraction_location": "page 1",
            },
            "facts": [{"field": "study_state", "value": "completed", "quote": "Study completed."}],
        }
        for rid in ("request-a", "request-b")
    ]
    assert len(module.interconnection_state(records, today=date(2026, 10, 8))["requests"]) == 2


def test_project_state_exposes_request_facts_without_energization_or_needs(retained):
    from gridlens.intelligence.interconnection import attach_interconnection_facts
    from gridlens.intelligence.project_state import project_state
    from gridlens.persistence.database import Base

    session, project, _, evidence, _ = retained
    Base.metadata.create_all(session.get_bind())
    attach_interconnection_facts(
        session,
        project.id,
        evidence.id,
        request_id="utility-serial-1",
        facts=[
            {
                "field": "intermediate_executed_on",
                "value": "2026-10-08",
                "quote": "Intermediate agreement executed.",
            }
        ],
        today=date(2026, 10, 8),
    )
    view = project_state(session, project.id, today=date(2026, 10, 8))["state"]
    assert view["large_load_interconnection"]["requests"]
    assert view["utility_service"]["status"] == "UNKNOWN"
    assert view["power_need"]["status"] == "UNKNOWN"


def test_reviewed_fact_changes_cannot_overwrite_accepted_history(retained):
    from gridlens.intelligence.interconnection import attach_interconnection_facts

    session, project, _, evidence, interpretation = retained
    args = {
        "request_id": "utility-serial-1",
        "facts": [
            {
                "field": "intermediate_executed_on",
                "value": "2026-10-08",
                "quote": "Intermediate agreement executed.",
            }
        ],
        "today": date(2026, 10, 8),
    }
    attach_interconnection_facts(session, project.id, evidence.id, **args)
    saved = deepcopy(interpretation.assessment)
    args["facts"][0]["value"] = "2026-10-07"
    with pytest.raises(ValueError, match="overwritten"):
        attach_interconnection_facts(session, project.id, evidence.id, **args)
    assert interpretation.assessment == saved


def test_malformed_retained_payload_returns_visible_limitation(retained):
    from gridlens.intelligence.interconnection import current_interconnection_state

    session, project, _, evidence, interpretation = retained
    interpretation.assessment = {
        **interpretation.assessment,
        "large_load_interconnection": {
            "version": "tx-large-load-v1",
            "project_identity_key": project.identity_key,
            "evidence_id": str(evidence.id),
            "evidence_hash": evidence.content_hash,
            "request_id": "utility-serial-1",
            "facts": None,
        },
    }
    view = current_interconnection_state(session, project.id, today=date(2026, 10, 8))
    assert view["requests"][0]["limitations"]
    assert view["requests"][0]["interpretation"]["applicability"] == "UNKNOWN"
