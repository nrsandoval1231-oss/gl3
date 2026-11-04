"""Header-keyed equipment table extraction from page text lines.

Targets the Oklahoma DEQ style (`EU Point Description Horsepower Serial # Const. Date`,
`EUG-N` group titles) and any text table whose header names a rating column. The header
fixes how many trailing columns follow the rating column; rows that do not fit that shape
are skipped with an issue rather than guessed. Regulatory threshold text is never a row.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from gridlens.ingestion.parsers.permit_docs.lexicon import (
    HEADER_SYNONYMS,
    NUMBER_RE,
    YEAR_RE,
    drive_from_text,
    parse_number,
    state_from_text,
    type_from_text,
    unit_from_text,
)
from gridlens.ingestion.parsers.permit_docs.models import ExtractedRow, FieldEvidence, Route
from gridlens.ingestion.parsers.permit_docs.router import header_unit
from gridlens.ingestion.parsers.permit_docs.text_layer import CanonicalText

_GROUP = re.compile(r"^\s*EUG[- ]?\d+[A-Za-z]?\s*[:.\-]?\s*(?P<title>.*)$", re.I)
_ID_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/\-]{0,39}$")
_NUMBER_TOKEN = re.compile(rf"^{NUMBER_RE.pattern}$")
_THRESHOLD_CELL = re.compile(r"[<>≥≤]|greater|less\s+than|more\s+than|\bto\b\s+\d", re.I)
_VOCAB_EXTRA = {"(gallons)", "mmscfd", "rpm", "(mmbtuh)", "mmbtuh", "barrels", "gallons"}
_MAX_TABLE_ROWS = 2_000


@dataclass(slots=True)
class _Table:
    unit: str
    unit_evidence: FieldEvidence
    trailing: int
    n_date: int
    group: str
    group_evidence: FieldEvidence | None
    header_page: int


def _norm(token: str) -> str:
    return token.strip().lower()


def _is_header_line(line: str) -> bool:
    tokens = line.split()
    if not tokens or len(tokens) > 12:
        return False
    hits = sum(
        1
        for t in tokens
        if _norm(t) in HEADER_SYNONYMS or header_unit(t) or _norm(t) in _VOCAB_EXTRA
    )
    return hits / len(tokens) >= 0.8


def _find_unit_token(line: str) -> tuple[str, str, int] | None:
    """(token, unit, offset-in-line) of the first rating-unit header word in ``line``."""
    for match in re.finditer(r"\S+", line):
        unit = header_unit(match.group(0))
        if unit is not None:
            return match.group(0), unit, match.start()
    return None


def _parse_row(line: str, table: _Table) -> dict[str, tuple[str, int, int]] | None:
    """Return id/rating/description token positions (text, offset, end) or None."""
    tokens = [(m.group(0), m.start(), m.end()) for m in re.finditer(r"\S+", line)]
    k = table.trailing
    if len(tokens) < k + 2 or len(tokens) > 40:
        return None
    id_text, id_start, id_end = tokens[0]
    clean_id = id_text.rstrip(",;:")
    if not _ID_TOKEN.fullmatch(clean_id) or not any(c.isdigit() for c in clean_id):
        return None
    rating_text, rating_start, rating_end = tokens[-(k + 1)]
    if not _NUMBER_TOKEN.fullmatch(rating_text):
        return None
    tail = [t for t, _, _ in tokens[len(tokens) - k :]]
    if table.n_date and not any(YEAR_RE.fullmatch(t) for t in tail):
        return None
    if len(tokens) - k - 1 < 1:
        return None
    desc_tokens = tokens[1 : len(tokens) - k - 1]
    desc_start = desc_tokens[0][1] if desc_tokens else id_end
    desc_end = desc_tokens[-1][2] if desc_tokens else id_end
    return {
        "id": (clean_id, id_start, id_start + len(clean_id)),
        "rating": (rating_text, rating_start, rating_end),
        "desc": (line[desc_start:desc_end], desc_start, desc_end),
    }


def extract_tables(
    canon: CanonicalText, routes: dict[int, Route]
) -> tuple[list[ExtractedRow], list[str]]:
    rows, issues = _extract_header_keyed(canon, routes)
    capacity_rows, capacity_issues = extract_capacity_tables(canon, routes)
    return rows + capacity_rows, issues + capacity_issues


def _extract_header_keyed(
    canon: CanonicalText, routes: dict[int, Route]
) -> tuple[list[ExtractedRow], list[str]]:
    rows: list[ExtractedRow] = []
    issues: list[str] = []
    active: _Table | None = None
    group_title = ""
    group_evidence: FieldEvidence | None = None
    for page in canon.pages:
        route = routes.get(page.page, "irrelevant")
        if route in ("scan", "irrelevant") and active is None:
            continue
        if route == "scan":
            active = None  # a scanned page breaks stitching; never guess across it
            continue
        base = canon.page_starts[page.page - 1]
        lines = page.text.split("\n")
        offsets: list[int] = []
        cursor = base
        for line in lines:
            offsets.append(cursor)
            cursor += len(line) + 1
        index = 0
        while index < len(lines):
            line = lines[index]
            line_start = offsets[index]
            group_match = _GROUP.match(line)
            if group_match is not None:
                active = None
                group_title = line.strip()
                lead = len(line) - len(line.lstrip())
                group_evidence = FieldEvidence(
                    "group",
                    group_title,
                    group_title,
                    line_start + lead,
                    line_start + lead + len(group_title),
                    page.page,
                )
                index += 1
                continue
            if _is_header_line(line):
                block_lo = index
                while (
                    block_lo > 0 and index - block_lo < 2 and _is_header_line(lines[block_lo - 1])
                ):
                    block_lo -= 1
                block_hi = index
                while block_hi + 1 < len(lines) and block_hi - index < 2:
                    if not _is_header_line(lines[block_hi + 1]):
                        break
                    block_hi += 1
                block = list(range(block_lo, block_hi + 1))
                units = [
                    (i, found) for i in block if (found := _find_unit_token(lines[i])) is not None
                ]
                words = [_norm(t) for i in block for t in lines[i].split()]
                if units and _is_header_line(lines[units[0][0]]):
                    distinct = {u[1][1] for u in units}
                    if len(distinct) > 1:
                        issues.append(
                            f"Table header on page {page.page} names several rating units; skipped."
                        )
                        active = None
                    else:
                        line_i, (token, unit, rel) = units[0]
                        abs_start = offsets[line_i] + rel
                        active = _Table(
                            unit=unit,
                            unit_evidence=FieldEvidence(
                                "unit", unit, token, abs_start, abs_start + len(token), page.page
                            ),
                            trailing=int("serial" in words) + words.count("date"),
                            n_date=words.count("date"),
                            group=group_title,
                            group_evidence=group_evidence,
                            header_page=page.page,
                        )
                    index = block_hi + 1
                    continue
                active = None  # a header without a rating column starts a different table
                index = block_hi + 1
                continue
            if active is not None:
                parsed = _parse_row(line, active)
                if parsed is None:
                    if len(line.split()) >= 7 and re.search(r"[a-z]{3,}\s+[a-z]{3,}", line):
                        active = None  # prose ends the table
                    index += 1
                    continue
                row = _build_row(parsed, line, line_start, page.page, active, issues)
                if row is not None:
                    rows.append(row)
                    if len(rows) >= _MAX_TABLE_ROWS:
                        issues.append("Table row bound reached; remaining rows omitted.")
                        return rows, issues
            index += 1
    return rows, issues


def _build_row(
    parsed: dict[str, tuple[str, int, int]],
    line: str,
    line_start: int,
    page: int,
    table: _Table,
    issues: list[str],
) -> ExtractedRow | None:
    id_text, id_s, id_e = parsed["id"]
    rating_text, rt_s, rt_e = parsed["rating"]
    desc_text, d_s, d_e = parsed["desc"]
    if _THRESHOLD_CELL.search(line):
        issues.append(f"Threshold-like text in table row {id_text!r} on page {page}; skipped.")
        return None
    rating = parse_number(rating_text)
    if rating is None or rating <= 0:
        return None
    title = table.group_evidence
    type_value = type_from_text(desc_text) if desc_text else None
    type_source: tuple[str, int, int, int] | None = None
    if type_value is not None:
        type_source = (desc_text, line_start + d_s, line_start + d_e, page)
    elif title is not None and (type_value := type_from_text(title.quote)) is not None:
        type_source = (title.quote, title.start, title.end, title.page)
    if type_value is None or type_source is None:
        issues.append(f"No equipment type stated for table row {id_text!r} on page {page}.")
        return None
    evidence = {
        "id": FieldEvidence("id", id_text, id_text, line_start + id_s, line_start + id_e, page),
        "type": FieldEvidence("type", type_value, *type_source[:3], type_source[3]),
        "rating": FieldEvidence(
            "rating", str(rating), rating_text, line_start + rt_s, line_start + rt_e, page
        ),
        "unit": table.unit_evidence,
    }
    drive = "unknown"
    for quote, start, end, pg in (
        (desc_text, line_start + d_s, line_start + d_e, page),
        *(((title.quote, title.start, title.end, title.page),) if title else ()),
    ):
        if quote and (found := drive_from_text(quote)) != "unknown":
            drive = found
            evidence["drive"] = FieldEvidence("drive", found, quote, start, end, pg)
            break
    state = "unknown"
    if title is not None and (found_state := state_from_text(title.quote)) != "unknown":
        state = found_state
        evidence["state"] = FieldEvidence(
            "state", state, title.quote, title.start, title.end, title.page
        )
    return ExtractedRow(
        origin="table",
        equipment_id=id_text,
        equipment_type=type_value,
        drive=drive,
        rating=Decimal(rating),
        unit=table.unit,
        count=None,
        state=state,
        evidence=evidence,
        group=table.group,
        stitched=page != table.header_page,
    )


# NMED application Table 2-A / UA2 style: `ID make model serial 2250 HP 2250 HP ...` where the
# first value is the Rated Capacity and the equipment type is on the unit's own description
# line (`Compressor Engine ENG-1`) or inside the row (`Turbine (Compressor) Solar Saturn`).
_CAPACITY_UNIT = r"(?P<u{n}>HP|hp|kW|KW|MW|MMBtu/hr)"
_CAPACITY_ROW = re.compile(
    r"^(?P<id>[A-Za-z0-9][A-Za-z0-9._/\-]{0,39})\s+(?P<mid>\S.*?)\s+"
    rf"(?P<r1>{NUMBER_RE.pattern})\s*{_CAPACITY_UNIT.format(n=1)}\s+"
    rf"(?P<r2>{NUMBER_RE.pattern})\s*{_CAPACITY_UNIT.format(n=2)}(?![A-Za-z])"
)


def extract_capacity_tables(
    canon: CanonicalText, routes: dict[int, Route]
) -> tuple[list[ExtractedRow], list[str]]:
    rows: list[ExtractedRow] = []
    issues: list[str] = []
    for page in canon.pages:
        if routes.get(page.page) in (None, "scan"):
            continue
        if "Table 2-A" not in page.text and "Rated Capacity" not in page.text:
            continue
        lines = page.text.split(chr(10))
        offsets = []
        cursor = canon.page_starts[page.page - 1]
        for line in lines:
            offsets.append(cursor)
            cursor += len(line) + 1
        for index, line in enumerate(lines):
            match = _CAPACITY_ROW.match(line)
            if match is None or match.group("u1").lower() != match.group("u2").lower():
                continue
            row = _capacity_row(match, lines, offsets, index, page.page, issues)
            if row is not None:
                rows.append(row)
    return rows, issues


def _capacity_row(
    match: re.Match[str],
    lines: list[str],
    offsets: list[int],
    index: int,
    page: int,
    issues: list[str],
) -> ExtractedRow | None:
    line_start = offsets[index]
    id_text = match.group("id")
    if not any(c.isdigit() for c in id_text):
        return None
    rating = parse_number(match.group("r1"))
    unit_token = match.group("u1")
    if rating is None or rating <= 0:
        return None
    mid = match.group("mid")
    candidates = [(mid, line_start + match.start("mid"))]
    for neighbor in (index + 1, index - 1):
        if 0 <= neighbor < len(lines):
            text = lines[neighbor]
            lead = len(text) - len(text.lstrip())
            candidates.append((text.strip(), offsets[neighbor] + lead))
    type_value, type_quote, type_start = _capacity_type(candidates)
    if type_value is None:
        issues.append(f"No equipment type stated for capacity row {id_text!r} on page {page}.")
        return None
    unit = unit_from_text(unit_token)
    if unit is None:
        return None
    evidence = {
        "id": FieldEvidence(
            "id",
            id_text,
            id_text,
            line_start + match.start("id"),
            line_start + match.end("id"),
            page,
        ),
        "type": FieldEvidence(
            "type", type_value, type_quote, type_start, type_start + len(type_quote), page
        ),
        "rating": FieldEvidence(
            "rating",
            str(rating),
            match.group("r1"),
            line_start + match.start("r1"),
            line_start + match.end("r1"),
            page,
        ),
        "unit": FieldEvidence(
            "unit",
            unit,
            unit_token,
            line_start + match.start("u1"),
            line_start + match.end("u1"),
            page,
        ),
    }
    drive = drive_from_text(type_quote)
    if drive != "unknown":
        evidence["drive"] = FieldEvidence(
            "drive", drive, type_quote, type_start, type_start + len(type_quote), page
        )
    return ExtractedRow(
        origin="table",
        equipment_id=id_text,
        equipment_type=type_value,
        drive=drive,
        rating=Decimal(rating),
        unit=unit,
        count=None,
        state="unknown",
        evidence=evidence,
        group="capacity-table",
    )


_SERVICE_TAG = re.compile(r"\([^)]*\)")
_PRIME_MOVERS = {"engine", "turbine", "generator", "heater", "flare"}


def _capacity_type(candidates: list[tuple[str, int]]) -> tuple[str | None, str, int]:
    """Type from the row or its own description lines. Prime movers outrank service tags,
    and a type that appears only inside a parenthetical service tag is not used."""
    found: list[tuple[str, str, int]] = []
    for text, start in candidates:
        value = type_from_text(_SERVICE_TAG.sub(" ", text))
        if value is not None:
            found.append((value, text, start))
    for value, text, start in found:
        if value in _PRIME_MOVERS:
            return value, text, start
    if found:
        return found[0]
    return None, "", 0
