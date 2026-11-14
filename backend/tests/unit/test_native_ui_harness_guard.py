from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_GUARD_PATH = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "validation"
    / "customer-intelligence-followup-20261113"
    / "ui"
    / "db_guard.py"
)
_SPEC = importlib.util.spec_from_file_location("native_ui_db_guard", _GUARD_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_GUARD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_GUARD)

TEST = "postgresql+psycopg://audit:disposable@127.0.0.1:50833/gl3_ui_followup_base_test"
APP = "postgresql+psycopg://audit:disposable@127.0.0.1:50833/gl3_ui_followup_app"


def test_accepts_distinct_loopback_databases_without_connecting():
    url = _GUARD.validate_database_urls(TEST, APP, {})
    target = _GUARD.validate_target_database(url, APP, "gl3_ui_followup_after_ab12cd34_test")
    assert target.database == "gl3_ui_followup_after_ab12cd34_test"
    assert url.database == "gl3_ui_followup_base_test"


def test_rejects_database_url_query_routing_overrides():
    with pytest.raises(ValueError, match="query routing"):
        _GUARD.validate_database_urls(TEST + "?host=203.0.113.20", APP, {})


@pytest.mark.parametrize("name", ["PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE"])
def test_rejects_libpq_environment_routing_overrides(name: str):
    for value in ("redirect", ""):
        with pytest.raises(ValueError, match="environment overrides"):
            _GUARD.validate_database_urls(TEST, APP, {name: value})


@pytest.mark.parametrize(
    "unsafe",
    [
        TEST.replace("127.0.0.1", "db.example.invalid"),
        TEST.replace("postgresql+psycopg", "postgresql"),
    ],
)
def test_rejects_nonloopback_hosts_and_other_drivers(unsafe: str):
    with pytest.raises(ValueError):
        _GUARD.validate_database_urls(unsafe, APP, {})


def test_rejects_application_database_reuse_and_unsafe_generated_names():
    same = TEST.replace("gl3_ui_followup_base_test", "gl3_ui_followup_app")
    with pytest.raises(ValueError, match="distinct"):
        _GUARD.validate_database_urls(same, APP, {})
    base = _GUARD.validate_database_urls(TEST, APP, {})
    for name in ("gl3_ui_followup_app", "unsafe;drop_database_test"):
        with pytest.raises(ValueError):
            _GUARD.validate_target_database(base, APP, name)
