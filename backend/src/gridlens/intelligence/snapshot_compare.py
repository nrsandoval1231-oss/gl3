"""Fail-closed comparison for deterministic operational snapshots."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

REQUIRED_TABLES = {
    "evidence",
    "jobs",
    "logical_calls",
    "settlements",
    "budgets",
    "monitor_watches",
    "monitor_sources",
}
SNAPSHOT_VERSION = 3
TOOL_VERSION = "intelligence-snapshot-v3"


def compare(before: dict[str, Any], after: dict[str, Any], reference: str = "") -> dict[str, Any]:
    issues = []
    before_tables = before.get("tables", {})
    after_tables = after.get("tables", {})
    if (
        before.get("version") != SNAPSHOT_VERSION
        or after.get("version") != SNAPSHOT_VERSION
        or before.get("tool_version") != TOOL_VERSION
        or after.get("tool_version") != TOOL_VERSION
    ):
        issues.append("snapshot_version_or_tool_mismatch")
    if not isinstance(before_tables, dict) or not isinstance(after_tables, dict):
        return {
            "version": SNAPSHOT_VERSION,
            "result": "MISMATCH",
            "issues": ["table_metadata_missing"],
        }
    if not REQUIRED_TABLES.issubset(before_tables) or not REQUIRED_TABLES.issubset(after_tables):
        issues.append("required_table_metadata_missing")
    for table in REQUIRED_TABLES:
        left, right = before_tables.get(table), after_tables.get(table)
        if right is None or left != right:
            issues.append(f"{table}_changed_or_missing")
    if before.get("logical_call_exposure") != after.get("logical_call_exposure"):
        issues.append("logical_call_exposure_changed_or_unknown")
    if (
        before.get("migration_head") != after.get("migration_head")
        or after.get("migration_head") == "UNKNOWN"
    ):
        issues.append("migration_head_mismatch_or_unknown")
    before_digest = hashlib.sha256(
        json.dumps(before, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    after_digest = hashlib.sha256(
        json.dumps(after, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "version": SNAPSHOT_VERSION,
        "tool_version": TOOL_VERSION,
        "compared_at": datetime.now(UTC).isoformat(),
        "reference": reference,
        "before_digest": before_digest,
        "after_digest": after_digest,
        "result": "MATCH" if not issues else "MISMATCH",
        "issues": issues,
    }
