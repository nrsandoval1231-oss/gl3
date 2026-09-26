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

from gridlens.ingestion.adapters.bounded_http import ResponseTooLarge, read_bounded_response
from gridlens.ingestion.adapters.federal_register import SourceParseError

MAX_PDF_BYTES = 5_000_000
MAX_PDF_PAGES = 50
MAX_PDFS_PER_RUN = 25
MAX_EXCERPT_CHARS = 1200
_PDF_PATH = re.compile(r"^/content/pkg/FR-\d{4}-\d{2}-\d{2}/pdf/(\d{4}-\d{5})\.pdf$")
_FOOTER = re.compile(r"FR\s*Doc\.?\s*(\d{4})[-–—](\d{5})\s+Filed", re.IGNORECASE)


def _title_pattern(title: str) -> re.Pattern[str]:
    words = re.findall(r"[A-Za-z0-9]+", title)
    if len(words) < 3:
        raise SourceParseError("Federal Register title is too short to identify a PDF notice")
    # The trailing project-specific phrase is the least likely part of the title
    # to occur in surrounding issue boilerplate.
    return re.compile(
        r"\b" + r"[\s,;:\-–—]+".join(map(re.escape, words[-4:])) + r"\b", re.IGNORECASE
    )


def retrieve_companion(
    record: dict[str, Any], client: httpx.Client | None = None
) -> list[dict[str, str]]:
    """Return one bounded excerpt whose PDF and page are tied to the FR record."""
    url = record.get("pdf_url")
    if not url:
        return []
    parsed = urlparse(url)
    match = _PDF_PATH.fullmatch(parsed.path)
    if parsed.scheme != "https" or parsed.hostname != "www.govinfo.gov" or not match:
        raise SourceParseError("Federal Register PDF URL is outside the GovInfo document path")
    document_number = record.get("document_number")
    if match.group(1) != document_number:
        raise SourceParseError("GovInfo PDF document number does not match Federal Register")
    try:
        published = date.fromisoformat(record["publication_date"])
    except (KeyError, ValueError) as exc:
        raise SourceParseError("Federal Register publication date is invalid for PDF") from exc
    title_pattern = _title_pattern(record.get("title", ""))
    own_client = client is None
    client = client or httpx.Client(timeout=30.0, follow_redirects=False)
    try:
        try:
            headers, content = read_bounded_response(client, url, MAX_PDF_BYTES)
        except ResponseTooLarge as exc:
            raise SourceParseError(str(exc)) from exc
        content_type = headers.get("content-type", "").split(";", 1)[0].lower()
        if content_type != "application/pdf" or not content.startswith(b"%PDF-"):
            raise SourceParseError("GovInfo response is not a PDF")
        reader = PdfReader(io.BytesIO(content), strict=True)
        if reader.is_encrypted or not reader.pages or len(reader.pages) > MAX_PDF_PAGES:
            raise SourceParseError("GovInfo PDF is encrypted, empty, or exceeds the page bound")

        start_page = None
        excerpt = None
        matching_footer = False
        for page_number, page in enumerate(reader.pages, start=1):
            page_text = page.extract_text() or ""
            if not page_text.strip():
                continue
            title_match = None
            if start_page is None:
                title_match = title_pattern.search(page_text)
                if title_match is None:
                    continue
                start_page = page_number
                # Use the raw-text match offset. Normalizing text before slicing
                # would select unrelated text from the preceding notice.
                target_page_text = page_text[title_match.start() :]
                excerpt = re.sub(r"\s+", " ", target_page_text).strip()
                excerpt = excerpt[:MAX_EXCERPT_CHARS]
            else:
                target_page_text = page_text
            footer_scan_text = target_page_text
            footer = _FOOTER.search(footer_scan_text)
            if footer:
                found_document = f"{footer.group(1)}-{footer.group(2)}"
                if found_document != document_number:
                    if start_page is not None:
                        raise SourceParseError(
                            "A different FR document footer ended the target notice"
                        )
                else:
                    matching_footer = True
                    if page_number == start_page:
                        excerpt = re.sub(r"\s+", " ", footer_scan_text[: footer.start()]).strip()[
                            :MAX_EXCERPT_CHARS
                        ]
                    break
        if start_page is None or not excerpt:
            raise SourceParseError("GovInfo PDF does not contain the discovered notice title")
        if not matching_footer:
            raise SourceParseError(
                "GovInfo PDF lacks the matching Federal Register document footer"
            )
        return [
            {
                "content_hash": hashlib.sha256(content).hexdigest(),
                "title": record["title"],
                "abstract": excerpt,
                "url": url,
                "published_at": published.isoformat(),
                "extraction_location": f"GovInfo PDF page {start_page}",
            }
        ]
    except SourceParseError:
        raise
    except Exception as exc:
        raise SourceParseError(f"GovInfo PDF extraction failed: {type(exc).__name__}") from exc
    finally:
        if own_client:
            client.close()
