"""California CEQAnet environmental documents that name a data center (statewide California).

CEQAnet is the State Clearinghouse database of CEQA documents. Its search accepts a
development type and a received-date range and returns every matching document in one HTML
table with a stated document count. Each document page gives the lead agency, document type,
received date, description, cities, counties and coordinates. A CEQA filing that names a data
center is official, dated evidence that a specific site is in environmental review. Admission
is decided in the domain layer.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx
from bs4 import BeautifulSoup, Tag

from gridlens.ingestion.adapters.bounded_http import read_bounded_response
from gridlens.ingestion.adapters.federal_register import SourceParseError

SOURCE_ID = "california-ceqanet-data-centers"
SEARCH_URL = "https://ceqanet.lci.ca.gov/Search"
HOST = "ceqanet.lci.ca.gov"
DEVELOPMENT_TYPES = {"Industrial", "Power", "Commercial", "Office", "Other"}
MAX_LISTING_BYTES = 3_000_000
MAX_DOCUMENT_BYTES = 1_000_000
MAX_ROWS_PER_TYPE = 400
DATA_CENTER = re.compile(r"\bdata\s*cent(?:er|re)s?\b|\bhyperscale\b", re.IGNORECASE)
_FOUND = re.compile(r"(\d[\d,]*)\s+document\(s\)\s+found")
_DMS = re.compile(r"(\d{1,3})°(\d{1,2})'([\d.]+)\"?\s*([NSEW])")


def _text(node: Tag | None) -> str:
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""


def parse_listing(body: bytes) -> list[dict[str, str]]:
    soup = BeautifulSoup(body, "html.parser")
    found = _FOUND.search(soup.get_text(" "))
    if not found:
        raise SourceParseError("CEQAnet search page lacks its document count")
    expected = int(found.group(1).replace(",", ""))
    rows: list[dict[str, str]] = []
    for tr in soup.select("table tbody tr"):
        cells = [cell for cell in tr.find_all("td", recursive=False) if isinstance(cell, Tag)]
        if len(cells) != 5:
            raise SourceParseError("CEQAnet result row does not have five columns")
        link = cells[1].find("a", href=True)
        received = cells[3].find("time")
        url = str(link["href"]) if isinstance(link, Tag) else ""
        if urlparse(url).hostname != HOST or not isinstance(received, Tag):
            raise SourceParseError("CEQAnet result row lacks a document link or received date")
        rows.append(
            {
                "sch": _text(cells[0]),
                "document_type": _text(cells[1]),
                "lead_agency": _text(cells[2]),
                "received": str(received.get("datetime") or ""),
                "title": _text(cells[4]),
                "url": url,
            }
        )
    if len(rows) != expected:
        # A silent page cap would hide documents; fail instead.
        raise SourceParseError(
            f"CEQAnet listed {expected} documents but the table holds {len(rows)}"
        )
    if len(rows) > MAX_ROWS_PER_TYPE:
        raise SourceParseError("CEQAnet result count exceeds its bound")
    return rows


def _dms(value: str) -> float | None:
    match = _DMS.search(value)
    if not match:
        return None
    degrees, minutes, seconds, hemisphere = match.groups()
    decimal = int(degrees) + int(minutes) / 60 + float(seconds) / 3600
    return round(-decimal if hemisphere in "SW" else decimal, 6)


def parse_document(body: bytes) -> dict[str, Any]:
    soup = BeautifulSoup(body, "html.parser")
    fields: dict[str, str] = {}
    for row in soup.select("div.row"):
        label = row.find("strong")
        value = row.find("div", class_="col-md-9")
        if isinstance(label, Tag) and isinstance(value, Tag):
            fields.setdefault(_text(label), _text(value))
    if not fields.get("SCH Number") or not fields.get("Document Title"):
        raise SourceParseError("CEQAnet document page lacks its SCH number or title")
    latitude = soup.find("meta", itemprop="latitude")
    longitude = soup.find("meta", itemprop="longitude")
    return {
        "sch": fields["SCH Number"],
        "title": fields["Document Title"],
        "lead_agency": fields.get("Lead Agency") or fields.get("Public Agency") or "",
        "document_type": fields.get("Document Type", ""),
        "description": fields.get("Document Description", ""),
        "cities": fields.get("Cities", ""),
        "counties": fields.get("Counties", ""),
        "development_types": fields.get("Development Types", ""),
        "latitude": _dms(str(latitude.get("content"))) if isinstance(latitude, Tag) else None,
        "longitude": _dms(str(longitude.get("content"))) if isinstance(longitude, Tag) else None,
    }


def names_data_center(row: dict[str, Any], document: dict[str, Any] | None = None) -> bool:
    text = " ".join([row.get("title", ""), (document or {}).get("description", "")])
    return bool(DATA_CENTER.search(text))


def record(row: dict[str, str], document: dict[str, Any]) -> dict[str, Any]:
    city = document["cities"].split(",")[0].strip()
    county = document["counties"].split(",")[0].strip()
    place = ", ".join(part for part in [city, f"{county} County" if county else ""] if part)
    location = f"{place}, CA" if place else None
    row_id = f"CEQA-{row['sch']}-{urlparse(row['url']).path.strip('/').replace('/', '-')}"
    semantic = {**row, **document}
    return {
        "document_number": row_id,
        "title": f"{document['title']} — CEQA {row['document_type']} ({document['lead_agency']})",
        "abstract": "\n".join(
            [
                f"Lead agency: {document['lead_agency']}",
                f"Document type: {document['document_type']}",
                f"Received: {row['received']}",
                f"Location: {location or 'not stated'}",
                f"Development types: {document['development_types'] or 'not stated'}",
                f"Description: {document['description'][:1500]}",
            ]
        ),
        "publication_date": row["received"],
        "event_date": row["received"],
        "event_date_label": "Received by the State Clearinghouse (CEQAnet)",
        "html_url": row["url"],
        "extraction_location": "CEQAnet document page: Summary and Location sections",
        "source_hash": hashlib.sha256(
            json.dumps(semantic, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "permit": {
            "source_type": SOURCE_ID,
            "row_id": row_id,
            "applicant": document["lead_agency"],
            "facility": document["title"],
            "document_type": document["document_type"],
            "status": document["document_type"],
            "description": document["description"],
            "title_names_data_center": bool(DATA_CENTER.search(document["title"])),
            "location": location,
            "city": city or None,
            "county": county or None,
            "latitude": document["latitude"],
            "longitude": document["longitude"],
            "document_links": {"CEQAnet document": row["url"]},
            "source_fields": {
                "facility": "Document Title",
                "received": "Received",
                "location": "Cities, Counties",
                "description": "Document Description",
            },
        },
    }


def _search_url(development_type: str, start: date, end: date) -> str:
    query = {
        "DevelopmentType": development_type,
        "StartRange": start.isoformat(),
        "EndRange": end.isoformat(),
    }
    return f"{SEARCH_URL}?{urlencode(query)}"


def retrieve(
    source: dict[str, Any], client: httpx.Client | None = None, today: date | None = None
) -> list[dict[str, Any]]:
    if source.get("id") != SOURCE_ID or source.get("endpoint") != SEARCH_URL:
        raise SourceParseError("CEQAnet source ID or endpoint is not configured")
    query = source.get("query", {})
    types = list(query.get("development_types", []))
    window = int(query.get("window_days", 0))
    max_documents = int(query.get("max_documents", 0))
    if not types or not set(types) <= DEVELOPMENT_TYPES or not 1 <= window <= 90:
        raise SourceParseError("CEQAnet query bounds are invalid")
    if not 1 <= max_documents <= 60:
        raise SourceParseError("CEQAnet document bound is invalid")
    end = today or date.today()
    start = end - timedelta(days=window)
    http = client or httpx.Client(timeout=25, follow_redirects=False)
    try:
        rows: dict[str, dict[str, str]] = {}
        for development_type in types:
            _, body = read_bounded_response(
                http, _search_url(development_type, start, end), MAX_LISTING_BYTES
            )
            for row in parse_listing(body):
                rows.setdefault(row["url"], row)
        # Titles that name a data center are read first; the rest are read while the bound
        # allows, because many filings name the data center only in their description.
        ordered = sorted(rows.values(), key=lambda row: not names_data_center(row))
        titled = [row for row in ordered if names_data_center(row)]
        if len(titled) > max_documents:
            raise SourceParseError(
                f"CEQAnet has {len(titled)} data-center titles, above the per-run bound"
            )
        records: list[dict[str, Any]] = []
        attempted = failed = 0
        for row in ordered[:max_documents]:
            attempted += 1
            try:
                _, page = read_bounded_response(http, row["url"], MAX_DOCUMENT_BYTES)
                document = parse_document(page)
            except (httpx.HTTPError, SourceParseError, ValueError):
                failed += 1
                if names_data_center(row):
                    raise SourceParseError(
                        f"CEQAnet document {row['sch']} names a data center but could not be read"
                    ) from None
                continue
            if names_data_center(row, document):
                records.append(record(row, document))
        if attempted and failed * 2 > attempted:
            raise SourceParseError(
                f"CEQAnet document pages failed for {failed} of {attempted} documents"
            )
        return records
    finally:
        if client is None:
            http.close()
