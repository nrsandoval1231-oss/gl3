"""Profile customer account groups on the pinned synthetic 40k test DB."""

from __future__ import annotations

import hashlib
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from sqlalchemy import event, text
from sqlalchemy.engine import make_url

ROOT = Path(
    os.environ.get(
        "PERF_SOURCE_ROOT", "/workspace/gl3-page-payload-opt-20261113"
    )
).resolve()
SRC = ROOT / "backend" / "src"
OUT = Path(__file__).resolve().parent
PROFILE_DATABASES = {
    "gl3_mission_rollup_scale_payload_20261113_test",
    "gl3_mission_rollup_scale_payload_after_20261113_test",
}
sys.path.insert(0, str(SRC))

from gridlens.intelligence.customer_results import groups  # noqa: E402
from gridlens.persistence.database import SessionLocal, engine  # noqa: E402


def source_manifest() -> tuple[str, dict[str, str]]:
    entries = {}
    digest = hashlib.sha256()
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        entries[rel] = content_hash
        digest.update(rel.encode())
        digest.update(b"\0")
        digest.update(bytes.fromhex(content_hash))
    return digest.hexdigest(), entries


def summarize_nodes(plan: dict) -> list[dict]:
    result = []
    stack = [plan]
    while stack:
        node = stack.pop()
        output = " ".join(str(item) for item in node.get("Output", []))
        if node.get("Node Type") == "Aggregate" or "jsonb_agg" in output:
            result.append({
                key: node.get(key)
                for key in (
                    "Node Type", "Strategy", "CTE Name", "Subplan Name",
                    "Actual Rows", "Actual Loops", "Actual Total Time", "Plan Rows",
                    "Shared Hit Blocks", "Shared Read Blocks", "Temp Read Blocks",
                    "Temp Written Blocks", "Group Key",
                )
                if key in node
            } | {"has_jsonb_agg_output": "jsonb_agg" in output})
        stack.extend(reversed(node.get("Plans", [])))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("before", "after"), default="before")
    parser.add_argument("--shortlist", action="store_true")
    args = parser.parse_args()
    phase = args.phase
    shortlist = args.shortlist
    url = make_url(os.environ["DATABASE_URL"])
    if url.host not in {"127.0.0.1", "localhost", "::1"} or url.database not in PROFILE_DATABASES or url.query:
        raise SystemExit("Refusing any database except the pinned synthetic loopback *_test database")

    overall_manifest, file_hashes = source_manifest()
    source_head = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    samples = {}
    for canonical_only in (False, True):
        label = "true" if canonical_only else "false"
        mode = "shortlist_" if shortlist else ""
        output = OUT / f"{phase}_{mode}canonical_only_{label}.json"
        if output.exists():
            raise SystemExit(f"Refusing to overwrite {output}")
        captured: list[tuple[str, dict]] = []
        statement_count = [0]

        def capture(_conn, _cursor, statement, parameters, _context, _many):
            statement_count[0] += 1
            normalized = " ".join(statement.lower().split())
            if "count(*) over() as total" in normalized and "from grouped g" in normalized and " limit " in normalized:
                captured.append((statement, dict(parameters)))

        event.listen(engine, "before_cursor_execute", capture)
        try:
            with SessionLocal() as session:
                session.execute(text("SET TRANSACTION READ ONLY"))
                session.execute(text("SET LOCAL statement_timeout = '15s'"))
                session.execute(text("SET LOCAL jit = off"))
                statement_count[0] = 0
                started = perf_counter()
                result = groups(
                    session,
                    limit=25,
                    canonical_only=canonical_only,
                    shortlist=shortlist,
                )
                call_ms = round((perf_counter() - started) * 1000, 3)
                if len(captured) != 1:
                    raise RuntimeError(f"Expected one grouped page SQL statement, got {len(captured)}")
                statement, parameters = captured[0]
                started = perf_counter()
                explain = session.connection().exec_driver_sql(
                    "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement,
                    parameters,
                ).scalar_one()
                explain_ms = round((perf_counter() - started) * 1000, 3)
                corpus = dict(session.execute(text("""
                    SELECT (SELECT count(*) FROM projects) AS projects,
                           (SELECT count(*) FROM power_needs) AS needs,
                           (SELECT count(*) FROM evidence) AS evidence,
                           (SELECT count(*) FROM browse_rows) AS browse_rows
                """)).mappings().one())
        finally:
            event.remove(engine, "before_cursor_execute", capture)

        plan_doc = explain[0]
        receipt = {
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "source": {
                "git_head": source_head,
                "git_status_porcelain": subprocess.check_output(["git", "-C", str(ROOT), "status", "--porcelain"], text=True).strip(),
                "backend_src_py_manifest_sha256": overall_manifest,
                "backend_src_py_file_sha256": file_hashes,
                "profile_harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            },
            "database": url.database,
            "workload": {
                "synthetic_fixture": True,
                "seeded_projects_requested": 40000,
                "corpus_counts": corpus,
                "canonical_only": canonical_only,
                "sector": "all",
                "search": None,
                "shortlist": shortlist,
                "page_size": 25,
                "returned_total_groups": result["total"],
                "returned_page_groups": len(result["items"]),
            },
            "postgres_context": "read-only transaction; SET LOCAL jit=off; SET LOCAL statement_timeout='15s' per statement",
            "measurement": {
                "groups_call_elapsed_ms_including_service_setup": call_ms,
                "sql_statements_during_groups_call": statement_count[0],
                "explain_analyze_elapsed_ms": explain_ms,
                "planning_time_ms": plan_doc.get("Planning Time"),
                "execution_time_ms": plan_doc.get("Execution Time"),
                "query_text_sha256": hashlib.sha256(statement.encode()).hexdigest(),
                "query_parameter_keys": sorted(parameters),
                "query_text": statement,
                "plan": plan_doc["Plan"],
                "aggregate_nodes": summarize_nodes(plan_doc["Plan"]),
            },
            "limitations": [
                "Single diagnostic page call and EXPLAIN ANALYZE per flag, on a synthetic local PostgreSQL corpus; not a latency distribution or production SLA.",
                "Only the account groups page query is explained; subsequent bounded contact/facet and page serialization work contributes to groups-call time.",
            ],
        }
        output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        samples[label] = {
            "receipt": str(output),
            "total_groups": result["total"],
            "page_groups": len(result["items"]),
            "groups_call_ms": call_ms,
            "sql_statements": statement_count[0],
            "explain_execution_ms": plan_doc.get("Execution Time"),
            "query_sha256": receipt["measurement"]["query_text_sha256"],
        }

    summary = {
        "source_head": source_head,
        "source_manifest_sha256": overall_manifest,
        "database": url.database,
        "seed_manifest_sha256": hashlib.sha256((OUT / "payload_seed_manifest.json").read_bytes()).hexdigest(),
        "profiles": samples,
    }
    adjustment_path = OUT / "controlled_policy_binding_adjustment.json"
    if phase == "after":
        if not adjustment_path.exists():
            raise SystemExit("The after profile requires the controlled policy-binding receipt")
        summary["controlled_policy_binding_adjustment"] = json.loads(
            adjustment_path.read_text(encoding="utf-8")
        )
    summary_path = OUT / f"{phase}_{'shortlist_' if shortlist else ''}profiles_summary.json"
    if summary_path.exists():
        raise SystemExit(f"Refusing to overwrite {summary_path}")
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
