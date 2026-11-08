"""Deterministic URL safety checks; no database connection is opened."""

import importlib.util
import os
from pathlib import Path

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://user:pass@127.0.0.1:54973/ui_pursuits_real_test")
os.environ.setdefault("TEST_DATABASE_URL", "postgresql+psycopg://user:pass@127.0.0.1:54974/backend_test")
os.environ.setdefault("APP_PASSWORD_HASH", "test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-seed-test")

SEED = Path(__file__).with_name("seed.py")
spec = importlib.util.spec_from_file_location("pursuits_seed", SEED)
seed = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(seed)
rollup_path = SEED.parents[1] / "rollup-scale" / "seed.py"
rollup_spec = importlib.util.spec_from_file_location("rollup_seed", rollup_path)
rollup_seed = importlib.util.module_from_spec(rollup_spec)
assert rollup_spec.loader is not None
rollup_spec.loader.exec_module(rollup_seed)


@pytest.mark.parametrize("override", [
    "host=remote.example", "hostaddr=192.0.2.1", "port=5432",
    "dbname=production", "service=external", "options=-csearch_path=public",
    "user=other", "host%61ddr=192.0.2.1", "hostaddr=127.0.0.1&hostaddr=192.0.2.1",
])
def test_rejects_effective_connection_overrides_before_connecting(override):
    url = f"postgresql+psycopg://user:pass@127.0.0.1:54973/ui_pursuits_real_test?{override}"
    with pytest.raises(SystemExit, match="connection-routing query overrides"):
        seed.checked_database_url(url)


def test_accepts_pinned_disposable_database_url():
    url = "postgresql+psycopg://user:pass@localhost:54973/ui_pursuits_real_test?sslmode=disable"
    assert seed.checked_database_url(url) == url


@pytest.mark.parametrize("checker, database", [
    (seed.checked_database_url, "ui_pursuits_real_test"),
    (seed.checked_database_url, "ui_pursuits_real_slice1n_test"),
    (rollup_seed.checked_database_url, "gl3_rollup_scale_test"),
])
@pytest.mark.parametrize("override", ["host=remote.example", "port=5432", "dbname=elsewhere", "host%61ddr=192.0.2.1"])
def test_both_seeders_reject_query_routing_overrides(checker, database, override):
    url = f"postgresql+psycopg://user:pass@127.0.0.1:54973/{database}?{override}"
    with pytest.raises(SystemExit, match="connection-routing query overrides"):
        checker(url)


@pytest.mark.parametrize("checker, database", [
    (seed.checked_database_url, "ui_pursuits_real_test"),
    (rollup_seed.checked_database_url, "gl3_rollup_scale_test"),
])
@pytest.mark.parametrize("variable", ["PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS"])
def test_both_seeders_reject_inherited_libpq_routing_environment(checker, database, variable, monkeypatch):
    monkeypatch.setenv(variable, "192.0.2.1" if variable == "PGHOSTADDR" else "remote-service")
    url = f"postgresql+psycopg://user:pass@127.0.0.1:54973/{database}"
    with pytest.raises(SystemExit, match="inherited libpq"):
        checker(url)


@pytest.mark.parametrize("checker, database", [
    (seed.checked_database_url, "ui_pursuits_real_test"),
    (rollup_seed.checked_database_url, "gl3_rollup_scale_test"),
])
def test_both_seeders_reject_fragments_and_missing_ports(checker, database):
    prefix = f"postgresql+psycopg://user:pass@127.0.0.1:54973/{database}"
    with pytest.raises(SystemExit, match="fragments"):
        checker(prefix + "#remote-target")
    with pytest.raises(SystemExit, match="explicit valid port"):
        checker(f"postgresql+psycopg://user:pass@127.0.0.1/{database}")
