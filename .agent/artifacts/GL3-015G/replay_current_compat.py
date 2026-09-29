from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from verify_rrc_compat import verify_snapshot

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ACCESS = ROOT / ".agent/artifacts/GL3-015G/access.json"
RAW_ROOT = (ROOT / ".artifacts/GL3-015G/raw").resolve()
F_ACCEPTED_SHA256 = "c0215842369f14d6e725b011649ffa0076f373344e3ce5bb0d2ed411fce79cd6"


def replay(access_path: Path = DEFAULT_ACCESS) -> dict[str, Any]:
    access = json.loads(access_path.read_text(encoding="utf-8-sig"))
    pulls = access.get("file_pulls", [])
    if not pulls:
        return {
            "decision": "REDIRECT",
            "current_file_sha256": "UNKNOWN",
            "compatibility": "UNKNOWN",
            "reason": access.get("reason", "no permit attachment bytes were retained"),
            "file_pull_attempts": sum(
                1 for item in access.get("attempts", []) if item.get("method") == "POST" and "permit-" in (item.get("raw_path") or "")
            ),
        }

    checks: dict[str, dict[str, Any]] = {}
    hashes: list[str] = []
    versions: list[tuple[Any, Any]] = []
    for pull in pulls:
        relative = Path(str(pull.get("raw_path", "")))
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(RAW_ROOT) or not path.is_file():
            return {
                "decision": "REDIRECT",
                "current_file_sha256": "UNKNOWN",
                "compatibility": "UNKNOWN",
                "reason": "retained pull path is missing or outside ignored GL3-015G raw evidence",
            }
        payload = path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if digest != pull.get("sha256") or len(payload) != pull.get("bytes"):
            return {
                "decision": "REDIRECT",
                "current_file_sha256": digest,
                "compatibility": "UNKNOWN",
                "reason": "retained pull bytes differ from access receipt hash/length",
            }
        if digest not in checks:
            checks[digest] = verify_snapshot(payload)
        hashes.append(digest)
        versions.append((pull.get("advertised_modified"), pull.get("advertised_size")))
    if len(pulls) != 2 or hashes[0] != hashes[1] or versions[0] != versions[1]:
        decision = "REDIRECT"
        reason = "independent pulls or listing versions are incomplete/different"
    elif hashes[0] == F_ACCEPTED_SHA256:
        decision = "GO_SAME_SNAPSHOT_ONLY"
        reason = "same accepted F bytes; no new-hash compatibility claim"
    elif checks[hashes[0]]["decision"] == "GO":
        decision = "GO_FOR_EXACT_HASH"
        reason = "both independent current pulls match and independent compatibility checks pass"
    else:
        decision = "REDIRECT"
        reason = checks[hashes[0]].get("reason", "compatibility invariant failed")
    return {
        "decision": decision,
        "current_file_sha256": hashes[0] if hashes[0] == hashes[-1] else "UNKNOWN",
        "compatibility": checks[hashes[0]]["decision"] if hashes[0] == hashes[-1] else "UNKNOWN",
        "reason": reason,
        "file_pulls": len(pulls),
        "verified_hashes": hashes,
        "compatibility_checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only replay of retained GL3-015G compatibility evidence")
    parser.add_argument("--access-receipt", type=Path, default=DEFAULT_ACCESS)
    args = parser.parse_args()
    print(json.dumps(replay(args.access_receipt), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
