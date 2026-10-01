"""Bounded primary-source research using the ingestion runtime's trusted HTTP proxy.

Only fixed official hosts and paths are supported. This does not weaken the
DNS-pinned arbitrary-public-URL reader or add a search/enrichment subscription.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
from bs4 import BeautifulSoup, Tag

from gridlens.ingestion.adapters.bounded_http import ResponseTooLarge, remaining_seconds
from gridlens.ingestion.adapters.buying_chain_public import PublicDocument, parse_document
from gridlens.ingestion.adapters.rrc_drilling import (
    MONTHLY_PORTAL,
    PORTAL,
    _download_listing_file,
    parse_snapshot,
    records_from_snapshots,
    source_today,
)

AUSTIN = "https://data.austintexas.gov/resource/3syk-w9eu.json"
TABS = "https://www.tdlr.texas.gov"
MAX_BYTES = 750_000
RequestHook = Callable[[], None]


def _read(
    method: str,
    url: str,
    deadline: float,
    on_request: RequestHook | None,
    *,
    data: dict[str, str] | None = None,
) -> tuple[str, bytes]:
    remaining = remaining_seconds(deadline)
    assert remaining is not None
    if on_request:
        on_request()
    # These constant hosts use the same trusted configured transport as ingestion.
    # Redirects are deliberately disabled; an external target is never followed.
    with httpx.Client(timeout=min(12.0, remaining), follow_redirects=False) as client:
        with client.stream(method, url, data=data) as response:
            remaining_seconds(deadline)
            response.raise_for_status()
            if response.status_code != 200:
                raise ValueError("Official source did not return a complete document")
            declared = response.headers.get("content-length")
            if declared and (not declared.isdigit() or int(declared) > MAX_BYTES):
                raise ResponseTooLarge("Official source response exceeds research byte bound")
            parts: list[bytes] = []
            size = 0
            for part in response.iter_bytes():
                remaining_seconds(deadline)
                size += len(part)
                if size > MAX_BYTES:
                    raise ResponseTooLarge("Official source response exceeds research byte bound")
                parts.append(part)
            remaining_seconds(deadline)
            return response.headers.get("content-type", ""), b"".join(parts)


def retrieve_austin(
    external_id: str, deadline: float, on_request: RequestHook | None = None
) -> PublicDocument:
    """Refresh one exact official permit identity, without discovery side effects."""
    if not re.fullmatch(r"\d{4}-\d{6} (?:BP|EP|MP|PP)", external_id):
        raise ValueError("Expected an exact Austin permit number including trade")
    url = AUSTIN + "?" + urlencode({"$where": f"permit_number='{external_id}'", "$limit": 1})
    kind, body = _read("GET", url, deadline, on_request)
    document = parse_document(url, body, kind)
    if len(document.structured) != 1 or document.structured[0].get("permit_number") != external_id:
        raise ValueError("Exact official Austin permit identity was not returned")
    return document


def tdlr_urls(
    address: str,
    deadline: float,
    on_request: RequestHook | None = None,
    limit: int = 2,
) -> list[str]:
    """Discover newest registrations for an address; matches are not project merges."""
    if not 3 <= len(address.strip()) <= 160 or not any(c.isdigit() for c in address):
        raise ValueError("An explicit bounded street address is required")
    if not 1 <= limit <= 2:
        raise ValueError("At most two TDLR detail sources are permitted")
    data = {
        "draw": "1",
        "start": "0",
        "length": str(limit),
        "LocationAddress": address.strip(),
        "order[0][column]": "3",
        "order[0][dir]": "desc",
    }
    for index, field in enumerate(
        (
            "ProjectId",
            "ProjectNumber",
            "ProjectName",
            "ProjectCreatedOn",
            "ProjectStatus",
            "FacilityName",
            "City",
            "County",
            "TypeOfWork",
            "EstimatedCost",
            "DataVersionId",
        )
    ):
        data[f"columns[{index}][data]"] = field
        data[f"columns[{index}][name]"] = ""
        data[f"columns[{index}][searchable]"] = "true"
        data[f"columns[{index}][orderable]"] = "true"
        data[f"columns[{index}][search][value]"] = ""
        data[f"columns[{index}][search][regex]"] = "false"
    _, body = _read("POST", TABS + "/TABS/Search/SearchProjects", deadline, on_request, data=data)
    result = json.loads(body)
    rows = result.get("data") if isinstance(result, dict) else None
    if (
        not isinstance(rows, list)
        or len(rows) > limit
        or not all(isinstance(r, dict) for r in rows)
    ):
        raise ValueError("TDLR search did not return a bounded project result")
    urls = []
    for row in rows:
        number = row.get("ProjectNumber", "")
        if not isinstance(number, str) or not re.fullmatch(
            r"(?:TABS\d{10}|EABPRJ[A-Z]?\d{7})", number
        ):
            raise ValueError("TDLR search returned an invalid project identity")
        urls.append(TABS + "/TABS/Search/Print/" + number)
    return list(dict.fromkeys(urls))


def _tabs_document(url: str, body: bytes, kind: str) -> PublicDocument:
    document = parse_document(url, body, kind)
    soup = BeautifulSoup(body, "html.parser")
    fields: dict[str, str] = {}
    for section in soup.select('[class*="project-details-"]'):
        # Prefix repeated Contact Name labels to preserve the relationship stated.
        classes = str(section.get("class", "")).split()
        raw_classes = section.get("class")
        if isinstance(raw_classes, list):
            classes = [str(item) for item in raw_classes]
        category = next(
            (
                str(c).removeprefix("project-details-")
                for c in classes
                if str(c).startswith("project-details-")
            ),
            "project",
        )
        if category not in {"project", "contact", "ras", "owner", "tenant", "designer"}:
            continue
        for label in section.find_all("dt"):
            values = []
            sibling = label.find_next_sibling()
            while isinstance(sibling, Tag) and sibling.name == "dd":
                values.append(sibling.get_text(" ", strip=True))
                sibling = sibling.find_next_sibling()
            key = label.get_text(" ", strip=True).rstrip(":")
            fields[f"{category}:{key}"] = " ".join(values)

    def value(label: str, section: str = "project") -> str | None:
        return fields.get(f"{section}:{label}") or None

    number = value("Project Number")
    if (
        number != url.rsplit("/", 1)[-1]
        or not value("Location Address")
        or not value("Scope of Work")
    ):
        raise ValueError("TDLR detail lacks exact identity, address or scope")
    record = {
        "source_type": "tdlr-tabs",
        "project_number": number,
        "project_name": value("Project Name"),
        "facility_name": value("Facility Name"),
        "address": value("Location Address"),
        "scope": value("Scope of Work"),
        "start": value("Start Date"),
        "end": value("Completion Date"),
        "timing_basis": "Registration planned dates; actual construction/startup unverified",
        "status": value("Current Status"),
        "type_of_work": value("Type of Work"),
        "square_footage": value("Square Footage"),
        "owner": value("Owner Name", "owner"),
        "owner_phone": value("Owner Phone", "owner"),
        "owner_contact": value("Contact Name", "owner"),
        "design_firm": value("Design Firm Name", "designer"),
        "design_phone": value("Design Firm Phone", "designer"),
        "filing_person": value("Contact Name", "contact"),
        "raw_labelled_facts": fields,
    }
    return replace(
        document, structured=(record,), extraction_location="TDLR labelled project registration"
    )


def retrieve_official(
    url: str, deadline: float, on_request: RequestHook | None = None
) -> PublicDocument:
    """Retrieve a discovered TDLR detail only; never follow arbitrary links."""
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or parts.netloc != "www.tdlr.texas.gov"
        or parts.query
        or parts.fragment
        or not re.fullmatch(
            r"/TABS/Search/(?:Print|Project)/(?:TABS\d{10}|EABPRJ[A-Z]?\d{7})", parts.path
        )
    ):
        raise ValueError("Unsupported official pursuit research URL")
    kind, body = _read("GET", url, deadline, on_request)
    return _tabs_document(url, body, kind)


def retrieve_tabs(
    address: str, deadline: float, on_request: RequestHook | None = None, fetch_limit: int = 3
) -> list[PublicDocument]:
    if not 2 <= fetch_limit <= 3:
        raise ValueError("TDLR research requires one search and at most two details")
    return [
        retrieve_official(url, deadline, on_request)
        for url in tdlr_urls(address, deadline, on_request, limit=fetch_limit - 1)
    ]


class _CountedClient:
    def __init__(self, client: httpx.Client, hook: RequestHook | None):
        self.client = client
        self.hook = hook

    def stream(self, *args: Any, **kwargs: Any) -> Any:
        if self.hook:
            self.hook()
        return self.client.stream(*args, **kwargs)


def retrieve_rrc_snapshot(
    deadline: float, on_request: RequestHook | None = None
) -> list[dict[str, Any]]:
    """One shared fresh daily snapshot; absence does not retract historical assets.

    The daily snapshot is research, not a replacement for the ingestion adapter's
    mandatory previous-month EOM overlap. Callers must preserve that distinction.
    """
    today = source_today()
    with httpx.Client(timeout=12, follow_redirects=False) as client:
        body, _ = _download_listing_file(
            _CountedClient(client, on_request), PORTAL, "daf420.dat", today, deadline
        )
    return records_from_snapshots([parse_snapshot(body, filename="daf420.dat", today=today)])


def retrieve_rrc_archive(
    filename: str, deadline: float, on_request: RequestHook | None = None
) -> list[dict[str, Any]]:
    """Re-retrieve a cited historical EOM snapshot, never evidence of current work.

    This is explicit historical research, not ingestion's missing-EOM fallback.
    Callers bound unique archives per batch and keep absence from daily visible.
    """
    if not re.fullmatch(r"daf420\.dat\.\d{2}-\d{2}-\d{4}", filename):
        raise ValueError("Expected an exact official RRC EOM snapshot filename")
    try:
        archive_date = datetime.strptime(filename.removeprefix("daf420.dat."), "%m-%d-%Y").date()
    except ValueError as exc:
        raise ValueError("Invalid RRC archive date") from exc
    today = source_today()
    if archive_date >= today or (archive_date + timedelta(days=1)).day != 1:
        raise ValueError("RRC archive must identify a past calendar month end")
    with httpx.Client(timeout=12, follow_redirects=False) as client:
        body, _ = _download_listing_file(
            _CountedClient(client, on_request),
            MONTHLY_PORTAL,
            filename,
            today,
            deadline,
            archive_date=archive_date,
        )
    return records_from_snapshots(
        [parse_snapshot(body, filename=filename, today=today, source_url=MONTHLY_PORTAL)]
    )
