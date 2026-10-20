"""TDLR TABS project registrations that name a data center (statewide Texas).

Texas requires commercial projects of $50,000 or more to register with the Texas Department of
Licensing and Regulation's Architectural Barriers program, inside or outside city limits. The
public project search lists registrations by date; each project page states the location and
county, the developer-reported start and completion dates, estimated cost, type of work, scope,
owner and design firm. This covers unincorporated county land that city permit tables miss.
Admission is decided in the domain layer.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta
from typing import Any

import httpx
from bs4 import BeautifulSoup, Tag

from gridlens.ingestion.adapters.bounded_http import ResponseTooLarge, read_bounded_response
from gridlens.ingestion.adapters.federal_register import SourceParseError

SOURCE_ID = "texas-tdlr-tabs-data-centers"
SEARCH_URL = "https://www.tdlr.texas.gov/TABS/Search/SearchProjects"
PROJECT_URL = "https://www.tdlr.texas.gov/TABS/Search/Project/{number}"
MAX_SEARCH_BYTES = 2_000_000
MAX_PAGE_BYTES = 1_000_000
PAGE_SIZE = 100
MAX_MATCHES = 300
DATA_CENTER = re.compile(r"\bdata\s*cent(?:er|re)s?\b|\bhyperscale\b", re.IGNORECASE)
_NUMBER = re.compile(r"^TABS\d{10}$")


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _day(value: str) -> str | None:
    try:
        return datetime.strptime(_text(value), "%m/%d/%Y").date().isoformat()
    except ValueError:
        return None


def _post(client: httpx.Client, form: dict[str, str]) -> bytes:
    try:
        with client.stream(
            "POST", SEARCH_URL, data=form, headers={"X-Requested-With": "XMLHttpRequest"}
        ) as response:
            response.raise_for_status()
            parts, size = [], 0
            for part in response.iter_bytes():
                size += len(part)
                if size > MAX_SEARCH_BYTES:
                    raise ResponseTooLarge("TABS search response exceeds its bound")
                parts.append(part)
            return b"".join(parts)
    except (httpx.HTTPError, ResponseTooLarge) as exc:
        raise SourceParseError(f"TABS search failed: {type(exc).__name__}") from exc


def search_form(term: str, start: date, offset: int) -> dict[str, str]:
    """The form the public search page posts (DataTables server-side protocol)."""
    return {
        "draw": "1",
        "start": str(offset),
        "length": str(PAGE_SIZE),
        "order[0][column]": "3",
        "order[0][dir]": "desc",
        "ProjectName": term,
        "RegistrationDateBegin": start.strftime("%m/%d/%Y"),
    }


def parse_search(body: bytes) -> tuple[int, list[dict[str, Any]]]:
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise SourceParseError("TABS search did not return JSON") from exc
    rows, total = (
        (payload.get("data"), payload.get("recordsFiltered"))
        if isinstance(payload, dict)
        else (None, None)
    )
    if not isinstance(rows, list) or not isinstance(total, int):
        raise SourceParseError("TABS search response lacks data or recordsFiltered")
    for row in rows:
        if not isinstance(row, dict) or not _NUMBER.match(_text(row.get("ProjectNumber"))):
            raise SourceParseError("TABS search row is malformed or lacks a project number")
        if "ProjectName" not in row:
            raise SourceParseError("TABS search row lacks ProjectName")
    return total, rows


def _sections(soup: BeautifulSoup) -> dict[str, dict[str, str]]:
    sections: dict[str, dict[str, str]] = {}
    for block in soup.select(".project-details-body > div"):
        heading = block.find("h4")
        name = _text(heading.get_text()) if isinstance(heading, Tag) else ""
        fields: dict[str, str] = {}
        label = None
        for node in block.find_all(["dt", "dd"]):
            if not isinstance(node, Tag):
                continue
            if node.name == "dt":
                label = _text(node.get_text()).rstrip(":")
            elif label:
                value = _text(node.get_text(" ")).rstrip(",").strip()
                fields[label] = f"{fields[label]}, {value}" if label in fields else value
        sections[name] = fields
    return sections


def parse_project(body: bytes, number: str) -> dict[str, Any]:
    soup = BeautifulSoup(body, "html.parser")
    sections = _sections(soup)
    project = sections.get("PROJECT", {})
    if project.get("Project Number") != number or not project.get("Project Name"):
        raise SourceParseError(f"TABS project page for {number} lacks its number or name")
    header_node = soup.select_one(".project-details-header")
    header = _text(header_node.get_text(" ")) if header_node is not None else ""
    registered = re.search(r"Registration Date:\s*(\d{1,2}/\d{1,2}/\d{4})", header)
    owner = sections.get("OWNER", {})
    return {
        "number": number,
        "name": project["Project Name"],
        "facility": project.get("Facility Name") or None,
        "address": project.get("Location Address") or None,
        "county": project.get("Location County") or None,
        "registered": _day(registered.group(1)) if registered else None,
        "start": _day(project.get("Start Date", "")),
        "completion": _day(project.get("Completion Date", "")),
        "cost": project.get("Estimated Cost") or None,
        "work_type": project.get("Type of Work") or None,
        "scope": project.get("Scope of Work") or "",
        "square_feet": project.get("Square Footage") or None,
        "status": project.get("Current Status") or None,
        "owner": owner.get("Owner Name") or None,
        "owner_contact": owner.get("Contact Name") or None,
        "design_firm": sections.get("DESIGN FIRM", {}).get("Design Firm Name") or None,
    }


def record(project: dict[str, Any]) -> dict[str, Any]:
    url = PROJECT_URL.format(number=project["number"])
    county = project["county"]
    address = project["address"]
    location = (
        f"{address} ({county} County)"
        if address and county
        else address or (f"{county} County, TX" if county else None)
    )
    row_id = f"TABS-{project['number']}"
    return {
        "document_number": row_id,
        "title": f"{project['name']} — TDLR TABS {project['number']}",
        "abstract": "\n".join(
            [
                f"Project: {project['name']} ({project['facility'] or 'facility not named'})",
                f"Location: {location or 'not stated'}",
                f"Registered: {project['registered'] or 'unknown'}",
                f"Developer-reported start: {project['start'] or 'unknown'}; completion: "
                f"{project['completion'] or 'unknown'}",
                f"Estimated cost: {project['cost'] or 'not stated'}",
                f"Type of work: {project['work_type'] or 'not stated'}",
                f"Scope: {project['scope'] or 'not stated'}",
                f"Owner: {project['owner'] or 'not stated'}",
                f"Design firm: {project['design_firm'] or 'not stated'}",
                f"TABS status: {project['status'] or 'unknown'}",
            ]
        ),
        # The registry has no publication date; the registration date is the event.
        "publication_date": None,
        "event_date": project["registered"],
        "event_date_label": "Registered with TDLR (Architectural Barriers)",
        "html_url": url,
        "extraction_location": "TDLR TABS project details page",
        "source_hash": hashlib.sha256(
            json.dumps(project, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "permit": {
            "source_type": SOURCE_ID,
            "row_id": row_id,
            "applicant": project["owner"],
            "facility": project["name"],
            "permit_type": "TDLR TABS project registration",
            "subtype": project["work_type"],
            "status": project["status"],
            "description": f"{project['name']} {project['scope']}".strip(),
            "job_value": project["cost"],
            "location": location,
            "city": None,
            "county": county,
            "latitude": None,
            "longitude": None,
            "reported_start": project["start"],
            "reported_completion": project["completion"],
            "design_firm": project["design_firm"],
            "document_links": {"TDLR TABS project": url},
            "source_fields": {
                "facility": "Project Name",
                "registered": "Registration Date",
                "start": "Start Date (developer-reported)",
                "completion": "Completion Date (developer-reported)",
                "location": "Location Address, Location County",
            },
        },
    }


def retrieve(
    source: dict[str, Any], client: httpx.Client | None = None, today: date | None = None
) -> list[dict[str, Any]]:
    if source.get("id") != SOURCE_ID or source.get("endpoint") != SEARCH_URL:
        raise SourceParseError("TABS source ID or endpoint is not configured")
    query = source.get("query", {})
    window = int(query.get("window_days", 0))
    terms = list(query.get("name_terms", []))
    if not 1 <= window <= 90 or not 1 <= len(terms) <= 4:
        raise SourceParseError("TABS query bounds are invalid")
    run_day = today or date.today()
    start = run_day - timedelta(days=window)
    http = client or httpx.Client(timeout=25, follow_redirects=False)
    try:
        numbers: dict[str, dict[str, Any]] = {}
        for term in terms:
            offset, total = 0, None
            while total is None or offset < total:
                total, rows = parse_search(_post(http, search_form(term, start, offset)))
                if total > MAX_MATCHES:
                    raise SourceParseError(f"TABS search for {term!r} matched {total} projects")
                if not rows and offset < total:
                    raise SourceParseError("TABS search returned an empty page before its total")
                for row in rows:
                    numbers.setdefault(_text(row["ProjectNumber"]), row)
                offset += len(rows)
        records = []
        for number in sorted(numbers):
            url = PROJECT_URL.format(number=number)
            _, body = read_bounded_response(http, url, MAX_PAGE_BYTES)
            project = parse_project(body, number)
            text = f"{project['name']} {project['facility']} {project['scope']}"
            if not DATA_CENTER.search(text):
                continue
            if project["registered"] and project["registered"] > run_day.isoformat():
                raise SourceParseError(f"TABS project {number} is registered after the run date")
            records.append(record(project))
        return records
    finally:
        if client is None:
            http.close()
