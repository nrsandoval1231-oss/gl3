"""Store raw captured SQL in receipts and make standalone SQL readable exports."""

from __future__ import annotations

import hashlib
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
PERFORMANCE = ROOT / "docs/validation/customer-intelligence-followup-20261113/performance"
RECEIPTS = (
    "candidate-canonical-page1-actual-retry.json",
    "candidate-canonical-page25-actual-retry.json",
    "candidate-canonical-page50-actual-retry.json",
    "candidate-current-page1-plan.json",
)

prepared: list[tuple[Path, Path, dict, str, str]] = []
for receipt_name in RECEIPTS:
    receipt_path = PERFORMANCE / receipt_name
    receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
    sql_path = PERFORMANCE / receipt["query_file"]
    if "captured_sql" in receipt:
        captured_sql = receipt["captured_sql"]
    else:
        sql_text = sql_path.read_bytes().decode("utf-8").replace("\r\n", "\n")
        captured_sql = sql_text.removesuffix("\n")
    actual_hash = hashlib.sha256(captured_sql.encode("utf-8")).hexdigest()
    if actual_hash != receipt["query_sha256"]:
        raise SystemExit(f"Raw SQL hash does not match receipt: {receipt_name}")
    readable_sql = "\n".join(line.rstrip(" \t") for line in captured_sql.split("\n"))
    readable_sql = readable_sql.rstrip("\n") + "\n"
    if receipt.get("captured_sql", captured_sql) != captured_sql:
        raise SystemExit(f"Existing captured SQL differs from receipt source: {receipt_name}")
    receipt["captured_sql"] = captured_sql
    receipt["query_file_representation"] = "derived_readable_export"
    receipt["query_file_note"] = (
        "Standalone SQL trims trailing horizontal whitespace for readability. "
        "The byte-exact captured statement is in captured_sql; query_sha256 is "
        "computed over its UTF-8 bytes without a terminal newline."
    )
    prepared.append((receipt_path, sql_path, receipt, captured_sql, readable_sql))

for receipt_path, sql_path, receipt, _captured_sql, readable_sql in prepared:
    sql_path.write_bytes(readable_sql.encode("utf-8"))
    receipt_path.write_bytes((json.dumps(receipt, indent=2) + "\n").encode("utf-8"))

failed_path = PERFORMANCE / "first-candidate-timeout-plan.json"
failed_receipt = json.loads(failed_path.read_text(encoding="utf-8-sig"))
current_receipt = json.loads(
    (PERFORMANCE / "candidate-current-page1-plan.json").read_text(encoding="utf-8-sig")
)
failed_script = ast.parse(
    (PERFORMANCE / "capture_failed_candidate_plan.py").read_text(encoding="utf-8")
)
reconstruction_constants = {
    node.targets[0].id: ast.literal_eval(node.value)
    for node in failed_script.body
    if isinstance(node, ast.Assign)
    and isinstance(node.targets[0], ast.Name)
    and node.targets[0].id in {"needle", "old_projection"}
}
current_sql = current_receipt["captured_sql"]
needle = reconstruction_constants["needle"]
if current_sql.count(needle) != 1:
    raise SystemExit("Expected exactly one compact projection in the captured candidate SQL")
reconstructed_sql = current_sql.replace(needle, reconstruction_constants["old_projection"])
reconstructed_hash = hashlib.sha256(reconstructed_sql.encode("utf-8")).hexdigest()
if reconstructed_hash != failed_receipt["statement_hash_sha256"]:
    raise SystemExit("Reconstructed timeout SQL does not match its preserved statement hash")
if failed_receipt.get("captured_sql", reconstructed_sql) != reconstructed_sql:
    raise SystemExit("Existing timeout SQL differs from the hash-verified reconstruction")
failed_receipt["captured_sql"] = reconstructed_sql
failed_receipt["captured_sql_note"] = (
    "Hash-verified reconstruction from candidate-current-page1-plan.json, replacing "
    "only the compact projection with the historical failed variant from "
    "capture_failed_candidate_plan.py; no query was rerun."
)
failed_path.write_bytes((json.dumps(failed_receipt, indent=2) + "\n").encode("utf-8"))

print(
    json.dumps(
        {
            "readable_exports_updated": [item[0].name for item in prepared],
            "hash_verified_timeout_sql_added": failed_path.name,
        },
        indent=2,
    )
)
