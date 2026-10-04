from datetime import UTC, datetime, timedelta
from importlib import import_module
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.persistence import models  # noqa: F401
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    BriefDailyBudget,
    Evidence,
    Interpretation,
    Job,
    NeedObservation,
    Observation,
    PowerNeed,
    PowerNeedBrief,
    PowerNeedBriefVersion,
    Project,
    Source,
)
from gridlens.security import token_for
from gridlens.settings import settings


@pytest.fixture
def runtime(monkeypatch):
    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and target.database.endswith("_test")
    assert (target.host, target.port, target.database) != (
        application.host,
        application.port,
        application.database,
    )
    engine = create_engine(settings.test_database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    service = import_module("gridlens.intelligence.briefs")
    api = import_module("gridlens.api.app")
    worker = import_module("gridlens.jobs.worker")
    monkeypatch.setattr(service, "SessionLocal", factory)
    monkeypatch.setattr(api, "SessionLocal", factory)
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("synthetic-key"))
    with factory.begin() as session:
        source = Source(
            id="brief-test-permits",
            publisher="Synthetic city",
            endpoint="https://example.test/permits",
            family="construction-permits",
            geography="Test City",
            industries=["construction"],
            retrieval_method="socrata-permits",
            health={},
        )
        session.add(source)
        session.flush()
        project = Project(
            identity_key="brief-test-project",
            name="Synthetic North Campus",
            location="Test City",
            source_id=source.id,
            external_id="record-1",
        )
        session.add(project)
        session.flush()
        need = PowerNeed(
            project_id=project.id,
            activity_key="construction",
            tier="Signal",
            rationale="Test only",
            supply="Unknown",
        )
        observation = Observation(
            source_id=source.id,
            external_id="record-1",
            title="Public permit describes construction at Synthetic North Campus",
            abstract="Construction work at Synthetic North Campus in Test City.",
            url="https://example.test/permits/record-1",
            content_hash="a" * 64,
        )
        session.add_all([need, observation])
        session.flush()
        evidence = Evidence(
            observation_id=observation.id,
            content_hash="a" * 64,
            title=observation.title,
            abstract=observation.abstract,
            url=observation.url,
            extraction_location="permit description",
        )
        session.add(evidence)
        session.flush()
        interpretation = Interpretation(
            observation_id=observation.id,
            content_hash=observation.content_hash,
            evaluator_version="brief-test",
            status="accepted",
            assessment={
                "semantic_hash": observation.content_hash,
                "evidence_hash": evidence.content_hash,
                "project_identity_key": project.identity_key,
                "power_activity": need.activity_key,
                "decision": "accepted",
                "subject": project.name,
                "location": project.location,
            },
        )
        session.add_all(
            [interpretation, NeedObservation(need_id=need.id, observation_id=observation.id)]
        )
        from gridlens.persistence.models import Pursuit, PursuitCallNote

        pursuit = Pursuit(
            identity_key="brief-test-private-workspace",
            project_id=project.id,
            project_ids=[str(project.id)],
            snapshot={},
            research_status="not_researched",
            research_errors=[],
        )
        session.add(pursuit)
        session.flush()
        session.add(
            PursuitCallNote(
                pursuit_id=pursuit.id,
                client_id=uuid4(),
                note="PRIVATE-BRIEF-TEST: never include this note",
                outcome="unknown",
                next_action="private next action",
            )
        )
        ids = need.id, evidence.id
    yield factory, service, ids
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_explicit_request_is_durable_deduplicated_and_cached(runtime):
    factory, service, (need_id, evidence_id) = runtime
    with factory.begin() as session:
        first = service.request_brief(session, need_id)
        second = service.request_brief(session, need_id)
        import json

        payload, _ = service.brief_input(session, need_id)
        assert "PRIVATE-BRIEF-TEST" not in json.dumps(payload)
        assert first["status"] == second["status"] == "pending"
        assert first["job_id"] == second["job_id"]
        assert session.scalar(select(func.count()).select_from(Job)) == 1


def test_question_bound_request_reuses_exact_pending_job_and_rejects_changed_question(runtime):
    import json

    factory, service, (need_id, _evidence_id) = runtime
    question = "Who owns the next construction power decision?"
    with factory.begin() as session:
        payload, _ = service.brief_input(session, need_id, question)
        first = service.request_brief(session, need_id, question)
        second = service.request_brief(session, need_id, question)
        job = session.scalar(select(Job))
        assert payload["commercial_question"] == question
        assert first["job_id"] == second["job_id"] == str(job.id)
        assert json.loads(job.checkpoint)["commercial_question"] == question
        with pytest.raises(service.BriefUnavailable, match="another_question_or_evidence_version"):
            service.request_brief(session, need_id, "What is the project's MW requirement?")
        assert session.scalar(select(func.count()).select_from(Job)) == 1


def test_browse_cache_fingerprint_matches_detail_relationship_evidence(runtime, monkeypatch):
    factory, service, (need_id, _evidence_id) = runtime
    relationship = {
        "stale": False,
        "organization_relationship": "DIRECT",
        "category": "owner_developer",
        "organization": "North Campus Development LLC",
        "evidence": [
            {
                "id": "chain-evidence-1",
                "quote": "North Campus Development LLC is named as project owner.",
                "published_at": None,
                "url": "https://example.test/owner",
            }
        ],
    }
    monkeypatch.setattr(
        service,
        "buying_chain_view",
        lambda _session, _project_id: {"candidates": [relationship]},
    )
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        detail_payload, evidence = service.brief_input(session, need_id)
        fingerprint = service.brief_fingerprint(detail_payload)
        raw_links = session.execute(
            select(Observation, Evidence, Interpretation)
            .join(NeedObservation, NeedObservation.observation_id == Observation.id)
            .join(Evidence, Evidence.observation_id == Observation.id)
            .outerjoin(Interpretation, Interpretation.observation_id == Observation.id)
            .where(NeedObservation.need_id == need_id)
        ).all()
        row = PowerNeedBrief(
            need_id=need_id,
            requested_fingerprint=fingerprint,
            generated_fingerprint=fingerprint,
            policy_version=service.POLICY_VERSION,
            schema_version=service.SCHEMA_VERSION,
            model=settings.openai_brief_model,
            status="ready",
            result={
                "event_summary": [],
                "commercial_hypothesis": {"text": "A cached summary."},
            },
            citations=[],
            generated_at=datetime.now(UTC),
        )
        session.add(row)
        preview = service.brief_preview(
            session,
            need,
            project,
            [(item[0], item[1], item[2]) for item in raw_links],
            {source.id: source for source in session.scalars(select(Source)).all()},
            row,
        )
        assert preview["brief_stale"] is False
        assert preview["brief_status"] == "ready"
        relationship["evidence"][0]["quote"] = (
            "North Campus Development LLC is listed in a separate retained source."
        )
        changed = service.brief_preview(
            session,
            need,
            project,
            [(item[0], item[1], item[2]) for item in raw_links],
            {source.id: source for source in session.scalars(select(Source)).all()},
            row,
        )
        assert changed["brief_stale"] is True
        assert "North Campus Development LLC" in detail_payload["need"]["display_title"]
    with factory.begin() as session:
        cached = session.get(PowerNeedBrief, need_id)
        cached.requested_fingerprint = cached.generated_fingerprint
        cached.generated_at = datetime.now(UTC)
        cached.result = {
            "event_summary": [],
            "commercial_hypothesis": {"text": "A cached summary."},
            "unknowns": [],
            "next_step": "Verify the activity.",
        }
        cached.citations = []
        cached.status = "ready"
        cached_fingerprint = cached.requested_fingerprint
        payload, _ = service.brief_input(session, need_id)
        cached_fingerprint = service.brief_fingerprint(payload)
        cached.generated_fingerprint = cached_fingerprint
        cached.requested_fingerprint = cached_fingerprint
        cached.generated_at = datetime.now(UTC)
        cached.status = "ready"
    with factory() as session:
        cached = session.get(PowerNeedBrief, need_id)
        project = session.get(Project, session.get(PowerNeed, need_id).project_id)
        links = session.execute(
            select(Observation, Evidence, Interpretation)
            .join(NeedObservation, NeedObservation.observation_id == Observation.id)
            .join(Evidence, Evidence.observation_id == Observation.id)
            .outerjoin(Interpretation, Interpretation.observation_id == Observation.id)
            .where(NeedObservation.need_id == need_id)
        ).all()
        card = service.brief_preview(
            session,
            session.get(PowerNeed, need_id),
            project,
            [(item[0], item[1], item[2]) for item in links],
            {source.id: source for source in session.scalars(select(Source)).all()},
            cached,
        )
        assert card["brief_stale"] is False


def test_uncached_card_preview_does_not_load_relationships(runtime, monkeypatch):
    factory, service, (need_id, _evidence_id) = runtime
    monkeypatch.setattr(
        service,
        "buying_chain_view",
        lambda *_args: pytest.fail("uncached card should not query relationships"),
    )
    with factory() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        preview = service.brief_preview(session, need, project, [], {}, None)
        assert preview["brief_status"] == "unavailable"


def test_provider_failure_retains_last_good_brief_without_blind_retry(runtime, monkeypatch):
    factory, service, (need_id, evidence_id) = runtime
    with factory.begin() as session:
        row = PowerNeedBrief(
            need_id=need_id,
            requested_fingerprint="old-fingerprint",
            generated_fingerprint="old-fingerprint",
            policy_version="old-policy",
            schema_version="old-schema",
            model="old-model",
            status="ready",
            result={"commercial_hypothesis": {"text": "Last good advisory."}},
            citations=[],
            generated_at=datetime.now(UTC),
            input_tokens=1,
            output_tokens=1,
        )
        session.add(row)
    with factory.begin() as session:
        requested = _request_due_brief(session, service, need_id)
        job_id = requested["job_id"]
    from gridlens.jobs.queue import lease_one

    with factory.begin() as session:
        job, fence = lease_one(session, "brief-test-worker", job_ids=[UUID(job_id)])
    monkeypatch.setattr(
        service,
        "_provider",
        lambda _payload, _evidence: (_ for _ in ()).throw(TimeoutError("provider timeout")),
    )
    service.process_brief_job(job_id, "brief-test-worker", fence)
    with factory() as session:
        row = session.get(PowerNeedBrief, need_id)
        job = session.get(Job, job_id)
        assert row and row.result["commercial_hypothesis"]["text"] == "Last good advisory."
        assert row.status == "failed"
        assert job and job.status == "failed"
        assert job.attempts == 1
        assert row.error == "request_failed"


def test_rejected_provider_output_keeps_usage_and_safe_reason(runtime, monkeypatch):
    factory, service, (need_id, _evidence_id) = runtime
    with factory.begin() as session:
        requested = _request_due_brief(session, service, need_id)
    leased = _lease(factory, UUID(requested["job_id"]))
    assert leased
    job, fence = leased

    def rejected(_payload, evidence):
        evidence_id, source = next(iter(evidence.items()))
        return (
            {
                "selected_fact_ids": ["invented-fact-id"],
                "hypothesis_fact_id": "invented-fact-id",
            },
            123,
            45,
        )

    monkeypatch.setattr(service, "_provider", rejected)
    service.process_brief_job(job.id, "brief-test-worker", fence)
    with factory() as session:
        row = session.get(PowerNeedBrief, need_id)
        assert row and row.status == "failed"
        assert row.error == "invalid_fact_selection"
        assert (row.input_tokens, row.output_tokens) == (123, 45)


def _valid_model_result(_payload, facts):
    fact_id = next(iter(facts))
    return {"selected_fact_ids": [fact_id], "hypothesis_fact_id": fact_id}, 120, 40


def _request_due_brief(session, service, need_id):
    """A new immediate-lease fixture is due despite sub-ms DB/Python clock skew."""
    requested = service.request_brief(session, need_id)
    job = session.get(Job, UUID(requested["job_id"]))
    assert job is not None and job.status == "queued" and job.attempts == 0
    job.available_at = datetime.now(UTC) - timedelta(seconds=1)
    return requested


def _lease(factory, job_id):
    from gridlens.jobs.queue import lease_one

    with factory.begin() as session:
        return lease_one(session, "brief-test-worker", job_ids=[job_id])


def test_budget_reservation_and_expired_reserved_job_never_call_provider(runtime, monkeypatch):
    factory, service, (need_id, _evidence_id) = runtime
    monkeypatch.setattr(settings, "briefs_daily_request_limit", 1)
    with factory.begin() as session:
        queued = _request_due_brief(session, service, need_id)
        today = datetime.now(UTC).astimezone(ZoneInfo("America/Chicago")).date()
        session.add(BriefDailyBudget(day=today, reserved_requests=1))
    leased = _lease(factory, UUID(queued["job_id"]))
    assert leased
    job, fence = leased
    calls = []
    monkeypatch.setattr(service, "_provider", lambda payload, _facts: calls.append(payload))
    service.process_brief_job(job.id, "brief-test-worker", fence)
    with factory() as session:
        assert calls == []
        assert session.get(Job, job.id).status == "failed"
        assert session.get(PowerNeedBrief, need_id).error == "daily_budget_exhausted"

    with factory.begin() as session:
        row = session.get(PowerNeedBrief, need_id)
        job = session.get(Job, job.id)
        row.status = "pending"
        row.error = None
        job.status = "queued"
        job.attempts = 0
        job.checkpoint = None
        retry = service.request_brief(session, need_id)
    leased = _lease(factory, UUID(retry["job_id"]))
    assert leased
    job, fence = leased
    with factory.begin() as session:
        running = session.get(Job, job.id)
        running.checkpoint = '{"reserved": true}'
        running.lease_until = datetime.now(UTC) - timedelta(seconds=1)
    leased_again = _lease(factory, job.id)
    assert leased_again
    retry_job, retry_fence = leased_again
    service.process_brief_job(retry_job.id, "brief-test-worker", retry_fence)
    with factory() as session:
        assert calls == []
        assert session.get(Job, retry_job.id).status == "failed"
        assert session.get(PowerNeedBrief, need_id).error == "ambiguous_prior_request"


def test_input_changes_fence_worker_and_last_good_version_history(runtime, monkeypatch):
    factory, service, (need_id, _evidence_id) = runtime
    with factory.begin() as session:
        row = PowerNeedBrief(
            need_id=need_id,
            requested_fingerprint="old-request",
            generated_fingerprint="old-fingerprint",
            policy_version="old-policy",
            schema_version="old-schema",
            model="old-model",
            status="ready",
            result={"commercial_hypothesis": {"text": "Last good advisory."}},
            citations=[],
            generated_at=datetime.now(UTC),
            input_tokens=10,
            output_tokens=5,
        )
        session.add(row)
    with factory.begin() as session:
        queued = _request_due_brief(session, service, need_id)
    leased = _lease(factory, UUID(queued["job_id"]))
    assert leased
    job, fence = leased

    def change_input_during_call(payload, facts):
        with factory.begin() as session:
            session.get(PowerNeed, need_id).start_window = "Q4 unknown source"
        return _valid_model_result(payload, facts)

    monkeypatch.setattr(service, "_provider", change_input_during_call)
    service.process_brief_job(job.id, "brief-test-worker", fence)
    with factory() as session:
        row = session.get(PowerNeedBrief, need_id)
        assert row.status == "stale"
        assert row.result["commercial_hypothesis"]["text"] == "Last good advisory."
        assert session.scalar(select(func.count()).select_from(PowerNeedBriefVersion)) == 0


def test_non_permit_application_uses_source_neutral_unknown(runtime, monkeypatch):
    factory, service, (need_id, _evidence_id) = runtime
    with factory.begin() as session:
        observation = session.scalar(select(Observation))
        observation.title = "Massachusetts cultivation application for Synthetic North Campus"
        observation.abstract = "Cultivation application at Synthetic North Campus in Test City."
        queued = _request_due_brief(session, service, need_id)
    leased = _lease(factory, UUID(queued["job_id"]))
    assert leased
    job, fence = leased
    monkeypatch.setattr(service, "_provider", _valid_model_result)
    service.process_brief_job(job.id, "brief-test-worker", fence)
    with factory() as session:
        row = session.get(PowerNeedBrief, need_id)
        assert row and row.status == "ready"
        assert (
            "Whether the reported activity creates any temporary or backup power need is unknown."
            in row.result["unknowns"]
        )
        assert all("permit creates" not in item for item in row.result["unknowns"])


def test_a_to_b_to_a_refresh_preserves_current_cache_status(runtime, monkeypatch):
    factory, service, (need_id, _evidence_id) = runtime
    with factory.begin() as session:
        payload_a, _ = service.brief_input(session, need_id)
        fingerprint_a = service.brief_fingerprint(payload_a)
        session.add(
            PowerNeedBrief(
                need_id=need_id,
                requested_fingerprint=fingerprint_a,
                generated_fingerprint=fingerprint_a,
                policy_version=service.POLICY_VERSION,
                schema_version=service.SCHEMA_VERSION,
                model=settings.openai_brief_model,
                status="ready",
                result={
                    "event_summary": [],
                    "commercial_hypothesis": {
                        "text": "Cached A advisory.",
                        "evidence_id": "cached-evidence",
                    },
                    "unknowns": [],
                    "next_step": "Verify the activity.",
                },
                citations=[],
                generated_at=datetime.now(UTC),
            )
        )
        session.get(PowerNeed, need_id).start_window = "Input B"
    with factory.begin() as session:
        queued = _request_due_brief(session, service, need_id)
    leased = _lease(factory, UUID(queued["job_id"]))
    assert leased
    job, fence = leased

    def return_to_a_during_b_call(payload, facts):
        with factory.begin() as session:
            session.get(PowerNeed, need_id).start_window = None
        return _valid_model_result(payload, facts)

    monkeypatch.setattr(service, "_provider", return_to_a_during_b_call)
    service.process_brief_job(job.id, "brief-test-worker", fence)
    api = import_module("gridlens.api.app")
    client = TestClient(api.app)
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    response = client.get(f"/api/power-needs/{need_id}/brief")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["stale"] is False
    with factory() as session:
        row = session.get(PowerNeedBrief, need_id)
        assert row and row.status == "ready"
        assert row.generated_fingerprint == fingerprint_a
        assert row.result["commercial_hypothesis"]["text"] == "Cached A advisory."


def test_successful_replacement_archives_old_policy_model_and_schema(runtime, monkeypatch):
    factory, service, (need_id, _evidence_id) = runtime
    with factory.begin() as session:
        row = PowerNeedBrief(
            need_id=need_id,
            requested_fingerprint="old-request",
            generated_fingerprint="old-fingerprint",
            policy_version="old-policy",
            schema_version="old-schema",
            model="old-model",
            status="ready",
            result={"commercial_hypothesis": {"text": "Old accepted brief."}},
            citations=[],
            generated_at=datetime.now(UTC),
            input_tokens=10,
            output_tokens=5,
        )
        session.add(row)
    with factory.begin() as session:
        queued = _request_due_brief(session, service, need_id)
    leased = _lease(factory, UUID(queued["job_id"]))
    assert leased
    job, fence = leased
    monkeypatch.setattr(service, "_provider", _valid_model_result)
    service.process_brief_job(job.id, "brief-test-worker", fence)
    with factory() as session:
        version = session.scalar(
            select(PowerNeedBriefVersion).where(PowerNeedBriefVersion.need_id == need_id)
        )
        row = session.get(PowerNeedBrief, need_id)
        assert version and version.result["commercial_hypothesis"]["text"] == "Old accepted brief."
        assert (version.policy_version, version.schema_version, version.model) == (
            "old-policy",
            "old-schema",
            "old-model",
        )
        assert row and row.status == "ready"
        assert row.model == settings.openai_brief_model


def test_brief_api_requires_auth_and_same_origin_for_explicit_request(runtime):
    factory, _service, (need_id, _evidence_id) = runtime
    api = import_module("gridlens.api.app")
    client = TestClient(api.app)
    assert client.get(f"/api/power-needs/{need_id}/brief").status_code == 401
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    assert client.get(f"/api/power-needs/{need_id}/brief").json()["status"] == "unavailable"
    response = client.post(
        f"/api/power-needs/{need_id}/brief",
        headers={"origin": "https://attacker.invalid"},
        json={},
    )
    assert response.status_code == 403
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 0


def test_missing_provider_key_and_wrong_project_evidence_fail_closed(runtime, monkeypatch):
    factory, service, (need_id, _evidence_id) = runtime
    monkeypatch.setattr(settings, "openai_api_key", None)
    from gridlens.intelligence.briefs import BriefUnavailable

    with factory.begin() as session:
        with pytest.raises(BriefUnavailable, match="provider_not_configured"):
            service.request_brief(session, need_id)
        assert session.scalar(select(func.count()).select_from(Job)) == 0
        interpretation = session.scalar(select(Interpretation))
        interpretation.assessment = {
            **interpretation.assessment,
            "project_identity_key": "another-project",
        }
        session.flush()
        with pytest.raises(BriefUnavailable, match="no_current_public_evidence"):
            service.brief_input(session, need_id)
