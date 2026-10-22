"""Target checks for the offline retained-news reassessment CLI."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "reinterpret_news.py"
SPEC = importlib.util.spec_from_file_location("reinterpret_news_cli", SCRIPT)
assert SPEC and SPEC.loader
cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cli)


def test_apply_requires_expected_name_before_database_setup(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["reinterpret_news.py", "--apply"])
    monkeypatch.setattr(
        cli, "_database_session_factory", lambda *_: pytest.fail("must not connect")
    )
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2


def test_mismatched_database_name_rejected_before_engine(monkeypatch):
    import sqlalchemy

    from gridlens.settings import settings

    monkeypatch.setattr(settings, "database_url", "postgresql://localhost/app")
    monkeypatch.setattr(settings, "test_database_url", "postgresql://localhost/private_test")
    monkeypatch.setattr(sqlalchemy, "create_engine", lambda *_: pytest.fail("must not connect"))
    with pytest.raises(ValueError, match="does not match"):
        cli._database_session_factory("test", "wrong_test")
    with pytest.raises(ValueError, match="does not match"):
        cli._database_session_factory("application", "other")
    monkeypatch.setattr(settings, "test_database_url", "postgresql://localhost/app")
    with pytest.raises(ValueError):
        cli._database_session_factory("test", "app")


def test_default_dry_run_reads_json_without_database(monkeypatch, tmp_path):
    source = tmp_path / "input.json"
    output = tmp_path / "output.json"
    source.write_text(json.dumps([]), encoding="utf8")
    monkeypatch.setattr(
        sys, "argv", ["reinterpret_news.py", "--input", str(source), "--output", str(output)]
    )
    monkeypatch.setattr(
        cli, "_database_session_factory", lambda *_: pytest.fail("must not connect")
    )
    cli.main()
    assert json.loads(output.read_text(encoding="utf8"))["mode"] == "dry-run"
