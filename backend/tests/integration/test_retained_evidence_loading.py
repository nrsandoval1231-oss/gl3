"""Retained evidence paging reuses source bindings without per-row SQL."""

from datetime import UTC, datetime, timedelta
from math import ceil
from uuid import uuid4

import pytest
from db_reset import reset_test_database
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.buying_chain import _retained
from gridlens.persistence.models import (
    Evidence,
    Interpretation,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Source,
)
from gridlens.settings import settings


@pytest.fixture
def retained_db():
    target, application = make_url(settings.test_database_url), make_url(settings.database_url)
    assert target.database and target.database.endswith("_test") and target != application
    engine = create_engine(settings.test_database_url)
    reset_test_database(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(
            Source(
                id="retained-loading-test",
                publisher="Synthetic",
                endpoint="https://example.test/retained",
                family="news",
                geography="US",
                industries=[],
                retrieval_method="test",
                health={},
            )
        )
        session.flush()
        project = Project(
            source_id="retained-loading-test",
            external_id="site",
            identity_key="retained-loading-site",
            name="Synthetic site",
            location="Austin, TX",
        )
        session.add(project)
        session.flush()
        need = PowerNeed(
            project_id=project.id,
            activity_key="construction",
            tier="Signal",
            rationale="Synthetic",
            active=True,
        )
        session.add(need)
        session.flush()
        ids = project.id, need.id
    yield engine, factory, ids
    engine.dispose()


def add_evidence(session, need_id, index, *, status="accepted", binding="current"):
    observation = Observation(
        source_id="retained-loading-test",
        external_id=str(uuid4()),
        title="Synthetic retained evidence",
        url="https://example.test/retained",
        content_hash=f"hash-{index}",
    )
    session.add(observation)
    session.flush()
    evidence = Evidence(
        observation_id=observation.id,
        title=observation.title,
        url=observation.url,
        content_hash=observation.content_hash,
        observed_at=datetime(2026, 10, 1, tzinfo=UTC) - timedelta(minutes=index),
    )
    session.add(evidence)
    session.flush()
    session.add(NeedObservation(need_id=need_id, observation_id=observation.id))
    if status != "missing":
        session.add(
            Interpretation(
                observation_id=observation.id,
                content_hash=observation.content_hash,
                status=status,
                assessment={
                    "decision": "accepted",
                    "evidence_hash": observation.content_hash if binding != "stale" else "old",
                    "project_identity_key": "retained-loading-site"
                    if binding != "wrong_project"
                    else "different-site",
                    "admission_status": "supplemental",
                },
            )
        )
    return evidence.id


@pytest.mark.parametrize("stale_count", [1, 25, 73])
def test_retained_evidence_query_count_scales_with_pages_not_rejected_rows(
    retained_db, stale_count
):
    engine, factory, (project_id, need_id) = retained_db
    with factory.begin() as session:
        for index in range(stale_count):
            add_evidence(session, need_id, index, binding="stale")
        expected = [
            add_evidence(session, need_id, index) for index in range(stale_count, stale_count + 4)
        ]
    statements = []

    def count_selects(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    with factory() as session:
        project = session.get(Project, project_id)
        event.listen(engine, "before_cursor_execute", count_selects)
        try:
            actual = _retained(session, project)
        finally:
            event.remove(engine, "before_cursor_execute", count_selects)
    assert [item.id for item in actual] == expected
    assert len(statements) <= ceil((stale_count + 4) / 24)


@pytest.mark.parametrize(
    ("status", "binding", "accepted"),
    [
        ("accepted", "current", True),
        ("failed", "current", True),
        ("pending", "current", True),
        ("rejected", "current", False),
        ("accepted", "stale", False),
        ("accepted", "wrong_project", False),
        ("missing", "current", False),
    ],
)
def test_retained_evidence_preloading_preserves_current_binding(
    retained_db, status, binding, accepted
):
    _engine, factory, (project_id, need_id) = retained_db
    with factory.begin() as session:
        evidence_id = add_evidence(session, need_id, 0, status=status, binding=binding)
    with factory() as session:
        actual = _retained(session, session.get(Project, project_id))
    assert [item.id for item in actual] == ([evidence_id] if accepted else [])
