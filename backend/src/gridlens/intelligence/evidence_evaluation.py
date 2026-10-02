"""Compare retained EvidenceJudge results with explicit non-UNKNOWN fixture labels."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any


def completed_or_pending_case_ids(result_doc: dict[str, Any]) -> set[str]:
    """Treat persisted PENDING attempts as consumed: interruption is never blind-retried."""
    return {
        str(row["case_id"])
        for row in result_doc.get("results", [])
        if row.get("case_id") is not None
    }


def persist_benchmark_results(result_doc: dict[str, Any], path: Path) -> None:
    """Atomically retain attempt intent before provider I/O and every terminal outcome."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(result_doc, stream, indent=2, default=str)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def score_fixture_results(cases: list[dict], rows: Iterable[Any]) -> dict[str, Any]:
    row_list = list(rows)
    by_evidence: dict[str, dict] = {}
    by_case: dict[str, dict] = {}
    for row in sorted(
        row_list, key=lambda item: str(getattr(item, "started_at", "")), reverse=True
    ):
        result = getattr(row, "result", None)
        if result is not None:
            case_id = getattr(row, "case_id", None)
            evidence_id = getattr(row, "evidence_id", None)
            if case_id is not None and str(case_id) not in by_case:
                by_case[str(case_id)] = result
            if evidence_id is not None and str(evidence_id) not in by_evidence:
                by_evidence[str(evidence_id)] = result
    fields = [
        "same_project",
        "material_change",
        "power_relevance",
        "temporary_power_hint",
        "needs_deep_enrichment",
    ]
    agreement_counts: dict[str, dict[str, int]] = {
        field: {"matched": 0, "denominator": 0} for field in fields
    }
    true_positive: int = 0
    false_positive: int = 0
    false_negative: int = 0
    unknown_predictions: int = 0
    relevance_labeled: int = 0
    relevance_covered: int = 0
    enrichment_recommended: int = 0
    enrichment_useful: int = 0
    research_recommendation_yes: int = 0
    research_recommendation_known: int = 0
    latency = [
        row.latency_ms for row in row_list if row.status == "valid" and row.latency_ms is not None
    ]
    valid = [row for row in row_list if row.status == "valid" and row.result is not None]
    input_known = [row.input_tokens for row in valid if row.input_tokens is not None]
    output_known = [row.output_tokens for row in valid if row.output_tokens is not None]
    for case in cases:
        case_id = case.get("case_id")
        evidence_id = case.get("evidence_id")
        result = by_case.get(str(case_id)) if case_id is not None else None
        if result is None:
            result = by_evidence.get(str(evidence_id)) if evidence_id is not None else None
        if not result:
            continue
        labels = case.get("labels", {})
        expected: str | None = labels.get("relevant")
        predicted: str | None = result.get("relevant")
        if expected in {"YES", "NO"}:
            relevance_labeled += 1
            if predicted == "UNKNOWN":
                unknown_predictions += 1
                if expected == "YES":
                    false_negative += 1
            else:
                relevance_covered += 1
                if expected == predicted == "YES":
                    true_positive += 1
                elif expected == "NO" and predicted == "YES":
                    false_positive += 1
                elif expected == "YES" and predicted == "NO":
                    false_negative += 1
        for field in fields:
            label = labels.get(field)
            prediction = result.get(field)
            if label is not None and label != "UNKNOWN":
                agreement_counts[field]["denominator"] += 1
                agreement_counts[field]["matched"] += int(prediction == label)
        if labels.get("needs_deep_enrichment") in {"YES", "NO"}:
            enrichment_recommended += int(result.get("needs_deep_enrichment") == "YES")
            enrichment_useful += int(
                result.get("needs_deep_enrichment") == labels["needs_deep_enrichment"] == "YES"
            )
        recommendation = result.get("advisory", {}).get("research_recommended")
        if isinstance(recommendation, bool):
            research_recommendation_known += 1
            research_recommendation_yes += int(recommendation)
    agreement = {
        field: {
            **counts,
            "value": counts["matched"] / counts["denominator"]
            if counts["denominator"]
            else "UNKNOWN",
        }
        for field, counts in agreement_counts.items()
    }
    latency.sort()

    def percentile(fraction: float):
        return (
            latency[min(len(latency) - 1, max(0, int((len(latency) - 1) * fraction)))]
            if latency
            else "UNKNOWN"
        )

    matched_cases = {
        str(row.case_id)
        for row in row_list
        if getattr(row, "case_id", None) and row.result is not None
    }
    matched_cases.update(
        str(case.get("case_id")) for case in cases if case.get("evidence_id") in by_evidence
    )
    return {
        "cases_with_provider_result": len(matched_cases),
        "cases_without_provider_result": len(cases) - len(matched_cases),
        "relevance": {
            "precision": {
                "value": true_positive / (true_positive + false_positive)
                if true_positive + false_positive
                else "UNKNOWN",
                "denominator": true_positive + false_positive,
            },
            "recall": {
                "value": true_positive / (true_positive + false_negative)
                if true_positive + false_negative
                else "UNKNOWN",
                "denominator": true_positive + false_negative,
            },
            "true_positive": true_positive,
            "false_positive": false_positive,
            "false_negative": false_negative,
            "unknown_predictions": unknown_predictions,
            "labeled_denominator": relevance_labeled,
            "coverage": relevance_covered / relevance_labeled if relevance_labeled else "UNKNOWN",
        },
        "agreement": agreement,
        "deep_enrichment_yield": {
            "value": enrichment_useful / enrichment_recommended
            if enrichment_recommended
            else "UNKNOWN",
            "useful_yes": enrichment_useful,
            "recommended_yes": enrichment_recommended,
            "labeled_cases": sum(
                case.get("labels", {}).get("needs_deep_enrichment") in {"YES", "NO"}
                for case in cases
            ),
        },
        "research_recommendation": {
            "recommended_yes": research_recommendation_yes,
            "recommended_no": research_recommendation_known - research_recommendation_yes,
            "evaluated_cases": research_recommendation_known,
        },
        "invalid_count": sum(row.status == "invalid" for row in row_list),
        "timeout_count": sum(row.status == "timeout" for row in row_list),
        "latency_p50_ms": percentile(0.50),
        "latency_p95_ms": percentile(0.95),
        "usage": {
            "input_tokens": (
                sum(input_known) if valid and len(input_known) == len(valid) else "UNKNOWN"
            ),
            "input_tokens_known_subtotal": sum(input_known) if input_known else "UNKNOWN",
            "input_tokens_unknown_cases": len(valid) - len(input_known),
            "output_tokens": (
                sum(output_known) if valid and len(output_known) == len(valid) else "UNKNOWN"
            ),
            "output_tokens_known_subtotal": sum(output_known) if output_known else "UNKNOWN",
            "output_tokens_unknown_cases": len(valid) - len(output_known),
            "cost": "UNKNOWN",
        },
    }
