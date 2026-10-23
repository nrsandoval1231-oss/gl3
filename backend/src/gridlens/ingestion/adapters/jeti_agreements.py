"""Governor's JETI public listing, checked against the Comptroller agreements table.

The listing PDF states company, school district, location, industry, and dates.
The Comptroller HTML table's application numbers must match the contracted
section. A missing announced date stays blank. The listing as-of date is not
used as a project's event date.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
from datetime import datetime
from typing import Any

import httpx
from pypdf import PdfReader

from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.power_signals import power_signal_tags
from gridlens.ingestion.adapters.public_source_http import read_public_response

SOURCE_ID = "texas-jeti-agreements"
AGREEMENTS_URL = (
    "https://comptroller.texas.gov/economy/development/prop-tax/jeti/current-agreements.php"
)
LISTING_PDF = "https://gov.texas.gov/uploads/files/business/JETI_Public_Listing.pdf"
MAX_RESPONSE_BYTES = 2_000_000
MAX_PDF_PAGES = 8
MAX_RECORDS = 80
_AS_OF = re.compile(r"AS OF ([A-Za-z]+ \d{1,2}, \d{4})", re.IGNORECASE)
_ROW = re.compile(
    r"(J\d{4})\s+(.*?)\s+(\d+%)\s+(\d+)\s+([\d,]+)\s+(\$[\d,]+)\s+(\$[\d,]+)"
    r"((?:\s+\d{1,2}/\d{1,2}/\d{4}){0,2})(?=\s*(?:J\d{4}\b|\d+\s+\d+))"
)
_DISTRICT = re.compile(
    r"^(?P<company>.+?)\s+(?P<district>.+?\s(?:Consolidated ISD|CISD|ISD))\s+(?P<rest>.+)$"
)
_DATA_CENTER = re.compile(r"data\s*cent(?:er|re)|hyperscale", re.IGNORECASE)


def _day(value: str) -> str:
    return datetime.strptime(value, "%m/%d/%Y").date().isoformat()


def _listing_day(text: str) -> str:
    found = _AS_OF.search(text)
    if not found:
        raise SourceParseError("JETI listing has no as-of date")
    try:
        return datetime.strptime(found.group(1).title(), "%B %d, %Y").date().isoformat()
    except ValueError as exc:
        raise SourceParseError("JETI listing as-of date is malformed") from exc


def _place(rest: str) -> tuple[str, str]:
    county = re.match(r"^(?P<location>.+?\sCounty)\s+(?P<industry>\S.*)$", rest)
    if county:
        return county.group("location"), county.group("industry")
    multi = re.match(
        r"^(?P<location>(?:Fort|San|El|Port|La|Grand|College|Corpus)\s+[A-Z][A-Za-z.-]+)"
        r"\s+(?P<industry>\S.*)$",
        rest,
    )
    if multi:
        return multi.group("location"), multi.group("industry")
    city = re.match(r"^(?P<location>[A-Z][A-Za-z.-]+)\s+(?P<industry>\S.*)$", rest)
    if not city:
        raise SourceParseError("JETI agreement location is not stated")
    return city.group("location"), city.group("industry")


def _rows(section: str, *, status: str, listing_day: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for contract, body, percent, required, jobs, capital, incentives, dates in _ROW.findall(
        section
    ):
        identity = _DISTRICT.match(body.strip())
        if not identity:
            raise SourceParseError(f"JETI agreement {contract} lacks a school district")
        location, industry = _place(identity.group("rest").strip())
        parsed = [_day(item) for item in re.findall(r"\d{1,2}/\d{1,2}/\d{4}", dates)]
        announced = None
        expiration = None
        if len(parsed) == 2:
            announced, expiration = parsed
            if announced > listing_day:
                raise SourceParseError("JETI announced date is after the listing date")
        elif len(parsed) == 1:
            if parsed[0] <= listing_day:
                announced = parsed[0]
            else:
                expiration = parsed[0]
        elif parsed:
            raise SourceParseError("JETI agreement has an unexpected date count")
        rows.append(
            {
                "id": contract,
                "company": identity.group("company").strip(),
                "school_district": identity.group("district").strip(),
                "location": f"{location}, TX",
                "industry": industry.strip(),
                "limitation": percent,
                "required_jobs": int(required),
                "total_jobs": int(jobs.replace(",", "")),
                "capital_investment": capital,
                "incentives": incentives,
                "event_date": announced,
                "expiration": expiration,
                "status": status,
                "listing_date": listing_day,
            }
        )
    found_ids = [row["id"] for row in rows]
    if len(found_ids) != len(set(found_ids)):
        raise SourceParseError("JETI listing repeats a contract id")
    return rows


def parse_listing_text(text: str) -> list[dict[str, Any]]:
    collapsed = " ".join(text.split())
    if "OFFICE OF THE GOVERNOR" not in collapsed or "JOBS, ENERGY, TECHNOLOGY" not in collapsed:
        raise SourceParseError("JETI PDF is not the governor's public listing")
    listing_day = _listing_day(collapsed)
    contracted, marker, rest = collapsed.partition("Total JETI Projects Contracted")
    if not marker:
        raise SourceParseError("JETI listing has no contracted-projects total")
    negotiating, _, _ = rest.partition("Total JETI Projects Approved")
    rows = _rows(contracted, status="contracted", listing_day=listing_day) + _rows(
        negotiating, status="approved and negotiating", listing_day=listing_day
    )
    if not rows:
        raise SourceParseError("JETI listing has no agreements")
    return rows


def parse_listing_pdf(body: bytes) -> list[dict[str, Any]]:
    try:
        reader = PdfReader(io.BytesIO(body))
    except Exception as exc:
        raise SourceParseError("JETI listing PDF could not be read") from exc
    if reader.is_encrypted or not 1 <= len(reader.pages) <= MAX_PDF_PAGES:
        raise SourceParseError("JETI listing PDF is encrypted or outside its page bound")
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return parse_listing_text(text)


def agreement_ids(body: bytes) -> set[str]:
    text = body.decode("utf-8", errors="replace")
    ids = set(re.findall(r">\s*(J\d{4})\s*<", text))
    if not ids:
        raise SourceParseError("JETI agreements page has no application numbers")
    return ids


def _record(row: dict[str, Any]) -> dict[str, Any]:
    text = f"{row['company']} {row['industry']} {row['school_district']}"
    tags = power_signal_tags(text)
    row_id = f"JETI-AGREEMENT-{row['id']}"
    semantic = {**row, "power_signals": tags}
    return {
        "document_number": row_id,
        "title": f"{row['company']} — JETI {row['id']}",
        "abstract": "\n".join(
            [
                f"Contract: {row['id']} ({row['status']})",
                f"Company: {row['company']}",
                f"School district: {row['school_district']}",
                f"Location column: {row['location']}",
                f"Industry: {row['industry']}",
                f"Announced: {row['event_date'] or 'not stated'}",
                f"Expiration or recommendation date: {row['expiration'] or 'not stated'}",
                f"Listing date: {row['listing_date']}",
                f"Capital investment stated by the listing: {row['capital_investment']}",
                f"Power signal tags: {', '.join(tags) or 'none'}",
            ]
        ),
        "publication_date": row["listing_date"],
        "event_date": row["event_date"],
        "event_date_label": "Date announced on the governor's JETI listing",
        "html_url": LISTING_PDF,
        "extraction_location": "Governor of Texas JETI public listing PDF",
        "source_hash": hashlib.sha256(
            json.dumps(semantic, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "permit": {
            "source_type": SOURCE_ID,
            "row_id": row_id,
            "applicant": row["company"],
            "facility": row["industry"],
            "permit_numbers": [row["id"]],
            "permit_type": "JETI agreement",
            "status": row["status"],
            "description": f"{row['company']} {row['industry']}",
            "location": row["location"],
            "state": "TX",
            "data_center": bool(_DATA_CENTER.search(text)),
            "power_signals": tags,
            "document_links": {
                "Governor JETI listing": LISTING_PDF,
                "Comptroller current agreements": AGREEMENTS_URL,
            },
            "source_fields": {
                "applicant": "Company",
                "facility": "Industry",
                "location": "Location column on the governor's listing",
                "event_date": "Date Announced, when the listing states one",
            },
        },
    }


def retrieve(source: dict[str, Any], client: httpx.Client | None = None) -> list[dict[str, Any]]:
    if source.get("id") != SOURCE_ID or source.get("endpoint") != AGREEMENTS_URL:
        raise SourceParseError("JETI agreement source ID or endpoint is not configured")
    query = source.get("query", {})
    if (
        query.get("max_response_bytes") != MAX_RESPONSE_BYTES
        or query.get("max_records") != MAX_RECORDS
    ):
        raise SourceParseError("JETI agreement query bounds are invalid")
    if query.get("listing_pdf") != LISTING_PDF:
        raise SourceParseError("JETI agreement listing PDF is not the governor's file")
    http = client or httpx.Client(timeout=60, follow_redirects=False, trust_env=False)
    try:
        _, page = read_public_response(
            http,
            AGREEMENTS_URL,
            max_bytes=MAX_RESPONSE_BYTES,
            allowed_media_types={"text/html"},
        )
        _, pdf = read_public_response(
            http,
            LISTING_PDF,
            max_bytes=MAX_RESPONSE_BYTES,
            allowed_media_types={"application/pdf"},
        )
        rows = parse_listing_pdf(pdf)
        contracted = {row["id"] for row in rows if row["status"] == "contracted"}
        if agreement_ids(page) != contracted:
            raise SourceParseError(
                "JETI Comptroller agreement numbers do not match the governor listing"
            )
        if len(rows) > MAX_RECORDS:
            raise SourceParseError("JETI agreement count exceeds its bound")
        return [_record(row) for row in rows]
    finally:
        if client is None:
            http.close()
