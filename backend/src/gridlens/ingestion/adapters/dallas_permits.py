"""Bounded reader for the City of Dallas published monthly new-construction XLSX reports."""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit
from xml.etree import ElementTree as ET

import httpx
from bs4 import BeautifulSoup

from gridlens.ingestion.adapters.bounded_http import read_bounded_response
from gridlens.ingestion.adapters.federal_register import SourceParseError

INDEX = "https://dallascityhall.com/departments/sustainabledevelopment/Pages/Reports.aspx"
HOST = "dallascityhall.com"
HEADERS = (
    "Record Type",
    "Record ID",
    "Date Opened",
    "Permit Issued Date",
    "Address",
    "Type of Work",
    "Proposed Land Use",
    "Proposed Number of Dwelling Units",
    "Total Building Area (Gross Sq. Ft)",
    "Estimated Total Cost (Job Value)",
    "Contact Type",
    "Name",
    "LP Business Name",
    "Council District",
    "Base Zoning",
)
NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
MAX_XLSX_BYTES = 5_000_000
MAX_ROWS_PER_REPORT = 5000
MAX_REPORTS = 4


def _cell_value(cell: ET.Element, strings: list[str]) -> str:
    value = cell.find("x:v", NS)
    if value is None:
        return ""
    raw = value.text or ""
    if cell.get("t") == "s":
        return strings[int(raw)]
    if cell.get("t") == "inlineStr":
        inline = cell.find("x:is", NS)
        return "".join(inline.itertext()) if inline is not None else ""
    return raw


def _excel_date(value: str) -> date:
    try:
        return (datetime(1899, 12, 30) + timedelta(days=float(value))).date()
    except (ValueError, OverflowError) as exc:
        raise SourceParseError("Dallas report contains an invalid Excel date") from exc


def parse_report(body: bytes, url: str, *, report_month: date, today: date) -> list[dict[str, Any]]:
    """Parse the published sheet while retaining exact row identity and fields."""
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            entries = archive.infolist()
            if len(entries) > 100 or sum(entry.file_size for entry in entries) > 20_000_000:
                raise SourceParseError("Dallas report exceeds expanded workbook bounds")
            names = {entry.filename for entry in entries}
            if len(names) != len(entries) or "xl/worksheets/sheet1.xml" not in names:
                raise SourceParseError("Dallas workbook layout changed")
            strings = []
            if "xl/sharedStrings.xml" in names:
                root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                strings = ["".join(item.itertext()) for item in root.findall("x:si", NS)]
            sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        rows: list[list[str]] = []
        for row in sheet.findall(".//x:row", NS):
            values = [""] * len(HEADERS)
            for cell in row.findall("x:c", NS):
                ref = cell.get("r", "")
                match = re.fullmatch(r"([A-O])\d+", ref)
                if not match or cell.find("x:f", NS) is not None:
                    raise SourceParseError("Dallas report has an unexpected cell or formula")
                values[ord(match[1]) - ord("A")] = _cell_value(cell, strings)
            rows.append(values)
        if not 2 <= len(rows) <= MAX_ROWS_PER_REPORT + 1:
            raise SourceParseError("Dallas report row count is outside supported bounds")
        headers = tuple(" ".join(value.split()) for value in rows[0])
        if headers != HEADERS:
            raise SourceParseError("Dallas report columns changed")
        # The index report combines residential and commercial rows. This adapter's
        # declared coverage is strictly the official commercial new-construction rows.
        month_start = report_month.replace(day=1)
        next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        output: list[dict[str, Any]] = []
        seen: dict[str, tuple[str, ...]] = {}
        for sheet_row, values in enumerate(rows[1:], start=2):
            if not any(values):
                continue
            record_type, record_id = values[0].strip(), values[1].strip()
            if "Commercial New Construction Permit" not in record_type:
                continue
            if not record_id or not values[3] or not values[4].strip():
                raise SourceParseError(
                    "Dallas commercial permit row lacks identity, issue date or site"
                )
            issue_date = _excel_date(values[3])
            if issue_date < month_start or issue_date >= next_month or issue_date > today:
                raise SourceParseError("Dallas permit issue date disagrees with report month")
            key = record_id
            if key in seen:
                if seen[key] != tuple(values):
                    raise SourceParseError("Dallas report has conflicting duplicate permit IDs")
                continue
            seen[key] = tuple(values)
            fields = {
                "row": record_id,
                "project": record_id,
                "date": issue_date.isoformat(),
                "event": "issued",
                "type": record_type,
                "work": values[5].strip(),
                "description": "; ".join(
                    value
                    for value in (
                        record_type,
                        f"Proposed Land Use: {values[6].strip()}" if values[6].strip() else "",
                        f"Type of Work: {values[5].strip()}" if values[5].strip() else "",
                    )
                    if value
                ),
                "proposed_land_use": values[6].strip(),
                "address": values[4].strip(),
                "status": "Unknown",
                "contact_type": values[10].strip(),
                "applicant_full_name": values[11].strip(),
                "lp_business_name": values[12].strip(),
                "district": values[13].strip(),
                "area": values[8].strip(),
                "cost": values[9].strip(),
                "units": values[7].strip(),
                "zoning": values[14].strip(),
            }
            abstract = "\n".join(
                f"{key}: {value}"
                for key, value in (
                    ("row", fields["row"]),
                    ("project", fields["project"]),
                    ("date", fields["date"]),
                    ("event", "Issued"),
                    ("status", "Unknown"),
                    ("type", fields["type"]),
                    ("work", fields["work"]),
                    ("proposed_land_use", fields["proposed_land_use"]),
                    ("description", fields["description"]),
                    ("address", fields["address"]),
                    ("contact_type", fields["contact_type"]),
                    ("applicant_full_name", fields["applicant_full_name"]),
                    ("lp_business_name", fields["lp_business_name"]),
                    ("district", fields["district"]),
                    ("area", fields["area"]),
                    ("cost", fields["cost"]),
                    ("units", fields["units"]),
                    ("zoning", fields["zoning"]),
                )
                if value
            )
            digest = hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()
            output.append(
                {
                    "document_number": key,
                    "title": f"Dallas issued commercial new-construction permit {record_id}",
                    "abstract": abstract,
                    "publication_date": None,
                    "event_date": issue_date.isoformat(),
                    "event_date_label": "Permit Issued Date",
                    "html_url": url,
                    "extraction_location": (
                        f"Official Dallas monthly report {report_month:%B %Y}; "
                        f"worksheet row {sheet_row}"
                    ),
                    "source_hash": digest,
                    "permit": {
                        "source_type": "dallas-monthly-permits",
                        "city": "Dallas",
                        "state": "TX",
                        "address": fields["address"],
                        "description": fields["description"],
                        "type": fields["type"],
                        "work": fields["work"],
                        "proposed_land_use": fields["proposed_land_use"],
                        "status": "Unknown",
                        "issuance_event": "issued",
                        "class": "Commercial",
                        "cost": fields["cost"],
                        "area": fields["area"],
                        "project": record_id,
                        "row_id": record_id,
                        "applicant_role": fields["contact_type"],
                        "applicant_full_name": fields["applicant_full_name"],
                        "lp_business_name": fields["lp_business_name"],
                        "council_district": fields["district"],
                        "report_month": report_month.isoformat(),
                        "source_fields": {
                            "date": "Permit Issued Date",
                            "status": "Unknown",
                            "description": "Record Type + Proposed Land Use + Type of Work",
                            "lp_business_name": "LP Business Name (role unverified)",
                        },
                    },
                }
            )
        if not output:
            raise SourceParseError("Dallas monthly report has no commercial new-construction rows")
        return output
    except (ValueError, KeyError, IndexError, zipfile.BadZipFile, ET.ParseError) as exc:
        if isinstance(exc, SourceParseError):
            raise
        raise SourceParseError("Dallas monthly workbook parse failed") from exc


def retrieve(source: dict[str, Any], client: httpx.Client | None = None) -> list[dict[str, Any]]:
    if source.get("id") != "dallas-monthly-permits" or source.get("endpoint") != INDEX:
        raise SourceParseError("Dallas source is outside its reviewed reports page")
    http = client or httpx.Client(timeout=20, follow_redirects=False)
    today = datetime.now().date()
    try:
        _, body = read_bounded_response(http, INDEX, 2_000_000)
        reports: dict[date, str] = {}
        for anchor in BeautifulSoup(body, "html.parser").select("a[href]"):
            href = urljoin(INDEX, str(anchor["href"]))
            parsed = urlsplit(href)
            path = unquote(parsed.path)
            if not path.rsplit("/", 1)[-1].casefold().startswith("com-resnew"):
                continue
            match = re.search(r"MonthlyReports?(20\d{2})[-\s]+([A-Za-z]+)\.xlsx$", path, re.I)
            if not match:
                continue
            if (
                parsed.scheme != "https"
                or parsed.hostname != HOST
                or parsed.query
                or parsed.fragment
            ):
                raise SourceParseError("Dallas report link is outside its reviewed official host")
            try:
                try:
                    month = datetime.strptime(match[2], "%b").month
                except ValueError:
                    month = datetime.strptime(match[2], "%B").month
            except ValueError as exc:
                raise SourceParseError(
                    "Dallas monthly report filename has an unknown month"
                ) from exc
            report_month = date(int(match[1]), month, 1)
            prior_link = reports.get(report_month)
            if prior_link is not None and prior_link != href:
                raise SourceParseError("Dallas page has conflicting report links for a month")
            reports[report_month] = href
        chosen = sorted(reports, reverse=True)[:MAX_REPORTS]
        if not chosen or (today - chosen[0]).days > 90:
            raise SourceParseError("Dallas latest linked report is missing or over 90 days old")
        all_records: dict[str, dict[str, Any]] = {}
        for report_month in reversed(chosen):
            report_url = reports[report_month]
            _, workbook = read_bounded_response(http, report_url, MAX_XLSX_BYTES)
            for record in parse_report(
                workbook, report_url, report_month=report_month, today=today
            ):
                prior_record = all_records.get(record["document_number"])
                if prior_record and prior_record["source_hash"] != record["source_hash"]:
                    # The report is a snapshot that can revise the same permit.
                    # Keep the version with the latest report month; ingestion's
                    # evidence-version store preserves prior report citations.
                    if date.fromisoformat(record["permit"]["report_month"]) > date.fromisoformat(
                        prior_record["permit"]["report_month"]
                    ):
                        all_records[record["document_number"]] = record
                else:
                    all_records[record["document_number"]] = record
        return list(all_records.values())
    finally:
        if client is None:
            http.close()
