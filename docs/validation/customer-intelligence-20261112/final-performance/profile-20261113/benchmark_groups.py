"""Ten read-only page timing samples for the pinned synthetic 40k corpus."""

from __future__ import annotations

import argparse
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

ROOT = Path(
    os.environ.get("PERF_SOURCE_ROOT", "/workspace/gl3-page-payload-opt-20261113")
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


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * p) - 1)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("before", "after"), required=True)
    parser.add_argument("--samples", type=int, default=10)
    args = parser.parse_args()
    if args.samples != 10:
        parser.error("This matched receipt is intentionally fixed at 10 samples")
    url = make_url(os.environ["DATABASE_URL"])
    expected_db = (
        "gl3_mission_rollup_scale_payload_20261113_test"
        if args.phase == "before"
        else "gl3_mission_rollup_scale_payload_after_20261113_test"
    )
    if url.host not in {"127.0.0.1", "localhost", "::1"} or url.database != expected_db or url.query:
        raise SystemExit(f"Refusing a database other than pinned loopback {expected_db}")

    overall_manifest, file_hashes = source_manifest()
    source_head = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    seed_path = OUT / "payload_seed_manifest.json"
    seed_manifest = json.loads(seed_path.read_text(encoding="utf-8"))
    samples_by_scope = {}

    statements = [0]

    def count(*_unused):
        statements[0] += 1

    event.listen(engine, "before_cursor_execute", count)
    try:
        for canonical_only in (False, True):
            times_ms = []
            statement_counts = []
            response_bytes = []
            totals = []
            page_counts = []
            for _ in range(args.samples):
                with SessionLocal() as session:
                    session.execute(text("SET TRANSACTION READ ONLY"))
                    session.execute(text("SET LOCAL statement_timeout = '15s'"))
                    session.execute(text("SET LOCAL jit = off"))
                    statements[0] = 0
                    started = perf_counter()
                    payload = groups(session, limit=25, canonical_only=canonical_only)
                    elapsed = round((perf_counter() - started) * 1000, 3)
                    encoded = json.dumps(payload, default=str, ensure_ascii=False).encode()
                    times_ms.append(elapsed)
                    statement_counts.append(statements[0])
                    response_bytes.append(len(encoded))
                    totals.append(payload["total"])
                    page_counts.append(len(payload["items"]))
            samples_by_scope[str(canonical_only).lower()] = {
                "samples_ms": times_ms,
                "p50_ms": round(statistics.median(times_ms), 3),
                "p95_ms_nearest_rank": percentile(times_ms, 0.95),
                "min_ms": min(times_ms),
                "max_ms": max(times_ms),
                "sql_statement_counts": statement_counts,
                "response_bytes": response_bytes,
                "total_groups": totals,
                "page_groups": page_counts,
            }
    finally:
        event.remove(engine, "before_cursor_execute", count)

    receipt = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "phase": args.phase,
        "source": {
            "worktree": str(ROOT),
            "git_head": source_head,
            "git_status_porcelain": subprocess.check_output(["git", "-C", str(ROOT), "status", "--porcelain"], text=True).strip(),
            "backend_src_py_manifest_sha256": overall_manifest,
            "backend_src_py_file_sha256": file_hashes,
            "benchmark_harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        },
        "runtime": {
            "python": platform.python_version(),
            "sqlalchemy": __import__("sqlalchemy").__version__,
            "soupsieve": __import__("soupsieve").__version__,
        },
        "database": expected_db,
        "snapshot": {
            "generation_id": seed_manifest["generation_id"],
            "seed_manifest_sha256": hashlib.sha256(seed_path.read_bytes()).hexdigest(),
            "seeded_projects": seed_manifest["total_rows"],
            "synthetic_only": True,
            "candidate_policy_binding_adjustment": (
                "See controlled_policy_binding_adjustment.json; clone changed only current generation policy_version to candidate source fingerprint."
                if args.phase == "after"
                else None
            ),
        },
        "context": "read-only SQL/service call; SET LOCAL jit=off; SET LOCAL statement_timeout='15s' per statement; page size 25; sector all; no search; shortlist false",
        "measurement": "Ten `groups()` service calls per canonical_only mode; includes query setup and post-query service work, excludes HTTP/authentication/UI. Samples are sequential within each source revision.",
        "page_sizes": samples_by_scope,
        "limitations": [
            "Synthetic local PostgreSQL only; results are not a production SLA.",
            "p95 uses nearest-rank on 10 samples (therefore the maximum); timing may include shared-host scheduling and cache effects.",
            "The pre-change and after-change runs use PostgreSQL template-cloned databases; candidate clone has the explicit test-only policy_version binding described in its receipt.",
            "Payload contract parity is measured separately in payload_parity.json for all four canonical_only × shortlist combinations.",
        ],
    }
    output = OUT / f"{args.phase}_timing_10.json"
    if output.exists():
        raise SystemExit(f"Refusing to overwrite {output}")
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "phase": args.phase,
        "source_head": source_head,
        "source_manifest_sha256": overall_manifest,
        "database": expected_db,
        "pages": {
            key: {"p50_ms": value["p50_ms"], "p95_ms_nearest_rank": value["p95_ms_nearest_rank"], "sql_counts": value["sql_statement_counts"]}
            for key, value in samples_by_scope.items()
        },
    }, indent=2))


if __name__ == "__main__":
    main()
