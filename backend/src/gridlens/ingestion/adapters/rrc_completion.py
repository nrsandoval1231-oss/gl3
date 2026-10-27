"""Finite exact-API public RRC completion history, separate from current permit status."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup, Tag

from gridlens.ingestion.adapters.bounded_http import remaining_seconds
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.rrc_well_lifecycle import (
    MAX_DETAIL_BYTES,
    WellIdentity,
    _sanitized_source_url,
    parse_completion_packet,
)

BASE = "https://webapps.rrc.texas.gov/CMPL/ewaSearchAction.do"
MAX_PACKETS = 2


def _url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "webapps.rrc.texas.gov"
        or not parsed.path.startswith("/CMPL/")
        or len(value) > 2000
    ):
        raise SourceParseError("Completion link left the reviewed official host/path")
    return value


def _read(client: httpx.Client, url: str, deadline: float) -> bytes:
    with client.stream(
        "GET", _url(url), follow_redirects=False, timeout=min(15, remaining_seconds(deadline) or 15)
    ) as response:
        if response.status_code != 200:
            raise SourceParseError("Official completion source was unavailable")
        content = []
        size = 0
        for part in response.iter_bytes():
            remaining_seconds(deadline)
            size += len(part)
            if size > MAX_DETAIL_BYTES:
                raise SourceParseError("Completion page exceeded its byte bound")
            content.append(part)
        return b"".join(content)


def retrieve_completion_history(
    identity: dict, *, deadline: float, client: httpx.Client | None = None
) -> dict:
    """Fetch at most two exact-well packets, with no chronology/qualification inference."""
    api = str(identity.get("api") or "")
    if not re.fullmatch(r"\d{8}", api):
        raise SourceParseError("Completion research requires a validated eight-digit Texas API")
    expected = WellIdentity(
        api_number=api,
        permit_number=str(identity.get("permit_number") or ""),
        operator_number=str(identity.get("operator_number") or ""),
        operator_name=identity.get("operator"),
        lease=str(identity.get("lease") or ""),
        well_number=str(identity.get("well_number") or identity.get("well") or ""),
        county_code=str(identity.get("county_code") or ""),
        county=identity.get("county"),
    )
    own_client = client is None
    http = client or httpx.Client(timeout=15, follow_redirects=False)
    query_url = (
        BASE + "?" + urlencode({"methodToCall": "searchByApiNo", "apiNo": api, "relatedLink": "Y"})
    )
    try:
        listing = _read(http, query_url, deadline)
        soup = BeautifulSoup(listing, "html.parser")
        links = {}
        for anchor in soup.find_all("a", href=True):
            if not isinstance(anchor, Tag):
                continue
            href = anchor.get("href")
            if not isinstance(href, str):
                continue
            target = urljoin(query_url, href)
            parsed = urlsplit(target)
            params = parse_qs(parsed.query)
            packet = params.get("packetSummaryId", [""])[0]
            if params.get("methodToCall") == ["displayBySummaryId"] and re.fullmatch(
                r"\d{6,7}", packet
            ):
                links[packet] = _url(target)
        if not links:
            if not re.search(
                r"No [\'\"]?Packet[\'\"]? records found", soup.get_text(" ", strip=True), re.I
            ):
                raise SourceParseError(
                    "Completion query did not establish a packet list or explicit empty result"
                )
            return {
                "status": "no_packets_returned",
                "source_url": query_url,
                "content_hash": hashlib.sha256(listing).hexdigest(),
                "records": [],
            }
        if len(links) > MAX_PACKETS:
            return {
                "status": "packet_limit_reached",
                "source_url": query_url,
                "content_hash": hashlib.sha256(listing).hexdigest(),
                "records": [],
            }
        records = []
        for _packet, target in sorted(links.items()):
            body = _read(http, target, deadline)
            facts = parse_completion_packet(body, expected, source_url=target)
            records.append(
                {
                    **facts,
                    "source_url": _sanitized_source_url(target, allowed_path="/CMPL/"),
                    "content_hash": hashlib.sha256(body).hexdigest(),
                }
            )
        return {
            "status": "bounded_packets_checked",
            "source_url": query_url,
            "content_hash": hashlib.sha256(listing).hexdigest(),
            "records": records,
        }
    finally:
        if own_client:
            http.close()
