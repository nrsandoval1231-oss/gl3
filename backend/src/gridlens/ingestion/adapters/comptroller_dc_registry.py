"""Texas Comptroller registered data-center lists (qualifying data centers and large projects).

**Discovery (verified live 2026-11-04;
see docs/engineering/early-signal-sources-more-20261103.md).**
``https://comptroller.texas.gov/taxes/data-centers/data-center-lists.php`` is a server-rendered
public page with two tables, "Registered Qualifying Data Center Projects" and "Registered
Qualifying Large Data Center Projects". Each row carries the project name, the registration
effective date, and owner, occupant and operator names with their registration numbers
(``DC######-OW1/OC1/OP1`` and ``LD######-...``) and an exemption end date. There is no download
link, county, address or MW. ``robots.txt`` allows ``/taxes/``.

One request per run (the page is about 145 KB), the declared generic user agent, no redirects,
exact URL policy. Each registry row is one evidence observation keyed by its registration number
root; a changed row (new operator, an exemption end date) is a new evidence version and the earlier
one stays. The source ships off. Registry rows carry names and dates only: a registration is not a
site, not a load and not a construction start, and the effective date is when the registration took
effect, not when the page listed it. Unknown is not zero.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import httpx

from gridlens.ingestion.adapters import early_signal_more as more
from gridlens.ingestion.adapters import early_signal_stage as stage
from gridlens.ingestion.adapters import tceq_application_documents as shared
from gridlens.ingestion.adapters.early_signal_http import EarlyFetcher
from gridlens.ingestion.adapters.federal_register import SourceParseError

SOURCE_ID = "texas-comptroller-dc-registry"
RETRIEVAL_METHOD = "comptroller-dc-registry"
ENDPOINT = "https://comptroller.texas.gov/taxes/data-centers/data-center-lists.php"
MAX_LISTING_BYTES = 3_000_000
MAX_RECORDS = 400
VERSION = "comptroller-dc-registry-v1"

_COLUMNS = (
    "name",
    "effective",
    "owner",
    "owner_no",
    "occupant",
    "occupant_no",
    "operator",
    "operator_no",
    "end",
)
_HEADER = [
    "data center",
    "effective date",
    "owner name",
    "owner registration number",
    "occupant name",
    "occupant registration number",
    "operator name",
    "operator registration number",
    "exemption end date",
]
_REGISTRATION = re.compile(r"\b(?P<root>(?:DC|LD)\d{6})-(?P<role>O[WCP]\d{1,2})\b")
_US_DATE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
_KIND = {"DC": "qualifying data center", "LD": "qualifying large data center project"}


def url_ok(url: Any) -> bool:
    return url == ENDPOINT


def valid_query(query: Any) -> bool:
    return (
        isinstance(query, dict)
        and set(query) == {"max_response_bytes", "max_records"}
        and query["max_response_bytes"] == MAX_LISTING_BYTES
        and type(query["max_records"]) is int
        and 1 <= query["max_records"] <= MAX_RECORDS
    )


def config_from_source(source: dict[str, Any]) -> stage.StageConfig | None:
    """No document stage: the registry rows are the evidence."""
    return None


def apply_prior_states(records: list[dict[str, Any]], prior: dict[str, dict[str, Any]]) -> None:
    return None


def _iso(value: str) -> str | None:
    found = _US_DATE.fullmatch(value.strip())
    if found is None:
        return None
    try:
        return date(int(found[3]), int(found[1]), int(found[2])).isoformat()
    except ValueError:
        return None


def _names(cell: more.Cell) -> list[str]:
    return [s[:160] for s in (cell.items or ([cell.text] if cell.text else []))][:12]


# The page has typos ("DC 358218-OW1", "LD693418-0P1"): a number cell only has to look like
# a registration, so a misaligned column (a name or a date in a number cell) is what fails.
_NUMBER_LIKE = re.compile(r"(?:DC|LD)\s?\d")


def _canonical(row: dict[str, Any]) -> str:
    return "|".join(
        [
            row["root"],
            row["name"],
            row["effective"],
            *row["numbers"],
            *row["owners"],
            *row["occupants"],
            *row["operators"],
            row["end"],
        ]
    )


def _readable_row(cells: list[more.Cell]) -> list[more.Cell] | None:
    """The nine cells of a row, or None when the row cannot be read as a registry row.

    A row of eight cells is padded (end date "not listed") only when its seventh cell is a
    registration number, so a row that lost another cell is skipped rather than shifted.
    """
    if any(c.span != 1 for c in cells):
        return None
    if len(cells) == len(_COLUMNS) - 1:
        if _NUMBER_LIKE.search(cells[-1].text) is None:
            return None
        cells = [*cells, more.Cell()]
    if len(cells) != len(_COLUMNS):
        return None
    named = dict(zip(_COLUMNS, cells, strict=True))
    for key in ("name", "owner", "occupant", "operator"):
        if any(_REGISTRATION.search(v) for v in _names(named[key]) + [named[key].text]):
            return None  # a number in a name column: the columns have shifted
    for key in ("owner_no", "occupant_no", "operator_no"):
        values = _names(named[key])
        if any(_NUMBER_LIKE.search(v) is None for v in values):
            return None  # a name or date in a number column
    if _DATE_LIKE.search(named["effective"].text) is None:
        return None
    return cells


_DATE_LIKE = re.compile(r"\d{1,2}/\d")


def parse_registry(html: bytes) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Registry rows (policy-checked, deterministic) and counts of what was skipped.

    The counts include ``rows`` (rows seen) so the caller can fail loudly on a layout change.
    """
    candidates: dict[str, list[dict[str, Any]]] = {}
    skipped = {"unreadable_row": 0, "no_registration": 0, "duplicate": 0, "tables": 0, "rows": 0}
    for table in more.parse_tables(html):
        if not table:
            continue
        header = [more.norm(c.text).casefold() for c in table[0]]
        if header != _HEADER:
            continue
        skipped["tables"] += 1
        for raw in table[1:]:
            skipped["rows"] += 1
            cells = _readable_row(raw)
            if cells is None:
                skipped["unreadable_row"] += 1
                continue
            row = dict(zip(_COLUMNS, cells, strict=True))
            numbers = [
                m["root"] + "-" + m["role"]
                for key in ("owner_no", "occupant_no", "operator_no")
                for item in _names(row[key])
                for m in _REGISTRATION.finditer(item)
            ]
            roots = sorted({n.split("-")[0] for n in numbers})
            if len(roots) != 1:
                # No registration number, or two different roots in one row: not an identity.
                skipped["no_registration"] += 1
                continue
            root = roots[0]
            candidates.setdefault(root, []).append(
                {
                    "root": root,
                    "kind": _KIND[root[:2]],
                    "name": row["name"].text[:200],
                    "effective": row["effective"].text[:20],
                    "owners": _names(row["owner"]),
                    "occupants": _names(row["occupant"]),
                    "operators": _names(row["operator"]),
                    "numbers": sorted(set(numbers)),
                    "end": row["end"].text[:20],
                }
            )
    rows: list[dict[str, Any]] = []
    for root in sorted(candidates):
        found = candidates[root]
        # The same root twice: keep the smallest canonical text, so the choice does not depend on
        # the order the rows appear in.
        rows.append(min(found, key=_canonical))
        skipped["duplicate"] += len(found) - 1
    return rows, skipped


def _join(names: list[str]) -> str:
    return "; ".join(names) if names else "not listed"


def _public_names(values: list[str]) -> list[str]:
    """Keep organization names; replace names or addresses identified as personal data."""
    return [
        "individual name withheld" if more.has_person(value) or more.has_address(value) else value
        for value in values
    ]


def record_for(row: dict[str, Any], listed_on: str) -> dict[str, Any]:
    # Do not put detected personal names or addresses into retained source text or its hash.
    owners = _public_names(row["owners"])
    occupants = _public_names(row["occupants"])
    operators = _public_names(row["operators"])
    effective = _iso(row["effective"])
    lines = [
        f"Texas Comptroller registered {row['kind']}: {row['name'] or row['root']}",
        f"Registration: {', '.join(row['numbers'])}",
        f"Registration effective date (as listed): {row['effective'] or 'not listed'}",
        f"Owner: {_join(owners)}",
        f"Occupant: {_join(occupants)}",
        f"Operator: {_join(operators)}",
        f"Exemption end date (as listed): {row['end'] or 'not listed'}",
        "The registry lists names, registration numbers and dates only: no county, address or MW "
        "(unknown is not zero). A registration is not a site, a load or a construction start.",
    ]
    canonical_row = {**row, "owners": owners, "occupants": occupants, "operators": operators}
    canonical = _canonical(canonical_row)
    return {
        "document_number": "TXCOMP-" + row["root"],
        "title": f"Comptroller {row['kind']}: {row['name'] or row['root']}"[:250],
        "abstract": "\n".join(lines),
        # The page carries no publication date; the effective date is when the registration took
        # effect and is kept as an event date, never as the time the page listed it.
        "publication_date": None,
        "event_date": effective,
        "event_date_label": "registration effective" if effective else None,
        "html_url": ENDPOINT,
        "extraction_location": f"registry table row {row['root']}",
        "source_hash": hashlib.sha256(canonical.encode()).hexdigest(),
        "listed_on": listed_on,
        "registry": {"version": VERSION, "root": row["root"], "kind": row["kind"]},
    }


def retrieve(
    source: dict[str, Any],
    client: httpx.Client | None = None,
    *,
    deadline: float | None = None,
    pacer: Callable[[], None] | None = None,
    today: date | None = None,
) -> Any:
    if source.get("id") != SOURCE_ID or source.get("endpoint") != ENDPOINT:
        raise SourceParseError("Comptroller registry source is not the reviewed endpoint")
    query = source.get("query")
    if not valid_query(query):
        raise SourceParseError("Comptroller registry configuration is invalid")
    assert isinstance(query, dict)
    listed_on = (today or datetime.now(UTC).date()).isoformat()
    own = client is None
    http = client or stage.new_client()
    try:
        fetcher = EarlyFetcher(http, pacer or shared.Pacer(), url_ok)
        html = more.fetch_page(
            fetcher, ENDPOINT, query["max_response_bytes"], deadline, "Comptroller"
        )
    finally:
        if own:
            http.close()
    rows, counts = parse_registry(html)
    if not rows:
        # A layout change or an error page is a loud failure, never an empty "nothing registered".
        raise SourceParseError("Comptroller registry page has no recognisable registry rows")
    records = [record_for(row, listed_on) for row in rows][: query["max_records"]]
    # Rows that were seen but not read are reported, and too many of them fail the run. A
    # duplicate registration number is reported too (the smallest row is kept).
    skipped = {
        k: v for k, v in counts.items() if k in {"unreadable_row", "no_registration", "duplicate"}
    }
    return more.acquisition_result(records, skipped, counts["rows"], "Comptroller")
