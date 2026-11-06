"""Bounded, metadata-free page rasterization for explicitly approved public OCR pages."""

from __future__ import annotations

import base64
import hashlib
import io
import math
import re
import time
from typing import Any

from gridlens.ingestion.adapters.bounded_http import run_isolated
from gridlens.ingestion.adapters.govinfo_scan import MAX_PDF_BYTES, MAX_PDF_PAGES

PAGE_RENDER_DEADLINE_SECONDS = 30.0
MAX_PAGE_PIXELS = 2_000_000
MAX_PAGE_DIMENSION = 2_048
MAX_RENDERED_BYTES = MAX_PDF_BYTES
_APPROVAL = re.compile(r"([0-9a-f]{64}):([1-9][0-9]{0,5}):([0-9a-f]{64})\Z")


class PageApprovalRequired(ValueError):
    """At least one exact source page/render fingerprint lacks explicit approval."""


def page_approval_key(document_hash: str, source_page: int, pixel_hash: str) -> str:
    if (
        not re.fullmatch(r"[0-9a-f]{64}", document_hash)
        or type(source_page) is not int
        or source_page < 1
        or not re.fullmatch(r"[0-9a-f]{64}", pixel_hash)
    ):
        raise ValueError("OCR page fingerprint is invalid")
    return f"{document_hash}:{source_page}:{pixel_hash}"


def reviewed_page_hashes(setting: str) -> set[str]:
    """Parse comma-separated exact document/page/clean-pixel SHA-256 approvals."""
    if not isinstance(setting, str) or len(setting) > 100_000:
        return set()
    values = {item.strip() for item in setting.split(",") if item.strip()}
    if len(values) > 2_000 or any(_APPROVAL.fullmatch(value) is None for value in values):
        return set()
    return values


def approved_source_pages(document_hash: str, source_pages: list[int], setting: str) -> list[int]:
    """Select only pages explicitly reviewed for this exact retained PDF hash."""
    if not re.fullmatch(r"[0-9a-f]{64}", document_hash):
        return []
    candidates = set(source_pages)
    selected: set[int] = set()
    for value in reviewed_page_hashes(setting):
        match = _APPROVAL.fullmatch(value)
        assert match is not None
        if match.group(1) == document_hash:
            page = int(match.group(2))
            if page in candidates:
                selected.add(page)
    return sorted(selected)


def has_document_page_approval(document_hash: str, setting: str) -> bool:
    if not re.fullmatch(r"[0-9a-f]{64}", document_hash):
        return False
    for value in reviewed_page_hashes(setting):
        match = _APPROVAL.fullmatch(value)
        if match is not None and match.group(1) == document_hash:
            return True
    return False


def require_page_approval(document_hash: str, pages: list[dict[str, Any]], setting: str) -> None:
    approved = reviewed_page_hashes(setting)
    if not approved or not re.fullmatch(r"[0-9a-f]{64}", document_hash):
        raise PageApprovalRequired("OCR page review approval is required")
    for page in pages:
        try:
            key = page_approval_key(document_hash, page["source_page"], page["pixel_sha256"])
        except (KeyError, TypeError, ValueError):
            raise PageApprovalRequired("OCR page review approval is required") from None
        if key not in approved:
            raise PageApprovalRequired("OCR page review approval is required")


def _render_worker(
    pdf_bytes: bytes,
    local_pages: list[int],
    source_pages: list[int],
    max_bytes: int,
) -> list[dict[str, Any]]:
    """Render only visible page pixels; omit PDF annotations, forms and all metadata."""
    import pypdfium2 as pdfium  # type: ignore[import-untyped]
    from PIL import Image
    from pypdf import PdfReader

    if (
        not isinstance(pdf_bytes, bytes)
        or not pdf_bytes.startswith(b"%PDF-")
        or len(pdf_bytes) > MAX_PDF_BYTES
        or not local_pages
        or len(local_pages) > MAX_PDF_PAGES
        or len(local_pages) != len(source_pages)
        or any(type(page) is not int or page < 1 for page in local_pages + source_pages)
    ):
        raise ValueError("OCR page render input is invalid")
    checked_pdf = PdfReader(io.BytesIO(pdf_bytes), strict=True)
    if checked_pdf.is_encrypted or len(checked_pdf.pages) > MAX_PDF_PAGES:
        raise ValueError("OCR page render document is encrypted or exceeds the page limit")
    document = pdfium.PdfDocument(pdf_bytes)
    if len(document) != len(checked_pdf.pages) or any(page > len(document) for page in local_pages):
        document.close()
        raise ValueError("OCR page render document is invalid")
    rendered: list[dict[str, Any]] = []
    total_bytes = 0
    try:
        for local_page, source_page in zip(local_pages, source_pages, strict=True):
            page = document[local_page - 1]
            width, height = float(page.get_width()), float(page.get_height())
            if not math.isfinite(width * height) or width <= 0 or height <= 0:
                raise ValueError("OCR page dimensions are invalid")
            scale = min(
                1.0,
                math.sqrt(MAX_PAGE_PIXELS / (width * height)),
                MAX_PAGE_DIMENSION / width,
                MAX_PAGE_DIMENSION / height,
            )
            bitmap = page.render(
                scale=scale,
                grayscale=True,
                draw_annots=False,
                may_draw_forms=False,
                fill_color=(255, 255, 255, 255),
            )
            try:
                source_image = bitmap.to_pil().convert("L")
                # Rebuild from raw samples so the encoded PNG carries no source PDF
                # metadata, profiles, ancillary chunks, annotation or attachment data.
                image = Image.frombytes("L", source_image.size, source_image.tobytes())
                image_width, image_height = image.size
                output = io.BytesIO()
                image.save(output, format="PNG", optimize=False, compress_level=9)
                png = output.getvalue()
                image.close()
                source_image.close()
            finally:
                bitmap.close()
                page.close()
            total_bytes += len(png)
            if total_bytes > max_bytes:
                raise ValueError("OCR rendered page images exceed the byte bound")
            rendered.append(
                {
                    "source_page": source_page,
                    "pixel_sha256": hashlib.sha256(png).hexdigest(),
                    "width": image_width,
                    "height": image_height,
                    "image_base64": base64.b64encode(png).decode("ascii"),
                }
            )
    finally:
        document.close()
    return rendered


def render_page_images(
    pdf_bytes: bytes,
    *,
    local_pages: list[int],
    source_pages: list[int],
    deadline_seconds: float = PAGE_RENDER_DEADLINE_SECONDS,
) -> list[dict[str, Any]]:
    """Rasterize in a killable worker with strict input, page, pixel, byte and time bounds."""
    if not 0 < deadline_seconds <= PAGE_RENDER_DEADLINE_SECONDS:
        raise ValueError("OCR render deadline is invalid")
    deadline = time.monotonic() + deadline_seconds
    return run_isolated(
        "gridlens.intelligence.ocr_public_pages:_render_worker",
        (pdf_bytes, local_pages, source_pages, MAX_RENDERED_BYTES),
        {},
        deadline=deadline,
    )
