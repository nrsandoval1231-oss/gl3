"""TCEQ pending New Source Review air permit applications (statewide Texas).

The official listing names applicant, facility, permit numbers, received date and a
stable TCEQ project link. For filings whose facility or applicant names data-center or
power-generation activity, the bounded Plain Language Summary PDF supplies the
site (city, county, coordinates) and the stated purpose. Every listed row is retained
as evidence; admission is decided in the domain layer.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
from datetime import date, datetime
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup, Tag
from pypdf import PdfReader

from gridlens.ingestion.adapters.bounded_http import read_bounded_response
from gridlens.ingestion.adapters.federal_register import SourceParseError

SOURCE_ID = "texas-tceq-nsr-pending"
LISTING_URL = (
    "https://www.tceq.texas.gov/assets/public/permitting/air/reports/applications/"
    "nsr-pending-permits.html"
)
SUMMARY_URL = (
    "https://www.tceq.texas.gov/downloads/permitting/air/bilingual/pending-permit-notices/"
    "{permit}-pls-english.pdf"
)
HOST = "www.tceq.texas.gov"
MAX_LISTING_BYTES = 3_000_000
MAX_PDF_BYTES = 2_000_000
MAX_PDF_PAGES = 4
MIN_ROWS = 20
MAX_ROWS = 2000

# Names that make a filing worth the bounded summary fetch. Admission is stricter.
RELEVANT_NAME = re.compile(
    r"\bDATA\s*CENTERS?\b|\bDIGITAL\b|\bCOMPUTE\b|\bHYPERSCALE\b|\bELECTRIC GENERATING\b|"
    r"\bPOWER (?:PLANT|STATION|GENERATION|CENTER)\b|\bGENERATING (?:UNIT|STATION|FACILITY)\b|"
    r"\bEGU\b|\bPEAKER\b",
    re.IGNORECASE,
)
_SITE = re.compile(
    r"\((RN\d{9})\)\s+(?:will|is)\b.{0,160}?\bat\b[,\s]+(?P<site>.{3,300}?),\s*"
    r"(?P<city>[A-Za-z .'\-]{2,60}),\s*(?:Texas,\s*)?(?P<county>[A-Za-z .'\-]{2,60}?)\s+County\b",
    re.DOTALL,
)
# Alternate wording: "(RN...) site is located in Carson County ... northeast of Amarillo, Texas".
_SITE_COUNTY = re.compile(
    r"\((RN\d{9})\)\s+site is located in\s+(?P<county>[A-Z][A-Za-z .'\-]{1,40}?)\s+County\b"
    r"(?P<site>[^.]{0,200}?(?:of|near|in)\s+(?P<city>[A-Z][A-Za-z .'\-]{1,40}),\s*Texas)?"
)
_COORD = re.compile(r"(-?\d{1,3}\.\d{3,}),\s*(-?\d{1,3}\.\d{3,})")


def _text(cell: Any) -> str:
    return " ".join(cell.get_text(" ", strip=True).split())


def _received(value: str, today: date) -> date:
    try:
        received = datetime.strptime(value, "%m/%d/%Y").date()
    except ValueError as exc:
        raise SourceParseError("TCEQ received date is malformed") from exc
    if received > today:
        raise SourceParseError("TCEQ received date is in the future")
    return received


def _official(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname != HOST:
        raise SourceParseError("TCEQ link is outside the official host")
    return url


def parse_listing(body: bytes, today: date) -> list[dict[str, Any]]:
    soup = BeautifulSoup(body, "html.parser")
    heading = soup.find(["h1", "h2"], string=re.compile("Pending Applications: New Source Review"))
    if heading is None:
        raise SourceParseError("TCEQ listing heading changed or page is not the NSR listing")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tr in soup.find_all("tr"):
        if not isinstance(tr, Tag):
            continue
        cells = [cell for cell in tr.find_all("td", recursive=False) if isinstance(cell, Tag)]
        if len(cells) != 5:
            continue
        applicant_cell, facility_cell, permit_cell, date_cell, link_cell = cells
        notice = applicant_cell.find("a", href=True)
        application = link_cell.find("a", href=True)
        if not isinstance(notice, Tag) or not isinstance(application, Tag):
            continue
        for anchor in applicant_cell.find_all("a"):
            anchor.extract()
        applicant = _text(applicant_cell)
        facility = _text(facility_cell)
        permits = [p.strip() for p in _text(permit_cell).replace(" ", "").split(",") if p.strip()]
        project = urlsplit(str(notice["href"])).fragment
        if not applicant or not facility or not permits or not project.isdigit():
            raise SourceParseError("TCEQ listing row lacks applicant, facility, permit or project")
        if project in seen:
            continue
        seen.add(project)
        rows.append(
            {
                "project": project,
                "applicant": applicant,
                "facility": facility,
                "permits": permits,
                "received": _received(_text(date_cell), today),
                "notice_url": _official(str(notice["href"])),
                "application_url": _official(str(application["href"])),
                "application_stage": _text(application),
            }
        )
    if not MIN_ROWS <= len(rows) <= MAX_ROWS:
        raise SourceParseError("TCEQ listing row count is outside its expected bounds")
    return rows


def parse_summary(body: bytes, permit: str) -> dict[str, Any]:
    if not body.startswith(b"%PDF-"):
        raise SourceParseError("TCEQ summary is not a PDF")
    reader = PdfReader(io.BytesIO(body))
    if len(reader.pages) > MAX_PDF_PAGES:
        raise SourceParseError("TCEQ summary exceeds its page bound")
    text = " ".join(" ".join((page.extract_text() or "").split()) for page in reader.pages)
    return summary_from_text(text, permit)


def summary_from_text(text: str, permit: str) -> dict[str, Any]:
    text = " ".join(text.split())
    if permit not in text:
        raise SourceParseError("TCEQ summary does not name the listed permit")
    site = _SITE.search(text)
    result: dict[str, Any] = {"text": text[:3000], "site": None, "city": None, "county": None}
    county_only = None if site else _SITE_COUNTY.search(text)
    if county_only:
        result.update(
            regulated_entity=county_only.group(1),
            site=" ".join((county_only.group("site") or "").split()) or None,
            city=county_only.group("city"),
            county=" ".join(county_only.group("county").split()),
        )
    if site:
        result.update(
            regulated_entity=site.group(1),
            site=" ".join(site.group("site").split()),
            city=" ".join(site.group("city").split()),
            county=" ".join(site.group("county").split()),
        )
        coords = _COORD.search(site.group("site"))
        if coords:
            result["latitude"], result["longitude"] = float(coords.group(1)), float(coords.group(2))
    purpose = re.search(
        r"((?:This|The)\b[^.]{0,80}?\b(?:permit|registration|application)\b[^.]{0,40}?"
        r"\bwill authorize[^.]{5,400}\.|[^.]{0,200}\bwill provide electricity to[^.]{3,200}\.)",
        text,
    )
    result["purpose"] = " ".join(purpose.group(1).split()) if purpose else None
    result["renewal"] = bool(
        re.search(r"\brenewal\b", text, re.IGNORECASE)
        and re.search(r"no changes|continued operation", text, re.IGNORECASE)
    )
    return result


def _record(row: dict[str, Any], summary: dict[str, Any] | None) -> dict[str, Any]:
    permit = row["permits"][0]
    location = (
        f"{summary['city']}, {summary['county']} County, TX"
        if summary and summary.get("city")
        else f"{summary['county']} County, TX"
        if summary and summary.get("county")
        else None
    )
    abstract = "\n".join(
        part
        for part in (
            f"Applicant: {row['applicant']}",
            f"Facility: {row['facility']}",
            f"Permit numbers: {', '.join(row['permits'])}",
            f"Application received: {row['received'].isoformat()}",
            f"Application stage: {row['application_stage']}",
            f"Location: {location}" if location else "",
            f"Stated purpose: {summary['purpose']}" if summary and summary.get("purpose") else "",
            f"Summary excerpt: {summary['text'][:900]}" if summary else "",
        )
        if part
    )
    semantic = {
        "project": row["project"],
        "applicant": row["applicant"],
        "facility": row["facility"],
        "permits": row["permits"],
        "received": row["received"].isoformat(),
        "stage": row["application_stage"],
        "summary": {k: v for k, v in (summary or {}).items() if k != "text"},
    }
    return {
        "document_number": f"TCEQ-{row['project']}",
        "title": f"{row['facility']} — TCEQ air permit application {permit}",
        "abstract": abstract,
        "publication_date": None,
        "event_date": row["received"].isoformat(),
        "event_date_label": "Application received (TCEQ listing)",
        "html_url": row["notice_url"],
        "extraction_location": "TCEQ NSR pending-application listing row"
        + ("; Plain Language Summary page 1" if summary else ""),
        "source_hash": hashlib.sha256(
            json.dumps(semantic, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "permit": {
            "source_type": SOURCE_ID,
            "row_id": f"TCEQ-{row['project']}",
            "project": row["project"],
            "applicant": row["applicant"],
            "facility": row["facility"],
            "permit_numbers": row["permits"],
            "application_stage": row["application_stage"],
            "status": "Pending",
            "description": " ".join(
                part for part in (row["facility"], (summary or {}).get("purpose") or "") if part
            ),
            "purpose": (summary or {}).get("purpose"),
            "renewal_without_change": bool((summary or {}).get("renewal")),
            "summary_text": (summary or {}).get("text"),
            "location": location,
            "city": (summary or {}).get("city"),
            "county": (summary or {}).get("county"),
            "latitude": (summary or {}).get("latitude"),
            "longitude": (summary or {}).get("longitude"),
            "regulated_entity": (summary or {}).get("regulated_entity"),
            "summary_fetched": summary is not None,
            "document_links": {
                "plain language notice": row["notice_url"],
                "application": row["application_url"],
                "plain language summary": SUMMARY_URL.format(permit=permit.lower()),
            },
            "source_fields": {
                "applicant": "Applicant Name",
                "facility": "Facility Name",
                "permits": "Permit Number",
                "received": "Received Date",
                "location": "Plain Language Summary site sentence",
            },
        },
    }


def retrieve(source: dict[str, Any], client: httpx.Client | None = None) -> list[dict[str, Any]]:
    if source.get("id") != SOURCE_ID or source.get("endpoint") != LISTING_URL:
        raise SourceParseError("TCEQ source ID or endpoint is not configured")
    max_summaries = int(source.get("query", {}).get("max_summaries", 0))
    if not 0 <= max_summaries <= 60:
        raise SourceParseError("TCEQ summary bound is invalid")
    today = datetime.now(ZoneInfo("America/Chicago")).date()
    http = client or httpx.Client(timeout=25, follow_redirects=False)
    try:
        _, body = read_bounded_response(http, LISTING_URL, MAX_LISTING_BYTES)
        rows = parse_listing(body, today)
        records = []
        fetched = 0
        # Newest relevant filings get the bounded summary budget first.
        for row in sorted(rows, key=lambda item: item["received"], reverse=True):
            summary = None
            relevant = RELEVANT_NAME.search(f"{row['applicant']} {row['facility']}")
            if relevant and fetched < max_summaries:
                fetched += 1
                permit = row["permits"][0]
                try:
                    _, pdf = read_bounded_response(
                        http, SUMMARY_URL.format(permit=permit.lower()), MAX_PDF_BYTES
                    )
                    summary = parse_summary(pdf, permit)
                except (httpx.HTTPError, SourceParseError, ValueError):
                    summary = None  # The listing row is still retained; location stays unknown.
            records.append(_record(row, summary))
        return records
    finally:
        if client is None:
            http.close()
