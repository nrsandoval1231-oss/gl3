"""TxDOT NEVI program results (public ArcGIS feature layer behind TxDOT's results page).

Live check 2026-11-04: TxDOT's "NEVI Program Results" page
(``https://www.dot.state.tx.us/apps/nevi/results.html``, linked from txdot.gov's Texas EV planning
page) renders its table from ``https://services.arcgis.com/KTcxiTD9dsQw4r7Z/arcgis/rest/services/
Texas_NEVI_Program/FeatureServer/0``: keyless JSON, 474 rows, ``maxRecordCount`` 1000, last edited
2026-10-20. Each row is one award or application site: NEVI ID, applicant, ports, per-port kW
(min and max), study area, status, grants, coordinates, dates stored as strings.

Oklahoma (ODOT / EVOK): no site-level award list was found. The ODOT and EVOK pages are narrative
(round one: 13 sites to Love's, Francis Energy and Tesla, stated in 2024 news text) and there is
no feature layer or file to read, so nothing is ingested for Oklahoma.

Identity: ``NEVI_ID`` is blank on 168 of the 474 live rows and repeats on others, and ``CSJ`` repeats
on placeholder rows (``0000-00-000``), so a site is keyed by CSJ plus its coordinate (five decimals),
which was unique across all 474 rows. ``OBJECTID`` is layer-local and only orders the paging. Rows
whose applicant reads "No Applications Received" are kept as sites with no applicant.

Nameplate: ``ports x max_per_port_kw`` is *calculated* from two stated numbers and labelled so. It
is the charger rating the award describes, not site demand, and it is unknown when either number
is missing.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any
from urllib.parse import urlencode

import httpx

from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.sector_common import (
    Pacer,
    candidate_record,
    clean,
    fetch,
    new_client,
    number,
    require_source,
)

SOURCE_ID = "texas-txdot-nevi-awards"
HOST = "services.arcgis.com"
ENDPOINT = (
    "https://services.arcgis.com/KTcxiTD9dsQw4r7Z/arcgis/rest/services/"
    "Texas_NEVI_Program/FeatureServer/0/query"
)
PAGE_SIZE = 500
_FIELDS = (
    "NEVI_ID,APPLICANT_NAME,PORTS,PUBLISHED,SCORE,CSJ,STUDY_AREA,MPO,STATUS,"
    "CONSTRUCTION_START_DATE,OPEN_DATE,MIN_PER_PORT_KW,MAX_PER_PORT_KW,PULL_THROUGH,"
    "CONSTRUCTION_GRANT,O_M_GRANT,CORRIDOR_TYPE,LATITUDE,LONGITUDE,FPAA_DATE"
)
_MDY = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


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
        and 1 <= query["max_pages"] <= 6
        and type(query["max_records"]) is int
        and 1 <= query["max_records"] <= 2000
        and query["max_records"] <= query["max_pages"] * PAGE_SIZE
    )


def _date(value: Any) -> str | None:
    """TxDOT writes M/D/YYYY, or ``--`` when unset; anything else is unknown."""
    match = _MDY.fullmatch(str(value or "").strip())
    if not match:
        return None
    try:
        return date(int(match[3]), int(match[1]), int(match[2])).isoformat()
    except ValueError:
        return None


def _query(extra: dict[str, Any]) -> str:
    return ENDPOINT + "?" + urlencode({"where": "1=1", "f": "json", **extra})


def parse_features(body: bytes) -> list[dict[str, Any]]:
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise SourceParseError("NEVI response is not JSON") from exc
    if not isinstance(payload, dict) or "error" in payload:
        raise SourceParseError("NEVI layer returned an error payload")
    features = payload.get("features")
    if not isinstance(features, list):
        raise SourceParseError("NEVI response lacks features")
    return [
        item["attributes"]
        for item in features
        if isinstance(item, dict) and isinstance(item.get("attributes"), dict)
    ]


def normalize(row: dict[str, Any]) -> dict[str, Any]:
    nevi_id = row.get("NEVI_ID")
    nevi_id = nevi_id if type(nevi_id) is int else None  # blank on 168 of 474 live rows
    csj = clean(row.get("CSJ"), 40)
    ports, max_kw = number(row.get("PORTS")), number(row.get("MAX_PER_PORT_KW"))
    lat, lon = number(row.get("LATITUDE")), number(row.get("LONGITUDE"))
    ok = lat is not None and lon is not None and 25 <= lat <= 37 and -107 <= lon <= -93
    if not csj or not ok or lat is None or lon is None:
        raise SourceParseError("NEVI row lacks a CSJ or a Texas coordinate for its identity")
    applicant = clean(row.get("APPLICANT_NAME"), 160)
    no_award = bool(applicant and applicant.casefold() == "no applications received")
    ports_i = int(ports) if ports is not None and ports > 0 else None
    return {
        "site_key": f"{csj}@{lat:.5f},{lon:.5f}",
        "nevi_id": nevi_id,
        "csj": csj,
        "applicant": None if no_award else applicant,
        "no_applications_received": no_award,
        "ports": ports_i,
        "min_per_port_kw": number(row.get("MIN_PER_PORT_KW")),
        "max_per_port_kw": max_kw if max_kw and max_kw > 0 else None,
        "study_area": clean(row.get("STUDY_AREA"), 80),
        "mpo": clean(row.get("MPO"), 80),
        "status": clean(row.get("STATUS"), 60),
        "corridor_type": clean(row.get("CORRIDOR_TYPE"), 40),
        "construction_grant_usd": number(row.get("CONSTRUCTION_GRANT")),
        "om_grant_usd": number(row.get("O_M_GRANT")),
        "published": _date(row.get("PUBLISHED")),
        "construction_start": _date(row.get("CONSTRUCTION_START_DATE")),
        "open_date": _date(row.get("OPEN_DATE")),
        "fpaa_date": _date(row.get("FPAA_DATE")),
        "latitude": lat,
        "longitude": lon,
    }


def calculated_nameplate_kw(row: dict[str, Any]) -> float | None:
    """Ports times the stated maximum per-port rating; unknown unless both are stated."""
    if row["ports"] is None or row["max_per_port_kw"] is None:
        return None
    return float(row["ports"] * row["max_per_port_kw"])


def build_record(row: dict[str, Any]) -> dict[str, Any]:
    nid = row["site_key"]
    nameplate = calculated_nameplate_kw(row)
    lines = [
        f"TxDOT NEVI site {nid} (NEVI ID {row['nevi_id'] or 'not stated'}): "
        + (
            "no applications received"
            if row["no_applications_received"]
            else row["applicant"] or "applicant not stated"
        ),
        f"Study area: {row['study_area'] or 'not stated'}; corridor type: "
        f"{row['corridor_type'] or 'not stated'}",
        f"Status: {row['status'] or 'not stated'}; published {row['published'] or 'not stated'}",
        f"Stated ports: {row['ports'] if row['ports'] is not None else 'not stated'}; "
        f"stated maximum per-port rating (kW): "
        f"{row['max_per_port_kw'] if row['max_per_port_kw'] is not None else 'not stated'}",
        "Calculated charger nameplate (ports x maximum per-port kW; a rating, not site demand): "
        + (f"{nameplate:g} kW" if nameplate is not None else "unknown"),
        f"Construction start: {row['construction_start'] or 'not stated'}; "
        f"open date: {row['open_date'] or 'not stated'}",
        f"Construction grant (USD): {row['construction_grant_usd'] or 'not stated'}",
    ]
    place = f"{row['study_area']}, TX" if row["study_area"] else None
    return candidate_record(
        source_id=SOURCE_ID,
        row_id=f"TXDOT-NEVI-{nid}",
        title=f"TxDOT NEVI site {nid} — {row['study_area'] or 'study area not stated'}",
        abstract_lines=lines,
        url="https://www.dot.state.tx.us/apps/nevi/results.html",
        extraction_location=f"Texas_NEVI_Program FeatureServer layer 0 site {nid}",
        semantic={"row": row},
        publication_date=row["published"],
        event_date=row["open_date"] or row["construction_start"] or row["published"],
        event_date_label="TxDOT NEVI open, construction start or publication date",
        permit={
            "applicant": row["applicant"],
            "facility": f"NEVI {row['csj']}",
            "status": row["status"],
            "location": place,
            "state": "TX",
            "permit_type": "TxDOT NEVI award",
            "nevi_ports": row["ports"],
            "nevi_max_per_port_kw": row["max_per_port_kw"],
            "calculated_nameplate_kw": nameplate,
            "nameplate_basis": "calculated: stated ports x stated maximum per-port kW"
            if nameplate is not None
            else "unknown",
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "source_fields": {
                "facility": "CSJ",
                "event_date": "OPEN_DATE / CONSTRUCTION_START_DATE / PUBLISHED",
                "publication_date": "PUBLISHED",
            },
        },
    )


def retrieve(
    source: dict[str, Any], client: httpx.Client | None = None, *, pacer: Pacer | None = None
) -> list[dict[str, Any]]:
    require_source(source, SOURCE_ID, ENDPOINT)
    if not valid_query(source):
        raise SourceParseError("NEVI query bounds are invalid")
    query = source["query"]
    http = client or new_client()
    pace = pacer or Pacer()
    kwargs = {
        "hosts": {HOST},
        "max_bytes": query["max_response_bytes"],
        "media_types": {"application/json", "text/plain"},
        "pacer": pace,
    }
    try:
        _, body = fetch(http, _query({"returnCountOnly": "true"}), **kwargs)
        try:
            total = json.loads(body)["count"]
        except (ValueError, KeyError, TypeError) as exc:
            raise SourceParseError("NEVI count is unreadable") from exc
        if type(total) is not int or total < 0 or total > query["max_records"]:
            raise SourceParseError("NEVI row count is invalid or exceeds its bound")
        rows: list[dict[str, Any]] = []
        for page in range(query["max_pages"]):
            if len(rows) >= total:
                break
            _, body = fetch(
                http,
                _query(
                    {
                        "outFields": _FIELDS,
                        "returnGeometry": "false",
                        "orderByFields": "OBJECTID",
                        "resultOffset": page * PAGE_SIZE,
                        "resultRecordCount": PAGE_SIZE,
                    }
                ),
                **kwargs,
            )
            batch = parse_features(body)
            if not batch:
                break
            rows.extend(batch)
        if len(rows) != total:
            raise SourceParseError("NEVI pages do not match the counted total")
        normalized = [normalize(row) for row in rows]
        keys = [row["site_key"] for row in normalized]
        if len(set(keys)) != len(keys):
            raise SourceParseError("NEVI layer has a duplicate site identity")
        return [build_record(row) for row in sorted(normalized, key=lambda r: r["site_key"])]
    finally:
        if client is None:
            http.close()
