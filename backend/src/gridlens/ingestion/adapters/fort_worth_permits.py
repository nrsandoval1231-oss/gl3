"""City of Fort Worth development permits that name a data center (Fort Worth, Texas).

The city's open-data "CFW Development Permits Table" is an ArcGIS feature table updated
hourly. It holds every permit filed through the Development Services permit center, one row
per permit and parcel, with the work description, project name, owner, file date, current
status and declared job value. A filed permit naming a data center (or its substation) is
official, dated evidence of a specific site moving toward construction. Admission is decided
in the domain layer.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from gridlens.ingestion.adapters.bounded_http import read_bounded_response
from gridlens.ingestion.adapters.federal_register import SourceParseError

SOURCE_ID = "fort-worth-development-permits"
QUERY_URL = (
    "https://services5.arcgis.com/3ddLCBXe1bRt7mzj/arcgis/rest/services/"
    "CFW_Open_Data_Development_Permits_View/FeatureServer/0/query"
)
DATASET_URL = "https://data.fortworthtexas.gov/datasets/cfw-development-permits-table/about"
MAX_BYTES = 8_000_000
MAX_ROWS = 1000
DATA_CENTER = re.compile(r"\bdata\s*cent(?:er|re)s?\b|\bhyperscale\b", re.IGNORECASE)
_TEAM_PREFIX = re.compile(r"^\s*(?:X\s+TEAMS?\s*)?(?:/{3}\s*)+", re.IGNORECASE)
_PLACEHOLDER_STREET = re.compile(r"FOR REVIEW ONLY", re.IGNORECASE)
_COORDS = re.compile(r"\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)")


def _clean(value: Any) -> str:
    text = " ".join(str(value or "").split())
    return _TEAM_PREFIX.sub("", text).strip()


def _day(epoch_ms: Any) -> str | None:
    if not isinstance(epoch_ms, int | float):
        return None
    return datetime.fromtimestamp(epoch_ms / 1000, tz=UTC).date().isoformat()


def _where(start: date) -> str:
    text_fields = ("B1_WORK_DESC", "B1_SPECIAL_TEXT")
    names = " OR ".join(f"UPPER({field}) LIKE '%DATA CENTER%'" for field in text_fields)
    return f"File_Date >= DATE '{start.isoformat()}' AND ({names})"


def query_url(start: date) -> str:
    params = {
        "where": _where(start),
        "outFields": "*",
        "orderByFields": "File_Date DESC",
        "resultRecordCount": str(MAX_ROWS),
        "f": "json",
    }
    return f"{QUERY_URL}?{urlencode(params)}"


def parse_rows(body: bytes) -> list[dict[str, Any]]:
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise SourceParseError("Fort Worth permit query did not return JSON") from exc
    if not isinstance(payload, dict) or "error" in payload:
        raise SourceParseError("Fort Worth permit query returned an error")
    if payload.get("exceededTransferLimit"):
        # A truncated page would hide permits; fail rather than collect part of the window.
        raise SourceParseError("Fort Worth permit query exceeded its row limit")
    features = payload.get("features")
    if not isinstance(features, list):
        raise SourceParseError("Fort Worth permit query lacks a features list")
    rows = [f.get("attributes") for f in features if isinstance(f, dict)]
    if any(not isinstance(row, dict) or not row.get("Permit_No") for row in rows):
        raise SourceParseError("Fort Worth permit row lacks a permit number")
    return rows  # type: ignore[return-value]


def _address(row: dict[str, Any]) -> str | None:
    street = " ".join(
        part
        for part in (
            str(row.get("Addr_No") or ""),
            _clean(row.get("Direction")),
            _clean(row.get("Street_Name")),
            _clean(row.get("Street_Suffix")),
            _clean(row.get("Street_Suffix_Dir")),
        )
        if part
    )
    if not row.get("Street_Name") or _PLACEHOLDER_STREET.search(street):
        return None
    zip_code = row.get("Zip_Code")
    return f"{street}, Fort Worth, TX{f' {zip_code}' if zip_code else ''}"


def group_permits(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The table repeats a permit once per parcel; keep one permit with all its parcels."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["Permit_No"]).strip(), []).append(row)
    permits = []
    for number, members in grouped.items():
        lead = max(members, key=lambda row: row.get("Status_Date") or 0)
        addresses = sorted({a for a in (_address(row) for row in members) if a})
        owners = sorted({_clean(row.get("Owner_Full_Name")) for row in members} - {""})
        matches = (_COORDS.search(str(row.get("Location_1") or "")) for row in members)
        coords = next((match for match in matches if match), None)
        permits.append(
            {
                "permit_no": number,
                "permit_type": _clean(lead.get("Permit_Type")),
                "subtype": _clean(lead.get("Permit_SubType")),
                "project": _clean(lead.get("B1_SPECIAL_TEXT")),
                "work": _clean(lead.get("B1_WORK_DESC")),
                "status": _clean(lead.get("Current_Status")),
                "status_date": _day(lead.get("Status_Date")),
                "filed": _day(min(row.get("File_Date") or 0 for row in members) or None),
                "job_value": _clean(lead.get("JobValue")) or None,
                "square_feet": next(
                    (_clean(row.get("SqFt")) for row in members if row.get("SqFt")), None
                ),
                "addresses": addresses,
                "owners": owners,
                "legal": sorted({_clean(row.get("B1_LEGAL_DESC")) for row in members} - {""}),
                "latitude": float(coords.group(1)) if coords else None,
                "longitude": float(coords.group(2)) if coords else None,
            }
        )
    return sorted(permits, key=lambda permit: (permit["filed"] or "", permit["permit_no"]))


def record(permit: dict[str, Any]) -> dict[str, Any]:
    location = permit["addresses"][0] if permit["addresses"] else "Fort Worth, TX"
    title = permit["project"] or permit["work"][:120]
    row_id = f"FTW-{permit['permit_no']}"
    return {
        "document_number": row_id,
        "title": f"{title} — Fort Worth {permit['permit_type'].lower()} {permit['permit_no']}",
        "abstract": "\n".join(
            [
                f"Permit: {permit['permit_no']} · {permit['permit_type']} · {permit['subtype']}",
                f"Project: {permit['project'] or 'not stated'}",
                f"Work description: {permit['work']}",
                f"Status: {permit['status']} (as of {permit['status_date'] or 'unknown'})",
                f"Filed: {permit['filed'] or 'unknown'}",
                f"Declared job value: {permit['job_value'] or 'not stated'}",
                f"Owner of record: {', '.join(permit['owners']) or 'not stated'}",
                f"Addresses: {'; '.join(permit['addresses']) or 'not stated'}",
            ]
        ),
        "publication_date": permit["status_date"],
        "event_date": permit["filed"],
        "event_date_label": "Permit application filed (Fort Worth Development Services)",
        "html_url": DATASET_URL,
        "extraction_location": "CFW Development Permits Table, rows for this permit number",
        "source_hash": hashlib.sha256(
            json.dumps(permit, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "permit": {
            "source_type": SOURCE_ID,
            "row_id": row_id,
            "applicant": permit["owners"][0] if permit["owners"] else None,
            "facility": title,
            "permit_type": permit["permit_type"],
            "subtype": permit["subtype"],
            "status": permit["status"],
            "description": f"{permit['project']} {permit['work']}".strip(),
            "job_value": permit["job_value"],
            "location": location,
            "city": "Fort Worth",
            "county": None,
            "latitude": permit["latitude"],
            "longitude": permit["longitude"],
            "document_links": {"Fort Worth permits dataset": DATASET_URL},
            "source_fields": {
                "facility": "B1_SPECIAL_TEXT (project name)",
                "description": "B1_WORK_DESC",
                "filed": "File_Date",
                "status": "Current_Status",
                "location": "Addr_No, Street_Name, Street_Suffix, Zip_Code",
            },
        },
    }


def retrieve(
    source: dict[str, Any], client: httpx.Client | None = None, today: date | None = None
) -> list[dict[str, Any]]:
    if source.get("id") != SOURCE_ID or source.get("endpoint") != QUERY_URL:
        raise SourceParseError("Fort Worth permit source ID or endpoint is not configured")
    window = int(source.get("query", {}).get("window_days", 0))
    if not 1 <= window <= 120:
        raise SourceParseError("Fort Worth permit window is invalid")
    start = (today or date.today()) - timedelta(days=window)
    http = client or httpx.Client(timeout=25, follow_redirects=False)
    try:
        _, body = read_bounded_response(http, query_url(start), MAX_BYTES)
        permits = group_permits(parse_rows(body))
        return [record(permit) for permit in permits if DATA_CENTER.search(
            f"{permit['project']} {permit['work']}"
        )]
    finally:
        if client is None:
            http.close()
