"""Read-only comparison of retained D/G RRC handoff evidence."""

from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]


def digest(path: Path) -> tuple[int, str]:
    payload = path.read_bytes()
    return len(payload), hashlib.sha256(payload).hexdigest()


def ledger_inventory() -> list[dict[str, Any]]:
    ledger = (ROOT / ".agent/artifacts/GL3-015D/retrieval-ledger.md").read_text(
        encoding="utf-8"
    )
    found = []
    for name, size, expected in re.findall(
        r"`raw/([^`]+)`\s*\|\s*(\d+)\s*\|\s*`([0-9a-f]{64})`", ledger
    ):
        actual_size, actual_hash = digest(ROOT / ".artifacts/GL3-015D/raw" / name)
        found.append(
            {
                "path": f".artifacts/GL3-015D/raw/{name}",
                "expected_bytes": int(size),
                "actual_bytes": actual_size,
                "expected_sha256": expected,
                "actual_sha256": actual_hash,
                "match": actual_size == int(size) and actual_hash == expected,
            }
        )
    return found


class ListingSummary(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.forms: list[dict[str, Any]] = []
        self.form: dict[str, Any] | None = None
        self.rows: list[dict[str, Any]] = []
        self.row: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if tag == "form":
            self.form = {
                "id": attr.get("id"),
                "method": attr.get("method"),
                "action": attr.get("action"),
                "fields": [],
                "buttons": [],
            }
            self.forms.append(self.form)
        elif tag == "tr":
            self.row = {
                "data_ri": attr.get("data-ri"),
                "data_rk": attr.get("data-rk"),
                "text": [],
            }
        elif self.form is not None and tag == "input":
            if attr.get("type") == "hidden":
                self.form["fields"].append(attr.get("name"))
        elif self.form is not None and tag in ("button", "select"):
            self.form["buttons"].append(
                {"tag": tag, "name": attr.get("name"), "id": attr.get("id")}
            )

    def handle_data(self, data: str) -> None:
        if self.row is not None and data.strip():
            self.row["text"].append(" ".join(data.split()))

    def handle_endtag(self, tag: str) -> None:
        if tag == "tr" and self.row is not None:
            if any(value.casefold() == "daf420.dat" for value in self.row["text"]):
                self.rows.append(self.row)
            self.row = None
        elif tag == "form":
            self.form = None


def listing(path: Path) -> dict[str, Any]:
    size, file_hash = digest(path)
    parsed = ListingSummary()
    parsed.feed(path.read_text(encoding="utf-8", errors="replace"))
    return {
        "bytes": size,
        "sha256": file_hash,
        "matching_rows": parsed.rows,
        "forms": [form for form in parsed.forms if form["id"] in ("fileList", "j_id_3e")],
    }


def compare() -> dict[str, Any]:
    d_listing = listing(ROOT / ".artifacts/GL3-015D/raw/daily-listing.html")
    g_receipt = json.loads((ROOT / ".agent/artifacts/GL3-015G/access.json").read_text())
    g_raw_checks = []
    for item in g_receipt["attempts"]:
        path = ROOT / item["raw_path"]
        size, file_hash = digest(path)
        g_raw_checks.append(
            {
                "path": item["raw_path"],
                "receipt_bytes": item["body_bytes_read"],
                "actual_bytes": size,
                "receipt_sha256": item["sha256_body_read"],
                "actual_sha256": file_hash,
                "match": size == item["body_bytes_read"] and file_hash == item["sha256_body_read"],
            }
        )
    g_listing_attempt = next(item for item in g_receipt["attempts"] if item.get("advertised_file"))
    g_listing = listing(ROOT / g_listing_attempt["raw_path"])
    g_selection = g_receipt["attempts"][2]
    g_download = g_receipt["attempts"][3]
    result = {
        "packet": "GL3-015H",
        "decision": "GO_FOR_ONE_BOUNDED_SAME_HOST_HANDOFF_PROBE",
        "d_reported_success": {
            "folder_guid": "5f07cc72-2e79-4df8-ade1-9aeb792e03fc",
            "file": "daf420.dat",
            "retrievals": 2,
            "status": 200,
            "content_type": "application/force-download",
            "bytes_each": 2391338,
            "sha256_each": "c0215842369f14d6e725b011649ffa0076f373344e3ce5bb0d2ed411fce79cd6",
            "limitation": "D ledger and two retained attachment bodies provide the identical response-body SHA-256, but per-request method, posted fields, headers, Location and redirect sequence are not retained.",
        },
        "d_raw_hash_checks": ledger_inventory(),
        "g_raw_hash_checks": g_raw_checks,
        "d_listing": d_listing,
        "g_listing": {
            "bytes": g_listing_attempt["body_bytes_read"],
            "sha256": g_listing_attempt["sha256_body_read"],
            "row_index": 0,
            "row_key": g_listing_attempt["row_key"],
            "file": g_listing_attempt["advertised_file"],
            "modified": g_listing_attempt["advertised_modified"],
            "advertised_size": g_listing_attempt["advertised_size"],
            "matching_rows": g_listing["matching_rows"],
            "forms": g_listing["forms"],
        },
        "g_selection": {
            "method": g_selection["method"],
            "status": g_selection["status"],
            "content_type": g_selection["content_type"],
            "bytes": g_selection["body_bytes_read"],
            "sha256": g_selection["sha256_body_read"],
            "started_at_utc": g_selection["started_at_utc"],
            "completed_at_utc": g_selection["completed_at_utc"],
        },
        "g_download_button": {
            "method": g_download["method"],
            "url": g_download["url"],
            "status": g_download["status"],
            "location": g_download["location"],
            "content_type": g_download["content_type"],
            "bytes": g_download["body_bytes_read"],
            "sha256": g_download["sha256_body_read"],
        },
        "d_download_request_metadata": "UNKNOWN: per-request method, posted form fields, response headers, Location, and redirect sequence are not retained; the identical attachment response-body SHA-256 is retained and verified for both D files",
        "safe_next_direction": "one separate packet may authorize exactly one explicit HTTPS GET to https://mft.rrc.texas.gov/servlets/fileServer after same-session JSF 302; no automatic redirects; accept only HTTP 200 file attachment with non-HTML/XML body, advertised file size within 5 MB, and <=5 MB response, 20-second timeout, one hop; reject changed host/path, cookies/state failure, other status/type, oversize, or second redirect",
        "current_file_sha256": "UNKNOWN",
        "current_file_compatibility": "UNKNOWN",
        "network_used": False,
    }
    if not all(item["match"] for item in result["d_raw_hash_checks"] + result["g_raw_hash_checks"]):
        raise RuntimeError("retained D/G raw evidence does not match its receipt hashes")
    if len(d_listing["matching_rows"]) != 1 or len(g_listing["matching_rows"]) != 1:
        raise RuntimeError("daily permit row is absent or ambiguous in retained listings")
    if d_listing["matching_rows"][0] != g_listing["matching_rows"][0]:
        raise RuntimeError("D/G exact current-file listing row metadata differs")
    return result


if __name__ == "__main__":
    print(json.dumps(compare(), indent=2, sort_keys=True))
