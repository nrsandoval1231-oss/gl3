"""Canonical text layer for permit PDFs: per-page text, one string, offset -> page/bbox."""

from __future__ import annotations

import io
import time
from bisect import bisect_right
from dataclasses import dataclass, field
from typing import Literal

SCAN_CHAR_THRESHOLD = 40
PAGE_SEPARATOR = "\n\n"

FailureCode = Literal[
    "too_large", "too_many_pages", "unreadable", "encrypted", "time_budget", "page_too_long"
]
BBox = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class TextLayerLimits:
    max_bytes: int = 64 * 1024 * 1024
    max_pages: int = 1_200
    max_page_chars: int = 120_000
    max_seconds: float = 180.0
    max_seconds_per_page: float = 20.0


@dataclass(frozen=True, slots=True)
class TextLayerFailure:
    code: FailureCode
    message: str
    page: int | None = None


@dataclass(frozen=True, slots=True)
class PageText:
    page: int  # 1-based
    text: str
    chars: int  # non-whitespace characters
    scanned: bool


@dataclass(frozen=True, slots=True)
class Location:
    page: int
    bbox: BBox | None  # (x0, top, x1, bottom) of the containing text line


@dataclass(slots=True)
class CanonicalText:
    pages: list[PageText]
    text: str
    page_starts: list[int]
    # (start, end, bbox) per source line, canonical offsets, ascending; empty without geometry.
    line_boxes: list[tuple[int, int, BBox]] = field(default_factory=list)
    failed_pages: list[int] = field(default_factory=list)  # text extraction raised; treated as scan

    @classmethod
    def from_page_texts(cls, page_texts: list[str]) -> CanonicalText:
        """Test/OCR seam: build from per-page text without geometry."""
        pages = [_page(i, t) for i, t in enumerate(page_texts, start=1)]
        text, starts = _join(pages)
        return cls(pages=pages, text=text, page_starts=starts)

    def page_span(self, page: int) -> tuple[int, int]:
        start = self.page_starts[page - 1]
        return start, start + len(self.pages[page - 1].text)

    def page_of(self, offset: int) -> int | None:
        if not 0 <= offset < len(self.text):
            return None
        page = bisect_right(self.page_starts, offset)
        start, end = self.page_span(page)
        return page if start <= offset < end else None

    def locate(self, offset: int) -> Location | None:
        """Page and (when geometry exists) line bounding box containing ``offset``."""
        page = self.page_of(offset)
        if page is None:
            return None
        bbox = None
        for start, end, box in self.line_boxes:
            if start <= offset < end:
                bbox = box
                break
        return Location(page=page, bbox=bbox)

    @property
    def scanned_pages(self) -> list[int]:
        return [p.page for p in self.pages if p.scanned]


def _page(number: int, text: str) -> PageText:
    chars = sum(1 for c in text if not c.isspace())
    return PageText(page=number, text=text, chars=chars, scanned=chars < SCAN_CHAR_THRESHOLD)


def _join(pages: list[PageText]) -> tuple[str, list[int]]:
    parts: list[str] = []
    starts: list[int] = []
    cursor = 0
    for index, page in enumerate(pages):
        starts.append(cursor)
        parts.append(page.text)
        cursor += len(page.text)
        if index < len(pages) - 1:
            parts.append(PAGE_SEPARATOR)
            cursor += len(PAGE_SEPARATOR)
    return "".join(parts), starts


def build_canonical_text(
    pdf_bytes: bytes, limits: TextLayerLimits | None = None
) -> CanonicalText | TextLayerFailure:
    """Extract the text layer with pdfplumber. Any bound breach returns a typed failure."""
    limits = limits or TextLayerLimits()
    if len(pdf_bytes) > limits.max_bytes:
        return TextLayerFailure("too_large", f"PDF exceeds {limits.max_bytes} bytes")
    try:
        import pdfplumber  # local import keeps module import cheap
    except ImportError:  # pragma: no cover - dependency is pinned
        return TextLayerFailure("unreadable", "pdfplumber is not installed")
    started = time.monotonic()
    pages: list[PageText] = []
    failed: list[int] = []
    line_data: list[list[tuple[str, BBox]]] = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            count = len(pdf.pages)
            if count > limits.max_pages:
                return TextLayerFailure("too_many_pages", f"{count} pages exceed the bound")
            if count == 0:
                return TextLayerFailure("unreadable", "PDF has no pages")
            for number, source_page in enumerate(pdf.pages, start=1):
                if time.monotonic() - started > limits.max_seconds:
                    return TextLayerFailure("time_budget", "time budget exceeded", number)
                page_started = time.monotonic()
                try:
                    lines = source_page.extract_text_lines(
                        layout=False, strip=True, return_chars=False
                    )
                except Exception:  # noqa: BLE001 - one bad page must not hide the others
                    # Loud, not silent: listed in failed_pages and routed to OCR.
                    failed.append(number)
                    pages.append(_page(number, ""))
                    line_data.append([])
                    continue
                texts = [(str(ln["text"]), _bbox(ln)) for ln in lines]
                text = "\n".join(t for t, _ in texts)
                if len(text) > limits.max_page_chars:
                    return TextLayerFailure("page_too_long", "page text exceeds bound", number)
                if time.monotonic() - page_started > limits.max_seconds_per_page:
                    return TextLayerFailure("time_budget", "page time budget exceeded", number)
                pages.append(_page(number, text))
                line_data.append(texts)
                source_page.flush_cache()
    except Exception as exc:  # noqa: BLE001 - any parser error becomes a typed failure
        name = type(exc).__name__
        code: FailureCode = "encrypted" if "Password" in name or "Encrypt" in name else "unreadable"
        return TextLayerFailure(code, f"{name}: {str(exc)[:200]}")
    text, starts = _join(pages)
    boxes: list[tuple[int, int, BBox]] = []
    for page_index, texts in enumerate(line_data):
        cursor = starts[page_index]
        for line_text, box in texts:
            boxes.append((cursor, cursor + len(line_text), box))
            cursor += len(line_text) + 1
    return CanonicalText(
        pages=pages, text=text, page_starts=starts, line_boxes=boxes, failed_pages=failed
    )


def _bbox(line: dict[str, object]) -> BBox:
    def num(key: str) -> float:
        value = line.get(key, 0.0)
        return float(value) if isinstance(value, int | float) else 0.0

    return (num("x0"), num("top"), num("x1"), num("bottom"))
