"""TCEQ pending temporary concrete batch plant registrations (statewide Texas).

A temporary batch plant registered for a named project is direct evidence of heavy
construction at a site now. The official pending-permit summaries page lists applicant,
facility and registration number for every pending application; for temporary plants the
Notice of Application and Preliminary Decision PDF supplies the submission date and the
site (city, county, and a map coordinate). Admission is decided in the domain layer.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
from datetime import datetime
from typing import Any

import httpx
from bs4 import BeautifulSoup, Tag
from pypdf import PdfReader

from gridlens.ingestion.adapters.diagnostics import acquisition_diagnostics
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.tceq_http import read_tceq_response

SOURCE_ID = "texas-tceq-temporary-batch-plants"
LISTING_URL = (
    "https://www.tceq.texas.gov/permitting/air/newsourcereview/airpermits-pendingpermit-apps"
)
NOTICE_URL = (
    "https://www.tceq.texas.gov/downloads/permitting/air/bilingual/pending-permit-notices/"
    "{registration}-napd-english.pdf"
)
MAX_LISTING_BYTES = 6_000_000
MAX_PDF_BYTES = 2_000_000
MAX_PDF_PAGES = 4
MIN_ROWS = 20
MAX_ROWS = 3000
TEMPORARY = re.compile(r"\bTEMPORARY\b.*\b(?:BATCH|CBP)\b|\b(?:BATCH|CBP)\b.*\bTEMPORARY\b", re.I)
_SUBMITTED = re.compile(r"submitted to the TCEQ on ([A-Z][a-z]+ \d{1,2}, \d{4})")
_ISSUED = re.compile(r"Notice Issuance Date:\s*([A-Z][a-z]+ \d{1,2}, \d{4})")
_SITE = re.compile(
    r"(?P<city>[A-Z][A-Za-z .'\-]{1,40}),\s*(?P<county>[A-Z][A-Za-z .'\-]{1,40}?)\s+County,"
    r"\s*Texas\s+\d{5}"
)
_MARKER = re.compile(r"marker=(-?\d{1,3}\.\d+),(-?\d{1,3}\.\d+)")


def _cell(cell: Tag) -> str:
    return " ".join(cell.get_text(" ", strip=True).split())


def parse_listing(body: bytes) -> list[dict[str, Any]]:
    soup = BeautifulSoup(body, "html.parser")
    if soup.find(id="concretebatchplant") is None:
        raise SourceParseError("TCEQ summaries page lost its concrete batch plant section")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tr in soup.find_all("tr", id=True):
        if not isinstance(tr, Tag):
            continue
        cells = [cell for cell in tr.find_all("td", recursive=False) if isinstance(cell, Tag)]
        project = str(tr.get("id") or "")
        if len(cells) != 4 or not project.isdigit() or project in seen:
            continue
        applicant, facility, registration = (_cell(cells[0]), _cell(cells[1]), _cell(cells[2]))
        if not applicant or not facility or not registration:
            raise SourceParseError("TCEQ summaries row lacks applicant, facility or registration")
        seen.add(project)
        rows.append(
            {
                "project": project,
                "applicant": applicant,
                "facility": facility,
                "registration": registration.split(",")[0].strip(),
            }
        )
    if not MIN_ROWS <= len(rows) <= MAX_ROWS:
        raise SourceParseError("TCEQ summaries row count is outside its expected bounds")
    return rows


def _date(value: str) -> str:
    return datetime.strptime(value, "%B %d, %Y").date().isoformat()


def notice_from_text(text: str, registration: str) -> dict[str, Any]:
    text = " ".join(text.split())
    if registration.upper() not in text.upper():
        raise SourceParseError("TCEQ notice does not name the listed registration")
    submitted = _SUBMITTED.search(text)
    issued = _ISSUED.search(text)
    site = _SITE.search(text)
    marker = _MARKER.search(text)
    if not submitted or not site:
        raise SourceParseError("TCEQ notice lacks a submission date or site")
    return {
        "submitted": _date(submitted.group(1)),
        "issued": _date(issued.group(1)) if issued else None,
        "city": " ".join(site.group("city").split()),
        "county": " ".join(site.group("county").split()),
        # The notice's LocationMapper link is marker=<longitude>,<latitude>.
        "longitude": float(marker.group(1)) if marker else None,
        "latitude": float(marker.group(2)) if marker else None,
        "text": text[:2500],
    }


def parse_notice(body: bytes, registration: str) -> dict[str, Any]:
    if not body.startswith(b"%PDF-"):
        raise SourceParseError("TCEQ notice is not a PDF")
    reader = PdfReader(io.BytesIO(body))
    if len(reader.pages) > MAX_PDF_PAGES:
        raise SourceParseError("TCEQ notice exceeds its page bound")
    return notice_from_text(
        " ".join(page.extract_text() or "" for page in reader.pages), registration
    )


def record(row: dict[str, Any], notice: dict[str, Any]) -> dict[str, Any]:
    location = f"{notice['city']}, {notice['county']} County, TX"
    url = NOTICE_URL.format(registration=row["registration"].lower())
    semantic = {**row, **{k: v for k, v in notice.items() if k != "text"}}
    return {
        "document_number": f"TCEQ-CBP-{row['project']}",
        "title": f"{row['facility']} — TCEQ temporary batch plant {row['registration']}",
        "abstract": "\n".join(
            [
                f"Applicant: {row['applicant']}",
                f"Facility: {row['facility']}",
                f"Registration: {row['registration']}",
                f"Application submitted: {notice['submitted']}",
                f"Notice issued: {notice['issued'] or 'unknown'}",
                f"Location: {location}",
                f"Notice excerpt: {notice['text'][:900]}",
            ]
        ),
        "publication_date": notice["issued"],
        "event_date": notice["submitted"],
        "event_date_label": "Application submitted (TCEQ notice)",
        "html_url": url,
        "extraction_location": "TCEQ Notice of Application and Preliminary Decision, page 1",
        "source_hash": hashlib.sha256(
            json.dumps(semantic, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "permit": {
            "source_type": SOURCE_ID,
            "row_id": f"TCEQ-CBP-{row['project']}",
            "applicant": row["applicant"],
            "facility": row["facility"],
            "registration": row["registration"],
            "status": "Pending",
            "description": row["facility"],
            "location": location,
            "city": notice["city"],
            "county": notice["county"],
            "latitude": notice["latitude"],
            "longitude": notice["longitude"],
            "document_links": {"notice": url, "summaries page": LISTING_URL},
            "source_fields": {
                "facility": "Facility Name (summaries table)",
                "submitted": "Notice: submitted to the TCEQ on",
                "location": "Notice: driving-directions city, county",
            },
        },
    }


def retrieve(source: dict[str, Any], client: httpx.Client | None = None) -> list[dict[str, Any]]:
    if source.get("id") != SOURCE_ID or source.get("endpoint") != LISTING_URL:
        raise SourceParseError("TCEQ batch plant source ID or endpoint is not configured")
    max_notices = int(source.get("query", {}).get("max_notices", 0))
    if not 0 <= max_notices <= 40:
        raise SourceParseError("TCEQ notice bound is invalid")
    http = client or httpx.Client(timeout=25, follow_redirects=False, trust_env=False)
    try:
        _, body = read_tceq_response(http, LISTING_URL, MAX_LISTING_BYTES, route="listing")
        rows = [row for row in parse_listing(body) if TEMPORARY.search(row["facility"])]
        records: list[dict[str, Any]] = []
        attempted = 0
        rate_limited = False
        for row in rows:
            if rate_limited:
                records.append(
                    _presence_only(
                        row,
                        SourceParseError("notice deferred after publisher rate limit"),
                        deferred=True,
                    )
                )
                continue
            if attempted >= max_notices:
                records.append(
                    _presence_only(row, SourceParseError("notice fetch budget exhausted"))
                )
                continue
            attempted += 1
            try:
                _, pdf = read_tceq_response(
                    http,
                    NOTICE_URL.format(registration=row["registration"].lower()),
                    MAX_PDF_BYTES,
                    route="pdf",
                )
                records.append(record(row, parse_notice(pdf, row["registration"])))
            except (httpx.HTTPError, SourceParseError, ValueError) as error:
                presence = _presence_only(row, error)
                records.append(presence)
                diagnostics = acquisition_diagnostics(error)
                status = diagnostics.get("http_status")
                retryable_status = type(status) is int and (
                    status in {408, 425, 429} or status >= 500
                )
                rate_limited = (
                    status == 429
                    or retryable_status
                    and (
                        "retry_after_seconds" in diagnostics
                        or diagnostics.get("retry_after_exceeds_bound") == 1
                    )
                )
                if rate_limited:
                    presence["_acquisition_diagnostics"] = {
                        key: diagnostics[key]
                        for key in (
                            "http_status",
                            "retry_after_seconds",
                            "retry_after_at",
                            "retry_after_exceeds_bound",
                            "retry_after_unrepresentable",
                        )
                        if key in diagnostics
                    }
        return records
    finally:
        if client is None:
            http.close()


def _presence_only(
    row: dict[str, Any], error: BaseException, *, deferred: bool = False
) -> dict[str, Any]:
    status = error.response.status_code if isinstance(error, httpx.HTTPStatusError) else None
    code = (
        f"http_status_{status}"
        if type(status) is int and 100 <= status <= 599
        else "network_error"
        if isinstance(error, httpx.RequestError)
        else "acquisition_timeout"
        if isinstance(error, TimeoutError)
        else "document_deferred"
        if deferred
        else "invalid_official_document"
    )
    registration = str(row["registration"])[:64]
    identity = f"TCEQ-CBP-{row['project']}"
    return {
        "document_number": identity,
        "presence_only": True,
        "partial_snapshot": True,
        "rejected_record": {
            "identity": identity,
            "stage": "tceq_document",
            "error_code": code,
            "selected_fields": ["registration"],
            "omitted_fields": ["document_body"],
            "raw": {"registration": registration},
        },
    }
