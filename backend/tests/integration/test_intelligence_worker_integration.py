from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.intelligence_jobs import enqueue_intelligence, intelligence_history
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
    PursuitResearchQuestion,
    Source,
)
from gridlens.settings import settings


@pytest.fixture
def sessions():
    target = make_url(settings.test_database_url)
    assert target.database and target.database.endswith("_test")
    assert target != make_url(settings.database_url)
    engine = create_engine(settings.test_database_url, pool_size=8)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _enable_bounded_typesafe(monkeypatch):
    values = {
        "intelligence_enabled": True,
        "intelligence_mode": "evaluation",
        "intelligence_typesafe_enabled": True,
        "intelligence_enabled_contracts": "SOURCE_RELEVANCE_V1",
        "jev_enabled": True,
        "typesafe_api_key": SecretStr("fixture-only"),
        "intelligence_typesafe_model": "pinned-fixture-model",
        "intelligence_typesafe_priced_model_id": "pinned-fixture-model",
        "intelligence_typesafe_pricing_verified": True,
        "intelligence_typesafe_input_usd_per_million": Decimal("1"),
        "intelligence_typesafe_output_usd_per_million": Decimal("0"),
        "intelligence_typesafe_max_output_tokens": 100,
        "intelligence_typesafe_output_limit_verified": True,
        "intelligence_max_active_calls": 2,
        "intelligence_max_call_usd": Decimal("0.1"),
    }
    for name, value in values.items():
        monkeypatch.setattr(settings, name, value)
    for scope in ("global", "provider", "model", "source", "project"):
        for period in ("daily", "monthly"):
            monkeypatch.setattr(settings, f"intelligence_{scope}_{period}_calls", 10)
            monkeypatch.setattr(settings, f"intelligence_{scope}_{period}_usd", Decimal("10"))


def _seed_job(sessions, *, task_type="SOURCE_RELEVANCE_V1", question_id=None, link_pursuit=False):
    source_id = "intelligence-fixture-source"
    need_id = uuid4()
    project_id = uuid4()
    observation_id = uuid4()
    evidence_id = uuid4()
    with sessions.begin() as session:
        session.add(
            Source(
                id=source_id,
                publisher="Fixture Utility",
                endpoint="https://example.invalid",
                family="test",
                geography="fixture",
                industries=["power"],
                retrieval_method="test",
                enabled=True,
                registry_enabled=True,
                health={},
            )
        )
        session.flush()
        session.add(
            Project(
                id=project_id,
                identity_key="fixture-project",
                name="Fixture Data Center",
                source_id=source_id,
                external_id="fixture-1",
                identity_facts={"identity": "fixture"},
            )
        )
        session.flush()
        session.add(
            PowerNeed(
                id=need_id,
                project_id=project_id,
                activity_key="fixture-construction",
                rationale="Fixture only; testing bounded advisory processing.",
                required_mw="12 MW",
                start_window="2027",
                duration="temporary",
                supply="Unknown",
            )
        )
        session.add(
            Observation(
                id=observation_id,
                source_id=source_id,
                external_id="fixture-evidence",
                title="Fixture project seeks utility coordination",
                abstract="Temporary load of 12 MW is requested in the utility service application.",
                published_at=date(2026, 10, 1),
                url="https://example.invalid/fixture",
                content_hash="a" * 64,
            )
        )
        session.add(
            Evidence(
                id=evidence_id,
                observation_id=observation_id,
                content_hash="a" * 64,
                title="Fixture project seeks utility coordination",
                abstract="Temporary load of 12 MW is requested in the utility service application.",
                url="https://example.invalid/fixture",
                published_at=date(2026, 10, 1),
            )
        )
        session.flush()
        session.add(NeedObservation(need_id=need_id, observation_id=observation_id))
        if link_pursuit:
            session.add(
                Pursuit(
                    identity_key="fixture-pursuit",
                    project_id=project_id,
                    project_ids=[str(project_id)],
                    snapshot={},
                    research_status="not_researched",
                )
            )
        job = enqueue_intelligence(
            session,
            need_id=need_id,
            task_type=task_type,
            question_id=question_id,
            origin="test",
        )
        job_id = job.id
    return need_id, evidence_id, job_id


def _fake_call(**_kwargs):
    return {
        "model": "pinned-fixture-model",
        "provider_response_id": "fixture-response",
        "answers": {
            "answer": {
                "type": "choice",
                "choice": "RELEVANT",
                "confidence": 1.0,
                "probabilities": {"RELEVANT": 1.0, "IRRELEVANT": 0.0, "UNCERTAIN": 0.0},
            }
        },
    }


def _wire_worker(sessions, monkeypatch):
    from gridlens.intelligence import intelligence_jobs
    from gridlens.jobs import worker

    monkeypatch.setattr(intelligence_jobs, "SessionLocal", sessions)
    monkeypatch.setattr(intelligence_jobs, "call_typesafe", _fake_call)
    monkeypatch.setattr(worker, "SessionLocal", sessions)
    return worker


def test_leased_worker_runs_retained_need_through_shared_ledger(sessions, monkeypatch):
    _enable_bounded_typesafe(monkeypatch)
    need_id, evidence_id, job_id = _seed_job(sessions)

    worker = _wire_worker(sessions, monkeypatch)
    worker_id = "fixture-worker"
    monkeypatch.setattr(worker, "WORKER_ID", worker_id)
    assert worker.run_one({}, job_ids=[job_id]) is True

    with sessions() as session:
        history = intelligence_history(session, need_id)
        call = session.scalar(select(LogicalCall))
    assert len(history) == 1
    assert history[0]["status"] == "completed"
    assert history[0]["result"]["authority"] == "ADVISORY_ONLY"
    assert history[0]["evidence_ids"] == [str(evidence_id)]
    assert history[0]["logical_call_id"] == str(call.id)
    assert history[0]["usage"] == {
        "input_tokens": None,
        "output_tokens": None,
        "actual_cost_usd": None,
        "estimated_cost_usd": None,
        "cost_basis": None,
    }
    assert call and call.status == "COMPLETED" and call.result_payload


def test_typesafe_dispatch_preserves_bounded_need_and_identity_context(sessions, monkeypatch):
    _enable_bounded_typesafe(monkeypatch)
    _need_id, _evidence_id, job_id = _seed_job(sessions)
    worker = _wire_worker(sessions, monkeypatch)
    from gridlens.intelligence import intelligence_jobs

    captured = {}

    def inspect_payload(**kwargs):
        captured.update(kwargs["payload"])
        return _fake_call()

    monkeypatch.setattr(intelligence_jobs, "call_typesafe", inspect_payload)
    monkeypatch.setattr(worker, "WORKER_ID", "fixture-context-worker")
    assert worker.run_one({}, job_ids=[job_id]) is True
    assert captured["state"]["task_type"] == "SOURCE_RELEVANCE_V1"
    assert captured["state"]["schema_version"]
    assert captured["state"]["need"]["project_identity_key"] == "fixture-project"
    assert "state_version_digest" in captured["state"]["need"]
    assert captured["state"]["evidence"][0]["content_hash"] == "a" * 64


def test_leased_worker_runs_grounded_question_and_retains_advisory_dossier(sessions, monkeypatch):
    values = {
        "intelligence_enabled": True,
        "intelligence_mode": "advisory",
        "intelligence_openai_enabled": True,
        "intelligence_research_enabled": True,
        "intelligence_enabled_contracts": "TEMP_LOAD_MW",
        "openai_api_key": SecretStr("fixture-only"),
        "intelligence_openai_reasoning_model": "pinned-reasoning-fixture",
        "intelligence_openai_reasoning_priced_model_id": "pinned-reasoning-fixture",
        "intelligence_openai_reasoning_pricing_verified": True,
        "intelligence_openai_reasoning_input_usd_per_million": Decimal("1"),
        "intelligence_openai_reasoning_output_usd_per_million": Decimal("0"),
        "intelligence_openai_reasoning_max_output_tokens": 1200,
        "intelligence_max_active_calls": 2,
        "intelligence_max_call_usd": Decimal("0.1"),
    }
    for name, value in values.items():
        monkeypatch.setattr(settings, name, value)
    for scope in ("global", "provider", "model", "source", "project"):
        for period in ("daily", "monthly"):
            monkeypatch.setattr(settings, f"intelligence_{scope}_{period}_calls", 10)
            monkeypatch.setattr(settings, f"intelligence_{scope}_{period}_usd", Decimal("10"))
    need_id, evidence_id, job_id = _seed_job(
        sessions,
        task_type="GROUNDED_DOSSIER",
        question_id="TEMP_LOAD_MW",
        link_pursuit=True,
    )
    worker = _wire_worker(sessions, monkeypatch)
    from gridlens.intelligence import intelligence_jobs

    output = {
        "candidates": [
            {
                "field": "temporary_load_mw",
                "value": "12",
                "unit": "MW",
                "evidence_id": str(evidence_id),
                "evidence_hash": "a" * 64,
                "quote": "Temporary load of 12 MW is requested in the utility service application.",
                "section": "abstract",
                "page": None,
                "span_start": len("Fixture project seeks utility coordination\n"),
                "span_end": len("Fixture project seeks utility coordination\n")
                + len("Temporary load of 12 MW is requested in the utility service application."),
                "publisher": "Fixture Utility",
                "published_date": "2026-10-01",
                "support": "direct",
                "status": "candidate",
            }
        ],
        "hypotheses": ["Ask the utility to confirm temporary load."],
        "contradictions": [],
        "unresolved_questions": ["What exact MW amount is requested?"],
        "candidate_orgs": [],
        "proposed_queries": ["utility temporary service load MW"],
        "suggested_pursuit": None,
    }
    monkeypatch.setattr(
        intelligence_jobs,
        "call_openai",
        lambda **_kwargs: {
            "model": "pinned-reasoning-fixture",
            "provider_response_id": "fixture-grounded-response",
            "latency_ms": 19,
            "input_tokens": 300,
            "output_tokens": 80,
            "output": output,
        },
    )
    monkeypatch.setattr(worker, "WORKER_ID", "fixture-openai-worker")
    assert worker.run_one({}, job_ids=[job_id]) is True
    with sessions() as session:
        history = intelligence_history(session, need_id)
        call = session.scalar(select(LogicalCall))
        question = session.scalar(select(PursuitResearchQuestion))
    assert history[0]["status"] == "completed"
    assert history[0]["evidence_ids"] == [str(evidence_id)]
    assert history[0]["result"]["schema_version"] == "grounded-candidates-v1"
    assert history[0]["result"]["candidates"][0]["value"] == "12"
    assert history[0]["result"]["unresolved_questions"] == output["unresolved_questions"]
    assert history[0]["result"]["actual_model"] == "pinned-reasoning-fixture"
    assert history[0]["result"]["latency_ms"] == 19
    assert history[0]["usage"]["actual_cost_usd"] is None
    assert history[0]["usage"]["estimated_cost_usd"] == "0.0003"
    assert history[0]["usage"]["cost_basis"] == "derived_from_verified_usage_and_pinned_rates"
    assert call and call.status == "COMPLETED" and call.input_tokens == 300
    assert question and question.category == "load" and question.status == "UNRESOLVED"
    assert question.receipt["intelligence_job"]["logical_call_id"] == str(call.id)


def test_worker_recovers_not_sent_reservation_after_lease_turnover(sessions, monkeypatch):
    from datetime import UTC, datetime, timedelta

    _enable_bounded_typesafe(monkeypatch)
    _need_id, _evidence_id, job_id = _seed_job(sessions)
    worker = _wire_worker(sessions, monkeypatch)
    monkeypatch.setattr(worker, "WORKER_ID", "fixture-worker-a")

    from gridlens.intelligence import intelligence_jobs

    real_dispatch = intelligence_jobs.mark_dispatched

    def crash_before_dispatch(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(intelligence_jobs, "mark_dispatched", crash_before_dispatch)
    with pytest.raises(KeyboardInterrupt):
        worker.run_one({}, job_ids=[job_id])
    monkeypatch.setattr(intelligence_jobs, "mark_dispatched", real_dispatch)
    with sessions.begin() as session:
        job = session.get(Job, job_id)
        job.lease_until = datetime.now(UTC) - timedelta(seconds=1)
        job.available_at = datetime.now(UTC) - timedelta(seconds=1)
    monkeypatch.setattr(worker, "WORKER_ID", "fixture-worker-b")
    assert worker.run_one({}, job_ids=[job_id]) is True
    with sessions() as session:
        row = session.scalar(select(LogicalCall))
        history = intelligence_history(session, _need_id)
    assert row and row.status == "COMPLETED"
    assert history[0]["status"] == "completed"


def test_zeroed_budget_after_reserve_cancels_before_provider_dispatch(sessions, monkeypatch):
    _enable_bounded_typesafe(monkeypatch)
    need_id, _evidence_id, job_id = _seed_job(sessions)
    worker = _wire_worker(sessions, monkeypatch)
    from gridlens.intelligence import intelligence_jobs

    provider_calls = 0

    def provider_call(**_kwargs):
        nonlocal provider_calls
        provider_calls += 1
        return _fake_call()

    monkeypatch.setattr(intelligence_jobs, "call_typesafe", provider_call)
    original_policy = intelligence_jobs._dispatch_policy

    def zero_budget_before_dispatch(*args, **kwargs):
        monkeypatch.setattr(settings, "intelligence_global_daily_calls", 0)
        return original_policy(*args, **kwargs)

    monkeypatch.setattr(intelligence_jobs, "_dispatch_policy", zero_budget_before_dispatch)
    assert worker.run_one({}, job_ids=[job_id]) is True
    with sessions() as session:
        call = session.scalar(select(LogicalCall))
        history = intelligence_history(session, need_id)
    assert call and call.status == "CANCELLED"
    assert provider_calls == 0
    assert history[0]["status"] == "blocked"
    assert history[0]["error"] == "GLOBAL_DAILY_CAP_ZERO"


@pytest.mark.parametrize("crash_point", ["after_dispatch", "after_provider_response"])
def test_worker_never_retries_ambiguous_dispatch_after_lease_turnover(
    sessions, monkeypatch, crash_point
):
    from datetime import UTC, datetime, timedelta

    _enable_bounded_typesafe(monkeypatch)
    _need_id, _evidence_id, job_id = _seed_job(sessions)
    worker = _wire_worker(sessions, monkeypatch)
    monkeypatch.setattr(worker, "WORKER_ID", "fixture-worker-a")
    from gridlens.intelligence import intelligence_jobs

    provider_calls = 0

    def provider_crash(**_kwargs):
        nonlocal provider_calls
        provider_calls += 1
        if crash_point == "after_dispatch":
            raise KeyboardInterrupt
        return _fake_call()

    monkeypatch.setattr(intelligence_jobs, "call_typesafe", provider_crash)
    if crash_point == "after_provider_response":

        def crash_before_ledger_commit(*_args, **_kwargs):
            raise KeyboardInterrupt

        monkeypatch.setattr(intelligence_jobs, "complete_call", crash_before_ledger_commit)
    with pytest.raises(KeyboardInterrupt):
        worker.run_one({}, job_ids=[job_id])

    with sessions.begin() as session:
        job = session.get(Job, job_id)
        job.lease_until = datetime.now(UTC) - timedelta(seconds=1)
        job.available_at = datetime.now(UTC) - timedelta(seconds=1)
    monkeypatch.setattr(worker, "WORKER_ID", "fixture-worker-b")
    assert worker.run_one({}, job_ids=[job_id]) is True

    with sessions() as session:
        call = session.scalar(select(LogicalCall))
        history = intelligence_history(session, _need_id)
    assert call and call.status == "SENT_OUTCOME_UNKNOWN"
    assert call.result_payload is None
    assert provider_calls == 1
    assert history[0]["status"] == "blocked"
    assert history[0]["error"] == "IDENTITY_LEASE_MISMATCH"


def test_same_job_reentry_does_not_repeat_sent_unknown_call(sessions, monkeypatch):
    _enable_bounded_typesafe(monkeypatch)
    need_id, _evidence_id, job_id = _seed_job(sessions)
    worker = _wire_worker(sessions, monkeypatch)
    monkeypatch.setattr(worker, "WORKER_ID", "fixture-worker-a")
    from gridlens.intelligence import intelligence_jobs

    provider_calls = 0

    def ambiguous_call(**_kwargs):
        nonlocal provider_calls
        provider_calls += 1
        raise KeyboardInterrupt

    monkeypatch.setattr(intelligence_jobs, "call_typesafe", ambiguous_call)
    with pytest.raises(KeyboardInterrupt):
        worker.run_one({}, job_ids=[job_id])
    result = intelligence_jobs.process_intelligence_job(job_id, "fixture-worker-a", 1)
    with sessions() as session:
        call = session.scalar(select(LogicalCall))
        history = intelligence_history(session, need_id)
    assert result["status"] == "blocked"
    assert call and call.status == "SENT_OUTCOME_UNKNOWN"
    assert provider_calls == 1
    assert history[0]["status"] == "blocked"


def test_conclusive_provider_schema_failure_is_terminal_not_unknown(sessions, monkeypatch):
    _enable_bounded_typesafe(monkeypatch)
    need_id, _evidence_id, job_id = _seed_job(sessions)
    worker = _wire_worker(sessions, monkeypatch)
    from gridlens.intelligence import intelligence_jobs

    monkeypatch.setattr(
        intelligence_jobs,
        "call_typesafe",
        lambda **_kwargs: {
            "model": "pinned-fixture-model",
            "provider_response_id": "fixture-invalid-response",
            "answers": {"answer": {"type": "choice", "choice": "NOT_ALLOWED"}},
        },
    )
    monkeypatch.setattr(worker, "WORKER_ID", "fixture-invalid-worker")
    assert worker.run_one({}, job_ids=[job_id]) is True
    with sessions() as session:
        call = session.scalar(select(LogicalCall))
        history = intelligence_history(session, need_id)
    assert call and call.status == "FAILED"
    assert call.result_payload == {"provider_response_ref": "response:fixture-invalid-response"}
    assert history[0]["status"] == "failed"
    assert history[0]["uncertain"] is False
