"""Freeze backend sources and their checked-in test dependencies into an archive."""
import hashlib
import json
import subprocess
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path

task = Path(__file__).resolve().parent
assert sys.argv[1:] in ([], ["--backend-only"])
backend_only = bool(sys.argv[1:])
repo = task / "gl3-title-enrichment"
paths = subprocess.check_output(
    ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=repo
).decode().split("\0")
test_prefixes = ("backend/", "config/", "scripts/", "deploy/")
files = sorted({p for p in paths if p.startswith(test_prefixes) and (repo / p).is_file()})
assert files and "backend/uv.lock" in files
assert not any(".env" == Path(p).name or ".venv" in Path(p).parts for p in files)
hashes = {p: hashlib.sha256((repo / p).read_bytes()).hexdigest() for p in files}
full_files = sorted({p for p in paths if p.startswith((*test_prefixes, "web/")) and (repo / p).is_file()})
full_hashes = {p: hashlib.sha256((repo / p).read_bytes()).hexdigest() for p in full_files}
full_candidate = hashlib.sha256(json.dumps(full_hashes, sort_keys=True).encode()).hexdigest()
candidate = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
archive = task / f"title02-{candidate[:12]}.tar.gz"
if not archive.exists():
    with tarfile.open(archive, "w:gz") as output:
        for relative in files:
            output.add(repo / relative, arcname=relative, recursive=False)
with tarfile.open(archive) as frozen:
    archived_hashes = {member.name: hashlib.sha256(frozen.extractfile(member).read()).hexdigest()
                       for member in frozen.getmembers()}
assert archived_hashes == hashes, "Archive does not match frozen source hashes"
assert all(hashlib.sha256((repo / p).read_bytes()).hexdigest() == value for p, value in hashes.items()), "Backend changed during freeze"
manifest = {
    "frozen_at": datetime.now(UTC).isoformat(),
    "base": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
    "candidate": candidate, "files": hashes,
    "archive": archive.name, "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
}
if not backend_only:
    assert all(hashlib.sha256((repo / p).read_bytes()).hexdigest() == value for p, value in full_hashes.items()), "Full candidate changed during freeze"
    (task / "title02-full-candidate-manifest.json").write_text(json.dumps({
        "frozen_at": manifest["frozen_at"], "base": manifest["base"],
        "candidate": full_candidate, "backend_candidate": candidate, "files": full_hashes,
    }, indent=2), encoding="utf-8")
(task / "title02-candidate-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
print(json.dumps({**{k: v for k, v in manifest.items() if k != "files"}, "full_candidate": None if backend_only else full_candidate}))
