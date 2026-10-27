"""Disposable PostgreSQL checks for source-version fencing and finite well jobs."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, select

from gridlens.intelligence import rrc_well_research as research
from gridlens.persistence.models import (
    Evidence,
    Interpretation,
    Job,
    Observation,
    PowerNeed,
    Project,
    Source,
)
from gridlens.settings import settings

pytest_plugins = ["test_saved_browse"]


def seed(factory, count=1):
    ids = []
    with factory.begin() as session:
        session.add(
            Source(
                id=research.SOURCE,
                publisher="RRC",
                endpoint="https://mft.rrc.texas.gov/",
                family="permits",
                geography="Texas",
                industries=["oil and gas"],
                retrieval_method="rrc-drilling",
                enabled=True,
                registry_enabled=True,
                health={},
            )
        )
        session.flush()
        for index in range(count):
            pid, oid = uuid4(), uuid4()
            fingerprint = str(index + 1).zfill(64)
            key = f"{research.SOURCE}:{index}"
            session.add(
                Project(
                    id=pid,
                    identity_key=key,
                    name="Well record",
                    location="Martin County, TX",
                    source_id=research.SOURCE,
                    external_id=str(index),
                    asset_type="upstream_well",
                )
            )
            session.add(
                Observation(
                    id=oid,
                    source_id=research.SOURCE,
                    external_id=str(index),
                    title="Permit",
                    abstract="Retained native source",
                    content_hash=fingerprint,
                    url="https://mft.rrc.texas.gov/",
                )
            )
            session.flush()
            session.add(
                Evidence(
                    observation_id=oid,
                    content_hash=fingerprint,
                    title="Permit",
                    abstract="Retained native source",
                    url="https://mft.rrc.texas.gov/",
                )
            )
            session.add(
                Interpretation(
                    observation_id=oid,
                    content_hash=fingerprint,
                    status="accepted",
                    assessment={"semantic_hash": fingerprint, "project_identity_key": key},
                )
            )
            session.add(
                PowerNeed(
                    project_id=pid,
                    activity_key="drilling",
                    tier="Signal",
                    active=True,
                    rationale="Need unconfirmed",
                    supply="Unknown",
                )
            )
            ids.append((pid, oid))
    return ids


def test_retained_official_identity_is_immutable_idempotent_and_native_version_fenced(saved_db):
    [(pid, oid)] = seed(saved_db)
    facts = {
        "source": "texas-rrc-w1-detail",
        "identity_validated": True,
        "content_hash": "a" * 64,
        "source_url": "https://webapps2.rrc.texas.gov/EWA/detail",
        "asset_identity": {"kind": "us_well_api", "value": "4231747395"},
        "events": [],
    }
    with saved_db.begin() as session:
        p, o = session.get(Project, pid), session.get(Observation, oid)
        first = research.retain_rrc_result(session, p, o, facts)
        second = research.retain_rrc_result(session, p, o, facts)
        assert first == second
        assert session.scalar(select(func.count()).select_from(Evidence)) == 2
        projected = research.verified_rrc_metadata(session, {pid})[str(pid)]
        assert projected["asset_identity"]["value"] == "4231747395"
        assert projected["evidence_refs"] == [first["evidence_id"]]
    with saved_db.begin() as session:
        o = session.get(Observation, oid)
        o.content_hash = "b" * 64
    with saved_db() as session:
        assert research.verified_rrc_metadata(session, {pid}) == {}
        assert session.scalar(select(func.count()).select_from(Evidence)) == 2


def test_planner_has_concurrency_daily_and_version_cooldown_bounds(saved_db):
    seed(saved_db, count=5)
    with saved_db.begin() as session:
        assert research.plan_rrc_well_jobs(session) == 2
        session.flush()
        assert research.plan_rrc_well_jobs(session) == 0
        jobs = session.scalars(select(Job).where(Job.kind == research.KIND)).all()
        for job in jobs:
            job.status = "succeeded"
        session.flush()
        assert research.plan_rrc_well_jobs(session) == 2
    with saved_db.begin() as session:
        for job in session.scalars(select(Job)):
            job.status = "succeeded"
        session.add_all(
            [
                Job(
                    source_id=research.SOURCE,
                    kind=research.KIND,
                    status="succeeded",
                    created_at=datetime.now(UTC),
                    checkpoint="{}",
                )
                for _ in range(24)
            ]
        )
        session.flush()
        assert research.plan_rrc_well_jobs(session) == 0
        tomorrow = datetime.now(UTC) + timedelta(days=1)
        assert research.plan_rrc_well_jobs(session, now=tomorrow) == 1


def test_disabling_source_or_feature_after_planning_prevents_acquisition(saved_db, monkeypatch):
    [(pid, _oid)] = seed(saved_db)
    import gridlens.ingestion.adapters.rrc_well_lifecycle as adapter

    monkeypatch.setattr(research, "SessionLocal", saved_db)
    monkeypatch.setattr(
        adapter,
        "retrieve_w1_detail",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("network")),
    )
    for feature_enabled, source_enabled in [(False, True), (True, False)]:
        monkeypatch.setattr(settings, "rrc_well_research_enabled", feature_enabled)
        with saved_db.begin() as session:
            session.get(Source, research.SOURCE).enabled = source_enabled
            job = Job(
                source_id=research.SOURCE,
                kind=research.KIND,
                target_id=pid,
                status="running",
                lease_owner="fixture",
                fence=1,
                lease_until=datetime.now(UTC) + timedelta(minutes=5),
                checkpoint="{}",
            )
            session.add(job)
            session.flush()
            job_id = job.id
        research.process_rrc_well_job(job_id, "fixture", 1)
        with saved_db() as session:
            job = session.get(Job, job_id)
            assert job.status == "succeeded"
            assert json.loads(job.checkpoint)["acquisition_performed"] is False


def test_publisher_policy_redirect_stops_retries_and_defers_other_queued_research(
    saved_db, monkeypatch
):
    import gridlens.ingestion.adapters.rrc_drilling as native
    import gridlens.ingestion.adapters.rrc_well_lifecycle as adapter

    ids = seed(saved_db, count=3)
    monkeypatch.setattr(research, "SessionLocal", saved_db)
    monkeypatch.setattr(settings, "rrc_well_research_enabled", True)
    monkeypatch.setattr(native, "reconstruct_retained_record", lambda *_a, **_k: {})
    attempts = []

    def restricted(*_args, **_kwargs):
        attempts.append(1)
        raise adapter.RrcAccessRestricted("Publisher policy destination")

    monkeypatch.setattr(adapter, "retrieve_w1_detail", restricted)
    for pid, oid in ids[:2]:
        with saved_db.begin() as session:
            job = Job(
                source_id=research.SOURCE,
                kind=research.KIND,
                target_id=pid,
                status="running",
                lease_owner="fixture",
                fence=1,
                lease_until=datetime.now(UTC) + timedelta(minutes=5),
                created_at=datetime.now(UTC) - timedelta(days=2),
                checkpoint=json.dumps(
                    {
                        "policy": research.POLICY,
                        "native_content_hash": session.get(Observation, oid).content_hash,
                    }
                ),
            )
            session.add(job)
            session.flush()
            job_id = job.id
        research.process_rrc_well_job(job_id, "fixture", 1)
    assert len(attempts) == 1
    with saved_db.begin() as session:
        assert research.plan_rrc_well_jobs(session) == 0
        assert session.scalar(select(func.count()).select_from(Evidence)) == 3
        assert all(
            not project.identity_facts.get("rrc_official_well")
            for project in session.scalars(select(Project))
        )
        statuses = [json.loads(job.checkpoint)["status"] for job in session.scalars(select(Job))]
        assert "access_restricted" in statuses
        assert "disabled_or_access_deferred" in statuses
        assert (
            research.plan_rrc_well_jobs(
                session, now=datetime.now(UTC) + timedelta(days=1, seconds=1)
            )
            == 1
        )
