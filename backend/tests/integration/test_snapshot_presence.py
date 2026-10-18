from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

import gridlens.ingestion.service as service
from gridlens.intelligence.snapshot_compare import compare
from gridlens.intelligence.snapshot_presence import (
    ABSENT,
    RETURNED,
    absent_need_ids,
    reconcile_snapshot,
)
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    ChangeEvent,
    Evidence,
    Job,
    LogicalCallSettlement,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Source,
)
from gridlens.settings import settings

SOURCE = "georgia-air-draft-title-v"


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
    engine = create_engine(settings.test_database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(
            Source(
                id=SOURCE,
                publisher="Georgia EPD",
                endpoint="https://epd.georgia.gov/x",
                family="construction-permits",
                geography="Georgia",
                industries=["data centers"],
                retrieval_method="georgia-air-permits",
                cadence_hours=24,
                health={},
            )
        )
        session.flush()
        needs = {}
        for key in ("a", "b"):
            observation = Observation(
                source_id=SOURCE,
                external_id=key,
                title=f"Filing {key}",
                url=f"https://epd.georgia.gov/{key}",
                content_hash=f"hash-{key}",
            )
            session.add(observation)
            session.flush()
            session.add(
                Evidence(
                    observation_id=observation.id,
                    content_hash=f"hash-{key}",
                    title=f"Filing {key}",
                    url=f"https://epd.georgia.gov/{key}",
                )
            )
            project = Project(
                identity_key=f"{SOURCE}:{key}",
                name=f"Project {key}",
                source_id=SOURCE,
                external_id=key,
            )
            session.add(project)
            session.flush()
            need = PowerNeed(
                project_id=project.id, activity_key="facility-expansion", rationale="r"
            )
            session.add(need)
            session.flush()
            session.add(NeedObservation(need_id=need.id, observation_id=observation.id))
            needs[key] = need.id
        job = Job(
            source_id=SOURCE,
            status="running",
            lease_owner="test",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        job_id = job.id
    yield factory, needs, job_id
    Base.metadata.drop_all(engine)
    engine.dispose()


def kinds(session):
    return [
        (event.kind, event.material)
        for event in session.scalars(select(ChangeEvent).order_by(ChangeEvent.id))
    ]


def test_snapshot_compare_fails_closed_on_missing_identity_or_changed_exposure():
    from gridlens.intelligence.snapshot_compare import REQUIRED_TABLES

    before = {
        "version": 3,
        "tool_version": "intelligence-snapshot-v3",
        "tables": {name: {"count": 0, "digest": "a"} for name in REQUIRED_TABLES},
        "logical_call_exposure": [{"status": "SENT_OUTCOME_UNKNOWN", "count": 1}],
        "migration_head": "0027",
    }
    assert compare(before, before)["result"] == "MATCH"
    after = {
        **before,
        "tables": {**before["tables"], "evidence": {"count": 1, "digest": "b"}},
    }
    assert compare(before, after)["result"] == "MISMATCH"
    missing = {
        "version": 3,
        "tool_version": "intelligence-snapshot-v3",
        "tables": {},
        "logical_call_exposure": before["logical_call_exposure"],
        "migration_head": "UNKNOWN",
    }
    assert compare(before, missing)["result"] == "MISMATCH"


def test_snapshot_covers_retained_text_job_recovery_and_call_intent(db):
    import runpy
    from pathlib import Path

    from gridlens.persistence.models import LogicalCall

    factory, _, job_id = db
    script = Path(__file__).resolve().parents[2] / "scripts" / "intelligence_snapshot.py"
    snapshot = runpy.run_path(str(script))["snapshot"]
    with factory.begin() as session:
        evidence = session.scalars(select(Evidence)).first()
        evidence.abstract = "retained source excerpt"
        session.add(
            LogicalCall(
                fingerprint="f" * 64,
                task_type="extract",
                task_key="need-1",
                evidence_digest="e" * 64,
                context_digest="c" * 64,
                prompt_contract="contract-v1",
                provider="openai",
                model="model-a",
                policy_version="policy-v1",
                source_id=SOURCE,
                lease_authority="job",
                job_id=job_id,
                status="NOT_SENT",
                estimated_cost_usd=0,
                max_cost_usd=1,
                actual_cost_usd=None,
                result_payload={"safe": "persisted result context"},
                budget_scopes=[],
            )
        )
        session.flush()
        call = session.scalars(select(LogicalCall)).one()
        session.add(
            LogicalCallSettlement(
                call_id=call.id,
                actor="host-operator",
                receipt_ref="restore-rehearsal-receipt",
                input_tokens=4,
            )
        )
    with factory() as session:
        before = snapshot(session)
        assert before["tables"]["settlements"]["count"] == 1
        evidence = session.scalars(select(Evidence)).first()
        evidence.abstract = "edited retained source excerpt"
        job = session.get(Job, job_id)
        job.checkpoint = "resume-from-here"
        call = session.scalars(select(LogicalCall)).one()
        call.task_key = "different-semantic-intent"
        session.commit()
        after = snapshot(session)
    assert compare(before, after)["result"] == "MISMATCH"
    omitted = {
        **before,
        "tables": {
            key: value for key, value in before["tables"].items() if key != "settlements"
        },
    }
    assert "required_table_metadata_missing" in compare(omitted, before)["issues"]


def test_snapshot_logical_call_exposure_has_stable_status_order(db):
    import runpy
    from pathlib import Path

    from gridlens.persistence.models import LogicalCall

    factory, _, job_id = db
    script = Path(__file__).resolve().parents[2] / "scripts" / "intelligence_snapshot.py"
    snapshot = runpy.run_path(str(script))["snapshot"]
    fields = {
        "task_type": "ordering-test",
        "evidence_digest": "a" * 64,
        "context_digest": "b" * 64,
        "prompt_contract": "v1",
        "provider": "fixture",
        "model": "fixture-model",
        "policy_version": "test-v1",
        "lease_authority": "job",
        "job_id": job_id,
        "fence_token": 0,
        "estimated_cost_usd": 0,
        "max_cost_usd": 1,
        "budget_scopes": [],
    }
    statuses = ["SENT_OUTCOME_UNKNOWN", "COMPLETED", "NOT_SENT"]
    with factory.begin() as session:
        for index, status in enumerate(statuses):
            session.add(
                LogicalCall(
                    fingerprint=str(index).zfill(64),
                    task_key=f"ordering-{index}",
                    status=status,
                    **fields,
                )
            )
    with factory() as session:
        result = snapshot(session)
    assert [row["status"] for row in result["logical_call_exposure"]] == sorted(statuses)


def test_absence_is_recorded_once_and_return_is_recorded(db):
    factory, needs, _ = db
    with factory.begin() as session:
        assert reconcile_snapshot(session, SOURCE, {"a"})["absent_from_snapshot"] == 1
        assert absent_need_ids(session, list(needs.values())) == {needs["b"]}
    with factory.begin() as session:
        # Replaying the same snapshot adds nothing.
        assert reconcile_snapshot(session, SOURCE, {"a"}) == {
            "absent_from_snapshot": 0,
            "returned_to_snapshot": 0,
        }
    with factory.begin() as session:
        assert reconcile_snapshot(session, SOURCE, {"a", "b"})["returned_to_snapshot"] == 1
        assert absent_need_ids(session, list(needs.values())) == set()
        assert kinds(session) == [(ABSENT, True), (RETURNED, True)]
        states = [
            (event.prior_state["listed"], event.new_state["listed"])
            for event in session.scalars(select(ChangeEvent).order_by(ChangeEvent.id))
        ]
        assert states == [(True, False), (False, True)]
    with factory.begin() as session:
        # A second departure is a new, distinct event.
        assert reconcile_snapshot(session, SOURCE, {"a"})["absent_from_snapshot"] == 1
        assert [kind for kind, _ in kinds(session)] == [ABSENT, RETURNED, ABSENT]
        # Evidence, observation and need are retained.
        assert session.get(PowerNeed, needs["b"]).active is True


def test_process_job_reconciles_only_declared_complete_snapshots(db, monkeypatch):
    factory, needs, job_id = db
    seen = []
    monkeypatch.setattr(
        service,
        "retrieve_source",
        lambda *_args: [
            {"document_number": "a"},
            {"document_number": "b", "presence_only": True},
        ],
    )
    monkeypatch.setattr(
        service,
        "process_records",
        lambda _s, _j, _w, _f, _d, records, client=None: seen.append(records)
        or {"new": 0, "changed": 0},
    )
    definition = {"id": SOURCE, "retrieval_method": "georgia-air-permits"}
    with factory() as session:
        service.process_job(session, job_id, "test", 1, definition)
        assert kinds(session) == []
    with factory() as session:
        counts = service.process_job(
            session, job_id, "test", 1, {**definition, "snapshot_complete": True}
        )
        # Presence-only rows are withheld from processing but still count as listed.
        assert seen[-1] == [{"document_number": "a"}]
        assert counts["absent_from_snapshot"] == 0
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [{"document_number": "a"}])
    with factory() as session:
        counts = service.process_job(
            session, job_id, "test", 1, {**definition, "snapshot_complete": True}
        )
        assert counts["absent_from_snapshot"] == 1 and counts["changed"] == 1
        assert absent_need_ids(session, list(needs.values())) == {needs["b"]}
