"""Prepare or run six fixed ordinary jobs; never enable a polling worker.

Execution requires a separately approved release gate and an absent durable
journal. A second invocation cannot dispatch. Provider uncertainty is retained.
The host must drain the ordinary worker and keep new contracts disabled there.
"""
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

if sys.flags.optimize != 0:
    raise RuntimeError("Controller requires Python optimization disabled")

from sqlalchemy import func, select, text

from gridlens.integrations.legacy_calls import _digest, perform_legacy_call
from gridlens.integrations.logical_calls import fingerprint_call
from gridlens.intelligence import intelligence_jobs as policy
from gridlens.intelligence import signal_adjudication as signals
from gridlens.intelligence import titles
from gridlens.jobs import worker
from gridlens.persistence.database import SessionLocal
from gridlens.persistence.models import (
    Evidence, Interpretation, Job, LogicalCall, Observation, PowerNeed,
    PowerNeedTitle, PowerNeedTitleVersion, Project, SignalDecision, Source,
)
from gridlens.settings import settings

SCOPE_HASH = "ce5b146ab3759a9af012ad521c15450c9621a64abc387c9999a4eb071d453cfc"
ACTIVATION_HASH = "5f6d5a44e6e740aed583d1269babdaa21eb9a2cfd954e952047cd499526608d5"
LIVE_DATABASE = "gridlens_restore_20261014"
ALLOWED_PREFLIGHT_DATABASES = {LIVE_DATABASE, "title02_retained_migration_20261019"}


def checked_json(path, expected):
    raw = Path(path).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == expected, "Reviewed input changed"
    return json.loads(raw)


def setting_value(name, value):
    current = getattr(settings, name)
    if isinstance(current, bool):
        assert value in ("true", "false")
        return value == "true"
    if isinstance(current, Decimal):
        return Decimal(value)
    if isinstance(current, int):
        return int(value)
    return value


def call_identity(task, key, payload, source_id, project_id):
    enabled, provider, model, reason = policy._enabled(task, payload=payload)
    assert enabled, reason
    billing = policy._billing_policy_identity(provider, model, task)
    evidence_digest = _digest(payload.get("evidence", payload.get("evidence_id", _digest(payload))))
    context_digest = _digest({"payload": payload, "billing_policy": billing})
    contract = "legacy-" + task.casefold() + "-v1"
    fingerprint = fingerprint_call(task_type=task, task_key=key[:200],
        evidence_digest=evidence_digest, context_digest=context_digest,
        prompt_contract=contract, provider=provider, model=model,
        policy_version="legacy-shared-ledger-v1")
    bound = policy._cost_bound(provider, task, payload)
    assert Decimal(0) < bound <= Decimal("0.01")
    return {"task_type": task, "task_key": key[:200], "provider": provider,
            "model": model, "fingerprint": fingerprint, "evidence_digest": evidence_digest,
            "context_digest": context_digest, "billing_policy": billing,
            "reservation_usd": str(bound), "source_id": source_id,
            "project_id": str(project_id) if project_id else None}


def inspect_record(session, item, expected):
    observation = session.get(Observation, UUID(item["observation_id"]))
    evidence = session.get(Evidence, UUID(item["evidence_id"]))
    need = session.get(PowerNeed, UUID(item["need_id"]))
    project = session.get(Project, UUID(item["project_id"]))
    source = session.get(Source, item["source_id"])
    assert all((observation, evidence, need, project, source)), "Selected record missing"
    assert source.enabled and source.registry_enabled and need.active, "Selected record disabled"
    assert observation.source_id == source.id and evidence.observation_id == observation.id
    assert need.project_id == project.id and project.source_id == source.id
    assert evidence.url == item["url"]
    assert observation.content_hash == evidence.content_hash == item["content_hash"], "Evidence version changed"
    interpretation = session.scalar(select(Interpretation).where(Interpretation.observation_id == observation.id))
    assert interpretation and interpretation.status == "accepted"
    assert interpretation.content_hash == item["content_hash"]
    assert interpretation.assessment.get("evidence_hash") == item["content_hash"]
    payload, title_evidence = titles.title_input(session, need.id)
    # The six initial intents may share only the specifically reviewed records.
    assert set(title_evidence) == {str(evidence.id)}, "Additional title evidence requires scope review"
    roles, activities = titles._role_options(title_evidence), titles._activity_options(title_evidence)
    assert activities, "No complete supported title activity"
    request = titles.title_request_payload(payload, title_evidence, roles, activities)
    title_payload = {"title": payload, "evidence": title_evidence, "roles": roles, "activities": activities}
    title_fingerprint = titles.digest(payload)
    assert title_fingerprint == expected["title_input_fingerprint"], "Title context changed"
    assert titles.digest(request) == expected["title_request_sha256"], "Title request changed"
    title_intent = call_identity("POWER_NEED_TITLE", f"{need.id}:{title_fingerprint}",
                                title_payload, source.id, project.id)
    title_intent.update(kind="power_need_title", target_id=str(need.id),
                        input_fingerprint=title_fingerprint,
                        request_sha256=titles.digest(request))
    state = signals._evidence_state(session, observation, evidence)
    signal_payload = {"state": state, "model": "jev-1.13.0", "contract": "signal-display-v2",
                      "observation_id": str(observation.id), "evidence_id": str(evidence.id),
                      "evidence_hash": evidence.content_hash}
    request = signals.jev_request_payload(state, model="jev-1.13.0")
    assert titles.digest(request) == expected["jev_request_sha256"], "Jev context changed"
    anchored = session.scalar(select(Project).where(
        Project.source_id == observation.source_id, Project.external_id == observation.external_id))
    assert anchored and anchored.id == project.id, "Jev project budget anchor changed"
    signal_intent = call_identity("SIGNAL_ADJUDICATION",
        f"{observation.id}:{evidence.content_hash}:{signals.POLICY_VERSION}",
        signal_payload, source.id, project.id)
    assert signal_intent["reservation_usd"] == "0.01"
    signal_intent.update(kind="signal_adjudication", target_id=str(observation.id),
                         evidence_id=str(evidence.id), content_hash=evidence.content_hash,
                         policy_version=signals.POLICY_VERSION,
                         request_sha256=titles.digest(request))
    return [title_intent, signal_intent]


def assert_no_uncertainty(session):
    assert not session.scalar(select(LogicalCall.id).where(
        LogicalCall.status.in_(["NOT_SENT", "SENT_OUTCOME_UNKNOWN"])).limit(1)), "Active or uncertain call exists"


def receipt(session, intent):
    job = session.get(Job, UUID(intent["job_id"]))
    assert job and job.status == "succeeded" and not job.error, "Validation job did not succeed"
    checkpoint = json.loads(job.checkpoint or "{}")
    call = session.get(LogicalCall, UUID(checkpoint["logical_call_id"]))
    assert call and call.status == "COMPLETED" and not call.blocked_reason, "Provider outcome requires review"
    assert call.job_id == job.id and call.fingerprint == intent["fingerprint"]
    assert call.provider == intent["provider"] and call.model == intent["model"]
    assert call.evidence_digest == intent["evidence_digest"] and call.context_digest == intent["context_digest"]
    assert call.actual_cost_usd is None, "Unexpected billing reconciliation"
    result = {"job_id": str(job.id), "logical_call_id": str(call.id), "status": call.status,
              "provider": call.provider, "model": call.model, "input_tokens": call.input_tokens,
              "output_tokens": call.output_tokens, "reservation_usd": str(call.max_cost_usd),
              "actual_cost_usd": None, "fingerprint": call.fingerprint}
    if intent["kind"] == "power_need_title":
        row = session.get(PowerNeedTitle, job.target_id)
        assert row and row.status == "ready" and row.generated_fingerprint == intent["input_fingerprint"]
        assert row.result and row.citations
        assert session.scalar(select(func.count()).select_from(PowerNeedTitleVersion).where(
            PowerNeedTitleVersion.need_id == job.target_id)) == 1
        result.update(title=row.result["title"], citations=row.citations)
    else:
        assert checkpoint["logical_call_policy"] == intent["billing_policy"]
        decision = session.scalar(select(SignalDecision).where(
            SignalDecision.observation_id == job.target_id,
            SignalDecision.content_hash == intent["content_hash"],
            SignalDecision.policy_version == intent["policy_version"]).order_by(SignalDecision.id.desc()))
        assert decision and decision.source == "jev" and decision.model_version == "jev-1.13.0"
        assert len(decision.dimensions) == 6
        result.update(decision=decision.decision, dimensions=decision.dimensions, cost_basis="ESTIMATE")
    return result


def append_journal(path, event):
    fd = os.open(path, os.O_WRONLY | os.O_APPEND)
    with os.fdopen(fd, "w") as output:
        output.write(json.dumps({"at": datetime.now(UTC).isoformat(), **event}, default=str) + "\n")
        output.flush()
        os.fsync(output.fileno())


def main():
    mode, scope_path, activation_path, preflight_path, *execution = sys.argv[1:]
    assert mode in ("preflight", "execute")
    scope = checked_json(scope_path, SCOPE_HASH)
    activation = checked_json(activation_path, ACTIVATION_HASH)
    preflight = json.loads(Path(preflight_path).read_text())
    assert preflight["scope_sha256"] == SCOPE_HASH and preflight["activation_sha256"] == ACTIVATION_HASH
    expected = {item["need_id"]: item for item in preflight["records"]}
    assert len(scope["records"]) == len(expected) == 3
    # Verify ordinary settings before this process applies temporary overrides.
    assert not settings.power_need_titles_enabled and not settings.jev_enabled
    assert not settings.intelligence_typesafe_enabled
    assert "POWER_NEED_TITLE" not in settings.intelligence_enabled_contracts
    assert "SIGNAL_ADJUDICATION" not in settings.intelligence_enabled_contracts
    for key, value in activation["required_unchanged_controls"].items():
        assert getattr(settings, key.lower()) == setting_value(key.lower(), value), "Existing control changed: " + key
    for key, value in activation["runtime_changes"].items():
        setattr(settings, key.lower(), setting_value(key.lower(), value))
    assert settings.openai_api_key and settings.typesafe_api_key, "Existing provider credential unavailable"
    assert not settings.intelligence_typesafe_total_input_bound_verified
    assert all(value > 0 for limits in policy._caps().values() for value in limits.values())
    intents = []
    with SessionLocal() as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        database = session.scalar(text("SELECT current_database()"))
        assert database in ALLOWED_PREFLIGHT_DATABASES
        assert_no_uncertainty(session)
        for item in scope["records"]:
            intents.extend(inspect_record(session, item, expected[item["need_id"]]))
        assert len(intents) == 6
        assert sum(Decimal(item["reservation_usd"]) for item in intents) <= Decimal("0.06")
        baseline_calls = {str(value) for value in session.scalars(select(LogicalCall.id)).all()}
    if mode == "preflight":
        assert not execution
        print(json.dumps({"passed": True, "read_only": True, "database": database,
                          "provider_calls": 0, "intents": intents}, default=str))
        return
    assert database == LIVE_DATABASE and len(execution) == 3
    gate_path, journal_path, git_manifest_path = map(Path, execution)
    gate = json.loads(gate_path.read_text())
    assert gate["initial_six_public_intents_authorized"] is True
    assert gate["scope_sha256"] == SCOPE_HASH and gate["activation_sha256"] == ACTIVATION_HASH
    assert gate["ordinary_worker_stopped"] is True and gate["normal_new_contracts_disabled"] is True
    assert gate["controller_sha256"] == hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    assert gate["preflight_sha256"] == hashlib.sha256(Path(preflight_path).read_bytes()).hexdigest()
    git_manifest = checked_json(git_manifest_path, gate["git_manifest_sha256"])
    assert git_manifest["revision"] == gate["revision"]
    assert git_manifest["full_candidate"] == gate["full_candidate"]
    assert Path(titles.__file__).resolve() == Path("/app/backend/src/gridlens/intelligence/titles.py")
    verified_files = 0
    for entry in git_manifest["entries"]:
        relative = entry["path"]
        if relative.startswith(("backend/src/", "backend/migrations/", "config/")) or relative in (
            "backend/pyproject.toml", "backend/uv.lock", "backend/alembic.ini"
        ):
            data = (Path("/app") / relative).read_bytes()
            assert hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() == entry["sha1"], "Running source differs from reviewed release"
            verified_files += 1
    assert verified_files > 100
    assert journal_path == Path("/release-control/title02-six-intents.jsonl") and not journal_path.exists()
    claim_fd = os.open("/release-control/title02-six-intents.lock",
                       os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(claim_fd, "w") as claim:
        claim.write(json.dumps({"scope_sha256": SCOPE_HASH, "gate_sha256":
            hashlib.sha256(gate_path.read_bytes()).hexdigest(), "revision": gate["revision"]}))
        claim.flush()
        os.fsync(claim.fileno())
    worker.WORKER_ID = "title02-reviewed-six-intent-controller"
    from gridlens.intelligence.worker_browse import install_worker_publication
    install_worker_publication(SessionLocal)
    with SessionLocal.begin() as session:
        assert_no_uncertainty(session)
        assert not session.scalar(select(Job.id).where(Job.status == "running").limit(1)), "Worker not drained"
        for item, pair in zip(scope["records"], (intents[i:i+2] for i in range(0, 6, 2)), strict=True):
            assert inspect_record(session, item, expected[item["need_id"]]) == pair
            assert session.get(PowerNeedTitle, UUID(item["need_id"])) is None, "Prior title intent exists"
            for intent in pair:
                assert not session.scalar(select(Job.id).where(Job.kind == intent["kind"],
                    Job.target_id == UUID(intent["target_id"]), Job.status.in_(["queued", "running"])).limit(1))
                assert not session.scalar(select(LogicalCall.id).where(LogicalCall.fingerprint == intent["fingerprint"]))
            title_result = titles.request_title(session, UUID(item["need_id"]))
            pair[0]["job_id"] = title_result["job_id"]
            signals.queue_adjudication(session, session.get(Observation, UUID(item["observation_id"])),
                                       session.get(Evidence, UUID(item["evidence_id"])))
            job = session.scalar(select(Job).where(Job.kind == "signal_adjudication",
                Job.target_id == UUID(item["observation_id"]), Job.status == "queued"))
            pair[1]["job_id"] = str(job.id)
        fd = os.open(journal_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as output:
            output.write(json.dumps({"phase": "fixed_intents_before_commit", "scope_sha256": SCOPE_HASH,
                "activation_sha256": ACTIVATION_HASH, "intents": intents,
                "baseline_call_ids": sorted(baseline_calls)}, default=str) + "\n")
            output.flush()
            os.fsync(output.fileno())
    try:
        results = []
        for index, intent in enumerate(intents):
            item = scope["records"][index // 2]
            with SessionLocal() as session:
                assert_no_uncertainty(session)
                fresh = inspect_record(session, item, expected[item["need_id"]])[index % 2]
                assert fresh == {key: value for key, value in intent.items() if key != "job_id"}
                job = session.get(Job, UUID(intent["job_id"]))
                assert job.status == "queued" and job.attempts == 0
                assert "logical_call_id" not in json.loads(job.checkpoint or "{}")
            append_journal(journal_path, {"phase": "dispatching_fixed_job", "job_id": intent["job_id"]})
            ran_job = worker.run_one({}, job_ids=[UUID(intent["job_id"])])
            assert ran_job
            with SessionLocal() as session:
                assert_no_uncertainty(session)
                result = receipt(session, intent)
                calls = session.scalars(select(LogicalCall).where(LogicalCall.id.not_in(
                    [UUID(value) for value in baseline_calls]))).all()
                assert len(calls) == index + 1 and all(str(call.job_id) in {x["job_id"] for x in intents} for call in calls)
                assert sum(call.max_cost_usd for call in calls) <= Decimal("0.06")
            results.append(result)
            append_journal(journal_path, {"phase": "completed_fixed_job", **result})
            print(json.dumps({"phase": "completed_fixed_job", **result}, default=str), flush=True)
        # Cache verification cannot invoke transport or create another job.
        def forbidden_transport():
            raise AssertionError("Cache verification attempted transport")
        for intent, result in zip(intents, results, strict=True):
            cached = perform_legacy_call(task_type=intent["task_type"], task_key=intent["task_key"],
                payload={}, source_id=intent["source_id"], project_id=UUID(intent["project_id"]),
                job_id=UUID(intent["job_id"]), worker_id=worker.WORKER_ID, fence_token=0,
                invoke=forbidden_transport, existing_call_id=UUID(result["logical_call_id"]))
            assert cached.cached
        with SessionLocal.begin() as session:
            for item in scope["records"]:
                reused = titles.request_title(session, UUID(item["need_id"]))
                assert reused["status"] == "ready" and reused["job_id"] is None
            assert session.scalar(select(func.count()).select_from(LogicalCall)) == len(baseline_calls) + 6
        append_journal(journal_path, {"phase": "complete", "six_jobs_passed": True, "cache_no_dispatch": True})
        print(json.dumps({"passed": True, "completed_jobs": 6, "cache_no_dispatch": True,
                          "continuing_activation_applied": False}), flush=True)
    finally:
        # Hold only our own remaining work, including a generic worker retry.
        # Saved call identities, reservations and uncertain outcomes remain intact.
        with SessionLocal.begin() as session:
            for intent in intents:
                job = session.get(Job, UUID(intent["job_id"]))
                if job and job.status in ("queued", "running"):
                    assert job.lease_owner in (None, worker.WORKER_ID), "Unexpected owner of validation job"
                    job.status, job.error = "failed", "release_validation_held_for_review"
                    job.lease_owner = job.lease_until = None
                    if job.kind == "power_need_title":
                        row = session.get(PowerNeedTitle, job.target_id)
                        if row and row.status == "pending":
                            row.status, row.error = "failed", "release_validation_held_for_review"


if __name__ == "__main__":
    main()
