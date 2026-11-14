"""Capture a non-executing plan for the first timed-out list query variant."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import event, text

ROOT = Path(__file__).resolve().parents[4]
from perf_db_guard import perf_database_url  # noqa: E402

env_url = perf_database_url(
    os.environ.get("DATABASE_URL"),
    allowed_databases={"gl3_perf_followup_rollup_scale_candidate_test"},
)
sys.path.insert(0, str(ROOT / "backend" / "src"))

from gridlens.settings import settings  # noqa: E402

url = perf_database_url(
    settings.database_url,
    allowed_databases={"gl3_perf_followup_rollup_scale_candidate_test"},
)
if url != env_url:
    raise SystemExit("Application DATABASE_URL differs from the validated process URL")

from gridlens.intelligence.customer_results import groups  # noqa: E402
from gridlens.persistence.database import SessionLocal, engine  # noqa: E402

old_projection = """jsonb_build_object(
  'browse_title', b.compact->'browse_title',
  'location', b.compact->'location',
  'project_metadata', jsonb_build_object(
    'oil_gas', jsonb_build_object(
      'operator_number', b.compact #> '{project_metadata,oil_gas,operator_number}'),
    'operator', b.compact #> '{project_metadata,operator}',
    'title', b.compact #> '{project_metadata,title}',
    'sector', b.compact #> '{project_metadata,sector}',
    'data_center', jsonb_build_object(
      'owner_developer', b.compact #> '{project_metadata,data_center,owner_developer}'),
    'event', jsonb_build_object(
      'kind', b.compact #> '{project_metadata,event,kind}',
      'source', b.compact #> '{project_metadata,event,source}',
      'evidence_refs', b.compact #> '{project_metadata,event,evidence_refs}')
  )
)"""
needle = "b.compact - ARRAY['customer_facts', 'customer_developments', 'customer_priority', 'contact_actions', 'contact_people']::text[]"
captured: dict = {}


class QueryCaptured(Exception):
    pass


def intercept(_conn, _cursor, statement, parameters, context, _many):
    if "page_rows AS MATERIALIZED" not in statement:
        return
    if needle not in statement:
        raise RuntimeError("Could not find narrow compact expression in compiled query")
    captured["sql"] = statement.replace(needle, old_projection)
    captured["parameters"] = (
        context.compiled_parameters[0]
        if getattr(context, "compiled_parameters", None)
        else parameters
    )
    raise QueryCaptured


event.listen(engine, "before_cursor_execute", intercept)
try:
    try:
        with SessionLocal() as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            session.execute(text("SET LOCAL jit = off"))
            groups(session, limit=25)
    except QueryCaptured:
        pass
finally:
    event.remove(engine, "before_cursor_execute", intercept)

if "sql" not in captured:
    raise SystemExit("List page SQL was not captured")
query_hash = hashlib.sha256(captured["sql"].encode()).hexdigest()
with SessionLocal() as session:
    session.execute(text("SET TRANSACTION READ ONLY"))
    plan = (
        session.connection()
        .exec_driver_sql(
            "EXPLAIN (FORMAT JSON, COSTS, VERBOSE) " + captured["sql"],
            captured["parameters"],
        )
        .scalar_one()[0]
    )


def summary_nodes(plan_root):
    output = []
    stack = [plan_root]
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
                    "Plan Rows",
                    "Plan Width",
                    "Startup Cost",
                    "Total Cost",
                )
                if key in node
            }
        )
        stack.extend(reversed(node.get("Plans", [])))
    return output


receipt = {
    "commit": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip(),
    "database": url.database,
    "failed_variant": "pre-page jsonb_build_object projection, reconstructed from the captured first candidate query",
    "statement_hash_sha256": query_hash,
    "captured_sql": captured["sql"],
    "captured_sql_note": "Byte-exact reconstructed statement hashed as UTF-8 without a terminal newline.",
    "execution": "No query execution; EXPLAIN estimates only, without ANALYZE.",
    "root": {
        key: plan["Plan"][key]
        for key in (
            "Node Type",
            "Plan Rows",
            "Plan Width",
            "Startup Cost",
            "Total Cost",
        )
        if key in plan["Plan"]
    },
    "planning_ms": plan.get("Planning Time"),
    "nodes": summary_nodes(plan["Plan"]),
    "limitations": [
        "EXPLAIN estimates do not establish actual execution cost or identify a runtime cause.",
        "The captured SQL used the same page query with only the initial pre-page compact projection restored.",
    ],
}
out = (
    ROOT
    / "docs/validation/customer-intelligence-followup-20261113/performance/first-candidate-timeout-plan.json"
)
if out.exists():
    raise SystemExit("Refusing to overwrite timeout plan receipt")
out.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
print(json.dumps(receipt["root"], indent=2))
