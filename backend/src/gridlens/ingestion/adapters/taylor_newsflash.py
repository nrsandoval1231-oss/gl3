"""Bounded, fail-closed reader for Taylor CivicPlus Development News/Notices."""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from gridlens.ingestion.adapters.bounded_http import ResponseTooLarge, read_bounded_response
from gridlens.ingestion.adapters.federal_register import SourceParseError

_HOST = "taylortx.gov"
_ROOT = "https://taylortx.gov/m/NewsFlash"
_ARTICLE = re.compile(r"^/m/NewsFlash/Home/Detail/(\d+)$")
_ARCHIVE_ITEM = re.compile(r"^/m/NewsFlash/Archive/Item/(\d+)$")
_REVISION = re.compile(r"^\d+$")
_LABELS = {"30": "Development News", "31": "Development Notices"}
_EVIDENCE_LOCATION_MAX = 100


def _evidence_location(category: str, *, archive: bool = False) -> str:
    location = f"header/body; category: {category}"
    if archive:
        location += "; table dates"
    if len(location) > _EVIDENCE_LOCATION_MAX:
        raise SourceParseError("Taylor category badge exceeds evidence location field bound")
    return location


def _archive_interval(query: dict[str, Any], cutoff: date) -> tuple[str, str]:
    window_days, overlap_days = query.get("archive_window_days"), query.get("archive_overlap_days")
    if (
        not isinstance(window_days, int)
        or not 1 <= window_days <= 90
        or not isinstance(overlap_days, int)
        or not 0 <= overlap_days <= 14
        or window_days + overlap_days > 90
    ):
        raise SourceParseError("Taylor bounded archive window configuration is invalid")
    start = cutoff - timedelta(days=window_days + overlap_days - 1)
    return start.isoformat(), cutoff.isoformat()


def _get(client: httpx.Client, url: str, limit: int) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != _HOST:
        raise SourceParseError("Taylor URL is outside the official host")
    try:
        _, content = read_bounded_response(client, url, limit)
    except ResponseTooLarge as exc:
        raise SourceParseError(str(exc)) from exc
    soup = BeautifulSoup(content, "html.parser")
    if soup.select_one("form#user-login-form, form[action*='Login']"):
        raise SourceParseError("Taylor returned a login page")
    return content


def _article(content: bytes, url: str, article_id: str, arc_id: str | None) -> dict[str, Any]:
    soup = BeautifulSoup(content, "html.parser")
    heading = soup.select_one("main h1.article-header-title")
    body = soup.select_one("main .article-content")
    text = body.get_text(" ", strip=True) if body is not None else ""
    category_nodes = soup.select("main .articles-category:not(.article-footer) > .article-badge")
    if (
        heading is None
        or heading.get_text(" ", strip=True).casefold() == "news flash"
        or body is None
        or not text.strip()
    ):
        raise SourceParseError("Taylor article structure is incomplete")
    if len(category_nodes) != 1:
        raise SourceParseError("Taylor article category badge is missing or ambiguous")
    category = category_nodes[0].get_text(" ", strip=True)
    if not category:
        raise SourceParseError("Taylor article category badge is empty")
    category_header = category_nodes[0].parent
    if category_header is None:
        raise SourceParseError("Taylor article category header is incomplete")
    title = heading.get_text(" ", strip=True)
    published = None
    posted = re.search(
        r"\bPosted on\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})",
        category_header.get_text(" ", strip=True),
    )
    if posted:
        try:
            published = datetime.strptime(posted.group(1), "%B %d, %Y").date().isoformat()
        except ValueError as exc:
            raise SourceParseError("Taylor posted date is malformed") from exc
    date_candidates = category_header.select("time[datetime], .publishDate")
    if soup.head is not None:
        date_candidates.extend(
            soup.head.select("[property='article:published_time'], meta[name='date']")
        )
    for candidate in date_candidates:
        if published:
            break
        value = (
            candidate.get("datetime")
            or candidate.get("content")
            or candidate.get_text(" ", strip=True)
        )
        match = re.search(r"\d{4}-\d{2}-\d{2}", str(value))
        if match:
            try:
                published = date.fromisoformat(match.group()).isoformat()
            except ValueError as exc:
                raise SourceParseError("Taylor article metadata date is malformed") from exc
            break
    if published is None:
        # CivicPlus pages may render a date in the article header as MM/DD/YYYY.
        match = re.search(
            r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b",
            category_header.get_text(" ", strip=True),
        )
        if match:
            published = date(
                int(match.group(3)), int(match.group(1)), int(match.group(2))
            ).isoformat()
    if published is None:
        raise SourceParseError("Taylor article publication date is missing or malformed")
    disposition = "withdrawn" if re.search(r"\bwithdrawn\b", title, re.I) else None
    identity = f"{article_id}:arcId={arc_id}" if arc_id else article_id
    return {
        "document_number": identity,
        "article_id": article_id,
        "archive_revision_id": arc_id,
        "title": title,
        "abstract": text[:1800],
        "publication_date": published,
        "event_date": None,
        "archived_date": None,
        "html_url": url,
        "source_hash": hashlib.sha256(content).hexdigest(),
        "extraction_location": _evidence_location(category),
        "category": category,
        "disposition": disposition,
    }


def retrieve(
    source: dict[str, Any],
    client: httpx.Client | None = None,
    *,
    today: date | None = None,
) -> list[dict[str, Any]]:
    query = source.get("query", {})
    end_date = today or date.today()
    start, end = _archive_interval(query, end_date)
    own_client = client is None
    client = client or httpx.Client(timeout=25, follow_redirects=False)
    count, max_pages = query.get("archive_count"), query.get("max_pages")
    limit, max_run = query.get("max_response_bytes"), query.get("max_run_bytes")
    if (
        count not in {10, 25, 50}
        or not isinstance(max_pages, int)
        or not 1 <= max_pages <= 20
        or not isinstance(limit, int)
        or not 1024 <= limit <= 5_000_000
        or not isinstance(max_run, int)
        or not limit <= max_run <= 100_000_000
    ):
        raise SourceParseError("Taylor bounded archive configuration is invalid")
    try:
        bytes_seen = 0
        rows: dict[str, dict[str, Any]] = {}
        for category_id, _category in _LABELS.items():
            content = _get(client, f"{_ROOT}?cat={category_id}", limit)
            bytes_seen += len(content)
            soup = BeautifulSoup(content, "html.parser")
            links = soup.select("a[href^='/m/NewsFlash/Home/Detail/']")
            if not links:
                raise SourceParseError(f"Taylor category {category_id} has no article links")
            for link in links:
                match = _ARTICLE.fullmatch(urlparse(str(link.get("href", ""))).path)
                if match:
                    article_id = match.group(1)
                    url = urljoin(_ROOT, str(link["href"]))
                    article_content = _get(client, url, limit)
                    bytes_seen += len(article_content)
                    record = _article(article_content, url, article_id, None)
                    record["source_geography"] = source.get("geography")
                    rows[record["document_number"]] = record
                if bytes_seen > max_run:
                    raise SourceParseError("Taylor response bytes exceed configured run bound")

        archive_ids: list[tuple[str, str]] = []
        archive_dates: dict[tuple[str, str], tuple[str, str]] = {}
        total: int | None = None
        offset = 0
        terminal = False
        for _ in range(max_pages):
            params = urlencode(
                {"archCc": 2, "startDate": start, "endDate": end, "count": count, "skip": offset}
            )
            url = f"{_ROOT}/Archive?{params}"
            content = _get(client, url, limit)
            bytes_seen += len(content)
            soup = BeautifulSoup(content, "html.parser")
            table = soup.select_one("#archiveTable")
            if table is None:
                raise SourceParseError("Taylor archive table is missing")
            summary = soup.get_text(" ", strip=True)
            page_range = re.search(r"(\d+)\s*[-–]\s*(\d+)\s+of\s+(\d+)", summary, re.I)
            if page_range is None:
                raise SourceParseError("Taylor archive page bounds/total are missing")
            first, last, page_total = map(int, page_range.groups())
            if total is None:
                total = page_total
            if page_total != total or first != offset + 1 or last < first:
                raise SourceParseError("Taylor archive total or contiguous page bounds changed")
            page_pairs: list[tuple[str, str]] = []
            for row in table.select("tbody tr"):
                archive_link = row.select_one("a[href*='/NewsFlash/Archive/Item/']")
                cells = row.select("td")
                if archive_link is None or len(cells) < 3:
                    raise SourceParseError("Taylor archive row is incomplete")
                parsed = urlparse(str(archive_link.get("href", "")))
                item = _ARCHIVE_ITEM.fullmatch(parsed.path)
                arc_id = (
                    parsed.query.split("arcId=", 1)[1].split("&", 1)[0]
                    if "arcId=" in parsed.query
                    else ""
                )
                if item is None or not _REVISION.fullmatch(arc_id):
                    raise SourceParseError("Taylor archive item/revision identity is malformed")
                page_pairs.append((item.group(1), arc_id))
                try:
                    archive_dates[(item.group(1), arc_id)] = tuple(
                        datetime.strptime(cell.get_text(" ", strip=True)[:19], "%m/%d/%Y %I:%M %p")
                        .date()
                        .isoformat()
                        for cell in cells[1:3]
                    )  # type: ignore[assignment]
                except ValueError as exc:
                    raise SourceParseError(
                        "Taylor archive publication/archive date is malformed"
                    ) from exc
            if len(page_pairs) != last - first + 1:
                raise SourceParseError(
                    "Taylor archive row count does not match displayed page range"
                )
            archive_ids.extend(page_pairs)
            next_link = soup.select_one("[aria-label='Next Page']")
            disabled = next_link is not None and (
                next_link.has_attr("disabled") or next_link.get("aria-disabled") == "true"
            )
            if last == total:
                if not disabled:
                    raise SourceParseError("Taylor terminal archive page is not disabled")
                terminal = True
                break
            if disabled:
                raise SourceParseError("Taylor archive ended before the reported total")
            offset += count
            if bytes_seen > max_run:
                raise SourceParseError("Taylor response bytes exceed configured run bound")
        if (
            not terminal
            or total is None
            or len(archive_ids) != total
            or len(set(archive_ids)) != total
        ):
            raise SourceParseError("Taylor archive sweep is incomplete or has duplicate identities")

        first_params = urlencode(
            {"archCc": 2, "startDate": start, "endDate": end, "count": count, "skip": 0}
        )
        first_url = f"{_ROOT}/Archive?{first_params}"
        replay_content = _get(client, first_url, limit)
        bytes_seen += len(replay_content)
        if bytes_seen > max_run:
            raise SourceParseError("Taylor response bytes exceed configured run bound")
        replay = BeautifulSoup(replay_content, "html.parser")
        replay_range = re.search(
            r"(\d+)\s*[-–]\s*(\d+)\s+of\s+(\d+)", replay.get_text(" ", strip=True), re.I
        )
        if replay_range is None or int(replay_range.group(3)) != total:
            raise SourceParseError("Taylor archive first-page replay total changed")
        replay_pairs = []
        for link in replay.select("#archiveTable a[href*='/NewsFlash/Archive/Item/']"):
            path = urlparse(str(link.get("href"))).path
            match = _ARCHIVE_ITEM.fullmatch(path)
            parsed = urlparse(str(link.get("href")))
            arc = (
                parsed.query.split("arcId=", 1)[1].split("&", 1)[0]
                if "arcId=" in parsed.query
                else ""
            )
            if match and _REVISION.fullmatch(arc):
                replay_pairs.append((match.group(1), arc))
        if replay_pairs != archive_ids[:count]:
            raise SourceParseError("Taylor archive first-page replay identity set changed")

        for article_id, arc_id in archive_ids:
            url = f"{_ROOT}/Archive/Item/{article_id}?arcId={arc_id}"
            content = _get(client, url, limit)
            bytes_seen += len(content)
            record = _article(content, url, article_id, arc_id)
            record["source_geography"] = source.get("geography")
            published, archived = archive_dates[(article_id, arc_id)]
            record["publication_date"] = published
            record["archived_date"] = archived
            record["event_date"] = None
            record["abstract"] = (
                f"{record['abstract']}\nSource archive dates: Published Date {published}; "
                f"Archived Date {archived}."
            )
            record["extraction_location"] = _evidence_location(record["category"], archive=True)
            rows[record["document_number"]] = record
            if bytes_seen > max_run:
                raise SourceParseError("Taylor response bytes exceed configured run bound")
        return list(rows.values())
    except SourceParseError:
        raise
    except (ValueError, OverflowError) as exc:
        raise SourceParseError("Taylor source returned malformed date or pagination data") from exc
    finally:
        if own_client:
            client.close()
