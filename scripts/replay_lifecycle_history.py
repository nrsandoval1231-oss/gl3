"""Replay accepted, explicitly bound evidence into lifecycle events."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.lifecycle_replay import replay_accepted_lifecycle
from gridlens.settings import settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database-url",
        help="Explicit database URL; takes precedence over configured test URL",
    )
    parser.add_argument(
        "--use-application-database",
        action="store_true",
        help="Explicitly select DATABASE_URL",
    )
    args = parser.parse_args()
    if args.database_url and args.use_application_database:
        parser.error("choose only one database selection option")
    url = args.database_url or (
        settings.database_url
        if args.use_application_database
        else settings.test_database_url
    )
    if not url:
        raise SystemExit("Choose --database-url or configure TEST_DATABASE_URL")
    if not (args.database_url or args.use_application_database):
        database = url.rsplit("/", 1)[-1].split("?", 1)[0]
        if not (database == "test" or database.endswith("_test")):
            raise SystemExit(
                "Refusing replay outside an explicitly named test database"
            )
    engine = create_engine(url)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        version = session.execute(
            __import__("sqlalchemy").text("select version_num from alembic_version")
        ).scalar_one_or_none()
        if version != "0006_lifecycle_identity_versions":
            raise SystemExit(
                f"Database must be migrated to 0006_lifecycle_identity_versions; found {version!r}"
            )
        print(json.dumps(replay_accepted_lifecycle(session), sort_keys=True))
    engine.dispose()


if __name__ == "__main__":
    main()
