"""Capture the slowest read SQL calls and compact EXPLAIN ANALYZE summaries."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from time import perf_counter

from sqlalchemy import event, text

ROOT = Path(__file__).resolve().parents[4]
from perf_db_guard import perf_database_url  # noqa: E402

env_url = perf_database_url(os.environ.get("DATABASE_URL"))
sys.path.insert(0, str(ROOT / "backend" / "src"))

from gridlens.settings import settings  # noqa: E402

url = perf_database_url(settings.database_url)
if url != env_url:
    raise SystemExit("Application DATABASE_URL differs from the validated process URL")

from gridlens.intelligence.customer_results import groups  # noqa: E402
from gridlens.persistence.database import SessionLocal, engine  # noqa: E402
canonical_only = os.environ.get("PROFILE_CANONICAL_ONLY", "0") == "1"

active: dict[int, tuple[float, str, object]] = {}
statements: list[dict] = []


def before(conn, _cursor, statement, parameters, _context, _many):
    compiled = getattr(_context, "compiled", None)
    explain_sql = str(compiled.statement) if compiled is not None else statement
    explain_parameters = (
        _context.compiled_parameters[0]
        if getattr(_context, "compiled_parameters", None)
        else parameters
    )
    active[id(conn)] = (perf_counter(), explain_sql, explain_parameters)


def after(conn, _cursor, _statement, _parameters, _context, _many):
    item = active.pop(id(conn), None)
    if item:
        started, statement, parameters = item
        statements.append(
            {
                "ms": (perf_counter() - started) * 1000,
                "sql": statement,
                "parameters": parameters,
            }
        )


def plan_nodes(plan):
    output = []
    stack = [plan]
    while stack:
        node = stack.pop()
        output.append(
            {
                key: node[key]
                for key in (
                    "Node Type",
                    "Parent Relationship",
                    "Relation Name",
                    "Alias",
                    "Actual Rows",
                    "Actual Loops",
                    "Actual Total Time",
                    "Plan Rows",
                    "Shared Hit Blocks",
                    "Shared Read Blocks",
                    "Temp Read Blocks",
                    "Temp Written Blocks",
                    "Sort Method",
                    "Disk Usage",
                    "Hash Batches",
                    "Peak Memory Usage",
                )
                if key in node
            }
        )
        stack.extend(reversed(node.get("Plans", [])))
    return output


event.listen(engine, "before_cursor_execute", before)
event.listen(engine, "after_cursor_execute", after)
try:
    with SessionLocal() as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        session.execute(text("SET LOCAL statement_timeout = '15s'"))
        session.execute(text("SET LOCAL jit = off"))
        result = groups(session, limit=25, canonical_only=canonical_only)
        sql_calls = [
            row
            for row in statements
            if row["sql"].lstrip().lower().startswith("with")
            or row["sql"].lstrip().lower().startswith("select")
        ]
        top = sorted(sql_calls, key=lambda row: row["ms"], reverse=True)[:3]
        plans = []
        for entry in top:
            query_hash = hashlib.sha256(entry["sql"].encode()).hexdigest()
            explain = session.execute(
                text(
                    "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON, VERBOSE) " + entry["sql"]
                ),
                entry["parameters"],
            ).scalar_one()[0]
            plans.append(
                {
                    "query_sha256": query_hash,
                    "sql_prefix": " ".join(entry["sql"].split())[:400],
                    "sql_suffix": " ".join(entry["sql"].split())[-1000:],
                    "cursor_execute_ms": round(entry["ms"], 3),
                    "plan_execution_ms": explain["Execution Time"],
                    "planning_ms": explain["Planning Time"],
                    "root": {
                        key: explain["Plan"][key]
                        for key in (
                            "Node Type",
                            "Actual Rows",
                            "Actual Loops",
                            "Actual Total Time",
                            "Shared Hit Blocks",
                            "Shared Read Blocks",
                            "Temp Read Blocks",
                            "Temp Written Blocks",
                            "Plan Rows",
                        )
                        if key in explain["Plan"]
                    },
                    "nodes": plan_nodes(explain["Plan"]),
                }
            )
finally:
    event.remove(engine, "before_cursor_execute", before)
    event.remove(engine, "after_cursor_execute", after)

receipt = {
    "commit": __import__("subprocess")
    .check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True)
    .strip(),
    "database": url.database,
    "route": "groups(limit=25, sector=all, canonical_only="
    + str(canonical_only).lower()
    + "), read-only, jit=off, statement_timeout=15s",
    "groups_returned": len(result["items"]),
    "sql_calls": len(sql_calls),
    "top_sql": plans,
    "limitations": [
        "One synthetic local sample; EXPLAIN ANALYZE is diagnostic and no production SLA is implied.",
        "SQL text and bind values are excluded from receipt; plans include synthetic row and buffer counts.",
    ],
}
out_name = os.environ.get("PROFILE_OUTPUT_NAME") or (
    "baseline-canonical-top-sql.json" if canonical_only else "baseline-top-sql.json"
)
if Path(out_name).name != out_name or not out_name.endswith(".json"):
    raise SystemExit("Invalid receipt output name")
out = (
    ROOT
    / "docs/validation/customer-intelligence-followup-20261113/performance"
    / out_name
)
if out.exists():
    raise SystemExit("Refusing to overwrite SQL plan receipt")
out.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
print(json.dumps(receipt, indent=2))
