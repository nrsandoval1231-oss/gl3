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
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup, Tag
from pypdf import PdfReader

from gridlens.ingestion.adapters.diagnostics import acquisition_diagnostics
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.tceq_http import read_tceq_response

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
_NOTICE_PATH = "/permitting/air/newsourcereview/airpermits-pendingpermit-apps"
_ECID_URL = "https://www14.tceq.texas.gov/epic/eCID/"
_APPLICATION_PATH = re.compile(
    r"^/assets/public/permitting/air/reports/applications/\d+-[a-z0-9-]+\.pdf$",
    re.IGNORECASE,
)

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


def _bounded_text(value: str, max_bytes: int) -> str:
    return value.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")


def _received(value: str, today: date) -> date:
    try:
        received = datetime.strptime(value, "%m/%d/%Y").date()
    except ValueError as exc:
        raise SourceParseError("TCEQ received date is malformed") from exc
    if received > today:
        raise SourceParseError("TCEQ received date is in the future")
    return received


def _normalize_link(url: str) -> str:
    # TCEQ wraps long hrefs at line boundaries in its HTML. Remove only those
    # line breaks, then resolve relative links against the fixed official page.
    if any(ord(char) < 0x20 and char not in "\r\n" for char in url) or "\x7f" in url:
        raise SourceParseError("TCEQ link contains an invalid control character")
    raw_path = urlsplit(url).path
    if any(segment in {".", ".."} for segment in raw_path.split("/")):
        raise SourceParseError("TCEQ link contains a traversal segment")
    # One observed publisher wrap splits the hostname at the omitted dot before
    # gov; repair that exact known form as well as ordinary filename wrapping.
    normalized = url.replace("www.tceq.texas\r\ngov", "www.tceq.texas.gov")
    normalized = normalized.replace("\r", "").replace("\n", "")
    return urljoin(LISTING_URL, normalized)


def _official(url: str) -> str:
    normalized = _normalize_link(url)
    parts = urlsplit(normalized)
    if (
        parts.scheme != "https"
        or parts.hostname != HOST
        or parts.username is not None
        or parts.password is not None
        or parts.port not in (None, 443)
        or parts.query
        or not (
            (_APPLICATION_PATH.fullmatch(parts.path) and not parts.fragment)
            or (parts.path == _NOTICE_PATH and parts.fragment.isdigit())
        )
    ):
        raise SourceParseError("TCEQ link is outside the official host")
    return normalized


def _notice(url: str) -> str:
    # eCID is an exact citation-only landing page, never a retrieval destination.
    # Its absence of a project fragment does not make its navigation a project ID.
    normalized = _normalize_link(url)
    if normalized == _ECID_URL:
        return normalized
    normalized = _official(url)
    if urlsplit(normalized).path != _NOTICE_PATH:
        raise SourceParseError("TCEQ notice link is outside the official notice path")
    return normalized


def parse_listing(
    body: bytes,
    today: date,
    *,
    rejected: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
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
            if cells and (
                re.search(r"\b\d{2}/\d{2}/\d{4}\b", _text(tr))
                or any(
                    re.search(r"/reports/applications/\d+-", str(anchor.get("href", "")))
                    for anchor in tr.find_all("a", href=True)
                    if isinstance(anchor, Tag)
                )
            ):
                raise SourceParseError("TCEQ listing application row has an invalid column count")
            continue
        applicant_cell, facility_cell, permit_cell, date_cell, link_cell = cells
        notice = applicant_cell.find("a", href=True)
        application = link_cell.find("a", href=True)
        if not isinstance(notice, Tag) or not isinstance(application, Tag):
            if any(_text(cell) for cell in (facility_cell, permit_cell, date_cell)):
                raise SourceParseError("TCEQ listing application row is missing a required link")
            continue
        notice_url = _notice(str(notice["href"]))
        application_url = _official(str(application["href"]))
        if not _APPLICATION_PATH.fullmatch(urlsplit(application_url).path):
            raise SourceParseError("TCEQ application link is outside the official application path")
        project = urlsplit(notice_url).fragment
        application_project = re.fullmatch(
            r"/assets/public/permitting/air/reports/applications/(\d+)-(?:ac|tc)\.pdf",
            urlsplit(application_url).path,
            re.IGNORECASE,
        )
        if notice_url == _ECID_URL:
            # Official AC/TC document filenames carry the TCEQ project number,
            # corroborated by the legacy notice fragments paired with these paths.
            if application_project is None:
                raise SourceParseError("TCEQ eCID row lacks a validated application project path")
            project = application_project.group(1)
        elif application_project and project != application_project.group(1):
            raise SourceParseError("TCEQ notice and application project identities conflict")
        if not project.isdigit() or len(project) > 12:
            raise SourceParseError("TCEQ listing row lacks applicant, facility, permit or project")
        if project in seen:
            raise SourceParseError("TCEQ listing has duplicate project identity")
        seen.add(project)
        for anchor in applicant_cell.find_all("a"):
            anchor.extract()
        applicant = _text(applicant_cell)
        facility = _text(facility_cell)
        permits = [p.strip() for p in _text(permit_cell).replace(" ", "").split(",") if p.strip()]
        raw = {
            "applicant": _bounded_text(applicant, 256),
            "facility": _bounded_text(facility, 256),
            "permits": _bounded_text(_text(permit_cell), 256),
            "received": _bounded_text(_text(date_cell), 64),
        }
        try:
            if not applicant or not facility or not permits:
                raise SourceParseError(
                    "TCEQ listing row lacks applicant, facility, permit or project"
                )
            received = _received(raw["received"], today)
        except SourceParseError as exc:
            if rejected is None:
                raise
            code = "tceq_received_date" if "date" in str(exc).lower() else "tceq_row_identity"
            rejected.append(
                {
                    "identity": f"TCEQ-{project}",
                    "stage": "tceq_listing_row",
                    "error_code": code,
                    "selected_fields": sorted(raw),
                    "omitted_fields": [],
                    "raw": raw,
                }
            )
            continue
        rows.append(
            {
                "project": project,
                "applicant": applicant,
                "facility": facility,
                "permits": permits,
                "received": received,
                "notice_href": str(notice["href"]),
                "application_href": str(application["href"]),
                "notice_url": notice_url,
                "application_url": application_url,
                "application_stage": _text(application),
            }
        )
    total_rows = len(rows) + len(rejected or [])
    if not MIN_ROWS <= total_rows <= MAX_ROWS:
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
        "html_url": (
            row["application_url"] if row["notice_url"] == _ECID_URL else row["notice_url"]
        ),
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
            "source_link_hrefs": {
                "plain language notice": row.get("notice_href", row["notice_url"]),
                "application": row.get("application_href", row["application_url"]),
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


def _presence_only(
    row: dict[str, Any], error: BaseException, *, deferred: bool = False
) -> dict[str, Any]:
    """Keep source identity for snapshot reconciliation and a bounded failure reason."""
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
    permit = str(row["permits"][0])[:64]
    return {
        "document_number": f"TCEQ-{row['project']}",
        "presence_only": True,
        "partial_snapshot": True,
        "rejected_record": {
            "identity": f"TCEQ-{row['project']}",
            "stage": "tceq_document",
            "error_code": code,
            "selected_fields": ["permit"],
            "omitted_fields": ["document_body"],
            "raw": {"permit": permit},
        },
    }


def retrieve(source: dict[str, Any], client: httpx.Client | None = None) -> list[dict[str, Any]]:
    if source.get("id") != SOURCE_ID or source.get("endpoint") != LISTING_URL:
        raise SourceParseError("TCEQ source ID or endpoint is not configured")
    max_summaries = int(source.get("query", {}).get("max_summaries", 0))
    if not 0 <= max_summaries <= 60:
        raise SourceParseError("TCEQ summary bound is invalid")
    today = datetime.now(ZoneInfo("America/Chicago")).date()
    http = client or httpx.Client(timeout=25, follow_redirects=False, trust_env=False)
    try:
        _, body = read_tceq_response(http, LISTING_URL, MAX_LISTING_BYTES, route="listing")
        rejected_rows: list[dict[str, Any]] = []
        rows = parse_listing(body, today, rejected=rejected_rows)
        records = [
            {
                "document_number": item["identity"],
                "presence_only": True,
                "partial_snapshot": True,
                "rejected_record": item,
            }
            for item in rejected_rows
        ]
        attempted = 0
        # Newest relevant filings get the bounded summary budget first. A relevant row is
        # emitted only with a successfully parsed summary: emitting it without one would
        # replace prior enrichment with an unsited version and could retire a valid Signal.
        # Skipped rows keep their last stored version and are retried on the next run.
        rate_limited = False
        for row in sorted(rows, key=lambda item: item["received"], reverse=True):
            if not RELEVANT_NAME.search(f"{row['applicant']} {row['facility']}"):
                records.append(_record(row, None))
                continue
            if rate_limited:
                records.append(
                    _presence_only(
                        row,
                        SourceParseError("summary deferred after publisher rate limit"),
                        deferred=True,
                    )
                )
                continue
            if attempted >= max_summaries:
                records.append(
                    _presence_only(row, SourceParseError("summary fetch budget exhausted"))
                )
                continue
            attempted += 1
            permit = row["permits"][0]
            try:
                _, pdf = read_tceq_response(
                    http,
                    SUMMARY_URL.format(permit=permit.lower()),
                    MAX_PDF_BYTES,
                    route="pdf",
                )
                records.append(_record(row, parse_summary(pdf, permit)))
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
                            "retry_after_exceeds_bound",
                        )
                        if key in diagnostics
                    }
        return records
    finally:
        if client is None:
            http.close()
