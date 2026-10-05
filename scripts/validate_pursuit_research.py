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
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
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
OWNER_ACCEPTED_NO_QUESTION_CATEGORIES = {
    "austin_data_center",
    "austin_temporary_power",
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
    from gridlens.domain.pursuit_research import plan_questions
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
        category_sources = category_source_evidence(
            card, category, source, session=session
        )
        result.append(
            {
                **item,
                "project_id": str(project.id),
                "source_id": source,
                "stable_project_id": project.external_id,
                "card": card,
                "category_source_evidence": category_sources,
                "planned_questions": plan_questions(card),
            }
        )
    return result


def category_source_evidence(
    card: dict, category: str, source_id: str, *, session=None
) -> list[dict]:
    """Return directly linked Austin evidence whose stored content supports the category."""
    if source_id != "austin-building-permits":
        return []
    patterns = {
        "austin_data_center": r"\bdata[ -]?cent(?:er|re)\b|\bcolocation\b",
        "austin_temporary_power": r"\btemporary (?:power|service)\b|\bconstruction power\b",
    }
    pattern = patterns.get(category)
    if pattern is None:
        return []
    linked_sources = {
        str(evidence.get("evidence_id")): evidence
        for evidence in card.get("sources", [])
        if evidence.get("evidence_id")
    }
    stored_content = {}
    if session is not None and linked_sources:
        from sqlalchemy import select

        from gridlens.persistence.models import Evidence

        try:
            evidence_ids = [UUID(identity) for identity in linked_sources]
        except ValueError:
            evidence_ids = []
        rows = session.scalars(
            select(Evidence).where(Evidence.id.in_(evidence_ids))
        ) if evidence_ids else []
        for row in rows:
            linked = linked_sources.get(str(row.id))
            if (
                linked
                and row.url == linked.get("url")
                and row.content_hash == linked.get("hash")
            ):
                stored_content[str(row.id)] = row.abstract or ""

    matches = {}
    for evidence in linked_sources.values():
        evidence_id = evidence.get("evidence_id")
        url = evidence.get("url")
        content_hash = evidence.get("hash")
        quote = str(stored_content.get(str(evidence_id)) or evidence.get("text") or "")
        try:
            UUID(str(evidence_id))
        except (TypeError, ValueError):
            continue
        if (
            not evidence_id
            or not isinstance(url, str)
            or not url.startswith("https://abc.austintexas.gov/")
            or not content_hash
            or not re.search(pattern, quote, re.IGNORECASE)
        ):
            continue
        matches[str(evidence_id)] = {
            "evidence_id": str(evidence_id),
            "url": url,
            "content_hash": str(content_hash),
            "date": evidence.get("date"),
            "quote": quote,
        }
    return [matches[key] for key in sorted(matches)]


def evidence_signature(card: dict) -> list[tuple[str, str, str]]:
    """Stable identities and content hashes for all cited retained evidence."""
    rows = set()
    for evidence in card.get("sources", []):
        evidence_id = evidence.get("evidence_id")
        url = evidence.get("url")
        content_hash = evidence.get("hash")
        if evidence_id and url and content_hash:
            rows.add((str(evidence_id), str(url), str(content_hash)))
    return sorted(rows)


def owner_accepted_no_question_case(initial: dict, final: dict, attempts: list[dict]) -> bool:
    """Apply the October 5 owner exception only to the two named Austin cases."""
    category = final.get("category")
    if (
        category not in OWNER_ACCEPTED_NO_QUESTION_CATEGORIES
        or initial.get("category") != category
        or initial.get("source_id") != "austin-building-permits"
        or final.get("source_id") != "austin-building-permits"
        or initial.get("need_id") != final.get("need_id")
        or initial.get("project_id") != final.get("project_id")
        or attempts
    ):
        return False
    before = initial.get("card", {})
    after = final.get("card", {})
    before_sources = initial.get("category_source_evidence", [])
    after_sources = final.get("category_source_evidence", [])
    return bool(
        initial.get("planned_questions") == []
        and final.get("planned_questions") == []
        and before_sources
        and before_sources == after_sources
        and before.get("input_hash")
        and before.get("input_hash") == after.get("input_hash")
        and before.get("disposition") == "ACTION NOW"
        and after.get("disposition") == "ACTION NOW"
        and before.get("tier") == after.get("tier")
        and evidence_signature(before)
        and evidence_signature(before) == evidence_signature(after)
    )


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


def drain_cohort_jobs(
    queued_job_ids,
    run_job,
    *,
    jobs_executed: int,
    max_jobs: int,
    deadline: float,
    per_question_timeout: int,
    monotonic=time.monotonic,
) -> tuple[int, str | None]:
    """Drain only eligible cohort work within the remaining job and time limits."""
    while jobs_executed < max_jobs:
        if monotonic() + per_question_timeout > deadline:
            return jobs_executed, "wall_clock"
        job_ids = queued_job_ids()
        if not job_ids:
            return jobs_executed, None
        if not run_job(job_ids):
            return jobs_executed, "runner_unavailable"
        jobs_executed += 1
    return jobs_executed, "max_jobs"


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
        evaluated_cards = [evaluate_target(session, identity) for identity in identifiers]
        if any(card is None for card in evaluated_cards):
            raise ValueError("Selected target no longer has an evaluation")
        cards = [card for card in evaluated_cards if card is not None]
        if digest(selected_cases(session, manifest)) != digest(baseline["cases"]):
            raise ValueError("Canonical case projection changed after baseline")
        schedule_questions(session, cards, origin="validation")
    definitions = {source["id"]: source for source in load_registry()}
    # At most two initial blockers and one child for each root, per selected need.
    # Only this cohort's newly created jobs are eligible. No unrelated queue drain.
    max_jobs = limits["max_jobs"]
    jobs_executed = 0
    wall_clock_limited = False
    settlement_rounds: list[dict[str, Any]] = []

    def queued_job_ids() -> list[UUID]:
        with SessionLocal() as session:
            return list(
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

    def run_cohort_job(job_ids: list[UUID]) -> bool:
        return run_one(definitions, job_ids=job_ids)

    jobs_executed, drain_stop = drain_cohort_jobs(
        queued_job_ids,
        run_cohort_job,
        jobs_executed=jobs_executed,
        max_jobs=max_jobs,
        deadline=deadline,
        per_question_timeout=limits["per_question_timeout_seconds"],
    )
    settlement_stop = drain_stop
    if drain_stop == "wall_clock":
        wall_clock_limited = True
    elif drain_stop == "max_jobs" and not queued_job_ids():
        settlement_stop = None

    # New facts can invalidate siblings that were already queued. Once that
    # queue is empty, plan only within the remaining execution budget and drain
    # those replacements before the strict no-new-question replay.
    while settlement_stop is None and jobs_executed < max_jobs:
        if time.monotonic() + limits["per_question_timeout_seconds"] > deadline:
            wall_clock_limited = True
            settlement_stop = "wall_clock"
            break
        with SessionLocal() as session:
            evaluated_cards = [evaluate_target(session, identity) for identity in identifiers]
        if any(card is None for card in evaluated_cards):
            raise ValueError("Selected target lost its current evaluation while settling")
        current_cards = [card for card in evaluated_cards if card is not None]
        before_inputs = digest(
            [(str(card["id"]), card["input_hash"]) for card in current_cards]
        )
        scheduled = 0
        planning_budget_limited = False
        remaining_jobs = max_jobs - jobs_executed
        round_number = len(settlement_rounds)
        round_question_ids: list[str] = []
        # Per-need transactions let us refuse a multi-question plan that would
        # exceed the remaining job cap without persisting any unauthorized job.
        for card in current_cards:
            if time.monotonic() + limits["per_question_timeout_seconds"] > deadline:
                wall_clock_limited = True
                settlement_stop = "wall_clock"
                break
            if scheduled >= remaining_jobs:
                break
            with SessionLocal.begin() as session:
                created = schedule_questions(session, [card], origin="validation")
                if len(created) > remaining_jobs - scheduled:
                    session.rollback()
                    planning_budget_limited = True
                else:
                    scheduled += len(created)
                    round_question_ids.extend(str(row.id) for row in created)
        if settlement_stop == "wall_clock":
            break
        if scheduled == 0:
            if planning_budget_limited:
                settlement_stop = "max_jobs"
            else:
                settlement_stop = "no_pending_replacements"
            break

        round_receipt = {
            "round": round_number + 1,
            "input_sha256_before": before_inputs,
            "input_sha256_after": None,
            "new_question_ids": round_question_ids,
            "stop_reason": None,
        }
        settlement_rounds.append(round_receipt)

        jobs_executed, drain_stop = drain_cohort_jobs(
            queued_job_ids,
            run_cohort_job,
            jobs_executed=jobs_executed,
            max_jobs=max_jobs,
            deadline=deadline,
            per_question_timeout=limits["per_question_timeout_seconds"],
        )
        if drain_stop == "wall_clock":
            wall_clock_limited = True
            settlement_stop = drain_stop
            round_receipt["stop_reason"] = drain_stop
            break
        if drain_stop is not None:
            settlement_stop = drain_stop if queued_job_ids() else None
            if settlement_stop is not None:
                round_receipt["stop_reason"] = settlement_stop
                break

        with SessionLocal() as session:
            evaluated_cards = [evaluate_target(session, identity) for identity in identifiers]
        if any(card is None for card in evaluated_cards):
            raise ValueError("Selected target lost its current evaluation while settling")
        settled_cards = [card for card in evaluated_cards if card is not None]
        after_inputs = digest(
            [(str(card["id"]), card["input_hash"]) for card in settled_cards]
        )
        round_receipt["input_sha256_after"] = after_inputs
        if planning_budget_limited:
            settlement_stop = "max_jobs"
            round_receipt["stop_reason"] = settlement_stop
            break
        if before_inputs == after_inputs:
            settlement_stop = "no_input_change"
            round_receipt["stop_reason"] = settlement_stop
            break

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
        evaluated_cards = [evaluate_target(session, identity) for identity in identifiers]
        if any(card is None for card in evaluated_cards):
            raise ValueError("Selected target lost its current evaluation during replay")
        replay_cards = [card for card in evaluated_cards if card is not None]
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
        no_question_accepted = owner_accepted_no_question_case(initial, final, attempts)
        case_accepted = meaningful or no_question_accepted
        cases.append(
            {
                "category": final["category"],
                "need_id": final["need_id"],
                "selection_reason": final["selection_reason"],
                "before": initial["card"],
                "after": final["card"],
                "category_source_evidence": final["category_source_evidence"],
                "planned_questions_before": initial["planned_questions"],
                "planned_questions_after": final["planned_questions"],
                "questions": attempts,
                "bounded_investigation_completed": meaningful,
                "owner_accepted_no_question_no_change": no_question_accepted,
                "case_acceptance_mode": (
                    "MEANINGFUL_INVESTIGATION"
                    if meaningful
                    else "OWNER_ACCEPTED_NO_QUESTION_NO_CHANGE"
                    if no_question_accepted
                    else "NOT_ACCEPTED"
                ),
                "case_accepted": case_accepted,
            }
        )
    replay_passed = not created_ids and digest(state_before_replay) == digest(state_after_replay)
    wall_clock_limited = wall_clock_limited or time.monotonic() > deadline
    passed = (
        invariant["passed"]
        and not wall_clock_limited
        and settlement_stop not in {"runner_unavailable", "max_jobs"}
        and replay_passed
        and all(case["case_accepted"] for case in cases)
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
        "settlement": {
            "stop_reason": settlement_stop,
            "remaining_queued_jobs": len(queued_job_ids()),
            "rounds": settlement_rounds,
        },
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
