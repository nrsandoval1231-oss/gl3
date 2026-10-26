"""Archived HTTP payload budgets cannot become a lifetime machine-planning cap."""

import hashlib
from datetime import UTC, datetime, timedelta
from importlib import import_module
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.pursuit_questions import schedule_questions
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    Evidence,
    Interpretation,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Pursuit,
    PursuitCallNote,
    PursuitResearchQuestion,
    Source,
)
from gridlens.settings import settings


@pytest.fixture
def planner_runtime(monkeypatch):
    target = make_url(settings.test_database_url)
    assert target.database and target.database.endswith("_test")
    assert target != make_url(settings.database_url)
    schema = "planner_history_" + uuid4().hex
    admin = create_engine(settings.test_database_url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        settings.test_database_url, connect_args={"options": f"-csearch_path={schema}"}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    api = import_module("gridlens.api.app")
    worker = import_module("gridlens.intelligence.autonomous_research")
    monkeypatch.setattr(api, "SessionLocal", factory)
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(settings, "saved_browse_enabled", False)
    monkeypatch.setattr(settings, "opportunity_enrichment_enabled", True)
    monkeypatch.setattr(settings, "autonomous_research_daily_questions", 1)
    now = datetime.now(UTC)
    body = "Data center electrical construction includes transformers."
    semantic_hash = hashlib.sha256(b"synthetic-planner-observation").hexdigest()
    evidence_hash = hashlib.sha256(body.encode()).hexdigest()
    with factory.begin() as session:
        source = Source(
            id="austin-building-permits",
            publisher="Synthetic planner regression source",
            endpoint="https://example.invalid/",
            family="construction-permits",
            geography="Austin",
            industries=[],
            retrieval_method="socrata-permits",
            health={},
        )
        session.add(source)
        session.flush()
        project = Project(
            source_id=source.id,
            external_id="2026-900001 EP",
            identity_key="austin-building-permits:2026-900001 EP",
            name="Synthetic planner site",
            location="811 CLAYTON LN, Austin, TX",
            asset_type="data_center",
            region_status="ELIGIBLE",
        )
        session.add(project)
        session.flush()
        need = PowerNeed(
            project_id=project.id,
            activity_key="electrical-construction",
            tier="Signal",
            rationale="Official work scope; activity-specific load and supply remain unknown.",
            supply="Unknown",
        )
        observation = Observation(
            source_id=source.id,
            external_id=project.external_id,
            title="Synthetic planner site electrical building permit",
            abstract=body,
            published_at=now.date(),
            url="https://abc.austintexas.gov/permit/2026-900001",
            content_hash=semantic_hash,
        )
        session.add_all([need, observation])
        session.flush()
        evidence = Evidence(
            observation_id=observation.id,
            content_hash=evidence_hash,
            title=observation.title,
            abstract=body,
            url=observation.url,
            published_at=observation.published_at,
            extraction_location="Synthetic exact official permit record",
        )
        session.add(evidence)
        session.flush()
        session.add_all(
            [
                NeedObservation(need_id=need.id, observation_id=observation.id),
                Interpretation(
                    observation_id=observation.id,
                    content_hash=semantic_hash,
                    evaluator_version="synthetic-planner-regression",
                    status="accepted",
                    assessment={
                        "decision": "accepted",
                        "semantic_hash": semantic_hash,
                        "evidence_hash": evidence_hash,
                        "evidence": {"id": str(evidence.id), "url": evidence.url},
                        "project_identity_key": project.identity_key,
                        "power_activity": need.activity_key,
                        "activity_key": need.activity_key,
                        "subject": project.name,
                        "location": project.location,
                        "action": body,
                    },
                ),
            ]
        )
        pursuit = Pursuit(
            identity_key=f"commercial-need:{need.id}",
            project_id=project.id,
            project_ids=[str(project.id)],
            snapshot={"retained_archive_marker": "preserve historical receipt"},
        )
        session.add(pursuit)
        session.flush()
        ids = need.id, project.id, pursuit.id, evidence.id, observation.id
    yield factory, api, worker, ids, now
    engine.dispose()
    with admin.begin() as connection:
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    admin.dispose()


@pytest.mark.parametrize("archive_kind", ["questions", "pursuits", "notes", "snapshot"])
def test_archived_history_does_not_stop_current_planning_or_scheduling(
    planner_runtime, archive_kind
):
    factory, api, worker, ids, now = planner_runtime
    need_id, project_id, pursuit_id, _evidence_id, _observation_id = ids
    old_time = now - timedelta(days=120)
    with factory.begin() as session:
        if archive_kind == "questions":
            session.add_all(
                PursuitResearchQuestion(
                    pursuit_id=pursuit_id,
                    project_id=project_id,
                    need_id=need_id,
                    category="load",
                    question=f"Historical unresolved load check {index}",
                    status="UNRESOLVED",
                    attempt_count=1,
                    query_fingerprint=f"{index:064x}",
                    evidence_fingerprint="f" * 64,
                    context={"policy_version": "historical-policy"},
                    budget={},
                    receipt={"historical_index": index},
                    created_at=old_time,
                    completed_at=old_time,
                )
                for index in range(501)
            )
        elif archive_kind == "pursuits":
            # Sparse legacy archive references are not current project evidence
            # and must neither block the current target nor create new projects.
            session.add_all(
                Pursuit(
                    identity_key=f"commercial-need:{uuid4()}",
                    project_id=project_id,
                    project_ids=[str(project_id)],
                    snapshot={"retained_archive_marker": f"old receipt {index}"},
                )
                for index in range(500)
            )
        elif archive_kind == "notes":
            session.add_all(
                PursuitCallNote(
                    pursuit_id=pursuit_id,
                    client_id=uuid4(),
                    note=f"Historical attributed note {index}",
                    outcome="Contacted",
                    next_action="Historical action; no new user entry",
                    created_at=old_time,
                )
                for index in range(501)
            )
        else:
            pursuit = session.get(Pursuit, pursuit_id)
            pursuit.snapshot = {
                **pursuit.snapshot,
                "retained_padding": "x" * (api._MAX_SAVED_SNAPSHOT_BYTES + 1),
            }
    with factory() as session:
        prior_questions = {
            row.id: row.receipt for row in session.scalars(select(PursuitResearchQuestion))
        }
        prior_notes = {row.id: row.note for row in session.scalars(select(PursuitCallNote))}
        prior_snapshots = {row.id: row.snapshot for row in session.scalars(select(Pursuit))}
        # The HTTP contract keeps its existing payload safeguards.
        with pytest.raises(HTTPException) as limited:
            api._commercial_triage_page(session, 50)
        assert limited.value.status_code == 413

    statements = []

    def record_query(_conn, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(factory.kw["bind"], "before_cursor_execute", record_query)
    try:
        planned = worker.planning_cards()
    finally:
        event.remove(factory.kw["bind"], "before_cursor_execute", record_query)
    assert [card["id"] for card in planned] == [str(need_id)]
    assert not any(
        "pursuit_call_notes" in query or "pursuits.snapshot" in query for query in statements
    )
    with factory.begin() as session:
        created = schedule_questions(session, planned, grouped=True, now=now)
        assert len(created) == 1
        assert created[0].need_id == need_id
        assert created[0].question
    with factory() as session:
        retained_questions = {
            row.id: row for row in session.scalars(select(PursuitResearchQuestion))
        }
        assert prior_questions.keys() <= retained_questions.keys()
        assert len(retained_questions) == len(prior_questions) + 1
        for identity, receipt in prior_questions.items():
            assert retained_questions[identity].receipt == receipt
            assert retained_questions[identity].status == "UNRESOLVED"
        assert {row.id: row.note for row in session.scalars(select(PursuitCallNote))} == prior_notes
        retained_pursuits = {row.id: row for row in session.scalars(select(Pursuit))}
        assert retained_pursuits.keys() == prior_snapshots.keys()
        for row in retained_pursuits.values():
            original = prior_snapshots[row.id]
            if row.id != pursuit_id:
                assert row.snapshot == original
            else:
                for key, value in original.items():
                    assert row.snapshot[key] == value
        assert session.scalar(select(func.count()).select_from(Project)) == 1
        assert session.scalar(select(func.count()).select_from(Evidence)) == 1
        assert session.get(PowerNeed, need_id).tier == "Signal"


@pytest.mark.parametrize("entrypoint", ["shortlist", "fallback"])
def test_oversized_current_group_is_isolated_while_valid_group_schedules(
    planner_runtime, monkeypatch, caplog, entrypoint
):
    factory, api, worker, ids, now = planner_runtime
    need_id, project_id, pursuit_id, evidence_id, observation_id = ids
    with factory.begin() as session:
        source = session.get(Evidence, evidence_id)
        session.add_all(
            Evidence(
                observation_id=observation_id,
                content_hash=hashlib.sha256(f"retained-version-{index}".encode()).hexdigest(),
                title=source.title,
                abstract=source.abstract,
                url=source.url,
                extraction_location="Synthetic historical source version",
            )
            for index in range(api._MAX_COMMERCIAL_CARD_EVIDENCE_ROWS)
        )
        original_project = session.get(Project, project_id)
        original_interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == observation_id)
        )
        other_project = Project(
            source_id=original_project.source_id,
            external_id="2026-900002 EP",
            identity_key="austin-building-permits:2026-900002 EP",
            name="Synthetic separate valid site",
            location="813 CLAYTON LN, Austin, TX",
            asset_type="data_center",
            region_status="ELIGIBLE",
        )
        session.add(other_project)
        session.flush()
        valid_need = PowerNeed(
            id=UUID(int=(1 << 128) - 1),
            project_id=other_project.id,
            activity_key="electrical-construction",
            tier="Signal",
            rationale="Supported separate work scope; missing load and supply facts.",
            supply="Unknown",
        )
        semantic_hash = hashlib.sha256(b"synthetic-valid-site-observation").hexdigest()
        content_hash = hashlib.sha256(b"synthetic-valid-site-source").hexdigest()
        observation = Observation(
            source_id=other_project.source_id,
            external_id=other_project.external_id,
            title="Synthetic separate valid site electrical building permit",
            abstract=source.abstract,
            content_hash=semantic_hash,
            published_at=now.date(),
            url="https://abc.austintexas.gov/permit/2026-900002",
        )
        session.add_all([valid_need, observation])
        session.flush()
        evidence = Evidence(
            observation_id=observation.id,
            title=observation.title,
            abstract=observation.abstract,
            content_hash=content_hash,
            published_at=observation.published_at,
            url=observation.url,
            extraction_location="Synthetic distinct official project record",
        )
        session.add(evidence)
        session.flush()
        session.add_all(
            [
                NeedObservation(need_id=valid_need.id, observation_id=observation.id),
                Interpretation(
                    observation_id=observation.id,
                    content_hash=semantic_hash,
                    evaluator_version="synthetic-planner-regression",
                    status="accepted",
                    assessment={
                        **original_interpretation.assessment,
                        "semantic_hash": semantic_hash,
                        "evidence_hash": content_hash,
                        "evidence": {"id": str(evidence.id), "url": evidence.url},
                        "project_identity_key": other_project.identity_key,
                        "subject": other_project.name,
                        "location": other_project.location,
                    },
                ),
            ]
        )
        valid_id = valid_need.id
    with factory() as session:
        # HTTP still fails closed rather than return a partial work group.
        with pytest.raises(HTTPException) as limited:
            api._commercial_triage_page(session, 50)
        assert limited.value.status_code == 413
        assert limited.value.detail["resource"] == "evidence_rows"
    if entrypoint == "fallback":
        # Exercise the real grouped evaluation beyond the initial shortlist;
        # it must not reopen an unguarded all-evidence fallback.
        monkeypatch.setattr(api, "_commercial_triage_cards", lambda *_args: [])
    planned = worker.planning_cards()
    assert [card["id"] for card in planned] == [str(valid_id)]
    assert "resource=evidence_rows count=501 max=500" in caplog.text
    with factory.begin() as session:
        scheduled = schedule_questions(session, planned, grouped=True, now=now)
        assert len(scheduled) == 1
        assert scheduled[0].need_id == valid_id
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Evidence)) == 502
        assert session.scalar(select(func.count()).select_from(Project)) == 2
        assert (
            session.scalar(
                select(func.count())
                .select_from(PursuitResearchQuestion)
                .where(PursuitResearchQuestion.need_id == need_id)
            )
            == 0
        )
        assert session.get(PowerNeed, need_id).tier == "Signal"
        assert session.get(PowerNeed, need_id).supply == "Unknown"
        assert session.get(Pursuit, pursuit_id).snapshot == {
            "retained_archive_marker": "preserve historical receipt"
        }
