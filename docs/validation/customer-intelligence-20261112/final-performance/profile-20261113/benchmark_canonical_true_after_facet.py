"""Ten read-only canonical customer page samples after facet aggregation removal."""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import statistics
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

from gridlens.intelligence.customer_results import groups  # noqa: E402
from gridlens.persistence.database import SessionLocal, engine  # noqa: E402


def manifest_digest() -> tuple[str, dict[str, str]]:
    files = {}
    digest = hashlib.sha256()
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        value = hashlib.sha256(path.read_bytes()).hexdigest()
        files[rel] = value
        digest.update(rel.encode())
        digest.update(b"\0")
        digest.update(bytes.fromhex(value))
    return digest.hexdigest(), files


def nearest_rank(values, p):
    return sorted(values)[max(0, math.ceil(len(values) * p) - 1)]


def main() -> None:
    url = make_url(os.environ["DATABASE_URL"])
    if (
        url.host not in {"127.0.0.1", "localhost", "::1"}
        or url.database != "gl3_mission_rollup_scale_payload_after_facet_20261113_test"
        or url.query
    ):
        raise SystemExit("Refusing anything other than the pinned after-facet synthetic *_test clone")
    output = OUT / "after_facet_canonical_true_timing_10.json"
    if output.exists():
        raise SystemExit(f"Refusing to overwrite {output}")
    seed_path = OUT / "payload_seed_manifest.json"
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    policy_adjustment_path = OUT / "controlled_policy_binding_adjustment_after_facet.json"
    if not policy_adjustment_path.exists():
        raise SystemExit("Missing controlled after-facet test policy-binding receipt")

    statement_count = [0]

    def count(*_unused):
        statement_count[0] += 1

    event.listen(engine, "before_cursor_execute", count)
    times_ms = []
    sql_counts = []
    payload_bytes = []
    totals = []
    page_sizes = []
    try:
        for _ in range(10):
            with SessionLocal() as session:
                session.execute(text("SET TRANSACTION READ ONLY"))
                session.execute(text("SET LOCAL statement_timeout = '15s'"))
                session.execute(text("SET LOCAL jit = off"))
                statement_count[0] = 0
                started = perf_counter()
                result = groups(session, limit=25, canonical_only=True, shortlist=False)
                times_ms.append(round((perf_counter() - started) * 1000, 3))
                sql_counts.append(statement_count[0])
                payload_bytes.append(len(json.dumps(result, default=str, ensure_ascii=False).encode()))
                totals.append(result["total"])
                page_sizes.append(len(result["items"]))
    finally:
        event.remove(engine, "before_cursor_execute", count)

    manifest, files = manifest_digest()
    previous = json.loads((OUT / "after_timing_10.json").read_text(encoding="utf-8"))
    previous_true = previous["page_sizes"]["true"]
    receipt = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": {
            "worktree": str(ROOT),
            "git_head": subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip(),
            "git_status_porcelain": subprocess.check_output(["git", "-C", str(ROOT), "status", "--porcelain"], text=True).strip(),
            "backend_src_py_manifest_sha256": manifest,
            "backend_src_py_file_sha256": files,
        },
        "runtime": {
            "python": platform.python_version(),
            "sqlalchemy": __import__("sqlalchemy").__version__,
            "soupsieve": __import__("soupsieve").__version__,
        },
        "database": url.database,
        "snapshot": {
            "generation_id": seed["generation_id"],
            "seed_manifest_sha256": hashlib.sha256(seed_path.read_bytes()).hexdigest(),
            "seeded_projects": seed["total_rows"],
            "controlled_policy_binding_adjustment": policy_adjustment_path.name,
        },
        "workload": {
            "canonical_only": True,
            "shortlist": False,
            "sector": "all",
            "search": None,
            "page_size": 25,
            "total_groups": totals,
            "page_groups": page_sizes,
            "response_bytes": payload_bytes,
            "sql_statement_counts": sql_counts,
        },
        "context": "read-only transactions; SET LOCAL jit=off; SET LOCAL statement_timeout='15s' per statement",
        "measurement": {
            "samples_ms": times_ms,
            "p50_ms": round(statistics.median(times_ms), 3),
            "p95_ms_nearest_rank": nearest_rank(times_ms, 0.95),
            "previous_candidate_without_facet_optimization_p50_ms": previous_true["p50_ms"],
            "previous_candidate_without_facet_optimization_p95_ms_nearest_rank": previous_true[
                "p95_ms_nearest_rank"
            ],
        },
        "limitations": [
            "Ten samples on synthetic local PostgreSQL; nearest-rank p95 is the maximum sample.",
            "Compared with the prior candidate on a template-cloned database; test-only policy binding is documented separately.",
            "Not a production latency guarantee.",
        ],
    }
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "source_manifest_sha256": manifest,
        "p50_ms": receipt["measurement"]["p50_ms"],
        "p95_ms_nearest_rank": receipt["measurement"]["p95_ms_nearest_rank"],
        "previous_candidate_p50_ms": previous_true["p50_ms"],
        "previous_candidate_p95_ms": previous_true["p95_ms_nearest_rank"],
        "sql_counts": sql_counts,
    }, indent=2))


if __name__ == "__main__":
    main()
