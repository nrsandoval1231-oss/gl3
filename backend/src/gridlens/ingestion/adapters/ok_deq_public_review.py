"""Oklahoma DEQ permits currently posted for public review.

The index is one HTML table. It has no bulk export. Rows are kept when the
company, facility, or permit type names a data center or on-site power
equipment. The index often has no event date; a public-comment window in the
step column is the only date this adapter records.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from html.parser import HTMLParser
from typing import Any

import httpx

from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.power_signals import power_signal_tags
from gridlens.ingestion.adapters.public_source_http import read_public_response

SOURCE_ID = "oklahoma-deq-public-review"
LISTING_URL = "https://applications.deq.ok.gov/PermitsPublicReview/"
HOST = "applications.deq.ok.gov"
MAX_RESPONSE_BYTES = 2_000_000
MAX_RECORDS = 400
_COLUMNS = [
    "Division",
    "County",
    "Company",
    "Facility",
    "Permit #",
    "Tier",
    "Type",
    "Step",
    "Staff Name",
    "Status",
    "Related Information",
]
_RELEVANT = re.compile(
    r"data\s*cent(?:er|re)|turbine|generator|electric\s+generat|hyperscale|"
    r"\bengines?\b|behind[- ]the[- ]meter|temporary power|power plant|"
    r"\bbridge power\b|\bbridge generation\b|\bbridging power\b",
    re.IGNORECASE,
)
_COMMENT_START = re.compile(r"(\d{2}/\d{2}/\d{4})")
_DETAIL_ID = re.compile(r"(?:^|/)permitinformation\.aspx\?id=(\d{1,12})$", re.IGNORECASE)


class _ReviewTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.hrefs: list[str | None] = []
        self._in_table = 0
        self._cells: list[str] | None = None
        self._cell: list[str] | None = None
        self._href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._in_table += 1
        if self._in_table != 1:
            return
        if tag == "tr":
            self._cells = []
            self._href = None
        elif tag in {"td", "th"} and self._cells is not None:
            self._cell = []
        elif tag == "a" and self._cell is not None and self._href is None:
            href = dict(attrs).get("href")
            if href and "permitinformation.aspx" in href.casefold():
                self._href = href

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self._in_table:
            self._in_table -= 1
            return
        if self._in_table != 1:
            return
        if tag in {"td", "th"} and self._cell is not None and self._cells is not None:
            self._cells.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._cells is not None:
            if any(self._cells):
                self.rows.append(self._cells)
                self.hrefs.append(self._href)
            self._cells = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def _detail_url(href: str | None) -> str:
    if not href:
        return LISTING_URL
    match = _DETAIL_ID.search(href.strip())
    if not match:
        return LISTING_URL
    return f"https://{HOST}/PermitsPublicReview/permitinformation.aspx?id={match.group(1)}"


def _event_date(step: str) -> str | None:
    match = _COMMENT_START.search(step)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%m/%d/%Y").date().isoformat()
    except ValueError as exc:
        raise SourceParseError("Oklahoma DEQ comment date is malformed") from exc


def parse_listing(body: bytes) -> list[dict[str, Any]]:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceParseError("Oklahoma DEQ listing is not UTF-8") from exc
    parser = _ReviewTableParser()
    parser.feed(text)
    if not parser.rows:
        raise SourceParseError("Oklahoma DEQ listing has no table")
    if parser.rows[0] != _COLUMNS:
        raise SourceParseError("Oklahoma DEQ listing columns changed")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for cells, href in zip(parser.rows[1:], parser.hrefs[1:], strict=True):
        if len(cells) not in {10, 11}:
            raise SourceParseError("Oklahoma DEQ listing row has an unexpected column count")
        padded = cells + [""] * (11 - len(cells))
        row = dict(zip(_COLUMNS, padded, strict=True))
        permit_no = row["Permit #"].strip()
        facility = row["Facility"].strip()
        company = row["Company"].strip()
        if not permit_no or not facility or not company:
            raise SourceParseError("Oklahoma DEQ listing row lacks permit, facility, or company")
        if permit_no in seen:
            raise SourceParseError("Oklahoma DEQ listing has a duplicate permit number")
        seen.add(permit_no)
        blob = " ".join(row[key] for key in ("Company", "Facility", "Type", "Step"))
        if not _RELEVANT.search(blob):
            continue
        county = row["County"].strip()
        location = f"{county.title()} County, OK" if county else None
        records.append(
            {
                "permit_no": permit_no,
                "division": row["Division"].strip(),
                "county": county,
                "company": company,
                "facility": facility,
                "tier": row["Tier"].strip(),
                "permit_type": row["Type"].strip(),
                "step": row["Step"].strip(),
                "status": row["Status"].strip(),
                "location": location,
                "event_date": _event_date(row["Step"]),
                "html_url": _detail_url(href),
                "tags": power_signal_tags(blob),
            }
        )
    if len(records) > MAX_RECORDS:
        raise SourceParseError("Oklahoma DEQ relevant row count exceeds its bound")
    return records


def _record(row: dict[str, Any]) -> dict[str, Any]:
    row_id = "OKDEQ-" + re.sub(r"[^A-Za-z0-9]+", "-", row["permit_no"]).strip("-")
    semantic = {key: row[key] for key in row if key != "tags"}
    semantic["power_signals"] = row["tags"]
    return {
        "document_number": row_id,
        "title": f"{row['facility']} — Oklahoma DEQ {row['permit_no']}",
        "abstract": "\n".join(
            [
                f"Company: {row['company']}",
                f"Facility: {row['facility']}",
                f"Division: {row['division']}",
                f"Permit: {row['permit_no']}",
                f"Type: {row['permit_type']}",
                f"Step: {row['step'] or 'not stated'}",
                f"Status: {row['status'] or 'not stated'}",
                f"County: {row['county'] or 'not stated'}",
                f"Power signal tags: {', '.join(row['tags']) or 'none'}",
            ]
        ),
        "publication_date": None,
        "event_date": row["event_date"],
        "event_date_label": (
            "Public comment window start (Oklahoma DEQ public-review index)"
            if row["event_date"]
            else None
        ),
        "html_url": row["html_url"],
        "extraction_location": "Oklahoma DEQ Permits for Public Review table",
        "source_hash": hashlib.sha256(
            json.dumps(semantic, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "permit": {
            "source_type": SOURCE_ID,
            "row_id": row_id,
            "applicant": row["company"],
            "facility": row["facility"],
            "permit_numbers": [row["permit_no"]],
            "permit_type": row["permit_type"],
            "status": row["status"],
            "description": f"{row['facility']} {row['permit_type']} {row['step']}".strip(),
            "location": row["location"],
            "county": row["county"].title() if row["county"] else None,
            "state": "OK",
            "power_signals": row["tags"],
            "document_links": {"Oklahoma DEQ public review": row["html_url"]},
            "source_fields": {
                "applicant": "Company",
                "facility": "Facility",
                "permit": "Permit #",
                "location": "County",
                "event_date": "Step public-comment window, when stated",
            },
        },
    }


def retrieve(source: dict[str, Any], client: httpx.Client | None = None) -> list[dict[str, Any]]:
    if source.get("id") != SOURCE_ID or source.get("endpoint") != LISTING_URL:
        raise SourceParseError("Oklahoma DEQ source ID or endpoint is not configured")
    query = source.get("query", {})
    bounds_ok = (
        query.get("max_response_bytes") == MAX_RESPONSE_BYTES
        and query.get("max_records") == MAX_RECORDS
    )
    if not bounds_ok:
        raise SourceParseError("Oklahoma DEQ query bounds are invalid")
    http = client or httpx.Client(timeout=25, follow_redirects=False, trust_env=False)
    try:
        _, body = read_public_response(
            http,
            LISTING_URL,
            max_bytes=MAX_RESPONSE_BYTES,
            allowed_media_types={"text/html"},
            allowed_hosts=frozenset({HOST}),
        )
        return [_record(row) for row in parse_listing(body)]
    finally:
        if client is None:
            http.close()
