"""City of Albuquerque building permits that name a data center or site power.

The city publishes one CSV of historical permits. Rows are kept when the
description names a data center, or when a commercial permit names a generator,
turbine, or explicit temporary, bridge, or behind-the-meter power. Undated rows
are not emitted. The window is measured from the issue date.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.power_signals import power_signal_tags
from gridlens.ingestion.adapters.public_source_http import read_public_response

SOURCE_ID = "albuquerque-building-permits"
CSV_URL = "https://data.cabq.gov/business/buildingpermits/BuildingPermitsCABQ-en-us.csv"
HOST = "data.cabq.gov"
MAX_RESPONSE_BYTES = 28_000_000
MAX_RECORDS = 200
WINDOW_DAYS = 730
_DATA_CENTER = re.compile(r"data\s*cent(?:er|re)|hyperscale", re.IGNORECASE)
_POWER = re.compile(
    r"generator|turbine|temporary power|bridge power|behind[- ]the[- ]meter|construction power",
    re.IGNORECASE,
)
_REQUIRED = {
    "ApplicationPermitNumber",
    "SiteNumber",
    "SiteStreet",
    "SiteStreetType",
    "SiteZip",
    "TypeofWork",
    "Description",
    "OwnerName",
    "IssueDate",
    "Status",
    "PlanCheckValuation",
}


def _issued(value: str) -> str | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").date().isoformat()
    except ValueError as exc:
        raise SourceParseError("Albuquerque permit issue date is malformed") from exc


def _address(row: dict[str, str]) -> str | None:
    street = " ".join(
        part
        for part in (
            row.get("SiteNumber", ""),
            row.get("SiteStreet", ""),
            row.get("SiteStreetType", ""),
        )
        if part
    )
    zip_code = row.get("SiteZip", "")
    if street:
        return f"{street}, Albuquerque, NM{f' {zip_code}' if zip_code else ''}"
    return "Albuquerque, NM"


def parse_permits(body: bytes, *, today: date) -> list[dict[str, Any]]:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceParseError("Albuquerque permit file is not UTF-8") from exc
    reader = csv.DictReader(io.StringIO(text))
    fieldnames = set(reader.fieldnames or [])
    if not _REQUIRED <= fieldnames:
        raise SourceParseError("Albuquerque permit columns changed")
    start = today - timedelta(days=WINDOW_DAYS)
    grouped: dict[str, dict[str, str]] = {}
    for raw in reader:
        row = {key: (value or "").strip() for key, value in raw.items() if key}
        number = row.get("ApplicationPermitNumber", "")
        description = row.get("Description", "")
        work = row.get("TypeofWork", "")
        relevant = bool(_DATA_CENTER.search(description)) or (
            "Commercial" in work and bool(_POWER.search(description))
        )
        if not number or not relevant:
            continue
        issued = _issued(row.get("IssueDate", ""))
        if issued is None:
            continue
        issued_day = date.fromisoformat(issued)
        if issued_day < start or issued_day > today:
            continue
        previous = grouped.get(number)
        if previous and previous.get("Description") != description:
            raise SourceParseError("Albuquerque permit identity has conflicting descriptions")
        grouped.setdefault(number, row)
    if len(grouped) > MAX_RECORDS:
        raise SourceParseError("Albuquerque relevant permit count exceeds its bound")
    permits: list[dict[str, Any]] = []
    for number, row in sorted(grouped.items()):
        description = row["Description"]
        blob = f"{description} {row.get('TypeofWork', '')}"
        permits.append(
            {
                "number": number,
                "work": row.get("TypeofWork", ""),
                "description": description,
                "status": row.get("Status", ""),
                "issued": _issued(row.get("IssueDate", "")),
                "owner": row.get("OwnerName") or None,
                "valuation": row.get("PlanCheckValuation") or None,
                "location": _address(row),
                "tags": power_signal_tags(blob),
                "data_center": bool(_DATA_CENTER.search(description)),
            }
        )
    return permits


def _record(permit: dict[str, Any]) -> dict[str, Any]:
    row_id = f"CABQ-{permit['number']}"
    return {
        "document_number": row_id,
        "title": f"{permit['number']} — Albuquerque {permit['work'] or 'building permit'}",
        "abstract": "\n".join(
            [
                f"Permit: {permit['number']}",
                f"Work type: {permit['work'] or 'not stated'}",
                f"Description: {permit['description']}",
                f"Status: {permit['status'] or 'not stated'}",
                f"Issued: {permit['issued']}",
                f"Owner: {permit['owner'] or 'not stated'}",
                f"Plan-check valuation: {permit['valuation'] or 'not stated'}",
                f"Location: {permit['location']}",
                f"Power signal tags: {', '.join(permit['tags']) or 'none'}",
            ]
        ),
        "publication_date": None,
        "event_date": permit["issued"],
        "event_date_label": "Permit issued (City of Albuquerque building permits)",
        "html_url": CSV_URL,
        "extraction_location": "BuildingPermitsCABQ-en-us.csv row",
        "source_hash": hashlib.sha256(
            json.dumps(permit, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "permit": {
            "source_type": SOURCE_ID,
            "row_id": row_id,
            "applicant": permit["owner"],
            "facility": permit["description"][:180],
            "status": permit["status"],
            "description": permit["description"],
            "location": permit["location"],
            "city": "Albuquerque",
            "state": "NM",
            "power_signals": permit["tags"],
            "data_center": permit["data_center"],
            "document_links": {"Albuquerque building permits": CSV_URL},
            "source_fields": {
                "description": "Description",
                "issued": "IssueDate",
                "location": "SiteNumber, SiteStreet, SiteStreetType, SiteZip",
                "status": "Status",
            },
        },
    }


def retrieve(
    source: dict[str, Any],
    client: httpx.Client | None = None,
    today: date | None = None,
) -> list[dict[str, Any]]:
    if source.get("id") != SOURCE_ID or source.get("endpoint") != CSV_URL:
        raise SourceParseError("Albuquerque permit source ID or endpoint is not configured")
    query = source.get("query", {})
    if (
        query.get("window_days") != WINDOW_DAYS
        or query.get("max_response_bytes") != MAX_RESPONSE_BYTES
        or query.get("max_records") != MAX_RECORDS
    ):
        raise SourceParseError("Albuquerque permit query bounds are invalid")
    http = client or httpx.Client(timeout=60, follow_redirects=False, trust_env=False)
    try:
        _, body = read_public_response(
            http,
            CSV_URL,
            max_bytes=MAX_RESPONSE_BYTES,
            allowed_media_types={"text/csv"},
            allowed_hosts=frozenset({HOST}),
        )
        return [_record(permit) for permit in parse_permits(body, today=today or date.today())]
    finally:
        if client is None:
            http.close()
