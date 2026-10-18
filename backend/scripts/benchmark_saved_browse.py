"""Disposable synthetic PostgreSQL benchmark, never production acceptance.

Creates/drops only a fresh random schema in an explicitly named *_test database.
No external sources/models, production copies, credentials or app accounts.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import resource
import statistics
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, event, func, insert, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from gridlens.intelligence.saved_browse import rebuild
from gridlens.persistence.browse_invalidation import install
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    BrowseState,
    Evidence,
    Interpretation,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Source,
)
from gridlens.settings import settings


def seed(factory, projects, evidence_count):
    now = datetime.now(UTC)
    with factory.begin() as session:
        session.add(
            Source(
                id="synthetic-b1",
                publisher="Synthetic fixture",
                endpoint="https://example.test",
                family="construction-permits",
                geography="US",
                industries=["construction"],
                retrieval_method="socrata-permits",
                health={},
            )
        )
    batch_size = 200
    for start in range(0, projects, batch_size):
        rows = {
            model: []
            for model in (
                Project,
                PowerNeed,
                Observation,
                Evidence,
                Interpretation,
                NeedObservation,
            )
        }
        for index in range(start, min(start + batch_size, projects)):
            pid, nid = uuid4(), uuid4()
            identity = f"synthetic-site-{index}"
            activity = "construction"
            location = ("Dallas, TX", "Austin, TX", "California", "Chicago, IL")[index % 4]
            rows[Project].append(
                dict(
                    id=pid,
                    identity_key=identity,
                    name=f"Synthetic project {index}",
                    location=location,
                    source_id="synthetic-b1",
                    external_id=str(index),
                    asset_type="data-center" if index % 3 == 0 else None,
                )
            )
            rows[PowerNeed].append(
                dict(
                    id=nid,
                    project_id=pid,
                    activity_key=activity,
                    tier="Signal",
                    rationale="Synthetic construction signal only",
                    supply="Unknown",
                    active=True,
                    updated_at=now - timedelta(minutes=index),
                )
            )
            histories = evidence_count // projects + (index < evidence_count % projects)
            for history in range(histories):
                oid, eid = uuid4(), uuid4()
                fingerprint = f"{index * 1000 + history:064x}"
                published = now.date() - timedelta(days=history * 15 + index % 40)
                abstract = (
                    f"Synthetic retained construction permit history {history}. "
                    f"Site {index}, {location}. "
                    "Description: site mobilization and construction activity; "
                    "size and supply unknown. "
                    "This is a fabricated benchmark record with no commercial authority. " * 4
                )
                rows[Observation].append(
                    dict(
                        id=oid,
                        source_id="synthetic-b1",
                        external_id=f"{index}-{history}",
                        title=f"Synthetic project {index} construction",
                        abstract=abstract,
                        published_at=published,
                        url=f"https://example.test/{oid}",
                        content_hash=fingerprint,
                    )
                )
                rows[Evidence].append(
                    dict(
                        id=eid,
                        observation_id=oid,
                        content_hash=fingerprint,
                        title=f"Synthetic project {index} construction",
                        abstract=abstract,
                        url=f"https://example.test/{oid}",
                        published_at=published,
                        observed_at=now - timedelta(days=history),
                        extraction_location="Synthetic fixture",
                    )
                )
                rows[Interpretation].append(
                    dict(
                        observation_id=oid,
                        content_hash=fingerprint,
                        evaluator_version="synthetic-b1-fixture",
                        status="accepted",
                        assessment={
                            "semantic_hash": fingerprint,
                            "evidence_hash": fingerprint,
                            "project_identity_key": identity,
                            "power_activity": activity,
                            "decision": "accepted",
                            "subject": f"Synthetic project {index}",
                            "location": location,
                        },
                    )
                )
                rows[NeedObservation].append(dict(need_id=nid, observation_id=oid))
        with factory.begin() as session:
            for model, values in rows.items():
                session.execute(insert(model), values)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projects", type=int, required=True)
    parser.add_argument("--evidence", type=int, required=True)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--baseline-samples", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    url = make_url(settings.test_database_url)
    if not url.database or not url.database.endswith("_test") or "corpus" in url.database:
        raise SystemExit("Explicit disposable *_test database required")
    if args.output.exists():
        raise SystemExit("Refusing to overwrite prior benchmark evidence")
    schema = "b1_bench_" + uuid4().hex
    admin = create_engine(url, hide_parameters=True)
    with admin.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(
        url, connect_args={"options": f"-csearch_path={schema}"}, hide_parameters=True
    )
    factory = sessionmaker(engine, expire_on_commit=False)
    api = import_module("gridlens.api.app")
    original_factory, original_switch = api.SessionLocal, settings.saved_browse_enabled
    result = {
        "kind": "synthetic-local-postgresql-server-function",
        "projects": args.projects,
        "evidence": args.evidence,
        "active_needs": args.projects,
        "limitations": [
            "Fabricated Signal histories; not a production data copy or HTTP/browser latency",
            "No live ingestion or external AI; concurrent reads only",
            "Connection wait, database CPU, and production network not separately measured",
        ],
    }
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as conn:
            install(conn)
        start = time.perf_counter()
        seed(factory, args.projects, args.evidence)
        result["seed_seconds"] = time.perf_counter() - start
        api.SessionLocal = factory

        def evidence_fingerprint():
            with factory() as session:
                return dict(
                    session.execute(
                        text("""
                    SELECT count(*) AS count,
                        md5(string_agg(md5(row_to_json(e)::text), '' ORDER BY id)) AS checksum
                    FROM evidence e
                """)
                    )
                    .mappings()
                    .one()
                )

        result["evidence_before"] = evidence_fingerprint()
        start = time.perf_counter()
        result["build"] = rebuild(factory)
        result["build_seconds"] = time.perf_counter() - start
        result["evidence_after"] = evidence_fingerprint()
        assert result["evidence_before"] == result["evidence_after"]
        if (
            result["build"]["status"] != "published"
            or result["build"]["row_count"] != args.projects
        ):
            raise AssertionError("Fixture population did not publish completely")
        settings.saved_browse_enabled = True
        local = threading.local()

        def capture(conn, cursor, statement, *unused):
            if statement.lstrip().upper().startswith(("SELECT", "WITH")):
                local.queries = getattr(local, "queries", 0) + 1

        event.listen(engine, "before_cursor_execute", capture)
        with factory() as session:
            detail_need_id = session.scalar(select(PowerNeed.id).order_by(PowerNeed.id).limit(1))

        def request(kind):
            local.queries = 0
            start = time.perf_counter()
            if kind == "map":
                payload = api.opportunity_map_window(tier="Signal")
            elif kind == "detail":
                payload = api.opportunity_need_detail(detail_need_id)
            elif kind == "filtered":
                payload = api.opportunities(
                    tier="Signal",
                    geography="Dallas, TX",
                    limit=50,
                    offset=0,
                    cohort=None,
                    sort="rank",
                )
            else:
                payload = api.opportunities(
                    tier="Signal", limit=50, offset=0, cohort=None, sort="rank"
                )
            return {
                "seconds": time.perf_counter() - start,
                "selects": local.queries,
                "bytes": len(json.dumps(payload, default=str).encode()),
            }

        def summarize(samples):
            times = sorted(sample["seconds"] for sample in samples)
            return {
                "samples": len(times),
                "p50_seconds": statistics.median(times),
                "p95_seconds": times[math.ceil(len(times) * 0.95) - 1],
                "max_seconds": max(times),
                "max_selects": max(s["selects"] for s in samples),
                "max_bytes": max(s["bytes"] for s in samples),
            }

        if args.baseline_samples:
            settings.saved_browse_enabled = False
            result["legacy_baseline"] = {}
            for kind in ("ranked_page", "map", "detail"):
                sequential = [request(kind) for _ in range(args.baseline_samples)]
                with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
                    concurrent = list(executor.map(request, [kind] * args.baseline_samples))
                result["legacy_baseline"][kind] = {
                    "sequential": summarize(sequential),
                    "concurrent": summarize(concurrent),
                }
            settings.saved_browse_enabled = True
        measurements = {}
        for kind in ("ranked_page", "filtered", "map", "detail"):
            request(kind)
            sequential = [request(kind) for _ in range(args.samples)]
            with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
                concurrent = list(executor.map(request, [kind] * args.samples))
            measurements[kind] = {}
            for label, samples in (("sequential", sequential), ("concurrent", concurrent)):
                measurements[kind][label] = summarize(samples)
        result["measurements"] = measurements
        cold_code = """
import json, os, time
from importlib import import_module
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from gridlens.settings import settings
api = import_module('gridlens.api.app')
engine = create_engine(os.environ['TEST_DATABASE_URL'],
    connect_args={'options': '-csearch_path=' + os.environ['B1_BENCH_SCHEMA']})
api.SessionLocal = sessionmaker(engine, expire_on_commit=False)
settings.saved_browse_enabled = True
queries = []
event.listen(engine, 'before_cursor_execute',
    lambda c, cur, statement, *args: queries.append(statement))
start = time.perf_counter()
items = api.opportunities(tier='Signal', limit=50, offset=0, cohort=None, sort='rank')
print(json.dumps({'seconds': time.perf_counter()-start, 'returned': len(items),
    'statements': len(queries), 'scope': 'fresh Python process/pool; warm PostgreSQL cache'}))
"""
        cold_env = {
            **os.environ,
            "B1_BENCH_SCHEMA": schema,
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        }
        result["fresh_process_ranked_page"] = json.loads(
            subprocess.check_output([sys.executable, "-c", cold_code], env=cold_env, text=True)
        )
        with factory() as session:
            state = session.get(BrowseState, 1)
            result["rank_page_explain"] = session.scalars(
                text("""
                EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) SELECT compact FROM browse_rows
                WHERE generation_id=:generation AND tier='Signal'
                ORDER BY rank_score DESC, updated_at DESC, need_id LIMIT 50
            """),
                {"generation": state.generation_id},
            ).all()
            result["postgres_version"] = session.scalar(select(func.version()))
        result["max_process_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps({"output": str(args.output), "measurements": measurements}))
    finally:
        api.SessionLocal, settings.saved_browse_enabled = original_factory, original_switch
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


if __name__ == "__main__":
    main()
