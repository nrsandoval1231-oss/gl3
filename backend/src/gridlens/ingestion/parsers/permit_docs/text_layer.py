"""Canonical text layer for permit PDFs: per-page text, one string, offset -> page/bbox."""

from __future__ import annotations

import io
import multiprocessing
import multiprocessing.connection
import multiprocessing.process
import sys
import time
from bisect import bisect_right
from dataclasses import dataclass, field
from typing import Literal

SCAN_CHAR_THRESHOLD = 40
PAGE_SEPARATOR = "\n\n"

FailureCode = Literal[
    "too_large",
    "too_many_pages",
    "unreadable",
    "encrypted",
    "time_budget",
    "page_too_long",
    "memory_limit",
    "worker_failed",
]
BBox = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class TextLayerLimits:
    max_bytes: int = 64 * 1024 * 1024
    max_pages: int = 1_200
    max_page_chars: int = 120_000
    max_seconds: float = 180.0
    max_seconds_per_page: float = 20.0
    max_memory_bytes: int = 2 * 1024 * 1024 * 1024  # enforced only where RLIMIT_AS exists
    # When set, only the first N pages are read and a longer file is not an error.
    first_pages: int | None = None


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
    source: str = "text_layer"  # or "ocr:<provider>:<model>" for a page read by OCR


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

    def with_ocr_pages(self, replacements: dict[int, str], source: str) -> CanonicalText:
        """Copy in which the given scanned pages carry OCR text labelled ``source``.

        Only pages that are scanned (or failed text extraction) can be replaced; a page with
        a real text layer is never overwritten. Geometry is kept for untouched pages and
        absent for OCR pages. The original object is not modified.
        """
        allowed = set(self.scanned_pages) | set(self.failed_pages)
        pages: list[PageText] = []
        for old in self.pages:
            if old.page in replacements and old.page in allowed:
                made = _page(old.page, replacements[old.page])
                pages.append(
                    PageText(
                        page=made.page,
                        text=made.text,
                        chars=made.chars,
                        scanned=made.scanned,
                        source=source,
                    )
                )
            else:
                pages.append(old)
        text, starts = _join(pages)
        replaced = {p.page for p in pages if p.source == source and p is not self.pages[p.page - 1]}
        boxes: list[tuple[int, int, BBox]] = []
        for start, end, box in self.line_boxes:
            page = self.page_of(start)
            if page is None or page in replaced:
                continue
            shift = starts[page - 1] - self.page_starts[page - 1]
            boxes.append((start + shift, end + shift, box))
        failed = [p for p in self.failed_pages if p not in replaced]
        return CanonicalText(
            pages=pages, text=text, page_starts=starts, line_boxes=boxes, failed_pages=failed
        )

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


# The parent waits max_seconds plus this for interpreter start-up and pickling, then kills.
_SPAWN_GRACE_SECONDS = 20.0


def build_canonical_text(
    pdf_bytes: bytes, limits: TextLayerLimits | None = None, *, isolate: bool = True
) -> CanonicalText | TextLayerFailure:
    """Extract the text layer with pdfplumber. Any bound breach returns a typed failure.

    With ``isolate`` (the default) parsing, including the page-tree walk, runs in a spawned
    child process that the parent kills at ``max_seconds`` plus a start-up grace, so a
    hostile or pathological PDF cannot hang or exhaust the caller. A POSIX child also gets
    an address-space cap (``max_memory_bytes``); Windows has no RLIMIT_AS, so there the
    memory bound is the byte, page and per-page character limits plus the wall-clock kill.
    Callers that spawn from a script must guard their entry point with ``__main__``.
    """
    limits = limits or TextLayerLimits()
    if len(pdf_bytes) > limits.max_bytes:
        return TextLayerFailure("too_large", f"PDF exceeds {limits.max_bytes} bytes")
    if not isolate:
        return _extract_in_process(pdf_bytes, limits)
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    child = context.Process(target=_worker, args=(sender, pdf_bytes, limits), daemon=True)
    child.start()
    sender.close()
    outcome: CanonicalText | TextLayerFailure
    try:
        if receiver.poll(limits.max_seconds + _SPAWN_GRACE_SECONDS):
            try:
                outcome = receiver.recv()
            except (EOFError, OSError):
                outcome = TextLayerFailure(
                    "worker_failed", f"extraction worker exited with code {_exit_code(child)}"
                )
        else:
            outcome = TextLayerFailure("time_budget", "hard wall-clock limit hit; worker killed")
    finally:
        receiver.close()
        if child.is_alive():
            child.kill()
        child.join(5)
    return outcome


def _exit_code(child: multiprocessing.process.BaseProcess) -> int | None:
    child.join(2)
    return child.exitcode


def _worker(
    sender: multiprocessing.connection.Connection, pdf_bytes: bytes, limits: TextLayerLimits
) -> None:
    outcome: CanonicalText | TextLayerFailure
    try:
        _cap_memory(limits.max_memory_bytes)
        outcome = _extract_in_process(pdf_bytes, limits)
    except MemoryError:
        outcome = TextLayerFailure("memory_limit", "extraction exceeded the memory cap")
    except BaseException as exc:  # noqa: BLE001 - the parent must always get a typed answer
        outcome = TextLayerFailure("unreadable", f"{type(exc).__name__}: {str(exc)[:200]}")
    sender.send(outcome)
    sender.close()


def _cap_memory(limit: int) -> None:
    if sys.platform == "win32":
        return  # no RLIMIT_AS on Windows; see build_canonical_text
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    except (ImportError, ValueError, OSError):  # pragma: no cover - platform dependent
        return


def _extract_in_process(
    pdf_bytes: bytes, limits: TextLayerLimits
) -> CanonicalText | TextLayerFailure:
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
            if limits.first_pages is None and count > limits.max_pages:
                return TextLayerFailure("too_many_pages", f"{count} pages exceed the bound")
            if count == 0:
                return TextLayerFailure("unreadable", "PDF has no pages")
            for number, source_page in enumerate(pdf.pages, start=1):
                if limits.first_pages is not None and number > limits.first_pages:
                    break
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
