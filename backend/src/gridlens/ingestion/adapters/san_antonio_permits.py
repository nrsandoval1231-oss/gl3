"""City of San Antonio permits and applications that name a data center (San Antonio, Texas).

Open Data SA publishes two Development Services tables through the CKAN datastore API:
permits issued and applications submitted. Each row is one permit type under a permit number,
with the project name, address, coordinates, submitted and issued dates, valuation and area.
A permit naming a data center is official, dated evidence of a specific site moving toward or
into construction. Admission is decided in the domain layer.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from gridlens.ingestion.adapters.bounded_http import read_bounded_response
from gridlens.ingestion.adapters.federal_register import SourceParseError

SOURCE_ID = "san-antonio-development-permits"
SEARCH_URL = "https://data.sanantonio.gov/api/3/action/datastore_search"
DATASET_URL = "https://data.sanantonio.gov/dataset/building-permits"
RESOURCES = {
    "issued": "c21106f9-3ef5-4f3a-8604-f992b4db7512",
    "applications": "fbb7202e-c6c1-475b-849e-c5c2cfb65833",
}
MAX_BYTES = 6_000_000
MAX_ROWS = 500
DATA_CENTER = re.compile(r"\bdata\s*cent(?:er|re)s?\b|\bhyperscale\b", re.IGNORECASE)


def search_url(resource: str) -> str:
    params = {"resource_id": RESOURCES[resource], "q": "data center", "limit": str(MAX_ROWS)}
    return f"{SEARCH_URL}?{urlencode(params)}"


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _day(value: Any) -> str | None:
    text = _text(value)[:10]
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def _number(value: Any) -> float | None:
    try:
        return float(_text(value)) if _text(value) else None
    except ValueError:
        return None


def parse_rows(body: bytes) -> list[dict[str, Any]]:
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise SourceParseError("San Antonio datastore did not return JSON") from exc
    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(payload, dict) or payload.get("success") is not True or not isinstance(
        result, dict
    ):
        raise SourceParseError("San Antonio datastore search failed")
    records, total = result.get("records"), result.get("total")
    if not isinstance(records, list) or not isinstance(total, int):
        raise SourceParseError("San Antonio datastore response lacks records or a total")
    if total > len(records):
        # More matches than one page holds would be silently dropped; fail instead.
        raise SourceParseError(
            f"San Antonio datastore matched {total} rows but returned {len(records)}"
        )
    for row in records:
        if not isinstance(row, dict) or not _text(row.get("PERMIT #")):
            raise SourceParseError("San Antonio permit row is malformed or lacks a number")
    return records


def group_permits(rows: list[dict[str, Any]], stage: str) -> list[dict[str, Any]]:
    """Rows repeat a permit number once per trade permit type; keep one permit."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(_text(row["PERMIT #"]), []).append(row)
    permits = []
    for number, members in grouped.items():
        lead = members[0]
        longitude = _number(lead.get("X_COORD"))
        latitude = _number(lead.get("Y_COORD"))
        # Some rows carry state-plane coordinates; keep only plausible longitude/latitude.
        geographic = (
            longitude is not None
            and latitude is not None
            and -107 <= longitude <= -93
            and 25 <= latitude <= 37
        )
        valuations = [v for v in (_number(row.get("DECLARED VALUATION")) for row in members) if v]
        areas = [a for a in (_number(row.get("AREA (SF)")) for row in members) if a]
        permits.append(
            {
                "permit_no": number,
                "stage": stage,
                "types": sorted({_text(row.get("PERMIT TYPE")) for row in members} - {""}),
                "project": _text(lead.get("PROJECT NAME")),
                "work_type": _text(lead.get("WORK TYPE")) or None,
                "address": _text(lead.get("ADDRESS")) or None,
                "submitted": _day(lead.get("DATE SUBMITTED")),
                "issued": _day(lead.get("DATE ISSUED")),
                "valuation": max(valuations) if valuations else None,
                "area_sf": max(areas) if areas else None,
                "contact": _text(lead.get("PRIMARY CONTACT")) or None,
                "latitude": latitude if geographic else None,
                "longitude": longitude if geographic else None,
            }
        )
    return permits


def record(permit: dict[str, Any]) -> dict[str, Any]:
    issued = permit["issued"]
    event = issued or permit["submitted"]
    label = (
        "Permit issued (San Antonio Development Services)"
        if issued
        else "Application submitted (San Antonio Development Services)"
    )
    address = permit["address"] or "San Antonio, TX"
    location = address.replace("City of San Antonio", "San Antonio")
    row_id = f"SAT-{permit['permit_no']}"
    status = "Issued" if issued else "Application submitted"
    return {
        "document_number": row_id,
        "title": f"{permit['project']} — San Antonio {status.lower()} {permit['permit_no']}",
        "abstract": "\n".join(
            [
                f"Permit: {permit['permit_no']} ({'; '.join(permit['types'])})",
                f"Project: {permit['project']}",
                f"Work type: {permit['work_type'] or 'not stated'}",
                f"Submitted: {permit['submitted'] or 'unknown'} · Issued: {issued or 'not issued'}",
                f"Declared valuation: {permit['valuation'] or 'not stated'}",
                f"Area (SF): {permit['area_sf'] or 'not stated'}",
                f"Primary contact: {permit['contact'] or 'not stated'}",
                f"Address: {permit['address'] or 'not stated'}",
            ]
        ),
        # The tables have no publication date.
        "publication_date": None,
        "event_date": event,
        "event_date_label": label,
        "html_url": DATASET_URL,
        "extraction_location": f"Open Data SA {permit['stage']} table, rows for this permit",
        "source_hash": hashlib.sha256(
            json.dumps(permit, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "permit": {
            "source_type": SOURCE_ID,
            "row_id": row_id,
            "applicant": None,
            "facility": permit["project"],
            "permit_type": "; ".join(permit["types"]),
            "subtype": permit["work_type"],
            "status": status,
            "description": permit["project"],
            "job_value": permit["valuation"],
            "location": location,
            "city": "San Antonio",
            "county": "Bexar",
            "latitude": permit["latitude"],
            "longitude": permit["longitude"],
            "document_links": {"San Antonio building permits dataset": DATASET_URL},
            "source_fields": {
                "facility": "PROJECT NAME",
                "submitted": "DATE SUBMITTED",
                "issued": "DATE ISSUED",
                "location": "ADDRESS",
            },
        },
    }


def retrieve(
    source: dict[str, Any], client: httpx.Client | None = None, today: date | None = None
) -> list[dict[str, Any]]:
    if source.get("id") != SOURCE_ID or source.get("endpoint") != SEARCH_URL:
        raise SourceParseError("San Antonio permit source ID or endpoint is not configured")
    window = int(source.get("query", {}).get("window_days", 0))
    if not 1 <= window <= 90:
        raise SourceParseError("San Antonio permit window is invalid")
    start = ((today or date.today()) - timedelta(days=window)).isoformat()
    http = client or httpx.Client(timeout=25, follow_redirects=False)
    try:
        permits: dict[str, dict[str, Any]] = {}
        # Applications first so an issued permit with the same number replaces its application.
        for stage in ("applications", "issued"):
            _, body = read_bounded_response(http, search_url(stage), MAX_BYTES)
            for permit in group_permits(parse_rows(body), stage):
                permits[permit["permit_no"]] = permit
        return [
            record(permit)
            for permit in permits.values()
            if DATA_CENTER.search(permit["project"])
            and max(permit["issued"] or "", permit["submitted"] or "") >= start
        ]
    finally:
        if client is None:
            http.close()
