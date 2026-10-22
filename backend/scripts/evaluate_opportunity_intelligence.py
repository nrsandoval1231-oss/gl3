#!/usr/bin/env python3
"""Read-only retained-corpus acceptance; never schedules research or calls providers.

Manifest: {"reviewer": "name", "cases": [{"need_id": "uuid", "categories": [...],
"expected_fields": {"customer": "source-verified expected value", "required_mw": null}}]}.
Expected values must be independently checked against retained evidence, not copied
from the projection. No manifest means availability check only, never acceptance.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter
from uuid import UUID

from sqlalchemy import func, select, text

from gridlens.api.app import (
    _bounded_opportunity_payload,
    _preflight_opportunity_details,
    opportunity_projection,
)
from gridlens.intelligence.opportunity_intelligence import attach_cards
from gridlens.persistence.database import SessionLocal
from gridlens.persistence.models import Evidence, PowerNeed, Project

CATEGORIES = {
    "data_center",
    "oil_gas",
    "utility_constraint",
    "construction_commissioning",
    "false_positive",
    "incomplete_contacts",
    "conflicting_dates",
    "shared_company",
    "unestablished_temporary_need",
    "bridge_power",
}


def evaluate(manifest: dict) -> dict:
    cases = manifest.get("cases", [])
    if len(cases) > 20:
        raise ValueError("At most 20 explicitly reviewed opportunities per evaluation")
    ids = {UUID(case["need_id"]) for case in cases}
    if len(ids) != len(cases):
        raise ValueError("Manifest needs must be distinct")
    report = {
        "status": "BLOCKED",
        "provider_calls": 0,
        "inference_cost_usd": "0",
        "live_provider_acceptance": "NOT_EXECUTED",
        "production_latency": "NOT_MEASURED",
    }
    with SessionLocal() as session:
        session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        session.execute(text("SET TRANSACTION READ ONLY"))
        session.execute(text("SET LOCAL statement_timeout = '15000ms'"))
        report["corpus_counts"] = {
            name: session.scalar(select(func.count()).select_from(model))
            for name, model in (
                ("projects", Project),
                ("power_needs", PowerNeed),
                ("evidence", Evidence),
            )
        }
        if not ids:
            report["blockers"] = ["No independently reviewed retained-corpus manifest supplied."]
            return report
        start = perf_counter()
        summaries = opportunity_projection(session, selected_need_ids=ids, summary_only=True)
        _preflight_opportunity_details(session, summaries)
        chains = {}
        items = opportunity_projection(
            session,
            selected_need_ids=ids,
            buying_chain_results=chains,
            include_operator_fact_refs=True,
        )
        attach_cards(session, items, chains)
        _bounded_opportunity_payload(items)
        report["batch_read_ms"] = round((perf_counter() - start) * 1000, 2)
        cards = {str(item["id"]): item["intelligence_card"] for item in items}
        results = []
        correct = tested = unsupported = populated = 0
        for case in cases:
            card = cards.get(str(UUID(case["need_id"])))
            if card is None:
                results.append({"need_id": case["need_id"], "error": "No current canonical card"})
                continue
            fields = {field["key"]: field for field in card["fields"]}
            checks = {}
            for key, expected in case.get("expected_fields", {}).items():
                tested += 1
                observed = fields.get(key, {}).get("value")
                passed = key in fields and observed == expected
                correct += int(passed)
                populated += int(observed is not None)
                unsupported += int(expected is None and observed is not None)
                checks[key] = {"expected": expected, "observed": observed, "pass": passed}
            results.append(
                {
                    "need_id": case["need_id"],
                    "qualification": card["qualification"],
                    "completeness": card["completeness"],
                    "field_checks": checks,
                    "fingerprint": card["input_fingerprint"],
                }
            )
        covered = {category for case in cases for category in case.get("categories", [])}
        blockers = []
        if len(ids) < 10:
            blockers.append("At least ten retained opportunities required.")
        if CATEGORIES - covered:
            blockers.append(
                "Missing representative categories: " + ", ".join(sorted(CATEGORIES - covered))
            )
        if not manifest.get("reviewer") or any(not case.get("expected_fields") for case in cases):
            blockers.append(
                "Independent reviewer and expected field labels required for every case."
            )
        if len(cards) != len(ids):
            blockers.append("Some selected records lack a current canonical card.")
        if tested != correct:
            blockers.append("Field expectations failed; inspect and repair before release.")
        report.update(
            status="BLOCKED" if blockers else "OFFLINE_CHECKS_PASSED",
            blockers=blockers,
            cases=results,
            field_accuracy=correct / tested if tested else None,
            reviewed_fields=tested,
            unsupported_claim_rate=unsupported / populated if populated else None,
            metric_scope="Only independently labeled fields; not a full factual audit.",
        )
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text()) if args.manifest else {}
    report = evaluate(manifest)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(report["status"])
    return 0 if report["status"] == "OFFLINE_CHECKS_PASSED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
