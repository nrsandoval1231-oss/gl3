"""Interleave main/candidate legacy reads and candidate default reads."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import statistics
import subprocess
import sys
from pathlib import Path
from time import perf_counter

from sqlalchemy import event, text

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_MAIN = Path(r"C:\Users\nrsan\Nucleus\02_Projects\GridLens\gl3")
from perf_db_guard import perf_database_url  # noqa: E402

env_url = perf_database_url(
    os.environ.get("DATABASE_URL"),
    allowed_databases={"gl3_perf_followup_rollup_scale_candidate_test"},
)
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--main-root", type=Path, default=DEFAULT_MAIN)
parser.add_argument("--samples", type=int, default=20)
parser.add_argument("--output-name", required=True)
args = parser.parse_args()
if not 20 <= args.samples <= 20:
    parser.error("This matched acceptance run requires exactly 20 paired samples")
if Path(args.output_name).name != args.output_name or not args.output_name.endswith(".json"):
    parser.error("output-name must be a simple JSON filename")
main_root = args.main_root.resolve()
if not (main_root / "backend/src/gridlens/intelligence/customer_results.py").is_file():
    parser.error("main-root must contain the customer_results.py source")
sys.path.insert(0, str(ROOT / "backend" / "src"))

from gridlens.settings import settings  # noqa: E402

url = perf_database_url(
    settings.database_url,
    allowed_databases={"gl3_perf_followup_rollup_scale_candidate_test"},
)
if url != env_url:
    raise SystemExit("Application DATABASE_URL differs from the validated process URL")

from gridlens.intelligence import customer_results as candidate_results  # noqa: E402
from gridlens.persistence.database import SessionLocal, engine  # noqa: E402
from gridlens.persistence.models import BrowseGeneration, BrowseState  # noqa: E402

main_path = main_root / "backend/src/gridlens/intelligence/customer_results.py"
spec = importlib.util.spec_from_file_location(
    "gridlens.intelligence.customer_results_main_c5", main_path
)
if spec is None or spec.loader is None:
    raise SystemExit("Could not load main customer_results.py")
main_results = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = main_results
spec.loader.exec_module(main_results)

def source_fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    for source in sorted((path / "backend/src").rglob("*.py")):
        digest.update(str(source.relative_to(path / "backend/src")).encode())
        digest.update(source.read_bytes())
    return digest.hexdigest()


def git_commit(path: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=path, text=True
    ).strip()


def git_dirty_source(path: Path) -> bool:
    output = subprocess.check_output(
        ["git", "status", "--short", "--", "backend/src"], cwd=path, text=True
    )
    return bool(output.strip())


with SessionLocal() as session:
    session.execute(text("SET TRANSACTION READ ONLY"))
    generation_id = session.get(BrowseState, 1).generation_id
    generation = session.get(BrowseGeneration, generation_id)
    if generation is None or generation.row_count != 40000:
        raise SystemExit("Expected the matching 40,000-row disposable fixture generation")

sql_elapsed = [0.0]
sql_calls = [0]
active_starts: dict[int, float] = {}


def before_cursor(conn, _cursor, _statement, _parameters, _context, _many):
    active_starts[id(conn)] = perf_counter()
    sql_calls[0] += 1


def after_cursor(conn, _cursor, _statement, _parameters, _context, _many):
    started = active_starts.pop(id(conn), None)
    if started is not None:
        sql_elapsed[0] += (perf_counter() - started) * 1000


event.listen(engine, "before_cursor_execute", before_cursor)
event.listen(engine, "after_cursor_execute", after_cursor)

def measure(module, *, limit: int, route: str) -> dict:
    sql_elapsed[0] = 0.0
    sql_calls[0] = 0
    with SessionLocal() as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        session.execute(text("SET LOCAL statement_timeout = '15s'"))
        session.execute(text("SET LOCAL jit = off"))
        options = {"limit": limit, "selected_generation": generation}
        if module is candidate_results:
            if route == "candidate_default":
                options["canonical_only"] = True
            else:
                options["canonical_only"] = False
        started = perf_counter()
        result = module.groups(session, **options)
        elapsed_ms = (perf_counter() - started) * 1000
    body = json.dumps(result, default=str, separators=(",", ":")).encode()
    return {
        "total_ms": round(elapsed_ms, 3),
        "sql_execute_ms": round(sql_elapsed[0], 3),
        "sql_statements": sql_calls[0],
        "payload_bytes": len(body),
        "payload_sha256": hashlib.sha256(body).hexdigest(),
        "groups_returned": len(result["items"]),
        "total_groups": result["total"],
        "account_total": result.get("totals", {}).get("accounts"),
    }


results = {}
try:
    routes = {
        "main_legacy": main_results,
        "candidate_legacy": candidate_results,
        "candidate_default": candidate_results,
    }
    # Warm each route/page once before timing, then alternate pair order on every
    # round. The candidate product-default route is interleaved at alternating
    # positions to reduce drift/order bias.
    for limit in (1, 25, 50):
        for route, module in routes.items():
            measure(module, limit=limit, route=route)
        samples = {route: [] for route in routes}
        for round_index in range(args.samples):
            pair = ["main_legacy", "candidate_legacy"]
            if round_index % 2:
                pair.reverse()
            order = (
                ["candidate_default", *pair]
                if round_index % 2
                else [*pair, "candidate_default"]
            )
            for route in order:
                samples[route].append(measure(routes[route], limit=limit, route=route))
        results[str(limit)] = {
            route: {
                "samples": values,
                "p50_total_ms": statistics.median(
                    row["total_ms"] for row in values
                ),
                "p95_total_ms_nearest_rank": sorted(
                    row["total_ms"] for row in values
                )[math.ceil(len(values) * 0.95) - 1],
            }
            for route, values in samples.items()
        }
finally:
    event.remove(engine, "before_cursor_execute", before_cursor)
    event.remove(engine, "after_cursor_execute", after_cursor)

receipt = {
    "phase": "matched_interleaved_40k_read_profile",
    "samples_per_route_page": args.samples,
    "database": url.database,
    "generation_id_sha256": hashlib.sha256(str(generation_id).encode()).hexdigest(),
    "generation_row_count": generation.row_count,
    "fixture_and_session": {
        "statement_timeout": "15s",
        "jit": "off",
        "selected_generation": True,
        "data_mutation": False,
    },
    "source_versions": {
        "main": {
            "root": str(main_root),
            "commit": git_commit(main_root),
            "backend_source_manifest_sha256": source_fingerprint(main_root),
            "backend_source_dirty": git_dirty_source(main_root),
            "execution_scope": (
                "customer_results.py file only, loaded by importlib into the candidate package; "
                "transitive gridlens dependencies resolve from candidate source"
            ),
        },
        "candidate": {
            "root": str(ROOT),
            "commit": git_commit(ROOT),
            "backend_source_manifest_sha256": source_fingerprint(ROOT),
            "backend_source_dirty": git_dirty_source(ROOT),
            "execution_scope": "candidate customer_results.py and candidate package dependencies",
        },
    },
    "route_contract": {
        "main_legacy": "main c5 customer_results.py file control using candidate package dependencies",
        "candidate_legacy": "candidate groups(canonical_only=False), matched explicit legacy path",
        "candidate_default": "candidate groups(canonical_only=True), current default path",
        "limits": [1, 25, 50],
        "round_order": "main/candidate legacy pair alternates first position; candidate default alternates before/after pair",
    },
    "timing_definitions": {
        "total_ms": "Wall time around direct groups() call; includes all SQL and deterministic projection.",
        "sql_execute_ms": "Summed DBAPI cursor execute/fetch-call time for SQL issued during groups().",
        "payload_bytes": "Compact JSON byte count of the returned response body.",
        "payload_sha256": "SHA-256 of returned compact JSON body; raw body omitted.",
    },
    "pages": results,
    "limitations": [
        "One local synthetic 40k fixture, one database clone, and one execution environment.",
        "selected_generation pins one already-published synthetic snapshot to compare query implementations; it bypasses the live current-generation qualification lookup.",
        "Historical account_total samples were produced by reading totals.account_total rather than totals.accounts; those nulls are invalid account-count evidence. The runner now reads totals.accounts.",
        "This is a diagnostic comparison, not a service-level objective or production latency claim.",
    ],
}
output = ROOT / "docs/validation/customer-intelligence-followup-20261113/performance" / args.output_name
if output.exists():
    raise SystemExit("Refusing to overwrite matched profile receipt")
output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"receipt": output.name, "pages": {limit: {route: values["p50_total_ms"] for route, values in page.items()} for limit, page in results.items()}}, indent=2))
