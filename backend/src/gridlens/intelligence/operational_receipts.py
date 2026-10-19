"""Parse configured operational receipt data without treating it as authority."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

MAX_RECEIPT_BYTES = 16_384
RECEIPT_VERSION = 1
REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,499}$")
HASH_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
CASE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_-]{0,119}$")
REVIEWER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .,'-]{0,119}$")
REVIEW_DECISIONS = {"SUPPORTED", "CONFLICT", "UNRESOLVED", "OTHER"}


def _valid_reference(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(REFERENCE_PATTERN.fullmatch(value))
        and "@" not in value.split("://", 1)[0]
    )


def _commercial_review_receipt(value: Any, now: datetime) -> dict[str, Any]:
    unknown: dict[str, Any] = {
        "status": "UNKNOWN",
        "reported_case_count": None,
        "decision_counts": None,
        "reviewer": None,
        "reviewed_at": None,
        "sample_sha256": None,
        "context_sha256": None,
        "cases": [],
        "independent_labels": "UNKNOWN",
        "quality_verification": "UNKNOWN",
        "acceptance": "UNKNOWN",
    }
    if value is None:
        return unknown
    if not isinstance(value, dict):
        return {**unknown, "reason": "invalid_schema"}
    if set(value) != {
        "reviewer",
        "reviewed_at",
        "sample_sha256",
        "context_sha256",
        "cases",
    }:
        return {**unknown, "reason": "invalid_schema"}
    reviewer = value.get("reviewer")
    sample_hash = value.get("sample_sha256")
    context_hash = value.get("context_sha256")
    cases = value.get("cases")
    if (
        not isinstance(reviewer, str)
        or not REVIEWER_PATTERN.fullmatch(reviewer)
        or not isinstance(sample_hash, str)
        or not HASH_PATTERN.fullmatch(sample_hash)
        or not isinstance(context_hash, str)
        or not HASH_PATTERN.fullmatch(context_hash)
        or not isinstance(cases, list)
        or not 1 <= len(cases) <= 100
    ):
        return {**unknown, "reason": "invalid_schema"}
    try:
        reviewed_at = datetime.fromisoformat(value["reviewed_at"].replace("Z", "+00:00"))
    except (KeyError, AttributeError, TypeError, ValueError):
        return {**unknown, "reason": "invalid_date"}
    if reviewed_at.tzinfo is None or reviewed_at > now + timedelta(minutes=5):
        return {**unknown, "reason": "invalid_date"}
    clean_cases = []
    case_ids: set[str] = set()
    counts = {decision: 0 for decision in REVIEW_DECISIONS}
    for case in cases:
        if not isinstance(case, dict) or set(case) != {
            "case_id",
            "need_id",
            "evidence_refs",
            "decision",
        }:
            return {**unknown, "reason": "invalid_case"}
        case_id = case.get("case_id")
        need_id = case.get("need_id")
        refs = case.get("evidence_refs")
        decision = case.get("decision")
        if (
            not isinstance(case_id, str)
            or not CASE_PATTERN.fullmatch(case_id)
            or case_id in case_ids
            or not isinstance(need_id, str)
            or not isinstance(refs, list)
            or not 1 <= len(refs) <= 20
            or decision not in REVIEW_DECISIONS
        ):
            return {**unknown, "reason": "invalid_case"}
        try:
            need_id = str(UUID(need_id))
        except ValueError:
            return {**unknown, "reason": "invalid_case"}
        clean_refs = []
        for ref in refs:
            if not isinstance(ref, dict) or set(ref) != {"evidence_id", "content_hash"}:
                return {**unknown, "reason": "invalid_evidence_reference"}
            try:
                evidence_id = str(UUID(ref["evidence_id"]))
            except (KeyError, TypeError, ValueError):
                return {**unknown, "reason": "invalid_evidence_reference"}
            content_hash = ref.get("content_hash")
            if not isinstance(content_hash, str) or not HASH_PATTERN.fullmatch(content_hash):
                return {**unknown, "reason": "invalid_evidence_reference"}
            clean_refs.append({"evidence_id": evidence_id, "content_hash": content_hash.lower()})
        case_ids.add(case_id)
        counts[decision] += 1
        clean_cases.append(
            {
                "case_id": case_id,
                "need_id": need_id,
                "evidence_refs": clean_refs,
                "decision": decision,
            }
        )
    return {
        "status": "REPORTED",
        "reported_case_count": len(clean_cases),
        "decision_counts": counts,
        "reviewer": reviewer,
        "reviewed_at": reviewed_at.astimezone(UTC).isoformat(),
        "sample_sha256": sample_hash.lower(),
        "context_sha256": context_hash.lower(),
        "cases": clean_cases,
        "independent_labels": "UNKNOWN",
        "quality_verification": "UNVERIFIED",
        "acceptance": "UNKNOWN",
    }


def load_operational_receipt(path: str) -> dict[str, Any]:
    """Return reported receipt metadata; verification requires attributable restore proof."""
    unknown = {
        "status": "UNKNOWN",
        "backup": "UNKNOWN",
        "restore": "UNKNOWN",
        "last_verified_restore_at": None,
        "last_reported_restore_at": None,
        "commercial_review": _commercial_review_receipt(None, datetime.now(UTC)),
    }
    if not path:
        return unknown
    try:
        file_path = Path(path)
        if not file_path.is_file():
            return {**unknown, "reason": "invalid_or_missing"}
        with file_path.open("rb") as source:
            raw = source.read(MAX_RECEIPT_BYTES + 1)
        if len(raw) > MAX_RECEIPT_BYTES:
            return {**unknown, "reason": "oversized"}
        data = json.loads(raw)
        if (
            not isinstance(data, dict)
            or type(data.get("version")) is not int
            or data.get("version") != RECEIPT_VERSION
        ):
            return {**unknown, "reason": "invalid_schema"}
        recorded = datetime.fromisoformat(data["recorded_at"].replace("Z", "+00:00"))
        now = datetime.now(UTC)
        if recorded.tzinfo is None or recorded > now + timedelta(minutes=5):
            return {**unknown, "reason": "invalid_date"}
        backup_ref = data.get("backup_reference")
        restore = data.get("restore_comparison")
        reference = restore.get("reference") if isinstance(restore, dict) else None
        reported_match = (
            isinstance(restore, dict)
            and restore.get("result") == "MATCH"
            and _valid_reference(reference)
            and isinstance(restore.get("before_digest"), str)
            and bool(HASH_PATTERN.fullmatch(restore["before_digest"]))
            and isinstance(restore.get("after_digest"), str)
            and bool(HASH_PATTERN.fullmatch(restore["after_digest"]))
            and restore["before_digest"] == restore["after_digest"]
            and isinstance(restore.get("tool_version"), str)
            and 1 <= len(restore["tool_version"].strip()) <= 80
            and isinstance(restore.get("compared_at"), str)
        )
        compared_at = None
        if reported_match:
            assert isinstance(restore, dict)
            compared_at = datetime.fromisoformat(restore["compared_at"].replace("Z", "+00:00"))
            reported_match = compared_at.tzinfo is not None and compared_at <= now + timedelta(
                minutes=5
            )
        return {
            "status": "REPORTED",
            "recorded_at": recorded.astimezone(UTC).isoformat(),
            "backup": "REPORTED" if _valid_reference(backup_ref) else "UNKNOWN",
            "backup_reference": backup_ref if _valid_reference(backup_ref) else None,
            "restore": "REPORTED_MATCH" if reported_match else "UNKNOWN",
            "restore_reference": reference if reported_match else None,
            "last_verified_restore_at": None,
            "last_reported_restore_at": compared_at.astimezone(UTC).isoformat()
            if reported_match and compared_at
            else None,
            "authenticity": "UNVERIFIED",
            "commercial_review": _commercial_review_receipt(data.get("commercial_review"), now),
        }
    except (OSError, UnicodeError, ValueError, TypeError, KeyError):
        return {**unknown, "reason": "invalid_or_missing"}
