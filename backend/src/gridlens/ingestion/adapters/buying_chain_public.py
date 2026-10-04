"""Bounded public-document reader for one selected project's buying-chain research.

No credentials, search crawl, registry entries or redirects. Resolve only global
addresses and pin the validated IP for the connection (including TLS SNI), so
DNS rebinding cannot turn an approved public hostname into a private request.
The optional deadline is shared and monotonic. System DNS resolution is a soft
bound: synchronous getaddrinfo is OS-controlled and cannot be interrupted here;
expiry is checked immediately after it returns, before opening a connection.
"""

from __future__ import annotations

import ipaddress
import json
import socket
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup, Tag

from gridlens.ingestion.adapters.bounded_http import read_bounded_response, remaining_seconds

MAX_BYTES = 750_000
MAX_TEXT = 30_000


@dataclass(frozen=True)
class PublicDocument:
    url: str
    title: str
    text: str
    published_at: date | None = None
    observed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    extraction_location: str = "public page text"
    links: tuple[str, ...] = ()
    structured: tuple[dict, ...] = ()
    retained_version: str | None = None


def validate_public_url(url: str) -> str:
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.port not in (None, 443)
        or len(url) > 2000
    ):
        raise ValueError("Only credential-free public HTTPS URLs are supported")
    host = parts.hostname.casefold()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("Private destinations are not allowed")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("Private destinations are not allowed")
    return urlunsplit(("https", parts.netloc, parts.path or "/", parts.query, ""))


def _public_ip(host: str) -> str:
    answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    addresses = sorted({str(answer[4][0]) for answer in answers})
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise ValueError("Destination does not resolve exclusively to public addresses")
    return addresses[0]


def _date(raw: object) -> date | None:
    try:
        parsed = date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None
    return parsed if parsed <= datetime.now(UTC).date() else None


def parse_document(url: str, body: bytes, content_type: str) -> PublicDocument:
    if "json" in content_type:
        data = json.loads(body)
        if isinstance(data, dict):
            data = [data]
        if (
            not isinstance(data, list)
            or len(data) > 5
            or not all(isinstance(r, dict) for r in data)
        ):
            raise ValueError("Expected a bounded exact-record JSON result")
        text = json.dumps(data, sort_keys=True, ensure_ascii=False)
        if len(text) > MAX_TEXT:
            raise ValueError("Record text exceeds research bound")
        return PublicDocument(
            url,
            "Official project record",
            text,
            None,  # Permit issue_date is an event date, not a publication date.
            extraction_location="official exact-record JSON",
            structured=tuple(data),
        )
    if "html" not in content_type and "text/plain" not in content_type:
        raise ValueError("Only public HTML/text and exact-record JSON are supported")
    soup = BeautifulSoup(body, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else "Public project source"
    published = None
    # Calendars, conference listings and generic page dates are not publication
    # evidence and must not refresh an archived person's employment claim.
    for node in soup.select('meta[property="article:published_time"],[itemprop~="datePublished"]'):
        published = _date(node.get("content") or node.get("datetime"))
        if published:
            break
    links = []
    for anchor in soup.find_all("a", href=True):
        if not isinstance(anchor, Tag):
            continue
        href = anchor.get("href")
        if not isinstance(href, str):
            continue
        link = urljoin(url, href)
        label = anchor.get_text(" ", strip=True).casefold()
        if urlsplit(link).hostname == urlsplit(url).hostname and any(
            term in label for term in ("team", "leadership", "management", "contact")
        ):
            try:
                links.append(validate_public_url(link))
            except ValueError:
                pass
    for excluded in soup(["script", "style", "nav", "footer", "header", "noscript", "form"]):
        excluded.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = "\n".join(
        line.strip() for line in main.get_text("\n", strip=True).splitlines() if line.strip()
    )
    if len(text) < 30 or any(
        marker in title.casefold()
        for marker in (
            "access denied",
            "just a moment",
            "verify you are human",
            "sign in",
            "captcha",
        )
    ):
        raise ValueError("Source did not return usable public content")
    return PublicDocument(
        url, title[:500], text[:MAX_TEXT], published, links=tuple(dict.fromkeys(links))[:2]
    )


def retrieve(
    url: str, *, deadline: float | None = None, max_bytes: int = MAX_BYTES
) -> PublicDocument:
    remaining_seconds(deadline)
    url = validate_public_url(url)
    host = urlsplit(url).hostname
    assert host is not None
    ip = _public_ip(host)
    remaining = remaining_seconds(deadline)
    pinned = httpx.URL(url).copy_with(host=ip)
    # SNI keeps certificate validation against the original host, not the IP.
    with httpx.Client(
        timeout=httpx.Timeout(min(7.0, remaining) if remaining is not None else 7.0),
        follow_redirects=False,
        trust_env=False,
        headers={"Host": host, "User-Agent": "GridLens project research/1.0"},
    ) as client:
        headers, body = read_bounded_response(
            client,
            str(pinned),
            min(max_bytes, MAX_BYTES),
            extensions={"sni_hostname": host},
            deadline=deadline,
        )
    remaining_seconds(deadline)
    document = parse_document(url, body, headers.get("content-type", ""))
    remaining_seconds(deadline)
    return document
