"""Pure historical entry guards; no Docker, files, or restore execution."""

import argparse
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "rehearse_release.py"
SPEC = importlib.util.spec_from_file_location("legacy_release_rehearsal", SCRIPT)
assert SPEC and SPEC.loader
legacy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(legacy)


def cli_args():
    return [
        "--dump",
        "/nonexistent/private.dump",
        "--dump-sha256",
        "0" * 64,
        "--api-image",
        "candidate-api",
        "--web-image",
        "candidate-web",
        "--revision",
        "a" * 40,
        "--prior-api-image",
        "prior-api",
        "--prior-web-image",
        "prior-web",
        "--test-env",
        "/nonexistent/private.env",
        "--output",
        "/nonexistent/receipts",
    ]


@pytest.mark.parametrize("acknowledgement", [None, False, "true", 1])
def test_default_entry_refuses_before_file_or_subprocess_access(monkeypatch, acknowledgement):
    def forbidden(*args, **kwargs):
        pytest.fail("historical guard must precede filesystem/subprocess/resource access")

    monkeypatch.setattr(Path, "is_symlink", forbidden)
    monkeypatch.setattr(Path, "resolve", forbidden)
    monkeypatch.setattr(legacy.subprocess, "run", forbidden)
    monkeypatch.setattr(legacy, "private_directory", forbidden)
    args = argparse.Namespace(historical_0041_only=acknowledgement)
    with pytest.raises(legacy.RehearsalBlocked, match="historical-0041-only.*recovery-release.md"):
        legacy.rehearsal(args)


def test_cli_default_refuses_before_dispatch_and_reports_current_guide(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("unacknowledged CLI must not dispatch rehearsal")

    monkeypatch.setattr(legacy, "rehearsal", forbidden)
    monkeypatch.setattr("sys.argv", [str(SCRIPT), *cli_args()])
    assert legacy.main() == 2
    assert "docs/operations/recovery-release.md" in capsys.readouterr().err


def test_explicit_historical_flag_parses_without_weakening_schema_guards():
    args = legacy.parser().parse_args([*cli_args(), "--historical-0041-only"])
    assert args.historical_0041_only is True
    assert legacy.EXPECTED_SCHEMA == legacy.TARGET_SCHEMA == "0041_evidence_packages"
    current = {"schema": "0049_scoped_identity_browse", "tables": {}}
    assert "unexpected_schema_transition" in legacy.compare_snapshots(current, current)


def test_explicit_acknowledgement_still_enters_original_input_validation(monkeypatch):
    args = legacy.parser().parse_args([*cli_args(), "--historical-0041-only"])
    monkeypatch.setattr(Path, "is_symlink", lambda self: True)
    with pytest.raises(legacy.RehearsalBlocked, match="input_files_must_not_be_symlinks"):
        legacy.rehearsal(args)
