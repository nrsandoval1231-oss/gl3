from datetime import UTC, date, datetime, timedelta
from importlib import import_module
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
from gridlens.jobs.queue import enqueue, lease_one
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    Evidence,
    Job,
    LogicalCall,
    Observation,
    PowerNeed,
    Project,
    Pursuit,
    PursuitCallNote,
    PursuitDocument,
    PursuitResearchRun,
    SignalDecision,
    Source,
)
from gridlens.security import token_for
from gridlens.settings import settings


@pytest.fixture
def runtime(monkeypatch):
    target = make_url(settings.test_database_url)
    assert target.database.endswith("_test")
    assert target != make_url(settings.database_url)
    engine = create_engine(settings.test_database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    service = import_module("gridlens.intelligence.pursuits")
    api = import_module("gridlens.api.app")
    public = import_module("gridlens.ingestion.adapters.pursuit_public")
    monkeypatch.setattr(service, "SessionLocal", factory)
    monkeypatch.setattr(api, "SessionLocal", factory)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr(settings, "typesafe_api_key", None)
    with factory.begin() as session:
        session.add(
            Source(
                id="austin-building-permits",
                publisher="Synthetic tests",
                endpoint="https://example.invalid/",
                family="construction-permits",
                geography="Austin",
                industries=[],
                retrieval_method="socrata-permits",
                health={},
            )
        )
        session.flush()
        project = Project(
            source_id="austin-building-permits",
            external_id="2026-100001 EP",
            name="Synthetic Orion",
            location="100 ORION LN, Austin, TX",
            identity_key="synthetic-orion",
        )
        session.add(project)
        session.flush()
        project_id = project.id
    fact = {
        "description": "New modular Data Center foundation",
        "address": "100 ORION LN, Austin, TX",
        "date": "2026-09-15",
        "status": "Active",
        "contractor_company_name": "Orion Electric",
        "contractor_full_name": "Pat Orion",
        "contractor_phone": "5125550100",
    }
    group = {
        "identity_key": "synthetic-work",
        "source_id": "austin-building-permits",
        "site": "100 ORION LN, Austin, TX",
        "projects": [{"id": str(project_id), "name": "Orion"}],
        "facts": [fact],
        "input_hash": "a",
        "records": [
            {
                "observation_id": str(uuid4()),
                "evidence_id": str(uuid4()),
                "external_id": "2026-100001 EP",
                "hash": "a",
                "url": "https://example.invalid/permit",
                "title": "Synthetic exact permit",
                "text": fact["description"],
                "observed_at": "2026-09-30T00:00:00+00:00",
                "published_at": None,
            }
        ],
        "screen": service.screen([fact], "austin-building-permits", datetime.now(UTC).date()),
    }
    monkeypatch.setattr(service, "candidates", lambda _: [group])
    monkeypatch.setattr(service, "enrich_buying_chain", lambda *_a, **_kw: {"candidates": []})

    def retrieve(_id, deadline, on_request):
        on_request()
        return PublicDocument(
            "https://example.invalid/permit",
            "Synthetic fresh permit",
            "New modular Data Center foundation",
            structured=(
                {
                    "permit_number": "2026-100001 EP",
                    "description": fact["description"],
                    "original_address1": fact["address"],
                    "issue_date": fact["date"],
                    "status_current": "Active",
                    "contractor_company_name": fact["contractor_company_name"],
                    "contractor_full_name": fact["contractor_full_name"],
                    "contractor_phone": fact["contractor_phone"],
                },
            ),
        )

    def tabs(_address, deadline, on_request, fetch_limit):
        on_request()
        return [
            PublicDocument(
                "https://example.invalid/state",
                "Synthetic state EV registration",
                "EV charging scope at 100 Orion Lane",
                structured=(
                    {
                        "project_number": "TABS2026000001",
                        "address": "100 ORION LN",
                        "scope": "EV charging",
                        "project_name": "Orion EV",
                        "start": "2026-01-01",
                        "end": "2026-12-31",
                    },
                ),
            )
        ]

    monkeypatch.setattr(public, "retrieve_austin", retrieve)
    monkeypatch.setattr(public, "retrieve_tabs", tabs)
    yield factory, service, public, api, project_id
    Base.metadata.drop_all(engine)
    engine.dispose()


def execute(factory, service, *, source_id="austin-building-permits", force=True):
    with factory.begin() as session:
        existing = session.scalar(
            select(Job)
            .where(
                Job.source_id == source_id,
                Job.kind == "pursuit_research",
                Job.status.in_(["queued", "running"]),
            )
            .limit(1)
        )
        job_id = enqueue(session, source_id, kind="pursuit_research")
        queued = session.get(Job, job_id)
        assert queued is not None
        if existing is None:
            # The server default can be a fraction of a millisecond ahead of
            # this Windows clock. Make only this newly seeded fixture due.
            queued.available_at = datetime.now(UTC) - timedelta(seconds=1)
        if force:
            queued.checkpoint = '{"force": true}'
        leased = lease_one(session, "pursuit-test", lease_seconds=600, job_ids=[job_id])
        assert leased is not None
        job, fence = leased
    service.process_research_job(job_id, "pursuit-test", fence)
    return job_id


def seed_signal_evidence(factory, service, *, decision=None, content_hash="a", policy_version=None):
    group = service.candidates(None)[0]
    record = group["records"][0]
    service_module = import_module("gridlens.intelligence.signal_adjudication")
    with factory.begin() as session:
        observation = Observation(
            id=UUID(record["observation_id"]),
            source_id="austin-building-permits",
            external_id="2026-100001 EP",
            title="Synthetic ambiguous project",
            content_hash="a",
            url=record["url"],
        )
        session.add(observation)
        session.flush()
        evidence = Evidence(
            id=UUID(record["evidence_id"]),
            observation_id=observation.id,
            content_hash="a",
            title=observation.title,
            url=observation.url,
        )
        session.add(evidence)
        if decision is not None:
            session.add(
                SignalDecision(
                    observation_id=observation.id,
                    content_hash=content_hash,
                    policy_version=policy_version or service_module.POLICY_VERSION,
                    decision=decision,
                    source="deterministic" if decision == "HOLD" else "jev",
                    model_version=None if decision == "HOLD" else "jev-1.13.0",
                    dimensions={"status": "synthetic"},
                    reason="Synthetic test-only source-pipeline decision.",
                )
            )


def test_live_research_contract_conflict_and_failure_persistence(runtime, monkeypatch):
    factory, service, public, api, _ = runtime
    execute(factory, service)
    with factory() as session:
        row = session.scalar(select(Pursuit))
        pursuit_id, researched = row.id, row.last_researched_at
        assert row.snapshot["action_status"] == "Verify first"
        assert "EV charging" in row.snapshot["conflicts"][0]
        document_count = session.scalar(select(func.count()).select_from(PursuitDocument))
        assert row.snapshot["people"][0]["purchasing_authority"] == "Unknown"
        assert row.snapshot["tier"] == "Signal"
    client = TestClient(api.app, base_url="https://testserver")
    assert client.get("/api/pursuits").status_code == 401
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    execute(factory, service)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Pursuit)) == 1
        assert session.scalar(select(func.count()).select_from(PursuitCallNote)) == 0
        assert session.scalar(select(func.count()).select_from(PursuitDocument)) == document_count
        row = session.get(Pursuit, pursuit_id)
        before, success = row.snapshot, row.last_researched_at

    def unavailable(*args, **kwargs):
        kwargs["on_request"]()
        raise TimeoutError("Synthetic failure")

    monkeypatch.setattr(public, "retrieve_austin", unavailable)
    monkeypatch.setattr(public, "retrieve_tabs", unavailable)
    execute(factory, service)
    # A new session/client represents restored persistence, no in-memory research cache.
    with factory() as session:
        row = session.get(Pursuit, pursuit_id)
        assert row.snapshot == before
        assert row.last_researched_at == success
        assert row.research_status == "failed"
        assert row.research_errors
        assert row.last_attempt_at >= researched
    restored = TestClient(api.app, base_url="https://testserver")
    restored.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    detail = restored.get(f"/api/pursuits/{pursuit_id}").json()
    assert detail["notes"] == []
    assert detail["tier"] == "Signal" and detail["conflicts"]


def test_kind_scoped_queue_and_durable_request_budget(runtime, monkeypatch):
    factory, service, _, api, _ = runtime
    with factory.begin() as session:
        ingestion = enqueue(session, "austin-building-permits")
        research = enqueue(session, "austin-building-permits", kind="pursuit_research")
        assert ingestion != research
        assert enqueue(session, "austin-building-permits", kind="pursuit_research") == research
        queued_research = session.get(Job, research)
        assert queued_research is not None
        queued_research.available_at = datetime.now(UTC) - timedelta(seconds=1)
    monkeypatch.setattr(settings, "pursuits_daily_fetch_limit", 1)
    execute(factory, service)
    with factory() as session:
        runs = session.scalars(select(PursuitResearchRun)).all()
        assert sum(r.fetch_count for r in runs) == 1
        assert runs[0].status == "partial"
        assert runs[0].errors
        assert session.get(Job, ingestion).status == "queued"
    execute(factory, service)
    with factory() as session:
        assert session.scalar(select(func.sum(PursuitResearchRun.fetch_count))) == 1
        row = session.scalar(select(Pursuit))
        assert row.research_status == "failed"
        assert row.snapshot["conflicts"] == []


def test_stale_worker_cannot_publish_research(runtime):
    factory, service, _, _, _ = runtime
    with factory.begin() as session:
        job_id = enqueue(session, "austin-building-permits", kind="pursuit_research")
        session.get(Job, job_id).available_at = datetime.now(UTC) - timedelta(seconds=1)
        job, fence = lease_one(session, "old", job_ids=[job_id])
        job.lease_until = datetime.now(UTC) - timedelta(seconds=1)
    with factory.begin() as session:
        job, new_fence = lease_one(session, "new", job_ids=[job_id])
        assert new_fence != fence
    with pytest.raises(RuntimeError, match="fence lost"):
        service.process_research_job(job_id, "old", fence)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Pursuit)) == 0


def test_ordinary_refresh_reconciles_saved_dallas_title_and_preserves_history(runtime, monkeypatch):
    factory, service, _, _, project_id = runtime
    from gridlens.domain.pursuits import POLICY_VERSION
    from gridlens.ingestion import adapters

    group = service.candidates(None)[0]
    group["source_id"] = "dallas-monthly-permits"
    group["records"][0]["external_id"] = "COM-NEW-26-000129"
    group["site"] = "2444 FABENS RD, Dallas, TX"
    group["facts"] = [
        {
            **group["facts"][0],
            "address": "2444 FABENS RD, Dallas, TX",
            "lp_business_name": "KEETER INVESTMENTS LLC",
        }
    ]
    group["screen"] = service.screen(group["facts"], group["source_id"], datetime.now(UTC).date())
    group["input_hash"] = service.digest(
        [service.POLICY_VERSION, service.PRESENTATION_POLICY_VERSION, group["records"]]
    )
    monkeypatch.setattr(service, "candidates", lambda _: [group])
    monkeypatch.setattr(
        adapters,
        "retrieve_source",
        lambda _source: [
            {
                "document_number": "COM-NEW-26-000129",
                "abstract": (
                    "row: COM-NEW-26-000129\naddress: 2444 FABENS RD, Dallas, TX\n"
                    "description: New modular Data Center foundation\n"
                    "lp_business_name: KEETER INVESTMENTS LLC\n"
                    "date: 2026-09-15\nstatus: Active"
                ),
                "html_url": "https://example.invalid/dallas/COM-NEW-26-000129",
                "title": "Dallas retained permit row",
                "source_hash": "current-dallas-hash",
                "extraction_location": "official city permit row",
            }
        ],
    )
    legacy_hash = service.digest([POLICY_VERSION, group["records"]])
    assert legacy_hash != group["input_hash"]
    with factory.begin() as session:
        session.add(
            Source(
                id="dallas-monthly-permits",
                publisher="Synthetic Dallas",
                endpoint="https://example.invalid/dallas",
                family="construction-permits",
                geography="Dallas, TX",
                industries=[],
                retrieval_method="city-permits",
                health={},
            )
        )
        row = Pursuit(
            identity_key=group["identity_key"],
            project_id=project_id,
            project_ids=[str(project_id)],
            snapshot={
                "project": "2444 FABENS RD, DALLAS, TX · COM-NEW-26-000129",
                "organization": "Organization unknown",
                "action_status": "Call now",
                "ranking_reasons": [],
                "next_action": "Confirm the work scope.",
                "evidence": [],
                "_input_hash": legacy_hash,
            },
            last_researched_at=datetime.now(UTC),
            last_attempt_at=datetime.now(UTC),
            research_status="succeeded",
        )
        session.add(row)
        project = session.get(Project, project_id)
        assert project is not None
        project.source_id = "dallas-monthly-permits"
        project.external_id = "COM-NEW-26-000129"
        project.location = "2444 FABENS RD, Dallas, TX"
        session.flush()
        pursuit_id = row.id
        note = PursuitCallNote(
            pursuit_id=row.id,
            client_id=uuid4(),
            note="Preserve owner-entered history through title reconciliation.",
            outcome="Needs follow-up",
            next_action="Reconfirm permit scope.",
        )
        document = PursuitDocument(
            pursuit_id=row.id,
            url="https://example.invalid/prior-evidence",
            content_hash="prior-retained-claim",
            source={"title": "Prior retained source claim"},
        )
        session.add_all([note, document])
        session.flush()
        note_id, document_id = note.id, document.id
        assert service.select_batch(session, [group]) == [group]

    execute(factory, service, source_id="dallas-monthly-permits", force=False)
    with factory() as session:
        refreshed = session.get(Pursuit, pursuit_id)
        assert refreshed.snapshot["organization"] == "KEETER INVESTMENTS LLC"
        assert refreshed.snapshot["project"].startswith(
            "KEETER INVESTMENTS LLC · LP Business Name · role unverified"
        )
        assert "role unverified" in refreshed.snapshot["organization_involvement"]
        assert refreshed.snapshot["_input_hash"] == group["input_hash"]
        assert refreshed.research_status == "succeeded"
        assert session.get(PursuitCallNote, note_id) is not None
        assert session.get(PursuitDocument, document_id) is not None
        assert refreshed.project_ids == [str(project_id)]


def test_changed_scope_and_withdrawal_overlay_list_and_detail(runtime, monkeypatch):
    factory, service, _, api, _ = runtime
    execute(factory, service)
    with factory() as session:
        row = session.scalar(select(Pursuit))
        pursuit_id = row.id
    group = service.candidates(None)[0]
    changed = {**group, "screen": {**group["screen"], "scope_priority": 0}}
    monkeypatch.setattr(service, "candidates", lambda _: [changed])
    with factory() as session:
        assert service.list_pursuits(session)["items"] == []
        assert (
            service.list_pursuits(session, include_dropped=True)["items"][0]["action_status"]
            == "Drop"
        )
    client = TestClient(api.app, base_url="https://testserver")
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    assert client.get(f"/api/pursuits/{pursuit_id}").json()["action_status"] == "Drop"
    monkeypatch.setattr(service, "candidates", lambda _: [])
    assert client.get(f"/api/pursuits/{pursuit_id}").json()["action_status"] == "Drop"


def test_all_four_grouped_permit_versions_are_retrieved_before_success(runtime, monkeypatch):
    factory, service, public, _, _ = runtime
    group = service.candidates(None)[0]
    group["records"] = [
        {**group["records"][0], "external_id": "2026-100001 " + trade}
        for trade in ["EP", "BP", "MP", "PP"]
    ]
    group["facts"] *= 4
    requested = []
    original = public.retrieve_austin

    def retrieve(number, **kwargs):
        requested.append(number)
        return original(number, **kwargs)

    monkeypatch.setattr(public, "retrieve_austin", retrieve)
    execute(factory, service)
    assert len(requested) == 4
    with factory() as session:
        row = session.scalar(select(Pursuit))
        assert row.research_status == "succeeded"
        assert len(row.snapshot["evidence"]) == 5
        assert all("2026-12-31" not in text for text in row.snapshot["timing"])
        assert any("2026-12-31" in text for text in row.snapshot["registration_context"])


def test_current_permit_candidates_use_evidence_hash_and_observation_source(runtime, monkeypatch):
    factory, service, _, _, project_id = runtime
    from gridlens.persistence.models import (
        Evidence,
        Interpretation,
        NeedObservation,
        Observation,
        PowerNeed,
    )

    monkeypatch.undo()
    with factory.begin() as session:
        session.add(
            Source(
                id="other-source",
                publisher="Synthetic origin",
                endpoint="https://example.invalid",
                family="news",
                geography="US",
                industries=[],
                retrieval_method="publisher-rss",
                health={},
            )
        )
        session.flush()
        project = session.get(Project, project_id)
        project.source_id = "other-source"
        for source_id, external_id, description in [
            ("austin-building-permits", "2026-100001 EP", "construction power temporary service"),
            (
                "texas-rrc-drilling-permits",
                "0910001",
                "W-1 well permit: Drill; lease ORION SWD, well 1.",
            ),
        ]:
            if not session.get(Source, source_id):
                session.add(
                    Source(
                        id=source_id,
                        publisher="Synthetic permit",
                        endpoint="https://example.invalid",
                        family="construction-permits",
                        geography="Texas",
                        industries=[],
                        retrieval_method="rrc-drilling-permits",
                        health={},
                    )
                )
                session.flush()
            obs = Observation(
                source_id=source_id,
                external_id=external_id,
                title="Synthetic work",
                abstract="site: 100 ORION LN",
                published_at=None,
                url="https://example.invalid/permit",
                content_hash="semantic-" + external_id,
            )
            session.add(obs)
            session.flush()
            ev = Evidence(
                observation_id=obs.id,
                content_hash="raw-" + external_id,
                title="Synthetic work",
                abstract=(
                    f"row: {external_id}\naddress: 100 ORION LN\n"
                    f"description: {description}\ndate: 2026-09-15\nstatus: Active"
                ),
                url=obs.url,
                published_at=None,
                event_date=datetime.now(UTC).date(),
            )
            session.add(ev)
            activity = "construction" if source_id.startswith("austin") else "drilling"
            session.add(
                Interpretation(
                    observation_id=obs.id,
                    content_hash=obs.content_hash,
                    status="accepted",
                    assessment={
                        "decision": "accepted",
                        "semantic_hash": obs.content_hash,
                        "evidence_hash": ev.content_hash,
                        "project_identity_key": project.identity_key,
                        "power_activity": activity,
                    },
                )
            )
            need = PowerNeed(
                project_id=project_id,
                activity_key=activity,
                rationale="Synthetic acceptance",
                admission_basis={},
                tier="Signal",
            )
            session.add(need)
            session.flush()
            session.add(NeedObservation(need_id=need.id, observation_id=obs.id))
    with factory() as session:
        groups = service.candidates(session)
        assert {g["source_id"] for g in groups} == {
            "austin-building-permits",
            "texas-rrc-drilling-permits",
        }
        assert all(g["screen"]["scope_priority"] > 0 for g in groups)
        needs = session.scalars(select(PowerNeed).order_by(PowerNeed.activity_key)).all()
        needs[0].required_mw = "0.2"
        needs[1].required_mw = "0.3"
        session.commit()
        sized = service.candidates(session)
        assert len(sized) == 1
        assert sized[0]["source_id"] == "texas-rrc-drilling-permits"

        needs[0].required_mw = None
        observation = session.scalar(
            select(Observation).where(Observation.source_id == "austin-building-permits")
        )
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == observation.id)
        )
        interpretation.assessment = {
            **interpretation.assessment,
            "action": "Generator replacement: 35 kW",
        }
        session.commit()
        assert [g["source_id"] for g in service.candidates(session)] == [
            "texas-rrc-drilling-permits"
        ]

        needs[0].required_mw = "5000"
        needs[1].required_mw = None
        session.commit()
        retained = service.candidates(session)
        assert {g["source_id"] for g in retained} == {
            "austin-building-permits",
            "texas-rrc-drilling-permits",
        }
        # This workflow screens Signals; it must never relabel a future
        # qualified Prospect or Lead as a Signal workspace.
        for need in session.scalars(select(PowerNeed)):
            need.tier = "Prospect"
        session.commit()
        assert service.candidates(session) == []


def test_successful_ingestion_queues_same_worker_research_without_source_health_loss(
    runtime, monkeypatch
):
    factory, _, _, _, _ = runtime
    worker = import_module("gridlens.jobs.worker")
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(
        worker,
        "process_job",
        lambda *_args, **_kwargs: {
            "new": 0,
            "changed": 0,
            "unchanged": 1,
            "latest_publication_date": None,
        },
    )
    with factory.begin() as session:
        job_id = enqueue(session, "austin-building-permits")
        queued = session.get(Job, job_id)
        assert queued is not None
        queued.available_at = datetime.now(UTC) - timedelta(seconds=1)
    assert worker.run_one({"austin-building-permits": {}}, job_ids=[job_id])
    with factory() as session:
        assert session.get(Job, job_id).status == "succeeded"
        research = session.scalar(select(Job).where(Job.kind == "pursuit_research"))
        assert research.status == "queued"
        assert (
            session.get(Source, "austin-building-permits").health["status"] == "Checked—No Change"
        )


def test_daily_usage_counts_request_day_even_if_run_crosses_midnight(runtime):
    factory, service, _, _, project_id = runtime
    now = datetime.now(UTC)
    from zoneinfo import ZoneInfo

    today = now.astimezone(ZoneInfo("America/Chicago")).date().isoformat()
    with factory.begin() as session:
        job = Job(source_id="austin-building-permits", kind="pursuit_research")
        pursuit = Pursuit(
            identity_key="usage-test", project_id=project_id, project_ids=[str(project_id)]
        )
        session.add_all([job, pursuit])
        session.flush()
        session.add(
            PursuitResearchRun(
                job_id=job.id,
                pursuit_id=pursuit.id,
                input_hash="a",
                policy_version="test",
                fetch_count=9,
                model_count=4,
                created_at=now - timedelta(days=1),
                snapshot={"_usage": {today: {"fetch": 2, "model": 1}}},
            )
        )
    with factory() as session:
        assert service.daily_usage(session) == 2
        assert service.daily_usage(session, True) == 1


def test_model_budget_pause_survives_adjudicator_without_false_decision(runtime, monkeypatch):
    factory, service, _, _, _ = runtime
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "typesafe_api_key", SecretStr("synthetic-key"))
    monkeypatch.setattr(settings, "pursuits_daily_model_limit", 0)
    seed_signal_evidence(factory, service)
    execute(factory, service)
    with factory() as session:
        row = session.scalar(select(Pursuit))
        assert row.research_status == "partial"
        assert any("Daily or batch research request cap" in error for error in row.research_errors)
        assert any("work is paused" in error for error in row.research_errors)
        assert row.last_researched_at is None
        assert session.scalar(select(func.count()).select_from(SignalDecision)) == 0
        run = session.scalar(select(PursuitResearchRun))
        assert run.model_count == 0
        assert session.scalar(select(func.count()).select_from(LogicalCall)) == 0
        assert (
            session.scalar(
                select(func.count()).select_from(Job).where(Job.kind == "signal_adjudication")
            )
            == 0
        )
        assert any("remains UNKNOWN" in value for value in row.snapshot["unknowns"])


@pytest.mark.parametrize("prior_findings", [False, True])
def test_zero_budget_research_keeps_saved_maps_current_after_every_commit(
    runtime, monkeypatch, prior_findings
):
    from sqlalchemy import event

    from gridlens.intelligence.saved_browse import current_generation, rebuild
    from gridlens.intelligence.worker_browse import install_worker_publication
    from gridlens.persistence.browse_invalidation import install
    from gridlens.persistence.models import BrowseState, Interpretation, NeedObservation

    factory, service, public, api, project_id = runtime
    seed_signal_evidence(factory, service)
    group = service.candidates(None)[0]
    with factory.begin() as session:
        need = PowerNeed(
            project_id=project_id,
            activity_key="construction",
            tier="Signal",
            rationale="Synthetic retained permit",
            supply="Unknown",
            active=True,
        )
        session.add(need)
        session.flush()
        observation_id = UUID(group["records"][0]["observation_id"])
        session.add(NeedObservation(need_id=need.id, observation_id=observation_id))
        session.add(
            Interpretation(
                observation_id=observation_id,
                content_hash="a",
                evaluator_version="fixture",
                status="accepted",
                assessment={
                    "semantic_hash": "a",
                    "evidence_hash": "a",
                    "decision": "accepted",
                    "project_identity_key": "synthetic-orion",
                    "power_activity": "construction",
                    "subject": "Synthetic Orion",
                    "location": "100 ORION LN, Austin, TX",
                },
            )
        )
    if prior_findings:
        execute(factory, service)
        with factory() as session:
            prior = session.scalar(select(Pursuit))
            prior_snapshot, prior_freshness = prior.snapshot, prior.last_researched_at
    with factory.kw["bind"].begin() as connection:
        install(connection)
    assert rebuild(factory)["status"] == "published"
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    monkeypatch.setattr(settings, "pursuits_daily_fetch_limit", 0)
    monkeypatch.setattr(settings, "pursuits_daily_model_limit", 0)
    worker_factory = sessionmaker(factory.kw["bind"], expire_on_commit=False)
    monkeypatch.setattr(service, "SessionLocal", worker_factory)
    install_worker_publication(worker_factory)
    attempts = []

    def no_network(*_args, **kwargs):
        kwargs["on_request"]()
        attempts.append("external request")
        raise AssertionError("Zero budgets must prevent external requests")

    monkeypatch.setattr(public, "retrieve_austin", no_network)
    monkeypatch.setattr(public, "retrieve_tabs", no_network)
    with factory() as session:
        initial_full = session.get(BrowseState, 1).full_revision
        canonical = api.opportunity_projection(session)
        assert len(canonical) == 1
    statuses = []
    client = TestClient(api.app, base_url="https://testserver")
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))

    def verify_after_commit(session):
        if session.in_nested_transaction():
            return
        with factory() as reader:
            state = reader.get(BrowseState, 1)
            assert current_generation(reader).input_revision == state.input_revision
            assert state.full_revision == initial_full
        response = client.get("/api/opportunities/map-window?tier=Signal&decision=ALL")
        statuses.append(response.status_code)
        assert response.status_code == 200

    event.listen(worker_factory, "after_commit", verify_after_commit)
    try:
        job_id = execute(factory, service)
    finally:
        event.remove(worker_factory, "after_commit", verify_after_commit)
        client.close()
    assert len(statuses) >= 4 and not attempts
    with factory() as session:
        assert session.get(Job, job_id).status == "succeeded"
        run = session.scalar(select(PursuitResearchRun).where(PursuitResearchRun.job_id == job_id))
        assert run.status == "failed" and run.fetch_count == run.model_count == 0
        assert any("Daily or batch" in message for message in run.errors)
        row = session.scalar(select(Pursuit))
        if prior_findings:
            assert row.snapshot == prior_snapshot
            assert row.last_researched_at == prior_freshness
        assert api.opportunity_projection(session) == canonical


def test_ingestion_dispatches_full_retained_research_batch_without_saved_map_gap(
    runtime, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from time import monotonic

    from sqlalchemy import event

    from gridlens.intelligence.saved_browse import current_generation, rebuild
    from gridlens.intelligence.worker_browse import install_worker_publication
    from gridlens.persistence.browse_invalidation import install
    from gridlens.persistence.models import BrowseState, Interpretation, NeedObservation

    factory, service, public, api, _unused_project_id = runtime
    # Exercise the real retained candidate selector, not the one-group unit fixture.
    monkeypatch.undo()
    monkeypatch.setattr(api, "SessionLocal", factory)
    monkeypatch.setattr(settings, "saved_browse_enabled", False)
    monkeypatch.setattr(settings, "typesafe_api_key", None)
    monkeypatch.setattr(settings, "pursuits_daily_fetch_limit", 0)
    monkeypatch.setattr(settings, "pursuits_daily_model_limit", 0)
    with factory.begin() as writer:
        writer.add(
            Source(
                id="texas-rrc-drilling-permits",
                publisher="Synthetic RRC",
                endpoint="https://example.test/rrc",
                family="construction-permits",
                geography="Texas",
                industries=[],
                retrieval_method="rrc-drilling-permits",
                health={},
            )
        )
        writer.flush()
        for index in range(12):
            source_id = "austin-building-permits" if index < 8 else "texas-rrc-drilling-permits"
            external = f"2026-{100100 + index} EP" if index < 8 else f"{910100 + index:07d}"
            address = f"{100 + index} SYNTHETIC CAMPUS LN"
            project = Project(
                source_id=source_id,
                external_id=external,
                name=f"Synthetic Campus {index}",
                location=address,
                identity_key=f"synthetic-batch-{index}",
            )
            writer.add(project)
            writer.flush()
            description = (
                "construction power temporary service for Data Center"
                if index < 8
                else f"W-1 well permit: Drill; lease SYNTHETIC SWD {index}, well 1."
            )
            observation = Observation(
                source_id=source_id,
                external_id=external,
                title=project.name,
                abstract=description,
                url=f"https://example.test/batch/{index}",
                content_hash=f"{index:064x}",
            )
            writer.add(observation)
            writer.flush()
            evidence = Evidence(
                observation_id=observation.id,
                content_hash=observation.content_hash,
                title=project.name,
                abstract=(
                    f"row: {external}\naddress: {address}\n"
                    f"description: {description}\ndate: 2026-09-15\nstatus: Active"
                ),
                url=observation.url,
                event_date=datetime.now(UTC).date(),
            )
            writer.add(evidence)
            activity = "construction" if index < 8 else "drilling"
            writer.add(
                Interpretation(
                    observation_id=observation.id,
                    content_hash=observation.content_hash,
                    status="accepted",
                    assessment={
                        "decision": "accepted",
                        "semantic_hash": observation.content_hash,
                        "evidence_hash": evidence.content_hash,
                        "project_identity_key": project.identity_key,
                        "power_activity": activity,
                    },
                )
            )
            need = PowerNeed(
                project_id=project.id,
                activity_key=activity,
                tier="Signal",
                rationale="Synthetic retained batch",
                supply="Unknown",
            )
            writer.add(need)
            writer.flush()
            writer.add(NeedObservation(need_id=need.id, observation_id=observation.id))
    prior = {}
    with factory.begin() as writer:
        groups = service.candidates(writer)
        assert len(groups) == len(service.select_batch(writer, groups)) == 12
        for index, group in enumerate(groups[:6]):
            row = Pursuit(
                identity_key=group["identity_key"],
                project_id=UUID(group["projects"][0]["id"]),
                project_ids=[p["id"] for p in group["projects"]],
                snapshot={"synthetic_retained_marker": index, "evidence": []},
                research_status="partial",
                last_researched_at=datetime.now(UTC) - timedelta(days=2),
            )
            writer.add(row)
            writer.flush()
            prior[row.id] = (row.snapshot, row.last_researched_at)
    with factory.kw["bind"].begin() as connection:
        install(connection)
    assert rebuild(factory)["status"] == "published"
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    worker = import_module("gridlens.jobs.worker")
    worker_factory = sessionmaker(factory.kw["bind"], expire_on_commit=False)
    monkeypatch.setattr(service, "SessionLocal", worker_factory)
    monkeypatch.setattr(worker, "SessionLocal", worker_factory)
    install_worker_publication(worker_factory)
    attempts = []

    def forbidden_request(*_args, **kwargs):
        kwargs["on_request"]()
        attempts.append("external request")
        raise AssertionError("Zero budgets must prevent requests")

    for name in (
        "retrieve_austin",
        "retrieve_tabs",
        "retrieve_rrc_snapshot",
        "retrieve_rrc_archive",
    ):
        monkeypatch.setattr(public, name, forbidden_request)

    def synthetic_ingestion(session, *_args, **_kwargs):
        observation = session.scalar(
            select(Observation).where(Observation.source_id == "austin-building-permits")
        )
        observation.title += " refreshed"
        session.commit()  # Same durable phase boundary used by ingestion.
        return {"new": 0, "changed": 1, "unchanged": 0, "latest_publication_date": None}

    monkeypatch.setattr(worker, "process_job", synthetic_ingestion)
    with factory.begin() as writer:
        ingestion_id = enqueue(writer, "austin-building-permits")
        writer.get(Job, ingestion_id).available_at = datetime.now(UTC) - timedelta(seconds=1)
    with factory() as reader:
        initial_full = reader.get(BrowseState, 1).full_revision
    commits = []

    def committed(session):
        if session.in_nested_transaction():
            return
        with factory() as reader:
            state = reader.get(BrowseState, 1)
            assert current_generation(reader).input_revision == state.input_revision
            assert state.full_revision == initial_full
        commits.append(1)

    event.listen(worker_factory, "after_commit", committed)
    started = monotonic()
    try:
        assert worker.run_one({"austin-building-permits": {}}, job_ids=[ingestion_id])
        with factory() as reader:
            assert reader.get(Job, ingestion_id).status == "succeeded"
            research = reader.scalar(select(Job).where(Job.kind == "pursuit_research"))
            assert research.status == "queued"
            research_id = research.id
        with (
            TestClient(api.app, base_url="https://testserver") as client,
            ThreadPoolExecutor(1) as pool,
        ):
            client.cookies.set(
                "gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300)
            )
            future = pool.submit(
                worker.run_one, {"austin-building-permits": {}}, job_ids=[research_id]
            )
            reads = 0
            while not future.done() or reads < 5:
                assert monotonic() - started < 120
                response = client.get("/api/opportunities/map-window?tier=Signal&decision=ALL")
                assert response.status_code == 200, response.text
                reads += 1
            assert future.result()
    finally:
        event.remove(worker_factory, "after_commit", committed)
    assert not attempts
    assert len(commits) >= 26
    with factory() as reader:
        assert reader.get(Job, research_id).status == "succeeded"
        runs = list(
            reader.scalars(
                select(PursuitResearchRun).where(PursuitResearchRun.job_id == research_id)
            )
        )
        assert len(runs) == 12
        assert all(
            run.fetch_count == run.model_count == 0 and run.status == "failed" for run in runs
        )
        for pursuit_id, (snapshot, freshness) in prior.items():
            row = reader.get(Pursuit, pursuit_id)
            assert row.snapshot == snapshot and row.last_researched_at == freshness
        assert reader.scalar(select(func.count()).select_from(LogicalCall)) == 0
    print(
        f"automatic_research groups=12 commits={len(commits)} "
        f"authenticated_200_reads={reads} elapsed_seconds={monotonic() - started:.3f}"
    )


def test_positive_legacy_model_cap_never_retries_missing_source_decision(runtime, monkeypatch):
    factory, service, _, _, _ = runtime
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "typesafe_api_key", SecretStr("synthetic-key"))
    monkeypatch.setattr(settings, "pursuits_daily_model_limit", 10)
    seed_signal_evidence(factory, service)
    execute(factory, service)
    with factory() as session:
        row = session.scalar(select(Pursuit))
        assert row.research_status == "succeeded"
        assert any("source pipeline" in value for value in row.snapshot["unknowns"]), row.snapshot[
            "unknowns"
        ]
        assert any("made no model request" in value for value in row.snapshot["unknowns"])
        run = session.scalar(select(PursuitResearchRun))
        assert run.model_count == 0
        assert session.scalar(select(func.count()).select_from(LogicalCall)) == 0
        assert session.scalar(select(func.count()).select_from(SignalDecision)) == 0
        assert (
            session.scalar(
                select(func.count()).select_from(Job).where(Job.kind == "signal_adjudication")
            )
            == 0
        )


def test_exact_current_signal_decision_is_reused_without_credentials(runtime):
    factory, service, _, _, _ = runtime
    seed_signal_evidence(factory, service, decision="SHOW")
    execute(factory, service)
    with factory() as session:
        row = session.scalar(select(Pursuit))
        assert not any(
            "Signal evidence adjudication remains" in value for value in row.snapshot["unknowns"]
        )
        run = session.scalar(select(PursuitResearchRun))
        assert run.model_count == 0
        assert session.scalar(select(func.count()).select_from(LogicalCall)) == 0
        assert session.scalar(select(func.count()).select_from(SignalDecision)) == 1
        assert (
            session.scalar(
                select(func.count()).select_from(Job).where(Job.kind == "signal_adjudication")
            )
            == 0
        )


@pytest.mark.parametrize(
    ("stale_hash", "stale_policy"),
    [("different-hash", None), ("a", "signal-display-old-policy")],
)
def test_stale_signal_decision_is_not_reused(runtime, monkeypatch, stale_hash, stale_policy):
    factory, service, _, _, _ = runtime
    monkeypatch.setattr(settings, "pursuits_daily_model_limit", 10)
    seed_signal_evidence(
        factory,
        service,
        decision="SHOW",
        content_hash=stale_hash,
        policy_version=stale_policy,
    )
    execute(factory, service)
    with factory() as session:
        row = session.scalar(select(Pursuit))
        assert any("source pipeline" in value for value in row.snapshot["unknowns"]), (
            row.snapshot["unknowns"],
            row.research_errors,
        )
        assert not any("reused exact current" in value for value in row.snapshot["unknowns"])
        run = session.scalar(select(PursuitResearchRun))
        assert run.model_count == 0
        assert session.scalar(select(func.count()).select_from(LogicalCall)) == 0
        assert session.scalar(select(func.count()).select_from(SignalDecision)) == 1
        assert (
            session.scalar(
                select(func.count()).select_from(Job).where(Job.kind == "signal_adjudication")
            )
            == 0
        )


@pytest.mark.parametrize("single_record", [False, True])
def test_third_historical_archive_is_explicitly_deferred_and_not_fresh(
    runtime, monkeypatch, single_record
):
    factory, service, public, _, _ = runtime
    import json

    original = service.candidates(None)[0]
    filenames = ["daf420.dat.01-31-2026", "daf420.dat.02-28-2026", "daf420.dat.03-31-2026"]
    groups, lookup = [], {}
    for index, filename in enumerate(filenames):
        number = f"091000{index}"
        text = (
            f"row: {number}\nlease: ORION {index} SWD\noperator: Synthetic Operator\n"
            "well: 1\ndate: 2026-04-01\nstatus: Approved\n"
            f"description: W-1 Drill; named ORION {index} SWD\n"
            "Source segment provenance: " + json.dumps([{"filename": filename}])
        )
        facts = {
            "lease": f"ORION {index} SWD",
            "operator": "Synthetic Operator",
            "well": "1",
            "date": "2026-04-01",
            "status": "Approved",
            "description": "W-1 Drill; SWD",
        }
        record = {**original["records"][0], "external_id": number, "text": text}
        group = {
            **original,
            "identity_key": f"archive-work-{index}",
            "source_id": "texas-rrc-drilling-permits",
            "facts": [facts],
            "records": [record],
            "screen": service.screen(
                [facts], "texas-rrc-drilling-permits", datetime.now(UTC).date()
            ),
        }
        groups.append(group)
        lookup[filename] = [
            {
                "document_number": number,
                "abstract": text,
                "html_url": "https://example.invalid/archive",
                "source_hash": str(index),
            }
        ]
    if single_record:
        groups = groups[:1]
        record = groups[0]["records"][0]
        record["text"] = record["text"].split("Source segment provenance: ")[0] + (
            "Source segment provenance: "
            + json.dumps([{"filename": filename} for filename in filenames])
        )
        # Only the third cited archive could establish this exact permit.
        lookup[filenames[0]] = lookup[filenames[1]] = []
    monkeypatch.setattr(service, "candidates", lambda _: groups)

    def daily(deadline, on_request):
        on_request()
        return []

    checked = []

    def archive(filename, deadline, on_request):
        on_request()
        checked.append(filename)
        return lookup[filename]

    monkeypatch.setattr(public, "retrieve_rrc_snapshot", daily)
    monkeypatch.setattr(public, "retrieve_rrc_archive", archive)
    execute(factory, service)
    assert len(checked) == 2
    with factory() as session:
        rows = session.scalars(select(Pursuit)).all()
        deferred = [
            p for p in rows if any("two-file batch cap" in message for message in p.research_errors)
        ]
        assert len(deferred) == 1
        assert any(filenames[2] in message for message in deferred[0].research_errors)
        assert deferred[0].last_researched_at is None
        assert deferred[0].research_status == "failed"
        assert (
            deferred[0].snapshot["evidence"][0]["retrieved_at"]
            == original["records"][0]["observed_at"]
        )


def test_commercial_triage_get_serializes_native_dates_and_persisted_evidence_ids(
    runtime, monkeypatch
):
    factory, _service, _public, api, project_id = runtime
    need_id, evidence_id = uuid4(), uuid4()
    item = {
        "id": need_id,
        "project_id": project_id,
        "name": "Synthetic Austin data center",
        "location": "Dallas, TX",
        "tier": "Signal",
        "activity": "temporary-power",
        "asset_type": "data_center",
        "lifecycle_state": "permitting",
        "lifecycle_timeline": [
            {
                "state": "electrical permit",
                "event_type": "permit_issued",
                "date": "2026-09-30",
                "value_kind": "observed",
                "evidence_url": "https://example.test/current-permit",
                "current": True,
                "published_at": date(2026, 9, 30),
                "event_date_label": "Permit issue date",
            }
        ],
        "required_mw": None,
        "start_window": None,
        "duration": None,
        "supply": "Unknown",
        "conflict_state": "Not assessed",
        "missing_facts": ["buyer or responsible operator"],
        "supported_action": "Temporary service for data center construction",
        "signal_display_decision": "REVIEW",
        "evidence": [
            {
                "id": evidence_id,
                "title": "Current permit evidence",
                "abstract": "Temporary service for data center construction",
                "url": "https://example.test/current-permit",
                "content_hash": "a" * 64,
                "event_date": date(2026, 9, 30),
                "source_id": "austin-building-permits",
                "document_number": "2026-123456 EP",
                "assessment_current": True,
            }
        ],
    }
    monkeypatch.setattr(api, "opportunity_projection", lambda *_args, **_kwargs: [item])
    monkeypatch.setattr(
        api,
        "buying_chain_view",
        lambda *_args, **_kwargs: {"candidates": [], "permit_summaries": []},
    )
    client = TestClient(api.app, base_url="https://testserver")
    assert client.get("/api/commercial/triage").status_code == 401
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    response = client.get("/api/commercial/triage")
    assert response.status_code == 200, response.text
    card = response.json()["items"][0]
    assert card["facts"][0]["evidence_id"] == str(evidence_id)
    assert card["facts"][0]["date"] == "2026-09-30"
    assert card["sources"][0]["evidence_id"] != "None"
    assert card["lifecycle_timeline"][0]["current"] is True
    assert card["lifecycle_timeline"][0]["evidence_url"] == "https://example.test/current-permit"
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Pursuit)) == 0
