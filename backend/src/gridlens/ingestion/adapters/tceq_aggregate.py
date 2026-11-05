"""TCEQ Aggregate Production Operations registrations (Socrata dataset ``9ixa-7k3m``).

Live check 2026-11-04: ``https://data.texas.gov/resource/9ixa-7k3m.json`` is keyless. The
dataset held 1,068 rows (``select count(*)``), updated 2026-11-04 14:03 GMT. One row is one
registration (``registration``, e.g. ``AP0000007``) with site, county, coordinates, material,
disturbed area, last application and status. The dataset spells one field
``last_applicaiton_status``; both spellings are read.

Bounded queries: a count first, then pages ordered by ``registration``; the pages must add up to
the count or the run fails (a changing dataset is retried, not half-ingested). New and changed
registrations are the diff: the record hash covers the stated fields, so an unchanged registration
creates nothing on replay.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

import httpx

from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.sector_common import (
    Pacer,
    candidate_record,
    clean,
    fetch,
    iso_date,
    new_client,
    number,
    require_source,
)

SOURCE_ID = "texas-tceq-aggregate-production"
HOST = "data.texas.gov"
ENDPOINT = "https://data.texas.gov/resource/9ixa-7k3m.json"
PAGE_SIZE = 500
_TEXT = (
    "registration",
    "registration_status",
    "customer_name",
    "regulated_entity_name",
    "site_name",
    "county",
    "city",
    "organization_name",
    "last_application_type",
    "material_type",
)
_DATES = (
    "registration_start_date",
    "last_application_submitted",
    "last_application_status_date",
    "current_expiration_date",
)


def valid_query(source: dict[str, Any]) -> bool:
    query = source.get("query")
    return (
        isinstance(query, dict)
        and source.get("id") == SOURCE_ID
        and source.get("endpoint") == ENDPOINT
        and source.get("cadence_hours") == 24
        and source.get("family") == "structured-government"
        and set(query) == {"max_response_bytes", "max_pages", "max_records"}
        and query["max_response_bytes"] == 2_000_000
        and type(query["max_pages"]) is int
        and 1 <= query["max_pages"] <= 10
        and type(query["max_records"]) is int
        and 1 <= query["max_records"] <= 5000
        and query["max_records"] <= query["max_pages"] * PAGE_SIZE
    )


def _page_url(offset: int) -> str:
    return (
        ENDPOINT
        + "?"
        + urlencode({"$order": "registration", "$limit": PAGE_SIZE, "$offset": offset})
    )


def parse_rows(body: bytes) -> list[dict[str, Any]]:
    try:
        rows = json.loads(body)
    except ValueError as exc:
        raise SourceParseError("TCEQ aggregate response is not JSON") from exc
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise SourceParseError("TCEQ aggregate response is not a row list")
    return rows


def normalize(row: dict[str, Any]) -> dict[str, Any]:
    reg = clean(row.get("registration"), 40)
    if not reg:
        raise SourceParseError("TCEQ aggregate row lacks a registration number")
    out: dict[str, Any] = {name: clean(row.get(name)) for name in _TEXT}
    out["last_application_status"] = clean(
        row.get("last_applicaiton_status") or row.get("last_application_status")
    )
    for name in _DATES:
        out[name] = iso_date(row.get(name))
    lat, lon = number(row.get("site_latitude")), number(row.get("site_longitude"))
    ok = lat is not None and lon is not None and 25 <= lat <= 37 and -107 <= lon <= -93
    out["latitude"], out["longitude"] = (lat, lon) if ok else (None, None)
    out["area_disturbed_acres"] = number(row.get("area_disturbed"))
    return out


def build_record(row: dict[str, Any]) -> dict[str, Any]:
    reg = row["registration"]
    name = row["site_name"] or row["regulated_entity_name"] or "unnamed site"
    lines = [
        f"TCEQ aggregate production operation registration {reg}: {name}",
        f"Registration status: {row['registration_status'] or 'not stated'}",
        f"Operator: {row['organization_name'] or row['customer_name'] or 'not stated'}",
        f"County: {row['county'] or 'not stated'}; city: {row['city'] or 'not stated'}",
        f"Material: {row['material_type'] or 'not stated'}; area disturbed (acres): "
        + (
            f"{row['area_disturbed_acres']:g}"
            if row["area_disturbed_acres"] is not None
            else "not stated"
        ),
        f"Registered since {row['registration_start_date'] or 'date not stated'}; "
        f"expires {row['current_expiration_date'] or 'date not stated'}",
        f"Last application: {row['last_application_type'] or 'not stated'}, "
        f"{row['last_application_status'] or 'status not stated'} on "
        f"{row['last_application_status_date'] or 'date not stated'}",
        "Registration only: no equipment, power source or electrical demand is stated.",
    ]
    county = row["county"]
    return candidate_record(
        source_id=SOURCE_ID,
        row_id=f"TCEQ-APO-{reg}",
        title=f"TCEQ aggregate registration {reg} — {name}",
        abstract_lines=lines,
        url=ENDPOINT,
        extraction_location=f"data.texas.gov 9ixa-7k3m registration {reg}",
        semantic={"row": row},
        event_date=row["last_application_status_date"] or row["registration_start_date"],
        event_date_label="TCEQ last application status date"
        if row["last_application_status_date"]
        else "TCEQ registration start date",
        permit={
            "applicant": row["organization_name"] or row["customer_name"],
            "facility": name,
            "status": row["registration_status"],
            "location": f"{county.title()} County, TX" if county else None,
            "state": "TX",
            "county": county,
            "permit_type": "Aggregate production operation registration",
            "permit_numbers": [reg],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "material_type": row["material_type"],
            "source_fields": {
                "facility": "site_name",
                "event_date": "last_application_status_date",
                "status": "registration_status",
            },
        },
    )


def retrieve(
    source: dict[str, Any],
    client: httpx.Client | None = None,
    *,
    pacer: Pacer | None = None,
    deadline: float | None = None,
) -> list[dict[str, Any]]:
    require_source(source, SOURCE_ID, ENDPOINT)
    if not valid_query(source):
        raise SourceParseError("TCEQ aggregate query bounds are invalid")
    query = source["query"]
    http = client or new_client()
    pace = pacer or Pacer(deadline=deadline)
    json_types = {"application/json"}
    try:
        _, body = fetch(
            http,
            ENDPOINT + "?" + urlencode({"$select": "count(*)"}),
            hosts={HOST},
            max_bytes=query["max_response_bytes"],
            media_types=json_types,
            pacer=pace,
        )
        counted = parse_rows(body)
        try:
            total = int(counted[0]["count"])
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            raise SourceParseError("TCEQ aggregate count is unreadable") from exc
        if total > query["max_records"]:
            raise SourceParseError("TCEQ aggregate row count exceeds its bound")
        rows: list[dict[str, Any]] = []
        for page in range(query["max_pages"]):
            if len(rows) >= total:
                break
            _, body = fetch(
                http,
                _page_url(page * PAGE_SIZE),
                hosts={HOST},
                max_bytes=query["max_response_bytes"],
                media_types=json_types,
                pacer=pace,
            )
            batch = parse_rows(body)
            if not batch:
                break
            rows.extend(batch)
        if len(rows) != total:
            raise SourceParseError("TCEQ aggregate pages do not match the counted total")
        normalized = [normalize(row) for row in rows]
        ids = [row["registration"] for row in normalized]
        if len(set(ids)) != len(ids):
            raise SourceParseError("TCEQ aggregate has a duplicate registration")
        return [build_record(row) for row in sorted(normalized, key=lambda r: r["registration"])]
    finally:
        if client is None:
            http.close()
