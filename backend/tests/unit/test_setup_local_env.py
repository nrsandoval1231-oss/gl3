import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "setup_local.py"
_SPEC = importlib.util.spec_from_file_location("setup_local", _SCRIPT)
assert _SPEC and _SPEC.loader
setup_local = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(setup_local)


def test_connection_env_skips_blanks_comments_and_bom():
    text = "\ufeff# local cluster\n\nDATABASE_URL=postgresql+psycopg://db/gridlens\n  # note\nTEST_DATABASE_URL=postgresql+psycopg://db/gridlens_test\n"
    assert setup_local.parse_connection_env(text) == {
        "DATABASE_URL": "postgresql+psycopg://db/gridlens",
        "TEST_DATABASE_URL": "postgresql+psycopg://db/gridlens_test",
    }


def test_connection_env_rejects_a_line_without_equals():
    with pytest.raises(ValueError, match="missing '='"):
        setup_local.parse_connection_env("DATABASE_URL\n")
