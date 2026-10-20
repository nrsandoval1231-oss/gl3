"""End only the redundant isolated test container after exact full CI passed."""
import json
import subprocess

name = "gridlens-title02-backend-tests"
info = json.loads(subprocess.check_output(["docker", "inspect", name], text=True))[0]
assert info["Name"] == "/" + name and info["State"]["Running"]
assert info["Image"] == "sha256:fd9f8d786b37a2a8e6afcfd0526443fb43310e2875623b8431efa8cda7bae628"
assert info["HostConfig"]["NetworkMode"] == "none"
assert any(m["Source"] == "/opt/gridlens/releases/title02-test-8f5d19165ab5" and m["Destination"] == "/workspace" and not m["RW"] for m in info["Mounts"])
assert info["Config"]["Cmd"][0] == "/app/backend/.venv/bin/pytest"
subprocess.run(["docker", "stop", "--timeout", "15", name], check=True, stdout=subprocess.DEVNULL)
print(json.dumps({"stopped_only": name, "reason": "Exact candidate full CI already passed 2212 tests; supplemental single-CPU run is redundant", "production_services_changed": False}))
