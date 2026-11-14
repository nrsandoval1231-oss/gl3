"""Capture full synthetic groups response JSON for before/after parity."""

from __future__ import annotations

import hashlib
import argparse
import json
import os
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url

ROOT = Path(
    os.environ.get(
        "PERF_SOURCE_ROOT", "/workspace/gl3-page-payload-opt-20261113"
    )
).resolve()
OUT = Path(__file__).resolve().parent
PROFILE_DATABASES = {
    "gl3_mission_rollup_scale_payload_20261113_test",
    "gl3_mission_rollup_scale_payload_after_20261113_test",
    "gl3_mission_rollup_scale_payload_after_facet_20261113_test",
}
sys.path.insert(0, str(ROOT / "backend" / "src"))

from gridlens.intelligence.customer_results import groups  # noqa: E402
from gridlens.persistence.database import SessionLocal  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("before", "after", "after_facet"), default="before")
    parser.add_argument("--shortlist", action="store_true")
    args = parser.parse_args()
    phase = args.phase
    shortlist = args.shortlist
    url = make_url(os.environ["DATABASE_URL"])
    if url.host not in {"127.0.0.1", "localhost", "::1"} or url.database not in PROFILE_DATABASES or url.query:
        raise SystemExit("Refusing any database except the pinned synthetic loopback *_test database")
    for canonical_only in (False, True):
        label = "true" if canonical_only else "false"
        mode = "shortlist_" if shortlist else ""
        output = OUT / f"{phase}_payload_{mode}{label}.json"
        if output.exists():
            raise SystemExit(f"Refusing to overwrite {output}")
        with SessionLocal() as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            session.execute(text("SET LOCAL statement_timeout = '15s'"))
            session.execute(text("SET LOCAL jit = off"))
            result = groups(
                session,
                limit=25,
                canonical_only=canonical_only,
                shortlist=shortlist,
            )
        payload = json.dumps(result, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
        output.write_text(payload + "\n", encoding="utf-8")
        print(json.dumps({
            "file": str(output),
            "canonical_only": canonical_only,
            "shortlist": shortlist,
            "total": result["total"],
            "page_count": len(result["items"]),
            "response_sha256": hashlib.sha256(payload.encode()).hexdigest(),
            "response_bytes": len(payload.encode()),
        }))


if __name__ == "__main__":
    main()
