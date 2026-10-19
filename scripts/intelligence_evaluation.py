"""Create and inspect frozen offline evaluation artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from gridlens.intelligence.integration_evaluation import (  # noqa: E402
    ROUTES,
    _read,
    evaluate_files,
    freeze_sample,
    validate_operational_receipts,
    verify_frozen_sample,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    freeze = sub.add_parser("freeze", help="freeze an evidence export without labels")
    freeze.add_argument("input", type=Path)
    freeze.add_argument("output", type=Path)
    report = sub.add_parser(
        "report", help="compare four route predictions on the frozen sample"
    )
    report.add_argument("evidence", type=Path)
    report.add_argument("labels", type=Path)
    report.add_argument("predictions", type=Path)
    report.add_argument("output", type=Path)
    template = sub.add_parser(
        "template", help="create a four-route UNKNOWN export bound to frozen evidence"
    )
    template.add_argument("evidence", type=Path)
    template.add_argument("output", type=Path)
    receipts = sub.add_parser(
        "receipts", help="check seven daily operational receipts structurally"
    )
    receipts.add_argument("input", type=Path)
    receipts.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "freeze":
        result = freeze_sample(_read(args.input), args.output)
        print(
            json.dumps(
                {
                    "sample_sha256": result["sample_sha256"],
                    "cases": len(result["cases"]),
                }
            )
        )
        return 0
    if args.command == "template":
        evidence = _read(args.evidence)
        errors = verify_frozen_sample(evidence)
        if errors:
            parser.error("invalid frozen evidence: " + "; ".join(errors))
        result = {
            "sample_sha256": evidence.get("sample_sha256"),
            "versions": {
                "frozen_sample_sha256": evidence.get("sample_sha256"),
                "context_version": "UNKNOWN",
                "route_versions": {route: "UNKNOWN" for route in ROUTES},
            },
            "routes": {
                route: {
                    "run_state": "NOT_RUN",
                    "version": "UNKNOWN",
                    "metric_provenance": {"kind": "UNKNOWN", "reference": "UNKNOWN"},
                    "case_ids": [row["case_id"] for row in evidence.get("cases", [])],
                    "predictions": [],
                }
                for route in ROUTES
            },
        }
        args.output.write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "sample_sha256": result["sample_sha256"],
                    "routes": len(result["routes"]),
                    "values": "UNKNOWN until measured",
                }
            )
        )
        return 0
    if args.command == "report":
        result = evaluate_files(args.evidence, args.labels, args.predictions)
    else:
        result = validate_operational_receipts(_read(args.input))
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if getattr(args, "output", None):
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 1 if result["status"] == "INVALID" else 0


if __name__ == "__main__":
    raise SystemExit(main())
