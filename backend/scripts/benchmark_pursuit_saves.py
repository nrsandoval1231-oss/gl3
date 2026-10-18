"""Synthetic PostgreSQL save/readback benchmark; never production acceptance."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, event, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from benchmark_browse_clock import stats
from benchmark_saved_browse import seed
from fastapi import HTTPException

from gridlens.intelligence.commercial_evaluation import save_evaluations
from gridlens.intelligence.saved_browse import POLICY_VERSION, current_generation, rebuild
from gridlens.persistence.browse_invalidation import install, install_workspace_triggers
from gridlens.persistence.database import Base
from gridlens.persistence.models import BrowseState, Pursuit, PursuitCallNote
from gridlens.settings import settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projects", type=int, required=True)
    parser.add_argument("--evidence", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt-history", type=int, default=20)
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
            "Synthetic prior receipt history is metadata-only, not fabricated qualified cards",
            "Server functions including pool/transactions; no HTTP/auth/network",
            "Warm PostgreSQL cache; shared host; driver BEGIN excluded",
            "SQL group selection still scans saved Signal scalars",
            "Persistence+readback excludes canonical evaluation POST selection/auth/network",
            "Legacy pending reproduces old trigger wiring on this runtime",
            "Date preparation remains future-only; no real production clock boundary tested",
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
        assert rebuild(factory)["status"] == "published"
        settings.saved_browse_enabled = True
        with factory() as session:
            cards = api._commercial_triage_cards(session, 50)

        # Reproduce the prior full invalidation using its frozen trigger wiring.
        def drop_workspace_triggers(conn):
            for name in (
                "invalidate_browse",
                "invalidate_browse_receipt_insert",
                "invalidate_browse_receipt_update",
            ):
                conn.execute(text(f"DROP TRIGGER IF EXISTS {name} ON pursuits"))
            conn.execute(text("DROP TRIGGER IF EXISTS invalidate_browse ON pursuit_call_notes"))

        with engine.begin() as conn:
            drop_workspace_triggers(conn)
            for table in ("pursuits", "pursuit_call_notes"):
                conn.execute(
                    text(
                        f"CREATE TRIGGER invalidate_browse AFTER INSERT OR UPDATE OR "
                        f"DELETE OR TRUNCATE ON {table} FOR EACH STATEMENT "
                        "EXECUTE FUNCTION invalidate_browse_generation('full')"
                    )
                )
        with factory.begin() as session:
            save_evaluations(session, cards)
            session.flush()
            receipt_id = session.scalar(select(Pursuit.id))
            session.add(
                PursuitCallNote(
                    pursuit_id=receipt_id,
                    client_id=uuid4(),
                    note="Legacy synthetic save",
                    outcome="Contacted",
                    next_action="Synthetic follow-up",
                )
            )
        with factory() as session:
            try:
                current_generation(session)
            except HTTPException as exc:
                assert exc.status_code == 503
            else:
                raise AssertionError("Legacy save did not reproduce pending")
        start = time.perf_counter()
        assert rebuild(factory)["status"] == "published"
        result["legacy_pending_rebuild_seconds"] = time.perf_counter() - start
        with engine.begin() as conn:
            drop_workspace_triggers(conn)
            install_workspace_triggers(conn)
        assert 0 <= args.receipt_history <= 200
        with factory.begin() as session:
            receipts = list(session.scalars(select(Pursuit)))
            for row in receipts:
                snapshot = dict(row.snapshot)
                triage = dict(snapshot["commercial_triage"])
                retained = [
                    {
                        "version": index + 1,
                        "disposition": "UNKNOWN",
                        "evaluated_at": (
                            datetime.now(UTC) - timedelta(days=args.receipt_history - index)
                        ).isoformat(),
                        "snapshot_status": "metadata_only",
                        "live_status": "not_rechecked",
                        "saved_card": None,
                    }
                    for index in range(args.receipt_history)
                ]
                triage["versions"] = retained + [
                    {**version, "version": args.receipt_history + index + 1}
                    for index, version in enumerate(triage["versions"])
                ]
                row.snapshot = {**snapshot, "commercial_triage": triage}
            result["receipt_workspaces"] = len(receipts)
            result["prior_metadata_only_versions_per_receipt"] = args.receipt_history
        # Independently measure only duplicate-chain removal on unchanged inputs.
        original_projection = api.opportunity_projection

        def duplicate_chain(*args, **kwargs):
            kwargs.pop("buying_chain_results", None)
            return original_projection(*args, **kwargs)

        api.opportunity_projection = duplicate_chain
        duplicate = [request(True) for _ in range(5)]
        api.opportunity_projection = original_projection
        optimized = [request(True) for _ in range(20)]
        assert {v[2] for v in duplicate + optimized} == {duplicate[0][2]}
        result["duplicate_chain_reads"] = {
            **stats([v[0] for v in duplicate]),
            "queries": sorted({v[1] for v in duplicate}),
        }
        result["reused_chain_reads"] = {
            **stats([v[0] for v in optimized]),
            "queries": sorted({v[1] for v in optimized}),
        }
        with factory() as session:
            baseline_generation = current_generation(session).id

        def save_and_read(index):
            local.queries = 0
            start = time.perf_counter()
            with factory.begin() as writer:
                # The actual note model and a recognized receipt saved-at update;
                # no fake evidence/input_hash/qualification changes are introduced.
                writer.execute(
                    text(
                        "UPDATE pursuits SET snapshot = jsonb_set(snapshot, "
                        "'{commercial_triage,saved_at}', to_jsonb(CAST(:at AS text))) "
                        "WHERE id = :id"
                    ),
                    {"at": datetime.now(UTC).isoformat(), "id": receipt_id},
                )
                writer.add(
                    PursuitCallNote(
                        pursuit_id=receipt_id,
                        client_id=uuid4(),
                        note=f"Synthetic save {index}",
                        outcome="Contacted",
                        next_action="Synthetic follow-up",
                    )
                )
            save_duration = time.perf_counter() - start
            with factory() as reader:
                api._begin_consistent_read(reader)
                assert current_generation(reader).id == baseline_generation
                payload = api._commercial_triage_payload(reader, 50, saved_selection=True)
                assert any(
                    note["note"] == f"Synthetic save {index}"
                    for card in payload["items"]
                    for note in card["notes"]
                )
            return save_duration, time.perf_counter() - start, local.queries

        sequential = [save_and_read(index) for index in range(10)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            concurrent = list(pool.map(save_and_read, range(10, 30)))
        for name, values in (("sequential", sequential), ("four_writers", concurrent)):
            result[name] = {
                "save": stats([v[0] for v in values]),
                "save_and_readback": stats([v[1] for v in values]),
                "queries": sorted({v[2] for v in values}),
            }
        # Saves at publication must neither supersede nor erase date preparation.
        from gridlens.intelligence.saved_browse import rebuild as prepare

        with factory() as session:
            boundary = current_generation(session).valid_until
        start = time.perf_counter()
        assert (
            prepare(factory, _prepare_at=boundary, before_publish=lambda: save_and_read(30))[
                "status"
            ]
            == "prepared"
        )
        result["preparation_with_save_seconds"] = time.perf_counter() - start
        with factory() as session:
            ready_id = session.get(BrowseState, 1).prepared_generation_id
        save_and_read(31)
        with factory() as session:
            api._begin_consistent_read(session)
            assert session.get(BrowseState, 1).prepared_generation_id == ready_id
            canonical = api._commercial_triage_payload(session, 50)
        with factory() as session:
            saved = api._commercial_triage_payload(session, 50, saved_selection=True)
        assert digest(canonical) == digest(saved)
        result["final_payload_parity"] = True
        result["evidence_after"] = checksum()
        assert result["evidence_before"] == result["evidence_after"]
        args.output.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result), flush=True)
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


if __name__ == "__main__":
    main()
