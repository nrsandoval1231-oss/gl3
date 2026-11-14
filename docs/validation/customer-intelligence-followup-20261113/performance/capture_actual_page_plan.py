"""Capture one read-only EXPLAIN ANALYZE plan for a list-page query."""

from __future__ import annotations

import argparse
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
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--limit", type=int, choices=(1, 25, 50), required=True)
parser.add_argument("--canonical-only", action="store_true")
parser.add_argument("--output-prefix", required=True)
args = parser.parse_args()
if Path(args.output_prefix).name != args.output_prefix or ".." in args.output_prefix:
    parser.error("output-prefix must be a simple filename prefix")
sys.path.insert(0, str(ROOT / "backend" / "src"))

from gridlens.settings import settings  # noqa: E402

url = perf_database_url(
    settings.database_url,
    allowed_databases={"gl3_perf_followup_rollup_scale_candidate_test"},
)
if url != env_url:
    raise SystemExit("Application DATABASE_URL differs from the validated process URL")

from gridlens.intelligence import customer_results  # noqa: E402
from gridlens.persistence.database import SessionLocal, engine  # noqa: E402

captured: dict = {}


class QueryCaptured(Exception):
    pass


def intercept(_conn, _cursor, statement, parameters, context, _many):
    normalized = " ".join(statement.lower().split())
    if "page_rows as" not in normalized or "from grouped g" not in normalized:
        return
    captured["sql"] = statement
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
            session.execute(text("SET LOCAL statement_timeout = '15s'"))
            session.execute(text("SET LOCAL jit = off"))
            options = {"limit": args.limit}
            if args.canonical_only:
                options["canonical_only"] = True
            customer_results.groups(session, **options)
    except QueryCaptured:
        pass
finally:
    event.remove(engine, "before_cursor_execute", intercept)

if "sql" not in captured:
    raise SystemExit("List page SQL was not captured")

source = ROOT / "backend" / "src"
manifest = hashlib.sha256()
for path in sorted(source.rglob("*.py")):
    manifest.update(str(path.relative_to(source)).encode())
    manifest.update(path.read_bytes())
query_sha256 = hashlib.sha256(captured["sql"].encode()).hexdigest()
output = ROOT / "docs/validation/customer-intelligence-followup-20261113/performance"
sql_path = output / f"{args.output_prefix}.sql"
receipt_path = output / f"{args.output_prefix}.json"
if sql_path.exists() or receipt_path.exists():
    raise SystemExit("Refusing to overwrite an existing plan receipt")

with SessionLocal() as session:
    session.execute(text("SET TRANSACTION READ ONLY"))
    session.execute(text("SET LOCAL statement_timeout = '15s'"))
    session.execute(text("SET LOCAL jit = off"))
    explain = (
        session.connection()
        .exec_driver_sql(
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + captured["sql"],
            captured["parameters"],
        )
        .scalar_one()[0]
    )
    stats = dict(
        session.execute(
            text("""
                SELECT current_setting('work_mem') AS work_mem,
                       current_setting('statement_timeout') AS statement_timeout,
                       current_setting('server_version') AS server_version,
                       (SELECT count(*) FROM projects) AS projects,
                       (SELECT count(*) FROM browse_rows) AS browse_rows,
                       (SELECT count(*) FROM power_needs) AS needs,
                       (SELECT count(*) FROM evidence) AS evidence,
                       (SELECT count(*) FROM browse_customer_memberships) AS memberships
            """)
        ).mappings().one()
    )


def summarize_bind(name, value):
    if isinstance(value, list):
        encoded = json.dumps([str(item) for item in value], separators=(",", ":"))
        return {
            "kind": "list",
            "count": len(value),
            "sha256": hashlib.sha256(encoded.encode()).hexdigest(),
        }
    if name == "generation":
        return {
            "kind": "synthetic-generation-id",
            "sha256": hashlib.sha256(str(value).encode()).hexdigest(),
        }
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    return {"kind": type(value).__name__}


plan = explain["Plan"]
readable_sql = "\n".join(
    line.rstrip(" \t") for line in captured["sql"].split("\n")
).rstrip("\n") + "\n"
sql_path.write_bytes(readable_sql.encode("utf-8"))
receipt = {
    "source_root": str(ROOT),
    "commit": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip(),
    "source_manifest_sha256": manifest.hexdigest(),
    "database": url.database,
    "route": f"groups(limit={args.limit}, canonical_only={args.canonical_only})",
    "query_file": sql_path.name,
    "query_sha256": query_sha256,
    "captured_sql": captured["sql"],
    "query_file_representation": "derived_readable_export",
    "query_file_note": (
        "Standalone SQL trims trailing horizontal whitespace for readability. "
        "query_sha256 is computed over the byte-exact captured_sql UTF-8 bytes "
        "without a terminal newline."
    ),
    "parameter_values_written": False,
    "bind_parameter_summary": {
        str(name): summarize_bind(str(name), value)
        for name, value in (captured["parameters"] or {}).items()
    },
    "plan_mode": "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON); one actual synthetic read-only query",
    "fixture_and_session": stats,
    "plan": explain,
    "limitations": [
        "One direct local execution is diagnostic, not an SLA or a latency distribution.",
        "Only task-owned disposable synthetic fixture data was read.",
    ],
}
receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
print(
    json.dumps(
        {
            "route": receipt["route"],
            "execution_ms": plan.get("Actual Total Time"),
            "rows": plan.get("Actual Rows"),
            "plan_root": plan.get("Node Type"),
            "temp_read_blocks": plan.get("Temp Read Blocks"),
            "temp_written_blocks": plan.get("Temp Written Blocks"),
            "query_sha256": query_sha256,
        }
    )
)
