"""Inspect only the existing GL3 isolated test resources; no mutation."""
import json
import shutil
import subprocess

container = json.loads(subprocess.check_output([
    "docker", "inspect", "gridlens-map-publication-test-db"
], text=True))[0]
image = json.loads(subprocess.check_output([
    "docker", "image", "inspect", "gridlens-test:candidate-f8b13dd"
], text=True))[0]
print(json.dumps({
    "test_database": {
        "name": container["Name"],
        "running": container["State"]["Running"],
        "network": container["HostConfig"]["NetworkMode"],
        "mounts": [{key: mount.get(key) for key in ("Source", "Destination", "RW")}
                   for mount in container["Mounts"]],
    },
    "test_image": {"id": image["Id"], "created": image["Created"]},
    "disk_free_bytes": shutil.disk_usage("/opt/gridlens").free,
}))
