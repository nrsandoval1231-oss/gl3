"""Official weekly Houston report snapshots; not the complete sold-permit history."""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit
from xml.etree import ElementTree as ET

import httpx
from bs4 import BeautifulSoup
from openpyxl.utils.datetime import MAC_EPOCH, WINDOWS_EPOCH, from_excel

from gridlens.ingestion.adapters.bounded_http import read_bounded_response
from gridlens.ingestion.adapters.federal_register import SourceParseError

INDEX = "https://www.houstonpermittingcenter.org/sold-permits-search"
HOST = "www.houstonpermittingcenter.org"
NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
HEADERS = ["Zip Code", "Permit Date", "Permit Type", "Project No", "Address", "Comments"]


def _permit_date(value: str, epoch: datetime) -> date:
    try:
        return datetime.strptime(value, "%Y/%m/%d").date()
    except ValueError as exc:
        if not re.fullmatch(r"\d{1,6}", value):
            raise SourceParseError("Houston permit date is malformed") from exc
        try:
            converted = from_excel(int(value), epoch=epoch)
        except (OverflowError, TypeError, ValueError) as exc:
            raise SourceParseError("Houston permit serial date is invalid") from exc
        if not isinstance(converted, datetime):
            raise SourceParseError("Houston permit serial date is invalid") from None
        return converted.date()


def parse_report(
    body: bytes,
    url: str,
    *,
    today: date,
    listed_week_start: date | None = None,
) -> tuple[date, list[dict[str, Any]]]:
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            entries = archive.infolist()
            if len(entries) > 100 or sum(e.file_size for e in entries) > 10_000_000:
                raise SourceParseError("Houston workbook exceeds expanded bounds")
            if len({e.filename for e in entries}) != len(entries):
                raise SourceParseError("Houston workbook has duplicate members")
            if [e.filename for e in entries if e.filename.startswith("xl/worksheets/sheet")] != [
                "xl/worksheets/sheet1.xml"
            ]:
                raise SourceParseError("Houston workbook sheet layout changed")
            strings = [
                "".join(si.itertext()) for si in ET.fromstring(archive.read("xl/sharedStrings.xml"))
            ]
            sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            workbook_properties = workbook.find("x:workbookPr", NS)
            date1904 = (
                workbook_properties is not None
                and workbook_properties.get("date1904") in {
                    "1",
                    "true",
                }
            )
            date_epoch = MAC_EPOCH if date1904 else WINDOWS_EPOCH
        rows = []
        for row in sheet.findall(".//x:row", NS):
            values = [""] * 6
            for cell in row:
                ref = cell.get("r", "")
                match = re.fullmatch(r"([A-F])\d+", ref)
                if not match or cell.find("x:f", NS) is not None:
                    raise SourceParseError("Houston unexpected cell or formula")
                value = cell.find("x:v", NS)
                if value is not None:
                    values[ord(match[1]) - ord("A")] = (
                        strings[int(value.text or "")] if cell.get("t") == "s" else value.text or ""
                    )
            rows.append(values)
        if not 6 <= len(rows) <= 5005 or rows[4] != HEADERS:
            raise SourceParseError("Houston workbook headers or row bounds changed")
        start = datetime.strptime(rows[1][0].strip(), "From: %Y/%m/%d").date()
        end = datetime.strptime(rows[2][0].strip(), "To : %Y/%m/%d").date()
        if (end - start).days != 7 or end > today:
            raise SourceParseError("Houston report date interval is invalid")
        if listed_week_start is not None and listed_week_start not in {start, end}:
            raise SourceParseError("Houston listed sale week disagrees with workbook period")
        output = []
        seen: dict[str, list[str]] = {}
        footer = [
            "* Information provided to City by applicant on the building permit. "
            "The City does not confirm or verify statement",
            "by applicant. If you believe the project does not meet the deed restrictions "
            "for this property, please contact ",
            "the City of Houston's Deed Restriction Hotline at 713.437.6769.",
        ]
        footer_seen = []
        for number, values in enumerate(rows[5:], start=6):
            if not any(values):
                continue
            if values[0].strip() in [line.strip() for line in footer] and not any(values[1:]):
                footer_seen.append(values[0].strip())
                continue
            if footer_seen:
                raise SourceParseError("Houston data appears after report footer")
            zipcode, stamp, kind, project, address, description = values
            issued = _permit_date(stamp, date_epoch)
            if not start <= issued <= end or not all((project, address, kind, description)):
                raise SourceParseError("Houston report has incomplete or out-of-window row")
            identity = f"{project}:{kind}:{issued.isoformat()}"
            if identity in seen:
                if seen[identity] != values:
                    raise SourceParseError("Houston report has ambiguous duplicate identity")
                continue  # Byte-equivalent field duplicates occur in official reports.
            seen[identity] = values
            output.append(
                {
                    "document_number": identity,
                    "title": f"Houston sold permit {project} — {kind}",
                    "abstract": "\n".join(
                        (
                            f"row: {project}",
                            "event: Sold (weekly report; issued permit event)",
                            f"date: {issued.isoformat()}",
                            f"report_start: {start.isoformat()}",
                            f"report_end: {end.isoformat()}",
                            "status: Unknown",
                            f"type: {kind}",
                            f"address: {address}",
                            f"description: {description}",
                            f"zip: {zipcode}",
                        )
                    ),
                    "publication_date": None,
                    "event_date": issued.isoformat(),
                    "event_date_label": "Permit sale date (weekly Sold Permits report)",
                    "html_url": url,
                    "extraction_location": (
                        f"Official weekly report {start} through {end}; sheet1 row {number}"
                    ),
                    "source_hash": hashlib.sha256(
                        json.dumps(values, ensure_ascii=False).encode()
                    ).hexdigest(),
                    "permit": {
                        "source_type": "houston-weekly-permits",
                        "city": "Houston",
                        "state": "TX",
                        "address": address,
                        "description": description,
                        "type": kind,
                        "status": "Unknown",
                        "issuance_event": "sold",
                        "report_period_start": start.isoformat(),
                        "report_period_end": end.isoformat(),
                        "class": "Unknown",
                        "work": "",
                        "cost": "",
                        "area": "",
                        "project": project,
                        "row_id": identity,
                        "zip": zipcode,
                    },
                }
            )
        if footer_seen != [line.strip() for line in footer]:
            raise SourceParseError("Houston report footer is missing or changed")
        if not output:
            raise SourceParseError("Houston report unexpectedly empty")
        return end, output
    except (ValueError, KeyError, IndexError, zipfile.BadZipFile, ET.ParseError) as exc:
        if isinstance(exc, SourceParseError):
            raise
        raise SourceParseError("Houston workbook parse failed") from exc


def retrieve(source: dict[str, Any], client: httpx.Client | None = None) -> list[dict[str, Any]]:
    if source.get("id") != "houston-weekly-permits" or source.get("endpoint") != INDEX:
        raise SourceParseError("Houston source is outside its reviewed endpoint")
    http = client or httpx.Client(timeout=20, follow_redirects=False)
    today = datetime.now(UTC).date()
    try:
        _, body = read_bounded_response(http, INDEX, 2_000_000)
        links: dict[date, str] = {}
        for anchor in BeautifulSoup(body, "html.parser").select("a[href]"):
            label = anchor.get_text(" ", strip=True)
            try:
                report_date = datetime.strptime(label, "%B %d, %Y").date()
            except ValueError:
                continue
            href = str(anchor["href"])
            parsed = urlsplit(href)
            if parsed.hostname == "view.officeapps.live.com":
                href = parse_qs(parsed.query).get("src", [""])[0]
            if report_date in links and links[report_date] != href:
                raise SourceParseError("Houston report date has ambiguous links")
            links[report_date] = href
        chosen = sorted(links, reverse=True)[:4]
        if not chosen:
            raise SourceParseError("Houston index lists no dated weekly report links")
        if chosen[0] > today:
            raise SourceParseError(
                f"Houston newest report link is dated in the future ({chosen[0].isoformat()})"
            )
        if (today - chosen[0]).days > 30:
            raise SourceParseError(
                f"Houston publisher has not posted a weekly report since {chosen[0].isoformat()}"
                " (over 30 days)"
            )
        output: dict[str, dict[str, Any]] = {}
        for report_date in reversed(chosen):
            href = links[report_date]
            parsed = urlsplit(href)
            if (
                parsed.scheme != "https"
                or parsed.netloc != HOST
                or not parsed.path.startswith("/sites/g/files/")
                or not parsed.path.lower().endswith(".xlsx")
                or parsed.query
            ):
                raise SourceParseError("Houston report link is outside its official path")
            _, workbook = read_bounded_response(http, links[report_date], 2_000_000)
            end, records = parse_report(
                workbook, links[report_date], today=today, listed_week_start=report_date
            )
            start = date.fromisoformat(records[0]["permit"]["report_period_start"])
            if (end - start).days != 7 or report_date not in {start, end}:
                raise SourceParseError("Houston workbook dates disagree with listing")
            for record in records:
                key = record["document_number"]
                if key in output and output[key]["source_hash"] != record["source_hash"]:
                    raise SourceParseError("Houston overlapping reports conflict")
                output[key] = record
        return list(output.values())
    finally:
        if client is None:
            http.close()
