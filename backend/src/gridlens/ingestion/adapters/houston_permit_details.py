"""Exact public Sold Permits Search detail lookup for supported Houston permit rows."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, date, datetime
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup

from gridlens.ingestion.adapters.bounded_http import read_bounded_response
from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
from gridlens.ingestion.adapters.federal_register import SourceParseError

HOST = "cohtora.houstontx.gov"
DETAIL = f"https://{HOST}/ibi_apps/WFServlet.ibfs"
SUPPORTED_TYPES = {"Building Pmt": "13"}
DETAIL_TYPE_CODES = {"building": "13", "building pmt": "13", "13": "13"}
MAX_BYTES = 150_000


def response_type_code(value: str) -> str | None:
    """Map only reviewed Houston detail labels to the public form selector code."""
    normalized = " ".join(value.split()).casefold()
    return DETAIL_TYPE_CODES.get(normalized)


def retrieve_detail(
    project_number: str,
    permit_type: str,
    *,
    event_date: str,
    site_address: str,
    client: httpx.Client | None = None,
) -> PublicDocument:
    if not re.fullmatch(r"\d{7,10}", project_number) or permit_type not in SUPPORTED_TYPES:
        raise SourceParseError("Houston exact permit detail is unsupported for this row")
    try:
        expected_date = date.fromisoformat(event_date)
    except ValueError as exc:
        raise SourceParseError("Houston permit event date is invalid") from exc
    http = client or httpx.Client(
        timeout=20,
        follow_redirects=False,
        headers={
            "User-Agent": "GridLens public source reader/1.0",
            "Referer": "https://cohtora.houstontx.gov/approot/soldpermits/online_permit.htm",
        },
    )
    params = {
        "IBIF_webapp": "/ibi_apps",
        "IBIC_server": "EDASERVE",
        "IBIWF_msgviewer": "OFF",
        "IBIAPP_app": "soldpermits",
        "IBIF_ex": "sold_permit_d",
        "CLICKED_ON": "",
        "PN": project_number,
        "PT": SUPPORTED_TYPES[permit_type],
    }
    url = DETAIL + "?" + urlencode(params)
    try:
        headers, body = read_bounded_response(http, url, MAX_BYTES)
        if "text/html" not in headers.get("content-type", "").lower():
            raise SourceParseError("Houston exact permit detail returned non-HTML content")
        soup = BeautifulSoup(body, "html.parser")
        values: dict[str, str] = {}
        for row in soup.select("tr"):
            cells = [
                " ".join(cell.stripped_strings)
                for cell in row.find_all(["td", "th"], recursive=False)
            ]
            if len(cells) >= 2:
                label = re.sub(r"\s*:\s*$", "", cells[0]).strip().casefold()
                if label:
                    values[label] = " ".join(cells[1].split())
        expected_project = project_number
        if values.get("project no", "").strip() != expected_project:
            raise SourceParseError("Houston permit detail project number did not match")
        try:
            observed_date = datetime.strptime(values.get("date", ""), "%Y/%m/%d %H:%M:%S").date()
        except ValueError as exc:
            raise SourceParseError("Houston permit detail has no supported event date") from exc
        if observed_date != expected_date:
            raise SourceParseError("Houston permit detail date did not match the sold report row")
        detail_address = values.get("job address", "")
        if not detail_address or site_address.casefold() not in detail_address.casefold():
            raise SourceParseError("Houston permit detail site did not match the sold report row")
        observed_type_code = response_type_code(values.get("permit type", ""))
        if observed_type_code != SUPPORTED_TYPES[permit_type]:
            raise SourceParseError(
                "Houston permit detail type did not match the Building Pmt / PT=13 search"
            )
        fields = {
            "project": values["project no"],
            "date": observed_date.isoformat(),
            "use": values.get("use", ""),
            "owner_occupant": values.get("owner/occupant", ""),
            "site_address": detail_address,
            "valuation": values.get("valuation", ""),
            "permit_type": observed_type_code,
            "fcc_group": values.get("fcc group", ""),
            "buyer": values.get("buyer", ""),
            "buyer_address": values.get("address", ""),
            "buyer_phone": values.get("phone", ""),
        }
        abstract = "\n".join(f"detail_{key}: {value}" for key, value in fields.items() if value)
        if not fields["buyer"]:
            raise SourceParseError("Houston permit detail omitted its Buyer field")
        return PublicDocument(
            url=url,
            title=f"Houston sold permit detail {project_number} — {permit_type}",
            text=abstract,
            published_at=None,
            observed_at=datetime.now(UTC),
            extraction_location=(
                "Official Houston Online Sold Permit Search; Project Details fields"
            ),
            structured=({"source_hash": hashlib.sha256(body).hexdigest()},),
        )
    finally:
        if client is None:
            http.close()
