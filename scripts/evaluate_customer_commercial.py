"""Offline real-source commercial extraction evaluation; never writes operational data.

Reference organization/project assignments are supplied, not resolved by this runner.
Only retained source excerpt text and source metadata enter the production extractor.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import re
import subprocess
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from gridlens.domain.commissioning import estimate_commissioning
from gridlens.domain.customer_intelligence import (
    FACTS_VERSION,
    extract_customer_facts,
    resolve_customer_intelligence,
)
from gridlens.intelligence.customer_intelligence import scope_customer_facts

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = ROOT / "eval" / "customer-commercial-v1"
BASIS = {
    "campus_development_capacity": "campus_development",
    "it_load": "it_load",
    "utility_service_capacity": "utility_service",
    "generation_capacity": "generation",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_manifest() -> dict[str, str]:
    from gridlens.domain.project_research import _subject_predicate

    return {
        str(path.relative_to(ROOT)): sha256(path)
        for path in {
            Path(inspect.getfile(function))
            for function in (
                extract_customer_facts,
                scope_customer_facts,
                estimate_commissioning,
                _subject_predicate,
            )
        }
    }


def verify_sources(fixture: Path) -> None:
    for entry in json.loads((fixture / "source-hashes.json").read_text()):
        source = fixture / entry["file"]
        if sha256(source) != entry["sha256"]:
            raise ValueError(f"Retained source artifact changed: {entry['file']}")


def _amount(value: Any) -> Decimal | None:
    try:
        amount = Decimal(str(value))
        return amount if amount.is_finite() else None
    except InvalidOperation:
        return None


def _scope(value: str, project_id: str) -> str:
    prefix = project_id + ":"
    value = value.removeprefix(prefix)
    # Roman and decimal phase labels name the same source phase, not a new scope.
    for roman, number in (("iii", "3"), ("ii", "2"), ("i", "1")):
        if value == f"phase:{roman}":
            return f"phase:{number}"
    return value


def reference_qualifier(claim: dict) -> str:
    """Retain numeric bounds and material conditional/rating semantics."""
    value = claim.get("qualifier", "exact")
    special = {
        "substation_rating": "substation_rating",
        "contracted_power_agreement": "contracted_power_agreement",
        "option_not_committed": "option_not_committed",
        "leased": "leased",
        "1plus_under_load_study": "studied_power_potential",
        "up_to_potential": "up_to_potential",
        "acquired_properties_capable_of_delivering_not_verified_existing_output": "capable_not_delivered",
    }
    if value in special:
        return special[value]
    if value.startswith("up_to"):
        return "up_to"
    if value.startswith(("more_than", "over_")):
        return "more_than"
    if value.startswith("approximately"):
        return "approximate"
    return "exact"


def capacity_matches(gold: dict, predicted: dict, project_id: str) -> bool:
    """Strict value/basis/scope/qualifier match; do not flatten service conditions."""
    basis = BASIS.get(gold.get("type"))
    return bool(
        basis
        and _amount(gold.get("value_mw")) == _amount(predicted.get("value_mw"))
        and basis == predicted.get("basis")
        and reference_qualifier(gold) == predicted.get("qualifier", "exact")
        and gold.get("evaluation_scope")
        == _scope(predicted.get("scope_id", ""), project_id)
    )


def normalized_date(label: str, precision: str) -> str:
    clean = label.strip().lower()
    if precision == "quarter":
        match = re.fullmatch(r"(?:(\d{4})-q([1-4])|q([1-4])\s+(\d{4}))", clean)
        if match:
            return f"{match[1] or match[4]}-q{match[2] or match[3]}"
        named = re.fullmatch(
            r"(first|second|third|fourth) quarter of (?:calendar )?(\d{4})", clean
        )
        if named:
            ordinal = {"first": 1, "second": 2, "third": 3, "fourth": 4}
            return f"{named[2]}-q{ordinal[named[1]]}"
    if precision == "half_year":
        named = re.fullmatch(r"(first|second) half of (\d{4})", clean)
        if named:
            return f"{named[2]}-h{1 if named[1] == 'first' else 2}"
    if precision == "month":
        for form in ("%B %Y", "%b %Y"):
            try:
                return datetime.strptime(clean, form).strftime("%Y-%m")
            except ValueError:
                pass
    if precision == "day":
        for form in ("%B %d, %Y", "%B %d %Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(clean, form).date().isoformat()
            except ValueError:
                pass
    # Do not normalize an approximate phrase to an exact date or interval.
    return re.sub(r"\s+", " ", clean)


def timeline_qualifier(value: str | None) -> str:
    """Compare interval semantics across reference and production enum spellings."""
    if value in {None, "exact", "within"}:
        return "within"
    if value in {"at_or_before", "deadline"}:
        return "deadline"
    return value


def timeline_matches(gold: dict, predicted: dict, project_id: str) -> bool:
    precision = gold.get("precision")
    return bool(
        gold.get("kind") == predicted.get("event_type")
        and precision == predicted.get("precision")
        and timeline_qualifier(gold.get("qualifier"))
        == timeline_qualifier(predicted.get("qualifier"))
        and normalized_date(gold.get("value", ""), precision)
        == normalized_date(predicted.get("label", ""), precision)
        and gold.get("evaluation_scope")
        == _scope(predicted.get("scope_id", ""), project_id)
    )


def score_claims(gold: list[dict], predicted: list[dict], matches: Any) -> dict:
    """Maximum one-to-one matching: repeated predictions never earn extra recall."""
    assignments: dict[int, int] = {}

    def augment(gold_index: int, visited: set[int]) -> bool:
        for predicted_index, claim in enumerate(predicted):
            if predicted_index in visited or not matches(gold[gold_index], claim):
                continue
            visited.add(predicted_index)
            if predicted_index not in assignments or augment(
                assignments[predicted_index], visited
            ):
                assignments[predicted_index] = gold_index
                return True
        return False

    for index in range(len(gold)):
        augment(index, set())
    true_positive = len(assignments)
    matched_gold = set(assignments.values())
    return {
        "true_positive": true_positive,
        "false_positive": len(predicted) - true_positive,
        "false_negative": len(gold) - true_positive,
        "reference_claims": len(gold),
        "predicted_claims": len(predicted),
        "precision": true_positive / len(predicted) if predicted else None,
        "recall": true_positive / len(gold) if gold else None,
        "unmatched_reference_indices": [
            i for i in range(len(gold)) if i not in matched_gold
        ],
        "unmatched_prediction_indices": [
            i for i in range(len(predicted)) if i not in assignments
        ],
    }


def predict_record(record: dict, fixture: Path, *, as_of: date) -> dict:
    """Source-only predictions under supplied fixture grouping, not canonical identity."""
    project_id = "fixture-project:" + record["id"]
    facts = []
    raw_facts = []
    seen_sources: set[tuple[str, str]] = set()
    source_reads = []
    for source_id, publication_date in record["sources"]:
        path = fixture / "sources" / f"{source_id}.json"
        source = json.loads(path.read_text())
        text = "\n\n".join(source["excerpts"])
        digest = hashlib.sha256(text.encode()).hexdigest()
        # Supplemental captures can repeat excerpts. Dedup only exact source text;
        # do not choose facts or scopes using expected labels.
        key = source["url"], digest
        if key in seen_sources:
            continue
        seen_sources.add(key)
        source_ref = {
            "url": source["url"],
            "evidence_id": "fixture-source:" + source_id,
            "content_hash": digest,
            # Independently labeled document metadata is permitted context;
            # capacity/timeline/contact target values never enter extraction.
            "published_at": publication_date,
            "observed_at": source["observation_date"],
            "authority": "primary",
            "verification_status": "reported",
        }
        raw = extract_customer_facts(text, project_id=project_id, source=source_ref)
        raw_facts.append(raw)
        facts.append(
            scope_customer_facts(raw, record["project"], record.get("location", ""))
        )
        source_reads.append(
            {"artifact": str(path.relative_to(fixture)), "text_sha256": digest}
        )

    def unique_claims(packages: list[dict], field: str) -> list[dict]:
        # One semantic assertion from one source counts once despite repeated
        # wording. Keep all supporting quotes; never merge different scopes,
        # qualifiers, amounts, event kinds, precision or source URLs.
        unique = {}
        for package in packages:
            for claim in package[field]:
                signature = json.dumps(
                    [
                        claim.get("basis"),
                        claim.get("scope_id"),
                        claim.get("value_mw"),
                        claim.get("event_type"),
                        claim.get("label"),
                        claim.get("precision"),
                        claim.get("qualifier"),
                        claim.get("status"),
                        claim.get("source", {}).get("url"),
                    ],
                    sort_keys=True,
                )
                if signature not in unique:
                    unique[signature] = {
                        **claim,
                        "supporting_quotes": [claim.get("quote")],
                    }
                elif claim.get("quote") not in unique[signature]["supporting_quotes"]:
                    unique[signature]["supporting_quotes"].append(claim.get("quote"))
        return list(unique.values())

    claims = {
        field: unique_claims(facts, field)
        for field in ("capacity_claims", "timeline_claims")
    }
    raw_claims = {
        "raw_" + field: unique_claims(raw_facts, field)
        for field in ("capacity_claims", "timeline_claims")
    }
    summary = resolve_customer_intelligence(
        [{"project_id": project_id, "facts": facts}], as_of=as_of
    )
    return {
        "project_id": project_id,
        **claims,
        **raw_claims,
        "summary": summary,
        "source_reads": source_reads,
        "supplied_project_context": {
            "name": record["project"],
            "location": record.get("location", ""),
        },
    }


def provenance_complete(claim: dict) -> bool:
    source = claim.get("source", {})
    return bool(
        source.get("url")
        and source.get("evidence_id")
        and source.get("content_hash")
        and source.get("observed_at")
        and "published_at" in source  # Unknown publication is valid, not invented.
        and source.get("authority")
        and claim.get("extraction_method")
        and claim.get("project_id")
        and claim.get("status")
        and claim.get("quote")
    )


def _aggregate(rows: list[dict]) -> dict:
    values = {
        key: sum(row[key] for row in rows)
        for key in (
            "true_positive",
            "false_positive",
            "false_negative",
            "reference_claims",
            "predicted_claims",
        )
    }
    values["precision"] = (
        values["true_positive"] / values["predicted_claims"]
        if values["predicted_claims"]
        else None
    )
    values["recall"] = (
        values["true_positive"] / values["reference_claims"]
        if values["reference_claims"]
        else None
    )
    return values


def evaluate(
    fixture: Path = DEFAULT_FIXTURE, *, as_of: date = date(2026, 11, 12)
) -> dict:
    before = source_manifest()
    verify_sources(fixture)
    reference_path = fixture / "reference-customers.json"
    reference = json.loads(reference_path.read_text())
    records = []
    for record in reference["records"]:
        prediction = predict_record(record, fixture, as_of=as_of)
        project_id = prediction["project_id"]
        capacity = [c for c in record["capacity"] if c.get("type") in BASIS]
        cap_score = score_claims(
            capacity,
            prediction["capacity_claims"],
            lambda gold, predicted: capacity_matches(gold, predicted, project_id),
        )
        time_score = score_claims(
            record["timeline"],
            prediction["timeline_claims"],
            lambda gold, predicted: timeline_matches(gold, predicted, project_id),
        )
        raw_cap_score = score_claims(
            capacity,
            prediction["raw_capacity_claims"],
            lambda gold, predicted: capacity_matches(gold, predicted, project_id),
        )
        raw_time_score = score_claims(
            record["timeline"],
            prediction["raw_timeline_claims"],
            lambda gold, predicted: timeline_matches(gold, predicted, project_id),
        )
        claims = prediction["capacity_claims"] + prediction["timeline_claims"]
        records.append(
            {
                "reference_record_key": record["id"],
                "company_label": record["company"],
                "grouping": "supplied_reference_assignment_not_runtime_identity",
                "capacity": cap_score,
                "timeline": time_score,
                "candidate_capacity": raw_cap_score,
                "candidate_timeline": raw_time_score,
                "candidate_precision": raw_cap_score["precision"],
                "scoped_precision": cap_score["precision"],
                "reference_missingness": record["missingness"],
                "provenance": {
                    "claims": len(claims),
                    "complete": sum(provenance_complete(claim) for claim in claims),
                },
                "commissioning": {
                    "expected": record["commissioning_expected"]["status"],
                    "actual": prediction["summary"]["commissioning"]["status"],
                    "correct_abstention": prediction["summary"]["commissioning"][
                        "status"
                    ]
                    == "insufficient_data",
                },
                "predictions": prediction,
            }
        )
    all_claims = sum(r["provenance"]["claims"] for r in records)
    complete = sum(r["provenance"]["complete"] for r in records)
    not_evaluated = {
        "status": "not_evaluated",
        "reason": "No runtime identity/project matcher or account grouping invoked; fixture assignment supplied.",
        "value": None,
    }
    if source_manifest() != before:
        raise RuntimeError(
            "Measured production source changed during evaluation; rerun on frozen source."
        )
    return {
        "evaluation_version": "customer-commercial-evaluation-v1.1",
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "source_manifest": before,
        "evaluation_source_authority": "primary",
        "runtime_authority_mismatch": "This source-text evaluation labels official company source URLs primary. Runtime currently maps .gov to regulatory and other hosts to unknown; this result does not verify live evidence-quality/confidence behavior.",
        "as_of": as_of.isoformat(),
        "reference_review_status": reference["labeling_status"],
        "reference_sha256": sha256(reference_path),
        "runner_sha256": sha256(Path(__file__)),
        "extractor_version": FACTS_VERSION,
        "extractor_source_sha256": sha256(
            Path(inspect.getfile(extract_customer_facts))
        ),
        "scope_guard_source_sha256": sha256(
            Path(inspect.getfile(scope_customer_facts))
        ),
        "organization_count": len(records),
        "metrics": {
            "raw_candidate_capacity_strict_value_basis_scope": _aggregate(
                [r["candidate_capacity"] for r in records]
            ),
            "raw_candidate_timeline_strict_kind_value_precision_scope": _aggregate(
                [r["candidate_timeline"] for r in records]
            ),
            "capacity_extraction_strict_value_basis_scope": _aggregate(
                [r["capacity"] for r in records]
            ),
            "timeline_extraction_strict_kind_value_precision_scope": _aggregate(
                [r["timeline"] for r in records]
            ),
            "provenance_completeness": {
                "complete": complete,
                "claims": all_claims,
                "coverage": complete / all_claims if all_claims else None,
            },
            "capacity_match_fields": [
                "value_mw",
                "basis",
                "scope",
                "numeric_bounds_and_material_qualifier",
            ],
            "commissioning_abstention": {
                "correct": sum(
                    r["commissioning"]["correct_abstention"] for r in records
                ),
                "eligible": len(records),
                "positive_scenarios_evaluated": 0,
            },
            "canonical_identity_accuracy": not_evaluated,
            "project_association_accuracy": not_evaluated,
            "duplicate_customer_rate": not_evaluated,
            "capacity_double_counting": {
                "status": "not_evaluated",
                "reason": "Requires independently reviewed expected typed rollup totals and included/disjoint scope coverage; claim recall alone is insufficient.",
            },
            "contacts": {
                "status": "not_evaluated",
                "reason": "Contact acquisition/verification pipeline not invoked.",
                "reference_historically_named_functional_leaders": sum(
                    bool(r["contacts"]) for r in reference["records"]
                ),
                "reference_current_verified_methods": 0,
            },
            "commercial_prioritization_quality": {
                "status": "not_evaluated",
                "reason": "No independent labeled ranking or salesperson review.",
            },
            "customer_card_usefulness": {
                "status": "not_evaluated",
                "reason": "Manual rubric has not been administered to independent sales reviewers.",
            },
        },
        "source_missingness": {
            category: sum(
                r["reference_missingness"]["capacity"] == category for r in records
            )
            for category in (
                "source_missing",
                "retrieval_partial",
                "covered_with_scope_and_qualifier",
            )
        },
        "limitations": [
            "Purposive stress cohort; results are not population-wide production accuracy.",
            "Input is retained selected source excerpts, not the complete discovery/ingestion pipeline.",
            "Predictions use source text plus independently supplied project name/location and source metadata; no target capacity/date/contact labels enter extraction. Supplied identity context is not canonical-company accuracy.",
            "Strict unmatched supported reference claims are parser missingness, not source missingness.",
            "Empty predictions produce undefined precision (null), never a perfect precision score.",
            "No current contact verification, positive commissioning scenario, or sales-user acceptance is established.",
            "Evaluation official-company sources use primary authority; runtime non-.gov authority is currently unknown. Do not infer production confidence or ranking parity.",
        ],
        "records": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--as-of", type=date.fromisoformat, default=date(2026, 11, 12))
    args = parser.parse_args()
    if (
        args.output.resolve()
        in {
            args.fixture.resolve() / "reference-customers.json",
            args.fixture.resolve() / "source-hashes.json",
        }
        or (args.fixture.resolve() / "sources") in args.output.resolve().parents
    ):
        parser.error("Output cannot overwrite immutable reference/source artifacts.")
    result = evaluate(args.fixture, as_of=args.as_of)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "organization_count": result["organization_count"],
                "metrics": result["metrics"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
