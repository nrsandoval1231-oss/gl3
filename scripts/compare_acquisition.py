"""Inspect immutable native captures or run an explicitly bounded comparison."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path

from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND / "src"))
sys.path.insert(0, str(BACKEND))

from gridlens.ingestion.compare_acquisition import (  # noqa: E402
    FIRECRAWL_MAX_TEXT_CHARS,
    compare_case,
    load_manifest,
    normalize_capture,
    report_complete,
    scrape_html,
    validate_capture,
)
from gridlens.settings import settings  # noqa: E402


def _load_captures(directory: Path, cases: list[dict]) -> dict[str, dict]:
    output = {}
    by_id = {case["case_id"]: case for case in cases}
    for path in sorted(directory.glob("*.json")):
        if path.name == "COMPLETION.json":
            continue
        row = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("case_id"), str)
            or row["case_id"] not in by_id
        ):
            raise ValueError(f"Invalid capture file: {path.name}")
        if row["case_id"] in output:
            raise ValueError(f"Duplicate native capture: {row['case_id']}")
        # Resolve text paths relative to the immutable receipt and reject path escape.
        text_path = row.get("extracted_text_path")
        if isinstance(text_path, str):
            candidate = Path(text_path)
            if candidate.is_absolute():
                raise ValueError("Capture text path must be relative to its receipt")
            resolved = (path.parent / candidate).resolve()
            if path.parent.resolve() not in resolved.parents:
                raise ValueError("Capture text path escapes its receipt directory")
            if not resolved.is_file():
                raise ValueError("Capture text path does not exist")
            if hashlib.sha256(resolved.read_bytes()).hexdigest() != row.get(
                "text_sha256"
            ):
                raise ValueError("Native extracted text SHA-256 does not match receipt")
            row["extracted_text_path"] = str(resolved)
        raw_path = row.get("raw_path")
        if isinstance(raw_path, str):
            raw_resolved = Path(raw_path)
            if not raw_resolved.is_absolute():
                raw_resolved = (path.parent / raw_resolved).resolve()
            if path.parent.resolve() not in raw_resolved.parents:
                raise ValueError("Capture raw path escapes its receipt directory")
            raw_bytes = raw_resolved.read_bytes()
            if len(raw_bytes) > by_id[row["case_id"]]["max_bytes"]:
                raise ValueError(
                    "Native raw capture exceeds the existing source adapter byte bound"
                )
            if hashlib.sha256(raw_bytes).hexdigest() != row.get("raw_sha256"):
                raise ValueError("Native raw capture SHA-256 does not match receipt")
            row["raw_path"] = str(raw_resolved)
            row["raw_size_bytes"] = len(raw_bytes)
        output[row["case_id"]] = normalize_capture(by_id[row["case_id"]], row)
    return output


def _require_isolated_database() -> None:
    url = make_url(settings.database_url)
    if (
        url.host not in {"127.0.0.1", "localhost", "::1"}
        or url.port != 55443
        or url.database != "pipeline_m2_app"
        or url.query
    ):
        raise ValueError(
            "Dispatch requires the exact isolated loopback pipeline_m2_app database"
        )


def _validate_dispatch_caps(args: argparse.Namespace, eligible_count: int) -> None:
    if (
        args.max_calls < 1
        or args.max_credits < args.max_calls
        or not args.max_cost_usd.is_finite()
        or args.max_cost_usd <= 0
    ):
        raise ValueError(
            "Dispatch requires positive finite call, credit, and cost caps"
        )
    if args.max_calls > eligible_count:
        raise ValueError("Call cap exceeds eligible HTML case count")
    if settings.firecrawl_api_key is None or settings.firecrawl_scrape_cost_usd is None:
        raise ValueError(
            "Firecrawl credentials and configured scrape cost are required before dispatch"
        )
    if settings.firecrawl_scrape_cost_usd * args.max_calls > args.max_cost_usd:
        raise ValueError(
            "Configured Firecrawl reservations exceed the explicit run cost cap"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "config/comparisons/production-five-sources.v1.json",
    )
    parser.add_argument(
        "--captures",
        type=Path,
        required=True,
        help="Immutable native adapter captures as one JSON file per case",
    )
    parser.add_argument(
        "--dispatch",
        action="store_true",
        help="Explicitly dispatch eligible exact HTML through the existing ledger",
    )
    parser.add_argument("--max-calls", type=int, default=0)
    parser.add_argument("--max-credits", type=int, default=0)
    parser.add_argument("--max-cost-usd", type=Decimal, default=Decimal("0"))
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the complete-text report to this local artifact path",
    )
    args = parser.parse_args()
    manifest = load_manifest(args.manifest)
    cases = manifest["cases"]
    captures = _load_captures(args.captures, cases)
    eligible_count = sum(
        case["media_type"].lower() in {"text/html", "application/xhtml+xml"}
        for case in cases
    )
    rows = []
    if args.dispatch:
        _require_isolated_database()
        _validate_dispatch_caps(args, eligible_count)
        # Validate every supplied complete receipt before any paid request. Missing
        # cases remain explicit in the report; malformed supplied receipts abort.
        for case in cases:
            capture = captures.get(case["case_id"])
            if capture is not None and capture.get("capture_kind") != "INCOMPLETE":
                validate_capture(case, capture)
    attempted_calls = 0
    for case in cases:
        capture = captures.get(case["case_id"])
        if capture is None:
            rows.append(
                {
                    "case_id": case["case_id"],
                    "native": {
                        "status": "INCOMPLETE",
                        "error_code": "NATIVE_CAPTURE_MISSING",
                    },
                    "firecrawl": {"status": "NOT_RUN", "logical_call_id": None},
                }
            )
            continue
        if (
            capture.get("capture_kind") == "INCOMPLETE"
            or capture.get("status") == "INCOMPLETE"
        ):
            rows.append(
                {
                    "case_id": case["case_id"],
                    "native": {
                        "status": "INCOMPLETE",
                        "capture_id": capture.get("capture_id"),
                        "error_code": capture.get("error_code", capture.get("error")),
                    },
                    "firecrawl": {"status": "NOT_RUN", "logical_call_id": None},
                }
            )
            continue
        native = validate_capture(case, capture)
        firecrawl = None
        if not native["eligible_html"]:
            firecrawl = {
                "status": "UNSUPPORTED",
                "error_code": "NATIVE_MEDIA_TYPE_NOT_HTML",
                "logical_call_id": None,
                "latency_ms": 0,
                "actual_cost_usd": None,
                "reserved_cost_usd": "0",
            }
        elif args.dispatch and len(native["text"]) > FIRECRAWL_MAX_TEXT_CHARS:
            firecrawl = {
                "status": "NOT_NEEDED",
                "disposition": "SKIPPED_NATIVE_TEXT_EXCEEDS_PROVIDER_BOUND",
                "logical_call_id": None,
                "latency_ms": 0,
                "actual_cost_usd": None,
                "reserved_cost_usd": "0",
            }
        elif args.dispatch and attempted_calls < args.max_calls:
            attempted_calls += 1
            firecrawl = scrape_html(
                native,
                api_key=settings.firecrawl_api_key.get_secret_value(),
                cost_cap_usd=args.max_cost_usd,
            )
        elif args.dispatch:
            firecrawl = {
                "status": "INCOMPLETE",
                "error_code": "FINITE_CALL_CAP_REACHED",
                "logical_call_id": None,
                "latency_ms": 0,
                "actual_cost_usd": None,
                "reserved_cost_usd": "0",
            }
        rows.append(compare_case(case, capture, firecrawl=firecrawl))
    report = {
        "manifest_version": manifest["version"],
        "complete": report_complete(rows),
        "live_html_scrape": any(
            row.get("firecrawl", {}).get("status") == "COMPLETED"
            and row.get("firecrawl", {}).get("cached") is False
            for row in rows
        ),
        "cases": rows,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "complete": report["complete"],
                    "live_html_scrape": report["live_html_scrape"],
                    "output": str(args.output),
                },
                sort_keys=True,
            )
        )
    else:
        print(rendered)
    return 0 if report["complete"] else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError) as exc:
        raise SystemExit(f"comparison incomplete: {type(exc).__name__}: {exc}") from exc
