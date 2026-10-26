"""Transactional research admission against an isolated PostgreSQL test schema."""

import json
from datetime import UTC, date, datetime, timedelta
from importlib import import_module
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.domain.pursuit_research import fingerprint
from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
from gridlens.ingestion.adapters.socrata_permits import render_record
from gridlens.ingestion.registry import load_registry
from gridlens.ingestion.service import process_records
from gridlens.intelligence.research_evidence import (
    retain_registered_record,
    retain_research_document,
)
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    BuyingChainEvidence,
    BuyingChainRun,
    Evidence,
    Interpretation,
    Job,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Source,
)
from gridlens.settings import settings


@pytest.fixture
def research_db():
    target = make_url(settings.test_database_url)
    app = make_url(settings.database_url)
    assert target.database and (target.database == "test" or target.database.endswith("_test"))
    assert (target.host, target.port, target.database) != (app.host, app.port, app.database)
    schema = "research_test_" + uuid4().hex
    admin = create_engine(settings.test_database_url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        settings.test_database_url, connect_args={"options": f"-csearch_path={schema}"}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    source = next(s for s in load_registry() if s["id"] == "austin-building-permits")
    try:
        with factory.begin() as session:
            session.add(
                Source(**{k: v for k, v in source.items() if k in Source.__table__.columns})
            )
            session.flush()
            job = Job(
                source_id=source["id"],
                status="running",
                lease_owner="research-test",
                fence=1,
                lease_until=datetime.now(UTC) + timedelta(minutes=10),
            )
            session.add(job)
            session.flush()
            job_id = job.id
        yield factory, source, job_id
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def official_record(source, status="Active"):
    return render_record(
        source,
        {
            "permit_number": "RESEARCH-TEST-1",
            "issue_date": "2026-01-01",
            "description": "Construct new data center.",
            "permit_type_desc": "Building Permit",
            "permit_class_mapped": "Commercial",
            "status_current": status,
            "original_address1": "811 Clayton Ln",
            "original_city": "Austin",
            "original_state": "TX",
            "project_id": "123",
            "link": {"url": "https://abc.austintexas.gov/permit/123"},
        },
    )


def test_buying_chain_research_service_reuses_job_and_result_reader_is_authenticated(
    research_db, monkeypatch
):
    from fastapi.testclient import TestClient

    from gridlens.intelligence import buying_chain
    from gridlens.security import token_for

    factory, source, _job_id = research_db
    api = import_module("gridlens.api.app")
    monkeypatch.setattr(api, "SessionLocal", factory)

    def unexpected_retrieval(*_args, **_kwargs):
        raise AssertionError("HTTP retrieval must run only in the worker")

    monkeypatch.setattr(buying_chain, "retrieve", unexpected_retrieval)
    with factory.begin() as session:
        project = Project(
            source_id=source["id"],
            external_id="buying-chain-async-test",
            name="Synthetic Orion Data Center",
            location="Austin, TX",
            identity_key="synthetic-orion-async-test",
        )
        session.add(project)
        session.flush()
        project_id = project.id

    client = TestClient(api.app, base_url="https://testserver")
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    with factory.begin() as session:
        first = buying_chain.enqueue_buying_chain_research(session, project_id, [])
    with factory.begin() as session:
        second = buying_chain.enqueue_buying_chain_research(session, project_id, [])
    assert first.status == second.status == "queued"
    assert first.id == second.id
    fetched = client.get(f"/api/projects/{project_id}/buying-chain")
    assert fetched.status_code == 200
    assert fetched.json()["research_job"]["id"] == str(first.id)
    assert fetched.json()["candidates"] == []


def test_buying_chain_worker_keeps_retained_path_when_public_research_disabled(
    research_db, monkeypatch
):
    from gridlens.intelligence import buying_chain
    from gridlens.jobs import worker

    factory, source, _job_id = research_db
    monkeypatch.setattr(buying_chain, "SessionLocal", factory)
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(worker, "WORKER_ID", "buying-chain-disabled-test")
    monkeypatch.setattr(settings, "buying_chain_public_research_enabled", False)

    def unexpected_retrieval(*_args, **_kwargs):
        raise AssertionError("disabled public research must not retrieve URLs")

    monkeypatch.setattr(buying_chain, "retrieve", unexpected_retrieval)
    with factory.begin() as session:
        project = Project(
            source_id=source["id"],
            external_id="buying-chain-disabled-test",
            name="Synthetic Orion Data Center",
            location="Austin, TX",
            identity_key="synthetic-orion-disabled-test",
        )
        session.add(project)
        session.flush()
        project_id = project.id
        job = buying_chain.enqueue_buying_chain_research(
            session, project_id, ["https://example.com/project-team"]
        )
        job_id = job.id
    assert worker.run_one({}) is True
    with factory() as session:
        completed = session.get(Job, job_id)
        assert completed.status == "succeeded"
        assert json.loads(completed.checkpoint)["detail_status"] == "disabled"
        assert session.scalar(select(func.count()).select_from(BuyingChainRun)) == 1


def test_buying_chain_worker_does_not_hold_project_lock_during_acquisition(
    research_db, monkeypatch
):
    import time
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from gridlens.intelligence import buying_chain
    from gridlens.jobs.queue import lease_one

    factory, source, _job_id = research_db
    monkeypatch.setattr(buying_chain, "SessionLocal", factory)
    monkeypatch.setattr(settings, "buying_chain_public_research_enabled", True)
    entered, release = Event(), Event()
    with factory.begin() as session:
        project = Project(
            source_id=source["id"],
            external_id="buying-chain-concurrent-test",
            name="Synthetic Orion Data Center",
            location="Austin, TX",
            identity_key="synthetic-orion-concurrent-test",
        )
        session.add(project)
        session.flush()
        project_id = project.id
        job = buying_chain.enqueue_buying_chain_research(
            session, project_id, ["https://example.com/project-team"]
        )
        job_id = job.id
    with factory.begin() as session:
        leased, fence = lease_one(session, "buying-chain-concurrent-test")
        assert leased.id == job_id
        lease_expiry = leased.lease_until

    def blocked_retrieval(url, *, deadline=None):
        entered.set()
        assert release.wait(timeout=10)
        return PublicDocument(url, "Synthetic project team", "No supported relationship.")

    monkeypatch.setattr(buying_chain, "retrieve", blocked_retrieval)
    with ThreadPoolExecutor(max_workers=1) as pool:
        result_future = pool.submit(
            buying_chain.run_buying_chain_research,
            job_id,
            "buying-chain-concurrent-test",
            fence,
            deadline=time.monotonic() + 30,
            lease_expiry=lease_expiry,
        )
        assert entered.wait(timeout=5)
        with factory.begin() as session:
            project = session.get(Project, project_id)
            project.location = "Updated project site, Austin, TX"
        release.set()
        result = result_future.result(timeout=10)
    assert result["status"] == "stale"
    with factory() as session:
        completed = session.get(Job, job_id)
        assert json.loads(completed.checkpoint)["status"] == "stale"
        assert session.scalar(select(func.count()).select_from(BuyingChainRun)) == 0
        assert session.scalar(select(func.count()).select_from(BuyingChainEvidence)) == 0


def test_retained_buying_chain_job_reads_and_cites_its_fifth_current_document(
    research_db, monkeypatch
):
    from gridlens.intelligence import buying_chain
    from gridlens.jobs.queue import lease_one

    factory, source, _job_id = research_db
    monkeypatch.setattr(buying_chain, "SessionLocal", factory)
    monkeypatch.setattr(settings, "buying_chain_public_research_enabled", False)
    target_id = None
    with factory.begin() as session:
        project = Project(
            source_id=source["id"],
            external_id="retained-five-document-test",
            name="Synthetic Orion Data Center",
            location="Austin, TX",
            identity_key="synthetic-orion-five-document-test",
        )
        session.add(project)
        session.flush()
        need = PowerNeed(
            project_id=project.id,
            activity_key="construction",
            tier="Signal",
            rationale="Synthetic test need",
            supply="Unknown",
        )
        session.add(need)
        session.flush()
        now = datetime.now(UTC)
        for index in range(5):
            is_target = index == 4
            abstract = (
                "Acme Industrial is the general contractor for Synthetic Orion "
                "Data Center in Austin, TX."
                if is_target
                else f"Synthetic Orion Data Center retained update {index} in Austin, TX."
            )
            observation = Observation(
                source_id=source["id"],
                external_id=f"retained-five-{index}",
                title=f"Retained document {index}",
                url=f"https://example.test/retained-five-{index}",
                abstract=abstract,
                content_hash=f"retained-hash-{index}",
            )
            session.add(observation)
            session.flush()
            evidence = Evidence(
                observation_id=observation.id,
                title=observation.title,
                url=observation.url,
                abstract=abstract,
                content_hash=observation.content_hash,
                observed_at=now - timedelta(days=index),
            )
            session.add(evidence)
            session.add(NeedObservation(observation_id=observation.id, need_id=need.id))
            session.add(
                Interpretation(
                    observation_id=observation.id,
                    content_hash=observation.content_hash,
                    status="accepted",
                    evaluator_version="research-policy-v1",
                    assessment={
                        "decision": "accepted",
                        "evidence_hash": observation.content_hash,
                        "project_identity_key": project.identity_key,
                        "admission_status": "supplemental",
                    },
                )
            )
            session.flush()
            if is_target:
                target_id = evidence.id
        target = session.get(Evidence, target_id)
        job = buying_chain.enqueue_retained_buying_chain_research(
            session, project.id, target.id, target.content_hash
        )
        assert job is not None
        job_id, project_id = job.id, project.id

    with factory.begin() as session:
        leased, fence = lease_one(session, "retained-five-document-test", job_ids=[job_id])
        assert leased is not None
    result = buying_chain.run_buying_chain_research(job_id, "retained-five-document-test", fence)
    assert result["status"] == "partial"
    assert (
        "Named individual project assignment and purchasing authority remain UNKNOWN."
        in result["result"]["unresolved"]
    )
    with factory.begin() as session:
        retained_row = session.scalar(
            select(BuyingChainEvidence).where(BuyingChainEvidence.retained_evidence_id == target_id)
        )
        assert retained_row is not None
        candidates = buying_chain.buying_chain_view(session, project_id)["candidates"]
        assert any(
            candidate["organization"] == "Acme Industrial"
            and any(
                evidence["id"] == retained_row.id
                and evidence["retained_evidence_id"] == str(target_id)
                for evidence in candidate["evidence"]
            )
            for candidate in candidates
        ), candidates
        stale_checkpoint = json.loads(session.get(Job, job_id).checkpoint)
        stale_checkpoint["status"] = "queued"
        # This job must already be due; the server and worker clocks need not align.
        stale_job = Job(
            source_id=source["id"],
            kind=session.get(Job, job_id).kind,
            target_id=project_id,
            checkpoint=json.dumps(stale_checkpoint, separators=(",", ":")),
            status="queued",
            available_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        session.add(stale_job)
        session.flush()
        stale_job_id = stale_job.id

    with factory.begin() as session:
        leased, stale_fence = lease_one(
            session, "retained-stale-target-test", job_ids=[stale_job_id]
        )
        assert leased is not None

    original_plan = buying_chain._public_research_plan
    policy_change_applied = False

    def change_target_policy_after_initial_check(session, *args):
        nonlocal policy_change_applied
        planned = original_plan(session, *args)
        if not policy_change_applied:
            with factory.begin() as policy_session:
                target = policy_session.get(Evidence, target_id)
                interpretation = policy_session.scalar(
                    select(Interpretation).where(
                        Interpretation.observation_id == target.observation_id
                    )
                )
                interpretation.evaluator_version = "research-policy-next"
            policy_change_applied = True
        return planned

    monkeypatch.setattr(
        buying_chain, "_public_research_plan", change_target_policy_after_initial_check
    )
    with factory() as session:
        prior_run_count = session.scalar(select(func.count()).select_from(BuyingChainRun))
    stale_result = buying_chain.run_buying_chain_research(
        stale_job_id, "retained-stale-target-test", stale_fence
    )
    assert policy_change_applied
    assert stale_result["status"] == "stale"
    with factory() as session:
        stale_checkpoint = json.loads(session.get(Job, stale_job_id).checkpoint)
        assert stale_checkpoint["stale_reason"] == "retained_evidence_version_changed"
        assert session.scalar(select(func.count()).select_from(BuyingChainRun)) == prior_run_count
        assert (
            session.scalar(
                select(func.count())
                .select_from(BuyingChainEvidence)
                .where(BuyingChainEvidence.retained_evidence_id == target_id)
            )
            == 1
        )
        target = session.get(Evidence, target_id)
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == target.observation_id)
        )
        interpretation.status = "rejected"
        assert (
            buying_chain.enqueue_retained_buying_chain_research(
                session, project_id, target.id, target.content_hash
            )
            is None
        )


def test_retained_buying_chain_failed_digest_has_one_durable_replacement(research_db):
    from gridlens.intelligence.buying_chain import (
        enqueue_retained_buying_chain_research,
        retained_buying_chain_backfill,
    )

    factory, source, _job_id = research_db
    with factory.begin() as session:
        project = Project(
            source_id=source["id"],
            external_id="retained-retry-test",
            name="Synthetic Retained Retry Project",
            location="Austin, TX",
            identity_key="synthetic-retained-retry-project",
        )
        session.add(project)
        session.flush()
        need = PowerNeed(
            project_id=project.id,
            activity_key="construction",
            tier="Signal",
            rationale="Synthetic retry test need",
            supply="Unknown",
        )
        session.add(need)
        session.flush()
        observation = Observation(
            source_id=source["id"],
            external_id="retained-retry-observation",
            title="Synthetic retained retry evidence",
            url="https://example.test/retained-retry",
            abstract="Synthetic project construction evidence in Austin, TX.",
            content_hash="retained-retry-hash",
        )
        session.add(observation)
        session.flush()
        evidence = Evidence(
            observation_id=observation.id,
            title=observation.title,
            url=observation.url,
            abstract=observation.abstract,
            content_hash=observation.content_hash,
            observed_at=datetime.now(UTC),
        )
        session.add(evidence)
        session.add(NeedObservation(observation_id=observation.id, need_id=need.id))
        session.add(
            Interpretation(
                observation_id=observation.id,
                content_hash=observation.content_hash,
                status="accepted",
                evaluator_version="research-policy-v1",
                assessment={
                    "decision": "accepted",
                    "evidence_hash": observation.content_hash,
                    "project_identity_key": project.identity_key,
                    "admission_status": "supplemental",
                },
            )
        )
        session.flush()

        initial = enqueue_retained_buying_chain_research(
            session, project.id, evidence.id, evidence.content_hash
        )
        assert initial is not None and initial.status == "queued"
        assert (
            enqueue_retained_buying_chain_research(
                session, project.id, evidence.id, evidence.content_hash
            )
            is initial
        )
        initial.status = "failed"
        initial.attempts = 5

        replacement = enqueue_retained_buying_chain_research(
            session, project.id, evidence.id, evidence.content_hash
        )
        assert replacement is not None and replacement.id != initial.id
        assert replacement.status == "queued" and replacement.attempts == 0
        assert retained_buying_chain_backfill(session, limit=1, enqueue=True)["queued_count"] == 1
        replacement.status = "failed"
        replacement.attempts = 5

        exhausted = enqueue_retained_buying_chain_research(
            session, project.id, evidence.id, evidence.content_hash
        )
        assert exhausted is not None and exhausted.status == "failed"
        assert exhausted.id in {initial.id, replacement.id}
        result = retained_buying_chain_backfill(session, limit=1, enqueue=True)
        assert result["queued_count"] == 0
        assert result["candidates"][0]["job_status"] == "failed"


def seed(factory, source, job_id):
    with factory.begin() as session:
        process_records(
            session,
            job_id,
            "research-test",
            1,
            source,
            [official_record(source)],
            commit=False,
            allow_model=False,
        )
        need = session.scalar(select(PowerNeed))
        assert need is not None
        return need.id


@pytest.mark.parametrize("replay", [False, True])
def test_transactional_ingestion_preserves_caller_lease_and_checkpoint(research_db, replay):
    factory, source, job_id = research_db
    if replay:
        seed(factory, source, job_id)
    caller_lease = datetime.now(UTC) + timedelta(seconds=600)
    with factory.begin() as session:
        job = session.get(Job, job_id)
        job.lease_until = caller_lease
        job.checkpoint = "caller-question-checkpoint"
        session.flush()
        result = process_records(
            session,
            job_id,
            "research-test",
            1,
            source,
            [official_record(source)],
            commit=False,
            allow_model=False,
        )
        assert result["unchanged"] == int(replay)
        assert job.lease_until == caller_lease
        assert job.checkpoint == "caller-question-checkpoint"
    with factory.begin() as session:
        job = session.get(Job, job_id)
        assert job.lease_until == caller_lease
        assert job.checkpoint == "caller-question-checkpoint"


def test_official_update_uses_original_observation_preserves_history_and_replays(research_db):
    factory, source, job_id = research_db
    need_id = seed(factory, source, job_id)
    with factory.begin() as session:
        original = session.scalar(select(Evidence))
        assert original is not None
        original_id, original_text = original.id, original.abstract
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        updated = official_record(source, "Completed")
        result = retain_registered_record(
            session,
            project,
            need,
            source,
            updated,
            job_id=job_id,
            worker_id="research-test",
            fence=1,
        )
        assert result["disposition"] == "ACCEPTED"
        assert result["canonical_support_withdrawn"] is True
        assert result["duplicate"] is False
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        result = retain_registered_record(
            session,
            project,
            need,
            source,
            updated,
            job_id=job_id,
            worker_id="research-test",
            fence=1,
        )
        assert result["duplicate"] is True
        assert session.scalar(select(func.count()).select_from(Observation)) == 1
        assert session.scalar(select(func.count()).select_from(Evidence)) == 2
        assert session.get(Evidence, original_id).abstract == original_text
        assert need.tier == "Signal"
        assert not need.active


def test_wrong_target_quarantine_rolls_back_observation_evidence_and_projection(
    research_db, monkeypatch
):
    factory, source, job_id = research_db
    need_id = seed(factory, source, job_id)
    url = "https://contractor.example/project"
    public_source_id = "research-public-" + fingerprint("contractor.example")[:32]
    with factory.begin() as session:
        session.add(
            Source(
                id=public_source_id,
                publisher="contractor.example",
                endpoint="https://contractor.example/",
                family="news",
                geography="test",
                industries=[],
                retrieval_method="publisher-rss",
                enabled=False,
                health={},
            )
        )
        session.flush()
        observation = Observation(
            source_id=public_source_id,
            external_id=fingerprint(url),
            title="old",
            abstract="old claims",
            url=url,
            content_hash="old",
        )
        session.add(observation)
        session.flush()
        observation_id = observation.id
        other = Project(
            identity_key="other",
            name="Other project",
            location="Chicago, IL",
            source_id=source["id"],
            external_id="other",
        )
        session.add(other)
        session.flush()
        other_need = PowerNeed(
            project_id=other.id, activity_key="facility-expansion", rationale="test"
        )
        session.add(other_need)
        session.flush()
        other_need_id, other_id = other_need.id, other.id
    monkeypatch.setattr(
        "gridlens.intelligence.research_evidence.project_document_match",
        lambda *_: (True, "test exact identity"),
    )
    monkeypatch.setattr(
        "gridlens.intelligence.research_evidence._publisher_eligible",
        lambda *_: True,
    )

    def wrong_admission(session, observation, evidence):
        session.add(NeedObservation(observation_id=observation.id, need_id=other_need_id))
        session.get(Project, other_id).name = "must roll back"
        session.flush()

    monkeypatch.setattr(
        "gridlens.intelligence.research_evidence.assess_retained_news", wrong_admission
    )
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        result = retain_research_document(
            session, project, need, PublicDocument(url, "new", "new claims")
        )
        assert result["disposition"] == "QUARANTINED"
        assert result["evidence_id"] is None
    with factory.begin() as session:
        observation = session.get(Observation, observation_id)
        assert observation.title == "old"
        assert observation.abstract == "old claims"
        assert observation.content_hash == "old"
        assert session.get(Project, other_id).name == "Other project"
        assert (
            session.scalar(
                select(func.count())
                .select_from(Evidence)
                .where(Evidence.observation_id == observation_id)
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(NeedObservation)
                .where(NeedObservation.observation_id == observation_id)
            )
            == 0
        )


@pytest.mark.parametrize("assigned", [False, True])
def test_contact_page_admits_only_relationship_and_retained_enrichment_has_no_tier_writes(
    research_db, assigned
):
    from gridlens.intelligence.buying_chain import enrich_buying_chain
    from gridlens.persistence.models import BuyingChainClaim, Interpretation

    factory, source, job_id = research_db
    need_id = seed(factory, source, job_id)
    suffix = " for Orion Data Center at 811 Clayton Ln, Austin, TX" if assigned else ""
    document = PublicDocument(
        "https://acme.com/projects/orion",
        "Acme Orion Data Center project team",
        "Acme is the electrical contractor for Orion Data Center at 811 Clayton Ln, Austin, TX.\n"
        f"Alice Smith is Project Manager at Acme{suffix}.\n"
        "Alice Smith can be reached at +1 (312) 555-0123.",
        datetime.now(UTC).date(),
    )
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        project.name = "Orion Data Center"
        session.flush()
        before = (need.tier, need.required_mw, need.supply, need.active, dict(need.admission_basis))
        result = retain_research_document(session, project, need, document)
        assert result["disposition"] == "ACCEPTED"
        evidence = session.get(Evidence, result["evidence_id"])
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == evidence.observation_id)
        )
        assert interpretation.assessment["admission_status"] == "relationship_supplement"
        assert "power_activity" not in interpretation.assessment
        assert "activity_key" not in interpretation.assessment
        assert "required_mw" not in interpretation.assessment
        attempts = interpretation.attempts
        repeat = retain_research_document(session, project, need, document)
        assert repeat["duplicate"] is True
        assert interpretation.attempts == attempts
        enrich_buying_chain(session, project.id, retained_only=True)
        claims = list(
            session.scalars(
                select(BuyingChainClaim).where(BuyingChainClaim.project_id == project.id)
            )
        )
        people = [claim for claim in claims if claim.person_name == "Alice Smith"]
        assert len(people) == 1
        assert people[0].organization == "Acme"
        assert people[0].organization_relationship == "DIRECT"
        assert people[0].person_project_relationship == ("DIRECT" if assigned else "ROLE_SUPPORTED")
        assert people[0].public_contacts[0]["value"] == "+1 (312) 555-0123"
        assert "authority" in people[0].reason.casefold()
        assert (
            need.tier,
            need.required_mw,
            need.supply,
            need.active,
            dict(need.admission_basis),
        ) == before
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 1


def test_generic_company_contact_page_is_not_project_evidence(research_db):
    factory, source, job_id = research_db
    need_id = seed(factory, source, job_id)
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        result = retain_research_document(
            session,
            project,
            need,
            PublicDocument(
                "https://acme.com/team",
                "Acme team",
                "Acme is an electrical contractor in Austin, TX. "
                "Alice Smith is Project Manager at Acme.",
            ),
        )
        assert result["disposition"] == "QUARANTINED"
        assert result["evidence_id"] is None
        assert session.scalar(select(func.count()).select_from(Observation)) == 1
        assert need.tier == "Signal"


@pytest.mark.parametrize(
    ("url", "extra"),
    [
        ("https://acme.com/projects/orion", "The project was cancelled."),
        ("https://acme.com/projects/orion", "Construction now has adequate supply."),
        ("https://acme.com/projects/orion", "Permanent utility service is energized."),
        ("https://acme.com/projects/orion", "Project notes. " * 80 + "The project was cancelled."),
        ("https://directory.example/orion", "Business directory listing."),
        ("https://directory.example/orion", ""),
        ("https://acme.com/projects/orion", "AI-generated summary of the project."),
    ],
)
def test_relationship_fallback_cannot_admit_adverse_or_untrusted_pages(research_db, url, extra):
    from gridlens.intelligence.buying_chain import enrich_buying_chain
    from gridlens.persistence.models import BuyingChainClaim, Interpretation

    factory, source, job_id = research_db
    need_id = seed(factory, source, job_id)
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        project.name = "Orion Data Center"
        session.flush()
        doc = PublicDocument(
            url,
            "Acme Orion Data Center project team",
            "Acme is the electrical contractor for Orion Data Center "
            "at 811 Clayton Ln, Austin, TX.\n"
            "Alice Smith is Project Manager at Acme for Orion Data Center "
            "at 811 Clayton Ln, Austin, TX.\n"
            "Alice Smith can be reached at +1 (312) 555-0123.\n" + extra,
            datetime.now(UTC).date(),
        )
        result = retain_research_document(session, project, need, doc)
        assert result["disposition"] == "QUARANTINED"
        if result["evidence_id"] is None:
            assert session.scalar(select(func.count()).select_from(Observation)) == 1
            assert need.tier == "Signal"
            return
        evidence = session.get(Evidence, result["evidence_id"])
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == evidence.observation_id)
        )
        assert interpretation.status == "rejected"
        assert interpretation.assessment.get("admission_status") != "relationship_supplement"
        enrich_buying_chain(session, project.id, retained_only=True)
        claims = list(
            session.scalars(
                select(BuyingChainClaim).where(BuyingChainClaim.project_id == project.id)
            )
        )
        assert not any(claim.public_contacts for claim in claims)
        assert need.tier == "Signal"


def test_adverse_update_retracts_prior_relationship_instead_of_reusing_contacts(research_db):
    from dataclasses import replace

    from gridlens.intelligence.buying_chain import enrich_buying_chain

    factory, source, job_id = research_db
    need_id = seed(factory, source, job_id)
    document = PublicDocument(
        "https://acme.com/projects/orion",
        "Acme Orion Data Center project team",
        "Acme is the electrical contractor for Orion Data Center at 811 Clayton Ln, Austin, TX.\n"
        "Alice Smith is Project Manager at Acme for Orion Data Center "
        "at 811 Clayton Ln, Austin, TX.\n"
        "Alice Smith can be reached at +1 (312) 555-0123.",
        datetime.now(UTC).date(),
    )
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        project.name = "Orion Data Center"
        session.flush()
        assert (
            retain_research_document(session, project, need, document)["disposition"] == "ACCEPTED"
        )
        first = enrich_buying_chain(session, project.id, retained_only=True)
        assert first["candidates"]
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        result = retain_research_document(
            session,
            project,
            need,
            replace(document, text=document.text + "\nThe project has been cancelled."),
        )
        assert result["disposition"] == "QUARANTINED"
        current = enrich_buying_chain(session, project.id, retained_only=True)
        assert not current["candidates"]
        assert need.tier == "Signal"


@pytest.mark.parametrize("label", ["AI-generated summary", "SEO directory", "Business directory"])
def test_explicit_weak_source_cannot_bypass_quarantine_with_qualifying_power_claims(
    research_db, monkeypatch, label
):
    from gridlens.domain.news_interpretation import assess_news

    factory, source, job_id = research_db
    need_id = seed(factory, source, job_id)
    title = "Northstar begins construction at the Northstar Mesa data center in Texas"
    summary = (
        "Northstar Mesa data center construction requires 42 MW. "
        "Power supply for Northstar Mesa data center construction is delayed. " + label
    )
    assert assess_news(title, summary).tier == "Prospect"
    monkeypatch.setattr(
        "gridlens.intelligence.research_evidence.assess_retained_news",
        lambda *_: pytest.fail("Weak source must be quarantined before news interpretation"),
    )
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        result = retain_research_document(
            session,
            project,
            need,
            PublicDocument("https://northstar.com/project", title, summary),
        )
        assert result["disposition"] == "QUARANTINED"
        assert result["evidence_id"] is None
        assert session.scalar(select(func.count()).select_from(Observation)) == 1
        assert need.tier == "Signal"


@pytest.mark.parametrize("correction", ["The project was cancelled.", "AI-generated summary."])
def test_full_document_correction_invalidates_prior_same_url_without_rewriting_history(
    research_db, correction
):
    from dataclasses import replace

    from gridlens.intelligence.buying_chain import enrich_buying_chain
    from gridlens.persistence.models import Interpretation

    factory, source, job_id = research_db
    need_id = seed(factory, source, job_id)
    document = PublicDocument(
        "https://acme.com/projects/orion",
        "Acme Orion Data Center project team",
        "Acme is the electrical contractor for Orion Data Center at 811 Clayton Ln, Austin, TX.\n"
        "Alice Smith is Project Manager at Acme for Orion Data Center "
        "at 811 Clayton Ln, Austin, TX.\n"
        "Alice Smith can be reached at +1 (312) 555-0123.\n" + "Project detail. " * 400,
        datetime.now(UTC).date(),
    )
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        project.name = "Orion Data Center"
        session.flush()
        initial = retain_research_document(session, project, need, document)
        assert initial["disposition"] == "ACCEPTED"
        old_evidence = session.get(Evidence, initial["evidence_id"])
        old_id, old_hash, old_text = (
            old_evidence.id,
            old_evidence.content_hash,
            old_evidence.abstract,
        )
        assert enrich_buying_chain(session, project.id, retained_only=True)["candidates"]
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        changed = replace(document, text=document.text + "\n" + correction)
        result = retain_research_document(session, project, need, changed)
        assert result["disposition"] == "QUARANTINED"
        fresh = session.get(Evidence, result["evidence_id"])
        assert fresh.id != old_id
        assert fresh.content_hash != old_hash
        assert correction in fresh.abstract
        assert len(fresh.abstract) <= 4000
        prior = session.get(Evidence, old_id)
        assert prior.abstract == old_text
        assert prior.content_hash == old_hash
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == fresh.observation_id)
        )
        assert interpretation.status == "rejected"
        assert interpretation.content_hash == fresh.content_hash
        assert interpretation.assessment["evidence_hash"] == fresh.content_hash
        assert any(
            item.get("admission_status") == "relationship_supplement"
            for item in interpretation.assessment["previous_decisions"]
        )
        assert not enrich_buying_chain(session, project.id, retained_only=True)["candidates"]
        repeated = retain_research_document(session, project, need, changed)
        assert repeated["disposition"] == "QUARANTINED"
        assert repeated["evidence_id"] == result["evidence_id"]
        assert need.tier == "Signal"


def test_unlabelled_unknown_publisher_cannot_admit_concrete_power_event(research_db, monkeypatch):
    from gridlens.domain.news_interpretation import assess_news

    factory, source, job_id = research_db
    need_id = seed(factory, source, job_id)
    title = "Northstar begins construction at the Northstar Mesa data center in Texas"
    summary = (
        "Northstar Mesa data center construction requires 42 MW. "
        "Power supply for Northstar Mesa data center construction is delayed. "
        "Northstar Mesa data center is at 811 Clayton Ln, Austin, TX."
    )
    assert assess_news(title, summary).tier == "Prospect"
    monkeypatch.setattr(
        "gridlens.intelligence.research_evidence.assess_retained_news",
        lambda *_: pytest.fail("Unreviewed publisher must be gated before canonical admission"),
    )
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        project.name = "Northstar Mesa data center"
        session.flush()
        result = retain_research_document(
            session,
            project,
            need,
            PublicDocument("https://unknown-aggregator.example/event", title, summary),
        )
        assert result["disposition"] == "QUARANTINED"
        assert "publisher" in result["reason"]
        assert result["evidence_id"] is None
        assert session.scalar(select(func.count()).select_from(Evidence)) == 1
        assert need.tier == "Signal"


def _contact_page():
    return PublicDocument(
        "https://acme.com/projects/orion",
        "Acme Orion Data Center project team",
        "Acme is the electrical contractor for Orion Data Center at 811 Clayton Ln, Austin, TX.\n"
        "Alice Smith is Project Manager at Acme for Orion Data Center "
        "at 811 Clayton Ln, Austin, TX.\n"
        "Alice Smith can be reached at +1 (312) 555-0123.",
        datetime.now(UTC).date(),
    )


@pytest.mark.parametrize("state", ["current", "stale", "rejected", "other_need"])
def test_identical_document_across_urls_reuses_only_current_exact_need_evidence(research_db, state):
    from dataclasses import replace

    from gridlens.persistence.models import Interpretation

    factory, source, job_id = research_db
    need_id = seed(factory, source, job_id)
    document = _contact_page()
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        project.name = "Orion Data Center"
        session.flush()
        initial = retain_research_document(session, project, need, document)
        assert initial["disposition"] == "ACCEPTED"
        evidence = session.get(Evidence, initial["evidence_id"])
        if state == "stale":
            session.get(Observation, evidence.observation_id).content_hash = "changed"
        elif state == "rejected":
            session.scalar(
                select(Interpretation).where(
                    Interpretation.observation_id == evidence.observation_id
                )
            ).status = "rejected"
        elif state == "other_need":
            need = PowerNeed(
                project_id=project.id, activity_key="different-activity", rationale="test"
            )
            session.add(need)
            session.flush()
        other_url = "https://acme.com/projects/orion-copy"
        result = retain_research_document(session, project, need, replace(document, url=other_url))
        assert result["url"] == other_url
        if state == "current":
            assert result["duplicate"] is True
            assert result["evidence_id"] == initial["evidence_id"]
            assert result["evidence_url"] == document.url
            assert result["claim_type"] == "project_organization_relationship"
            assert session.scalar(select(func.count()).select_from(Evidence)) == 2
            assert session.scalar(select(func.count()).select_from(Observation)) == 2
        else:
            assert result["duplicate"] is False
            assert result["evidence_id"] != initial["evidence_id"]
        assert session.get(Evidence, initial["evidence_id"]).url == document.url


def test_document_admission_contention_returns_without_waiting_or_duplicate_write(research_db):
    import time

    factory, source, job_id = research_db
    need_id = seed(factory, source, job_id)
    document = _contact_page()
    digest = fingerprint([document.title, document.text, document.published_at])
    with factory.begin() as holder:
        holder.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 30))"),
            {"key": fingerprint([need_id, digest])},
        )
        with factory.begin() as session:
            need = session.get(PowerNeed, need_id)
            project = session.get(Project, need.project_id)
            project.name = "Orion Data Center"
            session.flush()
            started = time.monotonic()
            result = retain_research_document(session, project, need, document)
            assert time.monotonic() - started < 2
            assert result["disposition"] == "UNRESOLVED"
            assert "in progress" in result["reason"]
            assert session.scalar(select(func.count()).select_from(Evidence)) == 1


def test_early_utility_phrase_cannot_hide_late_cancellation_from_normal_admission(research_db):
    from dataclasses import replace

    from gridlens.intelligence.buying_chain import enrich_buying_chain
    from gridlens.persistence.models import Interpretation

    factory, source, job_id = research_db
    need_id = seed(factory, source, job_id)
    document = _contact_page()
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        project.name = "Orion Data Center"
        session.flush()
        assert (
            retain_research_document(session, project, need, document)["disposition"] == "ACCEPTED"
        )
        assert enrich_buying_chain(session, project.id, retained_only=True)["candidates"]
    changed = replace(
        document,
        text=(
            "Utility service plans reviewed. "
            "Acme begins construction at Orion Data Center in Texas.\n"
            + document.text
            + "\n"
            + "Project details. " * 400
            + "The project was cancelled."
        ),
    )
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        result = retain_research_document(session, project, need, changed)
        assert result["disposition"] == "QUARANTINED"
        evidence = session.get(Evidence, result["evidence_id"])
        assert "The project was cancelled." in evidence.abstract
        assert len(evidence.abstract) <= 4000
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == evidence.observation_id)
        )
        assert interpretation.status == "rejected"
        assert interpretation.assessment["admission_status"] == "research_quarantine"
        assert not enrich_buying_chain(session, project.id, retained_only=True)["candidates"]
        assert need.tier == "Signal"


def test_existing_url_correction_is_not_skipped_when_another_url_has_same_content(research_db):
    from dataclasses import replace

    from gridlens.intelligence.buying_chain import enrich_buying_chain
    from gridlens.persistence.models import Interpretation

    factory, source, job_id = research_db
    need_id = seed(factory, source, job_id)
    first = _contact_page()
    second = replace(
        first,
        url="https://acme.com/projects/orion-update",
        text=first.text.replace("Alice Smith", "Bob Jones").replace("555-0123", "555-0199"),
    )
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        project.name = "Orion Data Center"
        session.flush()
        original = retain_research_document(session, project, need, first)
        other = retain_research_document(session, project, need, second)
        assert original["disposition"] == other["disposition"] == "ACCEPTED"
        original_evidence = session.get(Evidence, original["evidence_id"])
        original_id, original_text = original_evidence.id, original_evidence.abstract
        original_observation_id = original_evidence.observation_id
        assert enrich_buying_chain(session, project.id, retained_only=True)["candidates"]
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        correction = retain_research_document(
            session, project, need, replace(second, url=first.url)
        )
        assert correction["disposition"] == "ACCEPTED"
        assert correction["duplicate"] is False
        assert correction["evidence_id"] not in {original["evidence_id"], other["evidence_id"]}
        corrected = session.get(Evidence, correction["evidence_id"])
        assert corrected.observation_id == original_observation_id
        assert corrected.content_hash == session.get(Evidence, other["evidence_id"]).content_hash
        assert corrected.url == first.url
        assert session.get(Evidence, original_id).abstract == original_text
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == original_observation_id)
        )
        assert interpretation.assessment["evidence_hash"] == corrected.content_hash
        assert "Bob Jones" in session.get(Observation, original_observation_id).abstract
        current = enrich_buying_chain(session, project.id, retained_only=True)
        people = [item for item in current["candidates"] if item.get("person_name")]
        assert people
        assert all(item["person_name"] == "Bob Jones" for item in people)
        assert session.scalar(select(func.count()).select_from(Evidence)) == 4
        assert need.tier == "Signal"


@pytest.mark.parametrize("change", ["removed", "moved", "outside_excerpt", "structured"])
def test_known_reviewed_public_url_identity_corrections_retract_old_contacts(
    research_db, monkeypatch, change
):
    from dataclasses import replace

    from gridlens.intelligence.buying_chain import enrich_buying_chain
    from gridlens.persistence.models import Interpretation

    factory, source, job_id = research_db
    need_id = seed(factory, source, job_id)
    # A test-only reviewed publisher keeps publisher eligibility constant so
    # this exercises identity/format rejection, not the unknown-host guard.
    reviewed = [
        *load_registry(),
        {
            "endpoint": "https://acme.com/feed",
            "retrieval_method": "publisher-rss",
            "family": "news",
        },
    ]
    monkeypatch.setattr("gridlens.intelligence.research_evidence.load_registry", lambda: reviewed)
    document = _contact_page()
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        project.name = "Orion Data Center"
        session.flush()
        initial = retain_research_document(session, project, need, document)
        assert initial["disposition"] == "ACCEPTED"
        previous = session.get(Evidence, initial["evidence_id"])
        previous_text = previous.abstract
        assert enrich_buying_chain(session, project.id, retained_only=True)["candidates"]
    if change == "removed":
        updated = replace(document, title="Acme projects", text="Our project portfolio page.")
    elif change == "moved":
        updated = replace(
            document,
            title="Acme Delta Data Center",
            text=(
                "Acme is the electrical contractor for Delta Data Center "
                "at 500 Delta Rd, Dallas, TX."
            ),
        )
    elif change == "outside_excerpt":
        updated = replace(
            document, title="Acme projects", text="Project context. " * 400 + document.text
        )
    else:
        updated = replace(document, text='{"id": "different"}', structured=({"id": "different"},))
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        result = retain_research_document(session, project, need, updated)
        assert result["disposition"] == "QUARANTINED"
        assert result["current_support_invalidated"] is True
        fresh = session.get(Evidence, result["evidence_id"])
        assert fresh.content_hash == fingerprint(
            [updated.title, updated.text, updated.published_at]
        )
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == fresh.observation_id)
        )
        assert interpretation.status == "rejected"
        assert interpretation.assessment["admission_status"] == "research_quarantine"
        assert session.get(Evidence, initial["evidence_id"]).abstract == previous_text
        assert not enrich_buying_chain(session, project.id, retained_only=True)["candidates"]
        assert need.tier == "Signal"


def test_new_unrelated_reviewed_page_has_receipt_only_and_no_database_writes(research_db):
    from gridlens.persistence.models import Interpretation

    factory, source, job_id = research_db
    need_id = seed(factory, source, job_id)
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        tables = [
            Source,
            Observation,
            Evidence,
            Interpretation,
            Project,
            PowerNeed,
            NeedObservation,
        ]
        before = [session.scalar(select(func.count()).select_from(table)) for table in tables]
        result = retain_research_document(
            session,
            project,
            need,
            PublicDocument(
                "https://www.datacenterdynamics.com/en/news/unrelated/",
                "Other project",
                "An unrelated public project in Dallas, Texas.",
            ),
        )
        assert result["disposition"] == "QUARANTINED"
        assert result["evidence_id"] is None
        assert [
            session.scalar(select(func.count()).select_from(table)) for table in tables
        ] == before


def test_public_typed_reports_preserve_tier_and_versioned_conflicts(research_db):
    from dataclasses import replace

    from gridlens.intelligence.project_state import current_research_state

    factory, source, job_id = research_db
    need_id = seed(factory, source, job_id)
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        project.name = "Orion Data Center"
        session.flush()
        document = PublicDocument(
            "https://www.datacenterdynamics.com/en/news/orion-project/",
            "Orion Data Center update",
            "Orion Data Center at 811 Clayton Ln, Austin, TX construction is underway. "
            "Orion Data Center permanent service remains pending.",
            date(2026, 10, 1),
            datetime.now(UTC),
            "public project update",
        )
        receipt = retain_research_document(session, project, need, document)
        assert receipt["disposition"] == "ACCEPTED", receipt["reason"]
        assert receipt["claim_type"] == "project_research_report"
        assert need.tier == "Signal" and need.required_mw is None
        state = current_research_state(session, project.id, need.id)[str(need.id)]
        assert state["phase"]["value"] == "construction_active"
        assert state["permanent_service"]["value"] == "pending"
        replay = retain_research_document(session, project, need, document)
        assert replay["duplicate"] and replay["evidence_id"] == receipt["evidence_id"]
        alias = retain_research_document(
            session, project, need, replace(document, url=document.url + "-alias")
        )
        assert alias["duplicate"] and alias["evidence_id"] == receipt["evidence_id"]
        assert alias["claim_type"] == "project_research_report"
        second = replace(
            document,
            url=document.url + "-second",
            text="Orion Data Center at 811 Clayton Ln, Austin, TX permanent service is energized.",
        )
        assert retain_research_document(session, project, need, second)["disposition"] == "ACCEPTED"
        assert (
            current_research_state(session, project.id)[str(need.id)]["permanent_service"]["status"]
            == "CONFLICT"
        )
        corrected = replace(
            document,
            title="Orion Data Center cancelled",
            text="Orion Data Center at 811 Clayton Ln, Austin, TX project was cancelled.",
        )
        negative = retain_research_document(session, project, need, corrected)
        assert negative["disposition"] == "ACCEPTED", negative
        assert (
            current_research_state(session, project.id)[str(need.id)]["phase"]["value"]
            == "cancelled"
        )
        assert session.get(Evidence, receipt["evidence_id"]).abstract == document.text.strip()


def test_future_publication_does_not_admit_project_claims(research_db):
    from gridlens.intelligence.project_state import current_research_state

    factory, source, job_id = research_db
    need_id = seed(factory, source, job_id)
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        project.name = "Orion Data Center"
        document = PublicDocument(
            "https://www.datacenterdynamics.com/en/news/orion-future-project/",
            "Orion Data Center update",
            "Orion Data Center at 811 Clayton Ln, Austin, TX construction is underway.",
            date(2099, 1, 1),
            datetime.now(UTC),
            "public project update",
        )
        receipt = retain_research_document(session, project, need, document)
        assert receipt["disposition"] == "UNRESOLVED"
        assert receipt["research_claims"] == []
        assert receipt["label"] == "Unknown"
        assert need.tier == "Signal" and need.required_mw is None
        assert current_research_state(session, project.id, need.id) == {}


@pytest.mark.parametrize(
    "native_source",
    ["el-paso-new-commercial-permits"],
)
def test_native_research_refresh_uses_original_canonical_observation(research_db, native_source):
    from gridlens.ingestion.adapters import boston_permits, el_paso_permits

    factory, _, job_id = research_db
    definition = next(s for s in load_registry() if s["id"] == native_source)
    if native_source == "seattle-building-permits":
        raw = {
            "permitnum": "EXACT-1",
            "issueddate": "2026-01-01",
            "description": "Construct new data center.",
            "statuscurrent": "Issued",
            "originaladdress1": "100 Example Avenue",
            "permitclassmapped": "Commercial",
            "permittypemapped": "New Construction",
            "permittypedesc": "Building",
        }
        record = render_record(definition, raw)
    elif native_source == "boston-building-permits":
        record = boston_permits.render_record(
            {
                "_id": 123,
                "permitnumber": "EXACT-1",
                "issued_date": "2026-01-01",
                "description": "Construct new data center.",
                "status": "Open",
                "address": "100 Example Avenue",
                "city": "Boston",
                "state": "MA",
                "worktype": "New Construction",
                "occupancytype": "Commercial",
                "permittypedescr": "Long Form Permit",
            }
        )
    else:
        record = el_paso_permits._row(
            {
                "OBJECTID": 123,
                "B1_ALT_ID": "EXACT-1",
                "ISSUEDATE": 1767225600000,
                "B1_APPL_ST": "Issued",
                "SITEADDR_S": "100 Example Avenue",
                "Descriptio": "Construct new data center.",
                "Record_Typ": "New Construction",
            },
            datetime.now(UTC).date(),
        )
    with factory.begin() as session:
        session.add(
            Source(**{k: v for k, v in definition.items() if k in Source.__table__.columns})
        )
        session.flush()
        session.get(Job, job_id).source_id = native_source
        process_records(
            session,
            job_id,
            "research-test",
            1,
            definition,
            [record],
            commit=False,
            allow_model=False,
        )
        need = session.scalar(select(PowerNeed))
        assert need is not None
        project = session.get(Project, need.project_id)
        initial_observation = session.scalar(select(Observation))
        initial_ids = set(session.scalars(select(Evidence.id)))
        receipt = retain_registered_record(
            session,
            project,
            need,
            definition,
            record,
            job_id=job_id,
            worker_id="research-test",
            fence=1,
        )
        assert receipt["disposition"] == "ACCEPTED", receipt
        assert session.scalar(select(Observation)).id == initial_observation.id
        assert set(session.scalars(select(Evidence.id))) == initial_ids
        assert need.tier == "Signal" and need.required_mw is None
        assert receipt["published_at"] is None
        assert receipt["event_date"] == "2026-01-01"


@pytest.mark.parametrize("source_id", ["seattle-building-permits", "boston-building-permits"])
def test_disabled_out_of_region_native_sources_cannot_enqueue_refresh(research_db, source_id):
    from gridlens.jobs.queue import enqueue

    factory, _source, _job_id = research_db
    definition = next(source for source in load_registry() if source["id"] == source_id)
    assert definition["enabled"] is False
    with factory.begin() as session:
        session.add(
            Source(
                **{
                    **{
                        key: value
                        for key, value in definition.items()
                        if key in Source.__table__.columns
                    },
                    "enabled": False,
                    "registry_enabled": False,
                    "health": {},
                }
            )
        )
        session.flush()
        with pytest.raises(ValueError, match="disabled"):
            enqueue(session, source_id)
        assert (
            session.scalar(select(func.count()).select_from(Job).where(Job.source_id == source_id))
            == 0
        )


def test_fr_record_without_custom_extraction_location_is_quarantined_when_unbound(research_db):
    from gridlens.ingestion.adapters.federal_register import render_record as render_fr

    factory, source, job_id = research_db
    need_id = seed(factory, source, job_id)
    definition = next(s for s in load_registry() if s["id"] == "federal-register-eis")
    record = render_fr(
        {
            "document_number": "2026-0001",
            "title": "Environmental Impact Statement",
            "abstract": "Unbound official source context",
            "publication_date": "2026-01-01",
            "html_url": "https://www.federalregister.gov/documents/2026/01/01/2026-0001/notice",
        }
    )
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        initial_ids = set(session.scalars(select(Evidence.id)))
        receipt = retain_registered_record(
            session,
            project,
            need,
            definition,
            record,
            job_id=job_id,
            worker_id="research-test",
            fence=1,
        )
        assert receipt["disposition"] == "QUARANTINED"
        assert receipt["reason"] == "unbound_stable_record"
        assert receipt["extraction_location"] == "title and abstract"
        assert receipt["published_at"] == "2026-01-01"
        assert set(session.scalars(select(Evidence.id))) == initial_ids
