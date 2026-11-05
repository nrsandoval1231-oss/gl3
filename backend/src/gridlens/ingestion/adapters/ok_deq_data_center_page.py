"""Discovery from the Oklahoma DEQ "information on data centers" page.

The page (``https://oklahoma.gov/deq/deq-information-on-data-centers.html``) carries an HTML
table of issued and pending data-center permits: division, county, company, facility, permit
type, status and a link to a static PDF. It has no permit-number or application-id column; the
permit number is only readable from the linked file name (``2021-0235-C%20M-2.pdf``), so it is
recorded as ``from link file name`` and is absent for links such as ``Stillwater Data Center
Permit.pdf``.

This module is discovery only. It parses the table and offers the rows to the document stage
for joining on permit number. The linked PDFs describe on-site generation (supply), never
demand; they are not fetched or extracted here.
"""

from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit

from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.ok_deq_memo import normalize_permit

PAGE_HOST = "oklahoma.gov"
PAGE_URL = "https://oklahoma.gov/deq/deq-information-on-data-centers.html"
MAX_PAGE_BYTES = 2_000_000
MAX_ROWS = 200
MAX_CELL_CHARS = 200
_COLUMNS = ["DIV", "COUNTY", "COMPANY", "FACILITY", "PERMIT TYPE", "STATUS", "LINK"]
_PDF_PATH = re.compile(r"/content/dam/ok/en/deq/documents/(?:[A-Za-z0-9_.-]+/)+[^/\\]+\.pdf")
_FILE_PERMIT = re.compile(
    r"^(\d{4}-\d{2,5}-[A-Z]{1,4}\d{0,2})(?:[ _]+(M-?\d{1,2}))?\.pdf$", re.IGNORECASE
)


class _Table(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[tuple[list[str], str | None]]] = []
        self._depth = 0
        self._rows: list[tuple[list[str], str | None]] | None = None
        self._cells: list[str] | None = None
        self._cell: list[str] | None = None
        self._href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._depth += 1
            if self._depth == 1:
                self._rows = []
        if self._depth != 1:
            return
        if tag == "tr":
            self._cells, self._href = [], None
        elif tag in {"td", "th"} and self._cells is not None:
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")
        elif tag == "a" and self._cell is not None and self._href is None:
            self._href = dict(attrs).get("href")

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self._depth:
            if self._depth == 1 and self._rows is not None:
                self.tables.append(self._rows)
                self._rows = None
            self._depth -= 1
            return
        if self._depth != 1:
            return
        if tag in {"td", "th"} and self._cell is not None and self._cells is not None:
            self._cells.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._cells is not None and self._rows is not None:
            if any(self._cells):
                self._rows.append((self._cells, self._href))
            self._cells = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def _link(href: str | None) -> str | None:
    """Absolute https URL on ``oklahoma.gov`` for a documents PDF, else None."""
    if not href:
        return None
    absolute = urljoin(PAGE_URL, href.strip())
    parts = urlsplit(absolute)
    if (
        parts.scheme != "https"
        or (parts.hostname or "") != PAGE_HOST
        or parts.port not in (None, 443)
        or parts.username is not None
        or parts.query
        or parts.fragment
        or not _PDF_PATH.fullmatch(parts.path)
    ):
        return None
    return absolute


def _file_permit(url: str | None) -> str | None:
    if url is None:
        return None
    name = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
    match = _FILE_PERMIT.match(name)
    if match is None:
        return None
    return normalize_permit(" ".join(part for part in match.groups() if part))


def parse_page(body: bytes) -> list[dict[str, Any]]:
    """Rows of the issued/pending permits table (see ``parse_page_checked``)."""
    return parse_page_checked(body)[0]


def parse_page_checked(body: bytes) -> tuple[list[dict[str, Any]], int]:
    """Rows and the count of rows rejected for an overlong cell.

    Raises when the table is absent or its columns changed.
    """
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceParseError("Oklahoma DEQ data-center page is not UTF-8") from exc
    parser = _Table()
    parser.feed(text)
    table = next(
        (
            rows
            for rows in parser.tables
            if rows and [cell.upper() for cell in rows[0][0]] == _COLUMNS
        ),
        None,
    )
    if table is None:
        raise SourceParseError("Oklahoma DEQ data-center page table columns changed")
    result: list[dict[str, Any]] = []
    rejected = 0
    for cells, href in table[1:]:
        if len(cells) != len(_COLUMNS):
            raise SourceParseError("Oklahoma DEQ data-center page row has an unexpected shape")
        if any(len(cell) > MAX_CELL_CHARS for cell in cells):
            rejected += 1  # never store an overflowing cell; the row is counted and dropped
            continue
        row = dict(zip(_COLUMNS, cells, strict=True))
        link = _link(href)
        norm = _file_permit(link)
        result.append(
            {
                "division": row["DIV"],
                "county": row["COUNTY"],
                "company": row["COMPANY"],
                "facility": row["FACILITY"],
                "permit_type": row["PERMIT TYPE"],
                "status": row["STATUS"],
                "document_url": link,
                "permit_norm": norm,
                "permit_basis": "from link file name" if norm else None,
            }
        )
    if len(result) > MAX_ROWS:
        raise SourceParseError("Oklahoma DEQ data-center page row count exceeds its bound")
    return result, rejected


def page_blocks(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per permit join key, the deterministic block attached to a listing record."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row["permit_norm"]:
            grouped.setdefault(row["permit_norm"], []).append(row)
    blocks: dict[str, dict[str, Any]] = {}
    for norm, matches in grouped.items():
        body = {
            "source_url": PAGE_URL,
            "role": "discovery_and_supply_context",
            "rows": matches[:5],
            "note": (
                "Linked PDFs describe issued on-site generation permits: supply evidence, "
                "not demand. They are not read here."
            ),
        }
        body["digest"] = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        blocks[norm] = body
    return blocks
