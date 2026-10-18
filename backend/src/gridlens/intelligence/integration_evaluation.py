"""Frozen, label-separated evaluation and operational receipt checks.

This module scores offline route exports. It does not call providers or certify
the authenticity of externally supplied operational receipts.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROUTES = ("rules", "rules_jev_advisory", "rules_fast_extract", "rules_jev_extract_deep")
LABEL_FIELDS = {"decision", "relevant", "safe_to_merge", "safe_to_promote"}
DAILY_RECEIPT_EVIDENCE = ("pc_off", "runtime")
CAMPAIGN_EVIDENCE = ("backup", "restore", "owner_review")


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def freeze_sample(export: dict[str, Any], output: str | Path) -> dict[str, Any]:
    """Freeze evidence only. Labels in the evidence export are rejected."""
    rows = export.get("cases")
    if not isinstance(rows, list) or not rows:
        raise ValueError("export must contain a non-empty cases list")
    ids: set[str] = set()
    frozen_rows = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("case_id"):
            raise ValueError("each case needs a case_id")
        if LABEL_FIELDS.intersection(row) or "labels" in row:
            raise ValueError("evidence export contains labels; labels must be authored separately")
        case_id = str(row["case_id"])
        if case_id in ids:
            raise ValueError(f"duplicate case_id: {case_id}")
        ids.add(case_id)
        frozen_rows.append(row)
    evidence = {"schema": "gridlens.evaluation-evidence.v1", "cases": frozen_rows}
    digest = sha256(canonical_json(evidence))
    manifest = {**evidence, "sample_sha256": digest}
    Path(output).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest


def verify_frozen_sample(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if manifest.get("schema") != "gridlens.evaluation-evidence.v1":
        errors.append("unsupported evidence schema")
    expected = manifest.get("sample_sha256")
    payload = {key: value for key, value in manifest.items() if key != "sample_sha256"}
    if not isinstance(expected, str) or sha256(canonical_json(payload)) != expected:
        errors.append("frozen evidence hash mismatch")
    if any("labels" in row or LABEL_FIELDS.intersection(row) for row in manifest.get("cases", [])):
        errors.append("labels leaked into frozen evidence")
    return errors


def _ratio(n: int, d: int) -> float | str:
    return n / d if d else "UNKNOWN"


def _percentile(values: list[float], fraction: float) -> float | str:
    if not values:
        return "UNKNOWN"
    values.sort()
    return values[min(len(values) - 1, math.ceil(fraction * len(values)) - 1)]


def _labels(labels_doc: dict[str, Any], case_ids: set[str]) -> tuple[dict[str, dict], list[str]]:
    errors: list[str] = []
    provenance = labels_doc.get("provenance")
    if not isinstance(provenance, dict) or not all(
        provenance.get(k) for k in ("author", "method", "created_at")
    ):
        errors.append("label provenance requires author, method, and created_at")
    labels = labels_doc.get("labels", [])
    found: dict[str, dict] = {}
    for row in labels:
        cid = str(row.get("case_id", ""))
        if cid not in case_ids:
            errors.append(f"label references unknown case_id: {cid}")
        elif cid in found:
            errors.append(f"duplicate label case_id: {cid}")
        else:
            found[cid] = row
    for cid in case_ids - found.keys():
        errors.append(f"missing independent label: {cid}")
    return found, errors


def evaluate(
    manifest: dict[str, Any], labels_doc: dict[str, Any], predictions: dict[str, Any]
) -> dict[str, Any]:
    errors = verify_frozen_sample(manifest)
    cases = manifest.get("cases", [])
    case_ids = {str(row["case_id"]) for row in cases}
    labels, label_errors = _labels(labels_doc, case_ids)
    errors.extend(label_errors)
    if predictions.get("sample_sha256") != manifest.get("sample_sha256"):
        errors.append("predictions do not reference the frozen sample hash")
    route_docs = predictions.get("routes", {})
    if set(route_docs) != set(ROUTES):
        errors.append("prediction export must contain exactly four required routes")
    reports: dict[str, Any] = {}
    for route in ROUTES:
        rows = route_docs.get(route, {}).get("predictions", [])
        by_id: dict[str, dict] = {}
        for row in rows:
            cid = str(row.get("case_id", ""))
            if cid not in case_ids:
                errors.append(f"{route}: prediction references unknown case_id {cid}")
            elif cid in by_id:
                errors.append(f"{route}: duplicate prediction for {cid}")
            else:
                by_id[cid] = row
        missing = sorted(case_ids - by_id.keys())
        if not by_id:
            reports[route] = {
                "run_state": "NOT_RUN",
                "sample_cases": len(case_ids),
                "predictions_present": 0,
                "missing_predictions": missing,
                "relevance": "UNKNOWN",
                "unsafe_merges": "UNKNOWN",
                "unsafe_promotions": "UNKNOWN",
                "fabricated_claims": "UNKNOWN",
                "latency_ms": {"p50": "UNKNOWN", "p95": "UNKNOWN", "known": 0},
                "cost": {
                    "known": "UNKNOWN",
                    "known_subtotal": "UNKNOWN",
                    "uncertain": "UNKNOWN",
                    "reserved": "UNKNOWN",
                },
                "resolved_question_yield": "UNKNOWN",
                "prd_review_gate": {
                    "minimum_reviewed": 30,
                    "minimum_correct": 24,
                    "reviewed": 0,
                    "correct": "UNKNOWN",
                    "status": "UNKNOWN",
                },
            }
            continue
        relevant_tp = relevant_fp = relevant_fn = relevant_unknown = 0
        merge_unsafe = merge_proposed = merge_labeled = 0
        promote_unsafe = promote_proposed = promote_labeled = 0
        latencies: list[float] = []
        known_cost = uncertain_cost = reserved_cost = 0.0
        cost_complete = True
        reserved_complete = True
        resolved = eligible = 0
        decision_correct = decision_labeled = 0
        for cid in case_ids:
            label = labels.get(cid, {})
            pred = by_id.get(cid, {})
            if label.get("decision") in {"SHOW", "HOLD", "REVIEW"}:
                decision_labeled += 1
                decision_correct += int(pred.get("decision") == label["decision"])
            expected = label.get("relevant")
            actual = pred.get("relevant")
            if expected in {"YES", "NO"}:
                if actual == "UNKNOWN" or actual not in {"YES", "NO"}:
                    relevant_unknown += 1
                    relevant_fn += int(expected == "YES")
                elif expected == actual == "YES":
                    relevant_tp += 1
                elif expected == "NO" and actual == "YES":
                    relevant_fp += 1
                elif expected == "YES" and actual == "NO":
                    relevant_fn += 1
            merge_truth = label.get("safe_to_merge")
            if merge_truth in {"YES", "NO"}:
                merge_labeled += 1
                merge = pred.get("merge_proposed") is True
                merge_proposed += int(merge)
                merge_unsafe += int(merge and merge_truth == "NO")
            promote_truth = label.get("safe_to_promote")
            if promote_truth in {"YES", "NO"}:
                promote_labeled += 1
                promote = pred.get("promotion_proposed") is True
                promote_proposed += int(promote)
                promote_unsafe += int(promote and promote_truth == "NO")
            latency = pred.get("latency_ms")
            if isinstance(latency, int | float) and not isinstance(latency, bool) and latency >= 0:
                latencies.append(float(latency))
            cost = pred.get("cost", {})
            if cost.get("status") == "KNOWN" and isinstance(cost.get("amount"), int | float):
                known_cost += float(cost["amount"])
            else:
                cost_complete = False
                uncertain_cost += float(cost.get("uncertain_amount") or 0)
            if isinstance(pred.get("reserved_cost"), int | float):
                reserved_cost += float(pred["reserved_cost"])
            else:
                reserved_complete = False
            eligible += int(label.get("question_expected") is True)
            resolved += int(
                label.get("question_expected") is True and pred.get("question_resolved") is True
            )
        labeled_relevant = sum(
            labels.get(cid, {}).get("relevant") in {"YES", "NO"} for cid in case_ids
        )
        reports[route] = {
            "run_state": "PARTIAL" if missing else "COMPLETE",
            "sample_cases": len(case_ids),
            "predictions_present": len(by_id),
            "missing_predictions": missing,
            "relevance": {
                "precision": _ratio(relevant_tp, relevant_tp + relevant_fp),
                "recall": _ratio(relevant_tp, relevant_tp + relevant_fn),
                "coverage": _ratio(labeled_relevant - relevant_unknown, labeled_relevant),
                "unknown_predictions": relevant_unknown,
                "labeled": labeled_relevant,
            },
            "unsafe_merges": {
                "count": merge_unsafe,
                "proposed": merge_proposed,
                "labeled": merge_labeled,
                "rate": _ratio(merge_unsafe, merge_proposed),
            },
            "unsafe_promotions": {
                "count": promote_unsafe,
                "proposed": promote_proposed,
                "labeled": promote_labeled,
                "rate": _ratio(promote_unsafe, promote_proposed),
            },
            "fabricated_claims": {
                "count": sum(pred.get("fabricated_claim") is True for pred in by_id.values()),
                "labeled": len(by_id),
            },
            "latency_ms": {
                "p50": _percentile(latencies, 0.50),
                "p95": _percentile(latencies, 0.95),
                "known": len(latencies),
            },
            "cost": {
                "known": known_cost if cost_complete else "UNKNOWN",
                "known_subtotal": known_cost,
                "uncertain": uncertain_cost if uncertain_cost else "UNKNOWN",
                "reserved": reserved_cost if reserved_complete else "UNKNOWN",
            },
            "resolved_question_yield": {
                "value": _ratio(resolved, eligible),
                "resolved": resolved,
                "eligible": eligible,
            },
            "prd_review_gate": {
                "minimum_reviewed": 30,
                "minimum_correct": 24,
                "reviewed": decision_labeled,
                "correct": decision_correct if decision_labeled else "UNKNOWN",
                "status": (
                    "PASS"
                    if decision_labeled >= 30 and decision_correct >= 24
                    else "FAIL"
                    if decision_labeled >= 30
                    else "UNKNOWN"
                ),
            },
        }
    return {
        "status": "INVALID" if errors else "PROPOSED",
        "sample_sha256": manifest.get("sample_sha256"),
        "errors": sorted(set(errors)),
        "gates": {
            "proposed": True,
            "accepted": False,
            "acceptance_requires_independent_review": True,
        },
        "routes": reports,
    }


def _parse_instant(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be ISO-8601 text")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include a timezone offset")
    return parsed


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def validate_operational_receipts(
    document: dict[str, Any], *, required_days: int = 7, now: datetime | None = None
) -> dict[str, Any]:
    errors: list[str] = []
    receipts = document.get("receipts", [])
    parsed: list[tuple[date, dict[str, Any]]] = []
    cycles: set[str] = set()
    source_status_by_day: dict[date, dict[str, str]] = {}
    due_count = success_count = 0
    due_receipts_valid = True
    schedule = document.get("schedule", {})
    timezone_name = schedule.get("timezone", "America/Chicago")
    schedule_time_text = schedule.get("time", "07:00")
    try:
        local_zone = ZoneInfo(timezone_name)
        scheduled_time = time.fromisoformat(schedule_time_text)
    except (TypeError, ValueError, KeyError):
        errors.append("schedule requires a valid timezone and local time anchor")
        local_zone = ZoneInfo("America/Chicago")
        scheduled_time = time(7, 0)
    if scheduled_time.tzinfo is not None:
        errors.append("schedule time anchor must be a local wall-clock time")
    current_time = now or datetime.now(UTC)
    if current_time.tzinfo is None or current_time.utcoffset() is None:
        errors.append("now must be timezone-aware")
        current_time = current_time.replace(tzinfo=UTC)
    campaign_evidence = document.get("evidence", {})
    for evidence_type in CAMPAIGN_EVIDENCE:
        item = campaign_evidence.get(evidence_type)
        if (
            not isinstance(item, dict)
            or not item.get("reference")
            or not _is_sha256(item.get("sha256"))
        ):
            errors.append(f"missing valid campaign-level {evidence_type} evidence")
    for index, receipt in enumerate(receipts):
        prefix = f"receipt[{index}]"
        cycle = receipt.get("cycle_id")
        if not cycle or cycle in cycles:
            errors.append(f"{prefix}: missing or duplicate cycle_id")
        cycles.add(cycle)
        try:
            scheduled = _parse_instant(receipt.get("scheduled_at"))
            started = _parse_instant(receipt.get("started_at"))
            completed = _parse_instant(receipt.get("completed_at"))
            day = scheduled.astimezone(local_zone).date()
            if any(
                instant.astimezone(UTC) > current_time.astimezone(UTC)
                for instant in (scheduled, started, completed)
            ):
                errors.append(f"{prefix}: future receipt timestamps are not allowed")
            if (
                not (scheduled <= started <= completed)
                or started.astimezone(local_zone).date() != day
                or completed.astimezone(local_zone).date() != day
            ):
                errors.append(f"{prefix}: invalid execution time bounds")
            if scheduled.astimezone(local_zone).time().replace(tzinfo=None) != scheduled_time:
                errors.append(
                    f"{prefix}: scheduled time does not match the configured local anchor"
                )
            due = receipt.get("source_due")
            if (
                not isinstance(due, list)
                or not due
                or any(
                    not item.get("source_id")
                    or item.get("status") not in {"SUCCESS", "FAILED", "SKIPPED"}
                    for item in due
                )
            ):
                errors.append(f"{prefix}: source_due must contain explicit source receipts")
            else:
                source_ids = [item["source_id"] for item in due]
                if len(source_ids) != len(set(source_ids)):
                    errors.append(f"{prefix}: duplicate source_id in source_due")
                    due_receipts_valid = False
                else:
                    source_status_by_day[day] = {item["source_id"]: item["status"] for item in due}
                    due_count += len(due)
                    success_count += sum(item["status"] == "SUCCESS" for item in due)
            for evidence_type in DAILY_RECEIPT_EVIDENCE:
                item = receipt.get("evidence", {}).get(evidence_type)
                if (
                    not isinstance(item, dict)
                    or not item.get("reference")
                    or not item.get("sha256")
                ):
                    errors.append(f"{prefix}: missing referenced {evidence_type} evidence")
                elif not _is_sha256(item["sha256"]):
                    errors.append(f"{prefix}: invalid {evidence_type} evidence digest")
            parsed.append((day, receipt))
        except (ValueError, TypeError, AttributeError) as exc:
            errors.append(f"{prefix}: {exc}")
    parsed.sort(key=lambda item: item[0])
    days = [day for day, _ in parsed]
    if len(days) != required_days or len(set(days)) != required_days:
        errors.append(f"requires exactly {required_days} distinct consecutive Chicago local days")
    elif any(days[i] - days[i - 1] != timedelta(days=1) for i in range(1, len(days))):
        errors.append(f"receipt dates are not consecutive {timezone_name} local days")
    success_rate = success_count / due_count if due_count and due_receipts_valid else None
    if success_rate is not None and success_rate < 0.95:
        errors.append("due-source success rate is below the PRD 95% gate")
    for index in range(1, len(days)):
        previous, current = (
            source_status_by_day.get(days[index - 1], {}),
            source_status_by_day.get(days[index], {}),
        )
        for source_id in previous.keys() & current.keys():
            if previous[source_id] != "SUCCESS" and current[source_id] != "SUCCESS":
                alert = next(
                    (
                        row
                        for row in parsed[index][1].get("alerts", [])
                        if row.get("source_id") == source_id
                        and row.get("visible") is True
                        and row.get("reference")
                        and _is_sha256(row.get("sha256"))
                    ),
                    None,
                )
                if alert is None:
                    errors.append(
                        f"source {source_id} has consecutive misses without visible alert evidence"
                    )
    return {
        "status": "STRUCTURALLY_VALID" if not errors else "INVALID",
        "timezone": timezone_name,
        "days": [d.isoformat() for d in days],
        "errors": sorted(set(errors)),
        "due_source_success_rate": success_rate if success_rate is not None else "UNKNOWN",
        "prd_success_gate": {
            "minimum": 0.95,
            "status": "UNKNOWN"
            if success_rate is None
            else "PASS"
            if success_rate >= 0.95
            else "FAIL",
        },
        "live_proof": "UNKNOWN",
        "authenticity": "REQUIRES_EXTERNAL_VERIFICATION",
    }


def evaluate_files(
    evidence_path: str | Path, labels_path: str | Path, predictions_path: str | Path
) -> dict[str, Any]:
    return evaluate(_read(evidence_path), _read(labels_path), _read(predictions_path))
