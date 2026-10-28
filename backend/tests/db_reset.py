"""Shared database reset for integration tests.

Historically every integration fixture destroyed and re-created the full
73-table schema around each test (`Base.metadata.drop_all` + `create_all`,
~0.46s each way — ~556s per full suite). The schema is now created once per
test database URL and kept; per-test isolation comes from truncating every
table in a single `TRUNCATE ... CASCADE` statement.

Tests that intentionally exercise DDL or migrations keep their own
drop/create path (see the deployment audit, 03 — PYTEST_BOTTLENECKS.md).
"""

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import ProgrammingError

from gridlens.persistence import (
    models as _models,  # noqa: F401  # registers all tables on Base.metadata
)
from gridlens.persistence.database import Base

_SCHEMA_READY_URLS: set[str] = set()

# Trigger names installed by gridlens.persistence.browse_invalidation.install().
# Tests that install these on the shared test schema must drop them again so
# later modules see the same pristine schema a drop_all/create_all used to give
# them (TRUNCATE removes rows but not triggers).


def drop_browse_triggers(engine: Engine) -> None:
    """Remove browse-invalidation triggers installed on the shared schema."""
    with engine.begin() as connection:
        rows = connection.exec_driver_sql(
            """
            SELECT tgname, tgrelid::regclass::text
            FROM pg_trigger
            WHERE tgname ~ '^(invalidate_browse|dirty_browse)'
            """
        ).all()
        for name, table in rows:
            connection.exec_driver_sql(f'DROP TRIGGER IF EXISTS "{name}" ON {table}')


def reset_test_database(engine: Engine) -> None:
    """Ensure the schema exists once, then remove all rows for a clean test.

    Equivalent isolation to drop_all + create_all for row data, without the
    per-test DDL churn. Safe to call from function-scoped fixtures.
    """
    key = engine.url.render_as_string(hide_password=True)
    if key not in _SCHEMA_READY_URLS:
        Base.metadata.create_all(engine)
        _SCHEMA_READY_URLS.add(key)
    tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    if not tables:
        return
    # RESTART IDENTITY keeps sequence values equivalent to a fresh schema.
    statement = text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE")
    try:
        with engine.begin() as connection:
            # Suppress user triggers (e.g. browse-invalidation triggers a test
            # may have installed on the shared schema) while truncating.
            connection.exec_driver_sql("SET LOCAL session_replication_role = replica")
            connection.execute(statement)
    except ProgrammingError as exc:
        message = str(exc)
        if "InsufficientPrivilege" in message or "permission" in message.lower():
            # Non-superuser test role: truncate with triggers firing instead.
            with engine.begin() as connection:
                connection.execute(statement)
        elif "UndefinedTable" in message:
            # A DDL-focused test module may have dropped the shared schema after
            # our first creation. Recreate it and retry the reset once.
            Base.metadata.create_all(engine)
            with engine.begin() as connection:
                connection.exec_driver_sql("SET LOCAL session_replication_role = replica")
                connection.execute(statement)
        else:
            raise
