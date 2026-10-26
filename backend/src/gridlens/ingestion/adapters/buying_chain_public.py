"""Bounded public-document reader for one selected project's buying-chain research.

No credentials, search crawl, registry entries or redirects. Resolve only global
addresses and pin the validated IP for the connection (including TLS SNI), so
DNS rebinding cannot turn an approved public hostname into a private request.
The optional deadline is shared and monotonic. Research acquisition runs in a
killable child so OS-controlled DNS and PDF parsing cannot outlive that budget.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from io import BytesIO
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup, NavigableString, Tag

from gridlens.ingestion.adapters.bounded_http import (
    ResponseTooLarge,
    read_bounded_response,
    remaining_seconds,
    run_isolated,
)

MAX_BYTES = 750_000
MAX_TEXT = 30_000
MAX_PAGES = 20
MAX_PERSON_CARDS = 20
CAPTURE_VERSION = "public-document-v3"


class PublicExtractionUnavailable(ValueError):
    """Successful public response needs rendering; eligible for bounded extraction."""


class PublicAccessRestricted(ValueError):
    """Access controls are terminal; never eligible for an acquisition fallback."""


def _bounded_text(text: str) -> str:
    if len(text) > MAX_TEXT:
        # Never admit a prefix: omitted text may contradict the claimed fact.
        raise ResponseTooLarge("Extracted document exceeds 30000 characters")
    return text


def _bounded_title(title: str) -> str:
    if len(title) > 500:
        raise ResponseTooLarge("Document title exceeds 500 characters")
    return title


def _pdf_document(url: str, body: bytes) -> PublicDocument:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(body), strict=True)
    if reader.is_encrypted:
        raise PublicAccessRestricted("encrypted_pdf")
    if not 1 <= len(reader.pages) <= MAX_PAGES:
        raise ResponseTooLarge("PDF exceeds 20 page bound")
    pages = []
    size = 0
    for number, page in enumerate(reader.pages, 1):
        resources = page.get("/Resources")
        if resources and resources.get_object().get("/XObject"):
            # Image/form objects can hide an adverse scanned update even when
            # a page number is extractable. No OCR or partial-page admission.
            raise ValueError("PDF contains unsupported image or form content")
        content = page.get_contents()
        if content is not None and any(
            operator
            in {b"INLINE IMAGE", b"S", b"s", b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*", b"sh"}
            for _, operator in content.operations
        ):
            raise ValueError("PDF contains unsupported image or vector-painted content")
        text = page.extract_text() or ""
        size += len(text)
        if size > MAX_TEXT:
            raise ResponseTooLarge("Extracted PDF exceeds 30000 characters")
        if not text.strip():
            # No OCR: an unseen scanned page could contain an adverse fact.
            raise ValueError("PDF contains a page without extractable text")
        pages.append(f"[Page {number}]\n{text.strip()}")
    text = _bounded_text("\n".join(pages))
    metadata = reader.metadata
    title = str(metadata.title) if metadata and metadata.title else "Public project document"
    return PublicDocument(
        url,
        _bounded_title(title),
        text,
        # PDF creation/modification metadata does not establish publication.
        extraction_location=f"PDF pages 1-{len(pages)} (inline page markers)",
    )


@dataclass(frozen=True)
class PublicPersonCard:
    """A bounded literal heading-to-contact association from one HTML container."""

    heading_text: str
    contact_text: str
    href: str
    name: str
    title: str


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
    capture_version: str = CAPTURE_VERSION
    person_cards: tuple[PublicPersonCard, ...] = ()


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
    if len(body) > MAX_BYTES:
        raise ResponseTooLarge("Document exceeds 750000 bytes")
    if "application/pdf" in content_type:
        return _pdf_document(url, body)
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
    # Retain explicit Organization directory data before removing script bodies.
    directory: list[dict] = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(script.get_text())
        except (ValueError, TypeError):
            continue
        entries = value if isinstance(value, list) else [value]
        for entry in entries:
            if isinstance(entry, dict):
                entries_graph = entry.get("@graph", [entry])
                if isinstance(entries_graph, list):
                    directory.extend(
                        row
                        for row in entries_graph
                        if isinstance(row, dict) and row.get("@type") == "Organization"
                    )
    directory = directory[:20]
    # Container selection is not evidence admission. A sibling update or footer
    # correction must not disappear merely because a positive claim is in main.
    for excluded in soup(["script", "style"]):
        excluded.decompose()
    # Preserve literal contact targets even when link text is "Email". Record a
    # person association only when one immediate container has exactly one
    # heading and one safe method anchor; page-wide proximity is not evidence.
    method_labels: dict[Tag, tuple[str, str]] = {}
    for anchor in soup.find_all("a", href=True):
        if not isinstance(anchor, Tag):
            continue
        href = str(anchor.get("href", ""))
        if href.lower().startswith(("mailto:", "tel:")):
            method_labels[anchor] = (anchor.get_text(" ", strip=True), href)
    cards: list[PublicPersonCard] = []
    for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        if not isinstance(heading, Tag):
            continue
        parent = heading.parent
        if not isinstance(parent, Tag):
            continue
        headings = [
            item
            for item in parent.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
            if isinstance(item, Tag)
        ]
        anchors = [
            anchor
            for anchor in parent.find_all("a", href=True)
            if isinstance(anchor, Tag) and anchor in method_labels
        ]
        if len(headings) != 1 or len(anchors) != 1:
            continue
        nested = [
            child
            for child in parent.find_all(["div", "section", "article"])
            if isinstance(child, Tag)
        ]
        if any(
            child.find(["h1", "h2", "h3", "h4", "h5", "h6"])
            or any(candidate in method_labels for candidate in child.find_all("a", href=True))
            for child in nested
        ):
            continue
        heading_text = heading.get_text(" ", strip=True)
        heading_match = re.fullmatch(
            r"(?P<name>[A-Z][A-Za-zÀ-ž'’.-]+(?:[ \t]+[A-Z][A-Za-zÀ-ž'’.-]+){1,3})"
            r",[ \t]*(?P<title>[^,\n]{3,80})",
            heading_text,
        )
        if not heading_match or len(heading_text) > 200:
            continue
        anchor = anchors[0]
        label, href = method_labels[anchor]
        href_match = re.fullmatch(
            r"mailto:([A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63})"
            r"|tel:(\+?[0-9(). -]{7,30})",
            href,
            re.I,
        )
        if not href_match or any(char in href for char in "\r\n?#"):
            continue
        value = href_match.group(1) or href_match.group(2)
        if not value or not label or len(label) > 120:
            continue
        first_name = heading_match.group("name").split()[0].casefold()
        label_match = re.fullmatch(
            r"Contact[ \t]+(?P<name>[A-Za-z'-]+)[ \t]+by[ \t]+(?P<kind>Email|Phone)",
            label,
            re.I,
        )
        accepted_names = {first_name}
        if first_name == "christopher":
            accepted_names.add("chris")
        if (
            not label_match
            or label_match.group("name").casefold() not in accepted_names
            or (label_match.group("kind").casefold() == "email")
            != href.lower().startswith("mailto:")
        ):
            continue
        contact_text = label if value in label else f"{label} {value}".strip()
        if len(contact_text) > 200:
            continue
        cards.append(
            PublicPersonCard(
                heading_text=heading_text,
                contact_text=contact_text,
                href=href,
                name=heading_match.group("name"),
                title=heading_match.group("title").strip(),
            )
        )
        if len(cards) > MAX_PERSON_CARDS:
            raise ResponseTooLarge("Page exceeds 20 explicit person-contact cards")
    for anchor in soup.find_all("a", href=True):
        if not isinstance(anchor, Tag):
            continue
        href = str(anchor["href"])
        if href.lower().startswith(("mailto:", "tel:")):
            value = href.split(":", 1)[1].split("?", 1)[0]
            if value and not any(c in value for c in "\r\n"):
                label = anchor.get_text(" ", strip=True)
                anchor.replace_with(
                    NavigableString(label if value in label else f"{label} {value}".strip())
                )
    main = soup.body or soup
    text = "\n".join(
        line.strip() for line in main.get_text("\n", strip=True).splitlines() if line.strip()
    )
    cards = [card for card in cards if card.heading_text in text and card.contact_text in text]
    if directory:
        text += "\n" + "\n".join(
            json.dumps(row, sort_keys=True, ensure_ascii=False) for row in directory
        )
    body_restricted = bool(
        re.search(
            r"access denied|access forbidden|captcha|verify (?:you are|that you are) human|"
            r"(?:sign|log) in to (?:view|access)|login required",
            text,
            re.I,
        )
    ) or bool(soup.select('input[type="password"]'))
    if len(text) < 150 and re.search(r"\b(?:sign in|log in|login)\b", text, re.I):
        body_restricted = True
    if body_restricted or any(
        marker in title.casefold()
        for marker in (
            "access denied",
            "just a moment",
            "verify you are human",
            "sign in",
            "captcha",
        )
    ):
        raise PublicAccessRestricted("public_access_restricted")
    if len(text) < 30:
        # Only an explicit public JavaScript shell is eligible for rendering.
        raw = body.decode("utf-8", errors="replace").casefold()
        if "javascript" in raw and any(
            marker in raw for marker in ("enable javascript", "requires javascript")
        ):
            raise PublicExtractionUnavailable("javascript_rendering_required")
        raise ValueError("Source did not return usable public content")
    extraction_location = "public page text"
    if cards:
        card_data = [
            {
                "heading_text": card.heading_text,
                "contact_text": card.contact_text,
                "href": card.href,
                "name": card.name,
                "title": card.title,
            }
            for card in cards
        ]
        card_digest = hashlib.sha256(
            json.dumps(card_data, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        extraction_location += f"; pcards:{card_digest}"
    return PublicDocument(
        url,
        _bounded_title(title),
        _bounded_text(text),
        published,
        links=tuple(dict.fromkeys(links))[:2],
        structured=tuple(directory),
        extraction_location=extraction_location,
        person_cards=tuple(cards),
    )


def retrieve(
    url: str, *, deadline: float | None = None, max_bytes: int = MAX_BYTES
) -> PublicDocument:
    return run_isolated(
        "gridlens.ingestion.adapters.buying_chain_public:_retrieve_direct",
        (url,),
        {"deadline": deadline, "max_bytes": max_bytes},
        deadline=deadline if deadline is not None else time.monotonic() + 30,
    )


def _retrieve_direct(
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
