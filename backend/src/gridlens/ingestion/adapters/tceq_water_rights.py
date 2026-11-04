"""TCEQ pending surface-water right applications (applicant, county, dates, notice volumes).

**Discovery (verified live 2026-11-04;
see docs/engineering/early-signal-sources-more-20261103.md).**
``https://www.tceq.texas.gov/permitting/water_rights/wr-permitting/view-wr-pend-apps`` is a
server-rendered public page, refreshed weekly, with one table per river basin (accordion). Each row
has the applicant, the WR number, the county, the date received by TCEQ, and links to the
application, the administratively complete package, the notice package and a public meeting
package, each with its date. Individual notice PDFs state requested or existing volumes in
acre-feet. ``robots.txt`` does not disallow the page or the downloads.

Neither the listing nor a notice states an end use of "data center"; most applicants are cities,
districts and farms. The listing facts are evidence on their own; the document stage reads the
text layer of the first four pages of a *notice* package only (the read stops there; a longer file
is not an error), and keeps each stated acre-feet figure with its verbatim quote and a
deterministic role taken from the clause that holds the figure (requested, existing authorization,
or just stated).

Personal data: an applicant name is kept only when it has an organisation shape (a company, city,
district, ...). An individual's name is replaced by "individual applicant (name withheld)" in every
title, abstract and hash, the notice of an individual is not read, and any quote that contains the
applicant's name or an address is dropped.
Figures are never summed and a volume is never converted to a demand. The notice packages can be
large (observed 32 MB, 165 pages); the size cap is 40 MB and a bounded number is read per run. The
source ships off.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from gridlens.ingestion.adapters import early_signal_more as more
from gridlens.ingestion.adapters import early_signal_stage as stage
from gridlens.ingestion.adapters import ercot_rpg_extract as pdf_text
from gridlens.ingestion.adapters import tceq_application_documents as shared
from gridlens.ingestion.adapters.early_signal_http import PDF, EarlyFetcher
from gridlens.ingestion.adapters.federal_register import SourceParseError

SOURCE_ID = "texas-tceq-water-rights-pending"
RETRIEVAL_METHOD = "tceq-water-rights-pending"
ENDPOINT = "https://www.tceq.texas.gov/permitting/water_rights/wr-permitting/view-wr-pend-apps"
NOTICE_BASE = "https://www.tceq.texas.gov/downloads/permitting/water-rights/pending/notice/"
MAX_LISTING_BYTES = 3_000_000
MAX_PDF_BYTES = 40 * 1024 * 1024
MAX_RECORDS = 400
RECHECK_HOURS = 24.0 * 14
NOTICE_PAGES = 4
MAX_VOLUMES = 8
EXTRACT_VERSION = "tceq-water-notice-v1"
WITHHOLD_WITHOUT_DOCUMENTS = False

_HEADER = [
    "applicant",
    "wr no.",
    "county",
    "received by tceq",
    "admin. complete",
    "notice issued",
    "public meeting",
]
_NOTICE = re.compile(re.escape(NOTICE_BASE) + r"[A-Za-z0-9][A-Za-z0-9._-]{0,150}\.pdf")
_LINK_PATH = re.compile(
    r"/downloads/permitting/water-rights/pending/"
    r"(?P<kind>application|admin-complete|notice|public-meeting)/"
    r"(?P<name>[A-Za-z0-9][A-Za-z0-9._-]{0,150}\.pdf)"
)
_WR_NO = re.compile(r"[0-9A-Za-z]{1,3}-?[0-9]{2,6}[A-Za-z]{0,2}")
_US_DATE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


def notice_url_ok(url: Any) -> bool:
    return isinstance(url, str) and len(url) <= 400 and _NOTICE.fullmatch(url) is not None


def url_ok(url: Any) -> bool:
    return url == ENDPOINT or notice_url_ok(url)


def valid_query(query: Any) -> bool:
    return (
        isinstance(query, dict)
        and set(query) == {"max_response_bytes", "max_records", "documents"}
        and query["max_response_bytes"] == MAX_LISTING_BYTES
        and type(query["max_records"]) is int
        and 1 <= query["max_records"] <= MAX_RECORDS
        and stage.valid_config(query["documents"], None)
    )


def config_from_source(source: dict[str, Any]) -> stage.StageConfig | None:
    return stage.config_from((source.get("query") or {}).get("documents"))


# --------------------------------------------------------------------------- listing


def _iso(value: str) -> str | None:
    found = _US_DATE.search(value)
    if found is None:
        return None
    try:
        return date(int(found[3]), int(found[1]), int(found[2])).isoformat()
    except ValueError:
        return None


def _link_kind(href: str) -> tuple[str, str, str] | None:
    """(kind, file name, absolute URL) of a TCEQ download link, or None. Joined before matching."""
    absolute = urljoin(ENDPOINT, href.strip())
    parts = urlsplit(absolute)
    if (
        parts.scheme != "https"
        or parts.netloc != "www.tceq.texas.gov"
        or parts.query
        or parts.fragment
    ):
        return None
    found = _LINK_PATH.fullmatch(parts.path)
    return (found["kind"], found["name"], absolute) if found else None


def _parse(html: bytes) -> tuple[list[dict[str, Any]], dict[str, int], int]:
    rows: dict[str, dict[str, Any]] = {}
    skipped = {"malformed_row": 0, "bad_identity": 0, "duplicate": 0}
    seen = 0
    seen_table = False
    for table in more.parse_tables(html):
        if not table or [more.norm(c.text).casefold() for c in table[0]] != _HEADER:
            continue
        seen_table = True
        for cells in table[1:]:
            seen += 1
            if len(cells) != len(_HEADER) or any(c.span != 1 for c in cells):
                skipped["malformed_row"] += 1
                continue
            applicant, wr_no, county = (cells[0].text[:200], cells[1].text.strip(), cells[2].text)
            if not applicant or _WR_NO.fullmatch(wr_no) is None:
                skipped["bad_identity"] += 1
                continue
            organisation = more.is_organisation(applicant)
            row: dict[str, Any] = {
                # A person's name is never stored: not in a title, an abstract, a hash or a URL.
                "applicant": applicant if organisation else more.INDIVIDUAL_APPLICANT,
                "organisation": organisation,
                "wr_no": wr_no,
                "county": county[:80],
                "received": cells[3].text,
                "admin_complete": cells[4].text,
                "notice_issued": cells[5].text,
                "public_meeting": cells[6].text,
                "notice_url": None,
                "files": [],
            }
            for cell in cells[3:]:
                for href, _text in cell.links:
                    link = _link_kind(href)
                    if link is None:
                        continue
                    if organisation:
                        row["files"].append(link[1])
                        if link[0] == "notice" and notice_url_ok(link[2]):
                            row["notice_url"] = link[2]
            if wr_no in rows:
                skipped["duplicate"] += 1
                continue
            rows[wr_no] = row
    if not seen_table:
        raise SourceParseError("TCEQ pending-applications page has no recognisable table")
    return list(rows.values()), skipped, seen


def parse_listing(html: bytes) -> list[dict[str, Any]]:
    rows, _skipped, _seen = _parse(html)
    if not rows:
        raise SourceParseError("TCEQ pending-applications table has no readable rows")
    return rows


def _safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", value)[:40]


def record_for(row: dict[str, Any], listed_on: str) -> dict[str, Any]:
    lines = [
        f"TCEQ pending water right application {row['wr_no']}: {row['applicant']}",
        f"County (as listed): {row['county'] or 'not listed'}",
        f"Received by TCEQ (as listed): {row['received'] or 'not listed'}",
        f"Administratively complete (as listed): {row['admin_complete'] or 'not listed'}",
        f"Notice issued (as listed): {row['notice_issued'] or 'not listed'}",
        f"Public meeting (as listed): {row['public_meeting'] or 'not listed'}",
        "The listing states no volume or use: unknown is not zero. A water-right application is "
        "not a data-center project and its volume is not a power load.",
    ]
    if not row["organisation"]:
        lines.append(
            "The applicant is not an organisation: the name is withheld and no notice is read."
        )
    canonical = "|".join(
        [
            row["wr_no"],
            row["applicant"],
            row["county"],
            row["received"],
            row["admin_complete"],
            row["notice_issued"],
            row["public_meeting"],
            *row["files"],
        ]
    )
    notice = row["notice_url"]
    return {
        "document_number": "TCEQWR-" + _safe(row["wr_no"]),
        "title": f"TCEQ water right application {row['wr_no']}: {row['applicant']}"[:250],
        "abstract": "\n".join(lines),
        "publication_date": _iso(row["notice_issued"]),
        "event_date": _iso(row["received"]),
        "event_date_label": "received by TCEQ" if _iso(row["received"]) else None,
        "html_url": notice or ENDPOINT,
        "extraction_location": f"pending applications table, WR {row['wr_no']}",
        "source_hash": hashlib.sha256(canonical.encode()).hexdigest(),
        "state_key": notice,
        "doc_url": notice,
        "doc_kind": "water_notice" if notice else None,
        "applicant": row["applicant"] if row["organisation"] else None,
        "listed_on": listed_on,
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
        raise SourceParseError("TCEQ water-rights source is not the reviewed endpoint")
    query = source.get("query")
    if not valid_query(query):
        raise SourceParseError("TCEQ water-rights configuration is invalid")
    assert isinstance(query, dict)
    listed_on = (today or datetime.now(UTC).date()).isoformat()
    own = client is None
    http = client or stage.new_client()
    try:
        fetcher = EarlyFetcher(http, pacer or shared.Pacer(), url_ok)
        html = more.fetch_page(fetcher, ENDPOINT, query["max_response_bytes"], deadline, "TCEQ")
    finally:
        if own:
            http.close()
    rows, skipped, seen = _parse(html)
    if not rows:
        raise SourceParseError("TCEQ pending-applications table has no readable rows")
    records = [record_for(row, listed_on) for row in rows][: query["max_records"]]
    return more.acquisition_result(records, skipped, seen, "TCEQ")


# --------------------------------------------------------------------------- notice extraction

_ACRE_FEET = re.compile(r"(?<![\w.])(?P<n>\d[\d,]*(?:\.\d+)?)\s*acre[- ]?feet\b", re.I)
_REQUESTED = re.compile(
    r"\b(?:requests?|requested|requesting|seeks?|proposes?|applies|applying|to authorize)\b", re.I
)
_EXISTING = re.compile(
    r"\b(?:authorizes?|authorized|authorizing|currently|existing|presently)\b", re.I
)
# A clause ends at a semicolon, a sentence end (a period, then a capital) or "which".
_CLAUSE_END = re.compile(r";|(?<=[a-z0-9)])\.\s+(?=[A-Z])|\bwhich\b|\bwhereas\b", re.I)
_PURPOSES = (
    "municipal",
    "industrial",
    "agricultural",
    "irrigation",
    "mining",
    "domestic",
    "recreation",
    "hydroelectric",
    "cooling",
)
_PURPOSE = re.compile(
    r"\b(?:for|of)\s+(?P<p>" + "|".join(_PURPOSES) + r")\s+(?:purposes?|use)\b", re.I
)
_DATA_CENTER = re.compile(r"\bdata[- ]?centers?\b", re.I)


def _clause(text: str, start: int, end: int) -> tuple[int, int]:
    """Bounds of the clause that holds ``text[start:end]``."""
    lo = 0
    for m in _CLAUSE_END.finditer(text, 0, start):
        lo = m.end()
    nxt = _CLAUSE_END.search(text, end)
    return lo, (nxt.start() if nxt else len(text))


def volume_role(text: str, start: int, end: int) -> str:
    """requested / existing_authorization / stated, from the clause that holds the figure.

    The nearest verb before the figure decides; a clause that holds both verb classes is just
    ``stated`` (the figures cannot be told apart safely).
    """
    lo, hi = _clause(text, start, end)
    clause = text[lo:hi]
    requested = [m.start() for m in _REQUESTED.finditer(clause)]
    existing = [m.start() for m in _EXISTING.finditer(clause)]
    if requested and existing:
        return "stated"
    before = start - lo
    if requested and any(r < before for r in requested):
        return "requested"
    if existing and any(e < before for e in existing):
        return "existing_authorization"
    return "stated"


def _acre_feet(number: str) -> int | str:
    value = Decimal(number.replace(",", ""))
    if value == value.to_integral_value():
        return int(value)
    return format(value.normalize(), "f")


def _personal(quote_: str, applicant: str | None) -> bool:
    """Whether a quote carries an address, or the (individual) applicant's name."""
    if more.has_address(quote_) or more.has_person(quote_):
        return True
    return (
        bool(applicant)
        and len(applicant or "") >= 3
        and (applicant or "").casefold() in quote_.casefold()
    )


def extract_notice(
    pages: list[str],
    scanned: list[int],
    applicant: str | None = None,
    organisation: bool = True,
) -> dict[str, Any]:
    """Volumes, purposes and the applicant's name from the first pages of a notice.

    ``applicant`` is the name as printed on the listing. When the applicant is not an organisation
    the name is never stored and every quote that contains it, or any address, is dropped.
    """
    volumes: list[dict[str, Any]] = []
    purposes: list[dict[str, Any]] = []
    data_center: dict[str, Any] | None = None
    applicant_named: dict[str, Any] | None = None
    withheld = 0
    seen: set[tuple[int, int]] = set()
    for number, page in enumerate(pages[:NOTICE_PAGES], start=1):
        page_norm = more.norm(page)
        for match in _ACRE_FEET.finditer(page_norm):
            value = _acre_feet(match["n"])
            lo, hi = more.window_span(page_norm, match.start(), match.end(), 160, 120)
            quote_ = page_norm[lo:hi]
            # The value must reproduce from its own span inside the quote.
            own = _ACRE_FEET.match(quote_, match.start() - lo)
            if own is None or own.end() != match.end() - lo or _acre_feet(own["n"]) != value:
                continue
            if (number, match.start()) in seen or len(volumes) >= MAX_VOLUMES:
                continue
            if _personal(quote_, applicant if not organisation else None) or (
                organisation and more.has_address(quote_)
            ):
                withheld += 1
                continue
            seen.add((number, match.start()))
            item = more.evidence(
                value,
                "documented",
                number,
                quote_,
                page_norm,
                start=lo,
                unit="acre-feet",
                role=volume_role(page_norm, match.start(), match.end()),
            )
            if item is not None:
                volumes.append(item)
        for match in _PURPOSE.finditer(page_norm):
            lo, hi = more.window_span(page_norm, match.start(), match.end(), 100, 60)
            quote_ = page_norm[lo:hi]
            if _personal(quote_, applicant if not organisation else None) or more.has_address(
                quote_
            ):
                withheld += 1
                continue
            item = more.evidence(
                match["p"].casefold(), "documented", number, quote_, page_norm, start=lo
            )
            if (
                item is not None
                and len(purposes) < 6
                and all(p["value"] != item["value"] for p in purposes)
            ):
                purposes.append(item)
        if data_center is None and (found := _DATA_CENTER.search(page_norm)):
            lo, hi = more.window_span(page_norm, found.start(), found.end())
            quote_ = page_norm[lo:hi]
            if _personal(quote_, applicant if not organisation else None):
                withheld += 1
            else:
                data_center = more.evidence(True, "documented", number, quote_, page_norm, start=lo)
        if organisation and applicant and applicant_named is None and len(applicant) >= 4:
            at = page_norm.casefold().find(applicant.casefold())
            if at >= 0:
                lo, hi = more.window_span(page_norm, at, at + len(applicant), 40, 80)
                quote_ = page_norm[lo:hi]
                if not more.has_address(quote_):
                    applicant_named = more.evidence(
                        applicant, "documented", number, quote_, page_norm, start=lo
                    )
    lines = [
        f'Acre-feet stated (page {v["page"]}, {v["role"]}): {v["value"]} ("{v["quote"][:200]}")'
        for v in volumes
    ]
    lines += [f"Purpose stated (page {p['page']}): {p['value']}" for p in purposes]
    if data_center is not None:
        lines.append(f"Notice text names a data center (page {data_center['page']}).")
    if withheld:
        lines.append(f"{withheld} statement(s) withheld: they carried a name or an address.")
    return {
        "extractor": EXTRACT_VERSION,
        "pages": len(pages),
        "scanned_pages": scanned,
        "volumes": volumes,
        "purposes": purposes,
        "data_center": data_center,
        "applicant_named": applicant_named,
        "withheld_statements": withheld,
        "summary_lines": lines,
        "fields_found": len(volumes),
        "abstain": None
        if volumes
        else {"reason": "no acre-feet figure in the first pages", "note": "Abstention, not zero."},
    }


def _extract(
    body: bytes, item: stage.DocItem, prior: dict[str, Any] | None, budget: float, isolate: bool
) -> dict[str, Any]:
    pages, scanned = pdf_text.read_pdf_pages(body, budget, isolate, first_pages=NOTICE_PAGES)
    applicant = item.meta.get("applicant")
    return extract_notice(pages, scanned, applicant if isinstance(applicant, str) else None)


EXTRACTORS: dict[str, stage.Extractor] = {"water_notice": _extract}


def item_for(record: dict[str, Any]) -> stage.DocItem | None:
    url = record.get("doc_url")
    if not notice_url_ok(url) or record.get("doc_kind") != "water_notice":
        return None
    if record.get("state_key") != url:
        return None
    return stage.DocItem(
        key=str(url),
        url=str(url),
        kind="water_notice",
        max_bytes=MAX_PDF_BYTES,
        media_types=PDF,
        recheck_hours=RECHECK_HOURS,
        meta={
            "published_at": record.get("publication_date"),
            "applicant": record.get("applicant"),
        },
    )


def run_stage(
    records: list[dict[str, Any]],
    prior_states: dict[str, dict[str, Any]],
    *,
    client: httpx.Client | None,
    config: stage.StageConfig,
    index: dict[str, Any] | None = None,
    deadline: float | None = None,
    pacer: Callable[[], None] | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> stage.EarlyStageReport:
    return more.run_document_stage(
        records,
        prior_states,
        client=client,
        config=config,
        index=index,
        deadline=deadline,
        pacer=pacer,
        now=now,
        policy=url_ok,
        extractors=EXTRACTORS,
        item_for=item_for,
        withhold_unread=WITHHOLD_WITHOUT_DOCUMENTS,
    )


def apply_prior_states(records: list[dict[str, Any]], prior: dict[str, dict[str, Any]]) -> None:
    more.apply_prior_states(records, prior, item_for, WITHHOLD_WITHOUT_DOCUMENTS)
