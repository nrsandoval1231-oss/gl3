import json
from datetime import UTC, date, datetime
from importlib import import_module
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    Evidence,
    Job,
    LogicalCall,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Pursuit,
    PursuitCallNote,
    Source,
)
from gridlens.security import token_for
from gridlens.settings import settings


@pytest.fixture
def intelligence_api(monkeypatch):
    target = make_url(settings.test_database_url)
    assert target.database.endswith("_test")
    assert target != make_url(settings.database_url)
    engine = __import__("sqlalchemy").create_engine(settings.test_database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    api = import_module("gridlens.api.app")
    monkeypatch.setattr(api, "SessionLocal", factory)
    monkeypatch.setattr(settings, "intelligence_enabled", False)
    monkeypatch.setattr(settings, "intelligence_mode", "disabled")
    with factory.begin() as session:
        source = Source(
            id="austin-building-permits",
            publisher="Synthetic test source",
            endpoint="https://example.test/records",
            family="construction-permits",
            geography="Austin",
            industries=[],
            retrieval_method="test-fixture",
            health={"last_success": datetime.now(UTC).isoformat()},
        )
        session.add(source)
        session.flush()
        project = Project(
            source_id=source.id,
            external_id="synthetic-1",
            name="Synthetic Site",
            location="Austin, TX",
            identity_key="synthetic-site",
        )
        session.add(project)
        session.flush()
        need = PowerNeed(
            project_id=project.id,
            activity_key="electrical-construction",
            tier="Signal",
            rationale="Synthetic test fixture",
            supply="Unknown",
            admission_basis={},
        )
        session.add(need)
        session.flush()
        observation = Observation(
            source_id=source.id,
            external_id="synthetic-1",
            title="Synthetic source evidence",
            abstract="The source says the facility work scope is active.",
            published_at=date(2026, 10, 1),
            url="https://example.test/records/1",
            content_hash="a" * 64,
        )
        session.add(observation)
        session.flush()
        evidence = Evidence(
            observation_id=observation.id,
            content_hash="a" * 64,
            title=observation.title,
            abstract=observation.abstract,
            url=observation.url,
            published_at=observation.published_at,
            extraction_location="title and abstract",
            provenance={},
        )
        session.add(evidence)
        session.flush()
        session.add(NeedObservation(need_id=need.id, observation_id=observation.id))
        pursuit = Pursuit(
            identity_key=f"commercial-need:{need.id}",
            project_id=project.id,
            project_ids=[str(project.id)],
            snapshot={"tier": "Signal", "action_status": "Verify first"},
        )
        session.add(pursuit)
        session.flush()
        job_id = uuid4()
        logical_call_id = uuid4()
        candidate = {
            "field": "temporary_load_mw",
            "value": "2.0",
            "unit": "MW",
            "evidence_id": str(evidence.id),
            "evidence_hash": evidence.content_hash,
            "quote": "The source says the facility work scope is active.",
            "section": "abstract",
            "page": None,
            "span_start": 0,
            "span_end": len("The source says the facility work scope is active."),
            "publisher": source.publisher,
            "published_date": "2026-10-01",
            "support": "direct",
            "status": "candidate",
        }
        checkpoint = {
            "task_type": "GROUNDED_DOSSIER",
            "question_id": "TEMP_LOAD_MW",
            "status": "completed",
            "logical_call_id": str(logical_call_id),
            "payload": {
                "need": {"need_id": str(need.id)},
                "evidence": [
                    {
                        "id": str(evidence.id),
                        "content_hash": evidence.content_hash,
                        "url": evidence.url,
                        "publisher": source.publisher,
                    }
                ],
            },
            "result": {
                "candidates": [candidate],
                "hypotheses": [],
                "contradictions": [],
                "unresolved_questions": [],
                "candidate_orgs": [],
                "proposed_queries": [],
                "suggested_pursuit": None,
            },
            "usage": {"input_tokens": 12, "output_tokens": 9, "cost_usd": None},
        }
        session.add(
            Job(
                id=job_id,
                source_id=source.id,
                kind="intelligence_process",
                target_id=need.id,
                status="succeeded",
                checkpoint=__import__("json").dumps(checkpoint),
                created_at=datetime.now(UTC),
            )
        )
        session.add(
            LogicalCall(
                id=logical_call_id,
                fingerprint="b" * 64,
                task_type="GROUNDED_DOSSIER",
                task_key="test",
                evidence_digest="c" * 64,
                context_digest="d" * 64,
                prompt_contract="test",
                provider="openai",
                model="test-model",
                policy_version="test",
                source_id=source.id,
                project_id=project.id,
                lease_authority="job",
                job_id=job_id,
                worker_id="test-worker",
                status="COMPLETED",
                fence_token=1,
                estimated_cost_usd=0,
                max_cost_usd=0,
                actual_cost_usd=None,
                input_tokens=12,
                output_tokens=9,
                result_payload={"actual_model": "test-model", "latency_ms": 10},
                budget_scopes=[],
            )
        )
        ids = (need.id, job_id, logical_call_id, evidence.id, project.id, pursuit.id)
    client = TestClient(api.app, base_url="https://testserver")
    yield client, factory, ids
    engine.dispose()


def test_authenticated_bounded_intelligence_tasks_and_off_request(intelligence_api):
    client, factory, ids = intelligence_api
    need_id = ids[0]
    assert client.get("/api/intelligence/tasks").status_code == 401
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    tasks = client.get("/api/intelligence/tasks")
    assert tasks.status_code == 200
    assert tasks.json()["enabled"] is False
    assert all("api_key" not in key for key in tasks.json()["provider_configuration"])
    operations = client.get("/api/intelligence/operations")
    assert operations.status_code == 200
    assert operations.json()["backup"] == operations.json()["restore"] == "UNKNOWN"
    assert operations.json()["providers"]["accepted"] is None
    assert operations.json()["material_changes_30d"] is not None
    assert "outstanding_uncertain_calls_all_time" in operations.json()["providers"]
    assert operations.json()["providers"]["utc_day"]["timezone"] == "UTC"
    assert client.get(f"/api/intelligence/needs/{need_id}/history?limit=51").status_code == 422
    assert client.get(f"/api/intelligence/needs/{uuid4()}/history").status_code == 404
    assert (
        client.post(
            f"/api/intelligence/needs/{need_id}/jobs",
            json={"task_type": "NOT_A_TASK"},
            headers={"origin": "https://testserver"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/intelligence/needs/{need_id}/jobs",
            json={"task_type": "GROUNDED_DOSSIER", "question_id": "TEMP_LOAD_MW"},
            headers={"origin": "https://testserver"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/intelligence/needs/{need_id}/jobs",
            json={"task_type": "GROUNDED_DOSSIER", "question_id": "TEMP_LOAD_MW"},
            headers={"origin": "https://invalid.test"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/intelligence/needs/{need_id}/evidence/{ids[3]}/ocr",
            headers={"origin": "https://testserver"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/intelligence/needs/{need_id}/evidence/{ids[3]}/ocr-followon",
            json={"task_type": "OCR_GROUNDED_FOLLOWON", "question_id": "TEMP_LOAD_MW"},
            headers={"origin": "https://testserver"},
        ).status_code
        == 409
    )
    with factory() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(Job).where(Job.kind == "intelligence_process")
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(LogicalCall)
                .where(
                    LogicalCall.task_type.in_(
                        {
                            "OCR_EXTRACTION",
                            "OCR_INPUT_PREFLIGHT",
                            "OCR_GROUNDED_FOLLOWON",
                            "OCR_FOLLOWON_INPUT_PREFLIGHT",
                        }
                    )
                )
            )
            == 0
        )


def test_owner_feedback_replay_is_exact_attributed_and_pending_review(intelligence_api):
    client, factory, ids = intelligence_api
    need_id, job_id, call_id, evidence_id, _project_id, _pursuit_id = ids
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    body = {
        "client_id": str(uuid4()),
        "job_id": str(job_id),
        "logical_call_id": str(call_id),
        "decision": "CONFLICT",
        "note": "Synthetic owner review: verify the quoted scope with the project team.",
        "next_action": "Check scope with the named project contact.",
        "evidence_refs": [
            {
                "evidence_id": str(evidence_id),
                "content_hash": "a" * 64,
                "source_url": "https://example.test/records/1",
            }
        ],
        "candidate": {
            "field": "temporary_load_mw",
            "value": "2.0",
            "unit": "MW",
            "evidence_id": str(evidence_id),
            "evidence_hash": "a" * 64,
            "quote": "The source says the facility work scope is active.",
            "section": "abstract",
            "page": None,
            "span_start": 0,
            "span_end": len("The source says the facility work scope is active."),
            "publisher": "Synthetic test source",
            "published_date": "2026-10-01",
            "support": "direct",
            "status": "candidate",
            "source_url": "https://example.test/records/1",
            "source_id": "austin-building-permits",
        },
    }
    path = f"/api/intelligence/needs/{need_id}/feedback"
    first = client.post(path, json=body, headers={"origin": "https://testserver"})
    assert first.status_code == 200, first.text
    replay = client.post(path, json=body, headers={"origin": "https://testserver"})
    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]
    assert replay.json()["metadata"]["review_state"] == "pending_independent_review"
    assert replay.json()["metadata"]["need_id"] == str(need_id)
    assert replay.json()["metadata"]["logical_call_id"] == str(call_id)
    assert replay.json()["metadata"]["candidate"]["source_url"] == "https://example.test/records/1"
    changed = {**body, "note": "Different text with the same idempotency key."}
    assert (
        client.post(path, json=changed, headers={"origin": "https://testserver"}).status_code == 409
    )
    tampered = {
        **body,
        "client_id": str(uuid4()),
        "candidate": {**body["candidate"], "source_url": "https://attacker.test/"},
    }
    assert (
        client.post(path, json=tampered, headers={"origin": "https://testserver"}).status_code
        == 422
    )
    with factory.begin() as session:
        job = session.get(Job, job_id)
        checkpoint = json.loads(job.checkpoint)
        checkpoint.update(status="stale", result_status="stale_context")
        job.checkpoint = json.dumps(checkpoint)
    stale_feedback = {**body, "client_id": str(uuid4())}
    rejected = client.post(path, json=stale_feedback, headers={"origin": "https://testserver"})
    assert rejected.status_code == 409
    assert "current completed candidate" in rejected.json()["detail"]
    with factory() as session:
        notes = session.scalars(select(PursuitCallNote)).all()
        assert len(notes) == 1
        assert notes[0].intelligence_review["decision"] == "CONFLICT"
        assert notes[0].intelligence_review["review_state"] == "pending_independent_review"


def test_offline_worker_candidate_to_owner_review_is_persisted_and_exported(
    intelligence_api, monkeypatch
):
    client, factory, ids = intelligence_api
    need_id, _seed_job_id, _seed_call_id, evidence_id, _project_id, pursuit_id = ids
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    api = import_module("gridlens.api.app")
    from pydantic import SecretStr

    from gridlens.intelligence import intelligence_jobs
    from gridlens.jobs.queue import lease_one
    from gridlens.persistence.models import PursuitResearchQuestion

    quote = "a temporary load of 2.0 MW"
    with factory.begin() as session:
        evidence = session.get(Evidence, evidence_id)
        observation = session.get(Observation, evidence.observation_id)
        observation.abstract = "Project records confirm a temporary load of 2.0 MW during work."
        evidence.abstract = observation.abstract
        span_start = len(evidence.title) + 1 + evidence.abstract.index(quote)

    options = {
        "intelligence_enabled": True,
        "intelligence_mode": "advisory",
        "intelligence_research_enabled": True,
        "intelligence_openai_enabled": True,
        "intelligence_enabled_contracts": "TEMP_LOAD_MW",
        "openai_api_key": SecretStr("offline-fake-provider-key"),
        "intelligence_openai_reasoning_model": "test-grounded-model",
        "intelligence_openai_reasoning_priced_model_id": "test-grounded-model",
        "intelligence_openai_reasoning_pricing_verified": True,
        "intelligence_openai_reasoning_input_usd_per_million": 1,
        "intelligence_openai_reasoning_output_usd_per_million": 1,
        "intelligence_openai_reasoning_max_output_tokens": 500,
        "intelligence_max_call_usd": 1,
        "intelligence_max_active_calls": 1,
    }
    for name, value in options.items():
        monkeypatch.setattr(settings, name, value)
    for scope in ("global", "provider", "model", "source", "project"):
        monkeypatch.setattr(settings, f"intelligence_{scope}_daily_calls", 4)
        monkeypatch.setattr(settings, f"intelligence_{scope}_monthly_calls", 10)
        monkeypatch.setattr(settings, f"intelligence_{scope}_daily_usd", 2)
        monkeypatch.setattr(settings, f"intelligence_{scope}_monthly_usd", 5)
    monkeypatch.setattr(intelligence_jobs, "SessionLocal", factory)
    monkeypatch.setattr(api, "SessionLocal", factory)

    output = {
        "candidates": [
            {
                "field": "temporary_load_mw",
                "value": "2",
                "unit": "MW",
                "original_value": "2.0",
                "original_unit": "MW",
                "precision": 1,
                "date_precision": None,
                "evidence_id": str(evidence_id),
                "evidence_hash": "a" * 64,
                "quote": quote,
                "section": "abstract",
                "page": None,
                "span_start": span_start,
                "span_end": span_start + len(quote),
                "publisher": "Synthetic test source",
                "published_date": "2026-10-01",
                "speaker": None,
                "speaker_organization": None,
                "speaker_role": None,
                "support": "direct",
                "status": "candidate",
            }
        ],
        "hypotheses": [],
        "contradictions": [],
        "unresolved_questions": ["Verify whether the temporary load remains current."],
        "candidate_orgs": [],
        "proposed_queries": [],
        "suggested_pursuit": None,
    }
    monkeypatch.setattr(
        intelligence_jobs,
        "call_openai",
        lambda **_kwargs: {
            "output": output,
            "model": "test-grounded-model",
            "input_tokens": 23,
            "output_tokens": 29,
            "latency_ms": 7,
        },
    )
    queued = client.post(
        f"/api/intelligence/needs/{need_id}/jobs",
        json={"task_type": "GROUNDED_DOSSIER", "question_id": "TEMP_LOAD_MW"},
        headers={"origin": "https://testserver"},
    )
    assert queued.status_code == 200, queued.text
    queued_job = queued.json()
    assert queued_job["status"] == "queued"
    with factory.begin() as session:
        leased, fence = lease_one(
            session, "offline-intelligence-worker", job_ids=[UUID(queued_job["job_id"])]
        )
        assert leased is not None
        job_id = leased.id
        assert (
            session.scalar(
                select(PursuitResearchQuestion).where(
                    PursuitResearchQuestion.need_id == need_id,
                )
            )
            is not None
        )
    running = client.get(f"/api/intelligence/needs/{need_id}/history").json()["items"]
    assert next(item for item in running if item["job_id"] == str(job_id))["status"] == "running"
    result = intelligence_jobs.process_intelligence_job(
        job_id, "offline-intelligence-worker", fence
    )
    assert result["status"] == "completed", result
    history = client.get(f"/api/intelligence/needs/{need_id}/history").json()["items"]
    completed = next(item for item in history if item["job_id"] == str(job_id))
    assert completed["status"] == "completed"
    candidate = completed["result"]["candidates"][0]
    assert candidate["status"] == "candidate"
    assert candidate["source_url"] == "https://example.test/records/1"
    feedback = client.post(
        f"/api/intelligence/needs/{need_id}/feedback",
        json={
            "client_id": str(uuid4()),
            "job_id": str(job_id),
            "logical_call_id": completed["logical_call_id"],
            "decision": "UNRESOLVED",
            "note": "Offline owner review pending independent validation.",
            "next_action": "Verify with the project owner.",
            "candidate": candidate,
            "evidence_refs": [
                {
                    "evidence_id": str(evidence_id),
                    "content_hash": "a" * 64,
                    "source_url": "https://example.test/records/1",
                }
            ],
        },
        headers={"origin": "https://testserver"},
    )
    assert feedback.status_code == 200, feedback.text
    assert feedback.json()["metadata"]["review_state"] == "pending_independent_review"
    exported = client.get(f"/api/commercial/triage/history/{pursuit_id}")
    assert exported.status_code == 200
    assert exported.json()["notes"][0]["intelligence_review"]["review_state"] == (
        "pending_independent_review"
    )
