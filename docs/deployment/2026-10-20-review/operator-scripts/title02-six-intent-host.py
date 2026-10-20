"""Host-side admission, idle drain and recovery for the reviewed six-job run.

The permission input must contain real authorization and reviewed hashes. This
wrapper never enables the new contracts in ordinary services or prints secrets.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

if sys.flags.optimize != 0:
    raise RuntimeError("Controller host requires optimization disabled")

revision, permission_path, mode = sys.argv[1:]
assert re.fullmatch("[0-9a-f]{40}", revision)
assert mode in ("preflight", "execute")
permission = json.loads(Path(permission_path).read_text())
assert permission["revision"] == revision
inputs = Path("/opt/gridlens/releases") / ("title02-" + revision[:12]) / "validation-inputs"
release_control = inputs.parent / "validation-control"
names = {name: "gridlens-" + name + "-1" for name in ("api", "worker", "browse", "web", "db")}
containers = {item["Name"].lstrip("/"): item for item in json.loads(
    subprocess.check_output(["docker", "inspect", *names.values()], text=True))}
assert all(item["State"]["Running"] for item in containers.values())
for name in ("api", "worker", "browse", "web"):
    image = permission["images"]["web" if name == "web" else "api"]
    assert containers[names[name]]["Image"] == image, "Running release image mismatch"
    label = subprocess.check_output(["docker", "image", "inspect", image, "--format",
        '{{index .Config.Labels "org.opencontainers.image.revision"}}'], text=True).strip()
    assert label == revision
database = containers[names["db"]]
data_mounts = [m for m in database["Mounts"] if m.get("Name") == "gridlens_postgres-data" and m["Type"] == "volume"]
assert len(data_mounts) == 1 and data_mounts[0]["Destination"] == "/var/lib/postgresql", "Unexpected canonical database volume"
database_env = dict(pair.split("=", 1) for pair in database["Config"]["Env"] if "=" in pair)
assert PurePosixPath(database_env["PGDATA"]).is_relative_to("/var/lib/postgresql")
environments = {name: dict(pair.split("=", 1) for pair in containers[names[name]]["Config"]["Env"] if "=" in pair)
                for name in ("api", "worker")}
for env in environments.values():
    connection = urlsplit(env["DATABASE_URL"])
    assert connection.scheme == "postgresql+psycopg"
    assert connection.hostname == "db" and connection.port == 5432
    assert connection.path == "/gridlens_restore_20261014" and connection.username == "gridlens"
    assert not connection.query and not connection.fragment
    assert env.get("POWER_NEED_TITLES_ENABLED", "false").lower() == "false"
    assert env.get("JEV_ENABLED", "false").lower() == "false"
    assert env.get("INTELLIGENCE_TYPESAFE_ENABLED", "false").lower() == "false"
    assert "POWER_NEED_TITLE" not in env.get("INTELLIGENCE_ENABLED_CONTRACTS", "")
    assert "SIGNAL_ADJUDICATION" not in env.get("INTELLIGENCE_ENABLED_CONTRACTS", "")
api_env = environments["api"]
assert api_env["DATABASE_URL"] == environments["worker"]["DATABASE_URL"]
assert all(api_env.get(key) for key in ("DATABASE_URL", "OPENAI_API_KEY", "TYPESAFE_API_KEY"))
input_hashes = permission["input_hashes"]
expected_names = {"title02-six-intent-controller.py", "title02-jev-proposed-scope.json",
                  "title02-proposed-activation.json", "title02-restored-scope-preflight.json",
                  "title02-" + revision[:12] + "-git-manifest.json"}
assert set(input_hashes) == expected_names
for name, expected in input_hashes.items():
    assert hashlib.sha256((inputs / name).read_bytes()).hexdigest() == expected
assert permission["host_wrapper_sha256"] == hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def query(sql):
    return subprocess.check_output(["docker", "exec", "-e",
        "PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=10000",
        names["db"], "psql", "-U", "gridlens", "-d", "gridlens_restore_20261014",
        "-X", "-At", "-c", sql], text=True, stderr=subprocess.DEVNULL).strip()


assert query("SELECT version_num FROM alembic_version") == "0032_power_need_titles"
actual_pgdata = query("SHOW data_directory")
assert actual_pgdata == database_env["PGDATA"]
assert PurePosixPath(actual_pgdata).is_relative_to(data_mounts[0]["Destination"])
assert not any(m is not data_mounts[0] and PurePosixPath(actual_pgdata).is_relative_to(m["Destination"])
               for m in database["Mounts"])
assert query("SELECT count(*) FROM logical_calls WHERE status IN ('NOT_SENT','SENT_OUTCOME_UNKNOWN')") == "0"
command = ["docker", "run", "--rm", "--name", "gridlens-title02-six-intents", "--network", "gridlens_default",
           "--cpus", "1", "--memory", "2g", "-v", str(inputs) + ":/reviewed:ro"]
for key in api_env:
    command += ["-e", key]
entry = [permission["images"]["api"], "uv", "run", "python", "/reviewed/title02-six-intent-controller.py",
         mode, "/reviewed/title02-jev-proposed-scope.json", "/reviewed/title02-proposed-activation.json",
         "/reviewed/title02-restored-scope-preflight.json"]
if mode == "preflight":
    outcome = subprocess.run(command + entry, env={**os.environ, **api_env}, capture_output=True, text=True)
    assert outcome.returncode == 0, "Live read-only preflight failed; inspect privately"
    receipt = json.loads(outcome.stdout)
    receipt.update(image=permission["images"]["api"], revision=revision, normal_worker_changed=False)
    print(json.dumps(receipt), flush=True)
    raise SystemExit(0)

assert permission["initial_six_public_intents_authorized"] is True
assert isinstance(permission["authorization_evidence"], str) and permission["authorization_evidence"].strip()
assert not release_control.exists(), "Prior execution directory exists; inspect before any further dispatch"
release_control.mkdir(mode=0o700)
log_path = release_control / "host-private.log"
log_fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
report = {"revision": revision, "started_at": datetime.now(UTC).isoformat(),
          "continuing_activation_applied": False, "worker_restarted": False, "passed": False}
worker_stopped = False


def private_run(arguments, **kwargs):
    with log_path.open("ab") as log:
        completed = subprocess.run(arguments, stdout=log, stderr=subprocess.STDOUT, **kwargs)
    assert completed.returncode == 0, "Private controller operation failed"


def controller_state():
    result = subprocess.run(["docker", "inspect", "gridlens-title02-six-intents", "--format", "{{.State.Running}}"],
                            capture_output=True, text=True)
    if result.returncode == 0 and result.stdout.strip() in ("true", "false"):
        return "running" if result.stdout.strip() == "true" else "stopped"
    listed = subprocess.run(["docker", "ps", "-a", "--format", "{{.Names}}"], capture_output=True, text=True)
    if listed.returncode == 0 and "gridlens-title02-six-intents" not in listed.stdout.splitlines():
        return "absent"
    return "unknown"


try:
    os.close(log_fd)
    with log_path.open("ab") as log:
        fence = subprocess.Popen(["docker", "exec", "-i", names["db"], "psql", "-U", "gridlens",
            "-d", "gridlens_restore_20261014", "-X", "-A", "-t", "-q", "-v", "ON_ERROR_STOP=1"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True)
        try:
            fence.stdin.write("BEGIN; SET LOCAL lock_timeout='1000ms'; LOCK TABLE jobs IN SHARE MODE; "
                "SELECT 'DRAIN_READY:' || count(*) FROM jobs WHERE status='running';\n")
            fence.stdin.flush()
            assert fence.stdout.readline().strip() == "DRAIN_READY:0", "Worker not idle"
            private_run(["docker", "stop", "--timeout", "15", names["worker"]])
            worker_stopped = True
        finally:
            if fence.poll() is None:
                fence.communicate("ROLLBACK;\n\\q\n", timeout=10)
    assert query("SELECT count(*) FROM jobs WHERE status='running'") == "0"
    gate = {"revision": revision, "full_candidate": permission["full_candidate"],
            "initial_six_public_intents_authorized": True,
            "authorization_evidence": permission["authorization_evidence"],
            "ordinary_worker_stopped": True, "normal_new_contracts_disabled": True,
            "scope_sha256": input_hashes["title02-jev-proposed-scope.json"],
            "activation_sha256": input_hashes["title02-proposed-activation.json"],
            "controller_sha256": input_hashes["title02-six-intent-controller.py"],
            "preflight_sha256": input_hashes["title02-restored-scope-preflight.json"],
            "git_manifest_sha256": input_hashes["title02-" + revision[:12] + "-git-manifest.json"],
            "image": permission["images"]["api"]}
    gate_path = release_control / "gate.json"
    gate_path.write_text(json.dumps(gate, indent=2))
    os.chmod(gate_path, 0o600)
    command += ["-v", str(release_control) + ":/release-control"]
    entry += ["/release-control/gate.json", "/release-control/title02-six-intents.jsonl",
              "/reviewed/title02-" + revision[:12] + "-git-manifest.json"]
    # No client timeout: killing docker's client could leave the controller alive.
    private_run(command + entry, env={**os.environ, **api_env})
    assert controller_state() in ("stopped", "absent")
    journal = [json.loads(line) for line in (release_control / "title02-six-intents.jsonl").read_text().splitlines()]
    assert journal[-1]["phase"] == "complete" and journal[-1]["six_jobs_passed"]
    report.update(passed=True, results=[event for event in journal if event["phase"] == "completed_fixed_job"])
except BaseException as error:
    report.update(error_type=type(error).__name__, inspect_private_log=str(log_path))
finally:
    try:
        final_controller_state = controller_state()
        report["controller_state"] = final_controller_state
        if worker_stopped and final_controller_state in ("stopped", "absent"):
            current = json.loads(subprocess.check_output(["docker", "inspect", names["worker"]], text=True))[0]
            assert current["Id"] == containers[names["worker"]]["Id"]
            assert current["Image"] == permission["images"]["api"]
            assert current["Config"]["Env"] == containers[names["worker"]]["Config"]["Env"]
            private_run(["docker", "start", names["worker"]])
            report["worker_restarted"] = True
        elif worker_stopped:
            report["worker_remains_stopped"] = "Controller running or unknown; do not overlap normal worker"
            report["passed"] = False
    except Exception as recovery_error:
        report["worker_recovery_error_type"] = type(recovery_error).__name__
        report["passed"] = False
    report["finished_at"] = datetime.now(UTC).isoformat()
    (release_control / "host-receipt.json").write_text(json.dumps(report, indent=2, default=str))
    os.chmod(release_control / "host-receipt.json", 0o600)
    print(json.dumps(report, default=str), flush=True)
raise SystemExit(0 if report["passed"] and report["worker_restarted"] else 1)
