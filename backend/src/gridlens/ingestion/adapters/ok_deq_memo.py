"""Deterministic header facts from an Oklahoma DEQ evaluation memorandum.

Pure functions over the canonical text of a memo (see ``permit_docs.text_layer``). Every
returned fact carries the verbatim quote it came from and its offsets in that text, so a
caller can re-check it against the same bytes. A fact that cannot be matched is ``None``:
the permit number in particular is never guessed, because lineage hangs on it.

The header looks like::

    MEMORANDUM March 9, 2023
    SUBJECT:  Evaluation of Permit Application No. 2017-0987-C (M-2)
       ONEOK Gas Storage, L.L.C.
       West Edmond Station (Facility ID: 1226)

``normalize_permit`` is the join key shared with the public-review listing, whose permit
column reads ``2017-0987-C M-2``.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

HEADER_CHARS = 4_000  # the header is on page one; nothing beyond this is read for it
_MEMO_DATE = re.compile(r"MEMORANDUM[ \t]+([A-Z][a-z]{2,8}\.?[ \t]+\d{1,2},[ \t]+\d{4})")
_SUBJECT = re.compile(r"SUBJECT:[ \t]*", re.IGNORECASE)
_PERMIT = re.compile(
    r"No\.?[ \t]*(\d{4}-\d{2,5}-[A-Z]{1,4}\d{0,2}(?:[ \t]*\([ \t]*M-?\d{1,2}[ \t]*\)|[ \t]+M-?\d{1,2})?)(?![\w-])"
)
# Something that still looks like an amendment suffix after the match was not parsed: unknown.
_UNPARSED_AMENDMENT = re.compile(r"[ \t]*\(?[ \t]*M[ -]?\d")
_NOT_NAME = re.compile(
    r"^(?:section|sec\.|latitude|longitude|directions?|physical\s+address|[0-9])", re.IGNORECASE
)
_FACILITY_ID = re.compile(r"\b(?:AQD\s+)?(?:Facility|FAC)\s*ID\s*[:#]?\s*(\d{1,8})", re.IGNORECASE)
_FACILITY_LABEL = re.compile(r"\s*Facility:\s*(.+)$", re.IGNORECASE)
_SIC_TAIL = re.compile(r"\s*\((?:SIC|NAICS)\b.*$", re.IGNORECASE)
_PERMIT_FAMILY = re.compile(r"^(\d{4}-\d{2,5})")
_NORM_M = re.compile(r"\bM[ -]?(\d{1,2})\b")


def normalize_permit(value: str) -> str:
    """Join key: upper case, no parentheses, single spaces, ``M-n`` for amendment suffixes."""
    text = re.sub(r"[()]", " ", value.upper())
    text = " ".join(text.split())
    return _NORM_M.sub(r"M-\1", text)


def permit_family(norm: str) -> str | None:
    """``YYYY-NNNN`` prefix. Provenance only: it is never used to join documents."""
    match = _PERMIT_FAMILY.match(norm)
    return match.group(1) if match else None


@dataclass(frozen=True, slots=True)
class Quoted:
    value: str
    quote: str
    start: int
    end: int
    page: int | None

    def as_json(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "quote": self.quote[:200],
            "start": self.start,
            "end": self.end,
            "page": self.page,
        }


@dataclass(frozen=True, slots=True)
class MemoHeader:
    permit: Quoted | None
    permit_norm: str | None
    memo_date: Quoted | None  # value is ISO
    company: Quoted | None
    facility: Quoted | None
    facility_id: Quoted | None

    def as_json(self) -> dict[str, Any]:
        def one(item: Quoted | None) -> dict[str, Any] | None:
            return item.as_json() if item is not None else None

        return {
            "permit_number": one(self.permit),
            "permit_norm": self.permit_norm,
            "permit_family": permit_family(self.permit_norm) if self.permit_norm else None,
            "memo_date": one(self.memo_date),
            "company": one(self.company),
            "facility": one(self.facility),
            "facility_id": one(self.facility_id),
        }


def _clean_name(raw: str) -> str:
    cleaned = _SIC_TAIL.sub("", raw)
    return " ".join(cleaned.strip(" \t;,").split())


def _lines_after(text: str, offset: int, limit: int) -> list[tuple[int, int]]:
    """(start, end) of up to ``limit`` non-empty lines following the line holding ``offset``."""
    spans: list[tuple[int, int]] = []
    position = text.find("\n", offset)
    while position != -1 and len(spans) < limit:
        start = position + 1
        end = text.find("\n", start)
        stop = len(text) if end == -1 else end
        if text[start:stop].strip():
            spans.append((start, stop))
        position = end
    return spans


def parse_memo_header(
    text: str, page_of: Callable[[int], int | None] = lambda _offset: None
) -> MemoHeader:
    """Read permit number, memo date, company, facility and facility id from page one."""
    head = text[:HEADER_CHARS]

    def quoted(start: int, end: int, value: str) -> Quoted:
        return Quoted(value, text[start:end], start, end, page_of(start))

    memo_date: Quoted | None = None
    match = _MEMO_DATE.search(head)
    if match:
        raw = " ".join(match.group(1).replace(".", "").split())
        for fmt in ("%B %d, %Y", "%b %d, %Y"):
            try:
                iso = datetime.strptime(raw, fmt).date().isoformat()
            except ValueError:
                continue
            memo_date = quoted(match.start(1), match.end(1), iso)
            break
    permit: Quoted | None = None
    company: Quoted | None = None
    facility: Quoted | None = None
    facility_id: Quoted | None = None
    subject = _SUBJECT.search(head)
    found = None
    if subject is not None:
        # The number is on the SUBJECT line; it may wrap only directly after "No.".
        line_end = head.find("\n", subject.end())
        line_end = len(head) if line_end == -1 else line_end
        window_end = line_end
        if re.search(r"No\.?\s*$", head[subject.end() : line_end]):
            next_end = head.find("\n", line_end + 1)
            window_end = len(head) if next_end == -1 else next_end
        found = _PERMIT.search(head, subject.end(), window_end)
        if found is not None and _UNPARSED_AMENDMENT.match(head, found.end()):
            found = None  # never link an amendment memo to its base permit number
    if found is not None:
        permit = quoted(found.start(1), found.end(1), found.group(1))
        following = _lines_after(text, found.end(), 6)
        if following:
            start, end = following[0]
            name = _clean_name(text[start:end])
            if name and not _NOT_NAME.match(name) and not name.lower().startswith("facility"):
                company = quoted(start, end, name)
        for start, end in following[1:5]:
            raw = text[start:end]
            id_match = _FACILITY_ID.search(raw)
            if id_match is not None and facility_id is None:
                facility_id = quoted(
                    start + id_match.start(1), start + id_match.end(1), id_match.group(1)
                )
            if facility is not None or company is None:
                continue
            labelled = _FACILITY_LABEL.match(raw)
            body = labelled.group(1) if labelled else raw.strip()
            if not labelled and _NOT_NAME.match(body):
                continue
            name = _clean_name(_FACILITY_ID.sub("", body).replace("()", ""))
            name = name.strip(" ():-")
            if name:
                offset = start + raw.find(body)
                facility = quoted(offset, offset + len(body), name)
    norm = normalize_permit(permit.value) if permit is not None else None
    return MemoHeader(permit, norm, memo_date, company, facility, facility_id)
