"""Explicit bounded EvidenceJudge runner. Default mode is offline and never calls a provider."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import httpx
from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from gridlens.integrations.typesafe_evidence_judge import TypesafeEvidenceJudge  # noqa: E402
from gridlens.intelligence.evidence_evaluation import (  # noqa: E402
    completed_or_pending_case_ids,
    persist_benchmark_results,
    score_fixture_results,
)
from gridlens.intelligence.evidence_judge import InvalidJudgment  # noqa: E402
from gridlens.intelligence.evidence_shadow import run_shadow  # noqa: E402
from gridlens.intelligence.project_state import project_state  # noqa: E402
from gridlens.intelligence.research_recommendation import recommend_from_context  # noqa: E402
from gridlens.persistence.database import SessionLocal  # noqa: E402
from gridlens.persistence.models import Evidence, EvidenceJudgeRun  # noqa: E402
from gridlens.settings import settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=[
            "offline",
            "runtime-live",
            "benchmark-offline-results",
            "benchmark-live",
        ],
        default="offline",
    )
    parser.add_argument(
        "--fixture-set",
        type=Path,
        default=Path("docs/validation/gl3-028-evidence-judge-fixtures.json"),
    )
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--results",
        type=Path,
        help="Prior benchmark-live result JSON for offline scoring or safe resume",
    )
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 20:
        parser.error("--limit must be between 1 and 20")
    fixtures = json.loads(args.fixture_set.read_text(encoding="utf-8"))
    cases = fixtures["cases"]
    retained_ids = [
        case["evidence_id"]
        for case in fixtures["cases"]
        if case.get("kind") == "retained_real" and case.get("evidence_id")
    ]
    if args.mode == "benchmark-offline-results":
        if not args.results or not args.results.exists():
            parser.error("benchmark-offline-results requires an existing --results JSON")
        result_doc = json.loads(args.results.read_text(encoding="utf-8"))
        result_rows = [SimpleNamespace(**row) for row in result_doc.get("results", [])]
        scored = score_fixture_results(cases, result_rows)
        payload = {
            "mode": args.mode,
            "fixture_set": fixtures["fixture_set"],
            "results_file": str(args.results),
            "fixture_comparison": scored,
            "by_kind": {
                kind: score_fixture_results(
                    [case for case in cases if case.get("kind") == kind],
                    [
                        row
                        for row in result_rows
                        if any(
                            c.get("case_id") == row.case_id and c.get("kind") == kind for c in cases
                        )
                    ],
                )
                for kind in ("retained_real", "synthetic_variant")
            },
        }
    elif args.mode == "benchmark-live":
        if not args.results:
            parser.error("benchmark-live requires --results for durable per-case attempt records")
        if not settings.jev_enabled or not settings.jev_shadow_mode:
            parser.error("benchmark-live requires JEV_ENABLED=true and JEV_SHADOW_MODE=true")
        api_key = (
            settings.typesafe_api_key.get_secret_value() if settings.typesafe_api_key else None
        )
        if not api_key:
            parser.error("benchmark-live requires TYPESAFE_API_KEY in the process environment")
        selected = cases[: min(args.limit, 16)]
        result_doc = {
            "mode": args.mode,
            "fixture_set": fixtures["fixture_set"],
            "results": [],
        }
        if args.results and args.results.exists():
            result_doc = json.loads(args.results.read_text(encoding="utf-8"))
        done = completed_or_pending_case_ids(result_doc)
        transport_state = {"requests": 0, "pending": None}

        def tracked_post(url, **kwargs):
            transport_state["requests"] += 1
            pending_row = transport_state["pending"]
            if pending_row is not None:
                pending_row["transport_started"] = True
                persist_benchmark_results(result_doc, args.results)
            return httpx.post(url, **kwargs)

        judge = TypesafeEvidenceJudge(api_key, caller=tracked_post)
        new_attempts = 0
        for case in selected:
            if case["case_id"] in done:
                continue
            pending = {
                "case_id": case["case_id"],
                "evidence_id": case.get("evidence_id"),
                "status": "pending",
                "result": None,
                "latency_ms": None,
                "input_tokens": None,
                "output_tokens": None,
                "error_class": None,
                "transport_started": False,
            }
            transport_state["pending"] = pending
            result_doc["results"].append(pending)
            persist_benchmark_results(result_doc, args.results)
            new_attempts += 1
            started = time.monotonic()
            base = (
                case
                if case.get("kind") == "retained_real"
                else next(item for item in cases if item["case_id"] == case["derived_from"])
            )
            try:
                with SessionLocal() as session:
                    evidence = session.get(Evidence, UUID(base["evidence_id"]))
                    if evidence is None:
                        raise ValueError("retained evidence not found")
                    state = project_state(session, UUID(base["project_id"])) or {}
                    state = {
                        "project_id": state.get("project_id"),
                        "state": state.get("state", {}),
                        "organizations_and_roles": state.get("organizations_and_roles", [])[:8],
                    }
                    evidence_context = {
                        "id": str(evidence.id),
                        "hash": evidence.content_hash,
                        "title": evidence.title,
                        "abstract": evidence.abstract,
                        "url": evidence.url,
                        "published_at": evidence.published_at,
                        "retrieved_at": evidence.observed_at,
                        "extraction_location": evidence.extraction_location,
                    }
                variant = case.get("fixture_context", {})
                evidence_context.update(variant.get("evidence", {}))
                state["state"].update(variant.get("state", {}))
                candidates = variant.get("candidates", [])
                judgment, meta = judge.judge(state, evidence_context, candidates)
                row = {
                    "case_id": case["case_id"],
                    "evidence_id": case.get("evidence_id"),
                    "status": "valid",
                    "result": {
                        **judgment.model_dump(mode="json"),
                        "advisory": {
                            "research_recommended": recommend_from_context(
                                judgment.model_dump(mode="json"), state
                            )
                        },
                    },
                    **meta,
                }
            except InvalidJudgment:
                row = {**pending, "status": "invalid", "error_class": "InvalidJudgment"}
            except httpx.TimeoutException:
                row = {
                    **pending,
                    "status": "timeout",
                    "error_class": "TimeoutException",
                }
            except Exception as exc:  # noqa: BLE001 - record per-case provider/fixture failures without retry
                row = {**pending, "status": "failed", "error_class": type(exc).__name__}
            row["latency_ms"] = row.get("latency_ms") or int((time.monotonic() - started) * 1000)
            result_doc["results"][-1] = row
            persist_benchmark_results(result_doc, args.results)
        result_rows = [
            SimpleNamespace(**row, started_at=i) for i, row in enumerate(result_doc["results"])
        ]
        payload = {
            "mode": args.mode,
            "fixture_set": fixtures["fixture_set"],
            "attempts_this_run": new_attempts,
            "transport_requests_this_run": transport_state["requests"],
            "fixture_comparison": score_fixture_results(cases, result_rows),
            "by_kind": {
                kind: score_fixture_results(
                    [case for case in cases if case.get("kind") == kind],
                    [
                        SimpleNamespace(**row, started_at=i)
                        for i, row in enumerate(result_doc["results"])
                        if any(
                            c.get("case_id") == row.get("case_id") and c.get("kind") == kind
                            for c in cases
                        )
                    ],
                )
                for kind in ("retained_real", "synthetic_variant")
            },
            "results": result_doc["results"],
        }
    elif args.mode == "offline":
        with SessionLocal() as session:
            total = session.scalar(select(func.count(EvidenceJudgeRun.id))) or 0
            rows = session.scalars(
                select(EvidenceJudgeRun).order_by(EvidenceJudgeRun.started_at.desc()).limit(1000)
            ).all()
            valid_rows = [row for row in rows if row.status == "valid"]
            input_values = [row.input_tokens for row in valid_rows if row.input_tokens is not None]
            output_values = [
                row.output_tokens for row in valid_rows if row.output_tokens is not None
            ]
            payload = {
                "mode": "offline",
                "fixture_set": fixtures["fixture_set"],
                "fixture_cases": len(fixtures["cases"]),
                "retained_real_cases": len(retained_ids),
                "synthetic_variants": sum(
                    case["kind"] == "synthetic_variant" for case in fixtures["cases"]
                ),
                "historical_records": total,
                "attempted": len(rows),
                "valid": sum(r.status == "valid" for r in rows),
                "failed": sum(r.status != "valid" for r in rows),
                "latency_ms": sorted(r.latency_ms for r in rows if r.latency_ms is not None),
                "usage": {
                    "input_tokens": (
                        sum(input_values)
                        if valid_rows and len(input_values) == len(valid_rows)
                        else "UNKNOWN"
                    ),
                    "input_tokens_known_subtotal": sum(input_values) if input_values else "UNKNOWN",
                    "input_tokens_unknown_cases": len(valid_rows) - len(input_values),
                    "output_tokens": (
                        sum(output_values)
                        if valid_rows and len(output_values) == len(valid_rows)
                        else "UNKNOWN"
                    ),
                    "output_tokens_known_subtotal": sum(output_values)
                    if output_values
                    else "UNKNOWN",
                    "output_tokens_unknown_cases": len(valid_rows) - len(output_values),
                    "cost": "UNKNOWN",
                },
            }
            rows = [row for row in rows if str(row.evidence_id) in set(retained_ids)]
            payload["fixture_comparison"] = score_fixture_results(fixtures["cases"], rows)
    else:
        with SessionLocal() as session:
            payload = {
                "mode": "runtime-live",
                "historical_backfill": True,
                "fixture_set": fixtures["fixture_set"],
                "fixture_evidence_ids": retained_ids,
                **run_shadow(
                    session,
                    limit=min(args.limit, len(retained_ids)),
                    evidence_ids=retained_ids,
                ),
            }
        with SessionLocal() as session:
            rows = session.scalars(
                select(EvidenceJudgeRun)
                .where(EvidenceJudgeRun.evidence_id.in_(retained_ids))
                .order_by(EvidenceJudgeRun.started_at.desc())
            ).all()
        payload["fixture_comparison"] = score_fixture_results(fixtures["cases"], rows)
    if args.mode in {"offline", "runtime-live"}:
        payload["fixture_comparison"] = payload.get("fixture_comparison", "UNKNOWN")
    body = json.dumps(payload, indent=2, default=str) + "\n"
    if args.output:
        args.output.write_text(body, encoding="utf-8")
    attempts = payload.get("attempted", payload.get("attempts_this_run", 0))
    requests = payload.get("transport_requests_this_run")
    valid = payload.get("valid", "see fixture_comparison")
    failed = payload.get("failed", "see fixture_comparison")
    print(
        f"EvidenceJudge {args.mode}: attempts={attempts} transport_requests={requests} "
        f"valid={valid} failed={failed}"
    )
    print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
