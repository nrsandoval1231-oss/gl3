import hashlib
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.evidence_packages import (
    build_package,
    materialize_package,
    update_status,
)
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    Evidence,
    EvidencePackage,
    Job,
    LogicalCall,
    Observation,
    Project,
    SignalDecision,
    Source,
)
from gridlens.settings import settings

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts" / "materialize_evidence_package.py"
SPEC = importlib.util.spec_from_file_location("materialize_evidence_package_cli", SCRIPT_PATH)
cli = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(cli)


@pytest.fixture
def evidence_db():
    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and (target.database == "test" or target.database.endswith("_test")), (
        "Refusing destructive setup without an explicit *_test database"
    )
    assert (target.host, target.port, target.database) != (
        application.host,
        application.port,
        application.database,
    )
    engine = create_engine(settings.test_database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def seed_evidence(
    session,
    *,
    content_hash="a" * 64,
    abstract="Applicant: ACME Builders\nFacility: Hall 2\nPermit numbers: TXR123",
):
    source = Source(
        id="synthetic-evidence-source",
        publisher="Synthetic source",
        endpoint="https://example.gov/records",
        family="official-records",
        geography="TX",
        industries=["energy"],
        retrieval_method="test",
        enabled=True,
        registry_enabled=True,
        health={"collection_status": "PARTIAL"},
    )
    session.add(source)
    session.flush()
    observation = Observation(
        id=uuid4(),
        source_id=source.id,
        external_id="record-1",
        title="Source record title",
        abstract=abstract,
        published_at=None,
        url="https://example.gov/records/1",
        content_hash=content_hash,
    )
    project = Project(
        id=uuid4(),
        identity_key="synthetic-project-1",
        name="Synthetic project",
        location="Texas",
        source_id=source.id,
        external_id=observation.external_id,
    )
    evidence = Evidence(
        id=uuid4(),
        observation_id=observation.id,
        content_hash=content_hash,
        title=observation.title,
        abstract=abstract,
        url=observation.url,
        extraction_location="summary excerpt",
        observed_at=datetime.now(UTC),
        provenance={},
    )
    session.add_all([observation, project, evidence])
    session.flush()
    return observation, evidence


def test_materialization_is_idempotent_and_row_payload_status_is_atomic(evidence_db):
    with evidence_db.begin() as session:
        _observation, evidence = seed_evidence(session)
        first = materialize_package(session, evidence.id)
        first_id = first.id
        first_key = first.package_key
        assert first.payload["document_coverage"] == "RECORD_EXCERPT"
        assert first.payload["source_collection_status"] == "PARTIAL"
        assert first.payload["entity_candidates"][0]["role"] == "applicant"
        assert first.payload["entity_candidates"][0]["value"] == "ACME Builders"
        assert first.payload["entity_candidates"][0]["citation"]["excerpt_location"] == {
            "field": "abstract",
            "start": 11,
            "end": 24,
        }
        permits = [fact for fact in first.payload["facts"] if fact["field"] == "permit_numbers"]
        assert len(permits) == 1
        assert permits[0]["value"] == "TXR123"
        assert {fact["label"] for fact in first.payload["facts"]} == {"REPORTED"}
        update_status(session, first, "INCOMPLETE", reason="synthetic test receipt")
        assert first.processing_status == first.payload["processing_status"] == "INCOMPLETE"
    with evidence_db.begin() as session:
        again = materialize_package(session, evidence.id)
        assert again.id == first_id
        assert again.package_key == first_key
        assert again.processing_status == again.payload["processing_status"] == "INCOMPLETE"


def test_stale_evidence_hash_is_rejected_and_new_version_gets_new_key(evidence_db):
    with evidence_db.begin() as session:
        observation, evidence = seed_evidence(session)
        original = materialize_package(session, evidence.id)
        original_key = original.package_key
        observation.content_hash = "b" * 64
        with pytest.raises(ValueError, match="Stale evidence hash"):
            build_package(session, evidence.id)
        replacement = Evidence(
            id=uuid4(),
            observation_id=observation.id,
            content_hash=observation.content_hash,
            title=evidence.title,
            abstract="Changed source excerpt.",
            url=evidence.url,
            extraction_location=evidence.extraction_location,
            provenance={},
        )
        session.add(replacement)
        session.flush()
        new_package = materialize_package(session, replacement.id)
        assert new_package.package_key != original_key
        assert (
            session.scalar(
                select(EvidencePackage).where(EvidencePackage.package_key == original_key)
            )
            is not None
        )


def _registry(monkeypatch):
    from gridlens.ingestion import registry

    monkeypatch.setattr(
        registry,
        "load_registry",
        lambda: [{"id": "synthetic-evidence-source", "enabled": True}],
    )


def test_policy_or_credentials_block_without_dispatch(evidence_db, monkeypatch):
    _registry(monkeypatch)
    monkeypatch.setattr(cli, "SessionLocal", evidence_db)
    with evidence_db.begin() as session:
        _observation, evidence = seed_evidence(session)
        package = materialize_package(session, evidence.id)
        package_id = package.id

    status, call_id = cli._execute(package_id)
    assert status == "BLOCKED"
    assert call_id is None
    with evidence_db() as session:
        package = session.get(EvidencePackage, package_id)
        assert package.processing_status == package.payload["processing_status"] == "BLOCKED"
        assert session.scalar(select(func.count()).select_from(LogicalCall)) == 0
        assert session.scalar(select(func.count()).select_from(Job)) == 0


def test_product_database_guard_never_allows_test_database_for_dispatch(monkeypatch):
    monkeypatch.setattr(settings, "database_url", settings.test_database_url)
    with pytest.raises(ValueError, match="isolated loopback database"):
        cli._safe_database(dispatch=True)


def _insert_call_history(
    session,
    observation,
    evidence,
    *,
    call_status="COMPLETED",
    existing_job=None,
    decision_dimensions=None,
    decision_value="REVIEW",
):
    task_key = cli._task_key(observation.id, evidence.content_hash)
    call_id = uuid4()
    job_id = existing_job.id if existing_job is not None else uuid4()
    result = {
        "model": "jev-1.13.0",
        "answers": {
            name: {"type": "noul", "noul": 0.5}
            for name in (
                "physical_project_event",
                "meaningful_new_activity",
                "commercial_relevance",
                "temporary_power_relevance",
                "routine_maintenance",
                "transient_event",
            )
        },
    }
    checkpoint = {
        "evidence_id": str(evidence.id),
        "content_hash": evidence.content_hash,
        "policy_version": "signal-display-v2",
        "logical_call_id": str(call_id),
    }
    job = existing_job or Job(
        id=job_id,
        source_id=observation.source_id,
        kind="signal_adjudication",
        target_id=observation.id,
        status="succeeded",
        checkpoint=json.dumps(checkpoint),
    )
    job.checkpoint = json.dumps(checkpoint)
    evidence_digest = hashlib.sha256(
        json.dumps(
            str(evidence.id), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
    ).hexdigest()
    call = LogicalCall(
        id=call_id,
        fingerprint=hashlib.sha256(str(call_id).encode()).hexdigest(),
        task_type="SIGNAL_ADJUDICATION",
        task_key=task_key,
        evidence_digest=evidence_digest,
        context_digest="d" * 64,
        prompt_contract="legacy-signal_adjudication-v1",
        provider="typesafe",
        model="jev-1.13.0",
        policy_version="legacy-shared-ledger-v1",
        source_id=observation.source_id,
        lease_authority="job",
        job_id=job_id,
        status=call_status,
        dispatched_at=datetime.now(UTC)
        if call_status in {"SENT_OUTCOME_UNKNOWN", "FAILED", "RECONCILED", "QUARANTINED"}
        else None,
        result_payload=result if call_status == "COMPLETED" else None,
    )
    session.add_all([job, call])
    if call_status == "COMPLETED":
        session.add(
            SignalDecision(
                observation_id=observation.id,
                content_hash=evidence.content_hash,
                policy_version="signal-display-v2",
                decision=decision_value,
                source="jev",
                model_version="jev-1.13.0",
                dimensions=decision_dimensions or {name: 0.5 for name in result["answers"]},
                reason="synthetic test receipt",
            )
        )
    session.flush()
    return call, job


def test_completed_receipt_requires_exact_call_job_and_policy(evidence_db, monkeypatch):
    _registry(monkeypatch)
    monkeypatch.setattr(cli, "SessionLocal", evidence_db)
    with evidence_db.begin() as session:
        observation, evidence = seed_evidence(session)
        package = materialize_package(session, evidence.id)
        package_id = package.id
        call, _job = _insert_call_history(session, observation, evidence)

    status, reused_call_id = cli._execute(package_id)
    assert status == "COMPLETE_ADVISORY"
    assert reused_call_id == str(call.id)
    with evidence_db() as session:
        package = session.get(EvidencePackage, package_id)
        assert (
            package.processing_status == package.payload["processing_status"] == "COMPLETE_ADVISORY"
        )
        assert package.logical_call_id == call.id
        assert package.payload["advisory"]["model"] == "jev-1.13.0"


@pytest.mark.parametrize("path", ["prior", "post_worker", "replay"])
@pytest.mark.parametrize("tamper", ["dimensions", "mapped_decision"])
def test_completion_requires_shared_exact_response_and_decision_proof(
    evidence_db, monkeypatch, capsys, path, tamper
):
    _registry(monkeypatch)
    monkeypatch.setattr(cli, "SessionLocal", evidence_db)
    monkeypatch.setattr(settings, "database_url", settings.test_database_url)
    from gridlens.intelligence import intelligence_jobs
    from gridlens.jobs import worker

    monkeypatch.setattr(
        intelligence_jobs,
        "_enabled",
        lambda *_args, **_kwargs: (True, "typesafe", "jev-1.13.0", ""),
    )
    with evidence_db.begin() as session:
        observation, evidence = seed_evidence(session)
        package = materialize_package(session, evidence.id)
        package_id, evidence_id = package.id, evidence.id
        if path in {"prior", "replay"}:
            call, _job = _insert_call_history(session, observation, evidence)
            if path == "prior" and tamper == "dimensions":
                decision = session.scalar(select(SignalDecision))
                decision.dimensions = {**decision.dimensions, "commercial_relevance": 0.1}
            elif path == "prior":
                session.scalar(select(SignalDecision)).decision = "HOLD"

    if path == "post_worker":

        def inject_completed_receipt(_definitions, *, job_ids=None):
            with evidence_db.begin() as session:
                job = session.get(Job, job_ids[0])
                observation = session.get(Observation, job.target_id)
                evidence = session.scalar(
                    select(Evidence).where(Evidence.observation_id == observation.id)
                )
                _insert_call_history(
                    session,
                    observation,
                    evidence,
                    existing_job=job,
                    decision_dimensions=(
                        {
                            name: 0.5
                            for name in (
                                "physical_project_event",
                                "meaningful_new_activity",
                                "commercial_relevance",
                                "temporary_power_relevance",
                                "routine_maintenance",
                                "transient_event",
                            )
                        }
                        | {"commercial_relevance": 0.1}
                        if tamper == "dimensions"
                        else None
                    ),
                    decision_value="HOLD" if tamper == "mapped_decision" else "REVIEW",
                )
                job.status = "succeeded"

        monkeypatch.setattr(worker, "run_one", inject_completed_receipt)
        status, returned_id = cli._execute(package_id)
        assert status == "INCOMPLETE"
        assert returned_id is not None
        with evidence_db() as session:
            package = session.get(EvidencePackage, package_id)
            assert package.logical_call_id == UUID(returned_id)
            assert package.payload["logical_call_id"] == returned_id
    elif path == "prior":
        status, returned_id = cli._execute(package_id)
        assert (status, returned_id) == ("INCOMPLETE", str(call.id))
    else:
        assert cli._execute(package_id)[0] == "COMPLETE_ADVISORY"
        with evidence_db.begin() as session:
            observation = session.get(Observation, package.observation_id)
            decision = session.scalar(select(SignalDecision))
            if tamper == "dimensions":
                decision.dimensions = {**decision.dimensions, "commercial_relevance": 0.1}
            else:
                decision.decision = "HOLD"
            unrelated = Job(
                source_id=observation.source_id,
                kind="signal_adjudication",
                target_id=uuid4(),
                status="queued",
            )
            session.add(unrelated)
            session.flush()
            unrelated_id = unrelated.id
        monkeypatch.setattr(
            "sys.argv",
            ["materialize_evidence_package.py", "--evidence-id", str(evidence_id), "--replay"],
        )
        monkeypatch.setattr(cli, "_execute", lambda *_args: pytest.fail("invalid replay executed"))
        with pytest.raises(ValueError, match="exact call response and mapped decision"):
            cli.main()
        with evidence_db() as session:
            package = session.get(EvidencePackage, package_id)
            assert package.processing_status == package.payload["processing_status"] == "INCOMPLETE"
            assert package.logical_call_id == call.id
            assert package.payload["logical_call_id"] == str(call.id)
            assert package.payload["advisory"] is None
            assert session.scalar(select(func.count()).select_from(LogicalCall)) == 1
            assert session.scalar(select(func.count()).select_from(Job)) == 2
            assert session.get(Evidence, evidence.id).content_hash == "a" * 64
            assert session.get(Job, unrelated_id).status == "queued"
    with evidence_db() as session:
        assert session.scalar(select(func.count()).select_from(LogicalCall)) == 1


def test_final_invalid_completion_is_persisted_before_error(evidence_db, monkeypatch):
    _registry(monkeypatch)
    monkeypatch.setattr(cli, "SessionLocal", evidence_db)
    monkeypatch.setattr(cli, "_safe_database", lambda **_kwargs: None)
    from gridlens.intelligence import intelligence_jobs, signal_adjudication
    from gridlens.jobs import worker

    monkeypatch.setattr(
        intelligence_jobs,
        "_enabled",
        lambda *_args, **_kwargs: (True, "typesafe", "jev-1.13.0", ""),
    )
    monkeypatch.setattr(
        worker, "run_one", lambda *_a, **_k: pytest.fail("existing receipt must not dispatch")
    )
    monkeypatch.setattr(
        signal_adjudication,
        "_jev_call",
        lambda *_a, **_k: pytest.fail("existing receipt must not call provider"),
    )
    with evidence_db.begin() as session:
        observation, evidence = seed_evidence(session)
        package = materialize_package(session, evidence.id)
        package_id, evidence_id = package.id, evidence.id
        call, job = _insert_call_history(session, observation, evidence)
        job.status = "succeeded"
        unrelated = Job(
            source_id=observation.source_id,
            kind="signal_adjudication",
            target_id=uuid4(),
            status="queued",
        )
        session.add(unrelated)
        session.flush()
        unrelated_id = unrelated.id

    execute = cli._execute

    def complete_then_tamper(package_uuid):
        status, call_id = execute(package_uuid)
        assert (status, call_id) == ("COMPLETE_ADVISORY", str(call.id))
        with evidence_db.begin() as session:
            session.scalar(select(SignalDecision)).decision = "HOLD"
        return status, call_id

    monkeypatch.setattr(cli, "_execute", complete_then_tamper)
    monkeypatch.setattr(
        "sys.argv",
        ["materialize_evidence_package.py", "--evidence-id", str(evidence_id), "--execute-jev"],
    )
    with pytest.raises(ValueError, match="exact call response and mapped decision"):
        cli.main()
    with evidence_db() as session:
        package = session.get(EvidencePackage, package_id)
        assert package.processing_status == package.payload["processing_status"] == "INCOMPLETE"
        assert package.logical_call_id == call.id
        assert package.payload["logical_call_id"] == str(call.id)
        assert package.payload["advisory"] is None
        assert session.scalar(select(func.count()).select_from(LogicalCall)) == 1
        assert session.scalar(select(func.count()).select_from(Job)) == 2
        assert session.get(Evidence, evidence.id).content_hash == "a" * 64
        assert session.get(Job, unrelated_id).status == "queued"


@pytest.mark.parametrize("mismatch", ["policy", "source", "multiple"])
def test_active_jobs_must_be_unique_and_exact_before_worker_dispatch(
    evidence_db, monkeypatch, mismatch
):
    _registry(monkeypatch)
    monkeypatch.setattr(cli, "SessionLocal", evidence_db)
    from gridlens.intelligence import intelligence_jobs
    from gridlens.jobs import worker

    monkeypatch.setattr(
        intelligence_jobs,
        "_enabled",
        lambda *_args, **_kwargs: (True, "typesafe", "jev-1.13.0", ""),
    )
    monkeypatch.setattr(
        worker,
        "run_one",
        lambda *_a, **_k: pytest.fail("invalid active job dispatched"),
    )
    with evidence_db.begin() as session:
        observation, evidence = seed_evidence(session)
        package = materialize_package(session, evidence.id)
        package_id = package.id
        other_source = Source(
            id="other-source",
            publisher="other",
            endpoint="https://example.gov/other",
            family="official-records",
            geography="TX",
            industries=["energy"],
            retrieval_method="test",
            enabled=True,
            registry_enabled=True,
            health={},
        )
        session.add(other_source)
        session.flush()
        checkpoint = {
            "evidence_id": str(evidence.id),
            "content_hash": evidence.content_hash,
            "policy_version": "signal-display-v2",
        }
        job = Job(
            source_id="other-source" if mismatch == "source" else observation.source_id,
            kind="signal_adjudication",
            target_id=observation.id,
            status="queued",
            checkpoint=json.dumps(checkpoint),
        )
        if mismatch == "policy":
            checkpoint["policy_version"] = "stale-policy"
            job.checkpoint = json.dumps(checkpoint)
        session.add(job)
        if mismatch == "multiple":
            session.add(
                Job(
                    source_id=observation.source_id,
                    kind="signal_adjudication",
                    target_id=observation.id,
                    status="running",
                    checkpoint=json.dumps(checkpoint),
                )
            )
        unrelated = Job(
            source_id=observation.source_id,
            kind="signal_adjudication",
            target_id=uuid4(),
            status="queued",
        )
        session.add(unrelated)
        session.flush()
        unrelated_id = unrelated.id

    status, call_id = cli._execute(package_id)
    assert (status, call_id) == ("BLOCKED", None)
    with evidence_db() as session:
        assert session.scalar(select(func.count()).select_from(LogicalCall)) == 0
        assert session.get(Job, unrelated_id).status == "queued"
        package = session.get(EvidencePackage, package_id)
        assert package.processing_status == package.payload["processing_status"] == "BLOCKED"


@pytest.mark.parametrize(
    "mismatch",
    [
        "task_type",
        "provider",
        "model",
        "contract",
        "policy",
        "evidence_digest",
        "job_checkpoint",
        "decision_source",
        "malformed_response",
        "job_terminal_error",
    ],
)
def test_completed_but_nonmatching_or_malformed_receipt_is_not_advisory(
    evidence_db, monkeypatch, mismatch
):
    _registry(monkeypatch)
    monkeypatch.setattr(cli, "SessionLocal", evidence_db)
    with evidence_db.begin() as session:
        observation, evidence = seed_evidence(session)
        package = materialize_package(session, evidence.id)
        package_id = package.id
        call, job = _insert_call_history(session, observation, evidence)
        if mismatch == "task_type":
            call.task_type = "OTHER_TASK"
        elif mismatch == "provider":
            call.provider = "openai"
        elif mismatch == "model":
            call.model = "jev-other"
        elif mismatch == "contract":
            call.prompt_contract = "other-contract"
        elif mismatch == "policy":
            call.policy_version = "other-policy"
        elif mismatch == "evidence_digest":
            call.evidence_digest = "e" * 64
        elif mismatch == "job_checkpoint":
            checkpoint = json.loads(job.checkpoint)
            checkpoint["content_hash"] = "f" * 64
            job.checkpoint = json.dumps(checkpoint)
        elif mismatch == "decision_source":
            decision = session.scalar(select(SignalDecision))
            decision.source = "deterministic"
        elif mismatch == "malformed_response":
            call.result_payload = {"model": "jev-1.13.0", "answers": {}}
        elif mismatch == "job_terminal_error":
            job.error = "terminal failure"

    status, returned_call_id = cli._execute(package_id)
    assert status == "INCOMPLETE"
    assert returned_call_id == str(call.id)
    with evidence_db() as session:
        package = session.get(EvidencePackage, package_id)
        assert package.processing_status == package.payload["processing_status"] == "INCOMPLETE"
        assert session.scalar(select(func.count()).select_from(LogicalCall)) == 1
        assert session.scalar(select(func.count()).select_from(Job)) == 1


def test_uncertain_call_is_incomplete_and_never_retried(evidence_db, monkeypatch):
    _registry(monkeypatch)
    monkeypatch.setattr(cli, "SessionLocal", evidence_db)
    from gridlens.intelligence import intelligence_jobs

    monkeypatch.setattr(
        intelligence_jobs,
        "_enabled",
        lambda *_args, **_kwargs: pytest.fail("uncertain call must be inspected before policy"),
    )
    with evidence_db.begin() as session:
        observation, evidence = seed_evidence(session)
        package = materialize_package(session, evidence.id)
        package_id = package.id
        call, _job = _insert_call_history(
            session, observation, evidence, call_status="SENT_OUTCOME_UNKNOWN"
        )

    status, call_id = cli._execute(package_id)
    assert status == "INCOMPLETE"
    assert call_id == str(call.id)
    with evidence_db() as session:
        assert session.scalar(select(func.count()).select_from(LogicalCall)) == 1
        package = session.get(EvidencePackage, package_id)
        assert package.processing_status == package.payload["processing_status"] == "INCOMPLETE"


@pytest.mark.parametrize("call_status", ["FAILED", "RECONCILED"])
def test_sent_failed_or_reconciled_call_is_incomplete_without_retry(
    evidence_db, monkeypatch, call_status
):
    _registry(monkeypatch)
    monkeypatch.setattr(cli, "SessionLocal", evidence_db)
    with evidence_db.begin() as session:
        observation, evidence = seed_evidence(session)
        package = materialize_package(session, evidence.id)
        package_id = package.id
        call, _job = _insert_call_history(session, observation, evidence, call_status=call_status)
    status, returned_id = cli._execute(package_id)
    assert (status, returned_id) == ("INCOMPLETE", str(call.id))
    with evidence_db() as session:
        package = session.get(EvidencePackage, package_id)
        assert package.processing_status == package.payload["processing_status"] == "INCOMPLETE"
        assert session.scalar(select(func.count()).select_from(LogicalCall)) == 1


def test_pre_dispatch_not_sent_call_is_blocked_without_retry(evidence_db, monkeypatch):
    _registry(monkeypatch)
    monkeypatch.setattr(cli, "SessionLocal", evidence_db)
    with evidence_db.begin() as session:
        observation, evidence = seed_evidence(session)
        package = materialize_package(session, evidence.id)
        package_id = package.id
        call, _job = _insert_call_history(session, observation, evidence, call_status="NOT_SENT")
    status, returned_id = cli._execute(package_id)
    assert (status, returned_id) == ("BLOCKED", str(call.id))
    with evidence_db() as session:
        package = session.get(EvidencePackage, package_id)
        assert package.processing_status == package.payload["processing_status"] == "BLOCKED"
        assert session.scalar(select(func.count()).select_from(LogicalCall)) == 1


def test_multiple_prior_intents_are_ambiguous_and_never_select_a_receipt(evidence_db, monkeypatch):
    _registry(monkeypatch)
    monkeypatch.setattr(cli, "SessionLocal", evidence_db)
    with evidence_db.begin() as session:
        observation, evidence = seed_evidence(session)
        package = materialize_package(session, evidence.id)
        package_id = package.id
        _insert_call_history(session, observation, evidence, call_status="SENT_OUTCOME_UNKNOWN")
        _insert_call_history(session, observation, evidence)

    status, call_id = cli._execute(package_id)
    assert (status, call_id) == ("INCOMPLETE", None)
    with evidence_db() as session:
        package = session.get(EvidencePackage, package_id)
        assert package.payload["reason"] == "AMBIGUOUS_PRIOR_CALLS_NO_REDISPATCH"
        assert session.scalar(select(func.count()).select_from(LogicalCall)) == 2


def test_worker_budget_denial_is_blocked_and_never_dispatches(evidence_db, monkeypatch):
    _registry(monkeypatch)
    from decimal import Decimal

    from gridlens.integrations import legacy_calls
    from gridlens.intelligence import intelligence_jobs, signal_adjudication
    from gridlens.jobs import worker
    from gridlens.persistence import database

    for module in (cli, legacy_calls, worker, database):
        monkeypatch.setattr(module, "SessionLocal", evidence_db)

    def enabled(*_args, **_kwargs):
        return True, "typesafe", "jev-1.13.0", ""

    monkeypatch.setattr(intelligence_jobs, "_enabled", enabled)
    monkeypatch.setattr(legacy_calls, "_enabled", enabled)
    monkeypatch.setattr(intelligence_jobs, "_cost_bound", lambda *_a, **_k: Decimal("0.01"))
    monkeypatch.setattr(legacy_calls, "_cost_bound", lambda *_a, **_k: Decimal("0.01"))

    def zero_caps():
        return {
            scope: {
                "daily": 0,
                "monthly": 0,
                "daily_usd": Decimal("0"),
                "monthly_usd": Decimal("0"),
            }
            for scope in ("global", "provider", "model", "source", "project")
        }

    monkeypatch.setattr(intelligence_jobs, "_caps", zero_caps)
    monkeypatch.setattr(legacy_calls, "_caps", zero_caps)
    monkeypatch.setattr(settings, "intelligence_financial_budget_mode", "finite")
    monkeypatch.setattr(settings, "intelligence_max_active_calls", 1)
    monkeypatch.setattr(settings, "intelligence_max_call_usd", Decimal("0.01"))
    attempts = []

    def forbidden_provider(*_args, **_kwargs):
        attempts.append("attempt")
        raise AssertionError("provider dispatch must not occur after zero-cap denial")

    monkeypatch.setattr(signal_adjudication, "_jev_call", forbidden_provider)
    reserve_results = []
    reserve = legacy_calls.reserve_call

    def record_reserve(*args, **kwargs):
        result = reserve(*args, **kwargs)
        reserve_results.append((result.status, result.blocked_reason, result.call_id))
        return result

    monkeypatch.setattr(legacy_calls, "reserve_call", record_reserve)
    with evidence_db.begin() as session:
        observation, evidence = seed_evidence(session)
        package = materialize_package(session, evidence.id)
        package_id = package.id
        source_hash = evidence.content_hash
        unrelated = Job(
            source_id=observation.source_id,
            kind="signal_adjudication",
            target_id=uuid4(),
            status="queued",
        )
        session.add(unrelated)
        session.flush()
        unrelated_id = unrelated.id

    status, call_id = cli._execute(package_id)
    assert status == "BLOCKED"
    assert call_id is None
    assert attempts == []
    assert reserve_results == [("BLOCKED", "GLOBAL_DAILY_CAP_ZERO", None)]
    with evidence_db() as session:
        package = session.get(EvidencePackage, package_id)
        assert package.payload["reason"] == "BLOCKED:GLOBAL_DAILY_CAP_ZERO"
        assert package.processing_status == package.payload["processing_status"] == "BLOCKED"
        assert session.scalar(select(func.count()).select_from(LogicalCall)) == 0
        evidence = session.scalar(select(Evidence))
        assert evidence.content_hash == source_hash
        jobs = session.scalars(select(Job)).all()
        exact = next(job for job in jobs if job.target_id == package.observation_id)
        assert exact.status == "succeeded"
        assert exact.error == "BLOCKED:GLOBAL_DAILY_CAP_ZERO"
        checkpoint = json.loads(exact.checkpoint)
        assert checkpoint["legacy_call_block_reason"] == "GLOBAL_DAILY_CAP_ZERO"
        assert session.get(Job, unrelated_id).status == "queued"


def test_input_change_after_worker_prevents_advisory_completion(evidence_db, monkeypatch):
    _registry(monkeypatch)
    monkeypatch.setattr(cli, "SessionLocal", evidence_db)
    from gridlens.intelligence import intelligence_jobs
    from gridlens.jobs import worker

    monkeypatch.setattr(
        intelligence_jobs,
        "_enabled",
        lambda *_args, **_kwargs: (True, "typesafe", "jev-1.13.0", ""),
    )

    def stale_after_worker(_definitions, *, job_ids=None):
        with evidence_db.begin() as session:
            job = session.get(Job, job_ids[0])
            observation = session.get(Observation, job.target_id)
            evidence = session.scalar(
                select(Evidence).where(Evidence.observation_id == observation.id)
            )
            _insert_call_history(
                session,
                observation,
                evidence,
                call_status="SENT_OUTCOME_UNKNOWN",
                existing_job=job,
            )
            job.status = "succeeded"
            observation.content_hash = "b" * 64

    monkeypatch.setattr(worker, "run_one", stale_after_worker)
    with evidence_db.begin() as session:
        _observation, evidence = seed_evidence(session)
        package = materialize_package(session, evidence.id)
        package_id = package.id

    status, call_id = cli._execute(package_id)
    assert status == "INCOMPLETE"
    assert call_id is not None
    with evidence_db() as session:
        package = session.get(EvidencePackage, package_id)
        assert package.payload["reason"] == "POST_WORKER_INPUT_CHANGED_NO_RETRY"
        assert package.processing_status == "INCOMPLETE"
        assert package.logical_call_id == UUID(call_id)
        assert session.scalar(select(func.count()).select_from(LogicalCall)) == 1


def test_worker_receives_only_one_exact_job_and_leaves_other_jobs_queued(evidence_db, monkeypatch):
    _registry(monkeypatch)
    monkeypatch.setattr(cli, "SessionLocal", evidence_db)
    from gridlens.intelligence import intelligence_jobs
    from gridlens.jobs import worker

    monkeypatch.setattr(
        intelligence_jobs,
        "_enabled",
        lambda *_args, **_kwargs: (True, "typesafe", "jev-1.13.0", ""),
    )
    observed = {}

    def only_exact_job(definitions, *, job_ids=None):
        observed["definitions"] = definitions
        observed["job_ids"] = job_ids
        return False

    monkeypatch.setattr(worker, "run_one", only_exact_job)
    with evidence_db.begin() as session:
        observation, evidence = seed_evidence(session)
        package = materialize_package(session, evidence.id)
        package_id = package.id
        unrelated = Job(
            source_id=observation.source_id,
            kind="signal_adjudication",
            target_id=uuid4(),
            status="queued",
        )
        session.add(unrelated)
        session.flush()
        unrelated_id = unrelated.id

    status, call_id = cli._execute(package_id)
    assert status == "INCOMPLETE"
    assert call_id is None
    assert len(observed["job_ids"]) == 1
    with evidence_db() as session:
        exact = session.get(Job, observed["job_ids"][0])
        assert exact.target_id != unrelated_id
        assert session.get(Job, unrelated_id).status == "queued"
        assert session.scalar(select(func.count()).select_from(LogicalCall)) == 0


def test_replay_keeps_package_digest_jobs_calls_and_dispatch_times(
    evidence_db, monkeypatch, capsys
):
    monkeypatch.setattr(cli, "SessionLocal", evidence_db)
    monkeypatch.setattr(settings, "database_url", settings.test_database_url)
    _registry(monkeypatch)
    with evidence_db.begin() as session:
        observation, evidence = seed_evidence(session)
        package = materialize_package(session, evidence.id)
        package_id = package.id
        _insert_call_history(session, observation, evidence)

    assert cli._execute(package_id)[0] == "COMPLETE_ADVISORY"
    with evidence_db() as session:
        package = session.get(EvidencePackage, package_id)
        expected_digest = cli._json_digest(package.payload)

    monkeypatch.setattr(
        "sys.argv",
        ["materialize_evidence_package.py", "--evidence-id", str(evidence.id), "--replay"],
    )
    assert cli.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["package_id"] == str(package_id)
    assert report["package_digest"] == expected_digest
    assert report["replay_counts"] == {
        "jobs": 1,
        "calls": 1,
        "dispatch_timestamps": [None],
    }
    with evidence_db() as session:
        package = session.get(EvidencePackage, package_id)
        assert cli._json_digest(package.payload) == expected_digest
        assert session.scalar(select(func.count()).select_from(Job)) == 1
        assert session.scalar(select(func.count()).select_from(LogicalCall)) == 1
