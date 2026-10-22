"""Active read surfaces retain history while enforcing persisted site scope."""

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from gridlens.persistence.models import (
    ChangeEvent,
    Evidence,
    Observation,
    PowerNeed,
    Project,
    Pursuit,
    Source,
)

pytest_plugins = ["test_saved_browse"]


def test_active_change_and_pursuit_surfaces_exclude_out_of_region(saved_db):
    from test_saved_browse import seed

    from gridlens.api import app as api
    from gridlens.intelligence.pursuits import pursuit_view

    seed(saved_db, count=4, histories=1)
    with saved_db.begin() as session:
        source = session.get(Source, "synthetic-permits")
        tx = session.scalar(select(Project).where(Project.external_id == "1"))
        ca = session.scalar(select(Project).where(Project.external_id == "0"))
        assert source is not None and tx is not None and ca is not None
        ca.location = "Santa Clara, CA"
        obs = Observation(
            source_id=source.id,
            external_id=f"scope-{uuid4()}",
            title="Site update",
            abstract="Physical site update",
            url="https://example.test/change",
            content_hash="a" * 64,
            published_at=date(2026, 10, 22),
        )
        session.add(obs)
        session.flush()
        evidence = Evidence(
            observation_id=obs.id,
            title=obs.title,
            abstract=obs.abstract,
            url=obs.url,
            content_hash=obs.content_hash,
            observed_at=datetime.now(UTC),
        )
        session.add(evidence)
        session.flush()
        session.add_all(
            [
                ChangeEvent(
                    observation_id=obs.id,
                    content_hash=obs.content_hash,
                    kind="material_change",
                    project_id=tx.id,
                    evidence_id=evidence.id,
                    material=True,
                    field_name="phase",
                ),
                ChangeEvent(
                    observation_id=obs.id,
                    content_hash=obs.content_hash,
                    kind="material_change",
                    project_id=ca.id,
                    evidence_id=evidence.id,
                    material=True,
                    field_name="phase",
                ),
            ]
        )
        legacy = Pursuit(
            identity_key=f"legacy-{uuid4()}",
            project_id=ca.id,
            project_ids=[str(ca.id)],
            snapshot={"ranking_reasons": ["saved"], "location": "Santa Clara, CA"},
        )
        session.add(legacy)
        session.flush()
        legacy_id = legacy.id
        ca_id = ca.id

    visible = api.changes()
    assert len(visible) == 1
    assert visible[0]["title"] == "Site update"
    with saved_db() as session:
        assert (
            pursuit_view(session, session.get(Pursuit, legacy_id), current={})["action_status"]
            == "Drop"
        )
        with pytest.raises(HTTPException):
            api.project_changes_endpoint(ca_id)


def test_direct_need_ids_cannot_bypass_project_scope(saved_db):
    from test_saved_browse import seed

    from gridlens.api import app as api
    from gridlens.intelligence.commercial_evaluation import evaluate_targets

    need_ids = seed(saved_db, count=4, histories=1)
    with saved_db() as session:
        excluded = session.get(PowerNeed, need_ids[0])
        assert excluded is not None
        project = session.get(Project, excluded.project_id)
        assert project is not None
        project.location = "Santa Clara, CA"
        excluded_id = excluded.id
        assert api.opportunity_projection(session, selected_need_ids={excluded_id}) == []
        assert evaluate_targets(session, [excluded_id]) == {}
