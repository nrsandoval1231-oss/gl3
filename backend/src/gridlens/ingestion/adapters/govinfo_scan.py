"""Exact, bounded capture of an already-linked GovInfo Federal Register PDF."""

from __future__ import annotations

import base64
import hashlib
import io
import ipaddress
import re
import socket
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
from pypdf import PdfReader

from gridlens.ingestion.adapters.bounded_http import (
    ResponseTooLarge,
    read_bounded_response,
    run_isolated,
)

MAX_PDF_BYTES = 750_000
MAX_PDF_PAGES = 5
CAPTURE_DEADLINE_SECONDS = 25
CAPTURE_KEY = "govinfo_ocr_capture_v1"
_PATH = re.compile(r"^/content/pkg/FR-\d{4}-\d{2}-\d{2}/pdf/(\d{4}-\d{5})\.pdf$")


def _checked_url(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    match = _PATH.fullmatch(parts.path)
    if (
        parts.scheme != "https"
        or parts.hostname != "www.govinfo.gov"
        or parts.port not in (None, 443)
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or match is None
        or len(url) > 500
    ):
        raise ValueError("PDF URL is outside the exact GovInfo Federal Register path")
    return url, match.group(1)


def _capture_worker(url: str, expected_hash: str, deadline: float) -> dict[str, Any]:
    """Network and PDF parsing run only in bounded_http's killable child."""
    from gridlens.ingestion.adapters.bounded_http import remaining_seconds

    remaining_seconds(deadline)
    url, _document_id = _checked_url(url)
    host = "www.govinfo.gov"
    addresses = sorted(
        {str(answer[4][0]) for answer in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    )
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("GovInfo did not resolve exclusively to public addresses")
    ip = addresses[0]
    pinned_url = httpx.URL(url).copy_with(host=ip)
    with httpx.Client(
        timeout=httpx.Timeout(8),
        follow_redirects=False,
        trust_env=False,
        headers={"Host": host, "User-Agent": "GridLens scanned PDF capture/1.0"},
    ) as client:
        headers, content = read_bounded_response(
            client,
            str(pinned_url),
            MAX_PDF_BYTES,
            extensions={"sni_hostname": host},
            deadline=deadline,
        )
    if headers.get("content-type", "").split(";", 1)[0].lower() != "application/pdf":
        raise ValueError("GovInfo response MIME type is not PDF")
    if not content.startswith(b"%PDF-"):
        raise ValueError("GovInfo response lacks PDF magic bytes")
    digest = hashlib.sha256(content).hexdigest()
    if digest != expected_hash:
        raise ValueError("GovInfo PDF changed; normal source acquisition is required")
    reader = PdfReader(io.BytesIO(content), strict=True)
    if reader.is_encrypted or not 1 <= len(reader.pages) <= MAX_PDF_PAGES:
        raise ValueError("GovInfo PDF is encrypted, empty, or exceeds the page limit")
    # Parsing page text here is deliberately only a scan check. The model receives
    # the original PDF so PDF page images are handled by the provider itself.
    page_count = len(reader.pages)
    scanned_pages = [
        index
        for index, page in enumerate(reader.pages, start=1)
        if not (page.extract_text() or "").strip()
    ]
    remaining_seconds(deadline)
    return {
        "document_id": _checked_url(url)[1],
        "content_hash": digest,
        "page_count": page_count,
        "scanned_pages": scanned_pages,
        "data_base64": base64.b64encode(content).decode("ascii"),
        "source_url": url,
    }


def capture_govinfo_pdf(url: str, expected_hash: str) -> dict[str, Any]:
    """Download the linked source with exact URL, byte, page, hash and wall bounds."""
    if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise ValueError("Expected source PDF hash is invalid")
    _checked_url(url)
    deadline = time.monotonic() + CAPTURE_DEADLINE_SECONDS
    try:
        return run_isolated(
            "gridlens.ingestion.adapters.govinfo_scan:_capture_worker",
            (url, expected_hash, deadline),
            {},
            deadline=deadline,
        )
    except ResponseTooLarge as exc:
        raise ValueError("GovInfo PDF exceeds the byte limit") from exc


def merge_write_once_capture(
    provenance: dict[str, Any] | None,
    capture: dict[str, Any],
    *,
    source_allowed: bool,
    retention_allowed: bool,
    retention_reference: str,
    retrieved_at: datetime | None = None,
) -> dict[str, Any]:
    """Return provenance with an immutable, namespaced capture envelope."""
    if not source_allowed or not retention_allowed:
        raise ValueError("Source and retention must both be explicitly allowed")
    required = {
        "document_id",
        "content_hash",
        "page_count",
        "scanned_pages",
        "data_base64",
        "source_url",
    }
    if set(capture) != required:
        raise ValueError("Capture envelope shape is invalid")
    if (
        not isinstance(capture["content_hash"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", capture["content_hash"])
        or type(capture["page_count"]) is not int
        or not 1 <= capture["page_count"] <= MAX_PDF_PAGES
        or not isinstance(capture["scanned_pages"], list)
        or any(
            type(page) is not int or not 1 <= page <= capture["page_count"]
            for page in capture["scanned_pages"]
        )
        or not isinstance(capture["data_base64"], str)
        or not capture["data_base64"]
        or not isinstance(capture["source_url"], str)
        or not retention_reference
    ):
        raise ValueError("Capture envelope values are invalid")
    _url, document_id = _checked_url(capture["source_url"])
    try:
        source_bytes = base64.b64decode(capture["data_base64"], validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("Capture envelope bytes are invalid") from exc
    if (
        len(source_bytes) > MAX_PDF_BYTES
        or not source_bytes.startswith(b"%PDF-")
        or hashlib.sha256(source_bytes).hexdigest() != capture["content_hash"]
        or document_id != capture["document_id"]
    ):
        raise ValueError("Capture envelope does not match exact source PDF bytes")
    envelope = {
        **capture,
        "source": "www.govinfo.gov",
        "retention_policy": "explicit_source_retention_allowlist",
        "retention_reference": retention_reference,
        "retrieved_at": (retrieved_at or datetime.now(UTC)).isoformat(),
    }
    result = dict(provenance) if isinstance(provenance, dict) else {}
    previous = result.get(CAPTURE_KEY)
    if previous is not None and previous != envelope:
        # Retrieval time can differ for a repeat of identical bytes. The first
        # successful capture remains canonical and must never be overwritten.
        same_capture = isinstance(previous, dict) and all(
            previous.get(key) == envelope.get(key)
            for key in (
                "document_id",
                "content_hash",
                "page_count",
                "scanned_pages",
                "data_base64",
                "source_url",
                "source",
                "retention_reference",
            )
        )
        if not same_capture:
            raise ValueError("Existing GovInfo capture is immutable")
        return result
    result[CAPTURE_KEY] = envelope
    return result
