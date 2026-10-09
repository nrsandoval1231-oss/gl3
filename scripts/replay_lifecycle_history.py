"""Replay accepted, explicitly bound evidence into lifecycle events."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.lifecycle_replay import replay_accepted_lifecycle
from gridlens.settings import settings

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def validate_test_database_url(database_url: str, application_url: str) -> None:
    target = make_url(database_url)
    application = make_url(application_url)
    endpoint = (target.host, target.port, target.database)
    application_endpoint = (application.host, application.port, application.database)
    if not target.database or not target.database.endswith("_test"):
        raise SystemExit("Refusing replay outside an explicitly named disposable *_test database")
    if endpoint == application_endpoint:
        raise SystemExit("Refusing replay against the configured application database")


def repository_migration_heads() -> set[str]:
    backend_root = REPOSITORY_ROOT / "backend"
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "migrations"))
    return set(ScriptDirectory.from_config(config).get_heads())


def require_repository_heads(found: list[str], expected: set[str]) -> None:
    if set(found) != expected:
        raise SystemExit(
            "Database must already be at the repository Alembic head(s); "
            f"found {sorted(set(found))!r}, expected {sorted(expected)!r}. "
            "The replay command does not run migrations."
        )


def select_database_url(
    explicit_database_url: str | None,
    use_application_database: bool,
    test_database_url: str | None,
    application_database_url: str,
) -> str | None:
    if explicit_database_url and use_application_database:
        raise SystemExit("Choose only one database selection option")
    if use_application_database:
        return application_database_url
    return explicit_database_url or test_database_url


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database-url",
        help="Disposable test database URL; otherwise TEST_DATABASE_URL is used",
    )
    parser.add_argument(
        "--use-application-database",
        action="store_true",
        help=(
            "Select the application database; run only under a separately reviewed "
            "owner procedure"
        ),
    )
    args = parser.parse_args()
    try:
        url = select_database_url(
            args.database_url,
            args.use_application_database,
            settings.test_database_url,
            settings.database_url,
        )
    except SystemExit as exc:
        parser.error(str(exc))
    if not url:
        raise SystemExit("Choose --database-url or configure TEST_DATABASE_URL")
    if not args.use_application_database:
        validate_test_database_url(url, settings.database_url)
    expected_heads = repository_migration_heads()
    engine = create_engine(url)
    try:
        factory = sessionmaker(engine, expire_on_commit=False)
        with factory.begin() as session:
            found_heads = list(
                session.execute(text("select version_num from alembic_version")).scalars()
            )
            require_repository_heads(found_heads, expected_heads)
            print(json.dumps(replay_accepted_lifecycle(session), sort_keys=True))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
