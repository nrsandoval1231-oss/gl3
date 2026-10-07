"""Read-only inventory of lifecycle events affected by current support policy."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from gridlens.domain.lifecycle import classify_event  # noqa: E402
from gridlens.ingestion.adapters.retained_permits import (  # noqa: E402
    reported_permit_event_type,
    requires_achieved_lifecycle_milestone,
)
from gridlens.intelligence.lifecycle_service import lifecycle_event_supported  # noqa: E402

TABLES = (
    "evidence",
    "interpretations",
    "lifecycle_events",
    "observations",
    "project_lifecycles",
    "projects",
)


def _table_fingerprints(connection) -> dict[str, dict[str, Any]]:
    inspector = inspect(connection)
    preparer = connection.engine.dialect.identifier_preparer
    results: dict[str, dict[str, Any]] = {}
    for table in TABLES:
        primary_key = inspector.get_pk_constraint(table)
        columns = primary_key.get("constrained_columns") or []
        if not columns:
            raise RuntimeError(f"Expected a primary key for {table}")
        table_name = preparer.quote_identifier(table)
        order_by = ", ".join(preparer.quote_identifier(column) for column in columns)
        count = connection.execute(text(f"SELECT count(*) FROM {table_name}")).scalar_one()
        rows = connection.execute(
            text(
                f"SELECT to_jsonb(row_data)::text FROM {table_name} AS row_data ORDER BY {order_by}"
            )
        )
        digest = hashlib.sha256()
        for (row_text,) in rows:
            digest.update(row_text.encode("utf-8"))
            digest.update(b"\n")
        results[table] = {"rows": count, "sha256": digest.hexdigest()}
    return results


def _inventory(connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        text(
            """
            SELECT
                le.id::text AS event_id,
                le.project_id::text AS project_id,
                p.identity_key AS project_identity_key,
                p.name AS project_name,
                p.asset_type AS project_asset_type,
                le.observation_id::text AS observation_id,
                o.source_id,
                le.evidence_id::text AS evidence_id,
                e.url AS source_url,
                e.title AS evidence_title,
                e.abstract AS evidence_abstract,
                e.content_hash AS evidence_hash,
                e.event_date,
                e.event_date_label,
                o.content_hash AS observation_hash,
                le.event_type AS retained_event_type,
                le.state AS retained_state,
                i.status AS interpretation_status,
                i.content_hash AS interpretation_hash,
                i.assessment AS interpretation_assessment,
                pl.current_state AS projected_state
            FROM lifecycle_events AS le
            JOIN projects AS p ON p.id = le.project_id
            JOIN observations AS o ON o.id = le.observation_id
            JOIN evidence AS e ON e.id = le.evidence_id
            LEFT JOIN interpretations AS i ON i.observation_id = le.observation_id
            LEFT JOIN project_lifecycles AS pl ON pl.project_id = le.project_id
            ORDER BY le.project_id, le.observation_id, le.id
            """
        )
    ).mappings()
    inventory = []
    for row in rows:
        source_id = row["source_id"]
        is_rrc = source_id == "texas-rrc-drilling-permits"
        classification = classify_event(
            "Drilling permit" if is_rrc else row["evidence_title"],
            None if is_rrc else row["evidence_abstract"],
            project_name=row["project_name"],
            project_identity_key=row["project_identity_key"],
            project_asset_type=row["project_asset_type"],
            reported_permit_event=reported_permit_event_type(
                source_id,
                row["evidence_title"],
                row["evidence_abstract"],
                row["event_date"],
                row["event_date_label"],
            ),
            require_achieved_milestone=requires_achieved_lifecycle_milestone(source_id),
        )
        assessment = row["interpretation_assessment"] or {}
        evidence = SimpleNamespace(
            content_hash=row["evidence_hash"],
            title=row["evidence_title"],
            abstract=row["evidence_abstract"],
            event_date=row["event_date"],
            event_date_label=row["event_date_label"],
            observation=SimpleNamespace(
                source_id=source_id,
                content_hash=row["observation_hash"],
            ),
        )
        interpretation = SimpleNamespace(
            status=row["interpretation_status"],
            content_hash=row["interpretation_hash"],
            assessment=assessment,
        )
        project = SimpleNamespace(
            name=row["project_name"],
            identity_key=row["project_identity_key"],
            asset_type=row["project_asset_type"],
        )
        supported = lifecycle_event_supported(
            row["retained_event_type"],
            evidence,
            interpretation,
            project,
            row["retained_state"],
        )
        if supported:
            continue

        if not assessment:
            reason = "no retained interpretation assessment"
        elif row["observation_hash"] != row["evidence_hash"]:
            reason = "observation points to another current evidence version"
        elif row["interpretation_hash"] != row["evidence_hash"]:
            reason = "interpretation points to another evidence version"
        elif assessment.get("evidence_hash") != row["evidence_hash"]:
            reason = "interpretation is bound to another evidence version"
        elif assessment.get("project_identity_key") != row["project_identity_key"]:
            reason = "interpretation is bound to another project identity"
        elif classification is None:
            reason = "current evidence does not support an unambiguous lifecycle event"
        elif classification.event_type != row["retained_event_type"]:
            reason = (
                f"retained event type differs from current evidence ({classification.event_type})"
            )
        elif classification.state != row["retained_state"]:
            reason = f"retained state differs from current evidence ({classification.state})"
        elif row["interpretation_status"] not in {"accepted", "failed", "pending"}:
            reason = f"interpretation status is {row['interpretation_status']}"
        else:
            reason = "retained event does not meet current support rules"
        inventory.append(
            {
                "event_id": row["event_id"],
                "project_id": row["project_id"],
                "project_identity_key": row["project_identity_key"],
                "project_name": row["project_name"],
                "project_asset_type": row["project_asset_type"],
                "observation_id": row["observation_id"],
                "source_id": source_id,
                "evidence_id": row["evidence_id"],
                "source_url": row["source_url"],
                "evidence_title": row["evidence_title"],
                "evidence_hash": row["evidence_hash"],
                "interpretation_status": row["interpretation_status"],
                "retained_event_type": row["retained_event_type"],
                "retained_state": row["retained_state"],
                "proposed_event_type": classification.event_type if classification else None,
                "proposed_state": classification.state if classification else None,
                "support_outcome": "UNSUPPORTED_BY_CURRENT_POLICY",
                "reason": reason,
                "projected_state": row["projected_state"],
                "affects_current_projection": row["projected_state"] == row["retained_state"],
            }
        )
    return inventory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline", type=Path, required=True, help="Owner-provided corpus inventory JSON"
    )
    parser.add_argument("--output", type=Path, required=True, help="Local output JSON path")
    args = parser.parse_args()
    database_url = os.environ.get("LIFECYCLE_INVENTORY_DATABASE_URL")
    if not database_url:
        parser.error("Set LIFECYCLE_INVENTORY_DATABASE_URL to the authorized local corpus copy")
    target = make_url(database_url)
    if (
        target.database != "gl3audit_corpus_test"
        or target.host not in {"127.0.0.1", "localhost"}
        or target.port != 55437
        or target.username != "gl3audit"
    ):
        parser.error(
            "Refusing inventory: URL must identify local gl3audit_corpus_test on port 55437"
        )
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    if baseline.get("database") != "gl3audit_corpus_test":
        parser.error("Baseline manifest is not for gl3audit_corpus_test")

    engine = create_engine(
        database_url, connect_args={"options": "-c default_transaction_read_only=on"}
    )
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            before = _table_fingerprints(connection)
            suspects = _inventory(connection)
            after = _table_fingerprints(connection)
            transaction.commit()
    finally:
        engine.dispose()

    reference = {table: baseline.get("tables", {}).get(table) for table in TABLES}
    before_hash = hashlib.sha256(
        json.dumps(suspects, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    result = {
        "assessment": "READ_ONLY_ONLY",
        "database": target.database,
        "source_backup_sha256": baseline.get("backup_sha256"),
        "reference_baseline_tables": reference,
        "before_tables": before,
        "after_tables": after,
        "table_counts_and_hashes_unchanged": before == after,
        "suspect_event_count": len(suspects),
        "affected_project_count": len(
            {item["project_id"] for item in suspects if item["affects_current_projection"]}
        ),
        "suspect_inventory_sha256": before_hash,
        "suspects": suspects,
    }
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded, encoding="utf-8")
    print(
        json.dumps(
            {
                "assessment": result["assessment"],
                "database": result["database"],
                "suspect_event_count": result["suspect_event_count"],
                "affected_project_count": result["affected_project_count"],
                "table_counts_and_hashes_unchanged": result["table_counts_and_hashes_unchanged"],
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0 if result["table_counts_and_hashes_unchanged"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
