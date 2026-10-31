#!/usr/bin/env python3
"""Historical schema-0041 local restore/image rollback rehearsal only.

This helper cannot certify current schema-0049 recovery. See
docs/operations/recovery-release.md for the current recovery guide. Explicit
--historical-0041-only acknowledgement is required before any resource access.
It has no production mode, accepts only an authorized private dump, uses an
internal Docker network, and keeps failure resources for diagnosis.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

PG_IMAGE = "postgres:18.6"
EXPECTED_SCHEMA = "0041_evidence_packages"
TARGET_SCHEMA = "0041_evidence_packages"
EPHEMERAL_TABLES = {
    "alembic_version",
    "auth_login_buckets",
    "auth_sessions",
    "browse_customer_memberships",
    "browse_dirty_projects",
    "browse_generations",
    "browse_rows",
    "browse_state",
    "browse_unresolved_customers",
}
FORCED_ENV = {
    "AUTONOMOUS_RESEARCH_ENABLED": "false",
    "AUTONOMOUS_RESEARCH_DAILY_QUESTIONS": "0",
    "BRIEFS_DAILY_REQUEST_LIMIT": "0",
    "BUYING_CHAIN_PUBLIC_RESEARCH_ENABLED": "false",
    "COOKIE_SECURE": "false",
    "FIRECRAWL_API_KEY": "",
    "INTELLIGENCE_BOUNDED_ROUTING_AUTHORIZED": "false",
    "INTELLIGENCE_ENABLED": "false",
    "INTELLIGENCE_GLOBAL_DAILY_CALLS": "0",
    "INTELLIGENCE_GLOBAL_DAILY_USD": "0",
    "INTELLIGENCE_GLOBAL_MONTHLY_CALLS": "0",
    "INTELLIGENCE_GLOBAL_MONTHLY_USD": "0",
    "INTELLIGENCE_MAX_ACTIVE_CALLS": "0",
    "INTELLIGENCE_MODE": "disabled",
    "INTELLIGENCE_OPENAI_ENABLED": "false",
    "INTELLIGENCE_RESEARCH_ENABLED": "false",
    "INTELLIGENCE_TYPESAFE_ENABLED": "false",
    "JEV_ENABLED": "false",
    "JEV_SHADOW_DAILY_LIMIT": "0",
    "MONITORING_ENABLED": "false",
    "OPENAI_API_KEY": "",
    "OPPORTUNITY_ENRICHMENT_ENABLED": "false",
    "POWER_NEED_TITLES_ENABLED": "false",
    "PURSUITS_DAILY_FETCH_LIMIT": "0",
    "PURSUITS_DAILY_MODEL_LIMIT": "0",
    "SAVED_BROWSE_ENABLED": "true",
    "TYPESAFE_API_KEY": "",
    "WORKER_AUTO_REFRESH": "false",
}


class RehearsalBlocked(RuntimeError):
    """A precondition or deterministic rehearsal check failed."""


class RehearsalUnknown(RuntimeError):
    """A command outcome is ambiguous; owned resources are retained."""


def run(
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    stdin: Any = subprocess.DEVNULL,
    capture: bool = True,
    timeout: int = 180,
) -> subprocess.CompletedProcess:
    """Run quietly; never return command output that may contain private data."""
    try:
        result = subprocess.run(
            args,
            stdin=stdin,
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env=env,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RehearsalUnknown(f"command_outcome_unknown:{Path(args[0]).name}") from exc
    if result.returncode:
        raise RehearsalBlocked(f"command_failed:{Path(args[0]).name}:{result.returncode}")
    return result


def docker(*args: str, **kwargs: Any) -> subprocess.CompletedProcess:
    return run(["docker", *args], **kwargs)


def parse_env_file(path: Path) -> dict[str, str]:
    """Read a simple dotenv file without interpolation or diagnostic echoes."""
    values: dict[str, str] = {}
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            key, sep, value = line.partition("=")
            if not sep or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key.strip()):
                raise RehearsalBlocked("private_test_env_format_invalid")
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values[key] = value
    except OSError as exc:
        raise RehearsalBlocked("private_test_env_unreadable") from exc
    if not values.get("APP_PASSWORD_HASH") or not values.get("SESSION_SECRET"):
        raise RehearsalBlocked("private_test_env_missing_auth_material")
    if not values.get("REHEARSAL_LOGIN_PASSWORD"):
        raise RehearsalBlocked("private_test_env_missing_rehearsal_login")
    return values


def isolated_runtime_env(
    source: dict[str, str], database_url: str, trusted_origins: str
) -> dict[str, str]:
    """Keep only app authentication settings, then force all providers off."""
    allowed = {
        "APP_PASSWORD_HASH",
        "SESSION_SECRET",
        "SESSION_HOURS",
        "LOGIN_CLIENT_LIMIT",
        "LOGIN_GLOBAL_LIMIT",
        "LOGIN_WINDOW_SECONDS",
    }
    result = {key: value for key, value in source.items() if key in allowed}
    result.update(FORCED_ENV)
    result["DATABASE_URL"] = database_url
    result["TRUSTED_ORIGINS"] = trusted_origins
    return result


def validate_local_docker_target() -> str:
    """Refuse TCP/SSH Docker endpoints before any container/network mutation."""
    host_override = os.environ.get("DOCKER_HOST", "").strip()
    if host_override and not host_override.startswith(("unix://", "npipe://")):
        raise RehearsalBlocked("remote_docker_host_refused")
    context = run(["docker", "context", "show"]).stdout.decode().strip()
    if not context or any(char.isspace() for char in context):
        raise RehearsalBlocked("docker_context_identity_invalid")
    raw = (
        run(
            [
                "docker",
                "context",
                "inspect",
                "--format",
                "{{json .Endpoints.docker.Host}}",
                context,
            ]
        )
        .stdout.decode()
        .strip()
    )
    try:
        endpoint = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise RehearsalBlocked("docker_context_endpoint_invalid") from exc
    if not isinstance(endpoint, str) or not endpoint.startswith(("unix://", "npipe://")):
        raise RehearsalBlocked("remote_docker_context_refused")
    return "local-unix" if endpoint.startswith("unix://") else "local-npipe"


def validate_revision(value: str, *, label: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise RehearsalBlocked(f"{label}_must_be_full_git_revision")


def image_revision(image: str) -> str:
    raw = (
        docker(
            "image",
            "inspect",
            "--format",
            '{{ index .Config.Labels "org.opencontainers.image.revision" }}',
            image,
        )
        .stdout.decode("utf-8", errors="replace")
        .strip()
    )
    return raw


def image_id(image: str) -> str:
    raw = docker("image", "inspect", "--format", "{{.Id}}", image).stdout.decode().strip()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", raw):
        raise RehearsalBlocked("image_content_id_missing_or_invalid")
    return raw


def validate_images(
    api_image: str,
    web_image: str,
    prior_api_image: str,
    prior_web_image: str,
    revision: str,
) -> dict[str, str]:
    validate_revision(revision, label="expected_revision")
    if not all((api_image, web_image, prior_api_image, prior_web_image)):
        raise RehearsalBlocked("all_four_exact_image_references_required")
    if api_image == prior_api_image or web_image == prior_web_image:
        raise RehearsalBlocked("candidate_and_prior_image_refs_must_differ")
    actual = {"api": image_revision(api_image), "web": image_revision(web_image)}
    if actual != {"api": revision, "web": revision}:
        raise RehearsalBlocked("candidate_image_revision_label_mismatch")
    prior = {"api": image_revision(prior_api_image), "web": image_revision(prior_web_image)}
    if any(not re.fullmatch(r"[0-9a-f]{40}", value) for value in prior.values()):
        raise RehearsalBlocked("prior_image_revision_label_missing_or_invalid")
    return {
        "candidate": actual,
        "prior": prior,
        "resolved_image_ids": {
            "candidate_api": image_id(api_image),
            "candidate_web": image_id(web_image),
            "prior_api": image_id(prior_api_image),
            "prior_web": image_id(prior_web_image),
        },
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise RehearsalBlocked("source_dump_unreadable") from exc
    return digest.hexdigest()


def validate_local_paths(dump: Path, expected_sha: str, output: Path) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        raise RehearsalBlocked("expected_dump_sha256_invalid")
    if not dump.is_file() or dump.is_symlink():
        raise RehearsalBlocked("source_dump_must_be_regular_local_file")
    if output.exists():
        raise RehearsalBlocked("output_path_already_exists")
    actual = sha256_file(dump)
    if actual != expected_sha:
        raise RehearsalBlocked("source_dump_sha256_mismatch")
    return actual


def private_directory(path: Path) -> None:
    path.mkdir(parents=True, mode=0o700, exist_ok=False)
    try:
        os.chmod(path, 0o700)
    except OSError as exc:
        raise RehearsalBlocked("cannot_make_output_private") from exc


API_READY_CODE = r"""
from urllib.request import urlopen
try:
    with urlopen("http://127.0.0.1:8000/health/ready", timeout=3) as response:
        raise SystemExit(0 if response.status == 200 else 1)
except Exception:
    raise SystemExit(1)
"""

API_SMOKE_CODE = r"""
import http.cookiejar, json, os
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener
base = "http://127.0.0.1:8000"
jar = http.cookiejar.CookieJar()
opener = build_opener(HTTPCookieProcessor(jar))
def stop(step, status):
    print(json.dumps({"ok": False, "step": step, "status": status}))
    raise SystemExit(1)
def get(step, path):
    try:
        with opener.open(base + path, timeout=3) as response:
            raw = response.read(2_000_000)
            return response.status, json.loads(raw) if raw else None
    except HTTPError as exc:
        stop(step, exc.code)
    except Exception:
        stop(step, "transport")
status, body = get("unauthenticated_session", "/api/auth/session")
if status != 200 or body != {"authenticated": False}:
    stop("unauthenticated_session", status)
login = Request(
    base + "/api/auth/login",
    data=json.dumps({"password": os.environ["REHEARSAL_LOGIN_PASSWORD"]}).encode(),
    headers={"Content-Type": "application/json", "Origin": base},
    method="POST",
)
try:
    with opener.open(login, timeout=3) as response:
        status, body = response.status, json.loads(response.read(100_000))
except HTTPError as exc:
    stop("login", exc.code)
except Exception:
    stop("login", "transport")
if status != 200 or body.get("authenticated") is not True:
    stop("login", status)
status, body = get("authenticated_session", "/api/auth/session")
if status != 200 or body != {"authenticated": True}:
    stop("authenticated_session", status)
read_paths = (
    ("health", "/api/health"),
    ("workspace", "/api/opportunities/workspace?limit=1&offset=0"),
    ("customer_accounts", "/api/customer-accounts?limit=1&offset=0"),
    ("intelligence_tasks", "/api/intelligence/tasks"),
)
for step, path in read_paths:
    status, _ = get(step, path)
    if status != 200:
        stop(step, status)
print(
    json.dumps(
        {
            "ok": True,
            "unauthenticated_session": 200,
            "authenticated_session": 200,
            "authenticated_read_paths": [
                "/api/opportunities/workspace",
                "/api/customer-accounts",
                "/api/intelligence/tasks",
            ],
        }
    )
)
"""


def wait_api_ready(container: str, process_env: dict[str, str], *, timeout: int = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = subprocess.run(
                ["docker", "exec", "-i", container, "uv", "run", "python", "-"],
                input=API_READY_CODE.encode(),
                capture_output=True,
                env=process_env,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RehearsalUnknown("api_readiness_command_outcome_unknown") from exc
        if result.returncode == 0:
            return
        time.sleep(1)
    raise RehearsalBlocked("api_internal_readiness_timeout")


def api_smoke(container: str, process_env: dict[str, str]) -> dict[str, Any]:
    """Run exactly one authenticated read sequence after readiness is established."""
    try:
        result = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                "--env",
                "REHEARSAL_LOGIN_PASSWORD",
                container,
                "uv",
                "run",
                "python",
                "-",
            ],
            input=API_SMOKE_CODE.encode(),
            capture_output=True,
            env=process_env,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RehearsalUnknown("api_smoke_command_outcome_unknown") from exc
    try:
        value = json.loads(result.stdout)
    except (ValueError, TypeError) as exc:
        raise RehearsalBlocked("api_smoke_receipt_invalid") from exc
    if not isinstance(value, dict):
        raise RehearsalBlocked("api_smoke_receipt_invalid")
    if result.returncode or value.get("ok") is not True:
        step = value.get("step") if isinstance(value.get("step"), str) else "unknown"
        status = value.get("status")
        if not isinstance(status, int | str):
            status = "unknown"
        raise RehearsalBlocked(f"api_smoke_failed:{step}:{status}")
    return value


SNAPSHOT_CODE = r"""
import hashlib, json
from sqlalchemy import create_engine, inspect, text
from gridlens.settings import settings
engine = create_engine(settings.database_url)
ignored = {
    "alembic_version", "auth_login_buckets", "auth_sessions",
    "browse_customer_memberships", "browse_dirty_projects", "browse_generations",
    "browse_rows", "browse_state", "browse_unresolved_customers",
}
out = {"schema": None, "tables": {}, "logical_call_proof": {}, "browse_current_generation": None}
with engine.connect() as c:
    versions = c.execute(
        text("SELECT version_num FROM alembic_version ORDER BY version_num")
    ).scalars().all()
    out["schema"] = versions[-1] if versions else None
    browse = c.execute(
        text(
            "SELECT state.generation_id, state.input_revision, "
            "generation.policy_version, generation.valid_until "
            "FROM browse_state AS state LEFT JOIN browse_generations AS generation "
            "ON generation.id = state.generation_id WHERE state.id = 1"
        )
    ).mappings().one_or_none()
    if browse is not None and browse["generation_id"] is not None:
        out["browse_current_generation"] = {
            "generation_id": str(browse["generation_id"]),
            "input_revision": browse["input_revision"],
            "policy_version": browse["policy_version"],
            "valid_until": browse["valid_until"].isoformat() if browse["valid_until"] else None,
        }
    names = inspect(c).get_table_names()
    for name in sorted(set(names) - ignored):
        q = 'SELECT * FROM "' + name.replace('"', '""') + '"'
        rows = c.execute(text(q)).mappings().all()
        encoded = sorted(
            json.dumps(dict(row), default=str, sort_keys=True, separators=(",", ":"))
            for row in rows
        )
        out["tables"][name] = {
            "count": len(rows),
            "sha256": hashlib.sha256("\n".join(encoded).encode()).hexdigest(),
        }
    for table in ("logical_calls", "logical_call_budgets"):
        if table in names:
            rows = c.execute(text('SELECT * FROM "' + table + '"')).mappings().all()
            encoded = sorted(
                json.dumps(dict(row), default=str, sort_keys=True, separators=(",", ":"))
                for row in rows
            )
            out["logical_call_proof"][table] = {
                "count": len(rows),
                "sha256": hashlib.sha256("\n".join(encoded).encode()).hexdigest(),
            }
print(json.dumps(out, sort_keys=True, separators=(",", ":")))
"""


def snapshot(api_container: str) -> dict[str, Any]:
    # Use Popen for stdin while suppressing raw Python/SQL diagnostics.
    try:
        result = subprocess.run(
            ["docker", "exec", "-i", api_container, "uv", "run", "python", "-"],
            input=SNAPSHOT_CODE.encode(),
            capture_output=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RehearsalUnknown("snapshot_command_outcome_unknown") from exc
    if result.returncode:
        raise RehearsalBlocked("snapshot_command_failed")
    try:
        value = json.loads(result.stdout)
    except (ValueError, TypeError) as exc:
        raise RehearsalBlocked("snapshot_receipt_invalid") from exc
    if not isinstance(value, dict) or not isinstance(value.get("tables"), dict):
        raise RehearsalBlocked("snapshot_receipt_shape_invalid")
    return value


def compare_snapshots(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if before.get("schema") != EXPECTED_SCHEMA or after.get("schema") != TARGET_SCHEMA:
        problems.append("unexpected_schema_transition")
    left = {k: v for k, v in before.get("tables", {}).items() if k not in EPHEMERAL_TABLES}
    right = {k: v for k, v in after.get("tables", {}).items() if k not in EPHEMERAL_TABLES}
    for name in sorted(set(left) | set(right)):
        if name not in left and right[name].get("count") == 0:
            continue
        if left.get(name) != right.get(name):
            problems.append(f"retained_table_changed:{name}")
    if before.get("logical_call_proof") != after.get("logical_call_proof"):
        problems.append("logical_call_status_or_budget_changed")
    return problems


def retained_browse_generation(snapshot_value: dict[str, Any]) -> str:
    """Return the pre-candidate browse pointer only when its metadata is intact."""
    value = snapshot_value.get("browse_current_generation")
    if not isinstance(value, dict):
        raise RehearsalBlocked("prior_browse_generation_metadata_missing")
    generation_id = value.get("generation_id")
    if (
        not isinstance(generation_id, str)
        or not value.get("policy_version")
        or not value.get("valid_until")
    ):
        raise RehearsalBlocked("prior_browse_generation_metadata_invalid")
    try:
        return str(uuid.UUID(generation_id))
    except (ValueError, AttributeError) as exc:
        raise RehearsalBlocked("prior_browse_generation_metadata_invalid") from exc


def restore_prior_browse_generation(
    api_container: str, generation_id: str, process_env: dict[str, str]
) -> None:
    """Use the prior image's guarded derived-cache rollback; never write the pointer directly."""
    try:
        result = subprocess.run(
            [
                "docker",
                "exec",
                api_container,
                "uv",
                "run",
                "python",
                "-m",
                "gridlens.jobs.browse",
                "rollback",
                "--generation",
                generation_id,
            ],
            env=process_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RehearsalUnknown("prior_browse_generation_restore_outcome_unknown") from exc
    if result.returncode:
        raise RehearsalBlocked("prior_browse_generation_restore_refused")


def container_id(name: str) -> str:
    result = docker("inspect", "--format", "{{.Id}}", name).stdout.decode().strip()
    if not re.fullmatch(r"[0-9a-f]{64}", result):
        raise RehearsalUnknown("created_container_identity_unverifiable")
    return result


def network_id(name: str) -> str:
    result = docker("network", "inspect", "--format", "{{.Id}}", name).stdout.decode().strip()
    if not re.fullmatch(r"[0-9a-f]{64}", result):
        raise RehearsalUnknown("created_network_identity_unverifiable")
    return result


def run_owned(container_id_value: str) -> None:
    docker("start", container_id_value)


def wait_postgres(container: str) -> None:
    for _ in range(60):
        proc = subprocess.run(
            [
                "docker",
                "exec",
                container,
                "pg_isready",
                "--username",
                "gridlens",
                "-d",
                "freshdb",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if proc.returncode == 0:
            return
        time.sleep(1)
    raise RehearsalBlocked("postgres_readiness_timeout")


def postgres_restore_command(container: str) -> list[str]:
    """Build pg_restore args; database role is a client option, not Docker OS user."""
    return [
        "docker",
        "exec",
        "-i",
        container,
        "pg_restore",
        "--username",
        "gridlens",
        "--no-owner",
        "--no-privileges",
        "--exit-on-error",
        "--dbname",
        "freshdb",
    ]


def restore_failure_reason(stderr: bytes) -> str:
    """Map private pg_restore diagnostics to a safe, content-free reason code."""
    diagnostic = stderr.decode("utf-8", errors="replace").lower()
    if "could not open input file" in diagnostic:
        return "restore_input_argument_rejected"
    return "private_dump_restore_failed"


def migration(api_id: str, runtime: dict[str, str], *, command: tuple[str, ...]) -> None:
    env = os.environ.copy()
    env.update(runtime)
    env["DATABASE_URL"] = runtime["DATABASE_URL"]
    try:
        result = subprocess.run(
            ["docker", "exec", api_id, *command],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=900,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RehearsalUnknown("migration_outcome_unknown") from exc
    if result.returncode:
        raise RehearsalBlocked("candidate_migration_failed")


def write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def record_event(output: Path, phase: str, status: str) -> None:
    path = output / "events.jsonl"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "at_utc": dt.datetime.now(dt.UTC).isoformat(),
                    "phase": phase,
                    "status": status,
                },
                sort_keys=True,
            )
            + "\n"
        )
    os.chmod(path, 0o600)


def remove_owned(ids: list[str], network_identity: str) -> None:
    try:
        for value in ids:
            # Only immutable IDs returned by inspect after this run's create are accepted.
            if re.fullmatch(r"[0-9a-f]{64}", value):
                docker("rm", "-f", value, capture=False)
        if re.fullmatch(r"[0-9a-f]{64}", network_identity):
            docker("network", "rm", network_identity, capture=False)
        else:
            raise RehearsalUnknown("created_network_identity_unverifiable")
    except (RehearsalBlocked, RehearsalUnknown) as exc:
        raise RehearsalUnknown("owned_resource_cleanup_outcome_unknown") from exc


def assert_snapshot_equal(before: dict[str, Any], after: dict[str, Any]) -> None:
    if before.get("tables") != after.get("tables"):
        raise RehearsalBlocked("rollback_retained_snapshot_changed")
    if before.get("logical_call_proof") != after.get("logical_call_proof"):
        raise RehearsalBlocked("rollback_logical_call_status_or_budget_changed")


def web_smoke(container: str, *, timeout: int = 30) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            root = subprocess.run(
                [
                    "docker",
                    "exec",
                    container,
                    "wget",
                    "-q",
                    "-O",
                    "/dev/null",
                    "http://127.0.0.1:8080/",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
            )
            proxy = subprocess.run(
                [
                    "docker",
                    "exec",
                    container,
                    "wget",
                    "-q",
                    "-O",
                    "/dev/null",
                    "http://127.0.0.1:8080/api/auth/session",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RehearsalUnknown("web_smoke_command_outcome_unknown") from exc
        if root.returncode == 0 and proxy.returncode == 0:
            return {"root": 200, "proxied_session": 200, "network": "internal-container"}
        time.sleep(1)
    raise RehearsalBlocked("web_internal_proxy_readiness_timeout")


def require_historical_acknowledgement(args: argparse.Namespace) -> None:
    """Fail before file/Docker access; acknowledgement does not relax any guard."""
    if getattr(args, "historical_0041_only", False) is not True:
        raise RehearsalBlocked(
            "Historical schema-0041 helper requires --historical-0041-only; "
            "cannot certify current schema-0049 recovery. "
            "See docs/operations/recovery-release.md"
        )


def rehearsal(args: argparse.Namespace) -> dict[str, Any]:
    require_historical_acknowledgement(args)
    if args.dump.is_symlink() or args.test_env.is_symlink():
        raise RehearsalBlocked("input_files_must_not_be_symlinks")
    dump = args.dump.resolve(strict=True)
    output = args.output.resolve()
    dump_sha = validate_local_paths(dump, args.dump_sha256.lower(), output)
    env_path = args.test_env.resolve(strict=True)
    if not env_path.is_file() or env_path.is_symlink():
        raise RehearsalBlocked("private_test_env_must_be_regular_file")
    if os.name != "nt" and env_path.stat().st_mode & 0o077:
        raise RehearsalBlocked("private_test_env_permissions_too_open")
    source_env = parse_env_file(env_path)
    docker_target = validate_local_docker_target()
    revisions = validate_images(
        args.api_image,
        args.web_image,
        args.prior_api_image,
        args.prior_web_image,
        args.revision.lower(),
    )
    pg_image_id = image_id(args.pg_image)
    private_directory(output)
    run_id = uuid.uuid4().hex
    network = f"gridlens-rehearsal-{run_id}"
    names = {
        "db": f"gridlens-rehearsal-db-{run_id}",
        "api": f"gridlens-rehearsal-api-{run_id}",
        "web": f"gridlens-rehearsal-web-{run_id}",
    }
    owned: list[str] = []
    owned_network_id = ""
    receipt: dict[str, Any] = {
        "status": "UNKNOWN_STOP",
        "candidate_revision": args.revision.lower(),
        "candidate_images": {"api": args.api_image, "web": args.web_image},
        "prior_images": {"api": args.prior_api_image, "web": args.prior_web_image},
        "image_revisions": revisions,
        "postgres_image": {"reference": args.pg_image, "resolved_image_id": pg_image_id},
        "docker_target": docker_target,
        "created_name_candidates": names,
        "network_id": owned_network_id,
        "dump": {"sha256": dump_sha, "size_bytes": dump.stat().st_size},
        "disposition": "private diagnostic receipt; no production targets accepted",
    }
    pg_password = secrets.token_urlsafe(36)
    pg_env = os.environ.copy()
    pg_env.update(
        {"POSTGRES_USER": "gridlens", "POSTGRES_PASSWORD": pg_password, "POSTGRES_DB": "freshdb"}
    )
    try:
        record_event(output, "input_identity", "pass")
        docker(
            "network", "create", "--internal", "--label", f"gridlens.rehearsal={run_id}", network
        )
        owned_network_id = network_id(network)
        docker(
            "create",
            "--name",
            names["db"],
            "--network",
            network,
            "--network-alias",
            "db",
            "--label",
            f"gridlens.rehearsal={run_id}",
            "--env",
            "POSTGRES_USER",
            "--env",
            "POSTGRES_PASSWORD",
            "--env",
            "POSTGRES_DB",
            pg_image_id,
            env=pg_env,
        )
        db_id = container_id(names["db"])
        owned.append(db_id)
        run_owned(db_id)
        wait_postgres(db_id)
        try:
            with dump.open("rb") as source:
                result = subprocess.run(
                    postgres_restore_command(db_id),
                    stdin=source,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    timeout=3600,
                    check=False,
                )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RehearsalUnknown("restore_outcome_unknown") from exc
        if result.returncode:
            raise RehearsalBlocked(restore_failure_reason(result.stderr or b""))
        record_event(output, "pg18_restore", "pass")
        db_url = f"postgresql+psycopg://gridlens:{pg_password}@db:5432/freshdb"
        runtime = isolated_runtime_env(
            source_env,
            db_url,
            "http://127.0.0.1:8000,http://api:8000,http://127.0.0.1:8080,http://web:8080",
        )
        process_env = os.environ.copy()
        process_env.update(runtime)
        process_env["REHEARSAL_LOGIN_PASSWORD"] = source_env["REHEARSAL_LOGIN_PASSWORD"]
        process_env["POSTGRES_USER"] = "gridlens"
        process_env["POSTGRES_PASSWORD"] = pg_password
        process_env["POSTGRES_DB"] = "freshdb"
        docker(
            "create",
            "--name",
            names["api"],
            "--network",
            network,
            "--network-alias",
            "api",
            "--label",
            f"gridlens.rehearsal={run_id}",
            *(part for key in sorted(runtime) for part in ("--env", key)),
            revisions["resolved_image_ids"]["candidate_api"],
            "uv",
            "run",
            "uvicorn",
            "gridlens.api.app:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
            "--no-proxy-headers",
            env=process_env,
        )
        api_id = container_id(names["api"])
        owned.append(api_id)
        run_owned(api_id)
        baseline = snapshot(api_id)
        prior_generation_id = retained_browse_generation(baseline)
        write_receipt(output / "snapshot-before.json", baseline)
        record_event(output, "snapshot_before", "pass")
        if baseline.get("schema") != EXPECTED_SCHEMA:
            raise RehearsalBlocked("restored_dump_schema_not_expected")
        migration(api_id, runtime, command=("uv", "run", "alembic", "upgrade", "head"))
        after_migration = snapshot(api_id)
        write_receipt(output / "snapshot-candidate-migration.json", after_migration)
        if compare_snapshots(baseline, after_migration):
            raise RehearsalBlocked("migration_changed_retained_snapshot")
        migration(api_id, runtime, command=("uv", "run", "alembic", "upgrade", "head"))
        after_repeat = snapshot(api_id)
        write_receipt(output / "snapshot-candidate-migration-repeat.json", after_repeat)
        if compare_snapshots(baseline, after_repeat):
            raise RehearsalBlocked("repeated_migration_changed_retained_snapshot")
        record_event(output, "candidate_migration", "pass")
        # Rebuild only the derived browse projection, whose tables are excluded explicitly.
        migration(
            api_id,
            runtime,
            command=("uv", "run", "python", "-m", "gridlens.jobs.browse", "rebuild"),
        )
        candidate = snapshot(api_id)
        write_receipt(output / "snapshot-candidate-after-browse.json", candidate)
        if compare_snapshots(baseline, candidate):
            raise RehearsalBlocked("browse_rebuild_changed_retained_snapshot")
        wait_api_ready(api_id, process_env)
        api_receipt = api_smoke(api_id, process_env)
        # Web image is served only on loopback and shares the egress-disabled network.
        docker(
            "create",
            "--name",
            names["web"],
            "--network",
            network,
            "--label",
            f"gridlens.rehearsal={run_id}",
            revisions["resolved_image_ids"]["candidate_web"],
        )
        web_id = container_id(names["web"])
        owned.append(web_id)
        run_owned(web_id)
        web_receipt = web_smoke(web_id)
        record_event(output, "candidate_api_web_smoke", "pass")
        # Exercise worker/browse imports only. The worker loop and browse maintainer
        # are never started against retained jobs.
        migration(
            api_id,
            runtime,
            command=(
                "uv",
                "run",
                "python",
                "-c",
                "import gridlens.jobs.worker, gridlens.jobs.browse",
            ),
        )
        after_smoke = snapshot(api_id)
        write_receipt(output / "snapshot-candidate-after-smoke.json", after_smoke)
        if compare_snapshots(baseline, after_smoke):
            raise RehearsalBlocked("candidate_smoke_changed_retained_snapshot")
        # Stop candidate services and verify the prior images read the same forward schema.
        docker("stop", "--time", "15", api_id, web_id)
        rollback_name = f"gridlens-rehearsal-prior-api-{run_id}"
        rollback_web_name = f"gridlens-rehearsal-prior-web-{run_id}"
        docker(
            "create",
            "--name",
            rollback_name,
            "--network",
            network,
            "--network-alias",
            "api",
            "--label",
            f"gridlens.rehearsal={run_id}",
            *(part for key in sorted(runtime) for part in ("--env", key)),
            revisions["resolved_image_ids"]["prior_api"],
            "uv",
            "run",
            "uvicorn",
            "gridlens.api.app:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
            "--no-proxy-headers",
            env=process_env,
        )
        rollback_api_id = container_id(rollback_name)
        owned.append(rollback_api_id)
        run_owned(rollback_api_id)
        wait_api_ready(rollback_api_id, process_env)
        restore_prior_browse_generation(rollback_api_id, prior_generation_id, process_env)
        rollback_smoke = api_smoke(rollback_api_id, process_env)
        rollback_snapshot = snapshot(rollback_api_id)
        write_receipt(output / "snapshot-rollback.json", rollback_snapshot)
        if rollback_snapshot.get("schema") != TARGET_SCHEMA:
            raise RehearsalBlocked("prior_image_forward_schema_unreadable")
        if retained_browse_generation(rollback_snapshot) != prior_generation_id:
            raise RehearsalBlocked("prior_browse_generation_restore_not_current")
        assert_snapshot_equal(after_smoke, rollback_snapshot)
        docker(
            "create",
            "--name",
            rollback_web_name,
            "--network",
            network,
            "--label",
            f"gridlens.rehearsal={run_id}",
            revisions["resolved_image_ids"]["prior_web"],
        )
        rollback_web_id = container_id(rollback_web_name)
        owned.append(rollback_web_id)
        run_owned(rollback_web_id)
        prior_web_receipt = web_smoke(rollback_web_id)
        record_event(output, "prior_release_rollback_smoke", "pass")
        receipt.update(
            {
                "status": "PASS_CANDIDATE_REHEARSAL",
                "schema_before": baseline["schema"],
                "schema_after": after_smoke["schema"],
                "retained_snapshot_sha256": hashlib.sha256(
                    json.dumps(
                        after_smoke["tables"], sort_keys=True, separators=(",", ":")
                    ).encode()
                ).hexdigest(),
                "logical_call_proof": after_smoke.get("logical_call_proof", {}),
                "api_smoke": api_receipt,
                "web_smoke": web_receipt,
                "worker_browse": "imports_passed; dispatch and maintenance loops not invoked",
                "rollback": {
                    "schema": rollback_snapshot["schema"],
                    "restored_browse_generation": prior_generation_id,
                    "api_smoke": rollback_smoke,
                    "web_smoke": prior_web_receipt,
                    "retained_snapshot_sha256": hashlib.sha256(
                        json.dumps(
                            rollback_snapshot["tables"], sort_keys=True, separators=(",", ":")
                        ).encode()
                    ).hexdigest(),
                },
                "container_ids": owned.copy(),
                "network": network,
                "cleanup": (
                    "success path removes only recorded owned container IDs and exact network"
                ),
            }
        )
        write_receipt(output / "rehearsal-receipt.json", receipt)
        remove_owned(owned, owned_network_id)
        record_event(output, "owned_resource_cleanup", "pass")
        receipt["cleanup"] = "owned containers and exact network removed after successful rehearsal"
        write_receipt(output / "rehearsal-receipt.json", receipt)
        return receipt
    except Exception as exc:
        if isinstance(exc, RehearsalBlocked):
            receipt.update({"status": "BLOCKED", "reason": str(exc)})
        elif isinstance(exc, RehearsalUnknown):
            receipt.update({"status": "UNKNOWN_STOP", "reason": str(exc)})
        else:
            receipt.update({"status": "UNKNOWN_STOP", "reason": f"unexpected:{type(exc).__name__}"})
        receipt["owned_container_ids"] = owned
        receipt["created_name_candidates"] = names
        receipt["network"] = network
        receipt["network_id"] = owned_network_id
        receipt["cleanup"] = "failed/unknown outcomes preserve all owned resources for diagnosis"
        record_event(output, "rehearsal_stop", receipt["status"])
        write_receipt(output / "rehearsal-receipt.json", receipt)
        raise


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument(
        "--historical-0041-only",
        action="store_true",
        help="acknowledge historical schema-0041 only; cannot certify current recovery",
    )
    result.add_argument("--dump", type=Path, required=True)
    result.add_argument("--dump-sha256", required=True)
    result.add_argument("--api-image", required=True)
    result.add_argument("--web-image", required=True)
    result.add_argument("--revision", required=True)
    result.add_argument("--prior-api-image", required=True)
    result.add_argument("--prior-web-image", required=True)
    result.add_argument("--test-env", type=Path, required=True)
    result.add_argument("--output", type=Path, required=True)
    result.add_argument(
        "--pg-image",
        default=PG_IMAGE,
        help="local PostgreSQL image reference (default: postgres:18.6)",
    )
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        require_historical_acknowledgement(args)
    except RehearsalBlocked as exc:
        print(str(exc), file=sys.stderr)
        return 2
    try:
        result = rehearsal(args)
    except RehearsalBlocked:
        return 2
    except RehearsalUnknown:
        return 3
    except Exception:
        return 3
    print(
        json.dumps(
            {"status": result["status"], "receipt": str(args.output / "rehearsal-receipt.json")},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
