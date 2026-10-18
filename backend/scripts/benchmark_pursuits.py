"""Disposable synthetic PostgreSQL pursuits benchmark; no production acceptance."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from benchmark_browse_clock import stats
from benchmark_saved_browse import seed

from gridlens.intelligence.saved_browse import POLICY_VERSION, rebuild
from gridlens.persistence.browse_invalidation import install
from gridlens.persistence.database import Base
from gridlens.settings import settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projects", type=int, required=True)
    parser.add_argument("--evidence", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    url = make_url(settings.test_database_url)
    assert url.database and url.database.endswith("_test") and "corpus" not in url.database
    assert not args.output.exists()
    schema = "pursuits_" + uuid4().hex
    admin = create_engine(url, hide_parameters=True)
    with admin.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(
        url, connect_args={"options": f"-csearch_path={schema}"}, hide_parameters=True
    )
    factory = sessionmaker(engine, expire_on_commit=False)
    api = import_module("gridlens.api.app")
    local = threading.local()

    def count(*_args):
        local.queries = getattr(local, "queries", 0) + 1

    event.listen(engine, "before_cursor_execute", count)
    result = {
        "projects": args.projects,
        "evidence": args.evidence,
        "policy_version": POLICY_VERSION,
        "limitations": [
            "Synthetic dated Signal histories with unique synthetic addresses",
            "Server functions including pool/transactions; no HTTP/auth/network",
            "Warm PostgreSQL cache; shared host; driver BEGIN excluded",
            "SQL group selection still scans saved Signal scalars",
            "Card/history budgets and canonical selected detail unchanged",
        ],
    }
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as conn:
            install(conn)
        seed(factory, args.projects, args.evidence)
        with factory.begin() as session:
            session.execute(text("UPDATE projects SET location = name || ' Test Road, Dallas, TX'"))

        def checksum():
            with factory() as session:
                return list(
                    session.execute(
                        text(
                            "SELECT count(*), md5(string_agg(md5(row_to_json(e)::text), '' "
                            "ORDER BY id)) "
                            "FROM evidence e"
                        )
                    ).one()
                )

        def digest(payload):
            payload.pop("evaluated_at")
            return hashlib.sha256(
                json.dumps(payload, default=str, sort_keys=True).encode()
            ).hexdigest()

        def request(saved, offset=0):
            local.queries = 0
            start = time.perf_counter()
            with factory() as session:
                payload = api._commercial_triage_payload(session, 50, offset, saved_selection=saved)
            return time.perf_counter() - start, local.queries, digest(payload)

        result["evidence_before"] = checksum()
        settings.saved_browse_enabled = False
        baseline = [request(False) for _ in range(5)]
        result["canonical"] = {
            **stats([v[0] for v in baseline]),
            "queries": sorted({v[1] for v in baseline}),
        }
        start = time.perf_counter()
        assert rebuild(factory)["status"] == "published"
        result["build_seconds"] = time.perf_counter() - start
        settings.saved_browse_enabled = True
        saved = [request(True) for _ in range(30)]
        assert {v[2] for v in baseline + saved} == {baseline[0][2]}
        result["saved"] = {**stats([v[0] for v in saved]), "queries": sorted({v[1] for v in saved})}
        with ThreadPoolExecutor(max_workers=4) as pool:
            concurrent = list(pool.map(lambda _: request(True), range(40)))
        assert {v[2] for v in concurrent} == {baseline[0][2]}
        result["saved_four_readers"] = {
            **stats([v[0] for v in concurrent]),
            "queries": sorted({v[1] for v in concurrent}),
        }
        result["offset_parity"] = {}
        for offset in (50, args.projects - 1, args.projects, args.projects + 50):
            canonical, projected = request(False, offset), request(True, offset)
            assert canonical[2] == projected[2]
            result["offset_parity"][str(offset)] = True
        result["evidence_after"] = checksum()
        assert result["evidence_before"] == result["evidence_after"]
        result["canonical_payload_sha256"] = baseline[0][2]
        args.output.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result), flush=True)
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


if __name__ == "__main__":
    main()
