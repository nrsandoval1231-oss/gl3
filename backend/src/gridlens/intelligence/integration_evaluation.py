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
METRIC_FIELDS = (
    "source_freshness_hours",
    "end_to_end_latency_ms",
    "provider_latency_ms",
    "schema_valid",
    "queue_delay_ms",
    "queue_outcome",
    "reserved_cost",
)


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
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("case_id"), str)
            or not row["case_id"].strip()
        ):
            raise ValueError("each case needs a case_id")
        if LABEL_FIELDS.intersection(row) or "labels" in row:
            raise ValueError("evidence export contains labels; labels must be authored separately")
        if not isinstance(row["case_id"], str) or not row["case_id"].strip():
            raise ValueError("case_id must be non-empty text")
        case_id = row["case_id"]
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
    if not isinstance(manifest, dict):
        return ["frozen manifest must be an object"]
    if manifest.get("schema") != "gridlens.evaluation-evidence.v1":
        errors.append("unsupported evidence schema")
    expected = manifest.get("sample_sha256")
    payload = {key: value for key, value in manifest.items() if key != "sample_sha256"}
    try:
        digest_matches = isinstance(expected, str) and sha256(canonical_json(payload)) == expected
    except (TypeError, ValueError):
        digest_matches = False
    if not digest_matches:
        errors.append("frozen evidence hash mismatch")
    cases = manifest.get("cases", [])
    if not isinstance(cases, list):
        errors.append("frozen cases must be a list")
        cases = []
    found_ids: set[str] = set()
    for row in cases:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("case_id"), str)
            or not row["case_id"].strip()
        ):
            errors.append("each frozen case requires a non-empty text case_id")
            continue
        if row["case_id"] in found_ids:
            errors.append(f"duplicate frozen case_id: {row['case_id']}")
        found_ids.add(row["case_id"])
        if "labels" in row or LABEL_FIELDS.intersection(row):
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
    if not isinstance(labels_doc, dict):
        return {}, ["independent labels document must be an object"]
    provenance = labels_doc.get("provenance")
    if not isinstance(provenance, dict) or not all(
        isinstance(provenance.get(key), str) and provenance[key].strip()
        for key in ("author", "method", "created_at")
    ):
        errors.append("label provenance requires author, method, and created_at")
    labels = labels_doc.get("labels", [])
    if not isinstance(labels, list):
        return {}, [*errors, "independent labels must be a list"]
    found: dict[str, dict] = {}
    for row in labels:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("case_id"), str)
            or not row["case_id"].strip()
        ):
            errors.append("each independent label requires a text case_id")
            continue
        cid = row["case_id"]
        for field, allowed in (
            ("decision", {"SHOW", "HOLD", "REVIEW", None}),
            ("relevant", {"YES", "NO", None}),
            ("safe_to_merge", {"YES", "NO", None}),
            ("safe_to_promote", {"YES", "NO", None}),
        ):
            if (
                field in row
                and row[field] is not None
                and (not isinstance(row[field], str) or row[field] not in allowed)
            ):
                errors.append(f"label {cid}: invalid {field}")
        if (
            "question_expected" in row
            and row["question_expected"] is not None
            and not isinstance(row["question_expected"], bool)
        ):
            errors.append(f"label {cid}: question_expected must be boolean")
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
    if not isinstance(manifest, dict):
        manifest = {}
    if not isinstance(predictions, dict):
        errors.append("prediction export must be an object")
        predictions = {}
    cases = manifest.get("cases", [])
    if not isinstance(cases, list):
        cases = []
    case_ids = {
        row["case_id"]
        for row in cases
        if isinstance(row, dict) and isinstance(row.get("case_id"), str) and row["case_id"].strip()
    }
    labels, label_errors = _labels(labels_doc, case_ids)
    errors.extend(label_errors)
    if predictions.get("sample_sha256") != manifest.get("sample_sha256"):
        errors.append("predictions do not reference the frozen sample hash")
    route_docs = predictions.get("routes", {})
    if not isinstance(route_docs, dict):
        errors.append("routes must be an object")
        route_docs = {}
    if set(route_docs) != set(ROUTES):
        errors.append("prediction export must contain exactly four required routes")
    reports: dict[str, Any] = {}
    versions = predictions.get("versions", {})
    if not isinstance(versions, dict):
        errors.append("prediction versions must be an object")
        versions = {}
    for key in ("frozen_sample_sha256", "context_version", "route_versions"):
        if not versions.get(key):
            errors.append(f"prediction versions require {key}")
    if versions.get("context_version") is not None and not isinstance(
        versions.get("context_version"), str
    ):
        errors.append("context_version must be text")
    if versions.get("frozen_sample_sha256") != manifest.get("sample_sha256"):
        errors.append("prediction frozen-sample version mismatch")
    route_versions = versions.get("route_versions", {})
    if not isinstance(route_versions, dict) or set(route_versions) != set(ROUTES):
        errors.append("route_versions must identify exactly four routes")
    elif any(not isinstance(value, str) or not value.strip() for value in route_versions.values()):
        errors.append("each route version must be non-empty text")
    for route in ROUTES:
        route_doc = route_docs.get(route, {})
        if not isinstance(route_doc, dict):
            errors.append(f"{route}: route export must be an object")
            route_doc = {}
        if route_doc.get("version") != route_versions.get(route):
            errors.append(f"{route}: inconsistent route version")
        provenance = route_doc.get("metric_provenance")
        if provenance is not None and (
            not isinstance(provenance, dict)
            or not isinstance(provenance.get("kind"), str)
            or not provenance.get("kind")
            or not isinstance(provenance.get("reference"), str)
            or not provenance.get("reference")
        ):
            errors.append(f"{route}: metric_provenance requires kind and reference")
        if route_doc.get("context_version", versions.get("context_version")) != versions.get(
            "context_version"
        ):
            errors.append(f"{route}: inconsistent context version")
        rows = route_doc.get("predictions", [])
        if not isinstance(rows, list):
            errors.append(f"{route}: predictions must be a list")
            rows = []
        by_id: dict[str, dict] = {}
        for row in rows:
            if not isinstance(row, dict):
                errors.append(f"{route}: each prediction must be an object")
                continue
            has_measurement = any(
                field in row
                for field in (*METRIC_FIELDS, "latency_ms", "cost", "fabricated_claim_review")
            )
            if has_measurement and provenance is None:
                errors.append(f"{route}: measured fields require metric_provenance")
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
                "end_to_end_latency_ms": {"p50": "UNKNOWN", "p95": "UNKNOWN", "known": 0},
                "provider_latency_ms": {"p50": "UNKNOWN", "p95": "UNKNOWN", "known": 0},
                "source_freshness_hours": {"p50": "UNKNOWN", "p95": "UNKNOWN", "known": 0},
                "model_schema_validity": {"valid": "UNKNOWN", "reviewed": 0, "coverage": "UNKNOWN"},
                "queue": {
                    "delay_ms_p50": "UNKNOWN",
                    "delay_ms_p95": "UNKNOWN",
                    "delay_known": 0,
                    "outcomes": "UNKNOWN",
                },
                "cost": {
                    "known": "UNKNOWN",
                    "known_subtotal": "UNKNOWN",
                    "uncertain": "UNKNOWN",
                    "reserved": "UNKNOWN",
                },
                "resolved_question_yield": "UNKNOWN",
                "cost_per_useful_independently_reviewed_result": "UNKNOWN",
                "metric_provenance": "UNKNOWN",
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
        provider_latencies: list[float] = []
        e2e_latencies: list[float] = []
        freshness_values: list[float] = []
        queue_delays: list[float] = []
        known_cost = uncertain_cost = reserved_cost = 0.0
        known_cost_rows = uncertain_cost_rows = 0
        cost_complete = True
        reserved_complete = True
        fabricated_reviewed = fabricated_count = 0
        schema_reviewed = schema_valid = 0
        queue_outcomes: dict[str, int] = {}
        queue_outcome_rows = 0
        useful_reviewed = 0
        resolved = eligible = 0
        unknown_question_expectation = 0
        decision_correct = decision_labeled = 0
        for cid in case_ids:
            label = labels.get(cid, {})
            pred = by_id.get(cid, {})
            label_decision = label.get("decision")
            if isinstance(label_decision, str) and label_decision in {"SHOW", "HOLD", "REVIEW"}:
                decision_labeled += 1
                decision_correct += int(pred.get("decision") == label_decision)
            expected = label.get("relevant")
            actual = pred.get("relevant")
            if "relevant" in pred and (
                not isinstance(actual, str) or actual not in {"YES", "NO", "UNKNOWN"}
            ):
                errors.append(f"{route}:{cid}: relevant must be YES, NO, or UNKNOWN")
            if "decision" in pred and (
                not isinstance(pred["decision"], str)
                or pred["decision"] not in {"SHOW", "HOLD", "REVIEW", "UNKNOWN"}
            ):
                errors.append(f"{route}:{cid}: invalid prediction decision")
            if isinstance(expected, str) and expected in {"YES", "NO"}:
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
            if isinstance(merge_truth, str) and merge_truth in {"YES", "NO"}:
                merge_labeled += 1
                merge = pred.get("merge_proposed") is True
                merge_proposed += int(merge)
                merge_unsafe += int(merge and merge_truth == "NO")
            promote_truth = label.get("safe_to_promote")
            if isinstance(promote_truth, str) and promote_truth in {"YES", "NO"}:
                promote_labeled += 1
                promote = pred.get("promotion_proposed") is True
                promote_proposed += int(promote)
                promote_unsafe += int(promote and promote_truth == "NO")
            for field, target in (
                ("latency_ms", latencies),
                ("provider_latency_ms", provider_latencies),
                ("end_to_end_latency_ms", e2e_latencies),
                ("source_freshness_hours", freshness_values),
                ("queue_delay_ms", queue_delays),
            ):
                value = pred.get(field)
                if value is not None:
                    if (
                        not isinstance(value, int | float)
                        or isinstance(value, bool)
                        or not math.isfinite(value)
                        or value < 0
                    ):
                        errors.append(
                            f"{route}:{cid}: {field} must be a finite non-negative number"
                        )
                    else:
                        target.append(float(value))
            for field in (
                "schema_valid",
                "question_resolved",
                "merge_proposed",
                "promotion_proposed",
            ):
                if field in pred and not isinstance(pred[field], bool):
                    errors.append(f"{route}:{cid}: {field} must be boolean")
            outcome = pred.get("queue_outcome")
            if outcome is not None:
                if not isinstance(outcome, str) or outcome not in {
                    "COMPLETED",
                    "FAILED",
                    "CANCELLED",
                    "UNRESOLVED",
                }:
                    errors.append(f"{route}:{cid}: invalid queue_outcome")
                else:
                    queue_outcomes[outcome] = queue_outcomes.get(outcome, 0) + 1
                    queue_outcome_rows += 1
            if "schema_valid" in pred:
                schema_reviewed += 1
                schema_valid += int(pred["schema_valid"] is True)
            cost = pred.get("cost", {})
            if not isinstance(cost, dict):
                errors.append(f"{route}:{cid}: cost must be an object")
                cost = {}
            if set(cost) - {"status", "amount", "uncertain_amount", "reference"}:
                errors.append(f"{route}:{cid}: cost contains unsupported fields")
            amount = cost.get("amount")
            uncertain_amount = cost.get("uncertain_amount")
            cost_status = cost.get("status")
            if cost_status is not None and (
                not isinstance(cost_status, str)
                or cost_status not in {"KNOWN", "UNKNOWN", "UNCERTAIN"}
            ):
                errors.append(f"{route}:{cid}: invalid cost status")
            for name, value in (("amount", amount), ("uncertain_amount", uncertain_amount)):
                if value is not None and (
                    not isinstance(value, int | float)
                    or isinstance(value, bool)
                    or not math.isfinite(value)
                    or value < 0
                ):
                    errors.append(f"{route}:{cid}: {name} must be finite and non-negative")
            if cost_status == "KNOWN" and uncertain_amount is not None:
                errors.append(f"{route}:{cid}: KNOWN cost cannot include uncertain_amount")
            if cost_status in {"UNKNOWN", "UNCERTAIN"} and amount is not None:
                errors.append(f"{route}:{cid}: unknown cost cannot include amount")
            if (
                cost_status == "KNOWN"
                and isinstance(amount, int | float)
                and not isinstance(amount, bool)
                and math.isfinite(amount)
                and amount >= 0
            ):
                known_cost += float(amount)
                known_cost_rows += 1
            else:
                cost_complete = False
                if cost_status == "KNOWN":
                    errors.append(
                        f"{route}:{cid}: KNOWN cost requires a finite non-negative amount"
                    )
                if uncertain_amount is not None:
                    if (
                        not isinstance(uncertain_amount, int | float)
                        or isinstance(uncertain_amount, bool)
                        or not math.isfinite(uncertain_amount)
                        or uncertain_amount < 0
                    ):
                        errors.append(
                            f"{route}:{cid}: uncertain_amount must be finite and non-negative"
                        )
                    else:
                        uncertain_cost += float(uncertain_amount)
                        uncertain_cost_rows += 1
            reserve = pred.get("reserved_cost")
            if (
                reserve is not None
                and isinstance(reserve, int | float)
                and not isinstance(reserve, bool)
                and math.isfinite(reserve)
                and reserve >= 0
            ):
                reserved_cost += float(reserve)
            else:
                reserved_complete = False
                if reserve is not None:
                    errors.append(f"{route}:{cid}: reserved_cost must be finite and non-negative")
            review = pred.get("fabricated_claim_review")
            if review is not None:
                if (
                    not isinstance(review, dict)
                    or not isinstance(review.get("reviewed"), bool)
                    or not isinstance(review.get("fabricated_count"), int)
                    or isinstance(review.get("fabricated_count"), bool)
                    or review["fabricated_count"] < 0
                ):
                    errors.append(
                        f"{route}:{cid}: fabricated_claim_review needs reviewed and "
                        "non-negative fabricated_count"
                    )
                elif review["reviewed"]:
                    fabricated_reviewed += 1
                    fabricated_count += review["fabricated_count"]
                    useful_reviewed += int(pred.get("useful_independently_reviewed") is True)
            if "useful_independently_reviewed" in pred and not isinstance(
                pred["useful_independently_reviewed"], bool
            ):
                errors.append(f"{route}:{cid}: useful_independently_reviewed must be boolean")
            question_expected = label.get("question_expected")
            unknown_question_expectation += int(question_expected is None)
            eligible += int(question_expected is True)
            resolved += int(question_expected is True and pred.get("question_resolved") is True)
        labeled_relevant = sum(
            isinstance(labels.get(cid, {}).get("relevant"), str)
            and labels.get(cid, {}).get("relevant") in {"YES", "NO"}
            for cid in case_ids
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
                "count": fabricated_count if fabricated_reviewed == len(by_id) else "UNKNOWN",
                "reviewed": fabricated_reviewed,
                "coverage": _ratio(fabricated_reviewed, len(by_id)),
            },
            "latency_ms": {
                "p50": _percentile(latencies, 0.50),
                "p95": _percentile(latencies, 0.95),
                "known": len(latencies),
            },
            "end_to_end_latency_ms": {
                "p50": _percentile(e2e_latencies, 0.50),
                "p95": _percentile(e2e_latencies, 0.95),
                "known": len(e2e_latencies),
            },
            "provider_latency_ms": {
                "p50": _percentile(provider_latencies, 0.50),
                "p95": _percentile(provider_latencies, 0.95),
                "known": len(provider_latencies),
            },
            "source_freshness_hours": {
                "p50": _percentile(freshness_values, 0.50),
                "p95": _percentile(freshness_values, 0.95),
                "known": len(freshness_values),
            },
            "model_schema_validity": {
                "valid": schema_valid if schema_reviewed == len(by_id) else "UNKNOWN",
                "reviewed": schema_reviewed,
                "coverage": _ratio(schema_reviewed, len(by_id)),
            },
            "queue": {
                "delay_ms_p50": _percentile(queue_delays, 0.50),
                "delay_ms_p95": _percentile(queue_delays, 0.95),
                "delay_known": len(queue_delays),
                "outcomes": queue_outcomes if queue_outcome_rows == len(by_id) else "UNKNOWN",
                "outcome_coverage": _ratio(queue_outcome_rows, len(by_id)),
            },
            "cost": {
                "known": known_cost if cost_complete else "UNKNOWN",
                "known_subtotal": known_cost if known_cost_rows else "UNKNOWN",
                "uncertain": uncertain_cost if uncertain_cost_rows else "UNKNOWN",
                "reserved": reserved_cost if reserved_complete else "UNKNOWN",
            },
            "resolved_question_yield": {
                "value": (
                    _ratio(resolved, eligible) if unknown_question_expectation == 0 else "UNKNOWN"
                ),
                "resolved": resolved,
                "eligible": eligible,
                "unknown_expectation": unknown_question_expectation,
            },
            "cost_per_useful_independently_reviewed_result": (
                known_cost / useful_reviewed if cost_complete and useful_reviewed else "UNKNOWN"
            ),
            "metric_provenance": route_doc.get("metric_provenance", "UNKNOWN"),
            "prd_review_gate": {
                "minimum_reviewed": 30,
                "minimum_correct": 24,
                "reviewed": decision_labeled,
                "correct": decision_correct if decision_labeled else "UNKNOWN",
                "status": (
                    "PASS"
                    if not missing and decision_labeled >= 30 and decision_correct >= 24
                    else "FAIL"
                    if not missing and decision_labeled >= 30
                    else "UNKNOWN"
                ),
            },
        }
    return {
        "status": "INVALID" if errors else "PROPOSED",
        "sample_sha256": manifest.get("sample_sha256"),
        "versions": versions,
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
