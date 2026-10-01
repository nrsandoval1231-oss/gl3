from datetime import UTC, datetime, timedelta
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
    Job,
    Project,
    Pursuit,
    PursuitCallNote,
    PursuitDocument,
    PursuitResearchRun,
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
            location="100 ORION LN",
            identity_key="synthetic-orion",
        )
        session.add(project)
        session.flush()
        project_id = project.id
    fact = {
        "description": "New modular Data Center foundation",
        "address": "100 ORION LN",
        "date": "2026-09-15",
        "status": "Active",
        "contractor_company_name": "Orion Electric",
        "contractor_full_name": "Pat Orion",
        "contractor_phone": "5125550100",
    }
    group = {
        "identity_key": "synthetic-work",
        "source_id": "austin-building-permits",
        "site": "100 ORION LN",
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


def execute(factory, service):
    with factory.begin() as session:
        job_id = enqueue(session, "austin-building-permits", kind="pursuit_research")
        session.get(Job, job_id).checkpoint = '{"force": true}'
        job, fence = lease_one(session, "pursuit-test", lease_seconds=600, job_ids=[job_id])
    service.process_research_job(job_id, "pursuit-test", fence)
    return job_id


def test_live_research_contract_conflict_replay_notes_and_failure_persistence(runtime, monkeypatch):
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
    body = {
        "client_id": str(uuid4()),
        "note": "Synthetic validation: no commercial outreach",
        "outcome": "Needs follow-up",
        "next_action": "Resolve work scope",
        "follow_up": "2026-10-02",
    }
    assert (
        client.post(
            f"/api/pursuits/{pursuit_id}/notes",
            json=body,
            headers={"Origin": "https://bad.example"},
        ).status_code
        == 403
    )
    first = client.post(f"/api/pursuits/{pursuit_id}/notes", json=body)
    assert first.status_code == 200
    assert (
        client.post(f"/api/pursuits/{pursuit_id}/notes", json=body).json()["id"]
        == first.json()["id"]
    )
    altered = {**body, "note": "Changed request content"}
    assert client.post(f"/api/pursuits/{pursuit_id}/notes", json=altered).status_code == 409
    execute(factory, service)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Pursuit)) == 1
        assert session.scalar(select(func.count()).select_from(PursuitCallNote)) == 1
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
    assert detail["notes"][0]["outcome"] == "Needs follow-up"
    assert detail["tier"] == "Signal" and detail["conflicts"]


def test_kind_scoped_queue_and_durable_request_budget(runtime, monkeypatch):
    factory, service, _, api, _ = runtime
    with factory.begin() as session:
        ingestion = enqueue(session, "austin-building-permits")
        research = enqueue(session, "austin-building-permits", kind="pursuit_research")
        assert ingestion != research
        assert enqueue(session, "austin-building-permits", kind="pursuit_research") == research
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
        job, fence = lease_one(session, "old", job_ids=[job_id])
        job.lease_until = datetime.now(UTC) - timedelta(seconds=1)
    with factory.begin() as session:
        job, new_fence = lease_one(session, "new", job_ids=[job_id])
        assert new_fence != fence
    with pytest.raises(RuntimeError, match="fence lost"):
        service.process_research_job(job_id, "old", fence)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Pursuit)) == 0


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
        lambda *_args: {"new": 0, "changed": 0, "unchanged": 1, "latest_publication_date": None},
    )
    with factory.begin() as session:
        job_id = enqueue(session, "austin-building-permits")
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
    from gridlens.persistence.models import Evidence, Observation, SignalDecision

    jev = import_module("gridlens.intelligence.signal_adjudication")
    monkeypatch.setenv("TYPESAFE_API_KEY", "synthetic-key")
    monkeypatch.setattr(settings, "pursuits_daily_model_limit", 0)
    monkeypatch.setattr(jev, "deterministic_override", lambda *_args: None)
    group = service.candidates(None)[0]
    record = group["records"][0]
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
        session.add(
            Evidence(
                id=UUID(record["evidence_id"]),
                observation_id=observation.id,
                content_hash="a",
                title=observation.title,
                url=observation.url,
            )
        )

    def call(state, key, on_request=None):
        assert on_request
        on_request()
        raise AssertionError("Budget rejection must happen before a model request")

    monkeypatch.setattr(jev, "_jev_call", call)
    execute(factory, service)
    with factory() as session:
        row = session.scalar(select(Pursuit))
        assert row.research_status == "partial"
        assert any("work is paused" in error for error in row.research_errors)
        assert row.last_researched_at is None
        assert session.scalar(select(func.count()).select_from(SignalDecision)) == 0


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
