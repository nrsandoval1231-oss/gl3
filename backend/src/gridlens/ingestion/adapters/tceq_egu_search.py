"""TCEQ NSR search for pending electric-generating and engine registrations.

The public search at www2.tceq.texas.gov returns an HTML page whose body is
pipe-delimited. This adapter runs three fixed pending queries that were
verified on October 23, 2026: standard permits for electric generating
facilities (unit 8340), standard permits for natural gas electric generating
units (unit 15627), and permit-by-rule registrations for engines and turbines
(unit 7644). A generator row is evidence. It is not tagged behind-the-meter,
bridge, or temporary unless the row text says so.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

import httpx

from gridlens.domain.air_permit_hours import classify_operating_hours
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.power_signals import power_signal_tags
from gridlens.ingestion.adapters.public_source_http import read_public_response

SOURCE_ID = "texas-tceq-egu-registrations"
START_URL = "https://www2.tceq.texas.gov/airperm/index.cfm?fuseaction=airpermits.start"
SEARCH_URL = "https://www2.tceq.texas.gov/airperm/index.cfm"
ALLOWED_HOSTS = frozenset({"www2.tceq.texas.gov"})
MAX_RESPONSE_BYTES = 2_000_000
MAX_RECORDS = 400
_QUERIES = (
    ("STDPMT", "8340", "ELECTRIC GENERATING FACILITIES"),
    ("STDPMT", "15627", "NATURAL GAS ELECTRIC GENERATING UNITS"),
    ("PBR", "7644", "ENGINES AND TURBINES"),
)
_COLUMNS = (
    "program_area",
    "permit_number",
    "permit_type",
    "permit_status",
    "project_number",
    "customer_name",
    "legal_name",
    "cn_number",
    "project_type",
    "received",
    "complete",
    "renewal",
    "project_status",
    "project_name",
    "regulated_entity",
    "physical_location",
    "region",
    "county",
    "near_city",
    "rules",
)
_UPDATED = re.compile(r"Last Updated Date\s*:\s*(\d{2}/\d{2}/\d{4})")
_DATA_CENTER = re.compile(r"data\s*cent(?:er|re)|hyperscale", re.IGNORECASE)
_NONE = "there are no projects"


def _fields(chunk: str) -> list[str]:
    cleaned = chunk.replace("&nbsp;", " ")
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    parts = [" ".join(part.split()) for part in cleaned.split("|")]
    while parts and parts[0] == "":
        parts.pop(0)
    while parts and parts[-1] == "":
        parts.pop()
    return parts


def _date(value: str, label: str) -> str | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%m/%d/%Y").date().isoformat()
    except ValueError as exc:
        raise SourceParseError(f"TCEQ {label} is malformed") from exc


def _location(county: str, city: str) -> str | None:
    county_name = county.title() if county else ""
    city_name = city.title() if city else ""
    if city_name and county_name:
        return f"{city_name}, {county_name} County, TX"
    if county_name:
        return f"{county_name} County, TX"
    if city_name:
        return f"{city_name}, TX"
    return None


def parse_results(body: bytes, *, unit_id: str, unit_name: str) -> tuple[str, list[dict[str, Any]]]:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceParseError("TCEQ search result is not UTF-8") from exc
    updated_match = _UPDATED.search(text)
    if updated_match is None:
        raise SourceParseError("TCEQ search result has no last-updated date")
    updated = _date(updated_match.group(1), "last-updated date")
    assert updated is not None
    folded = text.casefold()
    empty = _NONE in folded
    rows: list[dict[str, Any]] = []
    for chunk in re.split(r"<br\s*/?>", text, flags=re.IGNORECASE):
        fields = _fields(chunk)
        if not fields or fields[0] != "NSR":
            continue
        if len(fields) != len(_COLUMNS):
            raise SourceParseError("TCEQ search row does not have the expected columns")
        item: dict[str, Any] = dict(zip(_COLUMNS, fields, strict=True))
        if not item["permit_number"].isdigit() or not item["project_number"].isdigit():
            raise SourceParseError("TCEQ search row has a non-numeric permit or project number")
        blob = " ".join(
            item[key]
            for key in (
                "customer_name",
                "legal_name",
                "project_name",
                "physical_location",
                "county",
                "near_city",
            )
        )
        item["unit_id"] = unit_id
        item["unit_name"] = unit_name
        item["event_date"] = _date(item["received"], "received date")
        item["location"] = _location(item["county"], item["near_city"])
        item["tags"] = power_signal_tags(blob)
        item["data_center"] = bool(_DATA_CENTER.search(blob))
        rows.append(item)
    if empty and rows:
        raise SourceParseError("TCEQ search result both says it is empty and contains rows")
    if empty:
        return updated, []
    if not rows:
        raise SourceParseError("TCEQ search result has no permit rows")
    return updated, rows


def _record(row: dict[str, Any], updated: str) -> dict[str, Any]:
    row_id = f"TCEQ-EGU-{row['permit_number']}"
    hours = classify_operating_hours(
        " ".join(
            str(row.get(key) or "")
            for key in (
                "project_name",
                "physical_location",
                "legal_name",
                "customer_name",
                "rules",
            )
        )
    )
    semantic = {key: row[key] for key in row if key != "tags"}
    semantic["report_updated"] = updated
    semantic["power_signals"] = row["tags"]
    semantic["operating_hours"] = hours
    return {
        "document_number": row_id,
        "title": f"{row['legal_name'] or row['customer_name']} — TCEQ {row['permit_number']}",
        "abstract": "\n".join(
            [
                f"Permit: {row['permit_number']}",
                f"Project: {row['project_number']}",
                f"Permit type: {row['permit_type']}",
                f"Search unit: {row['unit_id']} {row['unit_name']}",
                f"Customer: {row['customer_name']}",
                f"Legal name: {row['legal_name']}",
                f"Project name: {row['project_name'] or 'not stated'}",
                f"Received: {row['received'] or 'not stated'}",
                f"County: {row['county'] or 'not stated'}",
                f"Near city: {row['near_city'] or 'not stated'}",
                f"Physical location: {row['physical_location'] or 'not stated'}",
                f"Rules: {row['rules'] or 'not stated'}",
                f"Report updated: {updated}",
                f"Power signal tags: {', '.join(row['tags']) or 'none'}",
                f"Operating-hour rule {hours['rule_id']}: "
                f"{hours['classification'] or 'unclassified'}",
            ]
        ),
        "publication_date": None,
        "event_date": row["event_date"],
        "event_date_label": "TCEQ received date",
        "html_url": SEARCH_URL,
        "extraction_location": "TCEQ NSR air permits search, ASCII result",
        "source_hash": hashlib.sha256(
            json.dumps(semantic, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "permit": {
            "source_type": SOURCE_ID,
            "row_id": row_id,
            "applicant": row["legal_name"] or row["customer_name"],
            "facility": row["project_name"] or row["regulated_entity"],
            "permit_numbers": [row["permit_number"]],
            "permit_type": row["permit_type"],
            "status": row["project_status"] or row["permit_status"],
            "description": " ".join(
                part
                for part in (
                    row["project_name"],
                    row["physical_location"],
                    row["legal_name"],
                )
                if part
            ),
            "location": row["location"],
            "county": row["county"].title() if row["county"] else None,
            "state": "TX" if row["location"] else None,
            "data_center": row["data_center"],
            "power_signals": row["tags"],
            "operating_hours": hours,
            "document_links": {"TCEQ NSR search": SEARCH_URL},
            "source_fields": {
                "applicant": "Legal Name",
                "facility": "Project Name",
                "permit": "Permit Number",
                "location": "Near City Name and County Name",
                "event_date": "TCEQ Received Date",
            },
        },
    }


def _form(permit_type: str, unit_id: str) -> bytes:
    return urlencode(
        [
            ("RequestTimeout", "3000"),
            ("program", "NSR"),
            ("proj_status_txt", "PENDING"),
            ("addn_id_typ_txt", permit_type),
            ("unit_id", unit_id),
            ("out_form", "text"),
            ("order_by", "rcv_dt"),
            ("sort_dir", "desc"),
            ("date_option", "0"),
            ("_fuseaction=airpermits.validate_search_criteria.x", "1"),
            ("_fuseaction=airpermits.validate_search_criteria.y", "1"),
        ]
    ).encode()


def retrieve(source: dict[str, Any], client: httpx.Client | None = None) -> list[dict[str, Any]]:
    if source.get("id") != SOURCE_ID or source.get("endpoint") != START_URL:
        raise SourceParseError("TCEQ EGU source ID or endpoint is not configured")
    query = source.get("query", {})
    if (
        query.get("max_response_bytes") != MAX_RESPONSE_BYTES
        or query.get("max_records") != MAX_RECORDS
    ):
        raise SourceParseError("TCEQ EGU query bounds are invalid")
    http = client or httpx.Client(timeout=60, follow_redirects=False, trust_env=False)
    try:
        _, start = read_public_response(
            http,
            START_URL,
            max_bytes=MAX_RESPONSE_BYTES,
            allowed_media_types={"text/html"},
            allowed_hosts=ALLOWED_HOSTS,
        )
        if b"_fuseaction=airpermits.validate_search_criteria" not in start:
            raise SourceParseError("TCEQ search form is not the expected page")
        kept: dict[str, dict[str, Any]] = {}
        for permit_type, unit_id, unit_name in _QUERIES:
            _, body = read_public_response(
                http,
                SEARCH_URL,
                max_bytes=MAX_RESPONSE_BYTES,
                allowed_media_types={"text/html"},
                allowed_hosts=ALLOWED_HOSTS,
                method="POST",
                content=_form(permit_type, unit_id),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            updated, rows = parse_results(body, unit_id=unit_id, unit_name=unit_name)
            for row in rows:
                row["report_updated"] = updated
                prior = kept.get(row["permit_number"])
                if prior is None:
                    kept[row["permit_number"]] = row
                    continue
                left = {key: prior[key] for key in prior if key not in {"unit_id", "unit_name"}}
                right = {key: row[key] for key in row if key not in {"unit_id", "unit_name"}}
                if left != right:
                    raise SourceParseError(
                        "TCEQ permit number was returned with conflicting fields"
                    )
                if unit_id not in prior["unit_id"].split(","):
                    prior["unit_id"] = f"{prior['unit_id']},{unit_id}"
                    prior["unit_name"] = f"{prior['unit_name']}; {unit_name}"
        if len(kept) > MAX_RECORDS:
            raise SourceParseError("TCEQ EGU row count exceeds its bound")
        return [_record(row, row["report_updated"]) for row in kept.values()]
    finally:
        if client is None:
            http.close()
