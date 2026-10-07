"""Fresh public corpus receipts. Never establishes historical retained-corpus proof."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent))

from validate_pursuit_research import (  # noqa: E402
    CATEGORIES,
    candidate_identity,
    capture_baseline,
    database_snapshot,
    digest,
    execute_cases,
    file_hash,
    preservation,
    replay_state,
    validate_manifest,
    write_once,
)


def now():
    return datetime.now(UTC).isoformat()


def database_name(value):
    if not isinstance(value, str) or not re.fullmatch(r"gl3_regen_[a-z0-9_]{1,48}", value):
        raise ValueError("Require an isolated gl3_regen_ database name")
    return value


def fresh_directory(path):
    path = Path(path)
    if ".artifacts" not in path.resolve().parts:
        raise ValueError("Output must be under an ignored .artifacts directory")
    path.mkdir(parents=True, exist_ok=False)
    return path.resolve()


def child_file(base, relative):
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise ValueError("Expected relative artifact path")
    unresolved = base / relative
    path = unresolved.resolve()
    if path.parent != base.resolve() or unresolved.is_symlink():
        raise ValueError("Artifact path escaped collection directory")
    return path


def selection_rows(value):
    from gridlens.ingestion.adapters.pursuit_acquisition import SUPPORTED_SOURCES

    rows = value.get("records") if isinstance(value, dict) else value
    if not isinstance(rows, list) or not 1 <= len(rows) <= 40:
        raise ValueError("Select one to forty native records")
    keys = []
    for row in rows:
        key = (row.get("source_id"), row.get("external_id"))
        # Federal Register ingestion can implicitly retrieve unbounded companion PDFs.
        # This wrapper admits only the exact native permit path; never strip evidence.
        if key[0] not in SUPPORTED_SOURCES - {"federal-register-eis"} or not isinstance(
            key[1], str
        ):
            raise ValueError("Unsupported exact source or identifier")
        if not re.fullmatch(r"[A-Za-z0-9 /_.-]{1,100}", key[1]):
            raise ValueError("Invalid native identifier")
        keys.append(key)
    if len(set(keys)) != len(keys):
        raise ValueError("Duplicate native record selection")
    return rows


def safe_error(exc):
    from gridlens.ingestion.adapters.bounded_http import AcquisitionFailure

    result = {"error": type(exc).__name__}
    if isinstance(exc, AcquisitionFailure) and re.fullmatch(r"[a-z][a-z0-9_]{0,79}", str(exc)):
        result["acquisition_error_code"] = str(exc)
    return result


def collect(selection, output):
    from gridlens.ingestion.adapters.pursuit_acquisition import (
        acquire_registered_record,
    )

    rows = selection_rows(json.loads(selection.read_text()))
    out = fresh_directory(output)
    receipt = {
        "kind": "reingested",
        "started_at": now(),
        "candidate": candidate_identity(),
        "selection_sha256": file_hash(selection),
        "attempts": [],
    }
    for index, row in enumerate(rows):
        attempt = {
            "source_id": row["source_id"],
            "external_id": row["external_id"],
            "started_at": now(),
            "requests": [],
        }

        def before_request(url, *, attempt=attempt, index=index):
            request = {"url": url, "requested_at": now(), "method": "GET"}
            attempt["requests"].append(request)
            write_once(out / f"request-{index:02d}.json", request)

        try:
            source, record = acquire_registered_record(
                row["source_id"],
                row["external_id"],
                deadline=time.monotonic() + 30,
                before_request=before_request,
                max_bytes=750_000,
            )
            artifact = out / f"record-{index:02d}.json"
            write_once(artifact, {"source": source, "record": record})
            attempt.update(
                status="collected",
                artifact=artifact.name,
                artifact_sha256=file_hash(artifact),
                representation="adapter-rendered canonical record; not raw response",
            )
        except Exception as exc:
            attempt.update(status="failed", **safe_error(exc))
        attempt["finished_at"] = now()
        write_once(out / f"attempt-{index:02d}.json", attempt)
        receipt["attempts"].append(attempt)
    receipt["finished_at"] = now()
    receipt["passed"] = all(a["status"] == "collected" for a in receipt["attempts"])
    write_once(out / "collection.json", receipt)
    return receipt


def checked_collection(path):
    from gridlens.ingestion.registry import load_registry

    receipt = json.loads(path.read_text())
    attempts = receipt["attempts"]
    selection_rows(attempts)
    definitions = {s["id"]: s for s in load_registry()}
    records = []
    for attempt in attempts:
        if attempt["status"] == "failed":
            continue
        if attempt["status"] != "collected":
            raise ValueError("Unknown collection status")
        artifact = child_file(path.parent, attempt["artifact"])
        if file_hash(artifact) != attempt["artifact_sha256"]:
            raise ValueError("Collected artifact hash mismatch")
        item = json.loads(artifact.read_text())
        if item["source"] != definitions[attempt["source_id"]]:
            raise ValueError("Collected source differs from current registry")
        if str(item["record"].get("document_number")) != attempt["external_id"]:
            raise ValueError("Collected native identity mismatch")
        records.append((item["source"], item["record"]))
    return records


def configured_url():
    from sqlalchemy.engine import make_url

    url = make_url(os.environ["DATABASE_URL"])
    if url.drivername not in {"postgresql", "postgresql+psycopg"}:
        raise ValueError("Require a supported PostgreSQL driver")
    if not url.host or not url.port or not url.username:
        raise ValueError("Require explicit PostgreSQL host, port and username")
    tls_keys = {"sslmode", "sslrootcert", "sslcert", "sslkey"}
    if any(key not in tls_keys or not isinstance(value, str) for key, value in url.query.items()):
        raise ValueError("Only scalar TLS connection query options are supported")
    database_name(url.database)
    return url


def full_table_inventories(session):
    """Restore parity for every public table, including mutable row fields."""
    from sqlalchemy import inspect, text

    connection = session.connection()
    quote = connection.dialect.identifier_preparer.quote
    result = {}
    for table in sorted(inspect(connection).get_table_names(schema="public")):
        qualified = f"{quote('public')}.{quote(table)}"
        rows = session.scalars(text(f"SELECT to_jsonb(t) FROM {qualified} t"))
        # Sorted row hashes also preserve multiplicity for tables without an id.
        hashes = sorted(digest(row) for row in rows)
        result[table] = {"count": len(hashes), "sha256": digest(hashes), "rows": hashes}
    return result


def snapshot_session(session):
    from sqlalchemy import text

    result = database_snapshot(session)
    database_name(result["database_name"])
    for table in ("sources", "observations"):
        rows = session.execute(text(f"SELECT id::text, to_jsonb(t) FROM {table} t ORDER BY id"))
        inventory = {identity: digest(value) for identity, value in rows}
        result["immutable_tables"][table] = {
            "count": len(inventory),
            "sha256": digest(inventory),
            "rows": inventory,
        }
    result["replay_state"] = replay_state(session)
    result["full_table_inventories"] = full_table_inventories(session)
    return result


def snapshot():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    engine = create_engine(configured_url())
    try:
        with Session(engine) as session:
            return snapshot_session(session)
    finally:
        engine.dispose()


def finish_ingestion_job(session, job_id, fence, *, error=None):
    from gridlens.jobs.queue import assert_fence

    job = assert_fence(session, job_id, "corpus-regeneration", fence)
    job.status, job.error = ("failed", error) if error else ("succeeded", None)
    job.lease_owner, job.lease_until = None, None


def ingest(collection, output):
    from sqlalchemy import func, select, text

    from gridlens.ingestion.service import process_records
    from gridlens.intelligence.commercial_evaluation import evaluate_target
    from gridlens.jobs.queue import enqueue, lease_one
    from gridlens.jobs.worker import sync_registry
    from gridlens.persistence.database import SessionLocal
    from gridlens.persistence.models import Job, Observation, PowerNeed

    url = configured_url()
    records = checked_collection(collection)
    if not records:
        raise ValueError("No successfully collected records to ingest")
    out = fresh_directory(output)
    with SessionLocal() as session:
        if session.scalar(text("SELECT current_database()")) != url.database:
            raise ValueError("Configured session database mismatch")
        if session.scalar(select(func.count()).select_from(Observation)):
            raise ValueError("Ingestion requires an initially empty Observation table")
        if session.scalar(select(Job.id).where(Job.status.in_(["queued", "running"])).limit(1)):
            raise ValueError("Ingestion requires a quiescent isolated database")
    sync_registry()
    receipt = {
        "kind": "reingested",
        "started_at": now(),
        "candidate": candidate_identity(),
        "collection_sha256": file_hash(collection),
        "attempts": [],
    }
    for index, (source, record) in enumerate(records):
        with SessionLocal.begin() as session:
            job_id = enqueue(session, source["id"])
            leased = lease_one(session, "corpus-regeneration", lease_seconds=600, job_ids=[job_id])
            if leased is None:
                raise ValueError("Unable to lease exact ingestion job")
            _, fence = leased
        attempt = {
            "source_id": source["id"],
            "external_id": record["document_number"],
            "job_id": str(job_id),
            "started_at": now(),
        }
        try:
            with SessionLocal.begin() as session:
                counts = process_records(
                    session,
                    job_id,
                    "corpus-regeneration",
                    fence,
                    source,
                    [record],
                    commit=False,
                    allow_model=False,
                )
                finish_ingestion_job(session, job_id, fence)
                attempt.update(status="succeeded", counts=counts)
        except Exception as exc:
            attempt.update(status="failed", **safe_error(exc))
            try:
                with SessionLocal.begin() as session:
                    finish_ingestion_job(session, job_id, fence, error=type(exc).__name__)
            except RuntimeError:
                # A lost/expired fence belongs to its current worker, never overwrite it.
                attempt["terminal_write"] = "fence_lost_no_write"
        attempt["finished_at"] = now()
        write_once(out / f"ingestion-{index:02d}.json", attempt)
        receipt["attempts"].append(attempt)
    with SessionLocal() as session:
        receipt["snapshot"] = snapshot_session(session)
        receipt["canonical_rows"] = {}
        for table in ("observations", "evidence", "projects", "power_needs"):
            receipt["canonical_rows"][table] = list(
                session.scalars(text(f"SELECT to_jsonb(t) FROM {table} t ORDER BY id"))
            )
        receipt["cards"] = [
            evaluate_target(session, need_id) for need_id in session.scalars(select(PowerNeed.id))
        ]
        receipt["active_jobs"] = [
            str(i)
            for i in session.scalars(select(Job.id).where(Job.status.in_(["queued", "running"])))
        ]
    receipt["finished_at"] = now()
    receipt["collection_failures"] = sum(
        a["status"] != "collected" for a in json.loads(collection.read_text())["attempts"]
    )
    receipt["passed"] = (
        receipt["collection_failures"] == 0
        and bool(receipt["attempts"])
        and all(a["status"] == "succeeded" for a in receipt["attempts"])
    )
    write_once(out / "ingestion.json", receipt)
    return receipt


def backup_restore(target_db, pg_bin, output):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    url = configured_url()
    target_db = database_name(target_db)
    if target_db == url.database:
        raise ValueError("Restore target must differ from source")
    out = fresh_directory(output)
    before = snapshot()
    write_once(out / "before.json", before)
    receipt = {
        "kind": "reingested",
        "started_at": now(),
        "candidate": candidate_identity(),
        "source_database": url.database,
        "database_name": target_db,
        "commands": [],
        "retained_corpus_proof": False,
    }
    env = os.environ.copy()
    env.update(
        PGHOST=url.host or "localhost",
        PGPORT=str(url.port or 5432),
        PGUSER=url.username or "",
        PGPASSWORD=url.password or "",
    )
    # Preserve TLS connection options without placing credentials in arguments or receipts.
    for key in ("sslmode", "sslrootcert", "sslcert", "sslkey"):
        if key in url.query:
            env["PG" + key.upper()] = str(url.query[key])
    dump = out / "fresh-corpus.dump"
    commands = [
        (
            "pg_dump",
            [
                "--format=custom",
                "--no-owner",
                "--no-acl",
                "--file",
                str(dump),
                "--dbname",
                url.database,
            ],
        ),
        ("createdb", ["--template=template0", target_db]),
        (
            "pg_restore",
            [
                "--exit-on-error",
                "--no-owner",
                "--no-acl",
                "--dbname",
                target_db,
                str(dump),
            ],
        ),
    ]
    try:
        for program, args in commands:
            command = {"program": program, "started_at": now()}
            # Output can contain connection details; persist only exit status, never stderr.
            result = subprocess.run(
                [str(pg_bin / program), *args],
                env=env,
                capture_output=True,
                timeout=600,
                check=False,
            )
            command.update(exit_code=result.returncode, finished_at=now())
            receipt["commands"].append(command)
            write_once(out / f"{program}.json", command)
            if result.returncode:
                raise RuntimeError("PostgreSQL command failed")
            if program == "pg_dump":
                receipt["backup_sha256"] = file_hash(dump)
        after_source = snapshot()
        if before != after_source:
            raise ValueError("Source changed during backup")
        engine = create_engine(url.set(database=target_db))
        try:
            with Session(engine) as session:
                restored = snapshot_session(session)
        finally:
            engine.dispose()
        write_once(out / "restored.json", restored)
        receipt["preservation"] = preservation(before, restored)
        comparable = {**restored, "database_name": before["database_name"]}
        receipt["exact_inventory_match"] = before == comparable
        receipt["evidence_inventory_sha256"] = restored["immutable_tables"]["evidence"]["sha256"]
        receipt["passed"] = receipt["exact_inventory_match"] and receipt["preservation"]["passed"]
    except Exception as exc:
        receipt.update(passed=False, error=type(exc).__name__)
    receipt["finished_at"] = now()
    write_once(out / "restore.json", receipt)
    return receipt


def validate_diagnostic(manifest):
    """Subset shape only; canonical/category validation remains in capture_baseline."""
    if manifest.get("schema_version") != 1 or manifest.get("kind") != "reingested":
        raise ValueError("Diagnostic requires schema 1 and kind=reingested")
    database_name(manifest.get("database_name"))
    if manifest.get("isolated_database") is not True:
        raise ValueError("Diagnostic requires isolated_database=true")
    if not isinstance(manifest.get("corpus_id"), str) or not manifest["corpus_id"].strip():
        raise ValueError("Diagnostic requires explicit corpus_id")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= 4:
        raise ValueError("Diagnostic requires one to four cases")
    identities = []
    for case in cases:
        if case.get("category") not in CATEGORIES:
            raise ValueError("Unknown diagnostic category")
        if (
            not isinstance(case.get("selection_reason"), str)
            or not case["selection_reason"].strip()
        ):
            raise ValueError("Source-grounded selection_reason is required")
        identities.append(UUID(case["need_id"]))
    if len(set(identities)) != len(identities):
        raise ValueError("Diagnostic needs must be distinct")
    return sorted(CATEGORIES - {case["category"] for case in cases})


def diagnostic_projection(report, missing, full_gate_error, unchanged):
    result = dict(report)
    result.update(
        scope="partial_diagnostic",
        full_five_cohort_acceptance=False,
        retained_corpus_proof=False,
        operator_attested_retained_corpus_validation=False,
        missing_categories=missing,
        full_gate_error=full_gate_error,
        candidate_unchanged=unchanged,
    )
    if not unchanged:
        result["mechanical_gates_passed"] = False
    result["passed"] = bool(result.get("mechanical_gates_passed")) and unchanged
    return result


def diagnostic(manifest_path, output, *, execute=False, allow_public_research=False):
    if not execute or not allow_public_research:
        raise ValueError("Diagnostic requires --execute --allow-public-research")
    manifest = json.loads(manifest_path.read_text())
    # Run and preserve the real full gate before accepting any diagnostic subset.
    try:
        validate_manifest(manifest, manifest_path.parent)
    except (ValueError, KeyError, TypeError) as exc:
        full_gate_error = {"error": type(exc).__name__}
        if (
            isinstance(exc, ValueError)
            and str(exc) == "Manifest requires five to ten explicit cases"
        ):
            full_gate_error["reason"] = str(exc)
    else:
        raise ValueError("A full manifest must use the existing validation runner")
    missing = validate_diagnostic(manifest)
    url = configured_url()
    if url.database != manifest["database_name"]:
        raise ValueError("Diagnostic database does not match manifest")
    out = fresh_directory(output)
    write_once(out / "full-gate.json", full_gate_error)
    frozen_candidate = candidate_identity()
    from gridlens.persistence.database import SessionLocal

    try:
        with SessionLocal() as session:
            baseline = capture_baseline(
                session, manifest, {"kind": "reingested", "retained_provenance_verified": False}
            )
        write_once(out / "baseline.json", baseline)
        if baseline["candidate"] != frozen_candidate or candidate_identity() != frozen_candidate:
            raise ValueError("Candidate changed before diagnostic execution")
        report = execute_cases(manifest, baseline)
    except Exception as exc:
        report = {
            "error": type(exc).__name__,
            "mechanical_gates_passed": False,
            "corpus_id": manifest["corpus_id"],
            "kind": "reingested",
        }
    report["candidate_before"] = frozen_candidate
    report["candidate_after"] = candidate_identity()
    report = diagnostic_projection(
        report, missing, full_gate_error, report["candidate_after"] == frozen_candidate
    )
    write_once(out / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    for mode in ("collect", "ingest", "snapshot", "backup-restore", "diagnostic"):
        command = sub.add_parser(mode)
        command.add_argument("--output", type=Path, required=True)
        if mode == "diagnostic":
            command.add_argument("--manifest", type=Path, required=True)
            command.add_argument("--execute", action="store_true")
            command.add_argument("--allow-public-research", action="store_true")
        if mode == "collect":
            command.add_argument("--selection", type=Path, required=True)
        if mode == "ingest":
            command.add_argument("--collection", type=Path, required=True)
        if mode == "backup-restore":
            command.add_argument("--target-db", required=True)
            command.add_argument("--pg-bin", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.mode == "collect":
            result = collect(args.selection, args.output)
        elif args.mode == "ingest":
            result = ingest(args.collection, args.output)
        elif args.mode == "diagnostic":
            result = diagnostic(
                args.manifest,
                args.output,
                execute=args.execute,
                allow_public_research=args.allow_public_research,
            )
        elif args.mode == "backup-restore":
            result = backup_restore(args.target_db, args.pg_bin, args.output)
        else:
            result = snapshot()
            write_once(fresh_directory(args.output) / "snapshot.json", result)
        print(
            json.dumps(
                {
                    "mode": args.mode,
                    "output": str(args.output),
                    "passed": result.get("passed"),
                }
            )
        )
        if result.get("passed") is False:
            raise SystemExit(1)
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
