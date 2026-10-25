import json
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.buying_chain import _retained_evidence_current_for_project
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    CompanyIdentity,
    CompanyProjectMembership,
    Evidence,
    ExternalImportActivation,
    ExternalImportBatch,
    ExternalImportRow,
    Interpretation,
    Job,
    Observation,
    PlannerState,
    PowerNeed,
    Project,
    Source,
)
from gridlens.settings import settings


@pytest.fixture
def db():
    target, application = make_url(settings.test_database_url), make_url(settings.database_url)
    assert target.database.endswith("_test")
    assert target != application
    engine = create_engine(settings.test_database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(
            Source(
                id="planner-test",
                publisher="Planner tests",
                endpoint="https://planner-test.example",
                family="news",
                geography="US",
                industries=[],
                retrieval_method="test",
                health={},
            )
        )
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


def _project(session, suffix: str, *, company: CompanyIdentity) -> Project:
    url = f"https://planner-test.example/{suffix}"
    observation = Observation(
        source_id="planner-test",
        external_id=suffix,
        title=f"Acme project {suffix}",
        abstract=f"Acme is the owner of an Austin, TX project {suffix}.",
        published_at=date(2026, 10, 1),
        url=url,
        content_hash=f"hash-{suffix}",
    )
    session.add(observation)
    session.flush()
    evidence = Evidence(
        observation_id=observation.id,
        content_hash=observation.content_hash,
        title=observation.title,
        abstract=observation.abstract,
        url=url,
        published_at=observation.published_at,
        observed_at=datetime.now(UTC),
    )
    session.add(evidence)
    project = Project(
        identity_key=f"planner-{suffix}",
        name=f"Acme project {suffix}",
        location="Austin, TX",
        source_id="planner-test",
        external_id=suffix,
        identity_facts={},
    )
    session.add(project)
    session.flush()
    session.add(
        Interpretation(
            observation_id=observation.id,
            content_hash=observation.content_hash,
            evaluator_version="test",
            assessment={
                "project_identity_key": project.identity_key,
                "decision": "accepted",
                "evidence_hash": evidence.content_hash,
                "admission_status": "supplemental",
            },
            status="accepted",
        )
    )
    session.add(
        PowerNeed(
            project_id=project.id,
            activity_key="construction",
            tier="Prospect",
            rationale="Test need",
            required_mw="2-4 MW",
            start_window="2026-Q4",
        )
    )
    session.add(
        CompanyProjectMembership(
            company_identity_id=company.id,
            project_id=project.id,
            role="owner_developer",
            organization_name="Acme",
            source_id="planner-test",
            source_evidence_id=evidence.id,
            source_version_hash=evidence.content_hash,
            decision_basis="typed_source_v1",
            operator_number="000001",
            state="current",
        )
    )
    session.flush()
    project.region_status = "ELIGIBLE"
    assert _retained_evidence_current_for_project(session, project, evidence)
    return project


def _fixture_company(session) -> tuple[CompanyIdentity, list[Project]]:
    company = CompanyIdentity(rrc_operator_number="000001")
    session.add(company)
    session.flush()
    projects = [
        _project(session, "one", company=company),
        _project(session, "two", company=company),
    ]
    return company, projects


def test_company_reuse_changed_inputs_active_dedupe_and_stale_boundary(db, monkeypatch):
    from gridlens.intelligence.company_contact_discovery import (
        JOB_KIND,
        plan_company_contact_jobs,
    )

    with db.begin() as session:
        frozen_now = datetime.now(UTC)

        class FrozenDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return frozen_now if tz else frozen_now.replace(tzinfo=None)

        import gridlens.intelligence.company_contact_discovery as discovery

        monkeypatch.setattr(discovery, "datetime", FrozenDateTime)
        company, projects = _fixture_company(session)
        assert plan_company_contact_jobs(session, limit=10) == 1
        jobs = session.scalars(select(Job).where(Job.kind == JOB_KIND)).all()
        assert len(jobs) == 1
        assert jobs[0].target_id == company.id
        initial_digest = json.loads(jobs[0].checkpoint)["research_digest"]
        assert plan_company_contact_jobs(session, limit=10) == 0  # queued job is deduplicated
        assert len(session.scalars(select(Job).where(Job.kind == JOB_KIND)).all()) == 1

        # A source-backed project/need change invalidates the planner digest now.
        need = session.scalar(select(PowerNeed).where(PowerNeed.project_id == projects[0].id))
        need.duration = "6 months"
        assert plan_company_contact_jobs(session, limit=10) == 1
        jobs = session.scalars(
            select(Job).where(Job.kind == JOB_KIND).order_by(Job.created_at, Job.id)
        ).all()
        assert len(jobs) == 2

        # Successful unchanged research is skipped before the interval, and due at 30d.
        latest = next(
            job
            for job in jobs
            if json.loads(job.checkpoint).get("research_digest") != initial_digest
        )
        checkpoint = json.loads(latest.checkpoint)
        checkpoint.update(status="complete", completed_at=frozen_now.isoformat())
        latest.checkpoint = json.dumps(checkpoint)
        latest.status = "succeeded"
        assert plan_company_contact_jobs(session, limit=10) == 0
        checkpoint["completed_at"] = (frozen_now - timedelta(days=30)).isoformat()
        latest.checkpoint = json.dumps(checkpoint)
        assert plan_company_contact_jobs(session, limit=10) == 1
        assert len(session.scalars(select(Job).where(Job.kind == JOB_KIND)).all()) == 3


def test_refresh_request_fingerprint_is_stable_across_failed_retries(db):
    from gridlens.intelligence.company_contact_discovery import discover_company_contacts

    with db.begin() as session:
        company, _projects = _fixture_company(session)
        generation = str(datetime.now(UTC).date().toordinal() // 30)
        first = discover_company_contacts(session, company.id, refresh_generation=generation)
        job = session.get(Job, first["job_id"])
        first_digest = json.loads(job.checkpoint)["request_digest"]
        job.status = "failed"
        retry = discover_company_contacts(session, company.id, refresh_generation=generation)
        retry_job = session.get(Job, retry["job_id"])
        assert retry["status"] == "queued"
        assert json.loads(retry_job.checkpoint)["request_digest"] == first_digest
        retry_job.status = "failed"
        exhausted = discover_company_contacts(session, company.id, refresh_generation=generation)
        assert exhausted["status"] == "unresolved"
        assert exhausted["reason"] == "retries_exhausted"


def test_planner_candidate_page_is_bounded_and_cursor_advances(db):
    from gridlens.intelligence.company_contact_discovery import plan_company_contact_jobs

    with db.begin() as session:
        for number in range(1, 6):
            company = CompanyIdentity(id=UUID(int=number))
            session.add(company)
            session.flush()
            _project(session, f"page-{number}", company=company)
        sorted_ids = [UUID(int=n) for n in range(1, 6)]

        assert plan_company_contact_jobs(session, limit=1) == 1
        cursor = session.get(PlannerState, "company-contact-discovery-cursor")
        assert cursor is not None and cursor.cursor == str(sorted_ids[3])
        assert plan_company_contact_jobs(session, limit=1) == 1
        assert cursor.cursor == str(sorted_ids[4])


def test_active_import_hints_trigger_research_and_rollback_removes_them(db):
    from gridlens.intelligence.company_contact_discovery import (
        JOB_KIND,
        _known_contact_urls,
        plan_company_contact_jobs,
    )
    from gridlens.intelligence.external_imports import rollback_import

    with db.begin() as session:
        company, projects = _fixture_company(session)
        assert plan_company_contact_jobs(session, limit=10) == 1
        first = session.scalar(select(Job).where(Job.kind == JOB_KIND, Job.target_id == company.id))
        checkpoint = json.loads(first.checkpoint)
        checkpoint.update(status="complete", completed_at=datetime.now(UTC).isoformat())
        first.checkpoint = json.dumps(checkpoint)
        first.status = "succeeded"

        batch = ExternalImportBatch(
            filename="accounts.xlsx",
            content_hash="e" * 64,
            report={},
            metrics={},
            actor="test",
        )
        session.add(batch)
        session.flush()
        row = ExternalImportRow(
            batch_id=batch.id,
            sheet="Accounts",
            row_number=2,
            row_kind="company",
            raw={"Company": "Acme"},
            normalized={
                "company_name": "Acme",
                "domain": "acme-imported.example",
                "email": "person@acme-imported.example",
                "profile_url": "https://linkedin.example/acme",
            },
            errors=[],
            match_status="matched",
            company_match={"status": "matched", "candidate_id": str(company.id)},
            project_match={"status": "unmatched", "candidate_id": None},
        )
        session.add(row)
        session.flush()
        session.add(ExternalImportActivation(row_id=row.id, active=True, changed_by="test"))
        session.flush()

        assert plan_company_contact_jobs(session, limit=10) == 1
        assert "https://acme-imported.example/" in _known_contact_urls(
            session, company.id, projects
        )
        rollback_import(session, batch.id, actor="test")
        assert "https://acme-imported.example/" not in _known_contact_urls(
            session, company.id, projects
        )
        assert plan_company_contact_jobs(session, limit=10) == 0
