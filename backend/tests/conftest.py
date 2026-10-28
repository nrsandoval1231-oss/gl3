import ipaddress
import os
import socket

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from gridlens.settings import settings


def pytest_configure(config):
    """Point each xdist worker at its own test database before settings load."""
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if not worker:
        return
    base = os.environ.get("TEST_DATABASE_URL", "")
    if not base:
        return
    url = make_url(base)
    if not url.database:
        return
    stem = url.database[: -len("_test")] if url.database.endswith("_test") else url.database
    worker_url = url.set(database=f"{stem}_{worker}_test")
    os.environ["TEST_DATABASE_URL"] = worker_url.render_as_string(hide_password=False)


def pytest_sessionstart(session):
    """Create one pristine database per xdist worker (controller process only)."""
    if os.environ.get("PYTEST_XDIST_WORKER"):
        return
    num = getattr(session.config.option, "numprocesses", None)
    if not num:
        return
    if num == "auto":
        num = os.cpu_count() or 1
    num = max(int(num), 1)
    base = os.environ.get("TEST_DATABASE_URL", "")
    if not base:
        return
    url = make_url(base)
    if not url.database:
        return
    stem = url.database[: -len("_test")] if url.database.endswith("_test") else url.database
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        for index in range(num):
            name = f"{stem}_gw{index}_test"
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            connection.execute(text(f'CREATE DATABASE "{name}"'))
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


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Temporary flake forensics: dump browse state when the drift-fence test fails."""
    outcome = yield
    report = outcome.get_result()
    if (
        call.when == "call"
        and report.failed
        and "test_customer_search_and_generation_drift_fence" in item.nodeid
    ):
        import sys

        url = os.environ.get("TEST_DATABASE_URL", "")
        if not url:
            return
        engine = create_engine(url)
        queries = [
            "SELECT count(*) FROM browse_rows",
            "SELECT count(*) FROM browse_rows WHERE strpos(search_text, 'synthetic 7') > 0",
            "SELECT generation_id, count(*) FROM browse_rows GROUP BY 1",
            "SELECT id, generation_id, prepared_generation_id FROM browse_state",
            "SELECT id, row_count, valid_from, valid_until"
            " FROM browse_generations ORDER BY built_at",
        ]
        with engine.connect() as connection:
            for query in queries:
                try:
                    rows = connection.execute(text(query)).all()
                    print(f"\nDIAGNOSTIC {query} -> {rows}", file=sys.stderr)
                except Exception as error:  # noqa: BLE001
                    print(f"\nDIAGNOSTIC {query} ERROR {error}", file=sys.stderr)
        engine.dispose()
