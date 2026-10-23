"""Southwest Power Pool active generator-interconnection queue for OK and NM.

The queue is a public CSV. It is generation injection, not a large-load or
data-center queue. This adapter keeps Oklahoma and New Mexico thermal or gas
requests, plus any row whose text names a data center. Wind, solar, and
storage-only rows are left in the file and not emitted.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime
from typing import Any

import httpx

from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.power_signals import power_signal_tags
from gridlens.ingestion.adapters.public_source_http import read_public_response

SOURCE_ID = "spp-thermal-interconnection"
QUEUE_URL = "https://opsportal.spp.org/Studies/GenerateActiveCSV"
HOST = "opsportal.spp.org"
MAX_RESPONSE_BYTES = 2_000_000
MAX_QUEUE_ROWS = 5000
MAX_RECORDS = 200
_STATES = {"OK", "NM"}
_THERMAL_FUELS = {
    "gas",
    "ct",
    "ctg",
    "combined cycle",
    "combustion turbine",
    "reciprocating combustion engine",
    "thermal/storage",
    "gas/storage",
    "steam turbine",
}
_REQUIRED = {
    "Generation Interconnection Number",
    "State",
    "Nearest Town or County",
    "Generation Type",
    "Fuel Type",
    "Capacity",
    "Request Received",
    "Status",
    "In-Service Date",
    "Substation or Line",
}
_DATA_CENTER = re.compile(r"data\s*cent(?:er|re)|hyperscale", re.IGNORECASE)


def _normalize(row: dict[str, str | None]) -> dict[str, str]:
    return {str(key).strip(): (value or "").strip() for key, value in row.items()}


def _received(value: str) -> str | None:
    if not value:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    raise SourceParseError("SPP request-received date is malformed")


def _keep(row: dict[str, str]) -> bool:
    if row.get("State") not in _STATES:
        return False
    blob = " ".join(row.values())
    if _DATA_CENTER.search(blob):
        return True
    if row.get("Generation Type", "").casefold() == "thermal":
        return True
    return row.get("Fuel Type", "").casefold() in _THERMAL_FUELS


def parse_queue(body: bytes) -> tuple[str | None, list[dict[str, Any]]]:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceParseError("SPP queue is not UTF-8") from exc
    lines = text.splitlines()
    if not lines or not lines[0].startswith('"Last Updated On"'):
        raise SourceParseError("SPP queue is missing its update stamp")
    updated = lines[0].split(",")[1].strip().strip('"') if "," in lines[0] else None
    if updated:
        _received(updated)
    reader = csv.DictReader(lines[1:])
    fieldnames = {name.strip() for name in (reader.fieldnames or [])}
    if not _REQUIRED <= fieldnames:
        raise SourceParseError("SPP queue columns changed")
    raw_rows = list(reader)
    if len(raw_rows) > MAX_QUEUE_ROWS:
        raise SourceParseError("SPP queue row count exceeds its bound")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_rows:
        row = _normalize(raw)
        if not _keep(row):
            continue
        number = row["Generation Interconnection Number"]
        if not number:
            raise SourceParseError("SPP queue row lacks an interconnection number")
        if number in seen:
            raise SourceParseError("SPP queue has a duplicate interconnection number")
        seen.add(number)
        place = row["Nearest Town or County"]
        state = row["State"]
        blob = " ".join(row.values())
        records.append(
            {
                "number": number,
                "state": state,
                "place": place,
                "location": f"{place}, {state}" if place else None,
                "generation_type": row["Generation Type"],
                "fuel": row["Fuel Type"],
                "capacity": row["Capacity"],
                "status": row["Status"],
                "received": _received(row["Request Received"]),
                "in_service": row["In-Service Date"],
                "substation": row["Substation or Line"],
                "tags": power_signal_tags(blob),
                "data_center": bool(_DATA_CENTER.search(blob)),
            }
        )
    if len(records) > MAX_RECORDS:
        raise SourceParseError("SPP relevant row count exceeds its bound")
    return updated, records


def _record(row: dict[str, Any], updated: str | None) -> dict[str, Any]:
    row_id = f"SPP-{row['number']}"
    semantic = {key: row[key] for key in row if key != "tags"}
    semantic["queue_updated"] = updated
    semantic["power_signals"] = row["tags"]
    return {
        "document_number": row_id,
        "title": f"{row['number']} — SPP {row['fuel'] or row['generation_type']} interconnection",
        "abstract": "\n".join(
            [
                f"Interconnection number: {row['number']}",
                f"State: {row['state']}",
                f"Nearest town or county: {row['place'] or 'not stated'}",
                f"Generation type: {row['generation_type'] or 'not stated'}",
                f"Fuel: {row['fuel'] or 'not stated'}",
                "Queue capacity MW (generation injection, not site load): "
                + (row["capacity"] or "not stated"),
                f"Status: {row['status'] or 'not stated'}",
                f"Request received: {row['received'] or 'not stated'}",
                f"In-service date: {row['in_service'] or 'not stated'}",
                f"Substation or line: {row['substation'] or 'not stated'}",
                f"Queue updated: {updated or 'not stated'}",
                f"Power signal tags: {', '.join(row['tags']) or 'none'}",
            ]
        ),
        "publication_date": None,
        "event_date": row["received"],
        "event_date_label": "Request received (SPP active GI queue)",
        "html_url": QUEUE_URL,
        "extraction_location": "SPP GenerateActiveCSV row",
        "source_hash": hashlib.sha256(
            json.dumps(semantic, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "permit": {
            "source_type": SOURCE_ID,
            "row_id": row_id,
            "applicant": None,
            "facility": row["number"],
            "status": row["status"],
            "description": (
                f"{row['generation_type']} {row['fuel']} interconnection {row['number']} "
                f"capacity {row['capacity']} MW"
            ).strip(),
            "location": row["location"],
            "state": row["state"],
            "county": row["place"] or None,
            "capacity_mw": row["capacity"] or None,
            "power_signals": row["tags"],
            "data_center": row["data_center"],
            "document_links": {"SPP active generator interconnection queue": QUEUE_URL},
            "source_fields": {
                "facility": "Generation Interconnection Number",
                "location": "Nearest Town or County, State",
                "capacity": "Capacity",
                "event_date": "Request Received",
                "status": "Status",
            },
        },
    }


def retrieve(source: dict[str, Any], client: httpx.Client | None = None) -> list[dict[str, Any]]:
    if source.get("id") != SOURCE_ID or source.get("endpoint") != QUEUE_URL:
        raise SourceParseError("SPP source ID or endpoint is not configured")
    query = source.get("query", {})
    if (
        query.get("max_response_bytes") != MAX_RESPONSE_BYTES
        or query.get("max_queue_rows") != MAX_QUEUE_ROWS
        or query.get("max_records") != MAX_RECORDS
    ):
        raise SourceParseError("SPP query bounds are invalid")
    http = client or httpx.Client(timeout=25, follow_redirects=False, trust_env=False)
    try:
        _, body = read_public_response(
            http,
            QUEUE_URL,
            max_bytes=MAX_RESPONSE_BYTES,
            allowed_media_types={"text/csv"},
            allowed_hosts=frozenset({HOST}),
        )
        updated, rows = parse_queue(body)
        return [_record(row, updated) for row in rows]
    finally:
        if client is None:
            http.close()
