"""ERCOT Monthly Operational Overview: approved-to-energize versus observed large load (aggregate).

Live check 2026-11-04: ERCOT publishes a PDF each month (``/files/docs/YYYY/MM/DD/ERCOT-Monthly-
Operational-Overview-<Month>[-<Year>].pdf``, 1.2 to 1.6 MB, 27 to 31 pages) and the Board of
Directors page ``https://www.ercot.com/committees/board/index.html`` links every 2026 issue (nine
links, January to September). The March, August and September 2026 issues all carry the same
sentence on the "Loads Approved to Energize - Observations" page, for example September 2026:
"Of the 9,456 MW that have received Approval to Energize, ERCOT has observed a non-simultaneous
monthly peak consumption of 4,132 MW in September 2026". There is no machine-readable monthly
dataset (no CSV, no API), so this is a text extraction from a public PDF.

The figures are ERCOT-wide aggregates. They are never a site, a customer or a project, and this
reader emits no location. The ratio observed over approved is calculated from the two stated
numbers and labelled calculated. If a sentence is missing, the figure is unknown, not zero.
"""

from __future__ import annotations

import io
import re
from datetime import date
from typing import Any

import httpx
from pypdf import PdfReader

from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.sector_common import (
    Pacer,
    candidate_record,
    fetch,
    new_client,
    require_source,
)

SOURCE_ID = "texas-ercot-monthly-overview"
HOST = "www.ercot.com"
ENDPOINT = "https://www.ercot.com/committees/board/index.html"
MAX_PDF_PAGES = 60
MONTHS = [
    "January", "February", "March", "April", "May", "June", "July", "August", "September",
    "October", "November", "December",
]
_LINK = re.compile(
    r'href="(https://www\.ercot\.com/files/docs/(20\d{2})/(\d{2})/(\d{2})/'
    r'ERCOT-Monthly-Operational-Overview-[A-Za-z0-9-]{1,40}\.pdf)"',
    re.IGNORECASE,
)
_TITLE = re.compile(r"ERCOT Monthly Operational Overview \((" + "|".join(MONTHS) + r") (20\d{2})\)")
_FACT = re.compile(
    r"Of the (\d[\d,]*) MW that have received Approval to Energize, ERCOT has observed a "
    r"non-simultaneous monthly peak consumption of (\d[\d,]*) MW in ("
    + "|".join(MONTHS)
    + r") (20\d{2})"
)


def valid_query(source: dict[str, Any]) -> bool:
    query = source.get("query")
    return (
        isinstance(query, dict)
        and source.get("id") == SOURCE_ID
        and source.get("endpoint") == ENDPOINT
        and source.get("cadence_hours") == 168
        and source.get("family") == "structured-government"
        and set(query) == {"max_response_bytes", "max_reports", "max_pdf_bytes"}
        and query["max_response_bytes"] == 2_000_000
        and type(query["max_reports"]) is int
        and 1 <= query["max_reports"] <= 3
        and type(query["max_pdf_bytes"]) is int
        and 1_000_000 <= query["max_pdf_bytes"] <= 6_000_000
    )


def report_links(page: bytes) -> list[dict[str, Any]]:
    """Monthly overview PDFs linked from the page, newest first (by the date in the path)."""
    text = page.decode("utf-8", errors="replace")
    found: dict[str, dict[str, Any]] = {}
    for match in _LINK.finditer(text):
        url = match.group(1)
        try:
            posted = date(int(match.group(2)), int(match.group(3)), int(match.group(4)))
        except ValueError:
            continue
        found[url] = {"url": url, "posted": posted.isoformat()}
    return sorted(found.values(), key=lambda item: (item["posted"], item["url"]), reverse=True)


def parse_overview(body: bytes) -> dict[str, Any]:
    try:
        reader = PdfReader(io.BytesIO(body))
    except Exception as exc:
        raise SourceParseError("ERCOT overview PDF could not be read") from exc
    if reader.is_encrypted or len(reader.pages) > MAX_PDF_PAGES:
        raise SourceParseError("ERCOT overview PDF is encrypted or longer than its page bound")
    text = " ".join(" ".join((page.extract_text() or "") for page in reader.pages).split())
    title = _TITLE.search(text)
    if not title:
        raise SourceParseError("ERCOT overview PDF does not state its report month")
    month = MONTHS.index(title.group(1)) + 1
    year = int(title.group(2))
    fact = _FACT.search(text)
    approved = observed = None
    if fact and fact.group(3) == title.group(1) and int(fact.group(4)) == year:
        approved = int(fact.group(1).replace(",", ""))
        observed = int(fact.group(2).replace(",", ""))
    return {
        "report_month": f"{year:04d}-{month:02d}",
        "approved_to_energize_mw": approved,
        "observed_nonsimultaneous_peak_mw": observed,
        "quote": fact.group(0) if approved is not None else None,
    }


def build_record(parsed: dict[str, Any], url: str, posted: str) -> dict[str, Any]:
    approved, observed = parsed["approved_to_energize_mw"], parsed["observed_nonsimultaneous_peak_mw"]
    ratio = round(observed / approved, 3) if approved and observed is not None else None
    month = parsed["report_month"]
    lines = [
        f"ERCOT Monthly Operational Overview, report month {month}; PDF posted {posted}",
        "ERCOT-wide aggregate of large loads approved to energize; not a site, customer or project.",
        f"MW approved to energize: {approved if approved is not None else 'not stated'}",
        "Observed non-simultaneous monthly peak MW: "
        + (str(observed) if observed is not None else "not stated"),
        "Calculated observed / approved (from the two stated numbers): "
        + (str(ratio) if ratio is not None else "unknown"),
        f'Quote: "{parsed["quote"]}"' if parsed["quote"] else "Quote: sentence not found",
    ]
    year, mon = month.split("-")
    return candidate_record(
        source_id=SOURCE_ID,
        row_id=f"ERCOT-MONTHLY-{month}",
        title=f"ERCOT Monthly Operational Overview {month}: approved to energize vs observed",
        abstract_lines=lines,
        url=url,
        extraction_location="ERCOT Monthly Operational Overview, Loads Approved to Energize page",
        semantic={"parsed": parsed, "url": url},
        publication_date=posted,
        event_date=date(int(year), int(mon), 1).isoformat(),
        event_date_label="ERCOT report month (first day)",
        permit={
            "applicant": "ERCOT",
            "facility": f"ERCOT large-load aggregate {month}",
            "status": None,
            "location": None,
            "state": None,
            "permit_type": "ERCOT monthly approved-versus-observed aggregate",
            "stated_aggregates": {
                "approved_to_energize_mw": approved,
                "observed_nonsimultaneous_peak_mw": observed,
            },
            "calculated_observed_over_approved": ratio,
            "source_fields": {
                "event_date": "report month in the PDF title",
                "publication_date": "date folder in the PDF URL",
            },
        },
    )


def retrieve(
    source: dict[str, Any], client: httpx.Client | None = None, *, pacer: Pacer | None = None
) -> list[dict[str, Any]]:
    require_source(source, SOURCE_ID, ENDPOINT)
    if not valid_query(source):
        raise SourceParseError("ERCOT monthly query bounds are invalid")
    query = source["query"]
    http = client or new_client()
    pace = pacer or Pacer()
    try:
        _, page = fetch(http, ENDPOINT, hosts={HOST}, max_bytes=query["max_response_bytes"],
                        media_types={"text/html"}, pacer=pace)
        links = report_links(page)[: query["max_reports"]]
        if not links:
            raise SourceParseError("ERCOT board page links no monthly overview PDF")
        records = []
        for link in links:
            _, body = fetch(http, link["url"], hosts={HOST}, max_bytes=query["max_pdf_bytes"],
                            media_types={"application/pdf"}, pacer=pace)
            records.append(build_record(parse_overview(body), link["url"], link["posted"]))
        return sorted(records, key=lambda r: r["document_number"])
    finally:
        if client is None:
            http.close()
