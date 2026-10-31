from __future__ import annotations

import ast
import hashlib
import importlib.util
import os
import runpy
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[3] / "scripts" / "stage_release_wrapper.py"
SPEC = importlib.util.spec_from_file_location("stage_release_wrapper", SCRIPT)
assert SPEC and SPEC.loader
stage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stage)


def _source() -> str:
    return """import json
import os
from pathlib import Path
import shlex
import stat
import sys
ROOT = Path("/etc/gridlens")
PROJECT = "project-id"
def private_json(path):
    return json.loads(path.read_text())
def main():
    required = [ROOT / "scope", ROOT / "credentials", ROOT / "runtime.env"]
    if not all(path.is_file() for path in required):
        raise SystemExit("missing")
    try:
        token = private_json(required[1])["token"]
        runtime = {"DATABASE_URL": "configured", "OPENAI_API_KEY": "configured"}
    except (OSError, ValueError, KeyError):
        raise SystemExit("invalid") from None
    if sys.argv[1:] == ["--validate-only"]:
        print("present")
        return
    if sys.argv[1:]:
        raise SystemExit("arguments not allowed")
    env = {**os.environ, **runtime, "INFISICAL_TOKEN": token, "COMPOSE_PROFILES": "saved-browse"}
    command = [
        "infisical", "--silent", "--telemetry=false", "run", "--projectId=" + PROJECT,
        "--env=dev", "--path=/", "--include-imports=false", "--expand=false",
        "--secret-overriding=false", "--", "python3", str(ROOT / "with-env.py"), "docker",
        "compose", "-f", str(ROOT / "compose.app.yaml"), "--env-file", str(ROOT / "runtime.env"),
        "up", "-d", "--no-build",
    ]
    os.execvpe("infisical", command, env)
if __name__ == "__main__":
    main()
"""


def _authorize(monkeypatch: pytest.MonkeyPatch, source: str) -> None:
    tree = ast.parse(source)
    main = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    command = next(
        node
        for node in main.body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "command"
    )
    monkeypatch.setattr(
        stage, "EXPECTED_WRAPPER_SHA256", hashlib.sha256(source.encode()).hexdigest()
    )
    monkeypatch.setattr(stage, "EXPECTED_WRAPPER_AST_SHA256", stage._ast_digest(tree))
    monkeypatch.setattr(stage, "EXPECTED_COMMAND_AST_SHA256", stage._ast_digest(command.value))


def test_stages_only_exact_input_and_preserves_it(tmp_path, monkeypatch):
    source = _source()
    _authorize(monkeypatch, source)
    current = tmp_path / "current.py"
    staged = tmp_path / "staged.py"
    current.write_bytes(source.encode())

    stage.stage_release_wrapper(current, staged)

    assert current.read_text() == source
    rendered = staged.read_text()
    assert '"stop-app"' in rendered
    assert '"migrate"' in rendered
    assert '"rebuild-browse"' in rendered
    assert '"start-canary"' in rendered
    assert '"start-workers"' in rendered
    assert '"stage-browse"' in rendered
    assert "SECRET_TOKEN" not in rendered


def test_rejects_changed_bytes_and_existing_output(tmp_path, monkeypatch):
    source = _source()
    _authorize(monkeypatch, source)
    current = tmp_path / "current.py"
    current.write_bytes((source + "# changed\n").encode())
    with pytest.raises(ValueError, match="byte identity"):
        stage.stage_release_wrapper(current, tmp_path / "staged.py")
    current.write_bytes(source.encode())
    output = tmp_path / "existing.py"
    output.write_text("preserve me")
    with pytest.raises(FileExistsError):
        stage.stage_release_wrapper(current, output)
    assert output.read_text() == "preserve me"


def test_rejects_unobserved_all_service_suffix(tmp_path, monkeypatch):
    source = _source().replace('"--no-build",', '"--build",')
    _authorize(monkeypatch, source)
    current = tmp_path / "current.py"
    current.write_bytes(source.encode())
    with pytest.raises(ValueError, match="suffix"):
        stage.stage_release_wrapper(current, tmp_path / "staged.py")


def test_generated_wrapper_refuses_default_and_arbitrary_commands(tmp_path, monkeypatch):
    source = _source()
    _authorize(monkeypatch, source)
    current = tmp_path / "current.py"
    staged = tmp_path / "staged.py"
    current.write_bytes(source.encode())
    stage.stage_release_wrapper(current, staged)
    rendered = staged.read_text()
    ast.parse(rendered)
    assert "if not sys.argv[1:]" in rendered
    assert "operation in static_operations and not arguments" in rendered
    assert "generation != arguments[0]" in rendered
    assert "command = " in rendered and " + suffix" in rendered
    assert '"up", "-d", "--no-build", "--no-deps", "api", "web"' in rendered


def test_rejects_crlf_bytes_even_when_ast_is_identical(tmp_path, monkeypatch):
    source = _source()
    _authorize(monkeypatch, source)
    current = tmp_path / "current.py"
    current.write_bytes(source.replace("\n", "\r\n").encode())
    with pytest.raises(ValueError, match="byte identity"):
        stage.stage_release_wrapper(current, tmp_path / "staged.py")


class _Executed(Exception):
    pass


@pytest.mark.parametrize(
    ("arguments", "suffix"),
    [
        (["stop-app"], ["stop", "api", "worker", "browse", "web"]),
        (["migrate"], ["run", "--rm", "--no-deps", "migrate"]),
        (["start-canary"], ["up", "-d", "--no-build", "--no-deps", "api", "web"]),
        (["start-workers"], ["up", "-d", "--no-build", "--no-deps", "worker", "browse"]),
        *[
            (
                [operation, *(["123e4567-e89b-12d3-a456-426614174000"] if needs_id else [])],
                [
                    "run",
                    "--rm",
                    "--no-deps",
                    "browse",
                    "uv",
                    "run",
                    "python",
                    "-m",
                    "gridlens.jobs.browse",
                    action,
                    *(["--generation", "123e4567-e89b-12d3-a456-426614174000"] if needs_id else []),
                ],
            )
            for operation, action, needs_id in [
                ("browse-status", "status", False),
                ("stage-browse", "stage-recovery", False),
                ("inspect-browse", "inspect-recovery", True),
                ("publish-browse", "publish-recovery", True),
            ]
        ],
    ],
)
def test_generated_wrapper_executes_only_fixed_suffixes(tmp_path, monkeypatch, arguments, suffix):
    source = _source().replace("/etc/gridlens", tmp_path.as_posix())
    _authorize(monkeypatch, source)
    current, staged = tmp_path / "current.py", tmp_path / "staged.py"
    current.write_bytes(source.encode())
    stage.stage_release_wrapper(current, staged)
    for name in ("scope", "credentials", "runtime.env"):
        (tmp_path / name).write_text('{"token": "not-a-real-token-value-123456"}')
    captured = {}

    def fake_execvpe(file, command, env):
        captured.update(file=file, command=command, env=env)
        raise _Executed

    monkeypatch.setattr(os, "getuid", lambda: 0, raising=False)
    monkeypatch.setattr(os, "execvpe", fake_execvpe)
    monkeypatch.setattr(sys, "argv", [str(staged), *arguments])
    monkeypatch.chdir(tmp_path)
    with pytest.raises(_Executed):
        runpy.run_path(str(staged), run_name="__main__")
    assert captured["file"] == "infisical"
    assert captured["command"][-len(suffix) :] == suffix
    assert captured["command"][:4] == ["infisical", "--silent", "--telemetry=false", "run"]

    # Execute the generated action through the real CLI parser/dispatcher. Only
    # the database boundary is replaced; Infisical/Docker must never execute.
    if "gridlens.jobs.browse" in suffix and suffix[-1] != "status":
        from uuid import UUID

        from gridlens.jobs import browse

        observed = []
        factory = object()
        monkeypatch.setattr(browse, "SessionLocal", factory)

        def stage_recovery(actual_factory):
            assert actual_factory is factory
            observed.append(("stage-recovery", None))
            return {"status": "staged"}

        def inspect_recovery(actual_factory, generation):
            assert actual_factory is factory
            observed.append(("inspect-recovery", generation))
            return {"status": "ready"}

        def publish_recovery(actual_factory, generation):
            assert actual_factory is factory
            observed.append(("publish-recovery", generation))
            return {"status": "published"}

        monkeypatch.setattr(browse, "stage_recovery", stage_recovery)
        monkeypatch.setattr(browse, "inspect_recovery_stage", inspect_recovery)
        monkeypatch.setattr(browse, "publish_recovery_stage", publish_recovery)
        action_index = suffix.index("gridlens.jobs.browse") + 1
        monkeypatch.setattr(sys, "argv", ["browse", *suffix[action_index:]])
        assert browse.main() == 0
        expected = {
            "stage-browse": ("stage-recovery", None),
            "inspect-browse": ("inspect-recovery", UUID("123e4567-e89b-12d3-a456-426614174000")),
            "publish-browse": ("publish-recovery", UUID("123e4567-e89b-12d3-a456-426614174000")),
        }
        assert observed == [expected[arguments[0]]]


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["unknown"],
        ["migrate", "extra"],
        ["rollback-browse", "123e4567-e89b-12d3-a456-426614174000"],
        ["inspect-browse"],
        ["publish-browse", "not-a-uuid"],
        ["publish-browse", "123E4567-E89B-12D3-A456-426614174000"],
        ["publish-browse", "123e4567-e89b-12d3-a456-426614174000", "--force"],
        ["stage-browse", "--generation", "123e4567-e89b-12d3-a456-426614174000"],
        ["browse-status", "extra"],
    ],
)
def test_generated_wrapper_rejects_default_and_arbitrary_commands(tmp_path, monkeypatch, arguments):
    source = _source().replace("/etc/gridlens", tmp_path.as_posix())
    _authorize(monkeypatch, source)
    current, staged = tmp_path / "current.py", tmp_path / "staged.py"
    current.write_bytes(source.encode())
    stage.stage_release_wrapper(current, staged)
    for name in ("scope", "credentials", "runtime.env"):
        (tmp_path / name).write_text('{"token": "not-a-real-token-value-123456"}')
    monkeypatch.setattr(os, "getuid", lambda: 0, raising=False)
    monkeypatch.setattr(os, "execvpe", lambda *_: pytest.fail("must not execute"))
    monkeypatch.setattr(sys, "argv", [str(staged), *arguments])
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        runpy.run_path(str(staged), run_name="__main__")
