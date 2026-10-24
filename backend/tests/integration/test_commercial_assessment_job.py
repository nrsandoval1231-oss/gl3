import hashlib
import importlib.util
import json
import sys
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from threading import Event, Thread
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from gridlens.integrations.intelligence_provider import ProviderResponseError
from gridlens.intelligence.intelligence_jobs import (
    COMMERCIAL_ASSESSMENT_TASK,
    _current_payload,
    _digest,
    enqueue_intelligence,
)
from gridlens.persistence import database
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    Evidence,
    EvidencePackage,
    Job,
    LogicalCall,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Source,
)
from gridlens.settings import settings

_CLI_SPEC = importlib.util.spec_from_file_location(
    "run_commercial_assessment",
    Path(__file__).resolve().parents[3] / "scripts" / "run_commercial_assessment.py",
)
assessment_cli = importlib.util.module_from_spec(_CLI_SPEC)
assert _CLI_SPEC.loader is not None
_CLI_SPEC.loader.exec_module(assessment_cli)


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://operator:unused@127.0.0.1:55443/pipeline_m4_app",
        "postgresql://operator:unused@127.0.0.1:55443/pipeline_m6_app",
        "postgresql://operator:unused@127.0.0.1:55443/pipeline_test",
    ],
)
@pytest.mark.parametrize("execute", [False, True])
def test_commercial_assessment_guard_allows_existing_and_m6_targets(
    monkeypatch, database_url, execute
):
    monkeypatch.setattr(
        settings,
        "database_url",
        database_url,
    )
    assessment_cli._safe_database(execute=execute)


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://operator:unused@example.com:55443/pipeline_m6_app",
        "postgresql://operator:unused@127.0.0.1:5432/pipeline_m6_app",
        "postgresql://operator:unused@127.0.0.1:55443/pipeline_m5_app",
        "postgresql://operator:unused@127.0.0.1:55443/pipeline_m6_app?sslmode=disable",
    ],
)
@pytest.mark.parametrize("execute", [False, True])
def test_commercial_assessment_guard_rejects_nonexact_targets(monkeypatch, database_url, execute):
    monkeypatch.setattr(settings, "database_url", database_url)
    with pytest.raises(ValueError, match="exact isolated loopback database"):
        assessment_cli._safe_database(execute=execute)


@pytest.fixture
def sessions():
    target = make_url(settings.test_database_url)
    assert target.database and target.database.endswith("_test")
    assert target != make_url(settings.database_url)
    engine = create_engine(settings.test_database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def seed(sessions, monkeypatch):
    from gridlens.intelligence import evidence_packages

    monkeypatch.setattr(evidence_packages, "validate_package", lambda *_args, **_kwargs: None)
    source_id, project_id, need_id, observation_id, evidence_id, package_id = (
        "m4-fixture-source",
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    content = "Application stage: Permit application"
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    fact = {
        "field": "application_stage",
        "value": "Permit application",
        "label": "REPORTED",
        "citation": {
            "evidence_id": str(evidence_id),
            "evidence_hash": content_hash,
            "url": "https://example.invalid/source",
            "excerpt_location": {
                "field": "abstract",
                "start": content.index("Permit"),
                "end": len(content),
            },
        },
    }
    package_payload = {
        "package_key": "a" * 64,
        "processing_status": "COMPLETE_ADVISORY",
        "identity": {"project_id": str(project_id), "need_id": str(need_id)},
        "source_references": [
            {
                "evidence_id": str(evidence_id),
                "evidence_hash": content_hash,
                "observation_id": str(observation_id),
                "source_id": source_id,
                "url": "https://example.invalid/source",
            }
        ],
        "facts": [fact],
        "document_coverage": "RECORD_EXCERPT",
        "source_collection_status": "PARTIAL",
        "missing_fields": [],
        "unevaluated_dimensions": [
            "cross-claim contradictions",
            "commercial role classification",
        ],
    }
    with sessions.begin() as session:
        session.add(
            Source(
                id=source_id,
                publisher="Fixture",
                endpoint="https://example.invalid",
                family="test",
                geography="TX",
                industries=["power"],
                retrieval_method="test",
                enabled=True,
                registry_enabled=True,
                health={"collection_status": "PARTIAL"},
            )
        )
        session.flush()
        session.add(
            Project(
                id=project_id,
                identity_key=f"m4-{project_id}",
                name="Fixture project",
                location="Austin, TX",
                source_id=source_id,
                external_id="m4-fixture",
                identity_facts={"site_location": "Austin, TX"},
            )
        )
        session.flush()
        session.add(
            PowerNeed(
                id=need_id,
                project_id=project_id,
                activity_key="construction",
                rationale="fixture",
                supply="Unknown",
            )
        )
        session.add(
            Observation(
                id=observation_id,
                source_id=source_id,
                external_id="m4-observation",
                title="Fixture",
                abstract=content,
                url="https://example.invalid/source",
                content_hash=content_hash,
            )
        )
        session.flush()
        session.add(
            Evidence(
                id=evidence_id,
                observation_id=observation_id,
                content_hash=content_hash,
                title="Fixture",
                abstract=content,
                url="https://example.invalid/source",
                extraction_location="title and abstract",
            )
        )
        session.flush()
        session.add(NeedObservation(need_id=need_id, observation_id=observation_id))
        session.add(
            EvidencePackage(
                id=package_id,
                package_key="a" * 64,
                schema_version="evidence-package-v1",
                evidence_id=evidence_id,
                observation_id=observation_id,
                project_id=project_id,
                need_id=need_id,
                evidence_hash=content_hash,
                extractor_version="fixture",
                question_contract="fixture",
                provider="typesafe",
                model="jev-1.13.0",
                processing_status="COMPLETE_ADVISORY",
                payload=package_payload,
            )
        )
    return need_id, package_id, evidence_id


def _enable_m4(monkeypatch):
    values = {
        "intelligence_enabled": True,
        "intelligence_mode": "advisory",
        "intelligence_enabled_contracts": COMMERCIAL_ASSESSMENT_TASK,
        "intelligence_openai_enabled": True,
        "openai_api_key": SecretStr("fixture-only"),
        "intelligence_openai_reasoning_model": "gpt-6.1-sol",
        "intelligence_openai_reasoning_priced_model_id": "gpt-6.1-sol",
        "intelligence_openai_reasoning_pricing_verified": True,
        "intelligence_openai_reasoning_input_usd_per_million": Decimal("2"),
        "intelligence_openai_reasoning_output_usd_per_million": Decimal("10"),
        "intelligence_max_active_calls": 1,
        "intelligence_max_call_usd": Decimal("0.25"),
    }
    for name, value in values.items():
        monkeypatch.setattr(settings, name, value)
    for scope in ("global", "provider", "model", "source", "project"):
        for period in ("daily", "monthly"):
            monkeypatch.setattr(settings, f"intelligence_{scope}_{period}_calls", 10)
            monkeypatch.setattr(settings, f"intelligence_{scope}_{period}_usd", Decimal("10"))


def _wire_m4(sessions, monkeypatch):
    from gridlens.intelligence import intelligence_jobs
    from gridlens.jobs import worker

    monkeypatch.setattr(database, "SessionLocal", sessions)
    monkeypatch.setattr(intelligence_jobs, "SessionLocal", sessions)
    monkeypatch.setattr(worker, "SessionLocal", sessions)
    return worker, intelligence_jobs


def _valid_response(request, *, model="gpt-6.1-sol", service_tier="default"):
    payload = json.loads(request["input"])
    answer = {
        "disposition": "UNRESOLVED",
        "reason_code": "EXCERPT_INSUFFICIENT",
        "selected_fact_ids": [payload["package"]["facts"][0]["fact_id"]],
        "research_dimensions": [
            "REQUIRED_MW",
            "START_WINDOW",
            "BUYER_AUTHORITY",
            "SUPPLY_GAP",
            "DURATION",
            "RENTAL_VS_PERMANENT",
        ],
        "next_question_id": "TEMP_LOAD_MW",
    }
    return {
        "model": model,
        "provider_response_id": "fixture-m4-response",
        "latency_ms": 4,
        "service_tier": service_tier,
        "reported_usage": {"input_tokens": 100, "output_tokens": 25, "total_tokens": 125},
        "input_tokens": 100,
        "output_tokens": 25,
        "output": answer,
    }


def _queue_job(sessions, need_id, package_id):
    with sessions.begin() as session:
        return enqueue_intelligence(
            session,
            need_id=need_id,
            task_type=COMMERCIAL_ASSESSMENT_TASK,
            package_id=package_id,
        ).id


def test_exact_package_job_is_fresh_and_replay_payload_is_deterministic(sessions, monkeypatch):
    need_id, package_id, _evidence_id = seed(sessions, monkeypatch)
    with sessions.begin() as session:
        job = enqueue_intelligence(
            session, need_id=need_id, task_type=COMMERCIAL_ASSESSMENT_TASK, package_id=package_id
        )
        checkpoint = json.loads(job.checkpoint)
        first = checkpoint["payload"]
        second = _current_payload(session, checkpoint, need_id)
        assert first == second
        assert checkpoint["package_id"] == str(package_id)
        assert first["package"]["document_coverage"] == "RECORD_EXCERPT"
        assert first["package"]["source_collection_status"] == "PARTIAL"
        assert first["package"]["facts"][0]["fact_id"].startswith("f-")


def test_source_claim_acceptance_retraction_and_conflict_change_m4_context_and_freshness(
    sessions, monkeypatch
):
    need_id, package_id, _evidence_id = seed(sessions, monkeypatch)
    from gridlens.intelligence import project_state

    claims = {"temporary_load": {"status": "SUPPORTED", "value": "2 MW"}}
    monkeypatch.setattr(project_state, "current_research_state", lambda *a, **k: deepcopy(claims))
    with sessions.begin() as session:
        job = enqueue_intelligence(
            session, need_id=need_id, task_type=COMMERCIAL_ASSESSMENT_TASK, package_id=package_id
        )
        checkpoint = json.loads(job.checkpoint)
        accepted = _current_payload(session, checkpoint, need_id)
        assert accepted["need"]["accepted_source_claims"] == claims
        assert accepted["need"]["project_research_policy_version"]

        claims.clear()  # retraction removes the formerly accepted claim
        retracted = _current_payload(session, checkpoint, need_id)
        assert retracted["need"]["accepted_source_claims"] == {}
        assert retracted["need"]["state_version_digest"] != accepted["need"]["state_version_digest"]

        claims["temporary_load"] = {
            "status": "CONFLICT",
            "claims": [{"value": "2 MW"}, {"value": "4 MW"}],
        }
        conflicted = _current_payload(session, checkpoint, need_id)
        assert conflicted["need"]["accepted_source_claims"] == claims
        assert (
            conflicted["need"]["state_version_digest"] != retracted["need"]["state_version_digest"]
        )
        assert _digest(accepted) != _digest(retracted) != _digest(conflicted)


def test_package_row_payload_status_mismatch_blocks_enqueue(sessions, monkeypatch):
    need_id, package_id, _evidence_id = seed(sessions, monkeypatch)
    with sessions.begin() as session:
        package = session.get(EvidencePackage, package_id)
        package.payload = {**package.payload, "processing_status": "PREPARED"}
    with (
        sessions.begin() as session,
        pytest.raises(ValueError, match="row and payload status mismatch"),
    ):
        enqueue_intelligence(
            session, need_id=need_id, task_type=COMMERCIAL_ASSESSMENT_TASK, package_id=package_id
        )


def test_changed_retained_evidence_blocks_current_payload(sessions, monkeypatch):
    need_id, package_id, evidence_id = seed(sessions, monkeypatch)
    with sessions.begin() as session:
        job = enqueue_intelligence(
            session, need_id=need_id, task_type=COMMERCIAL_ASSESSMENT_TASK, package_id=package_id
        )
        checkpoint = json.loads(job.checkpoint)
        evidence = session.get(Evidence, evidence_id)
        evidence.content_hash = "f" * 64
    with sessions.begin() as session, pytest.raises(ValueError, match="no longer current"):
        _current_payload(session, checkpoint, need_id)


def test_package_observation_reference_must_match_current_observation(sessions, monkeypatch):
    need_id, package_id, _evidence_id = seed(sessions, monkeypatch)
    with sessions.begin() as session:
        package = session.get(EvidencePackage, package_id)
        package.payload = {
            **package.payload,
            "source_references": [
                {**package.payload["source_references"][0], "observation_id": str(uuid4())}
            ],
        }
    with sessions.begin() as session, pytest.raises(ValueError):
        enqueue_intelligence(
            session, need_id=need_id, task_type=COMMERCIAL_ASSESSMENT_TASK, package_id=package_id
        )


def test_changed_observation_hash_blocks_enqueue_without_provider(sessions, monkeypatch):
    need_id, package_id, _evidence_id = seed(sessions, monkeypatch)
    _enable_m4(monkeypatch)
    worker, jobs = _wire_m4(sessions, monkeypatch)
    calls = []
    monkeypatch.setattr(jobs, "call_openai_request", lambda **kwargs: calls.append(kwargs))
    with sessions.begin() as session:
        package = session.get(EvidencePackage, package_id)
        job = enqueue_intelligence(
            session, need_id=need_id, task_type=COMMERCIAL_ASSESSMENT_TASK, package_id=package_id
        )
        observation = session.get(Observation, package.observation_id)
        observation.content_hash = "e" * 64
        job_id = job.id
    worker.run_one({}, job_ids=[job_id])
    with sessions() as session:
        job = session.get(Job, job_id)
    assert json.loads(job.checkpoint)["status"] == "blocked"
    assert not calls


def test_worker_completes_exact_m4_and_reentry_does_not_dispatch_again(sessions, monkeypatch):
    _enable_m4(monkeypatch)
    need_id, package_id, _ = seed(sessions, monkeypatch)
    worker, jobs = _wire_m4(sessions, monkeypatch)
    calls = []

    def provider(**kwargs):
        calls.append(kwargs["request"])
        return _valid_response(kwargs["request"])

    monkeypatch.setattr(jobs, "call_openai_request", provider)
    job_id = _queue_job(sessions, need_id, package_id)
    assert worker.run_one({}, job_ids=[job_id]) is True
    assert worker.run_one({}, job_ids=[job_id]) is False
    with sessions() as session:
        job = session.get(Job, job_id)
        call = session.scalar(select(LogicalCall))
        need = session.get(PowerNeed, need_id)
        package = session.get(EvidencePackage, package_id)
    checkpoint = json.loads(job.checkpoint)
    assert checkpoint["status"] == "completed"
    assert call.status == "COMPLETED"
    assert call.result_payload["service_tier"] == "default"
    assert call.result_payload["reported_usage"]["input_tokens"] == 100
    assert call.result_payload["usage"]["cost_basis"] == "conservative_usage_estimate_not_invoice"
    assert (
        call.result_payload["next_question"]
        == "What exact-need evidence establishes temporary electrical load in MW?"
    )
    assert need.tier == "Signal"
    assert package.processing_status == "COMPLETE_ADVISORY"
    assert package.payload["unevaluated_dimensions"] == [
        "cross-claim contradictions",
        "commercial role classification",
    ]
    assert len(calls) == 1


def test_zero_call_cap_blocks_before_provider_dispatch(sessions, monkeypatch):
    _enable_m4(monkeypatch)
    monkeypatch.setattr(settings, "intelligence_max_call_usd", Decimal("0"))
    need_id, package_id, _ = seed(sessions, monkeypatch)
    worker, jobs = _wire_m4(sessions, monkeypatch)
    calls = []
    monkeypatch.setattr(jobs, "call_openai_request", lambda **kwargs: calls.append(kwargs))
    job_id = _queue_job(sessions, need_id, package_id)
    worker.run_one({}, job_ids=[job_id])
    with sessions() as session:
        job = session.get(Job, job_id)
        logical_calls = session.scalars(select(LogicalCall)).all()
    assert json.loads(job.checkpoint)["status"] == "blocked"
    assert not logical_calls
    assert not calls


def test_post_dispatch_evidence_change_is_stale_and_never_retried(sessions, monkeypatch):
    _enable_m4(monkeypatch)
    need_id, package_id, evidence_id = seed(sessions, monkeypatch)
    worker, jobs = _wire_m4(sessions, monkeypatch)
    calls = []

    def provider(**kwargs):
        calls.append(kwargs["request"])
        with sessions.begin() as session:
            evidence = session.get(Evidence, evidence_id)
            evidence.abstract = "Changed after dispatch"
        return _valid_response(kwargs["request"])

    monkeypatch.setattr(jobs, "call_openai_request", provider)
    job_id = _queue_job(sessions, need_id, package_id)
    worker.run_one({}, job_ids=[job_id])
    with sessions() as session:
        job = session.get(Job, job_id)
        call = session.scalar(select(LogicalCall))
    assert json.loads(job.checkpoint)["status"] == "stale"
    assert call.status == "COMPLETED"
    assert len(calls) == 1


def test_post_dispatch_observation_hash_change_cannot_accept_result(sessions, monkeypatch):
    _enable_m4(monkeypatch)
    need_id, package_id, _evidence_id = seed(sessions, monkeypatch)
    worker, jobs = _wire_m4(sessions, monkeypatch)
    calls = []

    provider_started = Event()
    update_committed = Event()

    def update_observation():
        assert provider_started.wait(timeout=5)
        with sessions.begin() as session:
            package = session.get(EvidencePackage, package_id)
            observation = session.get(Observation, package.observation_id)
            observation.content_hash = "b" * 64
        update_committed.set()

    updater = Thread(target=update_observation)
    updater.start()

    def provider(**kwargs):
        calls.append(kwargs["request"])
        with sessions() as session:
            job = session.scalar(select(Job).where(Job.target_id == need_id))
            checkpoint = json.loads(job.checkpoint)
            current = jobs._current_payload(session, checkpoint, need_id)
            assert jobs._digest(current) == checkpoint["request_digest"]
        provider_started.set()
        assert update_committed.wait(timeout=5)
        return _valid_response(kwargs["request"])

    monkeypatch.setattr(jobs, "call_openai_request", provider)
    job_id = _queue_job(sessions, need_id, package_id)
    worker.run_one({}, job_ids=[job_id])
    updater.join(timeout=5)
    assert not updater.is_alive()
    with sessions() as session:
        job = session.get(Job, job_id)
        call = session.scalar(select(LogicalCall))
    assert json.loads(job.checkpoint)["status"] == "stale"
    assert call.result_payload["validation_outcome"] == "STALE_CONTEXT"
    assert "disposition" not in call.result_payload
    assert len(calls) == 1
    monkeypatch.setattr(assessment_cli, "SessionLocal", sessions)
    monkeypatch.setattr(assessment_cli, "_safe_database", lambda **_kwargs: None)
    monkeypatch.setattr(settings, "openai_api_key", None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_commercial_assessment.py", "--package-id", str(package_id), "--replay"],
    )
    with pytest.raises(
        ValueError, match="Package observation version or evidence relation is stale"
    ):
        assessment_cli.main()


def test_publication_rolls_back_call_and_job_together(sessions, monkeypatch):
    _enable_m4(monkeypatch)
    need_id, package_id, _ = seed(sessions, monkeypatch)
    worker, jobs = _wire_m4(sessions, monkeypatch)
    monkeypatch.setattr(
        jobs, "call_openai_request", lambda **kwargs: _valid_response(kwargs["request"])
    )

    def fail_receipt(*_args, **_kwargs):
        raise RuntimeError("injected publication failure")

    monkeypatch.setattr(jobs, "_record_research_receipt", fail_receipt)
    job_id = _queue_job(sessions, need_id, package_id)

    # The worker reports that it consumed the lease even when its normal error
    # path records the failed Job. The publication transaction itself must not
    # settle the call before that outer error handling runs.
    assert worker.run_one({}, job_ids=[job_id]) is True

    with sessions() as session:
        job = session.get(Job, job_id)
        call = session.scalar(select(LogicalCall))
    checkpoint = json.loads(job.checkpoint)
    assert job.status == "queued"
    assert checkpoint["status"] == "dispatching"
    assert checkpoint.get("result") is None
    assert call.status == "SENT_OUTCOME_UNKNOWN"


def test_publication_retries_serialization_without_provider_redispatch(sessions, monkeypatch):
    _enable_m4(monkeypatch)
    need_id, package_id, _ = seed(sessions, monkeypatch)
    worker, jobs = _wire_m4(sessions, monkeypatch)
    calls = []
    original_current_payload = jobs._current_payload
    current_payload_attempts = 0

    class SerializationFailure(Exception):
        pgcode = "40001"

    def transient_serialization_failure(*args, **kwargs):
        nonlocal current_payload_attempts
        current_payload_attempts += 1
        if current_payload_attempts == 1:
            raise DBAPIError("SELECT", {}, SerializationFailure())
        return original_current_payload(*args, **kwargs)

    def provider(**kwargs):
        calls.append(kwargs["request"])
        return _valid_response(kwargs["request"])

    monkeypatch.setattr(jobs, "call_openai_request", provider)
    monkeypatch.setattr(jobs, "_current_payload", transient_serialization_failure)
    job_id = _queue_job(sessions, need_id, package_id)
    worker.run_one({}, job_ids=[job_id])

    with sessions() as session:
        job = session.get(Job, job_id)
        call = session.scalar(select(LogicalCall))
    assert current_payload_attempts == 2
    assert len(calls) == 1
    assert json.loads(job.checkpoint)["status"] == "completed"
    assert call.status == "COMPLETED"


@pytest.mark.parametrize(
    ("response_model", "input_tokens", "output_tokens", "expected"),
    [
        ("wrong-model", 100, 25, "MODEL_IDENTITY_MISMATCH"),
        ("gpt-6.1-sol", -1, 25, "INVALID_REPORTED_USAGE"),
        ("gpt-6.1-sol", None, 25, "MISSING_REPORTED_USAGE"),
        ("gpt-6.1-sol", 100, 6001, "ENFORCED_OUTPUT_BOUND_EXCEEDED"),
    ],
)
def test_invalid_response_identity_usage_or_output_is_quarantined(
    sessions, monkeypatch, response_model, input_tokens, output_tokens, expected
):
    _enable_m4(monkeypatch)
    need_id, package_id, _ = seed(sessions, monkeypatch)
    worker, jobs = _wire_m4(sessions, monkeypatch)
    calls = []

    def provider(**kwargs):
        calls.append(kwargs["request"])
        response = _valid_response(kwargs["request"], model=response_model)
        response["input_tokens"] = input_tokens
        response["output_tokens"] = output_tokens
        response["reported_usage"] = {"input_tokens": input_tokens, "output_tokens": output_tokens}
        return response

    monkeypatch.setattr(jobs, "call_openai_request", provider)
    job_id = _queue_job(sessions, need_id, package_id)
    worker.run_one({}, job_ids=[job_id])
    with sessions() as session:
        call = session.scalar(select(LogicalCall))
        job = session.get(Job, job_id)
    assert call.status == "SENT_OUTCOME_UNKNOWN", job.checkpoint
    assert call.result_payload["billing_quarantine"]["reason"] == expected
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("tier", "input_tokens", "expected"),
    [("flex", 100, "SERVICE_TIER_MISMATCH"), ("default", 999999, "ENFORCED_INPUT_BOUND_EXCEEDED")],
)
def test_wrong_tier_or_input_usage_exceeds_request_byte_bound_is_quarantined(
    sessions, monkeypatch, tier, input_tokens, expected
):
    _enable_m4(monkeypatch)
    need_id, package_id, _ = seed(sessions, monkeypatch)
    worker, jobs = _wire_m4(sessions, monkeypatch)

    def provider(**kwargs):
        response = _valid_response(kwargs["request"], service_tier=tier)
        response["input_tokens"] = input_tokens
        response["reported_usage"]["input_tokens"] = input_tokens
        return response

    monkeypatch.setattr(jobs, "call_openai_request", provider)
    job_id = _queue_job(sessions, need_id, package_id)
    worker.run_one({}, job_ids=[job_id])
    with sessions() as session:
        call = session.scalar(select(LogicalCall))
    assert call.result_payload["billing_quarantine"]["reason"] == expected
    if expected == "SERVICE_TIER_MISMATCH":
        assert call.result_payload["billing_quarantine"]["exposure_status"] == "UNKNOWN"


def test_uncertain_provider_send_is_never_retried(sessions, monkeypatch):
    _enable_m4(monkeypatch)
    need_id, package_id, _ = seed(sessions, monkeypatch)
    worker, jobs = _wire_m4(sessions, monkeypatch)
    calls = []

    def provider(**_kwargs):
        calls.append(True)
        raise ProviderResponseError("timeout", conclusive=False, response_received=False)

    monkeypatch.setattr(jobs, "call_openai_request", provider)
    job_id = _queue_job(sessions, need_id, package_id)
    worker.run_one({}, job_ids=[job_id])
    worker.run_one({}, job_ids=[job_id])
    with sessions() as session:
        call = session.scalar(select(LogicalCall))
    assert call.status == "SENT_OUTCOME_UNKNOWN"
    assert len(calls) == 1
