from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.research import process_research_job
from gridlens.jobs.queue import assert_fence, enqueue_owner_research, lease_one
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    Evidence,
    Interpretation,
    Job,
    NeedObservation,
    Observation,
    Organization,
    PowerNeed,
    Project,
    ProjectRole,
    ResearchEvidence,
    ResearchJob,
    Source,
)
from gridlens.settings import settings


@pytest.fixture
def db():
    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and target.database.endswith("_test")
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
                id="taylor-development-newsflash",
                publisher="City of Taylor",
                endpoint="https://taylortx.gov/m/NewsFlash",
                family="news",
                geography="Taylor, TX",
                industries=["data-centers"],
                retrieval_method="civicplus-newsflash",
                health={},
            )
        )
        session.flush()
        project = Project(
            identity_key="taylor-development-newsflash:2032",
            name="Project Comal - Employment Center Plan",
            location="Taylor, Texas",
            source_id="taylor-development-newsflash",
            external_id="2032",
            asset_type="data-center",
            identity_facts={"source_article_id": "2032"},
        )
        session.add(project)
        session.flush()
        need = PowerNeed(
            project_id=project.id,
            activity_key="facility-expansion",
            tier="Signal",
            rationale="Taylor approved an employment center plan for a data center at 1051 CR 401.",
            supply="Unknown",
            active=True,
        )
        session.add(need)
        session.flush()
        observation = Observation(
            source_id="taylor-development-newsflash",
            external_id="2032",
            title="Project Comal - Employment Center Plan at 1051 CR 401",
            abstract=(
                "On March 26, City Council approved an employment center plan for a "
                "data center at 1051 CR 401."
            ),
            published_at=None,
            url="https://taylortx.gov/m/NewsFlash/Home/Detail/2032",
            content_hash="a" * 64,
        )
        session.add(observation)
        session.flush()
        evidence = Evidence(
            observation_id=observation.id,
            content_hash="c" * 64,
            title=observation.title,
            abstract=observation.abstract,
            url=observation.url,
            published_at=None,
            extraction_location="header/body; category: Development News",
        )
        session.add(evidence)
        session.add(NeedObservation(need_id=need.id, observation_id=observation.id))
        session.add(
            Interpretation(
                observation_id=observation.id,
                content_hash=observation.content_hash,
                evaluator_version="test",
                assessment={
                    "decision": "accepted",
                    "semantic_hash": observation.content_hash,
                    "evidence_hash": evidence.content_hash,
                },
                status="accepted",
            )
        )
        session.flush()
        need_id = need.id
    yield engine, factory, need_id
    Base.metadata.drop_all(engine)
    engine.dispose()


COMAL_PAGE = b"""<!doctype html>
<html><head><title>KDC Project Comal</title></head><body>
<main>
<h1>KDC Project Comal</h1>
<p>KDC Real Estate Development and Investments is proposing to build a data center on
approximately 210 acres at 1051 County Road 401 northeast of Samsung.</p>
<p>Developer KDC seeks an Employment Center Zoning.</p>
</main></body></html>"""


def test_planner_requires_identity_linked_missing_fact_and_is_idempotent(db):
    _, factory, need_id = db
    with factory.begin() as session:
        first = enqueue_owner_research(session, need_id)
        second = enqueue_owner_research(session, need_id)
        assert first == second
        assert session.scalar(select(func.count()).select_from(Job)) == 1
        research = session.get(ResearchJob, first)
        job = session.get(Job, first)
        assert research and job
        assert research.target_fact == "developer"
        assert research.max_sources == research.max_requests == 1
        assert research.max_seconds == 20 and research.max_spend_cents == 0
        assert job.kind == "research" and job.source_id is None
        assert research.source_url == "https://taylortx.gov/1383/KDC-Project-Comal"


def test_official_developer_finding_persists_citation_and_replay_is_exact(db, monkeypatch):
    from fastapi.testclient import TestClient

    import gridlens.api.app as api
    import gridlens.intelligence.research as research_service
    import gridlens.jobs.worker as worker
    from gridlens.security import token_for

    _, factory, need_id = db
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(worker, "WORKER_ID", "research-test-worker")
    monkeypatch.setattr(research_service, "_fetch", lambda _: COMAL_PAGE)
    with factory.begin() as session:
        job_id = enqueue_owner_research(session, need_id)
    assert worker.run_one({})

    with factory() as session:
        research = session.get(ResearchJob, job_id)
        evidence = session.scalars(select(ResearchEvidence)).all()
        roles = session.scalars(select(ProjectRole)).all()
        assert research and research.result["decision"] == "supported"
        assert len(evidence) == len(roles) == 1
        assert evidence[0].source_url == research.source_url
        assert evidence[0].publisher == "City of Taylor, Texas"
        assert "1051 County Road 401" in evidence[0].excerpt
        assert "KDC Real Estate Development and Investments" in evidence[0].excerpt
        assert evidence[0].label == "Reported" and evidence[0].confidence == "High"
        assert roles[0].role == "Developer"
        need = session.get(PowerNeed, need_id)
        assert need and need.tier == "Signal" and need.required_mw is None

    monkeypatch.setattr(api, "SessionLocal", factory)
    client = TestClient(api.app)
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    card = next(
        item
        for item in client.get("/api/opportunities?tier=Signal").json()
        if item["id"] == str(need_id)
    )
    assert card["research_status"] == "Completed"
    assert card["known_organizations"][0]["name"] == "KDC Real Estate Development and Investments"
    assert card["known_organizations"][0]["role"] == "Developer"
    assert card["known_organizations"][0]["evidence_url"] == research.source_url

    # Replaying the completed job does not fetch again or duplicate evidence/role.
    with factory.begin() as session:
        job = session.get(Job, job_id)
        assert job
        job.status = "queued"
        job.available_at = datetime.now(UTC) - timedelta(seconds=1)
    with factory.begin() as session:
        replay, replay_fence = lease_one(session, "research-replay-worker")
        assert replay and replay.id == job_id
    with factory.begin() as session:
        assert process_research_job(
            session,
            job_id,
            "research-replay-worker",
            replay_fence,
            fetch=lambda _: pytest.fail("completed job refetched"),
        ) == {"status": "completed"}
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ResearchEvidence)) == 1
        assert session.scalar(select(func.count()).select_from(ProjectRole)) == 1


def test_unsupported_signal_projects_unknown_and_specific_research_action(db, monkeypatch):
    from fastapi.testclient import TestClient

    import gridlens.api.app as api
    from gridlens.security import token_for

    _, factory, need_id = db
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        assert need
        project = session.get(Project, need.project_id)
        assert project
        project.name = "Project Mustang data center"
        observation = session.scalar(select(Observation))
        assert observation
        observation.external_id = "2079"
    monkeypatch.setattr(api, "SessionLocal", factory)
    client = TestClient(api.app)
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    card = next(
        item
        for item in client.get("/api/opportunities?tier=Signal").json()
        if item["id"] == str(need_id)
    )
    assert card["research_status"] == "Unavailable (UNKNOWN)"
    assert card["research_unavailable_reason"] == (
        "No identity-linked official project record currently supports the developer relationship."
    )
    assert "Verify the developer in an official, project-specific planning" in card[
        "research_next_action"
    ]
    assert "UNKNOWN" in card["research_next_action"]
    assert "Comal" not in card["research_next_action"]
    assert "Comal" not in card["research_unavailable_reason"]
    assert "Run one bounded official-source check" not in card["research_next_action"]


def test_project_role_on_another_need_is_known_with_its_citation(db, monkeypatch):
    from fastapi.testclient import TestClient

    import gridlens.api.app as api
    from gridlens.security import token_for

    _, factory, need_id = db
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        assert need
        sibling = PowerNeed(
            project_id=need.project_id,
            activity_key="backup-power",
            tier="Signal",
            rationale="A separate activity for the same project.",
            supply="Unknown",
            active=True,
        )
        session.add(sibling)
        session.flush()
        job = Job(kind="research", source_id=None, status="succeeded")
        session.add(job)
        session.flush()
        research = ResearchJob(
            job_id=job.id,
            need_id=sibling.id,
            target_fact="developer",
            question="Which organization is the developer?",
            source_url="https://taylortx.gov/1383/KDC-Project-Comal",
            status="completed",
            next_action="Review the cited developer relationship.",
        )
        session.add(research)
        session.flush()
        evidence = ResearchEvidence(
            job_id=job.id,
            source_url=research.source_url,
            publisher="City of Taylor, Texas",
            excerpt="Official record names Example Development as the developer.",
            extraction_location="Project overview",
            content_hash="d" * 64,
            label="Reported",
            basis="Official project page explicitly names the developer.",
            confidence="High",
            relationship="Developer",
        )
        organization = Organization(name="Example Development")
        session.add_all([evidence, organization])
        session.flush()
        session.add(
            ProjectRole(
                project_id=need.project_id,
                need_id=sibling.id,
                organization_id=organization.id,
                role="Developer",
                evidence_id=evidence.id,
                basis=evidence.basis,
                confidence="High",
            )
        )
    monkeypatch.setattr(api, "SessionLocal", factory)
    client = TestClient(api.app)
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    card = next(
        item
        for item in client.get("/api/opportunities?tier=Signal").json()
        if item["id"] == str(need_id)
    )
    assert card["research_status"] == "Known"
    assert card["known_organizations"][0]["name"] == "Example Development"
    assert card["known_organizations"][0]["evidence_url"] == research.source_url
    assert "activity-specific power requirement" in card["research_next_action"]
    assert "developer verification is needed" in card["research_next_action"]
    assert card["research_unavailable_reason"] is None
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ResearchJob)) == 1


def test_recorded_identity_fact_without_role_is_unverified_not_unknown(db, monkeypatch):
    from fastapi.testclient import TestClient

    import gridlens.api.app as api
    from gridlens.security import token_for

    _, factory, need_id = db
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        assert need
        project = session.get(Project, need.project_id)
        assert project
        project.identity_facts = {"developer": "Example Development"}
    monkeypatch.setattr(api, "SessionLocal", factory)
    client = TestClient(api.app)
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    card = next(
        item
        for item in client.get("/api/opportunities?tier=Signal").json()
        if item["id"] == str(need_id)
    )
    assert card["research_status"] == "Recorded (unverified)"
    assert card["research_recorded_identity"] == "Developer: Example Development"
    assert "No cited ProjectRole evidence" in card["research_recorded_evidence_status"]
    assert "retain a citation" in card["research_next_action"]
    assert card["research_unavailable_reason"] is None
    assert card["known_organizations"] == []
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ResearchJob)) == 0


def test_unsupported_relationship_is_retained_as_unknown_without_signal_change(db):
    _, factory, need_id = db
    with factory.begin() as session:
        job_id = enqueue_owner_research(session, need_id)
    with factory.begin() as session:
        job, fence = lease_one(session, "unsupported-worker")
        assert job and job.id == job_id
    unsupported = b"""<html><main><h1>Project Comal</h1>
    <p>City Council reviewed a zoning request at 1051 County Road 401.</p>
    </main></html>"""
    with factory.begin() as session:
        assert process_research_job(
            session, job_id, "unsupported-worker", fence, fetch=lambda _: unsupported
        ) == {"status": "unresolved"}
        job = session.get(Job, job_id)
        assert job
        job.status = "succeeded"
        job.lease_owner = job.lease_until = None
    with factory() as session:
        research = session.get(ResearchJob, job_id)
        need = session.get(PowerNeed, need_id)
        evidence = session.scalar(select(ResearchEvidence))
        assert research and research.unresolved_reason
        assert research.result["decision"] == "unsupported_relationship"
        assert evidence and evidence.relationship is None and evidence.confidence == "Unknown"
        assert session.scalar(select(func.count()).select_from(ProjectRole)) == 0
        assert need and need.active and need.tier == "Signal" and need.required_mw is None
    with factory.begin() as session:
        assert enqueue_owner_research(session, need_id) == job_id
        retried = session.get(ResearchJob, job_id)
        retry_job = session.get(Job, job_id)
        assert retried and retry_job
        assert retried.status == "queued" and retry_job.status == "queued"
        assert retried.history[0]["status"] == "unresolved"
        assert retried.history[0]["result"]["decision"] == "unsupported_relationship"


def test_source_failure_is_durable_and_fence_is_checked(db):
    _, factory, need_id = db
    with factory.begin() as session:
        job_id = enqueue_owner_research(session, need_id)
    with factory.begin() as session:
        job, old_fence = lease_one(session, "dead-worker", lease_seconds=1)
        assert job and job.id == job_id
        job.lease_until = datetime.now(UTC) - timedelta(seconds=1)
    with factory.begin() as session:
        job, fence = lease_one(session, "retry-worker", lease_seconds=60)
        assert job and job.id == job_id and fence == old_fence + 1
    with factory() as stale_session:
        with pytest.raises(RuntimeError, match="fence lost"):
            assert_fence(stale_session, job_id, "dead-worker", old_fence)
    with factory.begin() as session:
        assert process_research_job(
            session,
            job_id,
            "retry-worker",
            fence,
            fetch=lambda _: (_ for _ in ()).throw(TimeoutError()),
        ) == {"status": "unresolved"}
    with factory() as session:
        research = session.get(ResearchJob, job_id)
        need = session.get(PowerNeed, need_id)
        assert research and "TimeoutError" in research.unresolved_reason
        assert research.next_action
        assert need and need.active and need.tier == "Signal"


def test_exhausted_crash_retries_record_unresolved_research(db):
    _, factory, need_id = db
    with factory.begin() as session:
        job_id = enqueue_owner_research(session, need_id)
        job = session.get(Job, job_id)
        assert job
        job.status = "running"
        job.attempts = 5
        job.lease_until = datetime.now(UTC) - timedelta(seconds=1)
    with factory.begin() as session:
        assert lease_one(session, "recovery-worker") is None
    with factory() as session:
        job = session.get(Job, job_id)
        research = session.get(ResearchJob, job_id)
        assert job and job.status == "failed"
        assert research and research.status == "unresolved"
        assert "lease expired" in research.unresolved_reason.casefold()
        assert research.next_action


def test_authenticated_opportunity_projection_shows_specific_research_action(db, monkeypatch):
    from fastapi.testclient import TestClient

    import gridlens.api.app as api
    from gridlens.security import token_for

    _, factory, need_id = db
    monkeypatch.setattr(api, "SessionLocal", factory)
    client = TestClient(api.app)
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    opportunities = client.get("/api/opportunities?tier=Signal")
    assert opportunities.status_code == 200
    signal = next(row for row in opportunities.json() if row["id"] == str(need_id))
    assert signal["research_status"] == "Not queued"
    assert "queues automatically when this accepted Signal is ingested" in signal[
        "research_next_action"
    ]
    response = client.post(
        f"/api/opportunities/{need_id}/research",
        headers={"origin": "http://testserver"},
    )
    assert response.status_code == 200
    assert response.json()["max_sources"] == response.json()["max_requests"] == 1
    assert response.json()["max_spend_cents"] == 0
