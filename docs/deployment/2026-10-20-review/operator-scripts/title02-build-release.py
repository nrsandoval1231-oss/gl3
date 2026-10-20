"""Build exact committed GL3 blobs without replacing any running container."""
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
from pathlib import Path

revision, expected = sys.argv[1:]
assert re.fullmatch("[0-9a-f]{40}", revision) and re.fullmatch("[0-9a-f]{64}", expected)
archive = Path("/tmp") / ("gridlens-title02-" + revision[:12] + ".tar.gz")
assert hashlib.sha256(archive.read_bytes()).hexdigest() == expected
manifest = json.loads((Path("/tmp") / ("title02-" + revision[:12] + "-git-manifest.json")).read_text())
assert manifest["revision"] == revision and manifest["archive_sha256"] == expected
entries = {entry["path"]: entry for entry in manifest["entries"]}
root = Path("/opt/gridlens/releases") / ("title02-" + revision[:12])
root.mkdir(mode=0o700)
with tarfile.open(archive) as incoming:
    files = {member.name: member for member in incoming.getmembers() if member.isfile()}
    assert set(files) == set(entries), "Archive file set differs from Git tree"
    for member in incoming.getmembers():
        assert (root / member.name).resolve().is_relative_to(root.resolve())
        assert not member.issym() and not member.islnk()
        if member.isfile():
            data = incoming.extractfile(member).read()
            assert hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() == entries[member.name]["sha1"]
            assert bool(member.mode & 0o111) == (entries[member.name]["mode"] == "100755")
    incoming.extractall(root, filter="data")
result = {"revision": revision, "source_archive_sha256": expected,
          "exact_git_blobs_and_modes": len(entries), "images": {}, "running_services_changed": False}
for kind in ("api", "web"):
    filename = "backend" if kind == "api" else kind
    tag = "gridlens-" + kind + ":title02-" + revision[:12]
    assert not subprocess.check_output(["docker", "ps", "--filter", "ancestor=" + tag, "-q"], text=True).strip()
    log = root / ("build-" + kind + ".log")
    fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as output:
        built = subprocess.run(["docker", "build", "--label", "org.opencontainers.image.revision=" + revision,
            "-f", str(root / "deploy" / ("Dockerfile." + filename)), "-t", tag, str(root)],
            stdout=output, stderr=subprocess.STDOUT, timeout=1800)
    assert built.returncode == 0, "Image build failed; inspect private build log"
    result["images"][tag] = subprocess.check_output(["docker", "image", "inspect", tag, "--format", "{{.Id}}"], text=True).strip()
    print(json.dumps({"built": tag, "image_id": result["images"][tag]}), flush=True)
(root / "build-evidence.json").write_text(json.dumps(result, indent=2))
os.chmod(root / "build-evidence.json", 0o600)
print(json.dumps(result), flush=True)
