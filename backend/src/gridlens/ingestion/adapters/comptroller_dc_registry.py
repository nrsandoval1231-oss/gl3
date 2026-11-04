"""Texas Comptroller registered data-center lists (qualifying data centers and large projects).

**Discovery (verified live 2026-11-04; see docs/engineering/early-signal-sources-more-20261103.md).**
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


def parse_registry(html: bytes) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Registry rows (policy-checked, deterministic) and counts of what was skipped."""
    rows: dict[str, dict[str, Any]] = {}
    skipped = {"no_registration": 0, "duplicate": 0, "tables": 0}
    for table in more.parse_tables(html):
        if not table:
            continue
        header = [more.norm(c.text).casefold() for c in table[0]]
        if header != _HEADER:
            continue
        skipped["tables"] += 1
        for cells in table[1:]:
            if len(cells) == len(_COLUMNS) - 1:
                # A row that omits the trailing exemption-end cell: the end date is not listed.
                cells = [*cells, more.Cell()]
            if len(cells) != len(_COLUMNS):
                skipped["no_registration"] += 1
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
            if root in rows:
                skipped["duplicate"] += 1
                continue
            rows[root] = {
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
    return list(rows.values()), skipped


def _join(names: list[str]) -> str:
    return "; ".join(names) if names else "not listed"


def record_for(row: dict[str, Any], listed_on: str) -> dict[str, Any]:
    effective = _iso(row["effective"])
    lines = [
        f"Texas Comptroller registered {row['kind']}: {row['name'] or row['root']}",
        f"Registration: {', '.join(row['numbers'])}",
        f"Registration effective date (as listed): {row['effective'] or 'not listed'}",
        f"Owner: {_join(row['owners'])}",
        f"Occupant: {_join(row['occupants'])}",
        f"Operator: {_join(row['operators'])}",
        f"Exemption end date (as listed): {row['end'] or 'not listed'}",
        "The registry lists names, registration numbers and dates only: no county, address or MW "
        "(unknown is not zero). A registration is not a site, a load or a construction start.",
    ]
    canonical = "|".join(
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
) -> list[dict[str, Any]]:
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
        html = more.fetch_page(fetcher, ENDPOINT, query["max_response_bytes"], deadline, "Comptroller")
    finally:
        if own:
            http.close()
    rows, _skipped = parse_registry(html)
    if not rows:
        # A layout change or an error page is a loud failure, never an empty "nothing registered".
        raise SourceParseError("Comptroller registry page has no recognisable registry rows")
    return [record_for(row, listed_on) for row in rows][: query["max_records"]]
