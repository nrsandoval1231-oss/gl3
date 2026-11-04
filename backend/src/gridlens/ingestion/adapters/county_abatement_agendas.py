"""County commissioners' court agendas that mention tax abatements or data centers (pilot: Haskell).

**Discovery (verified live 2026-11-04;
see docs/engineering/early-signal-sources-more-20261103.md).**
Three Texas counties with data-center abatement activity were examined:

* **Haskell County** (Crusoe; Homebound data-center abatements): ``www.haskellcountytx.gov``
serves a
  server-rendered Commissioners Court page, ``/page/haskell.Commissioners.Court``, that links every
  2026 agenda under ``/upload/page/7690/``; the files answer 200 directly. No ``robots.txt``
  (404). Implemented. About half of the agendas have a text layer; the rest are scans (an
  abstention: no OCR here), and two are ``.doc`` files (not read).
* **Milam County** (Orion, Riot): the agendas page is machine-readable, but each PDF link answers
  302 to a third-party CMS host (``cms2.revize.com``). Redirects are never followed, so Milam is
  documented but not implemented.
* **Medina County** (CyrusOne): agendas are hosted on ``destinyhosted.com``, whose ``robots.txt``
  disallows everything. Not read.

Only explicit statements are extracted: an agenda item that names a tax abatement, a Chapter 312
agreement, a reinvestment zone or a data center. Each item is a verbatim slice of the page text with
its page and span; the entity, a stated dollar investment, a stated MW, an acreage and a stated
location are kept only when the same pattern, run again on their own quote, returns the same value.
An agenda item is a topic for discussion or action, not an approval, an investment or a load.
Unknown is not zero. The source ships off.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import quote, urljoin, urlsplit

import httpx

from gridlens.ingestion.adapters import early_signal_more as more
from gridlens.ingestion.adapters import early_signal_stage as stage
from gridlens.ingestion.adapters import ercot_rpg_extract as pdf_text
from gridlens.ingestion.adapters import tceq_application_documents as shared
from gridlens.ingestion.adapters.early_signal_http import PDF, EarlyFetcher
from gridlens.ingestion.adapters.federal_register import SourceParseError

SOURCE_ID = "texas-county-abatement-agendas"
RETRIEVAL_METHOD = "tx-county-abatement-agendas"
HASKELL_PAGE = "https://www.haskellcountytx.gov/page/haskell.Commissioners.Court"
ENDPOINT = HASKELL_PAGE
COUNTIES = ("haskell",)
MAX_LISTING_BYTES = 3_000_000
MAX_PDF_BYTES = 15 * 1024 * 1024
MAX_RECORDS = 60
MAX_AGENDAS = 40
RECHECK_HOURS = 24.0 * 30
MAX_ITEMS = 12
EXTRACT_VERSION = "county-abatement-agenda-v1"
WITHHOLD_WITHOUT_DOCUMENTS = True

_FILE = re.compile(
    r"https://www\.haskellcountytx\.gov/upload/page/7690/(?:docs/)?"
    r"[A-Za-z0-9][A-Za-z0-9._%()+,-]{0,200}\.pdf"
)
_SKIP_LABEL = re.compile(r"cancel", re.I)
_LABEL_DATE = re.compile(r"\b(?P<mon>[A-Z][a-z]{2,8})\.? (?P<d>\d{1,2}), (?P<y>20\d{2})\b")
_AGENDA_START = re.compile(r"(?:^|(?<=\s))(?P<n>\d{1,2})\.\s+(?=[A-Z])")
_ABATEMENT = re.compile(
    r"\b(?:tax abatements?|property tax abatements?|abatement agreements?|chapter 312|"
    r"reinvestment zones?)\b",
    re.I,
)
_DATA_CENTER = re.compile(r"\b(?:data[- ]?centers?|large[- ]loads?|hyperscale)\b", re.I)
_COMPANY_SUFFIX = r"(?:LLC|L\.L\.C\.|LP|L\.P\.|Inc\.?|Corp\.?|Corporation|Company|Co\.|Ltd\.?|LLP)"
_ENTITY = re.compile(
    r"\b(?:(?:agreement|abatement|application|request|zone)\s+(?:with|from|by|for)|"
    r"between\s+[A-Z][a-z]+ County(?:,? Texas)?\s+and)\s+"
    rf"(?P<v>[A-Z][A-Za-z0-9&.'’ -]{{1,80}}?,? {_COMPANY_SUFFIX})(?=[\s,;.)]|$)"
)
_MONEY_SCALED = re.compile(r"\$\s?(?P<n>\d[\d,]*(?:\.\d+)?)\s*(?P<u>million|billion)\b", re.I)
_MONEY_PLAIN = re.compile(r"\$\s?(?P<n>\d{1,3}(?:,\d{3})+)(?![\d,])")
_MW = re.compile(
    r"(?<![\w.])(?P<n>\d[\d,]*(?:\.\d+)?)\s*(?P<u>MW|megawatts?|GW|gigawatts?)\b", re.I
)
_ACRES = re.compile(r"(?<![\w.])(?P<n>\d[\d,]*(?:\.\d+)?)[- ]acres?\b", re.I)
_LOCATION = re.compile(
    r"\b(?:located|situated)\s+(?:at|on|near|in|within)\s+(?P<v>[^.;]{5,120}?)(?=[.;,]|$)"
)


def file_url_ok(url: Any) -> bool:
    return isinstance(url, str) and len(url) <= 400 and _FILE.fullmatch(url) is not None


def url_ok(url: Any) -> bool:
    return url == HASKELL_PAGE or file_url_ok(url)


def valid_query(query: Any) -> bool:
    return (
        isinstance(query, dict)
        and set(query)
        == {"max_response_bytes", "max_records", "max_agendas", "counties", "documents"}
        and query["max_response_bytes"] == MAX_LISTING_BYTES
        and type(query["max_records"]) is int
        and 1 <= query["max_records"] <= MAX_RECORDS
        and type(query["max_agendas"]) is int
        and 1 <= query["max_agendas"] <= MAX_AGENDAS
        and query["counties"] == list(COUNTIES)
        and stage.valid_config(query["documents"], None)
    )


def config_from_source(source: dict[str, Any]) -> stage.StageConfig | None:
    return stage.config_from((source.get("query") or {}).get("documents"))


# --------------------------------------------------------------------------- listing


def _label_date(label: str) -> str | None:
    found = _LABEL_DATE.search(label)
    if found is None:
        return None
    for fmt in ("%B %d %Y", "%b %d %Y"):
        try:
            return (
                datetime.strptime(f"{found['mon']} {found['d']} {found['y']}", fmt)
                .date()
                .isoformat()
            )
        except ValueError:
            continue
    return None


def _safe_url(href: str) -> str:
    absolute = urljoin(HASKELL_PAGE, href.strip())
    parts = urlsplit(absolute)
    if parts.query or parts.fragment or parts.username or parts.port:
        return ""
    return f"{parts.scheme}://{parts.netloc}{quote(parts.path, safe='/%()._-+,')}"


def parse_listing(html: bytes, limit: int) -> list[dict[str, Any]]:
    """Agenda PDFs on the Commissioners Court page, newest meeting first, policy-checked."""
    docs: dict[str, dict[str, Any]] = {}
    for href, label in more.anchors(html):
        url = _safe_url(href)
        if not file_url_ok(url) or _SKIP_LABEL.search(label):
            continue
        docs.setdefault(url, {"url": url, "label": label[:200], "meeting": _label_date(label)})
    ordered = sorted(docs.values(), key=lambda d: (d["meeting"] or "", d["url"]), reverse=True)
    return ordered[:limit]


def record_for(doc: dict[str, Any], listed_on: str) -> dict[str, Any]:
    name = doc["url"].rsplit("/", 1)[-1]
    lines = [
        "Haskell County Commissioners Court agenda document",
        f"Listed on the county page as: {doc['label'] or name}",
        f"Meeting date (per the listed label): {doc['meeting'] or 'unknown'}",
        "An agenda item is a topic for discussion or action, not an approval, an investment or a "
        "load.",
    ]
    return {
        "document_number": "TXCOUNTY-HASKELL-"
        + hashlib.sha256(doc["url"].encode()).hexdigest()[:16],
        "title": f"Haskell County Commissioners Court agenda: {doc['label'] or name}"[:250],
        "abstract": "\n".join(lines),
        "publication_date": None,
        "event_date": doc["meeting"],
        "event_date_label": "commissioners court meeting" if doc["meeting"] else None,
        "html_url": doc["url"],
        "extraction_location": "Commissioners Court page",
        "source_hash": hashlib.sha256(f"{doc['url']}|{doc['label']}".encode()).hexdigest(),
        "state_key": doc["url"],
        "doc_url": doc["url"],
        "doc_kind": "county_agenda",
        "listed_on": listed_on,
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
        raise SourceParseError("County agenda source is not the reviewed endpoint")
    query = source.get("query")
    if not valid_query(query):
        raise SourceParseError("County agenda configuration is invalid")
    assert isinstance(query, dict)
    listed_on = (today or datetime.now(UTC).date()).isoformat()
    own = client is None
    http = client or stage.new_client()
    try:
        fetcher = EarlyFetcher(http, pacer or shared.Pacer(), url_ok)
        html = more.fetch_page(
            fetcher, HASKELL_PAGE, query["max_response_bytes"], deadline, "County agenda"
        )
    finally:
        if own:
            http.close()
    docs = parse_listing(html, query["max_agendas"])
    return [record_for(doc, listed_on) for doc in docs][: query["max_records"]]


# --------------------------------------------------------------------------- extraction


def _exact(value: Decimal) -> int | str:
    if value == value.to_integral_value():
        return int(value)
    return format(value.normalize(), "f")


def _money(match: re.Match[str]) -> tuple[int | str, str]:
    number = Decimal(match["n"].replace(",", ""))
    unit = (match.groupdict().get("u") or "").casefold()
    if unit == "million":
        return _exact(number * 1_000_000), "calculated"
    if unit == "billion":
        return _exact(number * 1_000_000_000), "calculated"
    return _exact(number), "documented"


def _mw(match: re.Match[str]) -> tuple[int | str, str]:
    number = Decimal(match["n"].replace(",", ""))
    if match["u"].casefold().startswith(("gw", "giga")):
        return _exact(number * 1000), "calculated"
    return _exact(number), "documented"


def _candidates(name: str, text: str) -> list[tuple[Any, str, re.Match[str]]]:
    found: list[tuple[Any, str, re.Match[str]]] = []
    if name == "entity":
        found = [(more.norm(m["v"]), "documented", m) for m in _ENTITY.finditer(text)]
    elif name == "investment_usd":
        for pattern in (_MONEY_SCALED, _MONEY_PLAIN):
            for m in pattern.finditer(text):
                value, basis = _money(m)
                found.append((value, basis, m))
    elif name == "stated_mw":
        for m in _MW.finditer(text):
            value, basis = _mw(m)
            found.append((value, basis, m))
    elif name == "acres":
        found = [
            (_exact(Decimal(m["n"].replace(",", ""))), "documented", m)
            for m in _ACRES.finditer(text)
        ]
    elif name == "location":
        found = [(more.norm(m["v"]), "documented", m) for m in _LOCATION.finditer(text)]
    return sorted(found, key=lambda c: c[2].start())


def _scalar(name: str, text: str) -> tuple[Any, str, re.Match[str]] | None:
    """The stated value of a field in ``text`` as (value, basis, first match).

    Two different values for one field in the same agenda item are a conflict, and a conflict is
    unknown: no value is chosen (for example a dollar investment next to a road fund).
    """
    found = _candidates(name, text)
    if not found or len({str(c[0]) for c in found}) > 1:
        return None
    return found[0]


_FIELD_NAMES = ("entity", "investment_usd", "stated_mw", "acres", "location")


def _item_fields(item: str, page: int, page_norm: str) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for name in _FIELD_NAMES:
        found = _scalar(name, item)
        if found is None:
            continue
        value, basis, match = found
        quote_ = more.window(item, match.start(), match.end())
        again = _scalar(name, quote_)
        if again is None or again[0] != value:
            continue
        evidence = more.evidence(value, basis, page, quote_, page_norm)
        if evidence is not None:
            fields[name] = evidence
    return fields


def extract_items(pages: list[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for number, page in enumerate(pages, start=1):
        page_norm = more.norm(page)
        starts = list(_AGENDA_START.finditer(page_norm))
        bounds = [(m.start(), m["n"]) for m in starts]
        if not bounds:
            bounds = [(0, "")]
        for position, (begin, label) in enumerate(bounds):
            end = bounds[position + 1][0] if position + 1 < len(bounds) else len(page_norm)
            text = page_norm[begin:end].strip()
            abatement = _ABATEMENT.search(text)
            data_center = _DATA_CENTER.search(text)
            if abatement is None and data_center is None:
                continue
            quote_ = text[: more.MAX_QUOTE]
            item = more.evidence(
                {
                    "agenda_item": label or None,
                    "names_abatement": abatement is not None,
                    "names_data_center": data_center is not None,
                },
                "documented",
                number,
                quote_,
                page_norm,
            )
            if item is None:
                continue
            item["fields"] = _item_fields(text, number, page_norm)
            items.append(item)
            if len(items) >= MAX_ITEMS:
                return items
    return items


def extract_agenda(pages: list[str], scanned: list[int]) -> dict[str, Any]:
    items = extract_items(pages)
    lines: list[str] = []
    for item in items:
        flags = item["value"]
        head = f"Agenda item {flags['agenda_item'] or '?'} (page {item['page']}): "
        lines.append(head + item["quote"][:240])
        for name, field in item["fields"].items():
            lines.append(f'  {name}: {field["value"]} ("{field["quote"][:160]}")')
    return {
        "extractor": EXTRACT_VERSION,
        "pages": len(pages),
        "scanned_pages": scanned,
        "items": items,
        "summary_lines": lines
        or [
            "No tax-abatement or data-center agenda item found in the text layer (not a statement "
            "that none was discussed)."
        ],
        "abstain": None
        if items
        else {"reason": "no abatement or data-center agenda item", "note": "Abstention, not zero."},
    }


def _extract(
    body: bytes, item: stage.DocItem, prior: dict[str, Any] | None, budget: float, isolate: bool
) -> dict[str, Any]:
    pages, scanned = pdf_text.read_pdf_pages(body, budget, isolate)
    return extract_agenda(pages, scanned)


EXTRACTORS: dict[str, stage.Extractor] = {"county_agenda": _extract}


def item_for(record: dict[str, Any]) -> stage.DocItem | None:
    url = record.get("doc_url")
    if not file_url_ok(url) or record.get("doc_kind") != "county_agenda":
        return None
    if record.get("state_key") != url:
        return None
    return stage.DocItem(
        key=str(url),
        url=str(url),
        kind="county_agenda",
        max_bytes=MAX_PDF_BYTES,
        media_types=PDF,
        recheck_hours=RECHECK_HOURS,
        meta={"published_at": None},
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
