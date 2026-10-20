"""Reversible TITLE-02 continuing activation controller for the GL3 host.

This is a prepared controller, not an execution receipt. It has no dry-run
mode and must only be invoked after the host operator has recorded the already
approved scope and passed release/test evidence in its fixed release gate. It
never edits Compose, starts a build, changes a database, or prints runtime
environment values. See title02-activate-runtime-notes.md for gate fields.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit


if sys.flags.optimize != 0:
    raise RuntimeError("Activation controller requires Python optimization disabled")

if len(sys.argv) != 2:
    raise SystemExit("usage: title02-activate-runtime.py <40-char-revision>")

REVISION = sys.argv[1]
assert re.fullmatch(r"[0-9a-f]{40}", REVISION)

HOST_ROOT = Path("/etc/gridlens")
RELEASE_ROOT = Path("/opt/gridlens/releases") / ("title02-" + REVISION[:12])
INPUTS = RELEASE_ROOT / "validation-inputs"
SIX_CONTROL = RELEASE_ROOT / "validation-control"
ACTIVATION_CONTROL = RELEASE_ROOT / "continuing-activation-control"
SCOPE_SHA256 = "ce5b146ab3759a9af012ad521c15450c9621a64abc387c9999a4eb071d453cfc"
ACTIVATION_SHA256 = "5f6d5a44e6e740aed583d1269babdaa21eb9a2cfd954e952047cd499526608d5"
AUTHORIZATION_SHA256 = "0859fcbb3c97c846abc3598355324e6d08207d520321d45c2f6b7353c1a6fb11"
BASELINE_COMPOSE_SHA256 = "3c0f64f2708df19dda40dc565040314d5dc2972b19690f00a5405d214931d660"
EXPECTED_CANDIDATE_COMPOSE_SHA256 = "524f2ba0ae7178dbae3fea4666eaaec19f225468b17227fa900d06a48c99971b"
RUNTIME_SHA256 = "b6bd47b38b67501bbc0623a83903748ef100e522d5ddb14d05651117125b9cb9"
STARTUP_SHA256 = "1cedfc857f6e29e818098f5fbd2e7ae3c691221467864779e350768b1dfd1920"
DB_NAME = "gridlens_restore_20261014"
SERVICE_NAMES = ("api", "worker", "browse")
CONTAINER_NAMES = {name: "gridlens-" + name + "-1" for name in (*SERVICE_NAMES, "web", "db")}
LOCK_PATH = Path("/run/lock/gridlens-title02-continuing-activation.lock")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def checked_file(path: Path, expected: str) -> bytes:
    assert path.is_file() and not path.is_symlink(), "Required reviewed file is absent or indirect"
    data = path.read_bytes()
    assert sha256(data) == expected, "Reviewed file digest mismatch"
    return data


def private_run(args: list[str], *, input_bytes: bytes | None = None, timeout: int = 180) -> bytes:
    """Capture all output; callers parse only explicitly nonsecret fields."""
    completed = subprocess.run(
        args,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError("Private host operation failed: " + Path(args[0]).name)
    return completed.stdout


def secure_json(path: Path) -> tuple[dict, bytes]:
    assert path.is_file() and not path.is_symlink(), "Required receipt/gate is absent or indirect"
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode & 0o077 == 0, "Approval/receipt file must be private"
    raw = path.read_bytes()
    parsed = json.loads(raw)
    assert isinstance(parsed, dict)
    return parsed, raw


def candidate_compose_text(prior_text: str, revision: str) -> str:
    api_old = "gridlens-api:pr88-85acc0eca4db"
    web_old = "gridlens-web:title01-d58691eaa5f9"
    api_new = "gridlens-api:title02-" + revision[:12]
    web_new = "gridlens-web:title02-" + revision[:12]
    assert prior_text.count(api_old) == 1 and prior_text.count(web_old) == 1
    return prior_text.replace(api_old, api_new).replace(web_old, web_new)


def validate_release_gate(path: Path, scope: dict, activation: dict):
    assert path == RELEASE_ROOT / "continuing-activation-gate.json"
    gate, _ = secure_json(path)
    assert gate.get("release_gate_passed") is True
    assert gate.get("revision") == REVISION
    manifest_path = INPUTS / ("title02-" + REVISION[:12] + "-git-manifest.json")
    manifest_bytes = checked_file(manifest_path, gate["git_manifest_sha256"])
    manifest = json.loads(manifest_bytes)
    assert manifest["revision"] == REVISION
    full_candidate = manifest["full_candidate"]
    assert re.fullmatch(r"[0-9a-f]{64}", full_candidate)
    assert gate.get("full_candidate") == full_candidate

    build_evidence_bytes = checked_file(RELEASE_ROOT / "build-evidence.json", gate["build_evidence_sha256"])
    build_evidence = json.loads(build_evidence_bytes)
    assert build_evidence.get("revision") == REVISION
    images = {}
    for kind in ("api", "web"):
        tag = f"gridlens-{kind}:title02-{REVISION[:12]}"
        image_id = build_evidence.get("images", {}).get(tag)
        assert isinstance(image_id, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", image_id)
        images[kind] = image_id
    assert gate.get("images") == images

    authorization_path = INPUTS / "title02-authorization-20261020.json"
    authorization_bytes = checked_file(authorization_path, AUTHORIZATION_SHA256)
    authorization = json.loads(authorization_bytes)
    assert authorization.get("approved") is True
    assert authorization.get("user_reply") == "Approved"
    assert authorization.get("user_reply_utc") == "2026-10-20T00:51:00Z"
    assert authorization.get("initial_six_public_intents_authorized") is True
    assert authorization.get("continuing_public_scope_authorized") is True
    assert authorization.get("scope_sha256") == SCOPE_SHA256
    assert authorization.get("activation_sha256") == ACTIVATION_SHA256
    assert gate.get("authorization_sha256") == AUTHORIZATION_SHA256
    assert gate.get("scope_sha256") == SCOPE_SHA256
    assert gate.get("activation_sha256") == ACTIVATION_SHA256
    assert gate.get("activation_controller_sha256") == sha256(Path(__file__).read_bytes())
    assert gate.get("git_manifest_sha256") == sha256(manifest_bytes)
    assert gate.get("build_evidence_sha256") == sha256(build_evidence_bytes)

    rollout_path = RELEASE_ROOT / ("title02-rollout-" + REVISION[:12] + ".json")
    rollout_bytes = checked_file(rollout_path, gate["rollout_receipt_sha256"])
    rollout = json.loads(rollout_bytes)
    assert rollout.get("passed") is True and rollout.get("revision") == REVISION
    assert rollout.get("tag") == "title02-" + REVISION[:12]
    assert gate.get("rollout_receipt_sha256") == sha256(rollout_bytes)
    prior_compose_path = Path(rollout["prior_compose"])
    assert prior_compose_path.parent == HOST_ROOT and prior_compose_path.is_file() and not prior_compose_path.is_symlink()
    assert prior_compose_path.name.startswith("compose.app.pre-title02-" + REVISION[:12] + "-")
    prior_compose_text = prior_compose_path.read_text(encoding="utf-8")
    assert sha256(prior_compose_text.encode("utf-8")) == BASELINE_COMPOSE_SHA256
    expected_compose_text = candidate_compose_text(prior_compose_text, REVISION)
    expected_compose_sha = sha256(expected_compose_text.encode("utf-8"))
    assert expected_compose_sha == EXPECTED_CANDIDATE_COMPOSE_SHA256
    assert gate.get("candidate_compose_sha256") == expected_compose_sha

    assert sha256((INPUTS / "title02-jev-proposed-scope.json").read_bytes()) == SCOPE_SHA256
    assert sha256((INPUTS / "title02-proposed-activation.json").read_bytes()) == ACTIVATION_SHA256
    assert gate.get("six_intent_receipt", {}).get("scope_sha256") == SCOPE_SHA256
    assert gate.get("six_intent_receipt", {}).get("activation_sha256") == ACTIVATION_SHA256
    assert scope.get("status") == "PROPOSED_NOT_ACTIVATED"
    assert activation.get("status") == "PROPOSED_NOT_AUTHORIZED_OR_APPLIED"
    assert len(scope["records"]) == 3
    observation_ids = [record["observation_id"] for record in scope["records"]]
    need_ids = [record["need_id"] for record in scope["records"]]
    assert len(set(observation_ids)) == len(set(need_ids)) == 3
    assert activation["runtime_changes"]["INTELLIGENCE_TYPESAFE_ESTIMATE_OBSERVATION_IDS"] == ",".join(
        observation_ids
    )

    receipt_path = SIX_CONTROL / "host-receipt.json"
    journal_path = SIX_CONTROL / "title02-six-intents.jsonl"
    six_gate_path = SIX_CONTROL / "gate.json"
    receipt, receipt_bytes = secure_json(receipt_path)
    journal_bytes = journal_path.read_bytes()
    six_gate, six_gate_bytes = secure_json(six_gate_path)
    bundle = gate.get("six_intent_receipt")
    assert isinstance(bundle, dict)
    assert bundle.get("host_receipt_sha256") == sha256(receipt_bytes)
    assert bundle.get("journal_sha256") == sha256(journal_bytes)
    assert bundle.get("gate_sha256") == sha256(six_gate_bytes)
    assert receipt.get("passed") is True and receipt.get("revision") == REVISION
    assert receipt.get("worker_restarted") is True
    assert receipt.get("controller_state") in ("absent", "stopped")
    assert six_gate.get("revision") == REVISION
    assert six_gate.get("full_candidate") == full_candidate
    assert six_gate.get("image") == images["api"]
    assert six_gate.get("scope_sha256") == SCOPE_SHA256
    assert six_gate.get("activation_sha256") == ACTIVATION_SHA256
    assert six_gate.get("ordinary_worker_stopped") is True
    assert six_gate.get("normal_new_contracts_disabled") is True

    events = [json.loads(line) for line in journal_bytes.decode("utf-8").splitlines() if line.strip()]
    assert events and events[-1].get("phase") == "complete"
    assert events[-1].get("six_jobs_passed") is True
    fixed = next(event for event in events if event.get("phase") == "fixed_intents_before_commit")
    intents = fixed.get("intents")
    completed = [event for event in events if event.get("phase") == "completed_fixed_job"]
    assert isinstance(intents, list) and len(intents) == 6 and len(completed) == 6
    assert len({item["job_id"] for item in intents}) == 6
    assert {item["job_id"] for item in intents} == {item["job_id"] for item in completed}
    assert len(receipt.get("results", [])) == 6
    assert {item["job_id"] for item in receipt["results"]} == {item["job_id"] for item in intents}
    assert {item["job_id"] for item in receipt["results"]} == {item["job_id"] for item in completed}
    assert receipt["results"] == completed
    kinds = [item["kind"] for item in intents]
    assert kinds.count("power_need_title") == kinds.count("signal_adjudication") == 3
    by_job = {item["job_id"]: item for item in intents}
    for result in receipt["results"]:
        intent = by_job[result["job_id"]]
        assert result.get("phase") == "completed_fixed_job"
        assert result.get("status") == "COMPLETED" and result.get("actual_cost_usd") is None
        assert result.get("logical_call_id") and result.get("fingerprint") == intent["fingerprint"]
        reservation = Decimal(result["reservation_usd"])
        assert Decimal(0) < reservation <= Decimal("0.01")
        if intent["kind"] == "power_need_title":
            assert isinstance(result.get("title"), str) and result["title"].strip()
            assert isinstance(result.get("citations"), list) and result["citations"]
        else:
            assert result.get("model") == "jev-1.13.0"
            assert result.get("cost_basis") == "ESTIMATE" and reservation == Decimal("0.01")
            assert isinstance(result.get("dimensions"), dict) and len(result["dimensions"]) == 6
    assert six_gate.get("image") == images["api"]
    authorization_path = INPUTS / "title02-authorization-20261020.json"
    authorization = json.loads(checked_file(authorization_path, AUTHORIZATION_SHA256))
    assert gate.get("authorization_sha256") == sha256(authorization_path.read_bytes())
    return gate, manifest, intents, receipt, rollout, expected_compose_sha


def inspect_containers(expected_images: dict[str, str]) -> tuple[dict[str, dict], dict[str, dict[str, str]], str]:
    names = [CONTAINER_NAMES[name] for name in (*SERVICE_NAMES, "web", "db")]
    inspected = json.loads(private_run(["docker", "inspect", *names]))
    containers = {item["Name"].lstrip("/"): item for item in inspected}
    assert set(containers) == set(names) and all(item["State"]["Running"] for item in inspected)
    for service in (*SERVICE_NAMES, "web"):
        expected = expected_images["web" if service == "web" else "api"]
        container = containers[CONTAINER_NAMES[service]]
        assert container["Image"] == expected, "Running service is not the approved candidate image"
        label = private_run(
            ["docker", "image", "inspect", expected, "--format", '{{index .Config.Labels "org.opencontainers.image.revision"}}']
        ).decode().strip()
        assert label == REVISION
    db = containers[CONTAINER_NAMES["db"]]
    db_mounts = [
        mount
        for mount in db["Mounts"]
        if mount.get("Name") == "gridlens_postgres-data"
        and mount.get("Type") == "volume"
        and mount.get("Destination") == "/var/lib/postgresql"
    ]
    assert len(db_mounts) == 1, "Canonical database volume is not the reviewed volume"
    db_env = dict(pair.split("=", 1) for pair in db["Config"]["Env"] if "=" in pair)
    assert Path(db_env["PGDATA"]).is_relative_to(Path("/var/lib/postgresql"))
    service_envs = {
        service: dict(pair.split("=", 1) for pair in containers[CONTAINER_NAMES[service]]["Config"]["Env"] if "=" in pair)
        for service in (*SERVICE_NAMES, "web")
    }
    database_urls = [service_envs[name].get("DATABASE_URL", "") for name in ("api", "worker", "browse")]
    assert all(value == database_urls[0] for value in database_urls)
    parsed = urlsplit(database_urls[0])
    assert parsed.scheme == "postgresql+psycopg" and parsed.hostname == "db" and parsed.port == 5432
    assert parsed.username == "gridlens" and parsed.path == "/" + DB_NAME
    assert not parsed.query and not parsed.fragment
    assert all(containers[CONTAINER_NAMES[name]]["HostConfig"]["NetworkMode"] == "gridlens_default" for name in (*SERVICE_NAMES, "web"))
    data_directory = query("SHOW data_directory")
    assert data_directory == db_env["PGDATA"]
    data_path = Path(data_directory)
    volume_path = Path(db_mounts[0]["Destination"])
    assert data_path.is_relative_to(volume_path), "Effective PostgreSQL data directory is outside canonical volume"
    assert not any(
        mount is not db_mounts[0]
        and Path(data_directory).is_relative_to(Path(mount.get("Destination", "/__no_match__")))
        for mount in db["Mounts"]
    ), "Effective PostgreSQL data directory is shadowed by another mount"
    return containers, service_envs, sha256(database_urls[0].encode())


def settings_probe(container_name: str) -> dict:
    code = r'''
import json
from gridlens.settings import settings
names = [
    "power_need_titles_enabled", "saved_browse_enabled", "worker_auto_refresh",
    "intelligence_enabled", "intelligence_mode", "intelligence_enabled_contracts",
    "intelligence_openai_enabled", "intelligence_typesafe_enabled", "jev_enabled",
    "openai_brief_model", "intelligence_openai_reasoning_model",
    "intelligence_openai_reasoning_priced_model_id", "intelligence_openai_reasoning_pricing_verified",
    "intelligence_openai_reasoning_input_usd_per_million",
    "intelligence_openai_reasoning_output_usd_per_million", "intelligence_max_active_calls",
    "intelligence_max_call_usd", "intelligence_typesafe_model",
    "intelligence_typesafe_priced_model_id", "intelligence_typesafe_pricing_verified",
    "intelligence_typesafe_input_usd_per_million", "intelligence_typesafe_output_usd_per_million",
    "intelligence_typesafe_billing_mode", "intelligence_typesafe_billing_model_id",
    "intelligence_typesafe_billing_contract_id", "intelligence_typesafe_billing_policy_id",
    "intelligence_typesafe_billing_reference", "intelligence_typesafe_billing_verified",
    "intelligence_typesafe_total_input_bound_verified",
    "intelligence_typesafe_estimated_reservation_usd",
    "intelligence_typesafe_estimate_observation_ids",
]
for scope in ("global", "provider", "model", "source", "project"):
    for period in ("daily", "monthly"):
        for kind in ("calls", "usd"):
            names.append(f"intelligence_{scope}_{period}_{kind}")
print(json.dumps({name: getattr(settings, name) for name in names}, default=str))
'''
    raw = private_run(["docker", "exec", container_name, "uv", "run", "python", "-c", code], timeout=30)
    return json.loads(raw)


def canonical(value) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def validate_pre_settings(controls: dict[str, dict], activation: dict) -> None:
    expected = {key.lower(): value for key, value in activation["required_unchanged_controls"].items()}
    for service in ("api", "worker"):
        current = controls[service]
        for key, wanted in expected.items():
            assert canonical(current[key]) == wanted, "An existing shared operating control differs"
        assert not current["power_need_titles_enabled"]
        assert not current["intelligence_typesafe_enabled"] and not current["jev_enabled"]
        contracts = current["intelligence_enabled_contracts"].split(",")
        assert "POWER_NEED_TITLE" not in contracts and "SIGNAL_ADJUDICATION" not in contracts
    browse = controls["browse"]
    assert browse["intelligence_enabled"] is False and browse["jev_enabled"] is False
    assert browse["saved_browse_enabled"] is True


def validate_post_settings(controls: dict[str, dict], activation: dict, prior: dict[str, dict]) -> None:
    changes = {key.lower(): value for key, value in activation["runtime_changes"].items()}
    for service in ("api", "worker"):
        current = controls[service]
        for key, wanted in changes.items():
            assert canonical(current[key]) == wanted, "Activated runtime setting does not match proposal"
        for key, wanted in activation["required_unchanged_controls"].items():
            assert canonical(current[key.lower()]) == wanted, "A shared operating control changed"
    for service in ("api", "worker", "browse"):
        current = controls[service]
        for scope in ("global", "provider", "model", "source", "project"):
            for period in ("daily", "monthly"):
                for kind in ("calls", "usd"):
                    key = f"intelligence_{scope}_{period}_{kind}"
                    assert current[key] == prior[service][key], "A narrower budget cap changed"
    assert controls["browse"]["intelligence_enabled"] is False
    assert controls["browse"]["jev_enabled"] is False
    assert controls["browse"]["saved_browse_enabled"] is True
    assert controls["browse"]["power_need_titles_enabled"] is True
    for key in ("intelligence_enabled", "jev_enabled", "saved_browse_enabled"):
        assert controls["browse"][key] == prior["browse"][key]


def write_private_backup(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    os.chmod(path, 0o600)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def patched_runtime(original: bytes, changes: dict[str, str]) -> bytes:
    assert all(re.fullmatch(r"[A-Z][A-Z0-9_]*", key) for key in changes)
    assert not any("KEY" in key or "TOKEN" in key or "SECRET" in key for key in changes)
    lines = original.splitlines(keepends=True)
    counts = {key: 0 for key in changes}
    output = []
    for line in lines:
        if not line.strip() or line.lstrip().startswith(b"#"):
            output.append(line)
            continue
        replaced = False
        for key, value in changes.items():
            match = re.match(rb"^([ \t]*" + key.encode() + rb"[ \t]*=[ \t]*)(.*?)([ \t]+\#[^\r\n]*)?(\r?\n)?$", line)
            if match:
                counts[key] += 1
                assert counts[key] == 1, "Duplicate active runtime variable"
                encoded = json.dumps(value, ensure_ascii=False).encode("utf-8")
                output.append(match.group(1) + encoded + (match.group(3) or b"") + (match.group(4) or b""))
                replaced = True
                break
        if not replaced:
            output.append(line)
    newline = b"\r\n" if b"\r\n" in original else b"\n"
    for key, value in changes.items():
        if counts[key] == 0:
            if output and not output[-1].endswith((b"\n", b"\r")):
                output.append(newline)
            output.append(key.encode() + b"=" + json.dumps(value, ensure_ascii=False).encode("utf-8") + newline)
    return b"".join(output)


def atomic_replace(path: Path, content: bytes, template_stat: os.stat_result) -> None:
    fd, temporary_name = tempfile.mkstemp(prefix=".runtime.env.title02.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.chown(temporary, template_stat.st_uid, template_stat.st_gid)
        os.chmod(temporary, stat.S_IMODE(template_stat.st_mode))
        os.utime(temporary, ns=(template_stat.st_atime_ns, template_stat.st_mtime_ns))
        for name in os.listxattr(path, follow_symlinks=False):
            os.setxattr(temporary, name, os.getxattr(path, name, follow_symlinks=False), follow_symlinks=False)
        os.replace(temporary, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        temporary.unlink(missing_ok=True)


def compose_start(startup_bytes: bytes, services: tuple[str, ...], log_path: Path) -> None:
    source = startup_bytes.decode("utf-8")
    anchor = "'up', '-d', '--no-build'"
    assert source.count(anchor) == 1, "Existing Infisical startup command changed"
    replacement = "'--profile', 'saved-browse', " + anchor + ", '--no-deps', " + ", ".join(
        repr(name) for name in services
    )
    transformed = source.replace(anchor, replacement)
    with log_path.open("ab") as log:
        process = subprocess.Popen(
            ["python3", "-"], stdin=subprocess.PIPE, stdout=log,
            stderr=subprocess.STDOUT, cwd="/opt/gridlens", start_new_session=True,
        )
        interrupted = False
        try:
            try:
                assert process.stdin is not None
                process.stdin.write(transformed.encode())
            except KeyboardInterrupt:
                interrupted = True
            finally:
                if process.stdin is not None and not process.stdin.closed:
                    try:
                        process.stdin.close()
                    except KeyboardInterrupt:
                        interrupted = True
            while True:
                try:
                    return_code = process.wait()
                    break
                except KeyboardInterrupt:
                    # Do not begin recovery while startup/Compose may still be
                    # applying service state. Wait until child completion is known.
                    interrupted = True
        except BaseException:
            # A non-interrupt Python error during I/O also must not race recovery
            # with the detached process group.
            while process.poll() is None:
                try:
                    process.wait()
                except KeyboardInterrupt:
                    interrupted = True
            raise
        if interrupted:
            raise KeyboardInterrupt
    if return_code:
        raise RuntimeError("Existing Infisical Compose startup failed")


def query(sql: str) -> str:
    return private_run(
        [
            "docker", "exec", "-e",
            "PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=15000",
            CONTAINER_NAMES["db"], "psql", "-U", "gridlens", "-d", DB_NAME,
            "-X", "-At", "-v", "ON_ERROR_STOP=1", "-c", sql,
        ],
        timeout=30,
    ).decode().strip()


def assert_accounting_clear() -> None:
    value = query(
        "SELECT count(*) FROM logical_calls WHERE status IN ('NOT_SENT','RESERVED','SENT_OUTCOME_UNKNOWN') "
        "OR coalesce(blocked_reason,'') LIKE 'BILLING_QUARANTINE:%'"
    )
    assert value == "0", "Active, unknown, or quarantined logical call exists"


def drain_and_stop_worker(log_path: Path) -> None:
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        with log_path.open("ab") as log:
            fence = subprocess.Popen(
                ["docker", "exec", "-i", CONTAINER_NAMES["db"], "psql", "-U", "gridlens", "-d", DB_NAME,
                 "-X", "-A", "-t", "-q", "-v", "ON_ERROR_STOP=1"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True,
            )
            try:
                fence.stdin.write(
                    "BEGIN; SET LOCAL lock_timeout='2000ms'; LOCK TABLE jobs IN SHARE MODE; "
                    "SELECT count(*)::text FROM jobs WHERE status='running';\n"
                )
                fence.stdin.flush()
                running = fence.stdout.readline().strip()
                if not running.isdigit():
                    raise RuntimeError("Could not establish a fenced worker drain")
                if running == "0":
                    with log_path.open("ab") as stop_log:
                        stopped = subprocess.run(
                            ["docker", "stop", "--timeout", "15", CONTAINER_NAMES["worker"]],
                            stdout=stop_log, stderr=subprocess.STDOUT, timeout=30,
                        )
                    if stopped.returncode:
                        raise RuntimeError("Worker stop failed under drain fence")
                    state = json.loads(private_run(["docker", "inspect", CONTAINER_NAMES["worker"]]))[0]
                    assert not state["State"]["Running"]
                    return
            finally:
                if fence.poll() is None:
                    fence.communicate("ROLLBACK;\n\\q\n", timeout=10)
        time.sleep(3)
    raise TimeoutError("Worker did not become idle under fenced drain")


def stop_api_and_browse(log_path: Path) -> None:
    with log_path.open("ab") as log:
        for service in ("api", "browse"):
            result = subprocess.run(
                ["docker", "stop", "--timeout", "15", CONTAINER_NAMES[service]],
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=30,
            )
            if result.returncode:
                raise RuntimeError("Could not stop policy writer: " + service)


def wait_ready(log_path: Path, started_at: float) -> None:
    with log_path.open("ab") as log:
        private_run(["docker", "exec", CONTAINER_NAMES["web"], "nginx", "-t"])
        subprocess.run(["docker", "exec", CONTAINER_NAMES["web"], "nginx", "-s", "reload"], stdout=log, stderr=subprocess.STDOUT, check=True, timeout=30)
        for _ in range(60):
            probe = subprocess.run(
                ["docker", "exec", CONTAINER_NAMES["web"], "wget", "-qO-", "http://api:8000/health/ready"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
            )
            if probe.returncode == 0:
                try:
                    if json.loads(probe.stdout).get("readiness") == "READY":
                        break
                except (json.JSONDecodeError, AttributeError):
                    pass
            time.sleep(1)
        else:
            raise RuntimeError("API readiness unavailable")
    heartbeat = query(
        "SELECT coalesce(bool_or(last_seen_at>=to_timestamp(" + str(started_at) + ") "
        "AND last_seen_at>now()-interval '30 seconds'),false)::text FROM worker_heartbeats"
    )
    assert heartbeat == "true", "Fresh worker heartbeat unavailable"


def verify_persisted_six_intents(
    intents: list[dict], scope: dict, completed: list[dict]
) -> None:
    # Recheck source currency and bind each journal result to persisted ledger,
    # checkpoint, title version or Jev decision. Emit no source or credential data.
    import_code = r'''
import json, sys
from decimal import Decimal
from uuid import UUID
from sqlalchemy import select
from gridlens.persistence.database import SessionLocal
from gridlens.persistence.models import (Evidence, Interpretation, Job, LogicalCall,
    Observation, PowerNeed, PowerNeedTitle, PowerNeedTitleVersion, Project,
    SignalDecision, Source)
from gridlens.intelligence import signal_adjudication as signals
from gridlens.intelligence import titles
payload = json.load(sys.stdin)
completed = {item["job_id"]: item for item in payload["completed"]}
with SessionLocal() as session:
    assert not session.scalar(select(LogicalCall.id).where(
        LogicalCall.status.in_(["NOT_SENT", "RESERVED", "SENT_OUTCOME_UNKNOWN"])).limit(1))
    assert not session.scalar(select(LogicalCall.id).where(
        LogicalCall.blocked_reason.like("BILLING_QUARANTINE:%")).limit(1))
    assert not session.scalar(select(Job.id).where(
        Job.kind.in_(["power_need_title", "signal_adjudication"]),
        Job.status.in_(["queued", "running"])).limit(1))
    for intent in payload["intents"]:
        result = completed[intent["job_id"]]
        job = session.get(Job, UUID(intent["job_id"]))
        assert job and job.status == "succeeded" and not job.error
        checkpoint = json.loads(job.checkpoint or "{}")
        call = session.get(LogicalCall, UUID(result["logical_call_id"]))
        assert call and call.status == "COMPLETED" and call.actual_cost_usd is None
        assert checkpoint.get("logical_call_id") == str(call.id)
        assert job.kind == intent["kind"] and str(job.target_id) == intent["target_id"]
        assert call.job_id == job.id and call.fingerprint == intent["fingerprint"]
        assert call.provider == intent["provider"] and call.model == intent["model"]
        assert call.context_digest == intent["context_digest"]
        assert call.evidence_digest == intent["evidence_digest"]
        assert call.max_cost_usd == Decimal(result["reservation_usd"])
        assert call.blocked_reason is None
        assert result["phase"] == "completed_fixed_job" and result["status"] == call.status
        assert result["provider"] == call.provider and result["model"] == call.model
        assert result["fingerprint"] == call.fingerprint and result["actual_cost_usd"] is None
        record = next(item for item in payload["scope"]["records"]
                      if item["need_id"] == intent["target_id"]
                      or item["observation_id"] == intent["target_id"])
        observation = session.get(Observation, UUID(record["observation_id"]))
        evidence = session.get(Evidence, UUID(record["evidence_id"]))
        need = session.get(PowerNeed, UUID(record["need_id"]))
        project = session.get(Project, UUID(record["project_id"]))
        source = session.get(Source, record["source_id"])
        interpretation = session.scalar(select(Interpretation).where(
            Interpretation.observation_id == UUID(record["observation_id"])))
        assert all((observation, evidence, need, project, source, interpretation))
        assert source.enabled and source.registry_enabled and need.active
        assert observation.source_id == source.id and evidence.observation_id == observation.id
        assert observation.content_hash == evidence.content_hash == record["content_hash"]
        assert evidence.url == record["url"] and project.source_id == source.id
        assert need.project_id == project.id and project.external_id == observation.external_id
        assert interpretation.status == "accepted" and interpretation.content_hash == record["content_hash"]
        assert interpretation.assessment.get("evidence_hash") == record["content_hash"]
        title_payload, title_evidence = titles.title_input(session, need.id)
        assert set(title_evidence) == {str(evidence.id)}
        role_options = titles._role_options(title_evidence)
        activity_options = titles._activity_options(title_evidence)
        assert activity_options
        title_request = titles.title_request_payload(
            title_payload, title_evidence, role_options, activity_options)
        if intent["kind"] == "power_need_title":
            assert titles.digest(title_payload) == intent["input_fingerprint"]
            assert titles.digest(title_request) == intent["request_sha256"]
            version = session.scalar(select(PowerNeedTitleVersion).where(
                PowerNeedTitleVersion.need_id == need.id,
                PowerNeedTitleVersion.input_fingerprint == intent["input_fingerprint"]))
            current_title = session.get(PowerNeedTitle, need.id)
            assert version and version.result and version.citations
            assert current_title and current_title.status == "ready"
            assert result["title"] == version.result["title"]
            assert result["citations"] == version.citations
        else:
            assert checkpoint.get("logical_call_policy") == intent["billing_policy"]
            assert call.max_cost_usd == Decimal("0.01")
            assert call.result_payload["usage_estimate_policy"]["hard_bound_verified"] is False
            signal_state = signals._evidence_state(session, observation, evidence)
            jev_request = signals.jev_request_payload(signal_state, model="jev-1.13.0")
            assert titles.digest(jev_request) == intent["request_sha256"]
            anchor = session.scalar(select(Project).where(
                Project.source_id == observation.source_id,
                Project.external_id == observation.external_id))
            assert anchor and anchor.id == project.id
            decision = session.scalar(select(SignalDecision).where(
                SignalDecision.observation_id == observation.id,
                SignalDecision.content_hash == intent["content_hash"],
                SignalDecision.policy_version == intent["policy_version"],
                SignalDecision.source == "jev"))
            assert decision and decision.model_version == "jev-1.13.0"
            assert result["decision"] == decision.decision
            assert result["dimensions"] == decision.dimensions
print(json.dumps({"persisted_initial_jobs": len(payload["intents"]), "passed": True}))
'''
    data = json.dumps({"intents": intents, "completed": completed, "scope": scope}).encode()
    raw = private_run(
        ["docker", "exec", "-i", CONTAINER_NAMES["api"], "uv", "run", "python", "-c", import_code],
        input_bytes=data,
        timeout=60,
    )
    result = json.loads(raw)
    assert result == {"persisted_initial_jobs": 6, "passed": True}


def main() -> int:
    scope_path = INPUTS / "title02-jev-proposed-scope.json"
    activation_path = INPUTS / "title02-proposed-activation.json"
    scope = json.loads(checked_file(scope_path, SCOPE_SHA256))
    activation = json.loads(checked_file(activation_path, ACTIVATION_SHA256))
    release_gate_path = RELEASE_ROOT / "continuing-activation-gate.json"
    gate, git_manifest, intents, receipt, rollout, candidate_compose_sha = validate_release_gate(
        release_gate_path, scope, activation
    )
    release_gate_bytes = release_gate_path.read_bytes()
    six_receipt_fields = gate["six_intent_receipt"]
    report_path = ACTIVATION_CONTROL / "host-receipt.json"
    assert not ACTIVATION_CONTROL.exists(), "Prior activation attempt exists; inspect its receipt first"
    ACTIVATION_CONTROL.mkdir(mode=0o700)
    log_path = ACTIVATION_CONTROL / "host-private.log"
    log_fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(log_fd)
    report = {
        "candidate_revision": REVISION,
        "full_candidate": git_manifest["full_candidate"],
        "api_image": gate["images"]["api"],
        "web_image": gate["images"]["web"],
        "scope_sha256": SCOPE_SHA256,
        "activation_sha256": ACTIVATION_SHA256,
        "authorization_sha256": AUTHORIZATION_SHA256,
        "activation_controller_sha256": gate["activation_controller_sha256"],
        "release_gate_sha256": sha256(release_gate_bytes),
        "rollout_receipt_sha256": gate["rollout_receipt_sha256"],
        "candidate_compose_sha256": candidate_compose_sha,
        "six_intent_receipt_sha256": six_receipt_fields["host_receipt_sha256"],
        "six_intent_journal_sha256": six_receipt_fields["journal_sha256"],
        "six_intent_gate_sha256": six_receipt_fields["gate_sha256"],
        "started_at": datetime.now(UTC).isoformat(),
        "runtime_changed": False,
        "services_stopped": [],
        "services_recreated": [],
        "passed": False,
    }
    runtime_path = HOST_ROOT / "runtime.env"
    original_runtime = b""
    original_metadata = None
    applied_runtime_sha = None
    runtime_changed = False
    runtime_apply_attempted = False
    services_may_be_stopped = False
    lock_fd = None
    previous_containers = {}
    previous_settings = {}
    try:
        lock_fd = os.open(LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.chmod(LOCK_PATH, 0o600)

        compose_path = HOST_ROOT / "compose.app.yaml"
        startup_path = HOST_ROOT / "start-gridlens.py"
        assert compose_path.is_file() and not compose_path.is_symlink()
        current_compose_text = compose_path.read_text(encoding="utf-8")
        assert sha256(current_compose_text.encode("utf-8")) == candidate_compose_sha
        assert current_compose_text == candidate_compose_text(
            Path(rollout["prior_compose"]).read_text(encoding="utf-8"), REVISION
        )
        startup_bytes = checked_file(startup_path, STARTUP_SHA256)
        original_metadata = runtime_path.stat(follow_symlinks=False)
        assert stat.S_ISREG(original_metadata.st_mode) and not runtime_path.is_symlink()
        original_runtime = checked_file(runtime_path, RUNTIME_SHA256)
        changes = activation["runtime_changes"]
        assert not (set(changes) & set(activation["required_unchanged_controls"]))
        assert not any("KEY" in key or "SECRET" in key or "TOKEN" in key for key in changes)
        proposed_runtime = patched_runtime(original_runtime, changes)
        report["runtime_before_sha256"] = sha256(original_runtime)
        report["runtime_after_sha256"] = sha256(proposed_runtime)

        # Compose is parsed in memory only; secret-bearing config output is never
        # written or printed. Verify the runtime.env backend anchor and preserve
        # browse's explicit disabled intelligence overrides.
        config_raw = private_run(
            ["docker", "compose", "-f", str(compose_path), "--env-file", str(runtime_path),
             "config", "--no-env-resolution", "--no-interpolate", "--format", "json"],
            timeout=60,
        )
        compose_config = json.loads(config_raw)
        assert all(name in compose_config["services"] for name in (*SERVICE_NAMES, "web", "db"))
        browse_environment = compose_config["services"]["browse"].get("environment", {})
        assert canonical(browse_environment.get("INTELLIGENCE_ENABLED", "")).lower() == "false"
        assert canonical(browse_environment.get("JEV_ENABLED", "")).lower() == "false"
        assert "runtime.env" in json.dumps(compose_config["services"]["api"].get("env_file", []))
        assert "runtime.env" in json.dumps(compose_config["services"]["worker"].get("env_file", []))
        assert "runtime.env" in json.dumps(compose_config["services"]["browse"].get("env_file", []))
        assert compose_config["services"]["api"].get("image") == compose_config["services"]["worker"].get("image")
        assert compose_config["services"]["worker"].get("image") == compose_config["services"]["browse"].get("image")
        assert compose_config["services"]["api"].get("image") == "gridlens-api:title02-" + REVISION[:12]
        assert compose_config["services"]["web"].get("image") == "gridlens-web:title02-" + REVISION[:12]

        previous_containers, service_envs, database_url_sha = inspect_containers(gate["images"])
        report["database_url_sha256"] = database_url_sha
        previous_settings = {service: settings_probe(CONTAINER_NAMES[service]) for service in SERVICE_NAMES}
        validate_pre_settings(previous_settings, activation)
        for service in SERVICE_NAMES:
            assert service_envs[service]["DATABASE_URL"] == service_envs["api"]["DATABASE_URL"]
        assert query("SELECT version_num FROM alembic_version") == "0032_power_need_titles"
        assert query("SELECT current_database()") == DB_NAME
        assert query("SELECT count(*) FROM jobs WHERE status='running'") == "0"
        assert_accounting_clear()
        verify_persisted_six_intents(intents, scope, receipt["results"])
        report["initial_six_intents_persisted"] = True
        report["preactivation_settings_verified"] = True

        backup = ACTIVATION_CONTROL / "runtime.env.pre-activation.bak"
        write_private_backup(backup, original_runtime)
        report["runtime_backup_sha256"] = sha256(backup.read_bytes())
        assert report["runtime_backup_sha256"] == report["runtime_before_sha256"]

        services_may_be_stopped = True
        stop_api_and_browse(log_path)
        report["services_stopped"].extend(("api", "browse"))
        drain_and_stop_worker(log_path)
        report["services_stopped"].append("worker")
        assert query("SELECT count(*) FROM jobs WHERE status='running'") == "0"
        assert_accounting_clear()
        assert query(
            "SELECT count(*) FROM jobs WHERE kind IN ('power_need_title','signal_adjudication') "
            "AND status IN ('queued','running')"
        ) == "0", "Unvalidated title/Jev work is queued; refusing feature activation"

        runtime_apply_attempted = True
        applied_runtime_sha = sha256(proposed_runtime)
        atomic_replace(runtime_path, proposed_runtime, original_metadata)
        runtime_changed = True
        assert applied_runtime_sha == sha256(proposed_runtime)
        report["runtime_changed"] = True

        start_time = time.time()
        compose_start(startup_bytes, SERVICE_NAMES, log_path)
        report["services_recreated"] = list(SERVICE_NAMES)
        wait_ready(log_path, start_time)
        current_containers, current_envs, current_url_sha = inspect_containers(gate["images"])
        assert current_url_sha == database_url_sha
        for name in ("web", "db"):
            assert current_containers[CONTAINER_NAMES[name]]["Id"] == previous_containers[CONTAINER_NAMES[name]]["Id"]
        current_settings = {service: settings_probe(CONTAINER_NAMES[service]) for service in SERVICE_NAMES}
        validate_post_settings(current_settings, activation, previous_settings)
        assert_accounting_clear()
        verify_persisted_six_intents(intents, scope, receipt["results"])
        report["postactivation_settings_verified"] = True
        report["postactivation_six_intents_persisted"] = True
        report["api_worker_browse_candidate_images_verified"] = True
        report["database_volume_and_url_unchanged"] = True
        report["fresh_worker_heartbeat"] = True
        report["nginx_validated_and_reloaded"] = True
        report["passed"] = True
    except BaseException as error:
        report["error_type"] = type(error).__name__
        report["private_log"] = str(log_path)
        report["passed"] = False
        runtime_safe_to_start = not runtime_apply_attempted
        recovery_services_stopped = False
        recovery_restart_safe = False
        if services_may_be_stopped:
            try:
                # Stop public admissions first. Then drain the activated worker
                # under the same SHARE fence before touching runtime policy.
                stop_api_and_browse(log_path)
                drain_and_stop_worker(log_path)
                recovery_services_stopped = True
                assert query("SELECT count(*) FROM jobs WHERE status='running'") == "0"
                assert_accounting_clear()
                assert query(
                    "SELECT count(*) FROM jobs WHERE kind IN ('power_need_title','signal_adjudication') "
                    "AND status IN ('queued','running')"
                ) == "0", "Unfinished feature work requires operator recovery"
                recovery_restart_safe = True
            except Exception as drain_error:
                report["rollback_drain_error_type"] = type(drain_error).__name__
        # Roll back only this process's exact runtime bytes. Never replace a
        # concurrently edited file and never mutate/cancel/replay database rows.
        if runtime_apply_attempted and recovery_services_stopped:
            try:
                assert original_metadata is not None
                current_runtime_sha = sha256(runtime_path.read_bytes())
                if current_runtime_sha == report["runtime_before_sha256"]:
                    report["runtime_restored"] = True
                else:
                    assert current_runtime_sha == applied_runtime_sha, "Runtime changed concurrently; refusing overwrite"
                    atomic_replace(runtime_path, original_runtime, original_metadata)
                    report["runtime_restored"] = sha256(runtime_path.read_bytes()) == report["runtime_before_sha256"]
                assert report["runtime_restored"]
                runtime_safe_to_start = True
            except Exception as restore_error:
                report["runtime_restore_error_type"] = type(restore_error).__name__
                runtime_safe_to_start = False
        # Restart only the same approved candidate images and unchanged Compose
        # bytes. If image state or configuration cannot be proven, leave stopped.
        if services_may_be_stopped and runtime_safe_to_start and recovery_restart_safe:
            try:
                assert sha256(compose_path.read_text(encoding="utf-8").encode("utf-8")) == candidate_compose_sha
                assert sha256(startup_path.read_bytes()) == STARTUP_SHA256
                current = json.loads(private_run(["docker", "inspect", *[CONTAINER_NAMES[n] for n in SERVICE_NAMES]]))
                by_name = {item["Name"].lstrip("/"): item for item in current}
                for service in SERVICE_NAMES:
                    item = by_name[CONTAINER_NAMES[service]]
                    assert item["Image"] == gate["images"]["api"]
                compose_start(startup_path.read_bytes(), SERVICE_NAMES, log_path)
                wait_ready(log_path, time.time())
                restored, _, _ = inspect_containers(gate["images"])
                assert all(restored[CONTAINER_NAMES[s]]["State"]["Running"] for s in SERVICE_NAMES)
                report["same_candidate_services_recovered"] = True
            except Exception as recovery_error:
                report["service_recovery_error_type"] = type(recovery_error).__name__
                report["services_may_remain_stopped"] = True
        elif services_may_be_stopped:
            report["services_may_remain_stopped"] = True
            report["service_recovery_blocked"] = "Runtime restoration or fenced drain could not be proven safe"
    finally:
        report["finished_at"] = datetime.now(UTC).isoformat()
        report["database_mutated_by_controller"] = False
        report["continuing_public_scope_authorized"] = True
        try:
            fd, temp_name = tempfile.mkstemp(prefix=".host-receipt.", dir=ACTIVATION_CONTROL)
            temp = Path(temp_name)
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump(report, output, indent=2, sort_keys=True)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temp, 0o600)
            os.replace(temp, report_path)
            dir_fd = os.open(ACTIVATION_CONTROL, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
            print(json.dumps({"passed": report["passed"], "receipt": str(report_path), "error_type": report.get("error_type")}))
        except Exception:
            print(json.dumps({"passed": False, "receipt_written": False, "error_type": "ReceiptWriteError"}))
            report["passed"] = False
        if lock_fd is not None:
            os.close(lock_fd)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
