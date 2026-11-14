import ipaddress
import os
import socket

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from gridlens.settings import Settings, settings


def _base_test_database_url() -> str:
    """Resolve the base test database URL without caching the settings singleton.

    A direct environment export wins; the repository .env is the fallback so
    parallel runs work without exporting anything. Settings() is constructed
    fresh (never get_settings()) because workers must read the base URL before
    the lazy singleton builds and gets pointed at a worker database.
    """
    base = os.environ.get("TEST_DATABASE_URL", "")
    if base:
        return base
    try:
        return Settings().test_database_url
    except Exception:  # missing .env or required fields: behave as if unset
        return ""


def _unsafe_test_database_url() -> pytest.UsageError:
    """Return a generic error that never includes URL credentials or query data."""
    return pytest.UsageError(
        "TEST_DATABASE_URL must target a local PostgreSQL test database with a safe name"
    )


def _validated_test_database_url(raw: str):
    """Validate routing and names before any engine can make a connection."""
    try:
        url = make_url(raw)
        database = url.database
        host = url.host
        # Accessing port can raise for malformed URL values; validate it here too.
        _ = url.port
    except Exception:
        raise _unsafe_test_database_url() from None

    if url.drivername != "postgresql+psycopg" or not database or not host:
        raise _unsafe_test_database_url() from None
    if not database.endswith("_test"):
        raise _unsafe_test_database_url() from None
    if (
        not database.isascii()
        or not database.replace("_", "a").isalnum()
        or not database[0].isalpha()
        and database[0] != "_"
    ):
        raise _unsafe_test_database_url() from None
    if len(database.encode("utf-8")) > 63:
        raise _unsafe_test_database_url() from None

    normalized_host = host.rstrip(".").lower()
    try:
        loopback = (
            normalized_host == "localhost" or ipaddress.ip_address(normalized_host).is_loopback
        )
    except ValueError:
        loopback = normalized_host == "localhost"
    if not loopback:
        raise _unsafe_test_database_url() from None

    # libpq query parameters override URL routing/name fields. Service files can
    # also redirect connections without changing the visible URL host.
    forbidden_query = {"host", "hostaddr", "database", "dbname", "service", "servicefile"}
    if forbidden_query.intersection(key.lower() for key in url.query):
        raise _unsafe_test_database_url() from None
    if any(os.environ.get(name) for name in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE")):
        raise _unsafe_test_database_url() from None
    return url


def _worker_database_name(database: str, worker: str) -> str:
    if (
        not database.endswith("_test")
        or not worker.isascii()
        or not worker.replace("_", "a").isalnum()
    ):
        raise _unsafe_test_database_url() from None
    stem = database[: -len("_test")]
    derived = f"{stem}_{worker}_test"
    if (
        not derived.isascii()
        or not derived.replace("_", "a").isalnum()
        or not (derived[0].isalpha() or derived[0] == "_")
    ):
        raise _unsafe_test_database_url() from None
    if len(derived.encode("utf-8")) > 63:
        raise _unsafe_test_database_url() from None
    return derived


def pytest_configure(config):
    """Point each xdist worker at its own test database before settings load."""
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if not worker:
        return
    base = _base_test_database_url()
    if not base:
        return
    url = _validated_test_database_url(base)
    worker_name = _worker_database_name(url.database, worker)
    worker_url = url.set(database=worker_name)
    os.environ["TEST_DATABASE_URL"] = worker_url.render_as_string(hide_password=False)


def pytest_sessionstart(session):
    """Create one pristine database per xdist worker (controller process only)."""
    if os.environ.get("PYTEST_XDIST_WORKER"):
        return
    if getattr(session.config.option, "collectonly", False):
        return  # listing tests must not drop or create worker databases
    num = getattr(session.config.option, "numprocesses", None)
    if not num:
        return
    if num == "auto":
        num = os.cpu_count() or 1
    num = max(int(num), 1)
    base = _base_test_database_url()
    if not base:
        return
    url = _validated_test_database_url(base)
    worker_names = [_worker_database_name(url.database, f"gw{index}") for index in range(num)]
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            for name in worker_names:
                connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
                connection.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        admin.dispose()


@pytest.fixture(autouse=True)
def disable_real_model_keys(monkeypatch):
    """Keep test runs isolated from locally configured paid model credentials."""
    monkeypatch.setattr(settings, "openai_api_key", None)
    monkeypatch.setattr(settings, "typesafe_api_key", None)
    monkeypatch.setattr(settings, "firecrawl_api_key", None)


@pytest.fixture(autouse=True)
def block_external_httpx_transport(monkeypatch):
    """Prevent accidental external HTTP requests while allowing local test servers."""

    def is_loopback(host: str) -> bool:
        normalized = host.rstrip(".").lower()
        if normalized == "localhost":
            return True
        try:
            return ipaddress.ip_address(normalized).is_loopback
        except ValueError:
            return False

    original_sync = httpx.HTTPTransport.handle_request
    original_async = httpx.AsyncHTTPTransport.handle_async_request
    original_getaddrinfo = socket.getaddrinfo
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def guarded_sync(transport, request):
        if not is_loopback(request.url.host):
            pytest.fail(f"Test attempted external HTTP request to {request.url.host}")
        return original_sync(transport, request)

    async def guarded_async(transport, request):
        if not is_loopback(request.url.host):
            pytest.fail(f"Test attempted external HTTP request to {request.url.host}")
        return await original_async(transport, request)

    def guarded_getaddrinfo(host, *args, **kwargs):
        if host is not None and not is_loopback(str(host)):
            pytest.fail(f"Test attempted external DNS lookup for {host}")
        return original_getaddrinfo(host, *args, **kwargs)

    def guarded_connect(sock, address):
        if sock.family not in {socket.AF_INET, socket.AF_INET6}:
            return original_connect(sock, address)
        host = address[0] if isinstance(address, tuple) and address else address
        if not is_loopback(str(host)):
            raise OSError(f"Test network guard blocked TCP connection to {host}")
        return original_connect(sock, address)

    def guarded_connect_ex(sock, address):
        if sock.family not in {socket.AF_INET, socket.AF_INET6}:
            return original_connect_ex(sock, address)
        host = address[0] if isinstance(address, tuple) and address else address
        if not is_loopback(str(host)):
            raise OSError(f"Test network guard blocked TCP connection to {host}")
        return original_connect_ex(sock, address)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", guarded_sync)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", guarded_async)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
