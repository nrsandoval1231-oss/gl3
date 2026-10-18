"""Synthetic PostgreSQL prepared-clock availability, never production acceptance."""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from benchmark_saved_browse import seed

from gridlens.intelligence import saved_browse as browse
from gridlens.persistence.browse_invalidation import install
from gridlens.persistence.database import Base
from gridlens.persistence.models import BrowseState, PowerNeed
from gridlens.settings import settings


def stats(values):
    ordered = sorted(values)
    return {
        "samples": len(values),
        "p50": ordered[(len(values) - 1) // 2],
        "p95": ordered[min(len(values) - 1, int(len(values) * 0.95))],
        "max": max(values),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projects", type=int, required=True)
    parser.add_argument("--evidence", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    url = make_url(settings.test_database_url)
    assert url.database.endswith("_test") and "corpus" not in url.database
    assert not args.output.exists()
    schema = "b1_clock_" + uuid4().hex
    admin = create_engine(url, hide_parameters=True)
    with admin.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(
        url, connect_args={"options": f"-csearch_path={schema}"}, hide_parameters=True
    )
    factory = sessionmaker(engine, expire_on_commit=False)
    physical_datetime = browse.datetime
    local = threading.local()
    result = {
        "projects": args.projects,
        "evidence": args.evidence,
        "policy_version": browse.POLICY_VERSION,
        "limitations": [
            "Synthetic dated Signal histories, not a production copy",
            "Boundary reader/publication clock simulated; preparation runs before real deadline",
            "Server functions, no HTTP/auth/network; shared local PostgreSQL; warm database cache",
            "Repeated writes may discard preparation; fallback is explicit pending/full rebuild",
        ],
    }
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as conn:
            install(conn)
        seed(factory, args.projects, args.evidence)

        def checksum():
            with factory() as session:
                return list(
                    session.execute(
                        text(
                            "SELECT count(*), md5(string_agg(md5(row_to_json(e)::text), '' "
                            "ORDER BY id)) FROM evidence e"
                        )
                    ).one()
                )

        result["evidence_before"] = checksum()
        start = time.perf_counter()
        assert browse.rebuild(factory)["status"] == "published"
        result["initial_build_seconds"] = time.perf_counter() - start
        with factory() as session:
            generation = browse.current_generation(session)
            original_id, boundary = generation.id, generation.valid_until
            need_id = session.scalar(select(PowerNeed.id).limit(1))

        class AtBoundary(datetime):
            @classmethod
            def now(cls, tz=None):
                return boundary

        browse.datetime = AtBoundary
        with factory() as session:
            try:
                browse.current_generation(session)
            except HTTPException as exc:
                assert exc.status_code == 503
            else:
                raise AssertionError("expired generation served")
        start = time.perf_counter()
        assert browse.maintain_once(factory)["status"] == "published"
        result["unprepared_expiry_pending_seconds"] = time.perf_counter() - start
        browse.datetime = physical_datetime
        assert browse.restore_generation(factory, original_id)
        print(
            json.dumps(
                {"stage": "baseline", "seconds": result["unprepared_expiry_pending_seconds"]}
            ),
            flush=True,
        )
        filters = dict.fromkeys(
            (
                "tier",
                "search",
                "geography",
                "industry",
                "activity",
                "timing",
                "mw_status",
                "mw_min",
                "mw_max",
                "priority_segment",
                "status",
            )
        )
        filters["decision"] = "ALL"
        counts = []
        timings = []
        errors = []
        stop = threading.Event()

        def capture(conn, cursor, statement, *unused):
            if getattr(local, "queries", None) is not None:
                local.queries += 1

        event.listen(engine, "before_cursor_execute", capture)

        def read():
            local.queries = 0
            start = time.perf_counter()
            with factory() as session:
                session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
                data = browse.page(session, filters, ranked=True)
                assert data["items"]
            return time.perf_counter() - start, local.queries

        def read_during_build():
            while not stop.is_set():
                try:
                    duration, queries = read()
                    timings.append(duration)
                    counts.append(queries)
                except Exception as exc:
                    errors.append(type(exc).__name__)
                    stop.set()
                time.sleep(0.01)

        reader = threading.Thread(target=read_during_build)
        reader.start()
        try:
            start = time.perf_counter()
            prepared = browse.prepare_next(factory, lead_seconds=90000)
            result["prepare_seconds"] = time.perf_counter() - start
            assert prepared["status"] == "prepared"
        finally:
            stop.set()
            reader.join()
        result["reads_during_preparation_seconds"] = stats(timings)
        result["reads_during_preparation_statements"] = sorted(set(counts))
        result["reads_during_preparation_errors"] = errors
        assert not errors
        with factory() as session:
            assert browse.current_generation(session).id == original_id
            prepared_id = session.get(BrowseState, 1).prepared_generation_id
            assert browse.current_generation(session, now=boundary).id == prepared_id
        # A fresh connection pool still observes the persisted prepared pointer.
        engine.dispose()
        browse.datetime = AtBoundary
        start = time.perf_counter()
        read()
        result["first_boundary_read_seconds"] = time.perf_counter() - start
        sequential = [read() for _ in range(60)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            concurrent = list(pool.map(lambda unused: read(), range(60)))
        result["prepared_boundary_sequential_seconds"] = stats([x[0] for x in sequential])
        result["prepared_boundary_concurrent_seconds"] = stats([x[0] for x in concurrent])
        result["prepared_boundary_statements"] = sorted(set(x[1] for x in sequential + concurrent))
        # No promotion, writer or maintenance action was needed for boundary reads.
        with factory() as session:
            assert session.get(BrowseState, 1).generation_id == original_id
        browse.datetime = physical_datetime

        def write():
            with factory.begin() as session:
                session.execute(
                    text("UPDATE power_needs SET rationale=rationale WHERE id=:id"), {"id": need_id}
                )
                assert browse.refresh_project_changes(session)["status"] == "published"

        write()  # invalidate the previous preparation and keep current browse fresh

        def repeated_writes():
            for _ in range(3):
                write()

        start = time.perf_counter()
        raced = browse.prepare_next(factory, lead_seconds=90000, before_publish=repeated_writes)
        result["invalidated_prepare_seconds"] = time.perf_counter() - start
        result["invalidated_prepare_status"] = raced["status"]
        assert raced["status"] == "superseded"
        with factory() as session:
            browse.current_generation(session)
            try:
                browse.current_generation(session, now=boundary)
            except HTTPException as exc:
                assert exc.status_code == 503
            else:
                raise AssertionError("invalidated future served")
        start = time.perf_counter()
        assert browse.prepare_next(factory, lead_seconds=90000)["status"] == "prepared"
        result["quiet_retry_prepare_seconds"] = time.perf_counter() - start
        result["evidence_after"] = checksum()
        assert result["evidence_before"] == result["evidence_after"]
        args.output.write_text(json.dumps(result, indent=2, default=str) + "\n")
        print(json.dumps(result, default=str), flush=True)
    finally:
        browse.datetime = physical_datetime
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


if __name__ == "__main__":
    main()
