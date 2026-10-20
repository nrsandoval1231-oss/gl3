from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_backfill_module():
    script = Path(__file__).resolve().parents[3] / "scripts" / "backfill_retained_buying_chain.py"
    spec = importlib.util.spec_from_file_location("backfill_retained_buying_chain", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_backfill_application_target_requires_exact_database_name_before_connect(monkeypatch):
    from gridlens.settings import settings

    monkeypatch.setattr(
        settings,
        "database_url",
        "postgresql+psycopg://user:pass@127.0.0.1:55520/gridlens_app_test",
    )
    monkeypatch.setattr(
        settings,
        "test_database_url",
        "postgresql+psycopg://user:pass@127.0.0.1:55520/gridlens_test",
    )
    module = _load_backfill_module()
    with pytest.raises(ValueError, match="does not match"):
        module._database_session_factory("application", "wrong_name")


def test_backfill_apply_requires_expected_name_at_argument_boundary(monkeypatch):
    module = _load_backfill_module()
    monkeypatch.setattr(module.sys, "argv", ["backfill_retained_buying_chain.py", "--apply"])
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 2
