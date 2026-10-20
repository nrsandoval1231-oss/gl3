"""Export a clean local commit; compare release bytes with the tested manifest."""
import hashlib
import json
import subprocess
import tarfile
from pathlib import Path

root = Path(__file__).resolve().parent
repo = root / "gl3-title-enrichment"
revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
assert not subprocess.check_output(["git", "status", "--porcelain"], cwd=repo, text=True).strip()
frozen = json.loads((root / "title02-full-candidate-manifest.json").read_text())
assert frozen["base"] == revision
entries = []
for record in subprocess.check_output(["git", "ls-tree", "-r", "-z", revision], cwd=repo).split(b"\0"):
    if record:
        metadata, path = record.decode().split("\t", 1)
        mode, kind, sha = metadata.split()
        assert kind == "blob" and mode in ("100644", "100755")
        entries.append({"path": path, "mode": mode, "sha1": sha})
manifest = root / ("title02-" + revision[:12] + "-git-manifest.json")
archive = root / ("gridlens-title02-" + revision[:12] + ".tar.gz")
assert not manifest.exists() and not archive.exists()
subprocess.run(["git", "-c", "core.autocrlf=false", "archive", "--format=tar.gz",
                "--output=" + str(archive), revision], cwd=repo, check=True)
with tarfile.open(archive) as exported:
    release = {member.name: exported.extractfile(member).read()
               for member in exported.getmembers() if member.isfile()}
assert set(release) == {entry["path"] for entry in entries}
for entry in entries:
    data = release[entry["path"]]
    assert hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() == entry["sha1"]
differences = []
for path, expected in frozen["files"].items():
    data = release[path]
    if hashlib.sha256(data).hexdigest() != expected:
        local = (repo / path).read_bytes()
        assert hashlib.sha256(local).hexdigest() == expected
        assert local.replace(b"\r\n", b"\n") == data, "Release differs beyond newline normalization: " + path
        differences.append(path)
manifest.write_text(json.dumps({"revision": revision, "full_candidate": frozen["candidate"],
    "entries": entries, "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
    "newline_normalized_paths": differences}, indent=2), encoding="utf-8")
print(json.dumps({"revision": revision, "git_blobs": len(entries),
    "archive": archive.name, "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
    "newline_normalized_paths": differences}))
