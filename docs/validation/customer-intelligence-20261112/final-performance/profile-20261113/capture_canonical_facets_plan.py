"""Capture one read-only plan for canonical-only facet calculation."""

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

ROOT = Path(os.environ.get("PERF_SOURCE_ROOT", "/workspace/gl3-page-payload-opt-20261113")).resolve()
SRC = ROOT / "backend" / "src"
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))

from gridlens.intelligence.customer_results import _facets  # noqa: E402
from gridlens.intelligence.saved_browse import current_generation  # noqa: E402
from gridlens.persistence.database import SessionLocal  # noqa: E402


def source_digest() -> str:
    digest = hashlib.sha256()
    for path in sorted(SRC.rglob("*.py")):
        digest.update(path.relative_to(SRC).as_posix().encode())
        digest.update(b"\0")
        digest.update(bytes.fromhex(hashlib.sha256(path.read_bytes()).hexdigest()))
    return digest.hexdigest()


def walk(plan):
    stack = [plan]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(node.get("Plans", []))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("after", "after_facet"), default="after")
    phase = parser.parse_args().phase
    output = OUT / (
        "canonical_facets_explain_after_facet.json"
        if phase == "after_facet"
        else "canonical_facets_explain.json"
    )
    if output.exists():
        raise SystemExit(f"Refusing to overwrite {output}")
    url = make_url(os.environ["DATABASE_URL"])
    if (
        url.host not in {"127.0.0.1", "localhost", "::1"}
        or url.database
        != (
            "gl3_mission_rollup_scale_payload_after_facet_20261113_test"
            if phase == "after_facet"
            else "gl3_mission_rollup_scale_payload_after_20261113_test"
        )
        or url.query
    ):
        raise SystemExit("Refusing a database other than the pinned synthetic loopback clone")

    captured = []

    def capture(_conn, _cursor, statement, parameters, _context, _many):
        normalized = " ".join(statement.lower().split())
        if (
            "array_agg" in normalized
            and "regions" in normalized
            and "stages" in normalized
            and "from all_rows b join assigned a" in normalized
        ):
            captured.append((statement, dict(parameters)))

    event.listen(SessionLocal.kw["bind"], "before_cursor_execute", capture)
    try:
        with SessionLocal() as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            session.execute(text("SET LOCAL statement_timeout = '15s'"))
            session.execute(text("SET LOCAL jit = off"))
            generation = current_generation(session, allow_stale=True, route="groups")
            started = perf_counter()
            facets = _facets(session, generation, "all", canonical_only=True)
            facets_elapsed_ms = round((perf_counter() - started) * 1000, 3)
            if len(captured) != 1:
                raise RuntimeError(f"Expected one canonical facet query, got {len(captured)}")
            statement, parameters = captured[0]
            started = perf_counter()
            plan_doc = session.connection().exec_driver_sql(
                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON, VERBOSE) " + statement,
                parameters,
            ).scalar_one()[0]
            explain_elapsed_ms = round((perf_counter() - started) * 1000, 3)
    finally:
        event.remove(SessionLocal.kw["bind"], "before_cursor_execute", capture)

    plan = plan_doc["Plan"]
    payload_aggregates = [
        node for node in walk(plan)
        if node.get("Node Type") == "Aggregate"
        and "jsonb_agg" in json.dumps(node.get("Output", [])).lower()
    ]
    manifest = {
        path.relative_to(SRC).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(SRC.rglob("*.py"))
    }
    receipt = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": {
            "worktree": str(ROOT),
            "git_head": subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip(),
            "git_status_porcelain": subprocess.check_output(["git", "-C", str(ROOT), "status", "--porcelain"], text=True).strip(),
            "backend_src_py_manifest_sha256": source_digest(),
            "backend_src_py_file_sha256": manifest,
        },
        "database": url.database,
        "generation_id": str(generation.id),
        "request_mode": {"canonical_only": True, "sector": "all", "shortlist": False},
        "facet_result_counts": {"regions": len(facets["regions"]), "stages": len(facets["stages"])},
        "context": "read-only transaction; SET LOCAL jit=off; SET LOCAL statement_timeout='15s' per statement",
        "measurement": {
            "facets_call_elapsed_ms": facets_elapsed_ms,
            "explain_elapsed_ms": explain_elapsed_ms,
            "planning_time_ms": plan_doc.get("Planning Time"),
            "execution_time_ms": plan_doc.get("Execution Time"),
            "query_sha256": hashlib.sha256(statement.encode()).hexdigest(),
            "query_text": statement,
            "jsonb_aggregate_node_count": len(payload_aggregates),
            "jsonb_aggregate_nodes": [
                {
                    key: node.get(key)
                    for key in (
                        "Node Type", "Strategy", "Subplan Name", "Actual Rows",
                        "Actual Loops", "Actual Total Time", "Temp Read Blocks",
                        "Temp Written Blocks", "Group Key",
                    )
                    if key in node
                }
                for node in payload_aggregates
            ],
            "plan": plan,
        },
        "limitations": [
            "Single synthetic local PostgreSQL facet-plan capture; diagnostic only, not a latency distribution or SLA.",
            "This measures the canonical-only facet SELECT itself, separate from the account page query.",
        ],
    }
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "source_manifest_sha256": receipt["source"]["backend_src_py_manifest_sha256"],
        "facet_counts": receipt["facet_result_counts"],
        "facets_call_ms": facets_elapsed_ms,
        "explain_execution_ms": plan_doc.get("Execution Time"),
        "jsonb_aggregate_node_count": len(payload_aggregates),
        "jsonb_aggregate_nodes": receipt["measurement"]["jsonb_aggregate_nodes"],
    }, indent=2))


if __name__ == "__main__":
    main()
