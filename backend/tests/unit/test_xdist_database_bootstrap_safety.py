"""The xdist database bootstrap must validate its target before connecting."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.engine import make_url


def _load_conftest():
    path = Path(__file__).parents[1] / "conftest.py"
    spec = importlib.util.spec_from_file_location("gridlens_xdist_test_conftest", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


conftest = _load_conftest()


class _Connection:
    def __init__(self):
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement):
        self.statements.append(str(statement))


class _Engine:
    def __init__(self, url):
        self.url = url
        self.connection = _Connection()
        self.disposed = False

    def connect(self):
        return self.connection

    def dispose(self):
        self.disposed = True


def _session(*, collectonly=False, numprocesses=2):
    return SimpleNamespace(
        config=SimpleNamespace(
            option=SimpleNamespace(collectonly=collectonly, numprocesses=numprocesses)
        )
    )


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "::1"])
def test_loopback_hosts_provision_safely_derived_worker_databases(monkeypatch, host):
    formatted_host = f"[{host}]" if ":" in host else host
    base = f"postgresql+psycopg://tester:secret@{formatted_host}:5432/gridlens_test"
    monkeypatch.setenv("TEST_DATABASE_URL", base)
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    engines = []

    def fake_create_engine(url, **kwargs):
        engine = _Engine(url)
        engines.append((engine, kwargs))
        return engine

    monkeypatch.setattr(conftest, "create_engine", fake_create_engine)
    conftest.pytest_sessionstart(_session(numprocesses=2))

    assert len(engines) == 1
    engine, options = engines[0]
    assert engine.url.database == "postgres"
    assert engine.url.host == host
    assert options == {"isolation_level": "AUTOCOMMIT"}
    assert engine.disposed
    assert engine.connection.statements == [
        'DROP DATABASE IF EXISTS "gridlens_gw0_test" WITH (FORCE)',
        'CREATE DATABASE "gridlens_gw0_test"',
        'DROP DATABASE IF EXISTS "gridlens_gw1_test" WITH (FORCE)',
        'CREATE DATABASE "gridlens_gw1_test"',
    ]


@pytest.mark.parametrize(
    "base",
    [
        "postgresql+psycopg://tester:secret@192.0.2.12:5432/gridlens_test",
        "postgresql+psycopg://tester:secret@localhost:5432/gridlens",
        "postgresql+psycopg://tester:secret@localhost:5432/gridlens%22_test",
        "postgresql+psycopg://tester:secret@127.0.0.1:5432/gridlens_test?host=remote.example",
        "postgresql+psycopg://tester:secret@127.0.0.1:5432/gridlens_test?hostaddr=203.0.113.9",
        "postgresql+psycopg://tester:secret@127.0.0.1:5432/gridlens_test?dbname=retained",
        "postgresql+psycopg://tester:secret@127.0.0.1:5432/gridlens_test?service=production",
        "postgresql+psycopg://tester:secret@localhost:5432/" + ("x" * 60) + "_test",
        "sqlite:///gridlens_test",
        "not a valid URL secret",
    ],
)
def test_unsafe_base_never_constructs_an_admin_engine(monkeypatch, base):
    monkeypatch.setenv("TEST_DATABASE_URL", base)
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    create_engine_calls = []
    monkeypatch.setattr(
        conftest,
        "create_engine",
        lambda *args, **kwargs: create_engine_calls.append((args, kwargs)),
    )

    with pytest.raises(pytest.UsageError) as error:
        conftest.pytest_sessionstart(_session())

    assert create_engine_calls == []
    assert "secret" not in str(error.value)
    assert "tester" not in str(error.value)


def test_xdist_worker_derivation_validates_before_rewriting_environment(monkeypatch):
    monkeypatch.setenv(
        "TEST_DATABASE_URL", "postgresql+psycopg://tester:secret@[::1]:5432/gridlens_test"
    )
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw2")

    conftest.pytest_configure(SimpleNamespace())

    rewritten = make_url(os.environ["TEST_DATABASE_URL"])
    assert rewritten.database == "gridlens_gw2_test"
    assert rewritten.host == "::1"


@pytest.mark.parametrize(
    "variable,value",
    [
        ("PGHOSTADDR", "203.0.113.9"),
        ("PGSERVICE", "production"),
        ("PGSERVICEFILE", "C:/private/pg_service.conf"),
    ],
)
def test_libpq_environment_routing_overrides_are_rejected_before_connect(
    monkeypatch, variable, value
):
    monkeypatch.setenv(
        "TEST_DATABASE_URL", "postgresql+psycopg://tester:secret@127.0.0.1:5432/gridlens_test"
    )
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    monkeypatch.setenv(variable, value)
    create_engine_calls = []
    monkeypatch.setattr(
        conftest,
        "create_engine",
        lambda *args, **kwargs: create_engine_calls.append((args, kwargs)),
    )

    with pytest.raises(pytest.UsageError):
        conftest.pytest_sessionstart(_session())

    assert create_engine_calls == []


@pytest.mark.parametrize(
    "base",
    [
        "postgresql+psycopg://tester:secret@203.0.113.9:5432/gridlens_test",
        "postgresql+psycopg://tester:secret@localhost:5432/gridlens",
        "postgresql+psycopg://tester:secret@localhost:5432/gridlens%22_test",
        "postgresql+psycopg://tester:secret@localhost:5432/" + ("x" * 60) + "_test",
    ],
)
def test_xdist_worker_derivation_rejects_unsafe_base_without_leaking_credentials(monkeypatch, base):
    monkeypatch.setenv("TEST_DATABASE_URL", base)
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw0")

    with pytest.raises(pytest.UsageError) as error:
        conftest.pytest_configure(SimpleNamespace())

    assert "secret" not in str(error.value)
    assert "tester" not in str(error.value)


def test_collect_only_and_unconfigured_runs_do_not_connect(monkeypatch):
    create_engine_calls = []
    monkeypatch.setenv(
        "TEST_DATABASE_URL", "postgresql+psycopg://tester:secret@203.0.113.9:5432/not_test"
    )
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    monkeypatch.setattr(
        conftest,
        "create_engine",
        lambda *args, **kwargs: create_engine_calls.append((args, kwargs)),
    )
    conftest.pytest_sessionstart(_session(collectonly=True))

    monkeypatch.delenv("TEST_DATABASE_URL")
    conftest.pytest_sessionstart(_session())

    assert create_engine_calls == []
