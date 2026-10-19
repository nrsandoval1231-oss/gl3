"""Read-only API timings against an explicitly disposable, already populated database.

Run baseline and candidate in separate processes with identical synthetic database
clones. This measures local API/database work, not browser rendering or production
network latency. Credentials are read from environment/ignored files and never logged.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from pathlib import Path
from time import perf_counter


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    parser.add_argument("--mode", choices=("baseline", "candidate"), required=True)
    parser.add_argument("--database-name", required=True)
    parser.add_argument("--auth-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=10)
    args = parser.parse_args()
    if not args.database_name.endswith("_test") or not 3 <= args.samples <= 100:
        parser.error("Use a dedicated *_test database and 3..100 samples")

    from dotenv import dotenv_values
    from sqlalchemy.engine import make_url

    for key, value in dotenv_values(Path.cwd() / ".env").items():
        os.environ.setdefault(key, value or "")
    url = make_url(os.environ["DATABASE_URL"]).set(database=args.database_name)
    os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
    os.environ["SAVED_BROWSE_ENABLED"] = "true"
    sys.path.insert(0, str(args.source_root.resolve() / "backend" / "src"))

    from fastapi.testclient import TestClient
    from sqlalchemy import func, select

    from gridlens.api.app import app
    from gridlens.persistence.database import SessionLocal
    from gridlens.persistence.models import Evidence, Observation, PowerNeed

    with SessionLocal() as session:
        corpus = {
            "power_needs": session.scalar(select(func.count()).select_from(PowerNeed)),
            "observations": session.scalar(select(func.count()).select_from(Observation)),
            "evidence": session.scalar(select(func.count()).select_from(Evidence)),
        }
        need_id = session.scalar(select(PowerNeed.id).order_by(PowerNeed.id).limit(1))
    prefix = "/api/opportunities/workspace" if args.mode == "candidate" else "/api/opportunities"
    paths = {
        "list": f"{prefix}?tier=Signal&limit=25&sort={'priority' if args.mode == 'candidate' else 'rank'}",
        "filter": f"{prefix}?tier=Signal&limit=25&geography=Dallas%2C%20TX",
        "sort": f"{prefix}?tier=Signal&limit=25&sort={'project' if args.mode == 'candidate' else 'updated'}",
        "detail": f"/api/opportunities/needs/{need_id}",
    }
    if args.mode == "baseline":
        paths["commercial_queue"] = "/api/commercial/triage?limit=50"
    client = TestClient(app)
    login = client.post("/api/auth/login", json={"password": args.auth_file.read_text().strip()})
    if login.status_code != 200:
        raise SystemExit("Local test authentication failed")
    metrics = {}
    for name, path in paths.items():
        values = []
        for _ in range(args.samples):
            started = perf_counter()
            response = client.get(path)
            values.append(round((perf_counter() - started) * 1000, 3))
            if response.status_code != 200:
                break
        metrics[name] = {
            "milliseconds": values,
            "median_ms": statistics.median(values),
            "max_ms": max(values),
            "status": response.status_code,
            "response_bytes": len(response.content),
        }
    result = {
        "mode": args.mode,
        "corpus": corpus,
        "data_kind": "SYNTHETIC; not retained or live acceptance",
        "transport": "in-process TestClient + local PostgreSQL 18",
        "limitations": "No browser render, network, concurrency or production SLO claim",
        "metrics": metrics,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
