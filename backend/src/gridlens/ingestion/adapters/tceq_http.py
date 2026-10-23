"""Narrow, bounded HTTP policy for the verified TCEQ public pages and PDFs."""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit

import httpx

from gridlens.ingestion.adapters.bounded_http import read_bounded_response
from gridlens.ingestion.adapters.federal_register import SourceParseError

HOST = "www.tceq.texas.gov"
RECORDS_HOST = "records.tceq.texas.gov"
# Exact hosts only. A suffix such as evil.tceq.texas.gov is not official.
OFFICIAL_HOSTS = frozenset(
    {
        "www.tceq.texas.gov",
        "www2.tceq.texas.gov",
        "www15.tceq.texas.gov",
        "records.tceq.texas.gov",
        "permit-search.tceq.texas.gov",
    }
)
NSR_LISTING = (
    "https://www.tceq.texas.gov/assets/public/permitting/air/reports/applications/"
    "nsr-pending-permits.html"
)
BATCH_LISTING = (
    "https://www.tceq.texas.gov/permitting/air/newsourcereview/airpermits-pendingpermit-apps"
)
_PDF_PREFIX = "/downloads/permitting/air/bilingual/pending-permit-notices/"
_PDF_SUFFIXES = ("-pls-english.pdf", "-napd-english.pdf")
_MAX_REDIRECTS = 3


def record_document_url(url: str) -> str | None:
    """Canonical Records Online file URL, or None when the URL is not that shape."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.hostname != RECORDS_HOST or parts.path != "/cs/idcplg" or parts.fragment:
        return None
    try:
        query = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return None
    if (
        len(query) != 3
        or len(dict(query)) != 3
        or dict(query).get("IdcService") != "TCEQ_EXTERNAL_SEARCH_GET_FILE"
        or dict(query).get("Rendition") != "Web"
        or not re.fullmatch(r"[1-9][0-9]{0,8}", dict(query).get("dID", ""))
    ):
        return None
    return "https://records.tceq.texas.gov/cs/idcplg?" + urlencode(sorted(query))


def _route(url: str, route: str) -> str:
    """Validate an exact supported URL before resolving DNS or making a request."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except (TypeError, ValueError) as exc:
        raise SourceParseError("TCEQ URL is malformed") from exc
    record = record_document_url(url)
    pdf_host = parts.hostname in OFFICIAL_HOSTS and parts.hostname != RECORDS_HOST
    if (
        parts.scheme != "https"
        or parts.hostname not in OFFICIAL_HOSTS
        or parts.username is not None
        or parts.password is not None
        or port not in (None, 443)
        or (bool(parts.query) and record is None)
        or parts.fragment
        or "\\" in parts.path
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in url)
        or any(segment in {".", ".."} for segment in parts.path.split("/"))
    ):
        raise SourceParseError("TCEQ URL is outside the verified HTTPS policy")
    pdf_name = parts.path[len(_PDF_PREFIX) :] if parts.path.startswith(_PDF_PREFIX) else ""
    supported_pdf = (
        route == "pdf"
        and pdf_host
        and pdf_name.isascii()
        and pdf_name.lower().endswith(_PDF_SUFFIXES)
        and pdf_name.replace("-pls-english.pdf", "").replace("-napd-english.pdf", "").isalnum()
    )
    supported = (route == "record_pdf" and record is not None) or (
        (route == "listing" and url in {NSR_LISTING, BATCH_LISTING}) or supported_pdf
    )
    if not supported:
        raise SourceParseError("TCEQ URL is outside the verified route allowlist")
    if record is not None and route == "record_pdf":
        return record
    return url


def _public_ip(host: str) -> str:
    """Choose a public address and pin the HTTP connection to that DNS answer."""
    try:
        answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        addresses = sorted({str(ipaddress.ip_address(answer[4][0])) for answer in answers})
    except (OSError, ValueError) as exc:
        raise SourceParseError("TCEQ host DNS resolution failed") from exc
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise SourceParseError("TCEQ host resolved to a non-public address")
    return addresses[0]


def read_tceq_response(
    client: httpx.Client, url: str, max_bytes: int, *, route: str
) -> tuple[httpx.Headers, bytes]:
    """Read a bounded TCEQ response, validating every redirect before its next hop."""
    if client.follow_redirects:
        raise SourceParseError("TCEQ client must not automatically follow redirects")
    current = _route(url, route)
    for hop in range(_MAX_REDIRECTS + 1):
        host = urlsplit(current).hostname or ""
        ip = _public_ip(host)
        # Connect to the validated IP while sending the official Host header
        # on this request only. The shared client header map is left unchanged.
        pinned_url = httpx.URL(current).copy_with(host=ip)
        try:
            headers, body = read_bounded_response(
                client,
                str(pinned_url),
                max_bytes,
                headers={"Host": host},
                extensions={"sni_hostname": host},
            )
        except httpx.HTTPStatusError as exc:
            response = exc.response
            if response.status_code not in {301, 302, 303, 307, 308} or hop == _MAX_REDIRECTS:
                raise
            location = response.headers.get("location")
            if not location:
                raise SourceParseError("TCEQ redirect has no destination") from exc
            current = _route(urljoin(current, location), route)
            continue
        media_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
        expected_type = "text/html" if route == "listing" else "application/pdf"
        if media_type != expected_type:
            raise SourceParseError("TCEQ response has an unexpected media type")
        if route in {"pdf", "record_pdf"} and not body.startswith(b"%PDF-"):
            raise SourceParseError("TCEQ document does not have a PDF signature")
        return headers, body
    raise SourceParseError("TCEQ redirect limit exceeded")
