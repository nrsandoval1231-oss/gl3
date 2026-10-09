"""Safety checks for the retained-lifecycle replay command."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "replay_lifecycle_history.py"
SPEC = importlib.util.spec_from_file_location("replay_lifecycle_history", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
replay_cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(replay_cli)


def test_replay_preserves_application_database_selector_without_connecting():
    application_url = "postgresql+psycopg://local@127.0.0.1:55437/gridlens"
    assert (
        replay_cli.select_database_url(
            None, True, "postgresql://localhost/test_test", application_url
        )
        == application_url
    )


def test_replay_rejects_conflicting_database_selectors():
    with pytest.raises(SystemExit, match="Choose only one"):
        replay_cli.select_database_url(
            "postgresql://localhost/explicit_test",
            True,
            "postgresql://localhost/default_test",
            "postgresql://localhost/application",
        )


def test_replay_accepts_distinct_test_database_endpoint():
    replay_cli.validate_test_database_url(
        "postgresql+psycopg://local@127.0.0.1:55437/gl3audit_lifecycle_replay_test",
        "postgresql+psycopg://local@127.0.0.1:55437/gl3audit_app",
    )


def test_replay_requires_all_current_repository_migration_heads(monkeypatch, tmp_path):
    heads = replay_cli.repository_migration_heads()
    monkeypatch.chdir(tmp_path)
    assert replay_cli.repository_migration_heads() == heads
    assert heads

    with pytest.raises(SystemExit, match="does not run migrations"):
        replay_cli.require_repository_heads(["0006_lifecycle_identity_versions"], heads)

    with pytest.raises(SystemExit, match="repository Alembic head"):
        replay_cli.require_repository_heads([], heads)

    replay_cli.require_repository_heads(sorted(heads), heads)


def test_replay_refuses_same_endpoint_even_if_url_credentials_differ():
    with pytest.raises(SystemExit, match="application database"):
        replay_cli.validate_test_database_url(
            "postgresql+psycopg://different-user@localhost:55437/gridlens_test",
            "postgresql+psycopg://local@localhost:55437/gridlens_test",
        )
