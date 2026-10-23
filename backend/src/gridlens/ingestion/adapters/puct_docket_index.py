"""PUCT Interchange docket index for large-load and data-center case styles.

The electric case-style search for "large load" and "data center" returns a
short docket list. Each search page is checked against its Excel export.
An unbounded certificate-of-convenience search is not this source.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from html import unescape
from io import BytesIO
from typing import Any
from urllib.parse import quote, urlencode
from xml.etree import ElementTree as ET

import httpx

from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.power_signals import power_signal_tags
from gridlens.ingestion.adapters.public_source_http import read_public_response

SOURCE_ID = "texas-puct-large-load-dockets"
SEARCH_URL = "https://interchange.puc.texas.gov/search/search/?UtilityType=E&ItemMatch=1&DocumentType=ALL&Description=large%20load"
DESCRIPTIONS = ("large load", "data center")
MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ALLOWED_HOSTS = frozenset({"interchange.puc.texas.gov"})
MAX_RESPONSE_BYTES = 2_000_000
MAX_RECORDS = 40
_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_HEADER = ("Control #", "Filings", "Utility", "Description (Case Style)")
_PLACE = re.compile(
    r"\b([A-Z][A-Za-z.'-]*(?:\s+[A-Z][A-Za-z.'-]*){0,3}),\s*(TX|Texas)\b"
    r"|\blocated in ([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){0,3})\s+Texas\b",
    re.IGNORECASE,
)
_DATA_CENTER = re.compile(r"data\s*cent(?:er|re)|hyperscale", re.IGNORECASE)


def _query(description: str) -> str:
    return urlencode(
        {
            "UtilityType": "E",
            "ItemMatch": "1",
            "DocumentType": "ALL",
            "Description": description,
        },
        quote_via=quote,
    )


def _search_url(description: str) -> str:
    return "https://interchange.puc.texas.gov/search/search/?" + _query(description)


def _export_url(description: str) -> str:
    return "https://interchange.puc.texas.gov/search/exportdockets/?" + urlencode(
        {
            "UtilityType": "E",
            "ItemMatch": "Equal",
            "DocumentType": "ALL",
            "Description": description,
            "SortBy": "ControlNumber",
            "SortOrder": "Ascending",
        },
        quote_via=quote,
    )


def _plain(value: str) -> str:
    return " ".join(unescape(value).split())


def _strings(book: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in book.namelist():
        return []
    root = ET.fromstring(book.read("xl/sharedStrings.xml"))
    return [
        "".join(node.text or "" for node in item.findall(".//m:t", _NS))
        for item in root.findall("m:si", _NS)
    ]


def _cell(cell: ET.Element, strings: list[str]) -> str:
    kind = cell.get("t")
    if kind == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//m:t", _NS)).strip()
    node = cell.find("m:v", _NS)
    if node is None or node.text is None:
        return ""
    if kind == "s":
        return strings[int(node.text)].strip()
    return node.text.strip()


def parse_export(body: bytes) -> list[dict[str, str]]:
    try:
        book = zipfile.ZipFile(BytesIO(body))
    except zipfile.BadZipFile as exc:
        raise SourceParseError("PUCT docket export is not an Excel workbook") from exc
    if "xl/worksheets/sheet1.xml" not in book.namelist():
        raise SourceParseError("PUCT docket export has no worksheet")
    strings = _strings(book)
    sheet = ET.fromstring(book.read("xl/worksheets/sheet1.xml"))
    parsed: list[list[str]] = []
    for row in sheet.findall("m:sheetData/m:row", _NS):
        cells: dict[str, str] = {}
        for cell in row.findall("m:c", _NS):
            column = "".join(char for char in (cell.get("r") or "") if char.isalpha())
            cells[column] = _cell(cell, strings)
        parsed.append([cells.get(column, "") for column in "ABCD"])
    if not parsed or tuple(parsed[0]) != _HEADER:
        raise SourceParseError("PUCT docket export columns changed")
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for control, filings, utility, description in parsed[1:]:
        control = control.strip()
        if not control.isdigit() or control in seen:
            raise SourceParseError("PUCT docket export control number is invalid or repeated")
        if not filings.isdigit() or not utility.strip() or not description.strip():
            raise SourceParseError("PUCT docket export row is missing filings, utility, or style")
        seen.add(control)
        rows.append(
            {
                "control": control,
                "filings": filings,
                "utility": _plain(utility),
                "description": _plain(description),
            }
        )
    return rows


def parse_search(body: bytes) -> list[dict[str, str]]:
    text = body.decode("utf-8", errors="replace")
    declared = re.search(r"(\d+) record\(s\) found", text)
    if not declared:
        raise SourceParseError("PUCT docket search did not state a record count")
    rows: list[dict[str, str]] = []
    for row in re.findall(r"<tr>([\s\S]*?)</tr>", text, re.IGNORECASE):
        control = re.search(r"ControlNumber=(\d+)", row)
        if not control:
            continue
        cells = [
            _plain(re.sub(r"<[^>]+>", " ", cell))
            for cell in re.findall(r"<td[^>]*>([\s\S]*?)</td>", row, re.IGNORECASE)
        ]
        if len(cells) != 4:
            raise SourceParseError("PUCT docket search row has an unexpected column count")
        rows.append(
            {
                "control": control.group(1),
                "filings": cells[1],
                "utility": cells[2],
                "description": cells[3],
            }
        )
    if len(rows) != int(declared.group(1)):
        raise SourceParseError("PUCT docket search count does not match its rows")
    return rows


def _location(text: str) -> str | None:
    found: list[str] = []
    for city, state, located in _PLACE.findall(text):
        name = city or located
        rendered = f"{name}, TX" if not state or state.casefold() == "texas" else f"{name}, {state}"
        if rendered not in found:
            found.append(rendered)
    return "; ".join(found) or None


def _record(row: dict[str, str], *, description_query: str) -> dict[str, Any]:
    text = f"{row['utility']} {row['description']}"
    tags = power_signal_tags(text)
    row_id = f"PUCT-DOCKET-{row['control']}"
    semantic = {**row, "description_query": description_query, "power_signals": tags}
    return {
        "document_number": row_id,
        "title": f"PUCT {row['control']} — {row['utility']}",
        "abstract": "\n".join(
            [
                f"Control number: {row['control']}",
                f"Case style: {row['description']}",
                f"Utility: {row['utility']}",
                f"Filings on the docket index: {row['filings']}",
                f"Case-style query: {description_query}",
                "Project site: not stated in the case style"
                if _location(text) is None
                else f"Place named in the case style: {_location(text)}",
                f"Power signal tags: {', '.join(tags) or 'none'}",
            ]
        ),
        "publication_date": None,
        "event_date": None,
        "event_date_label": None,
        "html_url": (
            "https://interchange.puc.texas.gov/Search/Filings?ControlNumber=" + row["control"]
        ),
        "extraction_location": "PUCT Interchange docket search and Excel export",
        "source_hash": hashlib.sha256(
            json.dumps(semantic, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "permit": {
            "source_type": SOURCE_ID,
            "row_id": row_id,
            "applicant": row["utility"],
            "facility": row["description"],
            "permit_numbers": [row_id],
            "permit_type": "PUCT interchange docket",
            "status": None,
            "description": row["description"],
            "location": _location(text),
            "state": "TX" if _location(text) else None,
            "data_center": bool(_DATA_CENTER.search(text)),
            "power_signals": tags,
            "document_links": {
                "PUCT filings": (
                    "https://interchange.puc.texas.gov/Search/Filings?ControlNumber="
                    + row["control"]
                )
            },
            "source_fields": {
                "applicant": "Utility",
                "facility": "Description (Case Style)",
                "location": "place named in the case style, when stated",
            },
        },
    }


def retrieve(source: dict[str, Any], client: httpx.Client | None = None) -> list[dict[str, Any]]:
    if source.get("id") != SOURCE_ID or source.get("endpoint") != SEARCH_URL:
        raise SourceParseError("PUCT docket source ID or endpoint is not configured")
    query = source.get("query", {})
    if (
        query.get("max_response_bytes") != MAX_RESPONSE_BYTES
        or query.get("max_records") != MAX_RECORDS
        or tuple(query.get("descriptions") or ()) != DESCRIPTIONS
    ):
        raise SourceParseError("PUCT docket query bounds are invalid")
    http = client or httpx.Client(timeout=60, follow_redirects=False, trust_env=False)
    try:
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        for description in DESCRIPTIONS:
            _, page = read_public_response(
                http,
                _search_url(description),
                max_bytes=MAX_RESPONSE_BYTES,
                allowed_media_types={"text/html"},
                allowed_hosts=ALLOWED_HOSTS,
            )
            _, workbook = read_public_response(
                http,
                _export_url(description),
                max_bytes=MAX_RESPONSE_BYTES,
                allowed_media_types={MEDIA_TYPE},
                allowed_hosts=ALLOWED_HOSTS,
            )
            listed = parse_search(page)
            exported = parse_export(workbook)
            if listed != exported:
                raise SourceParseError("PUCT docket search and Excel export disagree")
            for row in exported:
                if row["control"] in seen:
                    raise SourceParseError("PUCT docket control number was returned twice")
                seen.add(row["control"])
                records.append(_record(row, description_query=description))
        if len(records) > MAX_RECORDS:
            raise SourceParseError("PUCT docket count exceeds its bound")
        return records
    finally:
        if client is None:
            http.close()
