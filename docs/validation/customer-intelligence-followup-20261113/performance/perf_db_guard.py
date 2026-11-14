"""Validate perf-harness database routing before importing app modules."""

from __future__ import annotations

import os
from urllib.parse import urlsplit

from sqlalchemy.dialects.postgresql.psycopg import dialect
from sqlalchemy.engine import URL, make_url

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
PORT = 50833
ROLE = "gl3_audit"
BLOCKED_LIBPQ_ENV = (
    "PGHOST",
    "PGHOSTADDR",
    "PGPORT",
    "PGDATABASE",
    "PGUSER",
    "PGOPTIONS",
    "PGSERVICE",
    "PGSERVICEFILE",
    "PGTARGETSESSIONATTRS",
)


def perf_database_url(
    raw: str | None, *, allowed_databases: set[str] | None = None
) -> URL:
    """Require a pinned, explicit loopback URL and verify its effective libpq args."""
    if any(os.environ.get(name) for name in BLOCKED_LIBPQ_ENV):
        raise SystemExit("Inherited libpq routing overrides are set")
    if not raw:
        raise SystemExit("An explicit DATABASE_URL is required for perf harnesses")
    try:
        url = make_url(raw)
    except Exception as exc:
        raise SystemExit("DATABASE_URL is malformed") from exc
    database = url.database or ""
    database_allowed = (
        database in allowed_databases
        if allowed_databases is not None
        else database.startswith("gl3_perf_followup_") and database.endswith("_test")
    )
    if (
        url.drivername not in {"postgresql", "postgresql+psycopg"}
        or (url.host or "").lower() not in LOOPBACK_HOSTS
        or url.port != PORT
        or url.username != ROLE
        or not database_allowed
        or url.query
        or urlsplit(raw).fragment
    ):
        raise SystemExit("DATABASE_URL must target the pinned loopback perf database")
    args, effective = dialect().create_connect_args(url)
    if (
        args
        or (effective.get("host") or "").lower() not in LOOPBACK_HOSTS
        or effective.get("port") != PORT
        or effective.get("dbname") != database
        or effective.get("user") != ROLE
    ):
        raise SystemExit("Effective libpq parameters differ from the pinned perf URL")
    return url
