"""AFDC electric-vehicle charging stations (planned and open) from the NLR developer network.

Host fix: the API moved from ``developer.nrel.gov`` to ``developer.nlr.gov``. Live check
2026-11-04: ``developer.nrel.gov`` no longer resolves; ``https://developer.nlr.gov/api/
alt-fuel-stations/v1.json`` answers **403 ``API_KEY_MISSING``** without a key (the docs page on the
new host is public and lists ``GET /api/alt-fuel-stations/v1`` with no keyless variant; the AFDC
bulk download page is a form, not a stable file URL). So this reader needs a key, which is read
from the ``AFDC_API_KEY`` setting (secret store) and sent in the ``X-Api-Key`` header, never in a
URL and never in the repository. Without the key it fails closed before any request.

The response shape below follows the published station fields; it could not be checked live
without a key, so the reader refuses any reply that lacks ``total_results`` and ``fuel_stations``.
Port counts are counts, not kilowatts: a missing count stays unknown, never zero.
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

SOURCE_ID = "afdc-ev-stations"
HOST = "developer.nlr.gov"
ENDPOINT = "https://developer.nlr.gov/api/alt-fuel-stations/v1.json"
PAGE_SIZE = 200
STATUS_LABELS = {"E": "open", "P": "planned", "T": "temporarily unavailable"}
STATES = frozenset({"TX", "OK", "NM"})


def valid_query(source: dict[str, Any]) -> bool:
    query = source.get("query")
    return (
        isinstance(query, dict)
        and source.get("id") == SOURCE_ID
        and source.get("endpoint") == ENDPOINT
        and source.get("cadence_hours") == 24
        and source.get("family") == "structured-government"
        and set(query) == {"max_response_bytes", "max_pages", "max_records", "states", "statuses"}
        and query["max_response_bytes"] == 2_000_000
        and type(query["max_pages"]) is int
        and 1 <= query["max_pages"] <= 40
        and type(query["max_records"]) is int
        and 1 <= query["max_records"] <= 8000
        and isinstance(query["states"], list)
        and 1 <= len(query["states"]) <= 3
        and all(item in STATES for item in query["states"])
        and isinstance(query["statuses"], list)
        and 1 <= len(query["statuses"]) <= 3
        and all(item in STATUS_LABELS for item in query["statuses"])
    )


def parse_page(body: bytes) -> tuple[int, list[dict[str, Any]]]:
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise SourceParseError("AFDC response is not JSON") from exc
    total = payload.get("total_results") if isinstance(payload, dict) else None
    stations = payload.get("fuel_stations") if isinstance(payload, dict) else None
    if type(total) is not int or not isinstance(stations, list):
        raise SourceParseError("AFDC response lacks total_results or fuel_stations")
    return total, [row for row in stations if isinstance(row, dict)]


def _count(value: Any) -> int | None:
    parsed = number(value)
    return int(parsed) if parsed is not None and parsed >= 0 and parsed == int(parsed) else None


def normalize(row: dict[str, Any]) -> dict[str, Any]:
    station_id = row.get("id")
    if type(station_id) is not int:
        raise SourceParseError("AFDC station lacks an integer ID")
    status = clean(row.get("status_code"), 1)
    lat, lon = number(row.get("latitude")), number(row.get("longitude"))
    ok = lat is not None and lon is not None and 18 <= lat <= 72 and -180 <= lon <= -60
    connectors = row.get("ev_connector_types")
    return {
        "id": station_id,
        "name": clean(row.get("station_name"), 160),
        "status_code": status,
        "status": STATUS_LABELS.get(status or ""),
        "city": clean(row.get("city"), 80),
        "state": clean(row.get("state"), 2),
        "zip": clean(row.get("zip"), 10),
        "network": clean(row.get("ev_network"), 80),
        "access": clean(row.get("access_code"), 20),
        "dc_fast_ports": _count(row.get("ev_dc_fast_num")),
        "level2_ports": _count(row.get("ev_level2_evse_num")),
        "connector_types": sorted(
            {clean(item, 20) or "" for item in connectors if isinstance(item, str)} - {""}
        )
        if isinstance(connectors, list)
        else None,
        "open_date": iso_date(row.get("open_date")),
        "date_last_confirmed": iso_date(row.get("date_last_confirmed")),
        "updated_at": iso_date(row.get("updated_at")),
        "latitude": lat if ok else None,
        "longitude": lon if ok else None,
    }


def build_record(row: dict[str, Any]) -> dict[str, Any]:
    sid = row["id"]

    def ports(value: int | None) -> str:
        return str(value) if value is not None else "not stated"

    lines = [
        f"AFDC station {sid}: {row['name'] or 'unnamed'}",
        f"Status: {row['status'] or 'not stated'} (code {row['status_code'] or 'none'})",
        f"Location: {row['city'] or 'city not stated'}, {row['state'] or 'state not stated'}",
        f"DC fast ports: {ports(row['dc_fast_ports'])}; Level 2 ports: {ports(row['level2_ports'])}"
        " (counts of ports, not kilowatts)",
        f"Network: {row['network'] or 'not stated'}; access: {row['access'] or 'not stated'}",
        f"Open date: {row['open_date'] or 'not stated'}; last confirmed: "
        f"{row['date_last_confirmed'] or 'not stated'}",
        "Station register only: no site demand or utility service is stated.",
    ]
    place = ", ".join(part for part in (row["city"], row["state"]) if part)
    return candidate_record(
        source_id=SOURCE_ID,
        row_id=f"AFDC-{sid}",
        title=f"AFDC EV station {sid} — {row['name'] or 'unnamed'} ({row['status'] or 'status unknown'})",
        abstract_lines=lines,
        url=ENDPOINT,
        extraction_location=f"AFDC alt-fuel-stations v1 station id {sid}",
        semantic={"row": row},
        publication_date=row["updated_at"],
        event_date=row["open_date"],
        event_date_label="AFDC station open date",
        permit={
            "applicant": row["network"],
            "facility": row["name"],
            "status": row["status"],
            "location": place or None,
            "state": row["state"],
            "permit_type": "EV charging station register",
            "dc_fast_ports": row["dc_fast_ports"],
            "level2_ports": row["level2_ports"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "source_fields": {
                "facility": "station_name",
                "event_date": "open_date",
                "publication_date": "updated_at",
            },
        },
    )


def retrieve(
    source: dict[str, Any],
    client: httpx.Client | None = None,
    *,
    api_key: str | None = None,
    pacer: Pacer | None = None,
) -> list[dict[str, Any]]:
    require_source(source, SOURCE_ID, ENDPOINT)
    if not valid_query(source):
        raise SourceParseError("AFDC query bounds are invalid")
    if api_key is None:
        from gridlens.settings import get_settings

        secret = get_settings().afdc_api_key
        api_key = secret.get_secret_value() if secret else None
    if not api_key or len(api_key) > 200 or any(ch.isspace() for ch in api_key):
        raise SourceParseError("AFDC_API_KEY is not configured")
    query = source["query"]
    http = client or new_client()
    pace = pacer or Pacer()
    rows: dict[int, dict[str, Any]] = {}
    try:
        total = None
        for page in range(query["max_pages"]):
            url = ENDPOINT + "?" + urlencode(
                {
                    "fuel_type": "ELEC",
                    "state": ",".join(query["states"]),
                    "status": ",".join(query["statuses"]),
                    "limit": PAGE_SIZE,
                    "offset": page * PAGE_SIZE,
                }
            )
            _, body = fetch(
                http,
                url,
                hosts={HOST},
                max_bytes=query["max_response_bytes"],
                media_types={"application/json"},
                pacer=pace,
                headers={"X-Api-Key": api_key},
            )
            total, batch = parse_page(body)
            if total > query["max_records"]:
                raise SourceParseError("AFDC result count exceeds its bound")
            for station in batch:
                normalized = normalize(station)
                rows[normalized["id"]] = normalized
            if not batch or (page + 1) * PAGE_SIZE >= total:
                break
        if total is None or len(rows) != total:
            raise SourceParseError("AFDC pages do not match total_results")
        return [build_record(rows[key]) for key in sorted(rows)]
    finally:
        if client is None:
            http.close()
