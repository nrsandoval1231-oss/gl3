from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from bounded_rrc_http import bounded_request
from rrc_current_access import (
    FOLDER_URL,
    GO_DRIVE,
    INDEX_URL,
    MAX_RESPONSE_BYTES,
    MAX_RUN_BYTES,
    AccessError,
    ListingSelection,
    download_post,
    parse_index,
    parse_listing,
    selected_view_state,
    selection_post,
    validate_attachment,
    validate_jsf_partial,
    validate_response,
)
from verify_rrc_compat import verify_snapshot

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / ".agent/artifacts/GL3-015G"
RAW = ROOT / ".artifacts/GL3-015G/raw"
F_ACCEPTED_SHA256 = "c0215842369f14d6e725b011649ffa0076f373344e3ce5bb0d2ed411fce79cd6"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _request_capture(
    client: httpx.Client,
    method: str,
    url: str,
    filename: str,
    ledger: list[dict[str, Any]],
    accounting: dict[str, int],
    *,
    data: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes, dict[str, Any]]:
    started = datetime.now(UTC).isoformat()
    try:
        status, headers, body, meta = bounded_request(
            client, method, url, data=data, run_bytes=accounting
        )
    except httpx.HTTPError as exc:
        ledger.append(
            {
                "method": method,
                "url": url,
                "started_at_utc": started,
                "failed_at_utc": datetime.now(UTC).isoformat(),
                "failure": f"{type(exc).__name__}: {exc}",
                "body_bytes_read": 0,
                "raw_path": None,
            }
        )
        raise
    raw_path = RAW / filename
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(body)
    meta.update(
        {
            "method": method,
            "started_at_utc": started,
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "sha256_body_read": _sha256(body),
            "raw_path": str(raw_path.relative_to(ROOT)).replace("\\", "/"),
        }
    )
    ledger.append(meta)
    if len(body) > MAX_RESPONSE_BYTES:
        raise AccessError(f"response exceeded {MAX_RESPONSE_BYTES} byte limit")
    if accounting["bytes"] > MAX_RUN_BYTES:
        raise AccessError(f"run exceeded {MAX_RUN_BYTES} byte limit")
    return status, headers, body, meta


def _assert_html(status: int, headers: dict[str, str], url: str, body: bytes) -> None:
    validate_response(
        status=status,
        headers=headers,
        url=url,
        body=body,
        max_bytes=MAX_RESPONSE_BYTES,
    )
    if "html" not in headers.get("content-type", "").casefold():
        raise AccessError("official source returned non-HTML response for page request")


def _one_pull(
    index_confirmed_url: str,
    pull_number: int,
    ledger: list[dict[str, Any]],
    accounting: dict[str, int],
) -> tuple[bytes, dict[str, Any]]:
    selection: ListingSelection
    with httpx.Client(follow_redirects=False, timeout=20.0) as client:
        status, headers, listing, listing_meta = _request_capture(
            client,
            "GET",
            index_confirmed_url,
            f"{RUN_ID}-listing-{pull_number}.html",
            ledger,
            accounting,
        )
        _assert_html(status, headers, index_confirmed_url, listing)
        selection = parse_listing(listing)
        listing_meta["advertised_file"] = selection.filename
        listing_meta["advertised_modified"] = selection.modified
        listing_meta["advertised_size"] = selection.advertised_size
        listing_meta["row_key"] = selection.row_key

        status, headers, selected, _ = _request_capture(
            client,
            "POST",
            GO_DRIVE,
            f"{RUN_ID}-selection-{pull_number}.xml",
            ledger,
            accounting,
            data=selection_post(selection),
        )
        validate_jsf_partial(status, headers, GO_DRIVE, selected)
        view_state = selected_view_state(selected, selection.view_state)
        request_data = download_post(listing, view_state)
        status, headers, payload, pull_meta = _request_capture(
            client,
            "POST",
            GO_DRIVE,
            f"{RUN_ID}-permit-{pull_number}.dat",
            ledger,
            accounting,
            data=request_data,
        )
        validate_attachment(status, headers, GO_DRIVE, payload)
        if len(payload) > MAX_RESPONSE_BYTES:
            raise AccessError(f"permit file exceeded {MAX_RESPONSE_BYTES} byte limit")
        pull_meta.update(
            {
                "advertised_modified": selection.modified,
                "advertised_size": selection.advertised_size,
                "row_index": 0,
            }
        )
        return payload, pull_meta


def perform_probe(client: httpx.Client | None = None) -> dict[str, Any]:
    global RUN_ID
    RUN_ID = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    ledger: list[dict[str, Any]] = []
    accounting = {"bytes": 0}
    own_client = client is None
    session = client or httpx.Client(follow_redirects=False, timeout=20.0)
    receipt: dict[str, Any] = {
        "packet": "GL3-015G",
        "decision": "REDIRECT",
        "validated_at_utc": datetime.now(UTC).isoformat(),
        "request_allowlist": [INDEX_URL, FOLDER_URL, GO_DRIVE],
        "pull_limit": 2,
        "response_limit_bytes": MAX_RESPONSE_BYTES,
        "run_limit_bytes": MAX_RUN_BYTES,
        "attempts": ledger,
        "file_pulls": [],
        "compatibility": {},
        "run_bytes_read": 0,
    }
    try:
        status, headers, index, _ = _request_capture(
            session, "GET", INDEX_URL, f"{RUN_ID}-index.html", ledger, accounting
        )
        _assert_html(status, headers, INDEX_URL, index)
        folder_url = parse_index(index)
        pulls: list[tuple[bytes, dict[str, Any]]] = []
        for number in (1, 2):
            payload, metadata = _one_pull(folder_url, number, ledger, accounting)
            metadata.update({"sha256": _sha256(payload), "bytes": len(payload)})
            pulls.append((payload, metadata))
            receipt["file_pulls"].append(metadata)
            digest = metadata["sha256"]
            if digest not in receipt["compatibility"]:
                receipt["compatibility"][digest] = verify_snapshot(payload)
        hashes = [meta["sha256"] for _, meta in pulls]
        listing_versions = [
            (meta["advertised_modified"], meta["advertised_size"]) for _, meta in pulls
        ]
        if hashes[0] != hashes[1] or listing_versions[0] != listing_versions[1]:
            receipt["reason"] = "independent pulls or advertised listing versions changed"
            receipt["decision"] = "REDIRECT"
        elif hashes[0] == F_ACCEPTED_SHA256:
            receipt["decision"] = "GO_SAME_SNAPSHOT_ONLY"
            receipt["reason"] = "current archive hash matches accepted F snapshot; no new-hash claim"
        elif receipt["compatibility"][hashes[0]]["decision"] == "GO":
            receipt["decision"] = "GO_FOR_EXACT_HASH"
            receipt["reason"] = "both official pulls match and independent compatibility checks passed"
        else:
            receipt["decision"] = "REDIRECT"
            receipt["reason"] = receipt["compatibility"][hashes[0]].get(
                "reason", "new file failed accepted profile compatibility"
            )
    except (AccessError, httpx.HTTPError, OSError, ValueError) as exc:
        receipt["decision"] = "REDIRECT"
        receipt["reason"] = f"bounded probe stopped: {type(exc).__name__}: {exc}"
    finally:
        receipt["attempts"] = ledger
        receipt["run_bytes_read"] = accounting["bytes"]
        if own_client:
            session.close()
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="One bounded official RRC current-file access probe")
    parser.add_argument("--fetch", action="store_true", required=True)
    args = parser.parse_args()
    if not args.fetch:
        parser.error("--fetch is required to make public requests")
    receipt = perform_probe()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "access.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "decision": receipt["decision"],
                "file_pulls": [
                    {key: pull.get(key) for key in ("sha256", "bytes", "advertised_modified", "advertised_size")}
                    for pull in receipt["file_pulls"]
                ],
                "reason": receipt.get("reason"),
                "run_bytes_read": receipt["run_bytes_read"],
                "access_receipt": ".agent/artifacts/GL3-015G/access.json",
            },
            sort_keys=True,
        )
    )
    return 0 if receipt["decision"].startswith("GO") else 2


if __name__ == "__main__":
    raise SystemExit(main())
