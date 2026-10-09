"""Verify A5A retained-corpus browse parity and measure a first-page read."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import sys
import time
import tracemalloc
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import event

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gridlens.api import app as api_module
from gridlens.api.app import _commercial_triage_cards, opportunity_projection
from gridlens.domain.commercial_triage import _priority, grouped_need_ids
from gridlens.domain.pursuit_screening import work_identity
from gridlens.persistence.database import SessionLocal


def canonical(value: object) -> bytes:
    return json.dumps(value, default=str, sort_keys=True, separators=(",", ":")).encode()


def main() -> int:
    arguments = sys.argv[1:]
    output_path: Path | None = None
    if "--output" in arguments:
        index = arguments.index("--output")
        if index + 1 >= len(arguments):
            raise SystemExit("--output requires a new output file path")
        output_path = Path(arguments[index + 1])
        if output_path.exists():
            raise SystemExit(f"refusing to overwrite benchmark output: {output_path}")
        del arguments[index : index + 2]
    if len(arguments) != 2:
        raise SystemExit(
            "usage: benchmark_browse_projection.py FULL_ORACLE_DIRECTORY "
            "PAGE_ORACLE_DIRECTORY [--output NEW_RESULT_FILE]"
        )
    if os.environ.get("DATABASE_URL", "").rsplit("/", 1)[-1] != "gl3audit_a5_corpus_test":
        raise SystemExit("read-only A5 corpus database required")
    oracle_dir = Path(arguments[0])
    page_oracle_dir = Path(arguments[1])
    oracle_raw = gzip.decompress((oracle_dir / "semantic-oracle.json.gz").read_bytes())
    oracle = json.loads(oracle_raw)
    page_measurement = json.loads((page_oracle_dir / "measurement.json").read_text())
    page_oracle = json.loads(gzip.decompress((page_oracle_dir / "cards.json.gz").read_bytes()))
    page_oracle_bytes = canonical(page_oracle)
    page_oracle_sha = hashlib.sha256(page_oracle_bytes).hexdigest()
    if page_measurement.get("local_date") != "2026-10-07":
        raise AssertionError("matched page oracle is not bound to the governed comparison date")
    if page_measurement.get("card_json_sha256") != page_oracle_sha:
        raise AssertionError("matched page oracle file differs from its recorded fingerprint")
    oracle_rows = {str(row["id"]): row for row in oracle["rows"]}
    expected_groups = [card["related_need_ids"] for card in oracle["groups_without_buying_chain"]]
    result: dict[str, object] = {"oracle_sha256": hashlib.sha256(oracle_raw).hexdigest()}
    api_module.chicago_today = lambda now=None: date(2026, 10, 7)

    with SessionLocal() as session:
        session.connection().exec_driver_sql("SET TRANSACTION READ ONLY")
        summary_diagnostics: dict[str, int] = {}
        summary = opportunity_projection(
            session,
            tier="Signal",
            summary_only=True,
            summary_diagnostics=summary_diagnostics,
        )
        summary_ids = [str(row["id"]) for row in summary]
        if set(summary_ids) != set(oracle_rows):
            raise AssertionError("summary eligibility differs from the frozen oracle")
        actual_groups = grouped_need_ids(summary)
        if actual_groups != expected_groups:
            raise AssertionError("summary work groups/order differ from the frozen oracle")
        priority = {str(row["id"]): list(_priority(row)) for row in summary}
        if priority != oracle["priority_by_id"]:
            raise AssertionError("summary priority tuples differ from the frozen oracle")
        for row in summary:
            evidence: dict[str, Any] = next(
                (
                    item
                    for item in row.get("evidence", [])
                    if item.get("assessment_current", True)
                ),
                {},
            )
            actual_identity = work_identity(
                str(evidence.get("source_id") or ""),
                str(evidence.get("document_number") or evidence.get("id") or ""),
                str(row.get("location") or ""),
            )
            original = oracle_rows[str(row["id"])]
            original_evidence: dict[str, Any] = next(
                (
                    item
                    for item in original.get("evidence", [])
                    if item.get("assessment_current", True)
                ),
                {},
            )
            if actual_identity != work_identity(
                str(original_evidence.get("source_id") or ""),
                str(original_evidence.get("document_number") or original_evidence.get("id") or ""),
                str(original.get("location") or ""),
            ):
                raise AssertionError(f"summary work identity differs for {row['id']}")

        full_projection = opportunity_projection(session, tier="Signal")
        if len(full_projection) != len(oracle_rows):
            raise AssertionError("full detail projection row count differs from the frozen oracle")
        for row in full_projection:
            need_id = str(row["id"])
            if canonical(row) != canonical(oracle_rows[need_id]):
                raise AssertionError(
                    f"full detail projection differs from the frozen oracle: {need_id}"
                )

        selected_ids = {UUID(need_id) for group in actual_groups[:50] for need_id in group}
        selected = opportunity_projection(
            session, tier="Signal", selected_need_ids=selected_ids
        )
        selected_rows = {str(row["id"]): row for row in selected}
        if set(selected_rows) != {str(need_id) for need_id in selected_ids}:
            raise AssertionError("selected-page hydration omitted or added a related need")
        for need_id, row in selected_rows.items():
            if canonical(row) != canonical(oracle_rows[need_id]):
                raise AssertionError(f"selected detail differs from the frozen oracle: {need_id}")
        session.rollback()

    page_runs: list[dict[str, object]] = []
    cards: list[dict[str, Any]] = []
    first_card_bytes: bytes | None = None
    for run_name in ("cold_process", "warm_same_process"):
        with SessionLocal() as session:
            session.connection().exec_driver_sql("SET TRANSACTION READ ONLY")
            statements = [0]

            def count_statement(*_args: object, counter: list[int] = statements) -> None:
                counter[0] += 1

            engine = session.get_bind()
            event.listen(engine, "before_cursor_execute", count_statement)
            try:
                tracemalloc.start()
                started = time.perf_counter()
                cards = _commercial_triage_cards(session, 50)
                elapsed = time.perf_counter() - started
                _, peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
            finally:
                event.remove(engine, "before_cursor_execute", count_statement)
                session.rollback()
        serialized = canonical(cards)
        if first_card_bytes is None:
            first_card_bytes = serialized
        elif serialized != first_card_bytes:
            raise AssertionError("repeated read-only page output changed within one process")
        page_runs.append(
            {
                "run": run_name,
                "groups": len(cards),
                "related_needs": sum(len(card["related_need_ids"]) for card in cards),
                "query_count": statements[0],
                "elapsed_seconds": elapsed,
                "peak_python_bytes": peak,
                "serialized_card_bytes": len(serialized),
                "card_json_sha256": hashlib.sha256(serialized).hexdigest(),
            }
        )
    card_groups = [card["related_need_ids"] for card in cards]
    if card_groups != expected_groups[:50]:
        raise AssertionError("hydrated first page groups differ from the frozen oracle")
    card_bytes = canonical(cards)
    card_sha = hashlib.sha256(card_bytes).hexdigest()
    if card_bytes != page_oracle_bytes:
        raise AssertionError(
            "selected canonical page differs from the matched preoptimization page"
        )
    baseline_runs = {row["run"]: row for row in page_measurement["measurements"]}
    result.update(
        {
            "database": "gl3audit_a5_corpus_test",
            "eligible_signals": len(summary_ids),
            "eligible_groups": len(actual_groups),
            "selected_groups": len(cards),
            "selected_need_count": len(selected_ids),
            "selected_card_json_bytes": len(card_bytes),
            "selected_card_sha256": card_sha,
            "summary_diagnostics": summary_diagnostics,
            "matched_page_oracle_sha256": page_oracle_sha,
            "matched_page_oracle_local_date": page_measurement["local_date"],
            "measurements": page_runs,
            "matched_preoptimization_measurements": page_measurement["measurements"],
            "matched_deltas": [
                {
                    "run": current["run"],
                    "query_delta": current["query_count"]
                    - baseline_runs[current["run"]]["query_count"],
                    "elapsed_seconds_delta": current["elapsed_seconds"]
                    - baseline_runs[current["run"]]["latency_seconds"],
                    "peak_python_bytes_delta": current["peak_python_bytes"]
                    - baseline_runs[current["run"]]["peak_python_bytes"],
                }
                for current in page_runs
            ],
            "semantic_parity": "PASS",
        }
    )
    rendered_result = json.dumps(result, sort_keys=True)
    if output_path is not None:
        with output_path.open("x", encoding="utf-8") as output_file:
            output_file.write(rendered_result + "\n")
    print(rendered_result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
