"""Strict response comparison allowing only commercial freshness clock drift."""

from __future__ import annotations

import hashlib
import json
import argparse
from pathlib import Path

OUT = Path(__file__).resolve().parent


def without_allowed_freshness_as_of(value, path=()):
    if isinstance(value, dict):
        return {
            key: without_allowed_freshness_as_of(item, path + (key,))
            for key, item in value.items()
            if not (key == "as_of" and path[-2:] == ("commercial_brief", "freshness"))
        }
    if isinstance(value, list):
        return [
            without_allowed_freshness_as_of(item, path + (index,))
            for index, item in enumerate(value)
        ]
    return value


def compare(left, right, path=(), allowed_differences=None):
    if allowed_differences is None:
        allowed_differences = []
    if isinstance(left, dict) and isinstance(right, dict):
        if set(left) != set(right):
            return [(path, "object_keys_changed")]
        differences = []
        for key in sorted(left):
            child = path + (key,)
            if (
                key == "as_of"
                and child[-3:] == ("commercial_brief", "freshness", "as_of")
                and left[key] != right[key]
            ):
                allowed_differences.append(
                    "$"
                    + "".join(
                        f"[{part}]" if isinstance(part, int) else f".{part}"
                        for part in child
                    )
                )
            else:
                differences.extend(
                    compare(left[key], right[key], child, allowed_differences)
                )
        return differences
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return [(path, "array_length_changed")]
        differences = []
        for index, (left_item, right_item) in enumerate(zip(left, right, strict=True)):
            differences.extend(
                compare(left_item, right_item, path + (index,), allowed_differences)
            )
        return differences
    return [] if left == right else [(path, "value_changed")]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--after-phase", choices=("after", "after_facet"), default="after"
    )
    args = parser.parse_args()
    results = []
    for shortlist in (False, True):
        mode = "shortlist_" if shortlist else ""
        for canonical_only in (False, True):
            label = "true" if canonical_only else "false"
            before_path = OUT / f"before_payload_{mode}{label}.json"
            after_path = OUT / f"{args.after_phase}_payload_{mode}{label}.json"
            if not before_path.exists() or not after_path.exists():
                raise SystemExit(
                    f"Missing payload snapshot: {before_path} or {after_path}"
                )
            before_bytes = before_path.read_bytes()
            after_bytes = after_path.read_bytes()
            before = json.loads(before_bytes)
            after = json.loads(after_bytes)
            allowed_differences: list[str] = []
            differences = compare(
                before, after, allowed_differences=allowed_differences
            )
            normalized_before = json.dumps(
                without_allowed_freshness_as_of(before),
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
            normalized_after = json.dumps(
                without_allowed_freshness_as_of(after),
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
            results.append(
                {
                    "canonical_only": canonical_only,
                    "shortlist": shortlist,
                    "before_file": before_path.name,
                    "after_file": after_path.name,
                    "before_sha256": hashlib.sha256(
                        before_bytes.rstrip(b"\n")
                    ).hexdigest(),
                    "after_sha256": hashlib.sha256(
                        after_bytes.rstrip(b"\n")
                    ).hexdigest(),
                    "normalized_before_sha256": hashlib.sha256(
                        normalized_before
                    ).hexdigest(),
                    "normalized_after_sha256": hashlib.sha256(
                        normalized_after
                    ).hexdigest(),
                    "before_bytes": len(before_bytes.rstrip(b"\n")),
                    "after_bytes": len(after_bytes.rstrip(b"\n")),
                    "before_total": before["total"],
                    "after_total": after["total"],
                    "before_page_count": len(before["items"]),
                    "after_page_count": len(after["items"]),
                    "only_allowed_freshness_as_of_paths_ignored": allowed_differences,
                    "differences_outside_allowed_freshness_as_of": differences,
                    "equal_except_allowed_freshness_as_of": not differences,
                    "all_other_as_of_values_compared_exactly": True,
                }
            )
    receipt = {
        "comparison": "All response JSON fields and array ordering compared recursively; only *.commercial_brief.freshness.as_of paths were ignored. Every other as_of value, including top-level and commercial_intelligence.as_of, was compared exactly.",
        "source_db": "gl3_mission_rollup_scale_payload_20261113_test",
        "candidate_db": (
            "gl3_mission_rollup_scale_payload_after_facet_20261113_test"
            if args.after_phase == "after_facet"
            else "gl3_mission_rollup_scale_payload_after_20261113_test"
        ),
        "controlled_clone_policy_adjustment": (
            "See controlled_policy_binding_adjustment_after_facet.json; only candidate clone's current generation policy_version was rebound to the candidate source fingerprint."
            if args.after_phase == "after_facet"
            else "See controlled_policy_binding_adjustment.json; only candidate clone's current generation policy_version was rebound to the candidate source fingerprint."
        ),
        "combinations": results,
        "all_equal_except_allowed_freshness_as_of": all(
            item["equal_except_allowed_freshness_as_of"] for item in results
        ),
        "negative_control": {
            "description": "An artificial change to the top-level snapshot as_of value must be detected.",
            "detected": compare(
                json.loads(
                    (OUT / "before_payload_true.json").read_text(encoding="utf-8")
                ),
                {
                    **json.loads(
                        (OUT / "before_payload_true.json").read_text(encoding="utf-8")
                    ),
                    "as_of": "negative-control-different-clock",
                },
            )
            == [(("as_of",), "value_changed")],
        },
    }
    path = OUT / (
        "strict_freshness_parity_after_facet.json"
        if args.after_phase == "after_facet"
        else "strict_freshness_parity.json"
    )
    if path.exists():
        raise SystemExit(f"Refusing to overwrite {path}")
    path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
