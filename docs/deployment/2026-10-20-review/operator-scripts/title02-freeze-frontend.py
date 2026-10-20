"""Bind frontend validation to exact source bytes without generated build output."""
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

task = Path(__file__).resolve().parent
repo = task / "gl3-title-enrichment"
manifest = task / "title02-frontend-frozen.json"
paths = subprocess.check_output(
    ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "web"], cwd=repo
).decode().split("\0")
hashes = {p: hashlib.sha256((repo / p).read_bytes()).hexdigest()
          for p in sorted(set(paths)) if p and (repo / p).is_file()}
candidate = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
if sys.argv[1:] == ["--verify"]:
    expected = json.loads(manifest.read_text(encoding="utf-8-sig"))
    assert hashes == expected["files"], "Frontend changed after freeze"
else:
    assert not sys.argv[1:]
    manifest.write_text(json.dumps({"frozen_at": datetime.now(UTC).isoformat(),
                                   "candidate": candidate, "files": hashes}, indent=2))
print(json.dumps({"candidate": candidate, "verified": sys.argv[1:] == ["--verify"]}))
