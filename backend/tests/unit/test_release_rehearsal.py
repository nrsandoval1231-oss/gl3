from __future__ import annotations

import hashlib
import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "rehearse_release.py"
SPEC = importlib.util.spec_from_file_location("release_rehearsal", SCRIPT)
assert SPEC and SPEC.loader
rehearsal = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rehearsal)


def test_source_dump_digest_and_existing_output_fail_closed(tmp_path: Path):
    dump = tmp_path / "authorized.dump"
    dump.write_bytes(b"private fixture")
    digest = hashlib.sha256(dump.read_bytes()).hexdigest()
    output = tmp_path / "receipt"
    assert rehearsal.validate_local_paths(dump, digest, output) == digest
    with pytest.raises(rehearsal.RehearsalBlocked, match="sha256_mismatch"):
        rehearsal.validate_local_paths(dump, "0" * 64, output)
    output.mkdir()
    with pytest.raises(rehearsal.RehearsalBlocked, match="output_path_already_exists"):
        rehearsal.validate_local_paths(dump, digest, output)


def test_env_loader_requires_private_auth_and_never_passes_provider_values(tmp_path: Path):
    env_file = tmp_path / "test.env"
    env_file.write_text(
        "APP_PASSWORD_HASH=hash-value\nSESSION_SECRET=session-value\n"
        "REHEARSAL_LOGIN_PASSWORD=login-value\nOPENAI_API_KEY=must-not-pass\n"
        "DATABASE_URL=postgresql://production.example/live\n",
        encoding="utf-8",
    )
    values = rehearsal.parse_env_file(env_file)
    isolated = rehearsal.isolated_runtime_env(
        values,
        "postgresql+psycopg://local/freshdb",
        "http://127.0.0.1:44001,http://127.0.0.1:44002",
    )
    assert isolated["DATABASE_URL"] == "postgresql+psycopg://local/freshdb"
    assert isolated["OPENAI_API_KEY"] == ""
    assert isolated["FIRECRAWL_API_KEY"] == ""
    assert isolated["TYPESAFE_API_KEY"] == ""
    assert isolated["INTELLIGENCE_ENABLED"] == "false"
    assert isolated["AUTONOMOUS_RESEARCH_ENABLED"] == "false"
    assert isolated["BRIEFS_DAILY_REQUEST_LIMIT"] == "0"
    assert isolated["TRUSTED_ORIGINS"] == "http://127.0.0.1:44001,http://127.0.0.1:44002"
    assert "REHEARSAL_LOGIN_PASSWORD" not in isolated
    assert "must-not-pass" not in repr(isolated)
    assert "production.example" not in repr(isolated)


def test_revision_and_candidate_image_identity_are_exact(monkeypatch: pytest.MonkeyPatch):
    candidate = "a" * 40
    prior = "b" * 40
    revisions = {
        "candidate-api": candidate,
        "candidate-web": candidate,
        "wrong-web": prior,
        "prior-api": prior,
        "prior-web": prior,
    }
    monkeypatch.setattr(rehearsal, "image_revision", lambda image: revisions[image])
    image_ids = {
        "candidate-api": "sha256:" + "1" * 64,
        "candidate-web": "sha256:" + "2" * 64,
        "prior-api": "sha256:" + "3" * 64,
        "prior-web": "sha256:" + "4" * 64,
    }
    monkeypatch.setattr(rehearsal, "image_id", lambda image: image_ids[image])
    result = rehearsal.validate_images(
        "candidate-api", "candidate-web", "prior-api", "prior-web", candidate
    )
    assert result == {
        "candidate": {"api": candidate, "web": candidate},
        "prior": {"api": prior, "web": prior},
        "resolved_image_ids": {
            "candidate_api": image_ids["candidate-api"],
            "candidate_web": image_ids["candidate-web"],
            "prior_api": image_ids["prior-api"],
            "prior_web": image_ids["prior-web"],
        },
    }
    with pytest.raises(rehearsal.RehearsalBlocked, match="label_mismatch"):
        rehearsal.validate_images("candidate-api", "wrong-web", "prior-api", "prior-web", candidate)


def test_snapshot_compare_preserves_retained_rows_and_logical_call_proof():
    retained_runtime_tables = {"jobs", "planner_states", "worker_heartbeats"}
    assert retained_runtime_tables.isdisjoint(rehearsal.EPHEMERAL_TABLES)
    ignored_block = rehearsal.SNAPSHOT_CODE.split('out = {"schema"', maxsplit=1)[0]
    assert all(table not in ignored_block for table in retained_runtime_tables)
    before = {
        "schema": rehearsal.EXPECTED_SCHEMA,
        "tables": {
            "projects": {"count": 1, "sha256": "x"},
            "jobs": {"count": 2, "sha256": "job-digest"},
            "planner_states": {"count": 1, "sha256": "planner-digest"},
            "worker_heartbeats": {"count": 1, "sha256": "heartbeat-digest"},
        },
        "logical_call_proof": {"logical_calls": {"count": 0, "sha256": "y"}},
    }
    after = {
        "schema": rehearsal.TARGET_SCHEMA,
        "tables": {
            "projects": {"count": 1, "sha256": "x"},
            "jobs": {"count": 2, "sha256": "job-digest"},
            "planner_states": {"count": 1, "sha256": "planner-digest"},
            "worker_heartbeats": {"count": 1, "sha256": "heartbeat-digest"},
            "evidence_packages": {"count": 0, "sha256": "z"},
        },
        "logical_call_proof": before["logical_call_proof"],
    }
    assert rehearsal.compare_snapshots(before, after) == []
    after["tables"]["projects"]["sha256"] = "changed"
    assert "retained_table_changed:projects" in rehearsal.compare_snapshots(before, after)
    after["tables"]["projects"]["sha256"] = "x"
    after["tables"]["jobs"]["sha256"] = "changed-job-digest"
    assert "retained_table_changed:jobs" in rehearsal.compare_snapshots(before, after)
    after["tables"]["jobs"]["sha256"] = "job-digest"
    del after["tables"]["jobs"]
    assert "retained_table_changed:jobs" in rehearsal.compare_snapshots(before, after)
    after["tables"]["jobs"] = {"count": 2, "sha256": "job-digest"}
    after["logical_call_proof"] = {"logical_calls": {"count": 1, "sha256": "z"}}
    assert "logical_call_status_or_budget_changed" in rehearsal.compare_snapshots(before, after)


def test_prior_browse_generation_rollback_requires_intact_metadata_and_successful_guarded_cli(
    monkeypatch: pytest.MonkeyPatch,
):
    generation_id = "12345678-1234-5678-1234-567812345678"
    snapshot = {
        "browse_current_generation": {
            "generation_id": generation_id,
            "input_revision": 7,
            "policy_version": "browse-policy",
            "valid_until": "2030-01-01T00:00:00+00:00",
        }
    }
    assert rehearsal.retained_browse_generation(snapshot) == generation_id
    with pytest.raises(rehearsal.RehearsalBlocked, match="metadata_missing"):
        rehearsal.retained_browse_generation({})
    with pytest.raises(rehearsal.RehearsalBlocked, match="metadata_invalid"):
        rehearsal.retained_browse_generation(
            {"browse_current_generation": {"generation_id": "not-a-uuid"}}
        )

    monkeypatch.setattr(
        rehearsal.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1),
    )
    with pytest.raises(rehearsal.RehearsalBlocked, match="restore_refused"):
        rehearsal.restore_prior_browse_generation("a" * 64, generation_id, {})


def test_timeout_is_unknown_and_not_a_clean_failure(monkeypatch: pytest.MonkeyPatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 1)

    monkeypatch.setattr(rehearsal.subprocess, "run", timeout)
    with pytest.raises(rehearsal.RehearsalUnknown, match="command_outcome_unknown"):
        rehearsal.run(["docker", "start", "container-id"])


def test_remote_docker_host_is_refused_before_context_or_mutation(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DOCKER_HOST", "ssh://example.invalid")
    monkeypatch.setattr(
        rehearsal,
        "run",
        lambda *args, **kwargs: pytest.fail("remote target must fail before any Docker command"),
    )
    with pytest.raises(rehearsal.RehearsalBlocked, match="remote_docker_host_refused"):
        rehearsal.validate_local_docker_target()


def test_postgres_client_uses_database_role_without_nonexistent_container_os_user(
    monkeypatch: pytest.MonkeyPatch,
):
    seen = []

    def ready(args, **kwargs):
        seen.append(args)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(rehearsal.subprocess, "run", ready)
    rehearsal.wait_postgres("a" * 64)
    command = seen[0]
    assert command == [
        "docker",
        "exec",
        "a" * 64,
        "pg_isready",
        "--username",
        "gridlens",
        "-d",
        "freshdb",
    ]
    assert "--user" not in command
    restore = rehearsal.postgres_restore_command("a" * 64)
    assert restore[:5] == ["docker", "exec", "-i", "a" * 64, "pg_restore"]
    assert restore[5:7] == ["--username", "gridlens"]
    assert "--user" not in restore
    assert restore[-1] == "freshdb"
    assert "-" not in restore
    private_detail = b"could not open input file '-' containing private path"
    assert rehearsal.restore_failure_reason(private_detail) == "restore_input_argument_rejected"
    assert "private path" not in rehearsal.restore_failure_reason(private_detail)
