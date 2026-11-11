"""Ingestion write-path benchmark (performance Phase 2, Step 0).

Seeds a disposable ``*_test`` Postgres database with a varied project corpus, then runs a
synthetic Texas RRC drilling-permit source through the REAL ``process_job`` in three phases on
the same database, one ``process_job`` call (one source run) per phase:

  (a) all-new:       R records never seen before
  (b) all-unchanged: the same R records replayed byte-for-byte
  (c) mixed:         the same R records, ``--changed-fraction`` of them amended. RRC treats the
                     LOWEST amendment sequence as the latest amendment, so records start at
                     sequence 2 and the changed ones move to sequence 1 (a higher sequence would
                     be retained as older evidence, a different and cheaper path)

``--source legacy`` instead runs the Fort Worth data-center permit source through the same
``process_job``; that source takes the legacy ``process_records(commit=True)`` path with real
per-record commits (the RRC source commits once per segment). The Federal Register EIS source was
considered first but its mine notices are admitted as context only (no project matching), so a
permit-family source that admits a Signal in an eligible region is used instead. Rows are built by
the adapter's own ``record()`` from synthetic permits and flow through project matching, needs,
lifecycle and material-state code. Interpretation is deterministic and offline (no model).

Fixture payloads only: ``service.retrieve_collection_segment`` (rrc) and ``service.retrieve_source``
(legacy) are monkeypatched, so there is no network or provider access. The target database is
dropped and recreated on every run and migrated to head with alembic (``DATABASE_URL`` set for the
subprocess), so the real browse-invalidation triggers are installed and ``browse_state`` starts as
a pristine singleton.

Corpus recipe (project i of N, deterministic, bulk-inserted with
``session_replication_role = replica`` so seeding fires no triggers; ``browse_state`` is
snapshotted before and restored after, and ``browse_dirty_projects`` is emptied):
  * source_id: ``bench-src-0`` .. ``bench-src-5`` (i mod 6); external_id ``EXT-i``.
  * identity_key: ``bench:<source>:<i>`` (unique).
  * name: groups of 3 consecutive projects share a base ``Bench Energy Campus <i/3>``; members
    are the bare name, ``... Phase 2`` and ``... LLC`` (near duplicates); every 10th project is a
    ``Pioneer Bench Power Station <i>`` style name instead.
  * location: i mod 3 = 0 street address (``<n> Industrial Pkwy, Midland, TX 79701``), 1 a county
    (``Ward County, Texas``), 2 NULL.
  * asset_type cycles over data_center, oil_gas_drilling, power_plant, unknown.
  * identity_facts: i mod 4 = 0 has ``site``; i mod 5 = 0 has ``project_aliases`` (one alias
    sharing the group base name); i mod 20 = 0 has both; others ``{}``.
  * power_needs: every 10th project gets one active ``Signal`` need (activity ``bench-activity``).
Region columns keep their server defaults (HOLD / unknown) because seeding bypasses the ORM
region classifier; the ingested synthetic permits are classified normally.

What is measured (client side): wall seconds, records/second, SQLAlchemy ``commit`` events,
``before_cursor_execute`` statements, statements containing FOR UPDATE / FOR NO KEY UPDATE /
FOR SHARE, and count and time of statements containing ``FROM projects`` (the matching scans;
includes joins and counts only client-issued statements).

What is approximated: rows locked cannot be observed from the client and locks taken inside
triggers are invisible to it. The reported proxy is (1) explicit lock statements issued by the
client and (2) calls per record of every browse-invalidation trigger function, taken from
``pg_stat_user_functions`` (``track_functions = all``). Function time is inclusive of nested
calls, so the summed total can double count nested trigger functions; it is an upper bound on
time in browse invalidation. Stats are flushed lazily, so each snapshot waits ~2 s.

Usage (from backend/ with the backend venv):
  python ../scripts/ingestion_write_benchmark.py --database-url \
      postgresql+psycopg://postgres@localhost:5544/gl3_bench_test --projects 5000 \
      --records 300 --json-out out.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
OPERATORS = [f"SYNTHETIC OPERATOR {chr(65 + i)} LLC" for i in range(20)]
BROWSE_FUNCTION_RE = (
    r"^(dirty_browse_|invalidate_browse_|browse_observation_projects|scope_browse_"
    r"|mark_browse_|track_browse_stale_since)"
)
LOCK_RE = re.compile(r"FOR\s+(NO\s+KEY\s+UPDATE|UPDATE|SHARE|KEY\s+SHARE)\b", re.IGNORECASE)
PROJECT_SCAN_RE = re.compile(r"\bFROM\s+projects\b", re.IGNORECASE)
SOURCE_COUNT = 6


def guard_database(url: URL) -> None:
    if not (url.database or "").endswith("_test"):
        raise SystemExit(f"refusing: database name {url.database!r} must end with '_test'")


def recreate_database(url: URL) -> None:
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{url.database}"'))
        conn.execute(text(f"ALTER DATABASE \"{url.database}\" SET track_functions = 'all'"))
    admin.dispose()


def migrate(url: URL) -> float:
    started = time.perf_counter()
    env = {**os.environ, "DATABASE_URL": url.render_as_string(hide_password=False)}
    env.setdefault("SESSION_SECRET", "dummy-session-secret-dummy-session-secret")
    env.setdefault("APP_PASSWORD_HASH", "dummy")
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        env=env,
        check=True,
        capture_output=True,
    )
    return time.perf_counter() - started


SEED_SQL = """
INSERT INTO sources (id, publisher, endpoint, family, geography, industries, retrieval_method,
                     cadence_hours, enabled, registry_enabled, health)
SELECT 'bench-src-' || s, 'Bench publisher ' || s, 'https://bench.invalid/' || s, 'bench',
       'TX', '[]'::jsonb, 'fixture', 24, false, false, '{}'::jsonb
FROM generate_series(0, :sources - 1) AS s;

INSERT INTO projects (id, identity_key, name, location, source_id, external_id, asset_type,
                      identity_facts)
SELECT gen_random_uuid(),
       'bench:bench-src-' || (i % :sources) || ':' || i,
       CASE WHEN i % 10 = 0 THEN 'Pioneer Bench Power Station ' || i
            ELSE 'Bench Energy Campus ' || (i / 3) ||
                 CASE i % 3 WHEN 0 THEN '' WHEN 1 THEN ' Phase 2' ELSE ' LLC' END END,
       CASE i % 3 WHEN 0 THEN ((i % 9000) || ' Industrial Pkwy, Midland, TX 79701')
                  WHEN 1 THEN 'Ward County, Texas' ELSE NULL END,
       'bench-src-' || (i % :sources),
       'EXT-' || i,
       (ARRAY['data_center','oil_gas_drilling','power_plant','unknown'])[1 + i % 4],
       (CASE WHEN i % 4 = 0 THEN jsonb_build_object('site', (i % 9000) || ' Industrial Pkwy')
             ELSE '{}'::jsonb END)
       || (CASE WHEN i % 5 = 0
                THEN jsonb_build_object('project_aliases',
                                        jsonb_build_array('Bench Energy Campus ' || (i / 3)))
                ELSE '{}'::jsonb END)
FROM generate_series(1, :projects) AS i;

INSERT INTO power_needs (id, project_id, activity_key, tier, rationale, admission_basis, supply,
                         active)
SELECT gen_random_uuid(), p.id, 'bench-activity', 'Signal', 'Synthetic benchmark need',
       '{}'::jsonb, 'Unknown', true
FROM projects p
WHERE p.external_id ~ '^EXT-[0-9]*0$' AND p.source_id LIKE 'bench-src-%';
"""


def _backfill_match_keys(conn: Any) -> None:
    """Give seeded rows the keys the 0055 backfill would have given them.

    Raw SQL inserts leave ``projects.match_keys`` NULL, and a NULL-key row is always a
    candidate, so without this the indexed matcher would be benchmarked on its full-scan
    fallback. A database without the column (the pre-Step-1 baseline) is left untouched.
    """
    has_column = conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema()"
            " AND table_name = 'projects' AND column_name = 'match_keys'"
        )
    ).first()
    if not has_column:
        return
    from gridlens.intelligence.project_identity import project_match_keys

    last = None
    while True:
        rows = conn.execute(
            text(
                "SELECT id, name, location, identity_facts FROM projects"
                " WHERE (CAST(:last AS uuid) IS NULL OR id > CAST(:last AS uuid))"
                " ORDER BY id LIMIT 2000"
            ),
            {"last": last},
        ).all()
        if not rows:
            return
        conn.execute(
            text("UPDATE projects SET match_keys = :keys WHERE id = :id"),
            [
                {
                    "id": row.id,
                    "keys": project_match_keys(row.name, row.location, row.identity_facts),
                }
                for row in rows
            ],
        )
        last = str(rows[-1].id)


def seed(engine: Any, projects: int) -> float:
    started = time.perf_counter()
    with engine.begin() as conn:
        state = conn.execute(text("SELECT * FROM browse_state")).mappings().all()
        conn.execute(text("SET LOCAL session_replication_role = replica"))
        for statement in SEED_SQL.split(";\n\n"):
            if statement.strip():
                conn.execute(
                    text(statement.strip().rstrip(";")),
                    {"sources": SOURCE_COUNT, "projects": projects},
                )
        _backfill_match_keys(conn)
        # Seeding bypassed every trigger; restore the pristine browse_state singleton.
        conn.execute(text("DELETE FROM browse_dirty_projects"))
        for row in state:
            sets = ", ".join(f"{k} = :{k}" for k in row if k != "id")
            conn.execute(text(f"UPDATE browse_state SET {sets} WHERE id = :id"), dict(row))
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("ANALYZE"))
    return time.perf_counter() - started


def permit(definition: dict[str, Any], portal: str, project: int, sequence: int) -> dict:
    digest = hashlib.sha256(f"{project}:{sequence}".encode()).hexdigest()
    index = project % len(OPERATORS)
    operator = OPERATORS[index]
    number = f"{100001 + index:06d}"
    provenance = json.dumps(
        [
            {
                "filename": "daf420.dat",
                "source_url": portal,
                "ordinal": 1,
                "sequence": sequence,
                "raw_sha256": "a" * 64,
            }
        ]
    )
    return {
        "document_number": str(project),
        "title": f"Drilling permit {project}",
        "abstract": (
            f"amendment_sequence: {sequence}\noperator: {operator}\noperator_number: {number}"
            f"\nlease: Lease {project}\nwell: 1H\nstatus: Approved"
            "\napplication_type: 01"
            f"\nSource segment provenance: {provenance}"
            "\nOpaque source bytes (base64; not interpreted): {}"
        ),
        "publication_date": "2026-09-01",
        "event_date": "2026-09-01",
        "html_url": portal,
        "source_hash": digest,
        "extraction_location": "Synthetic OGA049M fixture",
        "permit": {
            "source_type": definition["id"],
            "project": str(project),
            "row_id": str(project),
            "lease": f"Lease {project}",
            "well": "1H",
            "operator": operator,
            "operator_number": number,
            "location": "RRC county code 001, Texas",
            "state": "TX",
            "status": "Approved",
            "description": f"Drilling permit {project}",
            "application_type": "01",
            "sequence": sequence,
        },
    }


def legacy_row(project: int, variant: int) -> dict:
    """A Fort Worth data-center building permit, as the adapter's own ``record()`` shapes it.

    The permit interprets into a dated, site-identified Signal in a region-eligible state, so it
    flows through project matching, needs, lifecycle and material-state code. One third of the
    facility names reuse the seeded ``Bench Energy Campus <group>`` base so matching has
    near-duplicate candidates; the rest are unique. ``variant`` 1 amends the work description.
    """
    from gridlens.ingestion.adapters.fort_worth_permits import record

    group = project % 1700
    facility = (
        f"Bench Energy Campus {group} Data Center"
        if project % 3 == 0
        else f"Legacy Bench Data Center {project}"
    )
    street = f"{100 + project % 900} Bench Parkway"
    filed = (datetime.now(UTC).date() - timedelta(days=2 + project % 20)).isoformat()
    return record(
        {
            "permit_no": f"PB{project}",
            "permit_type": "Building",
            "subtype": "New",
            "project": facility,
            "work": "New data center building 120,000 SF"
            + (" with added substation yard" if variant else ""),
            "status": "Issued",
            "status_date": filed,
            "filed": filed,
            "job_value": "$25,000,000",
            "owners": [f"Bench Owner {project % 50} LLC"],
            "addresses": [f"{street}, Fort Worth, TX 76177"],
            "latitude": 32.9 + (project % 100) / 1000,
            "longitude": -97.3 - (project % 100) / 1000,
        }
    )


class Counters:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.commits = 0
        self.statements = 0
        self.lock_statements = 0
        self.project_scans = 0
        self.project_scan_seconds = 0.0
        self._started: list[tuple[float, bool]] = []

    def attach(self, engine: Any) -> None:
        @event.listens_for(engine, "commit")
        def _commit(_conn: Any) -> None:
            self.commits += 1

        @event.listens_for(engine, "before_cursor_execute")
        def _before(_conn: Any, _cur: Any, statement: str, *_a: Any) -> None:
            self.statements += 1
            if LOCK_RE.search(statement):
                self.lock_statements += 1
            scan = bool(PROJECT_SCAN_RE.search(statement))
            self.project_scans += scan
            self._started.append((time.perf_counter(), scan))

        @event.listens_for(engine, "after_cursor_execute")
        def _after(*_a: Any) -> None:
            began, scan = self._started.pop()
            if scan:
                self.project_scan_seconds += time.perf_counter() - began


def function_stats(engine: Any) -> dict[str, dict[str, float]]:
    time.sleep(2.0)
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("SELECT pg_stat_clear_snapshot()"))
        rows = conn.execute(
            text(
                "SELECT funcname, calls, total_time, self_time FROM pg_stat_user_functions"
                " WHERE funcname ~ :pattern"
            ),
            {"pattern": BROWSE_FUNCTION_RE},
        ).all()
    return {
        r.funcname: {"calls": r.calls, "total_ms": r.total_time, "self_ms": r.self_time}
        for r in rows
    }


def diff_stats(before: dict, after: dict) -> dict[str, dict[str, float]]:
    out = {}
    for name, now in after.items():
        was = before.get(name, {"calls": 0, "total_ms": 0.0, "self_ms": 0.0})
        calls = now["calls"] - was["calls"]
        if calls:
            out[name] = {
                "calls": calls,
                "total_ms": now["total_ms"] - was["total_ms"],
                "self_ms": now["self_ms"] - was["self_ms"],
            }
    return out


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    url = make_url(args.database_url)
    guard_database(url)
    os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
    os.environ.setdefault("SESSION_SECRET", "dummy-session-secret-dummy-session-secret")
    os.environ.setdefault("APP_PASSWORD_HASH", "dummy")
    sys.path.insert(0, str(BACKEND / "src"))

    recreate_database(url)
    migrate_seconds = migrate(url)

    import gridlens.ingestion.service as service
    from gridlens.ingestion.adapters.rrc_drilling import PORTAL
    from gridlens.ingestion.registry import load_registry
    from gridlens.persistence.models import Job, Source

    legacy = args.source == "legacy"
    definition = next(
        r
        for r in load_registry()
        if r["id"] == ("fort-worth-development-permits" if legacy else "texas-rrc-drilling-permits")
    )
    engine = create_engine(url, pool_size=4)
    factory = sessionmaker(engine, expire_on_commit=False)

    seed_seconds = seed(engine, args.projects)
    with engine.connect() as conn:
        corpus = {
            "projects": conn.execute(text("SELECT count(*) FROM projects")).scalar_one(),
            "power_needs": conn.execute(text("SELECT count(*) FROM power_needs")).scalar_one(),
            "browse_state": dict(conn.execute(text("SELECT * FROM browse_state")).mappings().one()),
        }

    with factory.begin() as session:
        session.add(
            Source(
                **{
                    k: definition[k]
                    for k in (
                        "id",
                        "publisher",
                        "endpoint",
                        "family",
                        "geography",
                        "industries",
                        "retrieval_method",
                    )
                },
                health={},
            )
        )

    batch: list[dict] = []

    def segment(_source, _lane, _start, _end, _cursor, client=None, *_a, **_k):  # noqa: ANN001
        records = list(batch)
        return {
            "records": records,
            "cursor": {},
            "partial": False,
            "window_complete": True,
            "expected_count": len(records),
            "observed_count": len(records),
        }

    client = None
    if legacy:
        service.retrieve_source = lambda *_a, **_k: list(batch)
    else:
        service.retrieve_collection_segment = segment

    base = 70_000_000
    changed_count = max(1, round(args.records * args.changed_fraction))
    if legacy:
        unchanged = [legacy_row(base + i, 0) for i in range(args.records)]
        mixed = [legacy_row(base + i, 1 if i < changed_count else 0) for i in range(args.records)]
    else:
        unchanged = [permit(definition, PORTAL, base + i, 2) for i in range(args.records)]
        mixed = [
            permit(definition, PORTAL, base + i, 1 if i < changed_count else 2)
            for i in range(args.records)
        ]
    phases = [
        ("a_all_new", unchanged),
        ("b_all_unchanged", unchanged),
        (f"c_{args.changed_fraction:.0%}_changed", mixed),
    ]

    counters = Counters()
    counters.attach(engine)
    results = []
    for name, records in phases:
        batch[:] = records
        with factory.begin() as session:
            job = Job(
                source_id=definition["id"],
                status="running",
                lease_owner="bench",
                fence=1,
                lease_until=datetime.now(UTC) + timedelta(hours=6),
            )
            session.add(job)
            session.flush()
            job_id = job.id
            # Forget collection progress so every phase plans the same issue_recent lane; a
            # retained completed lane would route a replay through the history lane instead.
            session.execute(
                text("DELETE FROM source_collection_progress WHERE source_id = :s"),
                {"s": definition["id"]},
            )
        before = function_stats(engine)
        counters.reset()
        started = time.perf_counter()
        with factory() as session:
            outcome = service.process_job(session, job_id, "bench", 1, definition, client)
        wall = time.perf_counter() - started
        snapshot = (
            counters.commits,
            counters.statements,
            counters.lock_statements,
            counters.project_scans,
            counters.project_scan_seconds,
        )
        functions = diff_stats(before, function_stats(engine))
        n = len(records)
        trigger_ms = sum(f["total_ms"] for f in functions.values())
        row = {
            "phase": name,
            "records": n,
            "wall_seconds": wall,
            "records_per_second": n / wall,
            "commits": snapshot[0],
            "commits_per_record": snapshot[0] / n,
            "statements": snapshot[1],
            "statements_per_record": snapshot[1] / n,
            "explicit_lock_statements": snapshot[2],
            "explicit_lock_statements_per_record": snapshot[2] / n,
            "project_scan_statements": snapshot[3],
            "project_scan_seconds": snapshot[4],
            "trigger_calls": sum(f["calls"] for f in functions.values()),
            "trigger_calls_per_record": sum(f["calls"] for f in functions.values()) / n,
            "trigger_total_ms_inclusive": trigger_ms,
            "trigger_pct_of_wall": 100 * trigger_ms / 1000 / wall,
            "trigger_functions": functions,
            "process_job_result": json.loads(json.dumps(outcome, default=str)),
        }
        results.append(row)
        print(f"phase {name}: {wall:.1f}s", flush=True)

    with engine.connect() as conn:
        final = {
            "projects": conn.execute(text("SELECT count(*) FROM projects")).scalar_one(),
            "observations": conn.execute(text("SELECT count(*) FROM observations")).scalar_one(),
        }
    engine.dispose()
    return {
        "date": datetime.now(UTC).date().isoformat(),
        "args": {
            "source": args.source,
            "projects": args.projects,
            "records": args.records,
            "changed_fraction": args.changed_fraction,
        },
        "database": url.database,
        "migrate_seconds": migrate_seconds,
        "seed_seconds": seed_seconds,
        "corpus": corpus,
        "final_counts": final,
        "phases": results,
        "approximations": [
            "Rows locked cannot be measured from the client; reported proxies are explicit "
            "FOR UPDATE/SHARE statements and per-record calls of browse-invalidation trigger "
            "functions.",
            "Trigger function total_ms is inclusive of nested function calls and may double "
            "count; it bounds time spent in browse invalidation from above.",
            "Project scan statements are client statements containing 'FROM projects'.",
        ],
    }


def render_table(report: dict[str, Any]) -> str:
    header = (
        "| phase | wall s | rec/s | commits/rec | stmts/rec | lock stmts/rec | trigger calls/rec "
        "| trigger ms (incl.) | trigger % wall | projects scans | scan s |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|\n"
    )
    lines = [
        f"| {p['phase']} | {p['wall_seconds']:.1f} | {p['records_per_second']:.2f} "
        f"| {p['commits_per_record']:.2f} | {p['statements_per_record']:.1f} "
        f"| {p['explicit_lock_statements_per_record']:.2f} | {p['trigger_calls_per_record']:.1f} "
        f"| {p['trigger_total_ms_inclusive']:.0f} | {p['trigger_pct_of_wall']:.1f}% "
        f"| {p['project_scan_statements']} | {p['project_scan_seconds']:.1f} |"
        for p in report["phases"]
    ]
    return header + "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--projects", type=int, default=5000)
    parser.add_argument("--source", choices=("rrc", "legacy"), default="rrc")
    parser.add_argument("--records", type=int, default=300)
    parser.add_argument("--changed-fraction", type=float, default=0.05)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    report = run_benchmark(args)
    print(render_table(report))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2, default=str) + "\n")


if __name__ == "__main__":
    main()
