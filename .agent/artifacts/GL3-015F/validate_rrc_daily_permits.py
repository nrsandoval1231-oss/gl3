from __future__ import annotations

import json
import argparse
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from gridlens.ingestion.adapters.rrc_daily_permits import (  # noqa: E402
    PROFILE_ID,
    MANUAL_SHA256,
    SOURCE_SHA256,
    parse_daily_permits,
)

RAW = ROOT / ".artifacts/GL3-015D/raw/rrc-daily-permit-current-month.bin"
MANUAL = ROOT / ".artifacts/GL3-015D/raw/drilling-permit-daily-manual.pdf"
D_SAMPLE = ROOT / ".agent/artifacts/GL3-015D/sample-validation.json"


def sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="optional ignored local directory for a timestamped validation/sample export",
    )
    args = parser.parse_args()
    data = RAW.read_bytes()
    parsed = parse_daily_permits(
        data,
        expected_sha256=SOURCE_SHA256,
        profile_id=PROFILE_ID,
    )
    if sha256(MANUAL) != MANUAL_SHA256:
        raise SystemExit("retained RRC manual SHA-256 mismatch")
    prior = json.loads(D_SAMPLE.read_text(encoding="utf-8"))
    wanted = prior["sample"]
    by_key = {
        (row["identity"]["permit_number"], row["identity"]["sequence"]): row
        for row in parsed["records"]
    }
    sample = []
    for item in wanted:
        key = (item["status_number"], item["sequence"])
        record = by_key.get(key)
        if record is None:
            raise SystemExit(f"prior D sample identity missing: {key}")
        got_dates = record["dates"]
        comparisons = {
            "county_code": record["approved_county_code"],
            "lease_name": record["approved_lease_name"],
            "well_number": record["well_number"],
            "application_received": got_dates["application_received"]["raw"],
            "permit_issued": got_dates["permit_issued"]["raw"],
            "api8": record["api8"],
        }
        for field, value in comparisons.items():
            if value != item[field]:
                raise SystemExit(f"D sample mismatch for {key}: {field}")
        sample.append(
            {
                "identity": f"{key[0]}/{key[1]}",
                "source_lines": record["citation"]["lines"],
                "approved_county_code": record["approved_county_code"],
                "approved_lease_name": record["approved_lease_name"],
                "well_number": record["well_number"],
                "dates": got_dates,
                "api8": record["api8"],
            }
        )

    if parsed["physical_lines"] != 29494:
        raise SystemExit("physical line count differs from validated D profile")
    if parsed["classified_segments"] != 29459 or parsed["opaque_unknown_count"] != 35:
        raise SystemExit("classified/opaque counts differ from validated D profile")
    if parsed["permit_revision_count"] != 884 or parsed["unique_permit_revision_keys"] != 884:
        raise SystemExit("permit revision count/key uniqueness differs from validated D profile")
    receipt = {
        "packet": "GL3-015F",
        "decision": "GO",
        "decision_scope": "Offline parser proof for this exact retained RRC file/profile only; source remains nonactivated.",
        "validated_at_utc": datetime.now(UTC).isoformat(),
        "source": {
            "path": ".artifacts/GL3-015D/raw/rrc-daily-permit-current-month.bin",
            "bytes": len(data),
            "sha256": sha256(RAW),
            "manual_path": ".artifacts/GL3-015D/raw/drilling-permit-daily-manual.pdf",
            "manual_bytes": MANUAL.stat().st_size,
            "manual_sha256": sha256(MANUAL),
        },
        "candidate_files": {
            relative: sha256(ROOT / relative)
            for relative in (
                "backend/src/gridlens/ingestion/adapters/rrc_daily_permits.py",
                "backend/tests/unit/test_rrc_daily_permits.py",
                "docs/validation/gl3-015-rrc-adapter-proof.md",
                ".agent/artifacts/GL3-015F/validate_rrc_daily_permits.py",
            )
        },
        "profile_id": PROFILE_ID,
        "physical_lines": parsed["physical_lines"],
        "classified_segments": parsed["classified_segments"],
        "segment_counts": parsed["segment_counts"],
        "permit_revision_count": parsed["permit_revision_count"],
        "unique_permit_revision_keys": parsed["unique_permit_revision_keys"],
        "opaque_unknown_count": parsed["opaque_unknown_count"],
        "opaque_unknown_lines": parsed["opaque_unknown_lines"],
        "unknown_semantics": "UNKNOWN; 35 lines start 0x85; no decoding or meaning inferred",
        "sample_prior_D_matches": len(sample),
        "sample": sample,
        "limits": [
            "No source activation, network access, database writes, or application observations.",
            "Only the pinned type-01/type-02 fields are parsed; other known segment families are counted only.",
            "API8 is retained as a field and is not used as permit revision identity or a join key.",
            "Zero date values are preserved as raw 00000000 with normalized date null; no negative event is inferred.",
            "No pad, operator, production, electrification, demand, opportunity tier, or timing estimate is derived.",
        ],
    }
    if args.output_dir is not None:
        output_dir = args.output_dir.resolve()
        ignored_root = (ROOT / ".artifacts").resolve()
        if not output_dir.is_relative_to(ignored_root):
            raise SystemExit("--output-dir must be under the ignored repository .artifacts directory")
        rel_output = output_dir.relative_to(ROOT)
        check = subprocess.run(
            ["git", "check-ignore", "--quiet", "--", str(rel_output / "validation.json")],
            cwd=ROOT,
            check=False,
        )
        if check.returncode != 0:
            raise SystemExit("--output-dir is not ignored by Git")
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "validation.json").write_text(
            json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
        )
        (output_dir / "sample.json").write_text(
            json.dumps(sample, indent=2) + "\n", encoding="utf-8"
        )
    summary = {
        key: receipt[key]
        for key in (
            "decision",
            "source",
            "candidate_files",
            "physical_lines",
            "classified_segments",
            "permit_revision_count",
            "unique_permit_revision_keys",
            "opaque_unknown_count",
            "sample_prior_D_matches",
        )
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
