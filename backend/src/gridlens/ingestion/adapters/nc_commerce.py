"""Bounded reader for the NC Commerce press-release listing and articles."""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urljoin, urlparse, urlunsplit

import httpx
from bs4 import BeautifulSoup

from gridlens.ingestion.adapters.bounded_http import ResponseTooLarge, read_bounded_response
from gridlens.ingestion.adapters.federal_register import SourceParseError

_HOST = "www.commerce.nc.gov"
_LIST_PATH = "/news/press-releases"
_ARTICLE_PATH = re.compile(r"^/news/press-releases/\d{4}/\d{2}/\d{2}/[^/?#]+$")
_MAX_ARTICLE_EXCERPT = 700


def _allowed_url(url: str, path: str | None = None) -> bool:
    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == _HOST
        and parsed.username is None
        and parsed.password is None
        and port in (None, 443)
        and (path is None or parsed.path == path)
    )


def _next_page(soup: BeautifulSoup, current: str) -> str | None:
    link = soup.select_one('a[rel="next"], .pager__item--next a')
    if link is None or not link.get("href"):
        return None
    target = urljoin(current, str(link["href"]))
    parsed = urlparse(target)
    if not _allowed_url(target) or parsed.path != _LIST_PATH:
        raise SourceParseError("NC Commerce pagination target is outside the listing")
    return target


def _listing_rows(soup: BeautifulSoup) -> list[dict[str, str]]:
    rows = soup.select(".view-content .views-row")
    if not rows:
        raise SourceParseError("NC Commerce listing has no article rows")
    result = []
    for row in rows:
        anchor = row.select_one(".views-field-title a[href]")
        when = row.select_one('.views-field-field-release-date [property="content"]')
        if when is None:
            when = row.select_one(".views-field-field-release-date [content]")
        if anchor is None or when is None:
            raise SourceParseError("NC Commerce listing row lacks title URL or publication date")
        title, href = anchor.get_text(" ", strip=True), str(anchor["href"])
        # Drupal's listing occasionally exposes this one encoded front-controller
        # prefix. Strip only that exact known prefix; do not unquote arbitrary paths.
        if any(ord(char) < 0x20 or ord(char) == 0x7F for char in href):
            raise SourceParseError("NC Commerce listing has a malformed article")
        raw_parts = urlparse(href)
        path = raw_parts.path
        prefix = "/index%2ephp/news/press-releases/"
        if path.startswith(prefix):
            path = "/news/press-releases/" + path[len(prefix) :]
        normalized_href = (
            urlunsplit(
                (raw_parts.scheme, raw_parts.netloc, path, raw_parts.query, raw_parts.fragment)
            )
            if raw_parts.netloc or raw_parts.scheme
            else path
        )
        resolved = urljoin(f"https://{_HOST}/", normalized_href)
        parsed = urlparse(resolved)
        if (
            not title
            or raw_parts.query
            or raw_parts.fragment
            or any(segment in {".", ".."} for segment in raw_parts.path.split("/"))
            or not _ARTICLE_PATH.fullmatch(path)
            or not _allowed_url(resolved)
            or parsed.query
            or parsed.fragment
            or re.search(r"%(?:2f|5c|2e|0[0-9a-f]|1[0-9a-f])", path, re.IGNORECASE)
        ):
            raise SourceParseError("NC Commerce listing has a malformed article")
        try:
            published = date.fromisoformat(str(when.get("content")))
        except ValueError as exc:
            raise SourceParseError("NC Commerce listing publication date is malformed") from exc
        intro = row.select_one(".views-field-body .field-content")
        result.append(
            {
                "title": title,
                "url": resolved,
                "source_href": href,
                "publication_date": published.isoformat(),
                "listing_excerpt": intro.get_text(" ", strip=True) if intro else "",
            }
        )
    return result


def _parse_article(html: bytes, expected: dict[str, str], url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    page_title = soup.title.get_text() if soup.title else ""
    if (
        soup.select_one("form#user-login-form, form.user-login-form")
        or "Log in | NC Commerce" in page_title
    ):
        raise SourceParseError("NC Commerce returned a login page")
    heading = soup.select_one("h1.node__title")
    published = soup.select_one(".first-published time[datetime]")
    if published is None:
        published = soup.select_one(
            ".first-published [property='content'], .first-published [content]"
        )
    if published is None:
        published = soup.select_one(".first-published .field--name-field-release-date .field__item")
    if published is None:
        published = soup.select_one("article .field--name-field-release-date.field__item")
    body_node = soup.select_one("article .field--name-body")
    if heading is None or published is None or body_node is None:
        raise SourceParseError("NC Commerce article structure is incomplete")
    title = heading.get_text(" ", strip=True)
    if title != expected["title"]:
        raise SourceParseError("NC Commerce listing and article titles differ")
    try:
        value = (
            published.get("datetime")
            or published.get("content")
            or published.get_text(" ", strip=True)
        )
        try:
            published_date = date.fromisoformat(str(value)[:10])
        except ValueError:
            published_date = datetime.strptime(str(value), "%b %d, %Y").date()
    except ValueError as exc:
        raise SourceParseError("NC Commerce article publication date is malformed") from exc
    if published_date.isoformat() != expected["publication_date"]:
        raise SourceParseError("NC Commerce listing and article dates differ")
    paragraphs = [p.get_text(" ", strip=True) for p in body_node.select("p")]
    paragraphs = [re.sub(r"\s+", " ", text).strip() for text in paragraphs if text.strip()]
    if not paragraphs:
        raise SourceParseError("NC Commerce article body is empty")
    full_text = "\n".join(paragraphs)
    excerpt = " ".join(paragraphs[:2])[:_MAX_ARTICLE_EXCERPT].strip()
    source_hash = hashlib.sha256(
        (title + "\n" + expected["publication_date"] + "\n" + full_text).encode()
    ).hexdigest()
    canonical = soup.select_one('link[rel="canonical"]')
    canonical_url = (
        urljoin(url, str(canonical["href"])) if canonical and canonical.get("href") else url
    )
    if not _allowed_url(canonical_url) or urlparse(canonical_url).path != urlparse(url).path:
        raise SourceParseError("NC Commerce canonical article URL is invalid")
    return {
        "document_number": urlparse(canonical_url).path,
        "title": title,
        "abstract": excerpt,
        "publication_date": published_date.isoformat(),
        "html_url": canonical_url,
        # Keep the publisher's exact href alongside the normalized fetch URL.
        "source_url": expected.get("source_href", url),
        "source_hash": source_hash,
        "extraction_location": "article body paragraphs 1-2",
    }


def retrieve(source: dict[str, Any], client: httpx.Client | None = None) -> list[dict[str, Any]]:
    own_client = client is None
    client = client or httpx.Client(timeout=25.0, follow_redirects=False)
    query = source.get("query", {})
    max_pages = query.get("max_pages")
    window_days = query.get("window_days")
    max_articles = query.get("max_articles")
    max_response_bytes = query.get("max_response_bytes")
    max_run_bytes = query.get("max_run_bytes")
    if (
        not isinstance(max_pages, int)
        or not 1 <= max_pages <= 20
        or not isinstance(window_days, int)
        or not 1 <= window_days <= 90
        or not isinstance(max_articles, int)
        or not 1 <= max_articles <= 300
        or not isinstance(max_response_bytes, int)
        or not 1024 <= max_response_bytes <= 5_000_000
        or not isinstance(max_run_bytes, int)
        or not max_response_bytes <= max_run_bytes <= 100_000_000
    ):
        raise SourceParseError("NC Commerce bounded listing configuration is invalid")
    cutoff = date.today() - timedelta(days=window_days)
    page_url = source["endpoint"]
    if not _allowed_url(page_url, _LIST_PATH):
        raise SourceParseError("NC Commerce endpoint is not allowlisted")
    seen_pages: set[str] = set()
    candidates: dict[str, dict[str, str]] = {}
    listing_rows_seen = 0
    bytes_seen = 0
    prior_page_oldest: date | None = None
    try:
        complete = False
        for _page_number in range(1, max_pages + 1):
            if page_url in seen_pages:
                raise SourceParseError("NC Commerce listing pagination loop detected")
            seen_pages.add(page_url)
            try:
                _, content = read_bounded_response(client, page_url, max_response_bytes)
            except ResponseTooLarge as exc:
                raise SourceParseError(str(exc)) from exc
            bytes_seen += len(content)
            if bytes_seen > max_run_bytes:
                raise SourceParseError("NC Commerce response bytes exceed the configured run bound")
            soup = BeautifulSoup(content, "html.parser")
            if soup.select_one("form#user-login-form, form.user-login-form"):
                raise SourceParseError("NC Commerce returned a login page")
            page_rows = _listing_rows(soup)
            listing_rows_seen += len(page_rows)
            if listing_rows_seen > max_articles:
                raise SourceParseError(
                    f"NC Commerce listing exceeds the {max_articles}-article run bound"
                )
            dates = [date.fromisoformat(row["publication_date"]) for row in page_rows]
            if dates != sorted(dates, reverse=True):
                raise SourceParseError("NC Commerce listing is not newest-first")
            if prior_page_oldest is not None and max(dates) > prior_page_oldest:
                raise SourceParseError(
                    "NC Commerce pagination changed or reordered the listing window"
                )
            prior_page_oldest = min(dates)
            for row in page_rows:
                if date.fromisoformat(row["publication_date"]) >= cutoff:
                    candidates[row["url"]] = row
            if min(dates) < cutoff:
                complete = True
                break
            next_url = _next_page(soup, page_url)
            if next_url is None:
                complete = True
                break
            page_url = next_url
        if not complete:
            raise SourceParseError(
                f"NC Commerce collection window exceeds {max_pages} listing pages"
            )
        if not candidates:
            raise SourceParseError(
                "NC Commerce returned no articles in the declared collection window"
            )
        articles = []
        for row in candidates.values():
            try:
                _, content = read_bounded_response(client, row["url"], max_response_bytes)
            except ResponseTooLarge as exc:
                raise SourceParseError(str(exc)) from exc
            bytes_seen += len(content)
            if bytes_seen > max_run_bytes:
                raise SourceParseError("NC Commerce response bytes exceed the configured run bound")
            articles.append(_parse_article(content, row, row["url"]))
        return articles
    finally:
        if own_client:
            client.close()
