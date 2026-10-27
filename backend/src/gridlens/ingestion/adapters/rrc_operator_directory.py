"""Bounded, source-native retrieval of RRC P5 organization phone listings.

This adapter follows the official RRC operator contact page to one current
same-host XLSX file. It preserves the published source row and distinguishes
the organization's normal phone field from the separate emergency field.
"""

from __future__ import annotations

import copy
import hashlib
import io
import ipaddress
import posixpath
import re
import socket
import threading
import time
import zipfile
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree as ET

import httpx
from bs4 import BeautifulSoup

from gridlens.ingestion.adapters.bounded_http import read_bounded_response, run_isolated
from gridlens.ingestion.adapters.buying_chain_public import validate_public_url

INDEX_URL = (
    "https://www.rrc.texas.gov/oil-and-gas/research-and-statistics/"
    "operator-information/oil-gas-directory-operator-contact/"
)
HOST = "www.rrc.texas.gov"
MAX_INDEX_BYTES = 250_000
MAX_XLSX_BYTES = 2_000_000
MAX_ZIP_ENTRIES = 100
MAX_EXPANDED_BYTES = 25_000_000
MAX_ROWS = 20_000
CACHE_TTL_SECONDS = 24 * 60 * 60
_FILE_PATH = re.compile(
    r"^/media/[a-z0-9]+/oil-and-gas-directory-(\d{2}-\d{2}-\d{2})\.xlsx$",
    re.I,
)
_INDEX_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_HEADER = (
    "Org Number",
    "Org Name",
    "",
    "First Address Line",
    "Second Address Line",
    "Apt/Suite and #",
    "City",
    "State",
    "Zip",
    "Country",
    "Phone",
    "Emergency",
    "Mail Ret'd by PO",
    "P5 Status",
)
_STATUSES = frozenset(
    {"Active", "ActiveExtension", "ActiveHearing", "Delinquent", "Revoked", "SeeRemarks"}
)

_cache_lock = threading.Lock()
_cached_snapshot: dict | None = None
_cached_at: float | None = None


def _validated_directory_url(url: str) -> str:
    normalized = validate_public_url(url)
    parsed = urlsplit(normalized)
    if parsed.hostname != HOST or parsed.port not in (None, 443) or parsed.query or parsed.fragment:
        raise ValueError("RRC directory URL is outside the fixed official origin")
    return normalized


def select_directory_link(html: bytes, index_url: str = INDEX_URL) -> dict[str, str | None]:
    """Select the unique latest dated XLSX link from the exact official page."""
    _validated_directory_url(index_url)
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    page_text = " ".join(soup.get_text(" ", strip=True).split())
    if (
        not re.search(r"Oil\s*&\s*Gas Directory", title, re.I)
        or "Railroad Commission of Texas" not in page_text
    ):
        raise ValueError("Official RRC operator directory page identity changed")
    candidates: dict[str, tuple[str, str]] = {}
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href")
        if not isinstance(href, str):
            continue
        absolute = urljoin(index_url, href)
        try:
            absolute = _validated_directory_url(absolute)
        except ValueError:
            continue
        match = _FILE_PATH.fullmatch(urlsplit(absolute).path)
        if not match:
            continue
        try:
            file_date = datetime.strptime(match.group(1), "%m-%d-%y").date()
        except ValueError:
            continue
        label = anchor.get_text(" ", strip=True).casefold()
        if "excel" not in label and not urlsplit(absolute).path.casefold().endswith(".xlsx"):
            continue
        candidates[absolute] = (file_date.isoformat(), label)
    if not candidates:
        raise ValueError("Official RRC page lists no supported dated Excel directory")
    if len(candidates) != 1:
        raise ValueError("Official RRC page has ambiguous dated Excel directory links")
    selected_url, (filename_date, _label) = next(iter(candidates.items()))
    freshness_statement = _landing_freshness_statement(soup.get_text(" ", strip=True))
    return {
        "url": selected_url,
        "filename_date": filename_date,
        "landing_freshness_statement": freshness_statement,
    }


def _landing_freshness_statement(text: str) -> str | None:
    normalized = " ".join(text.split())
    patterns = (
        r"information available in this query is updated [^.]{1,80}\.",
        r"these downloadable files contain data as of [A-Za-z]+ \d{1,2}(?:st|nd|rd|th)?,? \d{4}\.?",
        r"(?:last )?updated (?:as of )?[A-Za-z]+ \d{1,2}(?:st|nd|rd|th)?,? \d{4}",
    )
    statements = [
        match.group(0)
        for pattern in patterns
        if (match := re.search(pattern, normalized, re.I)) is not None
    ]
    return " ; ".join(statements) if statements else None


def _cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    if cell.find(f"{{{_INDEX_NS}}}f") is not None:
        raise ValueError("RRC directory workbook contains a formula cell")
    kind = cell.get("t")
    if kind == "inlineStr":
        inline = cell.find(f"{{{_INDEX_NS}}}is")
        return "".join(inline.itertext()) if inline is not None else ""
    value = cell.find(f"{{{_INDEX_NS}}}v")
    raw = value.text if value is not None and value.text else ""
    if kind == "s":
        try:
            return shared_strings[int(raw)]
        except (ValueError, IndexError) as exc:
            raise ValueError("RRC directory workbook has an invalid shared string") from exc
    return raw


def _worksheet_path(archive: zipfile.ZipFile) -> str:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    sheets = workbook.findall(f"{{{_INDEX_NS}}}sheets/{{{_INDEX_NS}}}sheet")
    if len(sheets) != 1:
        raise ValueError("RRC workbook must contain exactly one worksheet")
    relationship_id = sheets[0].get(f"{{{_REL_NS}}}id")
    if not relationship_id:
        raise ValueError("RRC workbook worksheet relationship is missing")
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = [
        row.get("Target")
        for row in relationships.findall(f"{{{_PKG_REL_NS}}}Relationship")
        if row.get("Id") == relationship_id
    ]
    if len(targets) != 1 or not targets[0]:
        raise ValueError("RRC workbook worksheet target is ambiguous")
    raw_target = targets[0]
    target = (
        posixpath.normpath(raw_target.lstrip("/"))
        if raw_target.startswith("/")
        else posixpath.normpath(posixpath.join("xl", raw_target))
    )
    if target != "xl/worksheets/sheet1.xml":
        raise ValueError("RRC workbook worksheet path changed")
    return target


def parse_directory_workbook(body: bytes, source_url: str, observed_at: datetime) -> dict:
    """Parse the bounded P5 workbook and retain exact rows plus raw-artifact identity."""
    source_url = _validated_directory_url(source_url)
    filename_match = _FILE_PATH.fullmatch(urlsplit(source_url).path)
    if not filename_match:
        raise ValueError("RRC directory workbook URL has an unsupported filename")
    filename_date = datetime.strptime(filename_match.group(1), "%m-%d-%y").date()
    if not body or len(body) > MAX_XLSX_BYTES:
        raise ValueError("RRC directory workbook is empty or exceeds the byte bound")
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if (
                len(entries) > MAX_ZIP_ENTRIES
                or len(names) != len(set(names))
                or any(".." in name.split("/") or "\\" in name for name in names)
                or sum(entry.file_size for entry in entries) > MAX_EXPANDED_BYTES
                or "xl/workbook.xml" not in names
                or "xl/_rels/workbook.xml.rels" not in names
            ):
                raise ValueError("RRC directory workbook exceeds archive bounds or layout")
            shared_strings: list[str] = []
            if "xl/sharedStrings.xml" in names:
                shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                shared_strings = [
                    "".join(item.itertext()) for item in shared_root.findall(f"{{{_INDEX_NS}}}si")
                ]
            sheet_root = ET.fromstring(archive.read(_worksheet_path(archive)))
    except (zipfile.BadZipFile, ET.ParseError, KeyError, OSError) as exc:
        raise ValueError("RRC directory workbook could not be parsed safely") from exc

    sheet_data = sheet_root.find(f"{{{_INDEX_NS}}}sheetData")
    rows = list(sheet_data) if sheet_data is not None else []
    if not 4 <= len(rows) <= MAX_ROWS + 3:
        raise ValueError("RRC directory workbook row count is outside supported bounds")
    parsed_rows: dict[int, list[str]] = {}
    for row in rows:
        row_number = row.get("r")
        if not row_number or not row_number.isdecimal():
            raise ValueError("RRC directory workbook contains an invalid row number")
        number = int(row_number)
        if number in parsed_rows:
            raise ValueError("RRC directory workbook contains duplicate row numbers")
        values = [""] * len(_HEADER)
        for cell in row:
            reference = cell.get("r", "")
            match = re.fullmatch(r"([A-N])(\d+)", reference)
            if not match or int(match.group(2)) != number:
                raise ValueError("RRC directory workbook contains an unexpected cell")
            values[ord(match.group(1)) - ord("A")] = _cell_value(cell, shared_strings)
        parsed_rows[number] = values
    header_rows = [number for number, values in parsed_rows.items() if tuple(values) == _HEADER]
    if header_rows != [3]:
        raise ValueError("RRC directory workbook headers changed")

    header_timestamp = parsed_rows.get(1, [""])[0].strip()
    try:
        header_datetime = datetime.strptime(header_timestamp, "%m/%d/%Y %I:%M:%S %p")
    except ValueError as exc:
        raise ValueError("RRC directory workbook header timestamp changed") from exc
    operators: dict[str, list[dict[str, str | int]]] = {}
    for row_number in sorted(parsed_rows):
        if row_number <= 3:
            continue
        values = parsed_rows[row_number]
        if not any(values):
            continue
        operator_number, organization = values[0].strip(), values[1].strip()
        if not operator_number:
            # Some RRC contact rows are not assigned operator numbers; they
            # cannot be safely joined to this company identity and are skipped.
            continue
        if not re.fullmatch(r"\d{6}", operator_number) or not organization:
            raise ValueError("RRC directory workbook contains a malformed operator identity")
        status = values[13].strip()
        if status not in _STATUSES:
            raise ValueError("RRC directory workbook contains an unsupported P5 status")
        row = {
            "operator_number": operator_number,
            "organization": organization,
            "normal_phone": values[10].strip(),
            "status": status,
            "row_number": row_number,
        }
        operators.setdefault(operator_number, []).append(row)

    stamp = (
        observed_at.replace(tzinfo=UTC)
        if observed_at.tzinfo is None
        else observed_at.astimezone(UTC)
    )
    return {
        "index_url": INDEX_URL,
        "source_url": source_url,
        "filename_date": filename_date.isoformat(),
        "workbook_header_timestamp": header_timestamp,
        "workbook_header_date": header_datetime.date().isoformat(),
        "landing_freshness_statement": None,
        "observed_at": stamp.isoformat(),
        "raw_sha256": hashlib.sha256(body).hexdigest(),
        "operators": operators,
    }


def _public_ip(host: str) -> str:
    answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    addresses = sorted({str(answer[4][0]) for answer in answers})
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("RRC directory host does not resolve exclusively to public addresses")
    return addresses[0]


def _get_pinned(url: str, max_bytes: int, deadline: float) -> tuple[httpx.Headers, bytes]:
    url = _validated_directory_url(url)
    host = urlsplit(url).hostname
    assert host is not None
    address = _public_ip(host)
    remaining = min(deadline - time.monotonic(), 25.0)
    if remaining <= 0:
        raise TimeoutError("RRC directory retrieval deadline exhausted")
    pinned = httpx.URL(url).copy_with(host=address)
    with httpx.Client(
        timeout=httpx.Timeout(min(7.0, remaining)),
        follow_redirects=False,
        trust_env=False,
        headers={"Host": host, "User-Agent": "GridLens public source research/1.0"},
    ) as client:
        return read_bounded_response(
            client,
            str(pinned),
            max_bytes,
            extensions={"sni_hostname": host},
            deadline=deadline,
        )


def _retrieve_directory_direct() -> dict:
    deadline = time.monotonic() + 25
    headers, html = _get_pinned(INDEX_URL, MAX_INDEX_BYTES, deadline)
    if "html" not in headers.get("content-type", "").casefold():
        raise ValueError("Official RRC operator page did not return HTML")
    selected = select_directory_link(html)
    headers, workbook = _get_pinned(str(selected["url"]), MAX_XLSX_BYTES, deadline)
    content_type = headers.get("content-type", "").casefold()
    if "spreadsheet" not in content_type and "octet-stream" not in content_type:
        raise ValueError("Official RRC directory link did not return an XLSX document")
    snapshot = parse_directory_workbook(workbook, str(selected["url"]), datetime.now(UTC))
    snapshot["landing_freshness_statement"] = selected["landing_freshness_statement"]
    return snapshot


def load_current_directory(*, deadline: float) -> dict:
    """Return an immutable-source snapshot cached for at most 24 hours.

    Cache reads retain the original source observation time; reuse never marks
    a prior download as freshly retrieved.
    """
    global _cached_at, _cached_snapshot
    remaining = deadline - time.monotonic()
    if remaining <= 0 or not _cache_lock.acquire(timeout=remaining):
        raise TimeoutError("RRC directory cache deadline exhausted")
    try:
        if (
            _cached_snapshot is not None
            and _cached_at is not None
            and time.monotonic() - _cached_at < CACHE_TTL_SECONDS
        ):
            return copy.deepcopy(_cached_snapshot)
        snapshot = run_isolated(
            "gridlens.ingestion.adapters.rrc_operator_directory:_retrieve_directory_direct",
            (),
            {},
            deadline=deadline,
        )
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("operators"), dict):
            raise ValueError("RRC directory retrieval returned an invalid snapshot")
        _cached_snapshot = snapshot
        _cached_at = time.monotonic()
        return copy.deepcopy(snapshot)
    finally:
        _cache_lock.release()


def _reset_cache_for_tests() -> None:
    """Clear in-process snapshot state for isolated deterministic tests."""
    global _cached_at, _cached_snapshot
    with _cache_lock:
        _cached_snapshot = None
        _cached_at = None
