"""PUCT Interchange filings for the large-load projects.

Project 59142 is the review of ERCOT large-load interconnection, and project
58481 is the large-load rulemaking. The machine-readable access is the Excel
export linked from each filings page. A filing is not given a Texas location
unless its own text names a place. Comments without a site stay evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from datetime import datetime, timedelta
from html import unescape
from io import BytesIO
from typing import Any
from xml.etree import ElementTree as ET

import httpx

from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.power_signals import power_signal_tags
from gridlens.ingestion.adapters.public_source_http import read_public_response

SOURCE_ID = "texas-puct-large-load-filings"
FILINGS_URL = "https://interchange.puc.texas.gov/Search/Filings?ControlNumber=59142"
FILINGS_PAGE = "https://interchange.puc.texas.gov/Search/Filings?ControlNumber={control}"
EXPORT_URL = (
    "https://interchange.puc.texas.gov/search/exportfilings/"
    "?ControlNumber={control}&ItemMatch=0&SortBy=ItemNumber&SortOrder=Ascending"
)
ITEM_URL = (
    "https://interchange.puc.texas.gov/search/documents/?controlNumber={control}&itemNumber={item}"
)
MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ALLOWED_HOSTS = frozenset({"interchange.puc.texas.gov"})
CONTROL_NUMBERS = (59142, 58481)
MAX_RESPONSE_BYTES = 2_000_000
MAX_RECORDS = 500
_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_HEADER = ("Control #", "Item #", "File Stamp", "Filing Party", "Filing Description")
_PLACE = re.compile(r"\b([A-Z][A-Za-z.'-]*(?:\s+[A-Z][A-Za-z.'-]*){0,3}),\s*(TX|Texas)\b")
_DATA_CENTER = re.compile(r"data\s*cent(?:er|re)|hyperscale", re.IGNORECASE)
_EXCEL_EPOCH = datetime(1899, 12, 30)


def _strings(book: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in book.namelist():
        return []
    root = ET.fromstring(book.read("xl/sharedStrings.xml"))
    values: list[str] = []
    for item in root.findall("m:si", _NS):
        values.append("".join(node.text or "" for node in item.findall(".//m:t", _NS)))
    return values


def _cell(cell: ET.Element, strings: list[str]) -> str:
    kind = cell.get("t")
    if kind == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//m:t", _NS)).strip()
    node = cell.find("m:v", _NS)
    if node is None or node.text is None:
        return ""
    if kind == "s":
        try:
            return strings[int(node.text)].strip()
        except (ValueError, IndexError) as exc:
            raise SourceParseError("PUCT workbook string index is invalid") from exc
    return node.text.strip()


def _column(ref: str) -> str:
    return "".join(char for char in ref if char.isalpha())


def _stamp(value: str) -> str:
    try:
        serial = int(value)
    except ValueError as exc:
        raise SourceParseError("PUCT file stamp is not an Excel date") from exc
    if serial < 30000 or serial > 80000:
        raise SourceParseError("PUCT file stamp is outside the expected date range")
    return (_EXCEL_EPOCH + timedelta(days=serial)).date().isoformat()


def _location(text: str) -> str | None:
    found: list[str] = []
    for city, state in _PLACE.findall(text):
        rendered = f"{city}, TX" if state.casefold() == "texas" else f"{city}, {state}"
        if rendered not in found:
            found.append(rendered)
    if not found:
        return None
    return "; ".join(found)


def _plain(value: str) -> str:
    return " ".join(unescape(value).split())


def parse_filings_page(body: bytes, *, control_number: int) -> dict[str, dict[str, str]]:
    """Item, party, description, and file date from the server-rendered filings list."""
    text = body.decode("utf-8", errors="replace")
    pager = re.search(r'<li class="([^"]*PagedList-skipToNext[^"]*)"', text)
    if pager and "disabled" not in pager.group(1):
        raise SourceParseError("PUCT filings list continues on another page")
    rows: dict[str, dict[str, str]] = {}
    pattern = re.compile(
        rf'controlNumber={control_number}&amp;itemNumber=(\d+)"[^>]*>\s*\1\s*</a>([\s\S]*?)</tr>',
        re.IGNORECASE,
    )
    for item, rest in pattern.findall(text):
        cells = [
            _plain(re.sub(r"<[^>]+>", " ", cell))
            for cell in re.findall(r"<td[^>]*>([\s\S]*?)</td>", rest, re.IGNORECASE)
        ]
        if len(cells) < 4:
            raise SourceParseError("PUCT filings list row is missing columns")
        filed, party, _item_type, description = cells[:4]
        if item in rows:
            raise SourceParseError("PUCT filings list has a duplicate item")
        try:
            filed_iso = datetime.strptime(filed, "%m/%d/%Y").date().isoformat()
        except ValueError as exc:
            raise SourceParseError("PUCT filings list date is malformed") from exc
        if not party or not description:
            raise SourceParseError("PUCT filings list row is missing party or description")
        rows[item] = {"party": party, "description": description, "event_date": filed_iso}
    if not rows:
        raise SourceParseError("PUCT filings list has no items")
    return rows


def filings_match_export(page: dict[str, dict[str, str]], rows: list[dict[str, Any]]) -> None:
    exported = {row["item"]: row for row in rows}
    if set(page) != set(exported):
        raise SourceParseError("PUCT filings list and Excel export item numbers differ")
    for item, filing in page.items():
        row = exported[item]
        if (
            filing["party"] != _plain(row["party"])
            or filing["description"] != _plain(row["description"])
            or filing["event_date"] != row["event_date"]
        ):
            raise SourceParseError("PUCT filings list and Excel export disagree on a filing")


def parse_export(body: bytes, *, control_number: int) -> list[dict[str, Any]]:
    try:
        book = zipfile.ZipFile(BytesIO(body))
    except zipfile.BadZipFile as exc:
        raise SourceParseError("PUCT export is not an Excel workbook") from exc
    if "xl/worksheets/sheet1.xml" not in book.namelist():
        raise SourceParseError("PUCT export has no worksheet")
    strings = _strings(book)
    sheet = ET.fromstring(book.read("xl/worksheets/sheet1.xml"))
    parsed: list[list[str]] = []
    for row in sheet.findall("m:sheetData/m:row", _NS):
        cells: dict[str, str] = {}
        for cell in row.findall("m:c", _NS):
            ref = cell.get("r") or ""
            cells[_column(ref)] = _cell(cell, strings)
        parsed.append([cells.get(column, "") for column in "ABCDE"])
    if not parsed or tuple(parsed[0]) != _HEADER:
        raise SourceParseError("PUCT export columns changed")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for values in parsed[1:]:
        control, item, stamp, party, description = values
        if control != str(control_number):
            raise SourceParseError("PUCT export control number does not match the request")
        if not item.isdigit() or not party or not description:
            raise SourceParseError("PUCT export row is missing item, party, or description")
        identity = f"{control}-{item}"
        if identity in seen:
            raise SourceParseError("PUCT export has a duplicate filing item")
        seen.add(identity)
        text = f"{party} {description}"
        rows.append(
            {
                "control": control,
                "item": item,
                "event_date": _stamp(stamp),
                "party": party,
                "description": description,
                "location": _location(text),
                "tags": power_signal_tags(text),
                "data_center": bool(_DATA_CENTER.search(text)),
                "html_url": ITEM_URL.format(control=control, item=item),
            }
        )
    return rows


def _record(row: dict[str, Any]) -> dict[str, Any]:
    row_id = f"PUCT-{row['control']}-{row['item']}"
    semantic = {key: row[key] for key in row if key != "tags"}
    semantic["power_signals"] = row["tags"]
    return {
        "document_number": row_id,
        "title": f"PUCT {row['control']} item {row['item']} — {row['party']}",
        "abstract": "\n".join(
            [
                f"Control number: {row['control']}",
                f"Item: {row['item']}",
                f"Filing party: {row['party']}",
                f"File stamp: {row['event_date']}",
                f"Description: {row['description']}",
                "Project site: not stated in this filing"
                if row["location"] is None
                else f"Place named in the filing: {row['location']}",
                f"Power signal tags: {', '.join(row['tags']) or 'none'}",
            ]
        ),
        "publication_date": None,
        "event_date": row["event_date"],
        "event_date_label": "PUCT file stamp",
        "html_url": row["html_url"],
        "extraction_location": "PUCT Interchange filing export",
        "source_hash": hashlib.sha256(
            json.dumps(semantic, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "permit": {
            "source_type": SOURCE_ID,
            "row_id": row_id,
            "applicant": row["party"],
            "facility": row["description"],
            "permit_numbers": [row_id],
            "permit_type": "PUCT interchange filing",
            "status": None,
            "description": row["description"],
            "location": row["location"],
            "state": "TX" if row["location"] else None,
            "data_center": row["data_center"],
            "power_signals": row["tags"],
            "document_links": {"PUCT filing": row["html_url"]},
            "source_fields": {
                "applicant": "Filing Party",
                "facility": "Filing Description",
                "location": "place named in the filing text, when stated",
                "event_date": "File Stamp",
            },
        },
    }


def retrieve(source: dict[str, Any], client: httpx.Client | None = None) -> list[dict[str, Any]]:
    if source.get("id") != SOURCE_ID or source.get("endpoint") != FILINGS_URL:
        raise SourceParseError("PUCT source ID or endpoint is not configured")
    query = source.get("query", {})
    if (
        query.get("max_response_bytes") != MAX_RESPONSE_BYTES
        or query.get("max_records") != MAX_RECORDS
        or tuple(query.get("control_numbers") or ()) != CONTROL_NUMBERS
    ):
        raise SourceParseError("PUCT query bounds are invalid")
    http = client or httpx.Client(timeout=60, follow_redirects=False, trust_env=False)
    try:
        records: list[dict[str, Any]] = []
        for control in CONTROL_NUMBERS:
            _, listing = read_public_response(
                http,
                FILINGS_PAGE.format(control=control),
                max_bytes=MAX_RESPONSE_BYTES,
                allowed_media_types={"text/html"},
                allowed_hosts=ALLOWED_HOSTS,
            )
            _, body = read_public_response(
                http,
                EXPORT_URL.format(control=control),
                max_bytes=MAX_RESPONSE_BYTES,
                allowed_media_types={MEDIA_TYPE},
                allowed_hosts=ALLOWED_HOSTS,
            )
            rows = parse_export(body, control_number=control)
            filings_match_export(parse_filings_page(listing, control_number=control), rows)
            records.extend(_record(row) for row in rows)
        if len(records) > MAX_RECORDS:
            raise SourceParseError("PUCT filing count exceeds its bound")
        return records
    finally:
        if client is None:
            http.close()
