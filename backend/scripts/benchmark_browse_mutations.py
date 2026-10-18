"""Disposable synthetic PostgreSQL mutation availability benchmark; no external calls."""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from benchmark_saved_browse import seed

from gridlens.intelligence.saved_browse import (
    POLICY_VERSION,
    current_generation,
    maintain_once,
    page,
    rebuild,
)
from gridlens.persistence.browse_invalidation import install
from gridlens.persistence.database import Base
from gridlens.persistence.models import BrowseGeneration, PowerNeed, Project
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
    parser.add_argument("--samples", type=int, default=12)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    url = make_url(settings.test_database_url)
    assert url.database.endswith("_test") and "corpus" not in url.database
    assert not args.output.exists()
    schema = "b1_mutation_" + uuid4().hex
    admin = create_engine(url, hide_parameters=True)
    with admin.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(
        url,
        connect_args={"options": f"-csearch_path={schema}"},
        hide_parameters=True,
        pool_size=12,
        max_overflow=4,
    )
    factory = sessionmaker(engine, expire_on_commit=False)
    api = import_module("gridlens.api.app")
    original_factory = api.SessionLocal
    original_switch = settings.saved_browse_enabled
    result = {
        "policy_version": POLICY_VERSION,
        "projects": args.projects,
        "evidence": args.evidence,
        "fixture": "synthetic dated Signal histories, not production copy",
        "limitations": [
            "server functions, no HTTP/network/auth latency",
            "shared local PostgreSQL host",
            "clock expiry forced via stored valid_until; not an actual date rollover",
            "SQL generation clone/prune is population-sized work",
        ],
    }
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as conn:
            install(conn)
        seed(factory, args.projects, args.evidence)
        api.SessionLocal = factory
        settings.saved_browse_enabled = True
        with factory() as session:
            needs = list(session.scalars(select(PowerNeed).order_by(PowerNeed.id).limit(4)))

            def checksum(s):
                return s.execute(
                    text(
                        "SELECT count(*), md5(string_agg(md5(row_to_json(e)::text), '' "
                        "ORDER BY id)) FROM evidence e"
                    )
                ).one()

            result["evidence_before"] = list(checksum(session))
        start = time.perf_counter()
        assert rebuild(factory)["status"] == "published"
        result["full_build_seconds"] = time.perf_counter() - start
        print(json.dumps({"stage": "built", "seconds": result["full_build_seconds"]}), flush=True)
        # Quantify the old full-rebuild response to an ordinary committed write.
        with factory.begin() as session:
            session.execute(
                text("UPDATE power_needs SET rationale = rationale WHERE id = :id"),
                {"id": needs[0].id},
            )
        start = time.perf_counter()
        with factory() as session:
            try:
                current_generation(session)
            except HTTPException as exc:
                assert exc.status_code == 503
            else:
                raise AssertionError("stale generation served")
        assert rebuild(factory)["status"] == "published"
        result["full_rebuild_pending_seconds"] = time.perf_counter() - start
        # Four ordinary fact-independent workflow writers, exact per-need versions.
        versions = [0] * 4
        reads = []
        failures = []
        stop = threading.Event()
        local = threading.local()

        def capture(conn, cursor, statement, *unused):
            if getattr(local, "count", None) is not None:
                local.count += 1

        event.listen(engine, "before_cursor_execute", capture)

        def reader():
            while not stop.is_set():
                start = time.perf_counter()
                try:
                    with factory() as session:
                        session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
                        current_generation(session)
                        data = page(
                            session,
                            api._normalized_browse_filters(
                                **dict.fromkeys(
                                    (
                                        "tier",
                                        "decision",
                                        "geography",
                                        "industry",
                                        "activity",
                                        "timing",
                                        "mw_status",
                                        "mw_min",
                                        "mw_max",
                                        "priority_segment",
                                        "status",
                                        "search",
                                    )
                                )
                            ),
                            ranked=True,
                        )
                        assert data["items"]
                    reads.append(time.perf_counter() - start)
                except HTTPException as exc:
                    failures.append(exc.status_code)
                except Exception as exc:
                    failures.append(type(exc).__name__)
                    stop.set()
                time.sleep(0.005)

        thread = threading.Thread(target=reader)
        thread.start()

        def write(index, require_fresh=True):
            local.count = 0
            start = time.perf_counter()
            body = api.NeedWorkflowStatusBody(
                client_id=uuid4(),
                project_id=needs[index].project_id,
                expected_version=versions[index],
                status="Contacted" if versions[index] % 2 == 0 else "Investigating",
                reason="Synthetic availability benchmark",
            )
            api.set_need_workflow_status(needs[index].id, body, None)
            versions[index] += 1
            if require_fresh:
                with factory() as session:
                    current_generation(session)
            return {"seconds": time.perf_counter() - start, "statements": local.count}

        # Same-origin check still applies in production; benchmark calls server helper without HTTP.
        original_origin = api.require_same_origin
        api.require_same_origin = lambda request: None
        try:
            sequential = [write(0) for _ in range(args.samples)]
            print(
                json.dumps({"stage": "sequential", "seconds": [v["seconds"] for v in sequential]}),
                flush=True,
            )
            with ThreadPoolExecutor(max_workers=4) as pool:
                # Each worker owns its need; four contending transactions per round.
                concurrent = []
                for _ in range(max(1, args.samples // 4)):
                    concurrent.extend(pool.map(write, range(4)))
        finally:
            api.require_same_origin = original_origin
            stop.set()
            thread.join()
        result["atomic_operator_sequential_seconds"] = stats([v["seconds"] for v in sequential])
        result["atomic_operator_concurrent_seconds"] = stats([v["seconds"] for v in concurrent])
        result["mutation_statement_counts"] = sorted(
            set(v["statements"] for v in sequential + concurrent)
        )
        result["concurrent_read_seconds"] = stats(reads)
        result["concurrent_read_pending_or_errors"] = failures
        # Actual draft/accept/retract handlers on retained synthetic histories.
        fact_times = {"draft": [], "accepted": [], "retracted": []}
        fact_counts = {key: [] for key in fact_times}
        fact_version = 0
        with factory() as session:
            location = session.get(Project, needs[0].project_id).location
        api.require_same_origin = lambda request: None
        try:
            for _ in range(4):
                now = datetime.now(UTC)
                body = api.CallFactDraftBody(
                    client_id=uuid4(),
                    project_id=needs[0].project_id,
                    expected_version=fact_version,
                    activity_key=needs[0].activity_key,
                    facility_scope=location,
                    fact_type="demand",
                    value={"mw": "20"},
                    reporter_name="Synthetic fixture",
                    confirmation_channel="customer_call",
                    confirmed_at=now,
                    effective_from=now - timedelta(hours=1),
                    effective_until=now + timedelta(hours=1),
                )
                local.count = 0
                begin = time.perf_counter()
                fact = api.create_need_call_fact(needs[0].id, body, None)
                with factory() as session:
                    current_generation(session)
                fact_times["draft"].append(time.perf_counter() - begin)
                fact_counts["draft"].append(local.count)
                fact_version += 1
                for decision in ("accepted", "retracted"):
                    local.count = 0
                    begin = time.perf_counter()
                    receipt = api.decide_need_call_fact(
                        needs[0].id,
                        fact["id"],
                        api.CallFactDecisionBody(
                            client_id=uuid4(),
                            expected_version=fact_version,
                            decision=decision,
                            reason="Synthetic availability benchmark",
                        ),
                        None,
                    )
                    fact_version = receipt["version"]
                    with factory() as session:
                        current_generation(session)
                    fact_times[decision].append(time.perf_counter() - begin)
                    fact_counts[decision].append(local.count)
        finally:
            api.require_same_origin = original_origin
        result["fact_handler_seconds"] = {key: stats(values) for key, values in fact_times.items()}
        result["fact_handler_statement_counts"] = fact_counts

        # External writes commit pending; maintenance refreshes their project.
        start = time.perf_counter()
        with factory.begin() as session:
            session.execute(
                text("UPDATE power_needs SET rationale = rationale WHERE id = :id"),
                {"id": needs[0].id},
            )
        with factory() as session:
            try:
                current_generation(session)
            except HTTPException as exc:
                assert exc.status_code == 503
            else:
                raise AssertionError("pending not explicit")
        result["external_refresh"] = maintain_once(factory)
        result["external_commit_to_fresh_seconds"] = time.perf_counter() - start
        # Force a clock boundary: incremental reuse prohibited; full rebuild required.
        with factory.begin() as session:
            generation = current_generation(session)
            generation.valid_until = datetime.now(UTC) - timedelta(seconds=1)
        start = time.perf_counter()
        with factory() as session:
            try:
                current_generation(session)
            except HTTPException as exc:
                assert exc.status_code == 503
            else:
                raise AssertionError("expired served")
        tail_writes = []
        tail_errors = []

        def during_full_build():
            try:
                for index in range(8):
                    tail_writes.append(write(index % 4, require_fresh=False))
                    time.sleep(0.25)
            except Exception as exc:
                tail_errors.append(type(exc).__name__)

        api.require_same_origin = lambda request: None
        tail = threading.Thread(target=during_full_build)
        tail.start()
        try:
            result["expired_refresh"] = maintain_once(factory)
            result["clock_expiry_pending_seconds"] = time.perf_counter() - start
            tail.join()
        finally:
            api.require_same_origin = original_origin
        result["writes_during_expired_full_build"] = tail_writes
        result["writes_during_expired_full_build_errors"] = tail_errors
        assert not tail_errors and len(tail_writes) == 8
        assert result["expired_refresh"]["status"] == "published"
        with factory() as session:
            current_generation(session)
            result["retained_generations"] = len(list(session.scalars(select(BrowseGeneration))))
            result["evidence_after"] = list(checksum(session))
        assert result["evidence_before"] == result["evidence_after"]
        assert not failures
        args.output.write_text(json.dumps(result, indent=2, default=str) + "\n")
        print(json.dumps(result, default=str), flush=True)
    finally:
        api.SessionLocal = original_factory
        settings.saved_browse_enabled = original_switch
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


if __name__ == "__main__":
    main()
