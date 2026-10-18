import json
import os
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from gridlens.intelligence import signal_adjudication as jev

STATE = dict.fromkeys(
    [
        "title",
        "abstract",
        "url",
        "published_at",
        "source_id",
        "source_family",
        "publisher",
        "event_date",
        "event_date_label",
        "project_name",
        "location",
        "asset_type",
        "lifecycle_state",
    ],
    "Diagnostic only",
)


def _process_environment(**overrides):
    # Windows executable/plugin discovery needs its OS paths even for a
    # deliberately isolated subprocess environment. Never inherit provider keys.
    names = ("PATH", "SystemRoot", "ComSpec", "USERPROFILE", "APPDATA", "LOCALAPPDATA")
    return {**{key: os.environ[key] for key in names if key in os.environ}, **overrides}


def _shell_command(path, *args):
    if os.name != "nt":
        return [str(path), *args]
    git = shutil.which("git")
    bash = Path(git).resolve().parents[1] / "bin" / "bash.exe" if git else None
    if bash is None or not bash.is_file():
        pytest.skip("Git Bash is required to exercise Linux deployment scripts on Windows")
    return [str(bash), str(path), *args]


def _shell_environment(tmp_path, **overrides):
    if os.name == "nt":
        return _process_environment(PATH=f"{tmp_path}{os.pathsep}{os.environ['PATH']}", **overrides)
    return {"PATH": f"{tmp_path}:/usr/bin:/bin", **overrides}


@pytest.mark.parametrize(
    ("code", "status", "attempts"),
    [
        (401, "authentication_failed", 1),
        (403, "authentication_failed", 1),
        (429, "provider_unavailable", 3),
        (503, "provider_unavailable", 3),
        (400, "request_rejected", 1),
    ],
)
def test_provider_failure_is_safe_classified_and_bounded(monkeypatch, code, status, attempts):
    calls = []

    def post(*args, **kwargs):
        calls.append(1)
        return httpx.Response(
            code,
            text="secret-must-not-leak",
            request=httpx.Request(
                "POST",
                "https://api.typesafe.ai/v1/systemone",
                headers={"Authorization": "Bearer secret-must-not-leak"},
            ),
        )

    monkeypatch.setattr(jev.httpx, "post", post)
    monkeypatch.setattr(jev.time, "sleep", lambda _: None)
    with pytest.raises(RuntimeError) as raised:
        jev._jev_call(STATE, "secret-must-not-leak")
    assert getattr(raised.value, "status", None) == status
    assert "secret-must-not-leak" not in str(raised.value)
    assert raised.value.__cause__ is None
    assert len(calls) == attempts


def test_invalid_json_is_distinct_and_not_retried(monkeypatch):
    calls = []

    def post(*args, **kwargs):
        calls.append(1)
        return httpx.Response(
            200, text="not-json", request=httpx.Request("POST", "https://api.typesafe.ai")
        )

    monkeypatch.setattr(jev.httpx, "post", post)
    with pytest.raises(RuntimeError) as raised:
        jev._jev_call(STATE, "synthetic-key")
    assert getattr(raised.value, "status", None) == "malformed_response"
    assert len(calls) == 1


def test_compose_forwards_injected_keys_without_a_secret_file(tmp_path):
    if not shutil.which("docker"):
        pytest.skip("Docker Compose unavailable")
    root = Path(__file__).resolve().parents[3]
    config = tmp_path / ".env.prod"
    config.write_text((root / "deploy/digitalocean/env.prod.example").read_text())
    compose = tmp_path / "deploy/digitalocean/compose.prod.yaml"
    compose.parent.mkdir(parents=True)
    compose.write_text((root / "deploy/digitalocean/compose.prod.yaml").read_text())
    env = _process_environment(
        TYPESAFE_API_KEY="injected-sentinel",
        OPENAI_API_KEY="injected-openai-sentinel",
        CLOUDFLARE_TUNNEL_TOKEN="synthetic-tunnel",
    )
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(config),
            "-f",
            str(compose),
            "config",
            "--no-env-resolution",
            "--format",
            "json",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    services = json.loads(result.stdout)["services"]
    for name in ["api", "worker"]:
        assert services[name].get("environment", {}).get("TYPESAFE_API_KEY") == "injected-sentinel"
        assert (
            services[name].get("environment", {}).get("OPENAI_API_KEY")
            == "injected-openai-sentinel"
        )
    assert "TYPESAFE_API_KEY" not in services["web"].get("environment", {})
    assert "OPENAI_API_KEY" not in services["web"].get("environment", {})


@pytest.mark.parametrize("key", [None, "", "   "])
def test_health_without_credentials_never_calls_provider(monkeypatch, key):
    from pydantic import SecretStr

    from gridlens.intelligence.jev_health import diagnostic
    from gridlens.settings import settings

    monkeypatch.setattr(settings, "typesafe_api_key", SecretStr(key) if key is not None else None)
    monkeypatch.setattr(jev.httpx, "post", lambda *a, **k: pytest.fail("Unexpected provider call"))
    result = diagnostic(probe=True)
    assert result["status"] == "missing_credentials"
    assert result["provider_requests"] == 0


@pytest.mark.parametrize(
    "outcome", ["available", "authentication_failed", "provider_unavailable", "malformed_response"]
)
def test_health_probe_is_authenticated_single_request_and_redacted(monkeypatch, outcome):
    from pydantic import SecretStr

    from gridlens.intelligence.jev_health import diagnostic
    from gridlens.settings import settings

    monkeypatch.setattr(settings, "typesafe_api_key", SecretStr("synthetic-probe-key"))
    calls = []

    def post(url, **kwargs):
        calls.append(1)
        assert kwargs["headers"]["Authorization"] == "Bearer synthetic-probe-key"
        assert kwargs["timeout"] == 12.0
        if outcome == "provider_unavailable":
            raise httpx.ReadTimeout("synthetic-probe-key")
        payload = {
            "model": jev.MODEL,
            "answers": {
                name: {"type": "noul", "noul": 0.5}
                for name in [
                    "physical_project_event",
                    "meaningful_new_activity",
                    "commercial_relevance",
                    "temporary_power_relevance",
                    "routine_maintenance",
                    "transient_event",
                ]
            },
        }
        if outcome == "malformed_response":
            payload["answers"] = {"unexpected": "synthetic-probe-key"}
        return httpx.Response(
            401 if outcome == "authentication_failed" else 200,
            json=payload,
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(jev.httpx, "post", post)
    assert diagnostic()["status"] == "not_checked"
    assert not calls
    result = diagnostic(probe=True)
    assert result["status"] == outcome
    assert result["provider_requests"] == len(calls) == 1
    assert "synthetic-probe-key" not in json.dumps(result)


def test_infisical_wrapper_uses_explicit_existing_binding(tmp_path):
    root = Path(__file__).resolve().parents[3]
    stub = tmp_path / "infisical"
    stub.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
    stub.chmod(0o700)
    env = _shell_environment(
        tmp_path,
        INFISICAL_PROJECT_ID="existing-project",
        INFISICAL_ENVIRONMENT="existing-environment",
        INFISICAL_SECRET_PATH="/existing-folder",
    )
    command = _shell_command(
        root / "deploy/digitalocean/with-infisical.sh",
        "worker-command",
        "arg with spaces",
    )
    result = subprocess.run(command, env=env, text=True, capture_output=True, check=True)
    assert result.stdout.splitlines() == [
        "run",
        "--projectId=existing-project",
        "--env=existing-environment",
        "--path=/existing-folder",
        "--",
        "worker-command",
        "arg with spaces",
    ]
    del env["INFISICAL_ENVIRONMENT"]
    result = subprocess.run(command, env=env, text=True, capture_output=True)
    assert result.returncode != 0
    assert not result.stdout


def test_module_cli_preserves_auth_failure_classification(monkeypatch, capsys):
    import runpy
    import sys

    from pydantic import SecretStr

    from gridlens.settings import settings

    monkeypatch.setattr(settings, "typesafe_api_key", SecretStr("synthetic-cli-key"))
    monkeypatch.setattr(sys, "argv", ["jev_health", "--probe"])

    def post(url, **kwargs):
        return httpx.Response(401, request=httpx.Request("POST", url))

    monkeypatch.setattr(jev.httpx, "post", post)
    monkeypatch.delitem(sys.modules, "gridlens.intelligence.jev_health", raising=False)
    with pytest.raises(SystemExit) as raised:
        runpy.run_module("gridlens.intelligence.jev_health", run_name="__main__")
    assert raised.value.code == 1
    output = capsys.readouterr().out
    assert json.loads(output)["status"] == "authentication_failed"
    assert "synthetic-cli-key" not in output


@pytest.mark.parametrize("job", ["collect", "alert"])
def test_scheduled_commands_preserve_injected_environment(tmp_path, job):
    root = Path(__file__).resolve().parents[3]
    script = tmp_path / "gridlens-run.sh"
    script.write_text(
        (root / "deploy/digitalocean/gridlens-run.sh")
        .read_text()
        .replace("cd /opt/gridlens", 'cd "$(dirname "$0")"')
    )
    script.chmod(0o700)
    (tmp_path / ".env.prod").write_text("TYPESAFE_API_KEY=file-sentinel\n")
    docker = tmp_path / "docker"
    docker.write_text('#!/bin/sh\nprintf "%s" "$TYPESAFE_API_KEY"\n')
    docker.chmod(0o700)
    result = subprocess.run(
        _shell_command(script, job),
        env=_shell_environment(tmp_path, TYPESAFE_API_KEY="injected-sentinel"),
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout == "injected-sentinel"
