"""Synthetic tests against existing network-none GL3 test PostgreSQL only."""
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import time
from datetime import UTC, datetime
from pathlib import Path

archive = Path(sys.argv[1])
archive_hash = sys.argv[2]
candidate = sys.argv[3]
assert len(sys.argv) in (4, 5)
reuse_candidate = sys.argv[4] if len(sys.argv) == 5 else None
assert archive.parent == Path("/tmp") and archive.name.startswith("title02-")
assert hashlib.sha256(archive.read_bytes()).hexdigest() == archive_hash
assert len(candidate) == 64 and all(c in "0123456789abcdef" for c in candidate)
root = Path("/opt/gridlens/releases") / ("title02-test-" + candidate[:12])
root.mkdir(mode=0o700)
with tarfile.open(archive) as incoming:
    for member in incoming.getmembers():
        assert member.name.startswith(("backend/", "config/", "scripts/", "deploy/"))
        assert (root / member.name).resolve().is_relative_to(root.resolve())
        assert not member.issym() and not member.islnk()
    incoming.extractall(root, filter="data")
if reuse_candidate:
    assert len(reuse_candidate) == 64 and all(c in "0123456789abcdef" for c in reuse_candidate)
    prior_root = Path("/opt/gridlens/releases") / ("title02-test-" + reuse_candidate[:12])
    prior_receipt = json.loads((prior_root / "controller-results.json").read_text())
    assert prior_receipt["candidate"] == reuse_candidate
    assert any(r["phase"] == "mypy" and r["exit_code"] == 0 for r in prior_receipt["results"])

    def application_hashes(directory):
        return {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
                for prefix in ("backend", "config", "scripts", "deploy")
                for p in (directory / prefix).rglob("*")
                if p.is_file() and not p.relative_to(directory).as_posix().startswith("backend/tests/")}

    assert application_hashes(prior_root) == application_hashes(root), "Only test changes may reuse mypy"
image = "sha256:fd9f8d786b37a2a8e6afcfd0526443fb43310e2875623b8431efa8cda7bae628"
lock = subprocess.check_output(["docker", "run", "--rm", "--network", "none", "--entrypoint", "cat", image, "/app/backend/uv.lock"])
assert hashlib.sha256((root / "backend/uv.lock").read_bytes().replace(b"\r\n", b"\n")).digest() == hashlib.sha256(lock.replace(b"\r\n", b"\n")).digest()
pg = "gridlens-map-publication-test-db"
info = json.loads(subprocess.check_output(["docker", "inspect", pg], text=True))[0]
assert info["HostConfig"]["NetworkMode"] == "none" and not info["State"]["Running"]
pgroot = Path("/opt/gridlens/performance/map-publication-20261019")
assert any(m["Source"] == str(pgroot / "socket") and m["Destination"] == "/isolated-pg" for m in info["Mounts"])
assert any(m["Source"] == str(pgroot / "pgdata") and m["Destination"] == "/var/lib/postgresql" for m in info["Mounts"])
appdb, testdb = ("title02_" + candidate[:12] + "_" + suffix for suffix in ("app", "test"))
env = {
    "DATABASE_URL": f"postgresql+psycopg://postgres@/{appdb}?host=/isolated-pg",
    "TEST_DATABASE_URL": f"postgresql+psycopg://postgres@/{testdb}?host=/isolated-pg",
    # A migration test replaces its URL query with search_path options; retain
    # the isolated socket route through libpq when that removes query.host.
    "PGHOST": "/isolated-pg",
    "APP_PASSWORD_HASH": "non-authenticating-synthetic-test-only",
    "SESSION_SECRET": "title02-synthetic-isolated-tests-only",
    "PYTHONPATH": "/workspace/backend/src",
    "PYTHONDONTWRITEBYTECODE": "1",
    "MYPY_CACHE_DIR": "/tmp/mypy-cache",
    "INTELLIGENCE_MODE": "disabled", "INTELLIGENCE_ENABLED_CONTRACTS": "",
}
for key in ("WORKER_AUTO_REFRESH", "SAVED_BROWSE_ENABLED", "JEV_ENABLED", "JEV_SHADOW_MODE",
            "INTELLIGENCE_ENABLED", "INTELLIGENCE_OPENAI_ENABLED", "INTELLIGENCE_TYPESAFE_ENABLED",
            "INTELLIGENCE_RESEARCH_ENABLED", "AUTONOMOUS_RESEARCH_ENABLED", "MONITORING_ENABLED",
            "BUYING_CHAIN_PUBLIC_RESEARCH_ENABLED", "POWER_NEED_TITLES_ENABLED"):
    env[key] = "false"
for key in ("OPENAI_API_KEY", "TYPESAFE_API_KEY", "FIRECRAWL_API_KEY"):
    env[key] = ""
results = []
started = datetime.now(UTC).isoformat()
try:
    subprocess.run(["docker", "start", pg], check=True, stdout=subprocess.DEVNULL)
    for _ in range(30):
        if subprocess.run(["docker", "exec", pg, "pg_isready", "-h", "/isolated-pg", "-U", "postgres"], stdout=subprocess.DEVNULL).returncode == 0:
            break
        time.sleep(1)
    else:
        raise RuntimeError("Isolated PostgreSQL not ready")
    for database in (appdb, testdb):
        exists = subprocess.check_output(["docker", "exec", pg, "psql", "-h", "/isolated-pg", "-U", "postgres", "-d", "postgres", "-X", "-At", "-c", "SELECT count(*) FROM pg_database WHERE datname='" + database + "'"], text=True).strip()
        assert exists == "0", "Prior diagnostic database exists; do not overwrite"
        subprocess.run(["docker", "exec", pg, "createdb", "-h", "/isolated-pg", "-U", "postgres", database], check=True)
    commands = [
        ("ruff", ["ruff", "check", "--no-cache", "src", "tests"]),
        ("mypy", ["mypy", "src"]),
        ("migration", ["alembic", "upgrade", "head"]),
        ("migration-repeat", ["alembic", "upgrade", "head"]),
        ("schema-parity", ["alembic", "check"]),
        ("focused-tests", ["pytest", "-q", "--disable-warnings", "-o", "cache_dir=/tmp/pytest-cache", "tests/unit/test_power_need_titles.py", "tests/unit/test_intelligence_processing.py", "tests/integration/test_power_need_title_jobs.py", "tests/integration/test_intelligence_worker_integration.py"]),
        ("backend-tests", ["pytest", "-q", "--disable-warnings", "-o", "cache_dir=/tmp/pytest-cache", "tests"]),
    ]
    for label, arguments in commands:
        if label == "mypy" and reuse_candidate:
            reused = {"phase": label, "exit_code": 0, "elapsed_seconds": 0,
                      "reused_from_identical_application": reuse_candidate}
            results.append(reused)
            print(json.dumps(reused), flush=True)
            continue
        command = ["docker", "run", "--rm", "--name", "gridlens-title02-" + label,
                   "--network", "none", "--cpus", "1", "--memory", "2g", "-w", "/workspace/backend",
                   "-v", str(pgroot / "socket") + ":/isolated-pg", "-v", str(root) + ":/workspace:ro"]
        for key in env:
            command += ["-e", key]
        command += [image, "/app/backend/.venv/bin/" + arguments[0], *arguments[1:]]
        print(json.dumps({"phase": label, "candidate": candidate, "started_at": datetime.now(UTC).isoformat()}), flush=True)
        before = time.monotonic()
        result = subprocess.run(command, env={**os.environ, **env}, timeout=1800)
        results.append({"phase": label, "exit_code": result.returncode, "elapsed_seconds": round(time.monotonic() - before, 3)})
        if result.returncode:
            break
finally:
    subprocess.run(["docker", "stop", "--timeout", "15", pg], check=True, stdout=subprocess.DEVNULL)
    receipt = {"candidate": candidate, "archive_sha256": archive_hash, "started_at": started,
               "finished_at": datetime.now(UTC).isoformat(), "results": results,
               "network": "none", "synthetic_only": True, "test_database_stopped": True,
               "production_database_access": False}
    (root / "controller-results.json").write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt), flush=True)
sys.exit(0 if len(results) == 7 and all(item["exit_code"] == 0 for item in results) else 1)
