"""Capture an immutable corpus baseline, then bounded research and exact replay receipts.

No restore, credential setup, or work occurs by default. `baseline` is read-only.
`run` requires --execute --allow-public-research and the exact manifest corpus ID.
Use a separately restored, isolated database via the existing DATABASE_URL setting.
Fixture/reingested manifests can exercise mechanics but never claim retained proof.
See --help and scripts/pursuit-research-manifest.example.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

PR23_BACKUP = "828beace65cd2b06182f30e4713857656a993d3969c8cbecb02e6ee40ff8a886"
CATEGORIES = {
    "austin_data_center",
    "austin_temporary_power",
    "chicago_conversion",
    "oil_and_gas",
    "low_quality",
}
IMMUTABLE_TABLES = ("evidence", "pursuit_call_notes")
IDENTITY_TABLES = ("projects", "power_needs")
TERMINAL = {"RESOLVED", "PARTIALLY_RESOLVED", "UNRESOLVED", "FAILED", "BUDGET_EXCEEDED"}


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


def file_hash(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def write_once(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, sort_keys=True, indent=2, default=str)
        handle.write("\n")


def validate_manifest(manifest: dict, base: Path) -> dict:
    if manifest.get("schema_version") != 1:
        raise ValueError("Manifest schema_version must be 1")
    if manifest.get("kind") not in {"retained_pr23", "fixture", "reingested"}:
        raise ValueError("Explicit corpus kind is required")
    if not isinstance(manifest.get("corpus_id"), str) or not manifest["corpus_id"].strip():
        raise ValueError("Explicit corpus_id is required")
    database = manifest.get("database_name")
    if (
        not isinstance(database, str)
        or not database
        or database in {"gridlens", "gridlens_test", "postgres"}
        or manifest.get("isolated_database") is not True
    ):
        raise ValueError(
            "A named isolated validation database is required; runtime/test DBs refused"
        )
    cases = manifest.get("cases", [])
    if not isinstance(cases, list) or not 5 <= len(cases) <= 10:
        raise ValueError("Manifest requires five to ten explicit cases")
    if {case.get("category") for case in cases} != CATEGORIES:
        raise ValueError("Manifest must cover exactly the five required category names")
    ids = [str(UUID(case["need_id"])) for case in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("Cases must identify distinct PowerNeeds")
    if any(
        not isinstance(case.get("selection_reason"), str) or not case["selection_reason"].strip()
        for case in cases
    ):
        raise ValueError("Every category selection requires a source-grounded reason")
    provenance = {"kind": manifest["kind"], "retained_provenance_verified": False}
    if manifest["kind"] == "retained_pr23":
        supplied = manifest.get("provenance", {})
        backup = base / supplied["backup_path"]
        if supplied.get("backup_sha256") != PR23_BACKUP or file_hash(backup) != PR23_BACKUP:
            raise ValueError("Original PR23 retained backup hash does not match")
        restore_path = base / supplied["restore_receipt_path"]
        restore = json.loads(restore_path.read_text())
        if (
            restore.get("database_name") != database
            or restore.get("backup_sha256") != PR23_BACKUP
            or not restore.get("evidence_inventory_sha256")
        ):
            raise ValueError(
                "Restore receipt must bind the backup, database and evidence inventory"
            )
        provenance.update(
            {
                "retained_provenance_verified": True,
                "provenance_basis": "archive hash plus operator-attested restore inventory",
                "backup_sha256": PR23_BACKUP,
                "restore_receipt_sha256": file_hash(restore_path),
                "expected_evidence_inventory_sha256": restore["evidence_inventory_sha256"],
                "provenance_limit": (
                    "Restore receipt is operator-supplied; inventory is checked live."
                ),
            }
        )
    return provenance


def candidate_identity() -> dict:
    files = {}
    for folder in ("backend/src", "backend/migrations", "config", "scripts", "web/src"):
        for path in sorted((ROOT / folder).rglob("*")):
            if path.is_file() and path.suffix in {".py", ".ts", ".tsx", ".json", ".css"}:
                files[str(path.relative_to(ROOT))] = file_hash(path)
    for relative in ("backend/uv.lock", "backend/pyproject.toml", "web/package-lock.json"):
        path = ROOT / relative
        if path.is_file():
            files[relative] = file_hash(path)
    return {
        "commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "source_sha256": digest(files),
    }


def database_snapshot(session) -> dict:
    from sqlalchemy import text

    database = session.scalar(text("SELECT current_database()"))
    revision = session.scalar(text("SELECT version_num FROM alembic_version"))
    tables = {}
    # Table names are constant internal identifiers, never user-controlled SQL.
    for table in IMMUTABLE_TABLES:
        rows = session.execute(text(f"SELECT id::text, to_jsonb(t) FROM {table} t ORDER BY id"))
        inventory = {identity: digest(value) for identity, value in rows}
        tables[table] = {"count": len(inventory), "sha256": digest(inventory), "rows": inventory}
    identities = {}
    for table in IDENTITY_TABLES:
        identities[table] = list(session.scalars(text(f"SELECT id::text FROM {table} ORDER BY id")))
    return {
        "database_name": database,
        "alembic_revision": revision,
        "immutable_tables": tables,
        "identities": identities,
    }


def preservation(before: dict, after: dict) -> dict:
    changes = {}
    for table, state in before["immutable_tables"].items():
        current = after["immutable_tables"][table]["rows"]
        invalid = [
            identity for identity, value in state["rows"].items() if current.get(identity) != value
        ]
        changes[table] = {
            "preserved": not invalid,
            "changed_or_missing_ids": invalid,
            "before_count": state["count"],
            "after_count": len(current),
        }
    identities = {
        table: sorted(set(ids) - set(after["identities"][table]))
        for table, ids in before["identities"].items()
    }
    return {
        "passed": all(item["preserved"] for item in changes.values())
        and not any(identities.values()),
        "immutable_tables": changes,
        "removed_project_or_need_ids": identities,
    }


def evaluation_history_preserved(before: dict, after: dict) -> bool:
    for identity, receipt in before.get("evaluations", {}).items():
        current = after.get("evaluations", {}).get(identity)
        if current is None:
            return False
        current_versions = {
            version.get("version"): digest(version) for version in current.get("versions", [])
        }
        if any(
            current_versions.get(version.get("version")) != digest(version)
            for version in receipt.get("versions", [])
        ):
            return False
    return True


def selected_cases(session, manifest: dict, *, check_categories: bool = True) -> list[dict]:
    from gridlens.intelligence.commercial_evaluation import evaluate_target
    from gridlens.persistence.models import PowerNeed, Project

    result = []
    for item in manifest["cases"]:
        need_id = UUID(item["need_id"])
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id) if need else None
        card = evaluate_target(session, need_id)
        if need is None or project is None or card is None:
            raise ValueError(f"Manifest need lacks a current evaluation: {need_id}")
        source = project.source_id
        text = json.dumps(card, default=str).lower()
        category = item["category"]
        if check_categories and (
            category.startswith("austin_")
            and source != "austin-building-permits"
            or category == "chicago_conversion"
            and source != "chicago-building-permits"
            or category == "austin_data_center"
            and "data center" not in text
            and "data-center" not in text
            or category == "austin_temporary_power"
            and "temporary" not in text
            or category == "oil_and_gas"
            and "rrc" not in source
            and not any(term in text for term in ("oil", "gas", "drilling", "well"))
        ):
            raise ValueError(f"Case category does not match selected canonical record: {need_id}")
        result.append(
            {
                **item,
                "project_id": str(project.id),
                "source_id": source,
                "stable_project_id": project.external_id,
                "card": card,
            }
        )
    return result


def replay_state(session) -> dict:
    from sqlalchemy import select

    from gridlens.persistence.models import Evidence, Job, Pursuit, PursuitResearchQuestion

    return {
        "evidence_ids": sorted(str(i) for i in session.scalars(select(Evidence.id))),
        "research_job_ids": sorted(
            str(i) for i in session.scalars(select(Job.id).where(Job.kind == "pursuit_question"))
        ),
        "question_ids": sorted(str(i) for i in session.scalars(select(PursuitResearchQuestion.id))),
        "evaluations": {
            str(p.id): p.snapshot.get("commercial_triage")
            for p in session.scalars(select(Pursuit))
            if p.snapshot.get("commercial_triage")
        },
    }


def capture_baseline(session, manifest: dict, provenance: dict) -> dict:
    from sqlalchemy import select

    from gridlens.intelligence.autonomous_research import current_cards
    from gridlens.intelligence.research_metrics import metrics_report
    from gridlens.persistence.models import Job, Pursuit, PursuitResearchQuestion

    snapshot = database_snapshot(session)
    if snapshot["database_name"] != manifest["database_name"]:
        raise ValueError("Configured database does not match explicit manifest")
    if session.scalar(select(Job.id).where(Job.status.in_(["running", "queued"])).limit(1)):
        raise ValueError("Validation clone has active jobs; use a quiescent isolated restore")
    if provenance["retained_provenance_verified"]:
        evidence = snapshot["immutable_tables"]["evidence"]
        if (
            evidence["count"] != 16960
            or evidence["sha256"] != provenance["expected_evidence_inventory_sha256"]
        ):
            raise ValueError("Restored evidence does not match original corpus inventory")
    return {
        "schema_version": 1,
        "corpus_id": manifest["corpus_id"],
        "manifest_sha256": digest(manifest),
        "captured_at": datetime.now(UTC).isoformat(),
        "candidate": candidate_identity(),
        "execution_limits": execution_limits(manifest),
        "provenance": provenance,
        "snapshot": snapshot,
        "cases": selected_cases(session, manifest),
        "metrics": metrics_report(
            current_cards(),
            list(session.scalars(select(PursuitResearchQuestion))),
            list(session.scalars(select(Pursuit))),
        ),
        "replay_state": replay_state(session),
    }


def execution_limits(manifest: dict) -> dict:
    """Preflight the whole cohort against explicit cost and elapsed-time ceilings."""
    from gridlens.settings import settings

    requested = manifest.get("run_budget", {})
    cost = Decimal(str(requested.get("max_total_cost_usd", "0")))
    seconds = int(requested.get("max_wall_clock_seconds", 3600))
    if not cost.is_finite() or cost < 0 or cost > 20 or not 1 <= seconds <= 7200:
        raise ValueError("Run budget must be at most $20 and 7200 seconds")
    jobs = len(manifest["cases"]) * 4
    reserved = settings.autonomous_research_max_cost_usd * jobs
    if reserved > cost:
        raise ValueError("Configured cohort cost bound exceeds explicit run budget")
    if settings.autonomous_research_timeout_seconds > seconds:
        raise ValueError("Question timeout exceeds run wall-clock budget")
    return {
        "max_jobs": jobs,
        "max_total_cost_usd": str(cost),
        "max_wall_clock_seconds": seconds,
        "configured_reserved_cost_bound_usd": str(reserved),
        "per_question_timeout_seconds": settings.autonomous_research_timeout_seconds,
        "per_question_cost_usd": str(settings.autonomous_research_max_cost_usd),
        "per_question_searches": settings.autonomous_research_max_searches,
        "per_question_urls": settings.autonomous_research_max_urls,
        "per_question_documents": settings.autonomous_research_max_documents,
        "per_document_bytes": settings.autonomous_research_max_document_bytes,
        "daily_question_limit": settings.autonomous_research_daily_questions,
        "discovery_configured": settings.firecrawl_api_key is not None,
        "scrape_unit_cost_usd": str(settings.firecrawl_scrape_cost_usd)
        if settings.firecrawl_scrape_cost_usd is not None
        else None,
        "search_unit_cost_usd": str(settings.firecrawl_search_cost_usd)
        if settings.firecrawl_search_cost_usd is not None
        else None,
    }


def investigation_completed(question: dict) -> bool:
    """Unavailable/failed/skipped routes are not proof of a bounded search."""
    if question["status"] == "RESOLVED":
        return True
    if question["status"] not in {"PARTIALLY_RESOLVED", "UNRESOLVED"}:
        return False
    receipt = question["receipt"]
    retrieved = any(
        check.get("disposition") in {"ACCEPTED", "QUARANTINED", "REJECTED", "UNRESOLVED"}
        and check.get("url")
        and check.get("retrieved_at")
        for check in receipt.get("source_checks", [])
    )
    # Completed URL discovery with zero hits is meaningful. Reserving a search
    # or selecting a route alone does not mean that request succeeded.
    searched = bool(receipt.get("queries_searched"))
    return bool(retrieved or searched)


def execute_cases(manifest: dict, baseline: dict) -> dict:
    from sqlalchemy import select

    from gridlens.ingestion.registry import load_registry
    from gridlens.intelligence.commercial_evaluation import evaluate_target
    from gridlens.intelligence.pursuit_questions import question_view, schedule_questions
    from gridlens.intelligence.research_metrics import metrics_report
    from gridlens.jobs.worker import run_one
    from gridlens.persistence.database import SessionLocal
    from gridlens.persistence.models import Job, Pursuit, PursuitResearchQuestion

    limits = execution_limits(manifest)
    if baseline.get("execution_limits") != limits:
        raise ValueError("Research provider/cost configuration changed after baseline")
    deadline = time.monotonic() + limits["max_wall_clock_seconds"]
    started = datetime.now(UTC)
    identifiers = [UUID(case["need_id"]) for case in manifest["cases"]]
    with SessionLocal.begin() as session:
        current = database_snapshot(session)
        if digest(current) != digest(baseline["snapshot"]):
            raise ValueError("Database changed after baseline; refuse stale validation")
        if digest(replay_state(session)) != digest(baseline["replay_state"]):
            raise ValueError("Research/evaluations changed after baseline")
        cards = [evaluate_target(session, identity) for identity in identifiers]
        if any(card is None for card in cards):
            raise ValueError("Selected target no longer has an evaluation")
        if digest(selected_cases(session, manifest)) != digest(baseline["cases"]):
            raise ValueError("Canonical case projection changed after baseline")
        schedule_questions(session, cards, origin="validation")
    definitions = {source["id"]: source for source in load_registry()}
    # At most two initial blockers and one child for each root, per selected need.
    # Only this cohort's newly created jobs are eligible. No unrelated queue drain.
    max_jobs = limits["max_jobs"]
    jobs_executed = 0
    wall_clock_limited = False
    for _ in range(max_jobs):
        if time.monotonic() + limits["per_question_timeout_seconds"] > deadline:
            wall_clock_limited = True
            break
        with SessionLocal() as session:
            job_ids = list(
                session.scalars(
                    select(Job.id)
                    .join(PursuitResearchQuestion, PursuitResearchQuestion.id == Job.target_id)
                    .where(
                        Job.kind == "pursuit_question",
                        Job.status == "queued",
                        PursuitResearchQuestion.need_id.in_(identifiers),
                        Job.created_at >= started,
                    )
                )
            )
        if not job_ids or not run_one(definitions, job_ids=job_ids):
            break
        jobs_executed += 1
    with SessionLocal() as session:
        rows = list(
            session.scalars(
                select(PursuitResearchQuestion)
                .join(Job, Job.target_id == PursuitResearchQuestion.id)
                .where(
                    PursuitResearchQuestion.need_id.in_(identifiers),
                    Job.kind == "pursuit_question",
                    Job.created_at >= started,
                )
                .distinct()
                .order_by(PursuitResearchQuestion.created_at, PursuitResearchQuestion.id)
            )
        )
        after = selected_cases(session, manifest, check_categories=False)
        state_before_replay = replay_state(session)
        snapshot = database_snapshot(session)
        questions = [question_view(row) for row in rows]
        metrics = metrics_report(
            [case["card"] for case in after],
            rows,
            [
                p
                for p in session.scalars(select(Pursuit))
                if str(p.id) in {str(row.pursuit_id) for row in rows}
            ],
            started,
        )
    # Replay is planning-only: any newly queued work is an explicit failed proof,
    # never executed to disguise a duplicate. Existing freshness must prevent it.
    with SessionLocal.begin() as session:
        replay_cards = [evaluate_target(session, identity) for identity in identifiers]
        replay_created = schedule_questions(session, replay_cards, origin="validation")
        created_ids = [str(row.id) for row in replay_created]
        session.flush()
        state_after_replay = replay_state(session)
        # A failed dry replay must not leave unwanted queued work in the clone.
        session.rollback()
    invariant = preservation(baseline["snapshot"], snapshot)
    invariant["evaluation_history_preserved"] = evaluation_history_preserved(
        baseline["replay_state"], state_before_replay
    )
    invariant["passed"] = invariant["passed"] and invariant["evaluation_history_preserved"]
    cases = []
    for initial, final in zip(baseline["cases"], after, strict=True):
        attempts = [q for q in questions if q["need_id"] == final["need_id"]]
        inspected = bool(attempts) and all(q["status"] in TERMINAL for q in attempts)
        meaningful = inspected and all(investigation_completed(q) for q in attempts)
        cases.append(
            {
                "category": final["category"],
                "need_id": final["need_id"],
                "selection_reason": final["selection_reason"],
                "before": initial["card"],
                "after": final["card"],
                "questions": attempts,
                "bounded_investigation_completed": meaningful,
            }
        )
    replay_passed = not created_ids and digest(state_before_replay) == digest(state_after_replay)
    wall_clock_limited = wall_clock_limited or time.monotonic() > deadline
    passed = (
        invariant["passed"]
        and not wall_clock_limited
        and replay_passed
        and all(case["bounded_investigation_completed"] for case in cases)
    )
    return {
        "schema_version": 1,
        "corpus_id": manifest["corpus_id"],
        "kind": manifest["kind"],
        "candidate": candidate_identity(),
        "started_at": started.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "execution_limits": limits,
        "jobs_executed": jobs_executed,
        "wall_clock_limited": wall_clock_limited,
        "baseline_sha256": digest(baseline),
        "manifest_sha256": digest(manifest),
        "cases": cases,
        "metrics": metrics,
        "preservation": invariant,
        "replay": {
            "passed": replay_passed,
            "would_create_questions": created_ids,
            "before_sha256": digest(state_before_replay),
            "after_sha256": digest(state_after_replay),
        },
        "mechanical_gates_passed": passed,
        "retained_corpus_proof": False,
        "operator_attested_retained_corpus_validation": passed
        and manifest["kind"] == "retained_pr23"
        and baseline["provenance"]["retained_provenance_verified"],
        "proof_limit": "Archive bytes and operator-supplied inventory are checked, but this "
        "runner does not independently restore the archive or verify original project/need "
        "bindings. Operator attestation is not independent retained-corpus proof. Category "
        "usefulness and each cited finding require review; fixture/reingested runs never "
        "establish retained-corpus acceptance.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("baseline", "run"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--corpus-id", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--allow-public-research", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    provenance = validate_manifest(manifest, args.manifest.parent)
    if args.corpus_id != manifest["corpus_id"]:
        parser.error("--corpus-id must exactly match manifest")
    from gridlens.persistence.database import SessionLocal

    if args.mode == "baseline":
        if args.execute or args.allow_public_research:
            parser.error("baseline is read-only; execution flags apply only to run")
        with SessionLocal() as session:
            baseline = capture_baseline(session, manifest, provenance)
        write_once(args.baseline, baseline)
        print(
            json.dumps(
                {
                    "baseline": str(args.baseline),
                    "sha256": digest(baseline),
                    "kind": manifest["kind"],
                    "research_executed": False,
                }
            )
        )
        return
    if not args.execute or not args.allow_public_research or args.report is None:
        parser.error("run requires --execute --allow-public-research --report")
    if args.report.exists():
        parser.error("Report already exists; refusing to execute without a fresh output path")
    baseline = json.loads(args.baseline.read_text())
    if (
        baseline.get("manifest_sha256") != digest(manifest)
        or baseline.get("provenance") != provenance
        or baseline.get("candidate") != candidate_identity()
    ):
        parser.error("Baseline manifest/provenance/candidate mismatch")
    try:
        report = execute_cases(manifest, baseline)
    except Exception as exc:
        # Never include connection strings, raw exception text or secrets.
        report = {
            "corpus_id": manifest["corpus_id"],
            "kind": manifest["kind"],
            "candidate": candidate_identity(),
            "error": type(exc).__name__,
            "mechanical_gates_passed": False,
            "retained_corpus_proof": False,
        }
        write_once(args.report, report)
        raise SystemExit(1) from None
    report["candidate_unchanged"] = report["candidate"] == baseline["candidate"]
    if not report["candidate_unchanged"]:
        report["mechanical_gates_passed"] = report["retained_corpus_proof"] = False
        report["operator_attested_retained_corpus_validation"] = False
    write_once(args.report, report)
    print(
        json.dumps(
            {
                "report": str(args.report),
                "kind": manifest["kind"],
                "mechanical_gates_passed": report["mechanical_gates_passed"],
                "retained_corpus_proof": report["retained_corpus_proof"],
                "operator_attested_retained_corpus_validation": report.get(
                    "operator_attested_retained_corpus_validation", False
                ),
            }
        )
    )
    if not report["mechanical_gates_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
