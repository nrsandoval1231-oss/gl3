"""Read-only customer rollup measurements on an explicitly disposable local corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from pathlib import Path
from time import perf_counter


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=10)
    args = parser.parse_args()
    if not 5 <= args.samples <= 100:
        parser.error("Use 5–100 measured samples")
    if args.output.exists():
        parser.error("Refusing to overwrite prior measurements")
    source = args.source_root.resolve() / "backend" / "src"
    sys.path.insert(0, str(source))
    from sqlalchemy import event, text
    from sqlalchemy.engine import make_url

    from gridlens.intelligence.customer_results import groups
    from gridlens.persistence.database import SessionLocal, engine
    from gridlens.settings import settings

    url = make_url(settings.database_url)
    if url.host not in {"127.0.0.1", "localhost", "::1"} or not (
        url.database and url.database.endswith("_test") and not url.query
    ):
        raise SystemExit("Requires a disposable loopback *_test database with no routing overrides")
    statements = [0]

    @event.listens_for(engine, "before_cursor_execute")
    def count(*_unused):
        statements[0] += 1

    digest = hashlib.sha256()
    for path in sorted(source.rglob("*.py")):
        digest.update(str(path.relative_to(source)).encode())
        digest.update(path.read_bytes())
    with SessionLocal() as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        corpus = dict(session.execute(text("""
            SELECT (SELECT count(*) FROM projects) AS projects,
                   (SELECT count(*) FROM power_needs) AS needs,
                   (SELECT count(*) FROM evidence) AS evidence
        """)).mappings().one())
    results = {}
    for limit in (1, 25, 50):
        times, queries, totals = [], [], []
        for _ in range(args.samples):
            with SessionLocal() as session:
                session.execute(text("SET TRANSACTION READ ONLY"))
                session.execute(text("SET LOCAL statement_timeout = '15s'"))
                statements[0] = 0
                started = perf_counter()
                result = groups(session, limit=limit)
                times.append(round((perf_counter() - started) * 1000, 3))
                queries.append(statements[0])
                totals.append(result["total"])
        ordered = sorted(times)
        results[str(limit)] = {
            "p50_ms": statistics.median(times),
            "p95_ms": ordered[math.ceil(len(ordered) * 0.95) - 1],
            "times_ms": times, "sql_statements": queries, "account_totals": totals,
        }
    receipt = {
        "source_manifest_sha256": digest.hexdigest(), "corpus": corpus,
        "samples_per_page_size": args.samples, "page_sizes": results,
        "measurement": "Direct read-only SQL/service calls; excludes network, authentication and UI",
        "limitations": ["Synthetic source corpus; local PostgreSQL; finite sample; no production SLA"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
