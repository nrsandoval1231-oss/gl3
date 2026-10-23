"""Compare read-only API work on the same isolated corpus and configuration.

Run with a source root and an ignored env file. Authentication is bypassed only
inside this local TestClient harness; all database transactions are read-only.
This measures routing, serialization and SQL, not network or login latency.
"""

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

from dotenv import dotenv_values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--env", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=10)
    args = parser.parse_args()
    for key, value in dotenv_values(args.env).items():
        if value is not None:
            os.environ[key] = value
    sys.path.insert(0, str(args.root.resolve() / "backend" / "src"))
    from fastapi.testclient import TestClient
    from sqlalchemy import event, text

    from gridlens.api.app import app, require_session
    from gridlens.persistence.database import engine

    @event.listens_for(engine, "begin")
    def readonly(connection):
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        connection.exec_driver_sql("SET LOCAL statement_timeout='10s'")

    counter = [0]

    @event.listens_for(engine, "before_cursor_execute")
    def count(*unused):
        counter[0] += 1

    app.dependency_overrides[require_session] = lambda: None
    result = {"root": str(args.root), "samples_per_endpoint": args.samples, "api": {}}
    with engine.connect() as connection:
        result["corpus"] = dict(
            connection.execute(
                text(
                    "SELECT (SELECT count(*) FROM observations) AS observations,(SELECT count(*) FROM evidence) AS evidence,(SELECT count(*) FROM projects) AS projects"
                )
            )
            .mappings()
            .one()
        )
    with TestClient(app) as client:
        for endpoint in (
            "/health/ready",
            "/api/health",
            "/api/opportunities?limit=50",
            "/api/customer-accounts?limit=25",
        ):
            times, statements, statuses = [], [], []
            for _ in range(args.samples):
                counter[0] = 0
                start = time.perf_counter()
                response = client.get(endpoint)
                times.append(round((time.perf_counter() - start) * 1000, 3))
                statements.append(counter[0])
                statuses.append(response.status_code)
            ordered = sorted(times)
            result["api"][endpoint] = {
                "statuses": statuses,
                "times_ms": times,
                "p50_ms": statistics.median(times),
                "p95_ms": ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))],
                "sql_statements": statements,
            }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
