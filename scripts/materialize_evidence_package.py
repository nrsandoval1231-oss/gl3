"""Materialize or inspect a cited evidence package and its bounded Jev advisory."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "backend"))

from gridlens.intelligence.evidence_packages import (  # noqa: E402
    MODEL,
    build_package,
    materialize_package,
    update_status,
    validate_package,
)
from gridlens.persistence.database import SessionLocal  # noqa: E402
from gridlens.persistence.models import (  # noqa: E402
    Evidence,
    EvidencePackage,
    Job,
    LogicalCall,
    Observation,
    SignalDecision,
    Source,
)
from gridlens.settings import settings  # noqa: E402


def _safe_database(*, dispatch: bool) -> None:
    url = make_url(settings.database_url)
    test_url = make_url(settings.test_database_url)
    if (
        not dispatch
        and url == test_url
        and url.database
        and (url.database == "test" or url.database.endswith("_test"))
    ):
        return
    allowed = {"pipeline_test", "pipeline_m3_app"} if not dispatch else {"pipeline_m3_app"}
    if (
        url.host not in {"127.0.0.1", "localhost", "::1"}
        or url.port != 55443
        or url.database not in allowed
        or url.query
    ):
        raise ValueError("Evidence package operation requires its exact isolated loopback database")


def _task_key(observation_id: UUID, content_hash: str) -> str:
    return f"{observation_id}:{content_hash}:signal-display-v2"


def _json_digest(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def _counts(session, observation_id: UUID, task_key: str) -> dict:
    jobs = session.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.kind == "signal_adjudication", Job.target_id == observation_id)
    )
    calls = session.scalars(
        select(LogicalCall).where(
            LogicalCall.task_type == "SIGNAL_ADJUDICATION",
            LogicalCall.task_key == task_key,
        )
    ).all()
    return {
        "jobs": int(jobs or 0),
        "calls": len(calls),
        "dispatch_timestamps": sorted(
            call.dispatched_at.isoformat() if call.dispatched_at else None for call in calls
        ),
    }


def _persist_status(
    session,
    package: EvidencePackage,
    status: str,
    reason: str,
    *,
    call: LogicalCall | None = None,
    logical_call_id: UUID | None = None,
    advisory: dict | None = None,
) -> None:
    update_status(
        session,
        package,
        status,
        reason=reason or None,
        logical_call_id=call.id if call else logical_call_id,
        advisory=advisory,
    )


def _matching_decision(session, observation_id: UUID, evidence_hash: str, model: str):
    return session.scalar(
        select(SignalDecision)
        .where(
            SignalDecision.observation_id == observation_id,
            SignalDecision.content_hash == evidence_hash,
            SignalDecision.source == "jev",
            SignalDecision.model_version == model,
            SignalDecision.policy_version == "signal-display-v2",
        )
        .order_by(SignalDecision.id.desc())
    )


def _call_matches_exact_evidence(session, call, observation, evidence, job_id=None) -> bool:
    task_key = _task_key(observation.id, evidence.content_hash)
    evidence_digest = hashlib.sha256(
        json.dumps(
            str(evidence.id), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
    ).hexdigest()
    if not (
        call.task_type == "SIGNAL_ADJUDICATION"
        and call.task_key == task_key
        and call.provider == "typesafe"
        and call.model == MODEL
        and call.policy_version == "legacy-shared-ledger-v1"
        and call.prompt_contract == "legacy-signal_adjudication-v1"
        and call.evidence_digest == evidence_digest
        and call.source_id == observation.source_id
        and (job_id is None or call.job_id == job_id)
        and call.job_id is not None
    ):
        return False
    job = session.get(Job, call.job_id)
    if (
        job is None
        or job.kind != "signal_adjudication"
        or job.target_id != observation.id
        or job.status != "succeeded"
        or job.error is not None
    ):
        return False
    try:
        checkpoint = json.loads(job.checkpoint or "{}")
    except (TypeError, ValueError):
        return False
    return (
        checkpoint.get("evidence_id") == str(evidence.id)
        and checkpoint.get("content_hash") == evidence.content_hash
        and checkpoint.get("logical_call_id") == str(call.id)
    )


def _verify_completed_package(session, package: EvidencePackage) -> None:
    from gridlens.intelligence.signal_adjudication import validated_dimensions

    if package.processing_status != "COMPLETE_ADVISORY":
        return
    evidence = session.get(Evidence, package.evidence_id)
    observation = session.get(Observation, package.observation_id)
    call = session.get(LogicalCall, package.logical_call_id) if package.logical_call_id else None
    decision = _matching_decision(session, package.observation_id, package.evidence_hash, MODEL)
    if (
        evidence is None
        or observation is None
        or observation.content_hash != evidence.content_hash
        or not call
        or call.status != "COMPLETED"
        or decision is None
        or not _call_matches_exact_evidence(session, call, observation, evidence)
    ):
        raise ValueError("Complete advisory lacks its exact matching call and decision")
    dimensions = validated_dimensions(call.result_payload or {}, expected_model=MODEL)
    advisory = package.payload.get("advisory")
    if (
        not isinstance(advisory, dict)
        or advisory.get("logical_call_id") != str(call.id)
        or advisory.get("model") != MODEL
        or advisory.get("source") != "jev"
        or advisory.get("decision") != decision.decision
        or advisory.get("dimensions") != dimensions
    ):
        raise ValueError("Complete advisory payload does not match its exact ledger decision")


def _validate_current_package(
    session: Session, package: EvidencePackage
) -> tuple[Evidence, Observation, Source]:
    """Bind a package to current retained source text before any reuse or completion."""
    evidence = session.get(Evidence, package.evidence_id)
    observation = session.get(Observation, package.observation_id)
    source = session.get(Source, observation.source_id) if observation else None
    if (
        evidence is None
        or observation is None
        or source is None
        or evidence.observation_id != observation.id
        or evidence.content_hash != package.evidence_hash
        or observation.content_hash != evidence.content_hash
    ):
        raise ValueError("Package input is missing or stale")
    expected, *_ = build_package(session, evidence.id)
    validate_package(
        package.payload,
        evidence_fields={
            "title": evidence.title or "",
            "abstract": evidence.abstract or "",
        },
    )
    if (
        package.package_key != expected["package_key"]
        or package.payload.get("package_key") != expected["package_key"]
    ):
        raise ValueError("Package identity no longer matches current retained evidence")
    immutable = (
        "source_references",
        "identity",
        "extractor_version",
        "question_contract",
        "provider",
        "model",
        "facts",
        "entity_candidates",
        "missing_fields",
        "contradiction_pairs",
        "unevaluated_dimensions",
        "quality_basis",
        "document_coverage",
        "document_coverage_basis",
        "jev_input_coverage",
        "source_collection_status",
    )
    if any(package.payload.get(name) != expected.get(name) for name in immutable):
        raise ValueError("Package payload no longer matches current retained evidence")
    return evidence, observation, source


def _execute(package_id: UUID) -> tuple[str, str | None]:
    from gridlens.ingestion.registry import load_registry
    from gridlens.intelligence.intelligence_jobs import _enabled
    from gridlens.intelligence.signal_adjudication import (
        POLICY_VERSION,
        _evidence_state,
        queue_adjudication,
        validated_dimensions,
    )

    with SessionLocal.begin() as session:
        package = session.get(EvidencePackage, package_id)
        if package is None:
            raise ValueError("Evidence package does not exist")
        validate_package(package.payload)
        try:
            evidence, observation, source = _validate_current_package(session, package)
        except ValueError:
            _persist_status(session, package, "BLOCKED", "STALE_EVIDENCE_OR_IDENTITY")
            return "BLOCKED", None
        if package.processing_status != package.payload.get("processing_status"):
            raise ValueError("Stored package status differs from its validated payload")
        registry = {item["id"]: item for item in load_registry()}
        definition = registry.get(source.id)
        if (
            not source.enabled
            or not source.registry_enabled
            or not definition
            or definition.get("enabled", True) is False
        ):
            _persist_status(session, package, "BLOCKED", "SOURCE_DISABLED_OR_UNREGISTERED")
            return "BLOCKED", None
        task_key = _task_key(observation.id, evidence.content_hash)
        prior_calls = session.scalars(
            select(LogicalCall)
            .where(
                LogicalCall.task_key == task_key,
            )
            .order_by(LogicalCall.created_at.desc())
        ).all()
        if len(prior_calls) > 1:
            _persist_status(session, package, "INCOMPLETE", "AMBIGUOUS_PRIOR_CALLS_NO_REDISPATCH")
            return "INCOMPLETE", None
        if prior_calls:
            call = prior_calls[0]
            if call.status == "COMPLETED" and isinstance(call.result_payload, dict):
                decision = _matching_decision(session, observation.id, evidence.content_hash, MODEL)
                if decision is not None and _call_matches_exact_evidence(
                    session, call, observation, evidence
                ):
                    try:
                        dimensions = validated_dimensions(call.result_payload, expected_model=MODEL)
                    except (KeyError, TypeError, ValueError):
                        _persist_status(
                            session,
                            package,
                            "INCOMPLETE",
                            "COMPLETED_CALL_RESPONSE_FAILED_VALIDATION_NO_RETRY",
                            call=call,
                        )
                        return "INCOMPLETE", str(call.id)
                    advisory = {
                        "decision": decision.decision,
                        "dimensions": dimensions,
                        "source": "jev",
                        "model": MODEL,
                        "logical_call_id": str(call.id),
                        "validated": True,
                    }
                    _persist_status(
                        session,
                        package,
                        "COMPLETE_ADVISORY",
                        "Reused exact completed Jev ledger call and matching decision.",
                        call=call,
                        advisory=advisory,
                    )
                    return "COMPLETE_ADVISORY", str(call.id)
                _persist_status(
                    session,
                    package,
                    "INCOMPLETE",
                    "COMPLETED_CALL_LACKS_EXACT_MATCH",
                    call=call,
                )
                return "INCOMPLETE", str(call.id)
            status = "INCOMPLETE" if call.status == "SENT_OUTCOME_UNKNOWN" else "BLOCKED"
            _persist_status(
                session,
                package,
                status,
                f"EXISTING_CALL_{call.status}_NO_REDISPATCH",
                call=call,
            )
            return status, str(call.id)

        state = _evidence_state(session, observation, evidence)
        gate_payload = {
            "state": state,
            "model": MODEL,
            "contract": "signal-display-v2",
            "observation_id": str(observation.id),
            "evidence_id": str(evidence.id),
            "evidence_hash": evidence.content_hash,
        }
        enabled, provider, model, reason = _enabled("SIGNAL_ADJUDICATION", payload=gate_payload)
        if not enabled or provider != "typesafe" or model != MODEL:
            _persist_status(session, package, "BLOCKED", reason or "PINNED_POLICY_MISMATCH")
            return "BLOCKED", None

        prior_decision = session.scalar(
            select(SignalDecision)
            .where(
                SignalDecision.observation_id == observation.id,
                SignalDecision.content_hash == evidence.content_hash,
                SignalDecision.policy_version == POLICY_VERSION,
            )
            .order_by(SignalDecision.id.desc())
        )
        if prior_decision and prior_decision.source == "jev":
            _persist_status(
                session,
                package,
                "INCOMPLETE",
                "JEV_DECISION_WITHOUT_MATCHING_LEDGER_CALL",
            )
            return "INCOMPLETE", None
        queue_adjudication(session, observation, evidence, policy_version=POLICY_VERSION)
        job = session.scalar(
            select(Job)
            .where(
                Job.kind == "signal_adjudication",
                Job.target_id == observation.id,
                Job.status.in_(["queued", "running"]),
            )
            .order_by(Job.created_at.desc())
        )
        if job is None:
            _persist_status(session, package, "BLOCKED", "EXACT_ADJUDICATION_JOB_NOT_QUEUED")
            return "BLOCKED", None
        try:
            checkpoint = json.loads(job.checkpoint or "{}")
        except (TypeError, ValueError):
            checkpoint = {}
        if (
            checkpoint.get("evidence_id") != str(evidence.id)
            or checkpoint.get("content_hash") != evidence.content_hash
        ):
            _persist_status(
                session, package, "BLOCKED", "ACTIVE_JOB_HAS_DIFFERENT_EVIDENCE_VERSION"
            )
            return "BLOCKED", None
        job_id = job.id

    from gridlens.jobs.worker import run_one

    definitions = {item["id"]: item for item in load_registry()}
    run_one(definitions, job_ids=[job_id])

    with SessionLocal.begin() as session:
        package = session.get(EvidencePackage, package_id)
        if package is None:
            raise ValueError("Evidence package disappeared after worker execution")
        job = session.get(Job, job_id)
        post_checkpoint: dict = {}
        try:
            post_checkpoint = json.loads(job.checkpoint or "{}") if job else {}
        except (TypeError, ValueError):
            pass
        raw_call_id = post_checkpoint.get("logical_call_id")
        try:
            post_call_id = UUID(raw_call_id) if raw_call_id else None
        except (TypeError, ValueError):
            post_call_id = None
        post_call: LogicalCall | None = (
            session.get(LogicalCall, post_call_id) if post_call_id else None
        )
        try:
            current_evidence, observation, source = _validate_current_package(session, package)
        except ValueError:
            _persist_status(
                session,
                package,
                "INCOMPLETE",
                "POST_WORKER_INPUT_CHANGED_NO_RETRY",
                call=post_call,
                logical_call_id=post_call_id,
            )
            return "INCOMPLETE", str(post_call_id) if post_call_id else None
        registry = {item["id"]: item for item in load_registry()}
        registry_source = registry.get(source.id)
        if (
            not source.enabled
            or not source.registry_enabled
            or not registry_source
            or registry_source.get("enabled", True) is False
        ):
            _persist_status(
                session,
                package,
                "INCOMPLETE",
                "SOURCE_IDENTITY_CHANGED_AFTER_WORKER_NO_RETRY",
                call=post_call,
                logical_call_id=post_call_id,
            )
            return "INCOMPLETE", str(post_call_id) if post_call_id else None
        decision = _matching_decision(session, observation.id, package.evidence_hash, MODEL)
        if (
            post_call
            and post_call.status == "COMPLETED"
            and decision
            and job
            and job.status == "succeeded"
            and not job.error
            and _call_matches_exact_evidence(
                session,
                post_call,
                observation,
                current_evidence,
                job.id,
            )
        ):
            try:
                dimensions = validated_dimensions(
                    post_call.result_payload or {}, expected_model=MODEL
                )
            except (KeyError, TypeError, ValueError):
                _persist_status(
                    session,
                    package,
                    "INCOMPLETE",
                    "COMPLETED_CALL_RESPONSE_FAILED_VALIDATION_NO_RETRY",
                    call=post_call,
                )
                return "INCOMPLETE", str(post_call.id)
            advisory = {
                "decision": decision.decision,
                "dimensions": dimensions,
                "source": "jev",
                "model": MODEL,
                "logical_call_id": str(post_call.id),
                "validated": True,
            }
            _persist_status(
                session,
                package,
                "COMPLETE_ADVISORY",
                "Exact bounded job returned a validated Jev decision.",
                call=post_call,
                advisory=advisory,
            )
            return "COMPLETE_ADVISORY", str(post_call.id)
        if post_call and post_call.status == "SENT_OUTCOME_UNKNOWN":
            _persist_status(
                session,
                package,
                "INCOMPLETE",
                "SENT_OUTCOME_UNKNOWN_NO_RETRY",
                call=post_call,
            )
            return "INCOMPLETE", str(post_call.id)
        if post_call and post_call.status == "COMPLETED":
            _persist_status(
                session,
                package,
                "INCOMPLETE",
                "CALL_COMPLETED_WITHOUT_EXACT_MATCHING_DECISION",
                call=post_call,
            )
            return "INCOMPLETE", str(post_call.id)
        if post_call and (
            post_call.dispatched_at is not None or post_call.status in {"FAILED", "RECONCILED"}
        ):
            error = job.error if job and job.error else f"CALL_{post_call.status}"
            _persist_status(session, package, "INCOMPLETE", error, call=post_call)
            return "INCOMPLETE", str(post_call.id)
        error = (job.error if job else None) or (
            f"CALL_{post_call.status}" if post_call else "NO_CALL_RECEIPT"
        )
        blocked = bool(
            job and job.status == "succeeded" and error.startswith("BLOCKED:") and post_call is None
        ) or error in {
            "STALE_EVIDENCE",
            "STALE_EVIDENCE_OR_POLICY_AFTER_PROVIDER",
        }
        status = "BLOCKED" if blocked else "INCOMPLETE"
        _persist_status(
            session,
            package,
            status,
            error,
            call=post_call,
            logical_call_id=post_call_id,
        )
        return status, str(post_call_id) if post_call_id else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-id", required=True, type=UUID)
    parser.add_argument("--execute-jev", action="store_true")
    parser.add_argument("--replay", action="store_true")
    args = parser.parse_args()
    if args.execute_jev and args.replay:
        parser.error("--execute-jev and --replay are mutually exclusive")
    _safe_database(dispatch=args.execute_jev)
    started = time.monotonic()
    with SessionLocal.begin() as session:
        if args.replay:
            expected, *_ = build_package(session, args.evidence_id)
            existing = session.scalar(
                select(EvidencePackage).where(
                    EvidencePackage.package_key == expected["package_key"]
                )
            )
            if existing is None:
                raise ValueError("Replay requires an existing exact package")
        package = materialize_package(session, args.evidence_id)
        package_id = package.id
        package_key = package.package_key
        observation_id = package.observation_id
        task_key = _task_key(observation_id, package.evidence_hash)
        before = _counts(session, observation_id, task_key)
        previous_digest = _json_digest(package.payload)
        if args.replay:
            _validate_current_package(session, package)
            if package.processing_status != package.payload.get("processing_status"):
                raise ValueError("Stored package processing status differs from its payload")
        _verify_completed_package(session, package)
    status = package.processing_status
    call_id = str(package.logical_call_id) if package.logical_call_id else None
    if args.execute_jev and status != "COMPLETE_ADVISORY":
        status, call_id = _execute(package_id)
    with SessionLocal.begin() as session:
        final_package = session.get(EvidencePackage, package_id)
        if final_package is None:
            raise ValueError("Evidence package disappeared before final validation")
        _validate_current_package(session, final_package)
        if final_package.processing_status != final_package.payload.get("processing_status"):
            raise ValueError("Stored package status differs from its validated payload")
        _verify_completed_package(session, final_package)
        after = _counts(session, observation_id, task_key)
        digest = _json_digest(package.payload)
        if args.replay and (before != after or digest != previous_digest):
            raise ValueError(
                "Replay changed job/call counts, dispatch timestamps, or package digest"
            )
        logical_call = (
            session.get(LogicalCall, final_package.logical_call_id)
            if final_package.logical_call_id
            else None
        )
        output = {
            "evidence_id": str(final_package.evidence_id),
            "evidence_hash": final_package.evidence_hash,
            "observation_id": str(final_package.observation_id),
            "package_id": str(final_package.id),
            "package_key": package_key,
            "package_digest": digest,
            "processing_status": final_package.processing_status,
            "model": final_package.model,
            "logical_call_id": str(final_package.logical_call_id)
            if final_package.logical_call_id
            else None,
            "usage_available": bool(
                logical_call
                and (
                    logical_call.input_tokens is not None or logical_call.output_tokens is not None
                )
            ),
            "cost_available": bool(logical_call and logical_call.actual_cost_usd is not None),
            "replay_counts": after if args.replay else None,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "execute_elapsed_ms": round((time.monotonic() - started) * 1000)
            if args.execute_jev
            else None,
        }
    print(json.dumps(output, sort_keys=True))
    return 0 if status in {"PREPARED", "COMPLETE_ADVISORY"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
