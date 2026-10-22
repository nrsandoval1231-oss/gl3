"""Plan or explicitly enqueue bounded retained-evidence buying-chain work."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

MAX_PROJECTS = 100


def _database_session_factory(target_name: str, expected_database_name: str | None):
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import sessionmaker

    from gridlens.settings import settings

    if target_name not in {"test", "application"}:
        raise ValueError("--database-target must be test or application")
    database_url = settings.test_database_url if target_name == "test" else settings.database_url
    if not database_url:
        raise ValueError(f"Backfill target {target_name} is not configured")
    target = make_url(database_url)
    application = make_url(settings.database_url)
    if not target.database:
        raise ValueError("Backfill target has no database name")
    if target_name == "test" and not target.database.endswith("_test"):
        raise ValueError("Test backfill target must end in _test")
    if expected_database_name is not None and target.database != expected_database_name:
        raise ValueError("Target database name does not match --expected-database-name")
    if target_name == "test" and (target.host, target.port, target.database) == (
        application.host,
        application.port,
        application.database,
    ):
        raise ValueError("Backfill refuses to use the application database as the test target")
    engine = create_engine(database_url)
    return engine, sessionmaker(engine, expire_on_commit=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--after-project-id", type=UUID)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--database-target", choices=("test", "application"), default="test")
    parser.add_argument("--expected-database-name")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="enqueue against the selected target; default is read-only dry-run",
    )
    args = parser.parse_args()
    if not 1 <= args.limit <= MAX_PROJECTS:
        parser.error(f"--limit must be between 1 and {MAX_PROJECTS}")
    if args.apply and not args.expected_database_name:
        parser.error("--apply requires --expected-database-name")

    from gridlens.intelligence.buying_chain import retained_buying_chain_backfill

    engine, factory = _database_session_factory(args.database_target, args.expected_database_name)
    try:
        with factory.begin() as session:
            report = retained_buying_chain_backfill(
                session,
                after_project_id=args.after_project_id,
                limit=args.limit,
                enqueue=args.apply,
            )
        report["mode"] = f"apply-{args.database_target}-database" if args.apply else "dry-run"
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
