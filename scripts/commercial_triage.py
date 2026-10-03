"""Read-only local preview of the authenticated commercial triage projection."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from gridlens.api.app import SessionLocal, _commercial_triage_payload  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=50, choices=range(1, 51))
    args = parser.parse_args()
    with SessionLocal() as session:
        payload = _commercial_triage_payload(session, args.limit)
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
