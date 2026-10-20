"""Run a zero-write, zero-network preflight against the restored GL3 test database."""
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

candidate = sys.argv[1]
assert len(candidate) == 64 and all(c in "0123456789abcdef" for c in candidate)
source = Path("/opt/gridlens/releases") / ("title02-test-" + candidate[:12])
assert (source / "backend/src/gridlens/intelligence/titles.py").is_file()
inputs = Path("/tmp/title02-scope-preflight")
manifest = json.loads((inputs / "manifest.json").read_text())
for name, expected in manifest.items():
    assert name in {"title02-scoped-readonly-preflight.py", "title02-jev-proposed-scope.json",
                    "title02-proposed-activation.json"}
    assert hashlib.sha256((inputs / name).read_bytes()).hexdigest() == expected
pg = "gridlens-map-publication-test-db"
state = json.loads(subprocess.check_output(["docker", "inspect", pg], text=True))[0]
assert state["HostConfig"]["NetworkMode"] == "none" and not state["State"]["Running"]
socket = Path("/opt/gridlens/performance/map-publication-20261019/socket")
assert any(m["Source"] == str(socket) and m["Destination"] == "/isolated-pg"
           for m in state["Mounts"])
environment = {
    "DATABASE_URL": "postgresql+psycopg://postgres@/title02_retained_migration_20261019?host=/isolated-pg",
    "APP_PASSWORD_HASH": "non-authenticating-synthetic-preflight-only",
    "SESSION_SECRET": "title02-readonly-restored-preflight-only",
    "PYTHONPATH": "/workspace/backend/src", "PYTHONDONTWRITEBYTECODE": "1",
    "OPENAI_API_KEY": "", "TYPESAFE_API_KEY": "", "FIRECRAWL_API_KEY": "",
    "INTELLIGENCE_ENABLED": "false", "INTELLIGENCE_MODE": "disabled",
}
try:
    subprocess.run(["docker", "start", pg], check=True, stdout=subprocess.DEVNULL)
    for _ in range(30):
        if subprocess.run(["docker", "exec", pg, "pg_isready", "-h", "/isolated-pg", "-U", "postgres"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            break
        time.sleep(1)
    else:
        raise RuntimeError("Isolated test PostgreSQL did not become ready")
    command = ["docker", "run", "--rm", "--network", "none", "--cpus", "1", "--memory", "2g",
               "-v", str(socket) + ":/isolated-pg", "-v", str(source) + ":/workspace:ro",
               "-v", str(inputs) + ":/preflight:ro", "-w", "/workspace/backend"]
    for key in environment:
        command += ["-e", key]
    command += ["sha256:fd9f8d786b37a2a8e6afcfd0526443fb43310e2875623b8431efa8cda7bae628",
                "/app/backend/.venv/bin/python", "/preflight/title02-scoped-readonly-preflight.py",
                "/preflight/title02-jev-proposed-scope.json", "/preflight/title02-proposed-activation.json"]
    result = subprocess.run(command, env={**os.environ, **environment}, capture_output=True,
                            text=True, timeout=60)
    if result.returncode:
        sys.stderr.write(result.stderr)
        raise RuntimeError("Restored-scope preflight failed")
    receipt = json.loads(result.stdout)
    receipt.update({"backend_candidate": candidate, "network": "none", "input_hashes": manifest})
finally:
    subprocess.run(["docker", "stop", "--timeout", "15", pg], check=True, stdout=subprocess.DEVNULL)
receipt["test_database_stopped"] = True
print(json.dumps(receipt))
