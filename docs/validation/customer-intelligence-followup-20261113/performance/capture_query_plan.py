"""Capture one list-page SQL statement and its nonexecuting planner estimate."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[4]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source-root", type=Path, default=ROOT)
parser.add_argument("--limit", type=int, choices=(1, 25, 50), required=True)
parser.add_argument("--output-prefix", required=True)
parser.add_argument("--canonical-only", action="store_true")
args = parser.parse_args()
if Path(args.output_prefix).name != args.output_prefix or ".." in args.output_prefix:
    parser.error("output-prefix must be a simple filename prefix")
source_root = args.source_root.resolve()
sys.path.insert(0, str(source_root / "backend" / "src"))

from gridlens.intelligence import customer_results  # noqa: E402
from gridlens.persistence.database import SessionLocal, engine  # noqa: E402
from gridlens.settings import settings  # noqa: E402

url = make_url(settings.database_url)
if (
    url.host not in {"127.0.0.1", "localhost", "::1"}
    or url.port != 50833
    or not (url.database or "").startswith("gl3_perf_followup_")
    or not url.database.endswith("_test")
    or url.query
):
    raise SystemExit("Requires task-owned loopback port 50833 *_test database")

captured: dict = {}


class QueryCaptured(Exception):
    pass


def intercept(_conn, _cursor, statement, parameters, context, _many):
    lowered = statement.lower()
    if "page_rows as" not in lowered and "count(*) over() as total" not in lowered:
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
query_hash = hashlib.sha256(captured["sql"].encode()).hexdigest()
with SessionLocal() as session:
    session.execute(text("SET TRANSACTION READ ONLY"))
    session.execute(text("SET LOCAL jit = off"))
    plan = (
        session.connection()
        .exec_driver_sql(
            "EXPLAIN (FORMAT JSON, COSTS, VERBOSE) " + captured["sql"],
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
        )
        .mappings()
        .one()
    )
    analyze_stats = [
        dict(row)
        for row in session.execute(
            text("""
            SELECT c.relname, c.reltuples::bigint AS estimated_live_rows,
                   s.n_live_tup, s.last_analyze, s.last_autoanalyze
            FROM pg_class c
            JOIN pg_namespace n ON n.oid=c.relnamespace
            LEFT JOIN pg_stat_user_tables s ON s.relid=c.oid
            WHERE n.nspname=current_schema()
              AND c.relname IN ('projects','browse_rows','power_needs','evidence',
                                'browse_customer_memberships','company_identities')
            ORDER BY c.relname
        """)
        )
        .mappings()
        .all()
    ]


def summarize_bind(name, value):
    if isinstance(value, list):
        encoded = json.dumps([str(item) for item in value], separators=(",", ":"))
        return {
            "kind": "list",
            "count": len(value),
            "sha256": hashlib.sha256(encoded.encode()).hexdigest(),
        }
    if name in {"priority_map", "need_alias_map"} and isinstance(value, str):
        try:
            parsed = json.loads(value)
            return {
                "kind": "json-object",
                "key_count": len(parsed),
                "value_kinds": sorted(
                    {type(item).__name__ for item in parsed.values()}
                ),
            }
        except json.JSONDecodeError:
            return {"kind": "string", "length": len(value)}
    if name == "generation":
        return {
            "kind": "synthetic-generation-id",
            "sha256": hashlib.sha256(str(value).encode()).hexdigest(),
        }
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    return {"kind": type(value).__name__}


source = source_root / "backend" / "src"
manifest = hashlib.sha256()
for path in sorted(source.rglob("*.py")):
    manifest.update(str(path.relative_to(source)).encode())
    manifest.update(path.read_bytes())
commit = subprocess.check_output(
    ["git", "rev-parse", "HEAD"], cwd=source_root, text=True
).strip()
prefix = (
    ROOT
    / "docs/validation/customer-intelligence-followup-20261113/performance"
    / args.output_prefix
)
sql_path = prefix.with_suffix(".sql")
json_path = prefix.with_name(prefix.stem + "-plan.json")
if sql_path.exists() or json_path.exists():
    raise SystemExit("Refusing to overwrite a SQL plan receipt")
sql_path.write_text(captured["sql"] + "\n", encoding="utf-8")
receipt = {
    "source_root": str(source_root),
    "commit": commit,
    "source_manifest_sha256": manifest.hexdigest(),
    "database": url.database,
    "route": f"groups(limit={args.limit}, canonical_only={args.canonical_only})",
    "query_file": sql_path.name,
    "query_sha256": query_hash,
    "parameter_values_written": False,
    "bind_parameter_summary": {
        str(name): summarize_bind(str(name), value)
        for name, value in (captured["parameters"] or {}).items()
    },
    "plan_mode": "EXPLAIN (FORMAT JSON, COSTS, VERBOSE), no ANALYZE and no query execution",
    "fixture_and_session": stats,
    "planner_statistics": analyze_stats,
    "plan": plan,
    "limitations": [
        "Planner estimates are not measured execution and do not establish the timeout cause.",
        "Database contains only disposable synthetic fixture rows.",
    ],
}
json_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
print(
    json.dumps(
        {
            "query_sha256": query_hash,
            "planning_plan_root": {
                key: plan["Plan"][key]
                for key in ("Node Type", "Startup Cost", "Total Cost", "Plan Rows", "Plan Width")
                if key in plan["Plan"]
            },
        },
        default=str,
    )
)
