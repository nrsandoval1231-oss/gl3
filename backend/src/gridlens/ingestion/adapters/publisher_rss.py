"""Bounded collection of publisher RSS snapshots; article pages are never fetched."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree

import httpx

from gridlens.ingestion.adapters.bounded_http import ResponseTooLarge, read_bounded_response
from gridlens.ingestion.adapters.federal_register import SourceParseError

RSS_HOSTS = {
    "dcd-news": "www.datacenterdynamics.com",
    "utility-dive-news": "www.utilitydive.com",
    "manufacturing-dive-news": "www.manufacturingdive.com",
    "construction-dive-news": "www.constructiondive.com",
    "ogj-exploration-news": "www.ogj.com",
    "mjbizdaily-news": "mjbizdaily.com",
}
MAX_SUMMARY = 500


class RSSSnapshot(list[dict[str, Any]]):
    """List-compatible RSS result carrying only response cache metadata."""

    def __init__(
        self,
        records: list[dict[str, Any]] | None = None,
        *,
        not_modified: bool = False,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> None:
        super().__init__(records or [])
        self.not_modified = not_modified
        self.etag = etag
        self.last_modified = last_modified


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _text(value: str | None) -> str:
    parser = _Text()
    parser.feed(value or "")
    return " ".join(" ".join(parser.parts).split())


def _child(element: ElementTree.Element, name: str) -> str | None:
    wanted = name.casefold()
    if wanted == "link":
        for child in element:
            if child.tag.rsplit("}", 1)[-1].casefold() == wanted and child.attrib.get("href"):
                if child.attrib.get("rel", "alternate").casefold() == "alternate":
                    return child.attrib["href"].strip()
    for child in element:
        if child.tag.rsplit("}", 1)[-1].casefold() == wanted:
            if wanted == "link" and child.attrib.get("href"):
                continue
            value = "".join(child.itertext()).strip()
            if value:
                return value
    return None


def _published(raw: str | None) -> tuple[datetime, str]:
    if not raw:
        raise SourceParseError("RSS item is missing its publication date")
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            value = parsedate_to_datetime(raw)
        except (TypeError, ValueError, OverflowError) as exc:
            raise SourceParseError("RSS publication date is malformed") from exc
    if value.tzinfo is None:
        raise SourceParseError("RSS publication date has no timezone")
    if value.astimezone(UTC) > datetime.now(UTC):
        raise SourceParseError("RSS publication date is in the future")
    return value, value.date().isoformat()


def _canonical_link(raw: str | None, endpoint: str, host: str) -> str:
    if not raw:
        raise SourceParseError("RSS item is missing its canonical link")
    value = urljoin(endpoint, raw.strip())
    parts = urlsplit(value)
    if (
        parts.scheme != "https"
        or parts.hostname != host
        or parts.username is not None
        or parts.password is not None
        or parts.port not in (None, 443)
    ):
        raise SourceParseError("RSS item link is unsafe or off-host")
    return urlunsplit(("https", host, parts.path or "/", parts.query, ""))


def _identity(link: str) -> str:
    identity = link.strip()
    if not identity:
        raise SourceParseError("RSS item is missing a stable identity")
    if len(identity) > 200:
        return "sha256:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return identity


def _items(root: ElementTree.Element) -> list[ElementTree.Element]:
    for link in root.iter():
        if link.tag.rsplit("}", 1)[-1].casefold() == "link" and link.attrib.get("rel") == "next":
            raise SourceParseError("RSS continuation is unsupported; snapshot may be incomplete")
    local = root.tag.rsplit("}", 1)[-1].casefold()
    if local == "rss":
        channel = next(
            (node for node in root if node.tag.rsplit("}", 1)[-1].casefold() == "channel"),
            None,
        )
        if channel is None:
            raise SourceParseError("RSS channel is missing")
        entries = [node for node in channel if node.tag.rsplit("}", 1)[-1].casefold() == "item"]
    elif local == "feed":
        entries = [node for node in root if node.tag.rsplit("}", 1)[-1].casefold() == "entry"]
    else:
        raise SourceParseError("Response is not an RSS or Atom feed")
    return entries


def retrieve(source: dict[str, Any], client: httpx.Client | None = None) -> RSSSnapshot:
    source_id = source["id"]
    host = RSS_HOSTS.get(source_id)
    endpoint = source["endpoint"]
    if host is None or urlsplit(endpoint).scheme != "https" or urlsplit(endpoint).hostname != host:
        raise SourceParseError("RSS endpoint is outside the exact publisher allowlist")
    query = source["query"]
    own_client = client is None
    client = client or httpx.Client(timeout=25.0, follow_redirects=False)
    try:
        try:
            conditional = bool(
                client.headers.get("If-None-Match") or client.headers.get("If-Modified-Since")
            )
            headers, body, status = read_bounded_response(
                client,
                endpoint,
                query["max_response_bytes"],
                allow_not_modified=True,
            )
            if status == 304:
                if not conditional:
                    raise SourceParseError("RSS returned 304 without a conditional request")
                return RSSSnapshot(
                    not_modified=True,
                    etag=headers.get("etag"),
                    last_modified=headers.get("last-modified"),
                )
        except ResponseTooLarge as exc:
            raise SourceParseError(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise SourceParseError(f"RSS retrieval failed: {type(exc).__name__}") from exc
        content_type = headers.get("content-type", "").casefold()
        has_xml_type = any(value in content_type for value in ("xml", "rss", "atom"))
        if "html" in content_type or not has_xml_type:
            raise SourceParseError("RSS response has an unexpected content type")
        try:
            xml_text = body.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise SourceParseError("RSS XML must use UTF-8 encoding") from exc
        if "\x00" in xml_text:
            raise SourceParseError("RSS XML contains unsupported NUL bytes")
        upper = xml_text.upper()
        if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
            raise SourceParseError("RSS unsafe XML declarations are not allowed")
        if re.search(r"<\s*(?:html|!doctype)\b", xml_text[:4096], re.IGNORECASE):
            raise SourceParseError("RSS response contains login or HTML content")
        try:
            root = ElementTree.fromstring(xml_text)
        except ElementTree.ParseError as exc:
            raise SourceParseError("RSS response is malformed XML") from exc
        entries = _items(root)
        if not entries:
            raise SourceParseError("RSS publisher snapshot unexpectedly contains no items")
        if len(entries) > query["max_items"]:
            raise SourceParseError("RSS item count exceeds the configured snapshot bound")
        results: dict[str, dict[str, Any]] = {}
        for entry in entries:
            title = _text(_child(entry, "title"))
            raw_link = _child(entry, "link")
            link = _canonical_link(raw_link, endpoint, host)
            # Canonical item URLs are stable across publisher GUID corrections.
            identity = _identity(link)
            raw_date = (
                _child(entry, "pubDate") or _child(entry, "published") or _child(entry, "updated")
            )
            _, published = _published(raw_date)
            assert raw_date is not None
            summary = _text(_child(entry, "description") or _child(entry, "summary"))[:MAX_SUMMARY]
            if not title:
                raise SourceParseError("RSS item is missing its title")
            record = {
                "document_number": identity,
                "title": title,
                "abstract": summary,
                "publication_date": published,
                "html_url": link,
                "extraction_location": ("RSS title/summary; original published " + raw_date[:55]),
            }
            record["source_hash"] = hashlib.sha256(
                (
                    identity
                    + "\n"
                    + title
                    + "\n"
                    + summary
                    + "\n"
                    + published
                    + "\n"
                    + raw_date
                    + "\n"
                    + link
                ).encode("utf-8")
            ).hexdigest()
            prior = results.get(identity)
            if prior is not None and prior != record:
                raise SourceParseError("RSS feed contains conflicting duplicate item identities")
            results[identity] = record
        return RSSSnapshot(
            list(results.values()),
            etag=headers.get("etag"),
            last_modified=headers.get("last-modified"),
        )
    finally:
        if own_client:
            client.close()
