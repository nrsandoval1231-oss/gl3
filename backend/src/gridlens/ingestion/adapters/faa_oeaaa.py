"""FAA OE/AAA obstruction cases near known campuses (candidate observations only).

Live check 2026-11-04: ``GET https://oeaaa.faa.gov/oeaaa/services/caseList/date/OE?start=D&end=D+1``
answers keyless XML. The date filter is the determination (``dateCompleted``) day with an
exclusive end. One day was about 2,000 cases (2.4 MB); an 8-day window stopped at 8,001 cases,
which is the documented 8,000-row cap. The PDF guide at the old path now answers 404, so the
endpoint shape comes from the live response, not from a guide.

Paging is therefore by determination day: one request per day, a day that reaches the cap fails
loudly instead of being treated as complete. The spatial join is exact arithmetic: a case becomes
a candidate when its stated coordinate lies within ``radius_m`` metres (haversine, sphere radius
6,371,008.8 m) of an owner-listed campus. A candidate is a proximity observation. It does not say
the sponsor is the campus operator, that the structure serves the campus, or anything about demand.
"""

from __future__ import annotations

import math
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any
from xml.etree import ElementTree as ET

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

SOURCE_ID = "faa-oeaaa-obstruction"
HOST = "oeaaa.faa.gov"
ENDPOINT = "https://oeaaa.faa.gov/oeaaa/services/caseList/date/OE"
ROW_CAP = 8000
EARTH_RADIUS_M = 6_371_008.8
MAX_CAMPUSES = 200
_ASN = re.compile(r"^\d{4}-[A-Z]{3}-\d{1,7}-[A-Z]{2,4}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_FIELDS = (
    "asn",
    "dateEntered",
    "dateCompleted",
    "expirationDate",
    "caseType",
    "statusCode",
    "sponsor",
    "structureType",
    "structureDescription",
    "aglStructureHeight",
    "nearestCity",
    "nearestState",
    "latitude",
    "longitude",
    "latLongAccuracy",
)


def valid_campuses(value: Any) -> bool:
    if not isinstance(value, list) or len(value) > MAX_CAMPUSES:
        return False
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"id", "name", "latitude", "longitude"}:
            return False
        if not isinstance(item["id"], str) or not _ID.fullmatch(item["id"]) or item["id"] in seen:
            return False
        seen.add(item["id"])
        if not isinstance(item["name"], str) or not item["name"].strip() or len(item["name"]) > 120:
            return False
        lat, lon = item["latitude"], item["longitude"]
        if (
            type(lat) not in {int, float}
            or type(lon) not in {int, float}
            or not -90 <= lat <= 90
            or not -180 <= lon <= 180
        ):
            return False
    return True


def valid_query(source: dict[str, Any]) -> bool:
    query = source.get("query")
    return (
        isinstance(query, dict)
        and source.get("id") == SOURCE_ID
        and source.get("endpoint") == ENDPOINT
        and source.get("cadence_hours") == 24
        and source.get("family") == "structured-government"
        and set(query) == {"window_days", "max_response_bytes", "radius_m", "campuses"}
        and type(query["window_days"]) is int
        and 1 <= query["window_days"] <= 7
        and type(query["max_response_bytes"]) is int
        and 1_000_000 <= query["max_response_bytes"] <= 12_000_000
        and type(query["radius_m"]) is int
        and 50 <= query["radius_m"] <= 10_000
        and valid_campuses(query["campuses"])
    )


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def parse_cases(body: bytes) -> list[dict[str, str]]:
    """Cases from one caseList response. DTDs and entities are refused before parsing."""
    head = body[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in body[:65536].lower():
        raise SourceParseError("FAA caseList contains a DTD or entity declaration")
    try:
        root = ET.fromstring(body)  # DTD and entities refused above
    except ET.ParseError as exc:
        raise SourceParseError("FAA caseList is not well-formed XML") from exc
    if root.tag != "caseList":
        raise SourceParseError("FAA response is not a caseList")
    cases: list[dict[str, str]] = []
    for node in root:
        if node.tag != "OECase":
            continue
        fields = {name: (node.findtext(name) or "").strip() for name in _FIELDS}
        if _ASN.fullmatch(fields["asn"]):
            cases.append(fields)
    return cases


def match_campuses(
    case: dict[str, str], campuses: list[dict[str, Any]], radius_m: int
) -> list[dict[str, Any]]:
    """Campuses within the stated radius of the case, nearest first, ties by campus id."""
    lat, lon = number(case.get("latitude")), number(case.get("longitude"))
    if lat is None or lon is None or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        return []
    found = []
    for campus in campuses:
        distance = haversine_m(lat, lon, campus["latitude"], campus["longitude"])
        if distance <= radius_m:
            found.append({"campus_id": campus["id"], "name": campus["name"], "m": round(distance)})
    return sorted(found, key=lambda item: (item["m"], item["campus_id"]))


def build_record(case: dict[str, str], matches: list[dict[str, Any]]) -> dict[str, Any]:
    asn = case["asn"]
    height = number(case.get("aglStructureHeight"))
    structure = clean(case.get("structureType"), 60) or "not stated"
    sponsor = clean(case.get("sponsor"), 120)
    city, state = clean(case.get("nearestCity"), 60), clean(case.get("nearestState"), 2)
    entered, completed = iso_date(case.get("dateEntered")), iso_date(case.get("dateCompleted"))
    nearest = matches[0]
    semantic = {
        "asn": asn,
        "fields": {name: clean(case.get(name)) for name in _FIELDS},
        "campuses": matches,
    }
    lines = [
        f"FAA obstruction evaluation case {asn}",
        f"Structure type: {structure}",
        f"Structure height AGL (feet): {height:g}" if height is not None else "Height: not stated",
        f"Sponsor as filed: {sponsor or 'not stated'}",
        f"Case entered: {entered or 'not stated'}; determination date: {completed or 'not stated'}",
        f"FAA status code: {clean(case.get('statusCode'), 40) or 'not stated'}",
        f"Stated coordinate: {case['latitude']}, {case['longitude']} "
        f"(accuracy {clean(case.get('latLongAccuracy'), 8) or 'not stated'})",
        "Within the stated radius of known campus: "
        + "; ".join(f"{m['campus_id']} at {m['m']} m" for m in matches),
        "Candidate observation: proximity only. The filing does not say the sponsor operates "
        "the campus or that the structure serves it, and it states no electrical demand.",
    ]
    return candidate_record(
        source_id=SOURCE_ID,
        row_id=f"FAA-{asn}",
        title=f"FAA case {asn} — {structure} {nearest['m']} m from campus {nearest['campus_id']}",
        abstract_lines=lines,
        url=ENDPOINT,
        extraction_location=f"FAA OE/AAA caseList OECase {asn}",
        semantic=semantic,
        publication_date=completed,
        event_date=entered,
        event_date_label="FAA obstruction case entered",
        permit={
            "applicant": sponsor,
            "facility": asn,
            "status": clean(case.get("statusCode"), 40),
            "location": ", ".join(part for part in (city, state) if part) or None,
            "state": state,
            "permit_type": "FAA obstruction evaluation",
            "candidate_campuses": matches,
            "structure_type": structure,
            "structure_height_agl_ft": height,
            "source_fields": {
                "facility": "asn",
                "event_date": "dateEntered",
                "publication_date": "dateCompleted",
                "campus match": "haversine distance between stated coordinate and owner campus",
            },
        },
    )


def retrieve(
    source: dict[str, Any],
    client: httpx.Client | None = None,
    *,
    today: date | None = None,
    pacer: Pacer | None = None,
) -> list[dict[str, Any]]:
    require_source(source, SOURCE_ID, ENDPOINT)
    if not valid_query(source):
        raise SourceParseError("FAA query bounds are invalid")
    query = source["query"]
    campuses = query["campuses"]
    if not campuses:
        return []  # nothing to join against: no request, no claim
    end_day = today or datetime.now(UTC).date()
    http = client or new_client()
    pace = pacer or Pacer()
    records: dict[str, dict[str, Any]] = {}
    try:
        for offset in range(query["window_days"]):
            day = end_day - timedelta(days=offset)
            url = f"{ENDPOINT}?start={day.isoformat()}&end={(day + timedelta(days=1)).isoformat()}"
            _, body = fetch(
                http,
                url,
                hosts={HOST},
                max_bytes=query["max_response_bytes"],
                media_types={"application/xml", "text/xml"},
                pacer=pace,
            )
            cases = parse_cases(body)
            if len(cases) >= ROW_CAP:
                raise SourceParseError("FAA day reached the 8,000-row cap and may be incomplete")
            for case in cases:
                matches = match_campuses(case, campuses, query["radius_m"])
                if matches:
                    records[case["asn"]] = build_record(case, matches)
        return [records[key] for key in sorted(records)]
    finally:
        if client is None:
            http.close()
