"""Bounded recent-window retrieval from Boston's official CKAN permit table."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx

from gridlens.ingestion.adapters.bounded_http import ResponseTooLarge, read_bounded_response
from gridlens.ingestion.adapters.federal_register import SourceParseError

SOURCE_ID = "boston-building-permits"
HOST = "data.boston.gov"
RESOURCE_ID = "6ddcd912-32a0-43df-9908-63574f8c7e77"
FIELDS = (
    "_id,permitnumber,worktype,permittypedescr,description,comments,applicant,"
    "issued_date,expiration_date,status,occupancytype,address,city,state,"
    "declared_valuation,sq_feet,property_id,parcel_id"
)
PAGE_SIZE = 1000
MAX_PAGES = 20
MAX_RECORDS = PAGE_SIZE * MAX_PAGES
MAX_RESPONSE_BYTES = 2_000_000
MAX_RUN_BYTES = 20_000_000
_AMENDS = re.compile(
    r"\b(?:amend(?:ment)?(?:\s+to)?|amends?)\s+(?:permit\s+)?([A-Z]{1,4}\d{4,})\b", re.I
)


def _response(
    client: httpx.Client, endpoint: str, sql: str, state: dict[str, int]
) -> dict[str, Any]:
    try:
        headers, body = read_bounded_response(client, endpoint, MAX_RESPONSE_BYTES, {"sql": sql})
    except (httpx.HTTPError, ResponseTooLarge) as exc:
        raise SourceParseError(f"Boston permit query failed: {type(exc).__name__}") from exc
    state["bytes"] += len(body)
    if state["bytes"] > MAX_RUN_BYTES or "json" not in headers.get("content-type", "").lower():
        raise SourceParseError("Boston permit query exceeded bounds or returned non-JSON")
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise SourceParseError("Boston permit source returned malformed JSON") from exc
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise SourceParseError("Boston permit query was unsuccessful")
    result = payload.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("records"), list):
        raise SourceParseError("Boston permit response schema changed")
    return result


def retrieve(source: dict[str, Any], client: httpx.Client | None = None) -> list[dict[str, Any]]:
    if source.get("id") != SOURCE_ID:
        raise SourceParseError("Boston permit source ID is not configured")
    parsed = urlparse(str(source.get("endpoint") or ""))
    if (
        parsed.scheme != "https"
        or parsed.hostname != HOST
        or parsed.path != "/api/3/action/datastore_search_sql"
        or parsed.query
    ):
        raise SourceParseError("Boston endpoint is outside the configured official CKAN SQL API")
    query = source.get("query", {})
    days = int(query.get("window_days", 90))
    if not 1 <= days <= 90 or query.get("page_size") != PAGE_SIZE:
        raise SourceParseError("Boston permit window or page size is outside its bound")
    if query.get("max_pages") != MAX_PAGES or query.get("max_records") != MAX_RECORDS:
        raise SourceParseError("Boston permit result bound is not the reviewed configuration")

    today = datetime.now(UTC).date()
    start = today - timedelta(days=days - 1)
    where = (
        f"issued_date >= '{start.isoformat()}T00:00:00' "
        f"AND issued_date <= '{today.isoformat()}T23:59:59.999'"
    )
    relation = f'"{RESOURCE_ID}"'
    http = client or httpx.Client(
        timeout=20, follow_redirects=False, headers={"Accept": "application/json"}
    )
    state = {"bytes": 0}
    try:
        count_result = _response(
            http,
            source["endpoint"],
            f"SELECT COUNT(*) AS row_count FROM {relation} WHERE {where}",
            state,
        )
        count_rows = count_result["records"]
        if len(count_rows) != 1:
            raise SourceParseError("Boston completeness count is missing")
        expected = int(count_rows[0].get("row_count", -1))
        if expected < 1 or expected > min(MAX_RECORDS, int(query["max_records"])):
            raise SourceParseError("Boston recent permit count is empty or exceeds its bound")

        output: list[dict[str, Any]] = []
        seen: set[str] = set()
        seen_permit_numbers: set[str] = set()
        previous: tuple[datetime, int] | None = None
        for offset in range(0, expected, PAGE_SIZE):
            sql = (
                f"SELECT {FIELDS} FROM {relation} WHERE {where} "
                f"ORDER BY issued_date ASC, _id ASC LIMIT {PAGE_SIZE} OFFSET {offset}"
            )
            rows = _response(http, source["endpoint"], sql, state)["records"]
            if not rows or len(rows) > PAGE_SIZE:
                raise SourceParseError("Boston permit pages ended early or exceeded page size")
            for row in rows:
                if not isinstance(row, dict) or not all(
                    key in row
                    for key in (
                        "_id",
                        "permitnumber",
                        "issued_date",
                        "status",
                        "address",
                        "city",
                        "state",
                    )
                ):
                    raise SourceParseError("Boston permit row lacks stable identity or site fields")
                row_id = str(row["_id"])
                permit_number = " ".join(str(row.get("permitnumber") or "").split())
                try:
                    issued = datetime.fromisoformat(str(row["issued_date"]).replace("Z", "+00:00"))
                    ordered_issued = (
                        issued.replace(tzinfo=UTC)
                        if issued.tzinfo is None
                        else issued.astimezone(UTC)
                    )
                    sort_key = (ordered_issued, int(row_id))
                except (ValueError, TypeError) as exc:
                    raise SourceParseError(
                        "Boston permit row has malformed ID or issue date"
                    ) from exc
                if issued.date() < start or issued.date() > today:
                    raise SourceParseError("Boston permit row escaped its recent-date window")
                if (
                    not permit_number
                    or row_id in seen
                    or permit_number in seen_permit_numbers
                    or (previous and sort_key < previous)
                ):
                    raise SourceParseError(
                        "Boston permit rows have duplicate identity or bad ordering"
                    )
                seen.add(row_id)
                seen_permit_numbers.add(permit_number)
                previous = sort_key
                output.append(render_record(row))
            if len(output) > expected:
                raise SourceParseError("Boston permit pages exceeded the declared result count")
        if len(output) != expected:
            raise SourceParseError("Boston permit pages did not match the exact result count")
        confirm = _response(
            http,
            source["endpoint"],
            f"SELECT COUNT(*) AS row_count FROM {relation} WHERE {where}",
            state,
        )["records"]
        if len(confirm) != 1 or int(confirm[0].get("row_count", -1)) != expected:
            raise SourceParseError("Boston permit row count changed during pagination")
        return output
    finally:
        if client is None:
            http.close()


def render_record(row: dict[str, Any]) -> dict[str, Any]:
    """Canonical Boston row rendering shared by ingestion and exact research."""
    required = ("_id", "permitnumber", "issued_date", "status", "address", "city", "state")
    if any(key not in row for key in required):
        raise SourceParseError("Boston permit row lacks stable identity or site fields")
    row_id = str(row["_id"])
    permit_number = " ".join(str(row.get("permitnumber") or "").split())
    try:
        if isinstance(row["_id"], bool):
            raise ValueError("Boolean row identity")
        int(row_id)
        issued = datetime.fromisoformat(str(row["issued_date"]).replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise SourceParseError("Boston permit row has malformed ID or issue date") from exc
    if not permit_number or issued.date() > datetime.now(UTC).date():
        raise SourceParseError("Boston permit identity is empty or issue date is future")
    clean = {
        key: " ".join(str(row.get(key) or "").split())
        for key in (
            "worktype",
            "permittypedescr",
            "description",
            "comments",
            "applicant",
            "status",
            "occupancytype",
            "address",
            "city",
            "state",
            "declared_valuation",
            "sq_feet",
            "property_id",
            "parcel_id",
            "expiration_date",
        )
    }
    amend_match = _AMENDS.search(clean["comments"])
    amendment_of = amend_match.group(1) if amend_match else None
    semantic = {
        "permit_number": permit_number,
        "issued_date": issued.isoformat(),
        **clean,
        "amendment_of": amendment_of,
    }
    digest = hashlib.sha256(
        json.dumps(semantic, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    abstract = "\n".join(
        f"{label}: {value}"
        for label, value in (
            ("Permit number", permit_number),
            ("Work type", clean["worktype"]),
            ("Permit type", clean["permittypedescr"]),
            ("Description", clean["description"]),
            ("Comments", clean["comments"]),
            ("Applicant (buying role unknown)", clean["applicant"]),
            ("Status", clean["status"]),
            ("Occupancy", clean["occupancytype"]),
            ("Address", clean["address"]),
            ("City", clean["city"]),
            ("State", clean["state"]),
        )
        if value
    )
    if amendment_of:
        abstract += f"\nExplicitly referenced amended permit: {amendment_of}"
    citation_url = "https://data.boston.gov/api/3/action/datastore_search?" + urlencode(
        {
            "resource_id": RESOURCE_ID,
            "filters": json.dumps({"permitnumber": permit_number}, separators=(",", ":")),
            "limit": 1,
        }
    )
    return {
        "document_number": permit_number,
        "title": clean["description"] or clean["permittypedescr"] or permit_number,
        "abstract": abstract,
        "publication_date": None,
        "html_url": citation_url,
        "extraction_location": f"Official Boston CKAN permitnumber={permit_number}",
        "event_date": issued.date().isoformat(),
        "event_date_label": "Boston permit issued date",
        "source_hash": digest,
        "permit": {
            "source_type": "boston-building-permits",
            "city": clean["city"],
            "state": clean["state"],
            "address": clean["address"],
            "class": clean["occupancytype"],
            "work": clean["worktype"],
            "type": clean["permittypedescr"],
            "status": clean["status"] or "Unknown",
            "description": " ".join(filter(None, [clean["description"], clean["comments"]])),
            "applicant": clean["applicant"],
            "applicant_role": "applicant",
            "buyer_role": "UNKNOWN",
            "declared_valuation": clean["declared_valuation"],
            "area": clean["sq_feet"],
            "expiration_date": clean["expiration_date"],
            "row_id": permit_number,
            "permit_number": permit_number,
            "raw_source_row_id": row_id,
            "amendment_of": amendment_of,
            "source_fields": {
                key: key
                for key in (
                    "permitnumber",
                    "worktype",
                    "permittypedescr",
                    "description",
                    "comments",
                    "applicant",
                    "issued_date",
                    "expiration_date",
                    "status",
                    "occupancytype",
                    "address",
                    "city",
                    "state",
                    "declared_valuation",
                    "sq_feet",
                    "property_id",
                    "parcel_id",
                    "_id",
                )
            },
        },
    }
