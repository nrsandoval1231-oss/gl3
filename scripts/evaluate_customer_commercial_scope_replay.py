"""Replay the 20-source corpus through source-text-aware scope guards.

Reference project labels are used only as declared oracle evaluation context.
Runtime identity accuracy is not measured. Project aliases come only from the
retained source adapter's fresh native reparse and are never read from gold.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FIXTURE = ROOT / "eval" / "customer-commercial-v1"
EXPECTED_GOLD_SHA256 = (
    "dd061c52a85b0ba05b59aab4229f5dd886bced31145fe6ab315c5ad1cda0b922"
)
if str(BACKEND / "src") not in sys.path:
    sys.path.insert(0, str(BACKEND / "src"))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evaluate(
    fixture: Path = FIXTURE,
    *,
    as_of: date = date(2026, 11, 13),
    frozen: bool = False,
) -> dict[str, Any]:
    from evaluate_customer_commercial import (
        BASIS,
        capacity_matches,
        score_claims,
        timeline_matches,
    )

    from gridlens.domain.customer_intelligence import extract_customer_facts
    from gridlens.ingestion.adapters.retained_company_projects import (
        interpret_retained_company_project,
        retained_records,
    )
    from gridlens.intelligence.customer_intelligence import scope_customer_facts

    source_implementation = {
        "native_alias_adapter": ROOT
        / "backend/src/gridlens/ingestion/adapters/retained_company_projects.py",
        "evaluation_scorer": ROOT / "scripts/evaluate_customer_commercial.py",
        "runner": Path(__file__).resolve(),
        "extractor": ROOT / "backend/src/gridlens/domain/customer_intelligence.py",
        "scoper": ROOT / "backend/src/gridlens/intelligence/customer_intelligence.py",
        "subject_binding": ROOT / "backend/src/gridlens/domain/customer_subjects.py",
        "research_evidence_caller": ROOT
        / "backend/src/gridlens/intelligence/research_evidence.py",
    }
    initial_implementation_hashes = {
        label: _hash(path) for label, path in source_implementation.items()
    }

    reference_path = fixture / "reference-customers.json"
    if _hash(reference_path) != EXPECTED_GOLD_SHA256:
        raise ValueError("Reference bytes differ from immutable r2 hash")
    reference = json.loads(reference_path.read_text())
    manifest = json.loads((fixture / "source-hashes.json").read_text())
    immutable_sources = {item["file"]: item["sha256"] for item in manifest}
    for relative, expected in immutable_sources.items():
        if _hash(fixture / relative) != expected:
            raise ValueError(f"Retained source changed: {relative}")

    initial_input_hashes = {
        path: _hash(path)
        for path in [
            reference_path,
            fixture / "source-hashes.json",
            *[fixture / relative for relative in immutable_sources],
        ]
    }

    native_records, _held = retained_records(fixture)
    native_aliases: dict[str, list[str]] = {}
    for record in native_records:
        if interpret_retained_company_project(record) is None:
            raise ValueError("Native retained alias record failed fresh source reparse")
        context = record["retained_company_project"]
        native_aliases[record["html_url"]] = list(context.get("project_aliases", []))

    rows = []
    bundle_sources: set[str] = set()
    for oracle in reference["records"]:
        project_id = "oracle-context:" + oracle["id"]
        raw_capacity: list[dict] = []
        scoped_capacity: list[dict] = []
        raw_timeline: list[dict] = []
        scoped_timeline: list[dict] = []
        inputs = []
        for source_id, publication_date in oracle["sources"]:
            bundle_sources.add(source_id)
            source_path = fixture / "sources" / f"{source_id}.json"
            source = json.loads(source_path.read_text())
            text = "\n\n".join(source["excerpts"])
            digest = hashlib.sha256(text.encode()).hexdigest()
            source_ref = {
                "url": source["url"],
                "evidence_id": "offline-source:" + source_id,
                "content_hash": digest,
                "published_at": publication_date,
                "observed_at": source["observation_date"],
                "authority": "primary",
                "verification_status": "reported",
            }
            raw = extract_customer_facts(text, project_id=project_id, source=source_ref)
            scoped = scope_customer_facts(
                raw,
                oracle["project"],
                oracle.get("location", ""),
                source_text=text,
                project_aliases=native_aliases.get(source["url"], []),
            )
            raw_capacity.extend(raw.get("capacity_claims", []))
            scoped_capacity.extend(scoped.get("capacity_claims", []))
            raw_timeline.extend(raw.get("timeline_claims", []))
            scoped_timeline.extend(scoped.get("timeline_claims", []))
            inputs.append(
                {
                    "source_file": str(source_path.relative_to(fixture)),
                    "source_text_sha256": digest,
                    "native_aliases": native_aliases.get(source["url"], []),
                }
            )

        reference_capacity = [
            claim for claim in oracle["capacity"] if claim.get("type") in BASIS
        ]
        capacity_score = score_claims(
            reference_capacity,
            scoped_capacity,
            lambda gold, predicted, pid=project_id: capacity_matches(
                gold, predicted, pid
            ),
        )
        timeline_score = score_claims(
            oracle["timeline"],
            scoped_timeline,
            lambda gold, predicted, pid=project_id: timeline_matches(
                gold, predicted, pid
            ),
        )
        rows.append(
            {
                "oracle_record": oracle["id"],
                "source_count": len(inputs),
                "raw_capacity_candidates": len(raw_capacity),
                "scoped_capacity_claims": len(scoped_capacity),
                "raw_timeline_candidates": len(raw_timeline),
                "scoped_timeline_claims": len(scoped_timeline),
                "capacity_score": capacity_score,
                "timeline_score": timeline_score,
                "inputs": inputs,
            }
        )

    implementation_hashes = {
        label: _hash(path) for label, path in source_implementation.items()
    }
    if implementation_hashes != initial_implementation_hashes:
        raise ValueError("Measured implementation changed during replay")
    for path, expected in initial_input_hashes.items():
        if _hash(path) != expected:
            raise ValueError(f"Evaluation input changed during replay: {path.name}")
    return {
        "evaluation_version": "customer-commercial-source-text-scope-replay-v1",
        "receipt_status": "final frozen replay" if frozen else "intermediate replay",
        "captured_at": datetime.now(UTC).isoformat(),
        "as_of": as_of.isoformat(),
        "reference_sha256": _hash(reference_path),
        "source_manifest_sha256": _hash(fixture / "source-hashes.json"),
        "runner_sha256": _hash(Path(__file__).resolve()),
        "retained_source_artifacts": len(manifest),
        "reference_source_bundle_occurrences": sum(
            len(item["sources"]) for item in reference["records"]
        ),
        "distinct_reference_source_captures": len(bundle_sources),
        "unassigned_retained_artifact_count": len(manifest) - len(bundle_sources),
        "implementation_hashes": implementation_hashes,
        "expected_claim_values_used_as_extractor_input": False,
        "reference_identity_metadata_used_as_scope_input": True,
        "reference_publication_metadata_used_as_source_context": True,
        "gold_used_for_oracle_scoring": True,
        "evaluation_context": (
            "Reference project identity/location selects source bundles and supplies "
            "oracle scope labels only. No reference company/project labels create aliases, "
            "runtime identities, or account memberships."
        ),
        "native_alias_policy": (
            "Only aliases emitted and freshly reparsed by retained_records; no gold labels."
        ),
        "runtime_identity_accuracy": "not_measured",
        "records": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--frozen",
        action="store_true",
        help="Mark receipt final after independent source/scoper freeze review.",
    )
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError(f"Refusing to overwrite evaluation receipt: {args.output}")
    result = evaluate(frozen=args.frozen)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        output.write(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
