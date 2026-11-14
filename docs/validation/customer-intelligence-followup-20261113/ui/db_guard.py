"""Fail-closed routing checks for the disposable native UI database harness."""

from __future__ import annotations

import ipaddress
import os
import re

from sqlalchemy.engine import URL, make_url

_SAFE_DATABASE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,62}\Z")
_LIBPQ_ROUTING = ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE")


def _parse_loopback(raw: str) -> URL:
    try:
        url = make_url(raw)
        host = url.host
        port = url.port
    except Exception:
        raise ValueError("Database URLs must use an explicit loopback PostgreSQL endpoint") from None
    if url.drivername != "postgresql+psycopg" or not host or not url.database:
        raise ValueError("Database URLs must use an explicit loopback PostgreSQL endpoint")
    normalized = host.rstrip(".").lower()
    try:
        loopback = normalized == "localhost" or ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        loopback = normalized == "localhost"
    if not loopback or not _SAFE_DATABASE.fullmatch(url.database) or (port is not None and not 1 <= port <= 65535):
        raise ValueError("Database URLs must use an explicit loopback PostgreSQL endpoint")
    if url.query:
        raise ValueError("Database URL query routing options are not allowed")
    return url


def validate_database_urls(test_raw: str, application_raw: str, environ: dict[str, str] | None = None) -> URL:
    """Validate both URLs before creating an engine or issuing SQL."""
    environment = os.environ if environ is None else environ
    if any(name in environment for name in _LIBPQ_ROUTING):
        raise ValueError("libpq host or service environment overrides are not allowed")
    test_url = _parse_loopback(test_raw)
    app_url = _parse_loopback(application_raw)
    if not test_url.database.endswith("_test") or test_url.database == app_url.database:
        raise ValueError("Test and application databases must be distinct and the test database must end in _test")
    return test_url


def validate_target_database(test_url: URL, application_raw: str, database: str) -> URL:
    """Validate a generated test database name before substituting it into the URL."""
    app_url = _parse_loopback(application_raw)
    if not _SAFE_DATABASE.fullmatch(database) or not database.endswith("_test") or database == app_url.database:
        raise ValueError("Generated database must be a distinct disposable *_test database")
    return test_url.set(database=database)
