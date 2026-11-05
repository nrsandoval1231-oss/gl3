"""Shared helpers for the later early-signal sources (workstream 4b).

The Comptroller data-center registry, the Oklahoma Corporation Commission data-center notices,
county commissioners' abatement agendas and TCEQ pending water-right applications all follow the
discipline of the ERCOT and PUCT adapters (``early_signal_stage``, ``early_signal_http``): a listing
step that fetches a few server-rendered public pages, and an optional document stage that reads PDFs
under the shared pacer, size caps, change detection and ``not_before`` rest.

This module only holds what those four adapters share: a bounded page fetch with a typed listing
error, a small table parser, quote-bound evidence values, and the generic stage runner. Nothing here
reads a response into an error message, and nothing creates a project, need or card.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html import unescape
from html.parser import HTMLParser
from typing import Any

import httpx

from gridlens.ingestion.adapters import early_signal_stage as stage
from gridlens.ingestion.adapters.bounded_http import remaining_seconds
from gridlens.ingestion.adapters.early_signal_http import HTML, EarlyFetcher
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.tceq_application_documents import DocumentFailure

MAX_QUOTE = 600


def norm(text: str) -> str:
    """Whitespace-normalised text with the Unicode replacement character turned into a space."""
    return " ".join(text.replace("�", " ").split())


def listing_error(failure: DocumentFailure, label: str) -> SourceParseError:
    error = SourceParseError(f"{label} listing fetch failed: {failure.code}")
    if failure.rate_limited:
        error.acquisition_code = failure.code  # type: ignore[attr-defined]
        if failure.retry_after is not None:
            error.acquisition_retry_after_seconds = failure.retry_after  # type: ignore[attr-defined]
    return error


def fetch_page(
    fetcher: EarlyFetcher, url: str, max_bytes: int, deadline: float | None, label: str
) -> bytes:
    remaining_seconds(deadline)
    try:
        return fetcher.get(url, max_bytes=max_bytes, media_types=HTML, accept="text/html").body
    except DocumentFailure as failure:
        raise listing_error(failure, label) from failure


# --------------------------------------------------------------------------- table parsing


@dataclass(slots=True)
class Cell:
    text: str = ""
    items: list[str] = field(default_factory=list)
    links: list[tuple[str, str]] = field(default_factory=list)  # (href, anchor text)
    header: bool = False
    span: int = 1  # colspan; a row with any span other than 1 is not read as a plain row


def _span(attrs: list[tuple[str, str | None]]) -> int:
    values = dict(attrs)
    for name in ("colspan", "rowspan"):
        raw = values.get(name)
        if raw is not None and raw.strip() != "1":
            return 2
    return 1


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[Cell]]] = []
        self._depth = 0
        self._row: list[Cell] | None = None
        self._cell: Cell | None = None
        self._buf: list[str] = []
        self._item: list[str] | None = None
        self._anchor: tuple[str, list[str]] | None = None
        self._skip = 0

    def _close_cell(self) -> None:
        if self._cell is not None and self._row is not None:
            self._cell.text = norm("".join(self._buf))
            self._row.append(self._cell)
        self._cell = None
        self._item = None
        self._anchor = None

    def _close_row(self) -> None:
        self._close_cell()
        if self._row is not None and self.tables and self._row:
            self.tables[-1].append(self._row)
        self._row = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "svg"}:
            self._skip += 1
        elif tag == "table":
            self._depth += 1
            if self._depth == 1:
                self.tables.append([])
        elif self._depth != 1:
            return
        elif tag == "tr":
            self._close_row()  # an unclosed row ends where the next one starts
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._close_cell()  # an unclosed cell ends where the next one starts
            self._cell = Cell(header=tag == "th", span=_span(attrs))
            self._buf = []
        elif self._cell is not None and tag == "li":
            self._item = []
        elif self._cell is not None and tag == "a":
            href = dict(attrs).get("href")
            self._anchor = (href or "", [])
        elif self._cell is not None and tag == "br":
            self._buf.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "svg"}:
            self._skip = max(0, self._skip - 1)
        elif tag == "table" and self._depth:
            if self._depth == 1:
                self._close_row()
            self._depth -= 1
        elif self._depth != 1:
            return
        elif tag in {"td", "th"}:
            self._close_cell()
        elif tag == "tr":
            self._close_row()
        elif tag == "li" and self._item is not None and self._cell is not None:
            value = norm("".join(self._item))
            if value:
                self._cell.items.append(value)
            self._item = None
        elif tag == "a" and self._anchor is not None and self._cell is not None:
            self._cell.links.append((self._anchor[0], norm("".join(self._anchor[1]))))
            self._anchor = None

    def handle_data(self, data: str) -> None:
        if self._skip or self._cell is None or self._depth != 1:
            return
        self._buf.append(data)
        if self._item is not None:
            self._item.append(data)
        if self._anchor is not None:
            self._anchor[1].append(data)


def parse_tables(html: bytes) -> list[list[list[Cell]]]:
    """Top-level tables as rows of cells (nested tables are not entered)."""
    parser = _TableParser()
    parser.feed(html.decode("utf-8", errors="replace"))
    parser.close()
    return parser.tables


_ANCHOR = re.compile(
    r"""<a\b[^>]*?\bhref\s*=\s*(?:"(?P<d>[^"]{1,700})"|'(?P<s>[^']{1,700})')[^>]*>(?P<t>.*?)</a>""",
    re.S | re.I,
)


def anchors(html: bytes) -> list[tuple[str, str]]:
    """Every anchor as (href, text), in document order, with entities decoded."""
    text = html.decode("utf-8", errors="replace")
    found: list[tuple[str, str]] = []
    for match in _ANCHOR.finditer(text):
        href = match["d"] if match["d"] is not None else match["s"]
        found.append((unescape(href), norm(unescape(re.sub(r"<[^>]+>", " ", match["t"])))))
    return found


# --------------------------------------------------------------------------- evidence values


def evidence(
    value: Any,
    basis: str,
    page: int,
    quote: str,
    page_norm: str,
    *,
    start: int | None = None,
    **extra: Any,
) -> dict[str, Any] | None:
    """A value with its verbatim quote and the quote's span inside the normalised page text.

    ``start`` is the known offset of the quote in ``page_norm``; the quote must sit exactly there
    (a quote that merely occurs earlier on the page would give a wrong span). Without ``start`` the
    first occurrence is used.
    """
    if not quote:
        return None
    if start is None:
        start = page_norm.find(quote)
    if start < 0 or page_norm[start : start + len(quote)] != quote:
        return None
    return {
        "value": value,
        "basis": basis,
        "page": page,
        "quote": quote,
        "span": [start, start + len(quote)],
        **extra,
    }


def window_span(
    text: str, start: int, end: int, before: int = 80, after: int = 120, limit: int = MAX_QUOTE
) -> tuple[int, int]:
    """Offsets of the match plus bounded context cut at word edges, at most ``limit`` long."""
    lo, hi = max(0, start - before), min(len(text), end + after)
    while lo > 0 and text[lo - 1] != " ":
        lo -= 1
    while hi < len(text) and text[hi] != " ":
        hi += 1
    while lo < start and text[lo] == " ":
        lo += 1
    if hi - lo > limit:
        lo, hi = max(0, start - 20), min(len(text), end + 20)
        hi = min(hi, lo + limit)
    return lo, hi


def window(text: str, start: int, end: int, before: int = 80, after: int = 120) -> str:
    lo, hi = window_span(text, start, end, before, after)
    return text[lo:hi].strip()


# --------------------------------------------------------------------------- personal data

_ORG = re.compile(
    r"\b(?:LLC|L\.L\.C\.?|Inc\.?|Incorporated|LP|L\.P\.?|LLP|Ltd\.?|Company|Co\b|Corp\.?|"
    r"Corporation|Cooperative|Partnership|Association|District|Authority|County|Water Supply|"
    r"Municipal|Utility|Utilities|Board|Commission|Department|Agency)\b"
    r"|^(?:City|Town|Village) of\b|\bMWD\b|\bWCID\b",
)
_ADDRESS = re.compile(
    r"\b\d{1,6}\s+(?:[A-Z][A-Za-z.]*\s+){0,3}(?:County Road|CR|Road|Rd|Street|St|Avenue|Ave|"
    r"Drive|Dr|Lane|Ln|Highway|Hwy|FM|Boulevard|Blvd|Court|Ct|Circle|Trail|Way)\b\.?"
    r"|\bP\.?\s?O\.?\s+Box\s+\d+\b|\b[A-Z]{2}\s+\d{5}(?:-\d{4})?\b|\bTexas\s+\d{5}\b",
)
_PERSON = re.compile(
    r"\b(?:Mr|Mrs|Ms|Dr)\.\s+[A-Z][a-z]+"
    r"|\b[A-Z][a-z]+ [A-Z][a-z]+,? (?:a |an |the )?"
    r"(?:resident|landowner|property owner|citizen|owner)\b"
)
INDIVIDUAL_APPLICANT = "individual applicant (name withheld)"


def is_organisation(name: str) -> bool:
    """Whether an applicant name has an organisation shape (a company, city, district, ...)."""
    return _ORG.search(name) is not None


def has_address(text: str) -> bool:
    return _ADDRESS.search(text) is not None


def has_person(text: str) -> bool:
    return _PERSON.search(text) is not None


# --------------------------------------------------------------------------- listing result


def acquisition_result(
    records: list[dict[str, Any]], skipped: dict[str, int], rows_seen: int, label: str
) -> Any:
    """The records, or a partial result naming skipped rows; too many skipped rows fail loudly."""
    total = sum(skipped.values())
    if total == 0:
        return records
    if total > max(1, rows_seen // 20):
        raise SourceParseError(f"{label} listing skipped too many rows ({total} of {rows_seen})")
    rejected = [
        {
            "identity": f"{label.upper()}-LISTING",
            "stage": "listing",
            "error_code": re.sub(r"[^a-z0-9_]", "_", code.lower()),
            "selected_fields": ["rows"],
            "omitted_fields": [],
            "raw": {"rows": str(count)},
        }
        for code, count in sorted(skipped.items())
        if count
    ]
    return {
        "records": records,
        "partial": True,
        "partial_reason": "skipped_rows",
        "rejected_count": total,
        "rejected_records": rejected[:50],
    }


# --------------------------------------------------------------------------- stage runner

ItemFor = Callable[[dict[str, Any]], "stage.DocItem | None"]


def run_document_stage(
    records: list[dict[str, Any]],
    prior_states: dict[str, dict[str, Any]],
    *,
    client: httpx.Client | None,
    config: stage.StageConfig,
    index: dict[str, Any] | None,
    deadline: float | None,
    pacer: Callable[[], None] | None,
    now: Callable[[], datetime],
    policy: Callable[[str], bool],
    extractors: dict[str, stage.Extractor],
    item_for: ItemFor,
    withhold_unread: bool,
) -> stage.EarlyStageReport:
    """Read the listed documents and fold their states into the records.

    With ``withhold_unread`` a listed document that was not read (budget, deadline, rate limit,
    failure) and has no retained state is dropped from this run's list rather than stored empty.
    Without it the listing record stands on its own (its listing facts are evidence) and only gains
    the document fields when a state exists.
    """
    started = now()
    listed_count = len(records)
    items = [item for record in records if (item := item_for(record)) is not None]
    in_scope = {item.key for item in items}
    states = {k: v for k, v in prior_states.items() if k in in_scope}
    owns = client is None
    http = client or stage.new_client()
    try:
        run = stage.make_run(
            client=http,
            pacer=pacer or stage.default_pacer(),
            policy=policy,
            config=config,
            deadline=deadline,
            record_count=len(records),
            index=index,
            states=states,
            extractors=extractors,
            now=started,
        )
        run.report.counts["in_scope"] = len(items)
        if stage.resting(index, started):
            run.report.bump("skipped_retry_after")
        else:
            stage.run_documents(run, items)
        report = stage.finish(run, index, listed_count)
    finally:
        if owns:
            http.close()
    unread: list[dict[str, Any]] = []
    for record in records:
        state = run.states.get(str(record.get("state_key")))
        if state is not None:
            stage.apply_state(record, state)
        elif withhold_unread and item_for(record) is not None:
            unread.append(record)
    records[:] = [r for r in records if not any(r is u for u in unread)]
    report.counts["withheld_unread"] = len(unread)
    return report


def apply_prior_states(
    records: list[dict[str, Any]],
    prior: dict[str, dict[str, Any]],
    item_for: ItemFor,
    withhold_unread: bool,
) -> None:
    """Fold retained states into the records when the stage did not run (fault, disabled)."""
    unread: list[dict[str, Any]] = []
    for record in records:
        state = prior.get(str(record.get("state_key")))
        if state is not None:
            stage.apply_state(record, state)
        elif withhold_unread and item_for(record) is not None:
            unread.append(record)
    records[:] = [r for r in records if not any(r is u for u in unread)]


def today_utc() -> str:
    return datetime.now(UTC).date().isoformat()
