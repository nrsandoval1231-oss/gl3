"""Bounded, page-cited extraction of a GovInfo Federal Register PDF notice."""

from __future__ import annotations

import hashlib
import io
import re
from datetime import date
from typing import Any
from urllib.parse import urlparse

import httpx
from pypdf import PdfReader

from gridlens.ingestion.adapters.bounded_http import (
    ResponseTooLarge,
    read_bounded_response,
    remaining_seconds,
)
from gridlens.ingestion.adapters.federal_register import SourceParseError

MAX_PDF_BYTES = 5_000_000
MAX_PDF_PAGES = 50
MAX_PDFS_PER_RUN = 25
MAX_NOTICE_CHARS = 128_000
_PDF_PATH = re.compile(r"^/content/pkg/FR-(\d{4}-\d{2}-\d{2})/pdf/(\d{4}-\d{5})\.pdf$")
_FOOTER = re.compile(r"FR\s*Doc\.?\s*(\d{4})[-–—](\d{5})\s+Filed", re.IGNORECASE)


def _title_pattern(title: str) -> re.Pattern[str]:
    words = re.findall(r"[^\W_]+", title)
    if len(words) < 3:
        raise SourceParseError("Federal Register title is too short to identify a PDF notice")
    return re.compile(
        r"(?<!\w)" + r"[\W_]+".join(map(re.escape, words)) + r"(?!\w)",
        re.IGNORECASE,
    )


def retrieve_companion(
    record: dict[str, Any], client: httpx.Client | None = None, *, deadline: float | None = None
) -> list[dict[str, str]]:
    """Return one bounded complete notice whose PDF and pages match the FR record."""
    url = record.get("pdf_url")
    if not url:
        return []
    parsed = urlparse(url)
    match = _PDF_PATH.fullmatch(parsed.path)
    try:
        port = parsed.port
    except ValueError as exc:
        raise SourceParseError("Federal Register PDF URL has an invalid port") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != "www.govinfo.gov"
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.query
        or parsed.fragment
        or "?" in url
        or "#" in url
        or not match
    ):
        raise SourceParseError("Federal Register PDF URL is outside the GovInfo document path")
    document_number = record.get("document_number")
    if match.group(2) != document_number:
        raise SourceParseError("GovInfo PDF document number does not match Federal Register")
    try:
        published = date.fromisoformat(record["publication_date"])
    except (KeyError, ValueError) as exc:
        raise SourceParseError("Federal Register publication date is invalid for PDF") from exc
    if match.group(1) != published.isoformat():
        raise SourceParseError("GovInfo PDF package date does not match Federal Register")
    title_pattern = _title_pattern(record.get("title", ""))
    own_client = client is None
    client = client or httpx.Client(timeout=30.0, follow_redirects=False)
    try:
        try:
            headers, content = read_bounded_response(client, url, MAX_PDF_BYTES, deadline=deadline)
        except ResponseTooLarge as exc:
            raise SourceParseError(str(exc)) from exc
        remaining_seconds(deadline)
        content_type = headers.get("content-type", "").split(";", 1)[0].lower()
        if content_type != "application/pdf" or not content.startswith(b"%PDF-"):
            raise SourceParseError("GovInfo response is not a PDF")
        reader = PdfReader(io.BytesIO(content), strict=True)
        if reader.is_encrypted or not reader.pages or len(reader.pages) > MAX_PDF_PAGES:
            raise SourceParseError("GovInfo PDF is encrypted, empty, or exceeds the page bound")

        start_page = None
        end_page = None
        page_fragments: list[str] = []
        for page_number, page in enumerate(reader.pages, start=1):
            remaining_seconds(deadline)
            page_text = page.extract_text() or ""
            if not page_text.strip():
                if start_page is not None:
                    raise SourceParseError(
                        f"GovInfo PDF page {page_number} is blank inside the target notice"
                    )
                continue
            if start_page is None:
                title_matches = list(title_pattern.finditer(page_text))
                target_footer = next(
                    (
                        footer
                        for footer in _FOOTER.finditer(page_text)
                        if f"{footer.group(1)}-{footer.group(2)}" == document_number
                    ),
                    None,
                )
                if target_footer and (
                    not title_matches or title_matches[0].start() > target_footer.start()
                ):
                    raise SourceParseError("GovInfo PDF target footer occurs before its full title")
                if not title_matches:
                    continue
                if len(title_matches) != 1:
                    raise SourceParseError("GovInfo PDF contains ambiguous target title starts")
                title_match = title_matches[0]
                start_page = page_number
                target_page_text = page_text[title_match.start() :]
            else:
                target_page_text = page_text
                if title_pattern.search(target_page_text):
                    raise SourceParseError("GovInfo PDF contains ambiguous target title starts")

            footer_scan_text = target_page_text
            footer = _FOOTER.search(footer_scan_text)
            if footer:
                found_document = f"{footer.group(1)}-{footer.group(2)}"
                if found_document != document_number:
                    raise SourceParseError("A different FR document footer ended the target notice")
                target_page_text = footer_scan_text[: footer.start()].rstrip()
                if target_page_text.endswith("["):
                    target_page_text = target_page_text[:-1].rstrip()
                end_page = page_number
            page_fragments.append(f"[GovInfo PDF page {page_number}] {target_page_text}")
            if end_page is not None:
                break
        if start_page is None:
            raise SourceParseError("GovInfo PDF does not contain the discovered notice title")
        if end_page is None or not page_fragments:
            raise SourceParseError(
                "GovInfo PDF lacks the matching Federal Register document footer"
            )
        excerpt = re.sub(r"\s+", " ", " ".join(page_fragments)).strip()
        if not excerpt:
            raise SourceParseError("GovInfo target notice is empty")
        if len(excerpt) > MAX_NOTICE_CHARS:
            raise SourceParseError("GovInfo target notice exceeds the text character bound")
        return [
            {
                "content_hash": hashlib.sha256(content).hexdigest(),
                "title": record["title"],
                "abstract": excerpt,
                "url": url,
                "published_at": published.isoformat(),
                "extraction_location": (
                    f"GovInfo PDF page {start_page}"
                    if start_page == end_page
                    else f"GovInfo PDF pages {start_page}-{end_page}"
                ),
            }
        ]
    except SourceParseError:
        raise
    except Exception as exc:
        raise SourceParseError(f"GovInfo PDF extraction failed: {type(exc).__name__}") from exc
    finally:
        if own_client:
            client.close()
