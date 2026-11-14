"""Measure read-only group response phases on a task-owned synthetic corpus."""

from __future__ import annotations

import hashlib
import argparse
import json
import math
import os
import statistics
import sys
from pathlib import Path
from time import perf_counter

from sqlalchemy import event, text

ROOT = Path(__file__).resolve().parents[4]
from perf_db_guard import perf_database_url  # noqa: E402

env_url = perf_database_url(os.environ.get("DATABASE_URL"))
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--canonical-only", action="store_true")
parser.add_argument("--source-root", type=Path, default=ROOT)
parser.add_argument("--samples", type=int, default=20)
parser.add_argument("--output-name")
args = parser.parse_args()
if not 5 <= args.samples <= 100:
    parser.error("Use 5-100 timed samples")
if args.output_name and (
    Path(args.output_name).name != args.output_name
    or not args.output_name.endswith(".json")
):
    parser.error("output-name must be a JSON filename")
source_root = args.source_root.resolve()
source = source_root / "backend" / "src"
sys.path.insert(0, str(source))

from gridlens.settings import settings  # noqa: E402

url = perf_database_url(settings.database_url)
if url != env_url:
    raise SystemExit("Application DATABASE_URL differs from the validated process URL")

from gridlens.intelligence import customer_results  # noqa: E402
from gridlens.persistence.database import SessionLocal, engine  # noqa: E402

digest = hashlib.sha256()
for path in sorted(source.rglob("*.py")):
    digest.update(str(path.relative_to(source)).encode())
    digest.update(path.read_bytes())

sql_ms = [0.0]
commercial_ms = [0.0]
sql_count = [0]
cursor_started: dict[int, float] = {}


def before_cursor(conn, _cursor, _statement, _parameters, _context, _many):
    cursor_started[id(conn)] = perf_counter()
    sql_count[0] += 1


def after_cursor(conn, _cursor, _statement, _parameters, _context, _many):
    started = cursor_started.pop(id(conn), None)
    if started is not None:
        sql_ms[0] += (perf_counter() - started) * 1000


original_commercial = getattr(customer_results, "_commercial_by_groups", None)


def timed_commercial(*args, **kwargs):
    started = perf_counter()
    try:
        return original_commercial(*args, **kwargs)
    finally:
        commercial_ms[0] += (perf_counter() - started) * 1000


if original_commercial is not None:
    customer_results._commercial_by_groups = timed_commercial
event.listen(engine, "before_cursor_execute", before_cursor)
event.listen(engine, "after_cursor_execute", after_cursor)

results = {}
try:
    for limit in (1, 25, 50):
        rows = []
        for sample in range(args.samples + 1):
            sql_ms[0] = 0.0
            commercial_ms[0] = 0.0
            sql_count[0] = 0
            with SessionLocal() as session:
                session.execute(text("SET TRANSACTION READ ONLY"))
                session.execute(text("SET LOCAL statement_timeout = '15s'"))
                session.execute(text("SET LOCAL jit = off"))
                started = perf_counter()
                group_options = {"limit": limit}
                if args.canonical_only:
                    group_options["canonical_only"] = True
                result = customer_results.groups(session, **group_options)
                total = (perf_counter() - started) * 1000
            if sample == 0:
                # Warm-up only; not included in the reported distributions.
                continue
            encoded = json.dumps(result, default=str, separators=(",", ":")).encode()
            rows.append(
                {
                    "total_ms": round(total, 3),
                    "sql_execute_ms": round(sql_ms[0], 3),
                    "commercial_projection_ms": round(commercial_ms[0], 3),
                    "other_ms_estimate": round(total - sql_ms[0] - commercial_ms[0], 3),
                    "sql_statements": sql_count[0],
                    "payload_bytes": len(encoded),
                    "groups": len(result["items"]),
                    "account_total": result["total"],
                }
            )
        totals = [row["total_ms"] for row in rows]
        results[str(limit)] = {
            "samples": rows,
            "p50_total_ms": statistics.median(totals),
            "p95_total_ms_nearest_rank": sorted(totals)[
                math.ceil(len(totals) * 0.95) - 1
            ],
        }
finally:
    event.remove(engine, "before_cursor_execute", before_cursor)
    event.remove(engine, "after_cursor_execute", after_cursor)
    if original_commercial is not None:
        customer_results._commercial_by_groups = original_commercial

receipt = {
    "phase": "read_only_phase_profile",
    "canonical_only": args.canonical_only,
    "source_root": str(source_root),
    "commit": __import__("subprocess")
    .check_output(["git", "rev-parse", "HEAD"], cwd=source_root, text=True)
    .strip(),
    "source_manifest_sha256": digest.hexdigest(),
    "database": url.database,
    "postgres_context": f"read-only transaction, statement_timeout=15s, jit=off; one warm-up plus {args.samples} timed samples",
    "timing_definitions": {
        "sql_execute_ms": "Sum of DBAPI cursor execute/fetch-call duration captured around each SQLAlchemy execute call.",
        "commercial_projection_ms": "Wall time inside _commercial_by_groups, including SQL and deterministic projection.",
        "other_ms_estimate": "Total less summed cursor-call time and commercial projection; components overlap, so not additive phase partition.",
    },
    "pages": results,
    "limitations": [
        "Synthetic corpus and local PostgreSQL only; direct service calls exclude HTTP/network/browser.",
        "Phase timers overlap by design and are diagnostic, not an SLA.",
    ],
}
out_name = args.output_name or (
    "baseline-canonical-phases.json" if args.canonical_only else "baseline-phases.json"
)
out = (
    ROOT
    / "docs/validation/customer-intelligence-followup-20261113/performance"
    / out_name
)
if out.exists():
    raise SystemExit("Refusing to overwrite baseline receipt")
out.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
print(json.dumps(receipt, indent=2))
