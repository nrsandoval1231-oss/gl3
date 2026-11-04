"""Oklahoma Corporation Commission data-center land-purchase notices (HB 2992, 17 O.S. 906).

**Discovery (verified live 2026-11-04; see docs/engineering/early-signal-sources-more-20261103.md).**
The notices ARE published. The OCC page
``https://oklahoma.gov/occ/divisions/public-utility/energy/electric-utility/data-center-customer-ratepayer-protection-act.html``
has a "Notice of Intent Submissions" list of PDFs under
``/content/dam/ok/en/occ/documents/pu/data-center-act/notice-of-intent-submissions/``. Each link text
names the company, (sometimes a project) the county and a date. The PDF is the OCC "Oklahoma Data
Center Attestation" form: page 1 states the large-load customer company name, the land purchase
date, the county and the planned utility provider; later pages are the signature page and
attachments (plat, notices to adjacent landowners). ``oklahoma.gov/robots.txt`` allows everything.

The listing facts (link text) are evidence on their own. The document stage reads only the form's
label/value lines on the first two pages. It never reads or stores the attestant's name, adjacent
landowners or any attachment text. Scanned forms (no text layer) are abstentions. The notice states
no MW. The source ships off.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urljoin

import httpx

from gridlens.ingestion.adapters import early_signal_more as more
from gridlens.ingestion.adapters import early_signal_stage as stage
from gridlens.ingestion.adapters import ercot_rpg_extract as pdf_text
from gridlens.ingestion.adapters import tceq_application_documents as shared
from gridlens.ingestion.adapters.early_signal_http import PDF, EarlyFetcher
from gridlens.ingestion.adapters.federal_register import SourceParseError

SOURCE_ID = "oklahoma-occ-data-center-notices"
RETRIEVAL_METHOD = "ok-occ-dc-notices"
ENDPOINT = (
    "https://oklahoma.gov/occ/divisions/public-utility/energy/electric-utility/"
    "data-center-customer-ratepayer-protection-act.html"
)
FILE_BASE = (
    "https://oklahoma.gov/content/dam/ok/en/occ/documents/pu/data-center-act/"
    "notice-of-intent-submissions/"
)
MAX_LISTING_BYTES = 3_000_000
MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_RECORDS = 200
RECHECK_HOURS = 24.0 * 14
EXTRACT_VERSION = "ok-occ-notice-form-v1"
FORM_PAGES = 2
WITHHOLD_WITHOUT_DOCUMENTS = False

_FILE = re.compile(re.escape(FILE_BASE) + r"[A-Za-z0-9][A-Za-z0-9._-]{0,150}\.pdf")
_HEADING = ">Notice of Intent Submissions</h2>"
_SEPARATOR = re.compile(r"\s+[-–—][-–—\s]*")
_DATE_TEXT = re.compile(r"^(?P<mon>[A-Z][a-z]+) (?P<d>\d{1,2}), (?P<y>\d{4})$")
_COUNTY_TEXT = re.compile(r"^(?P<c>[A-Z][A-Za-z .'-]{1,40}?) County$")


def file_url_ok(url: Any) -> bool:
    return isinstance(url, str) and len(url) <= 400 and _FILE.fullmatch(url) is not None


def url_ok(url: Any) -> bool:
    return url == ENDPOINT or file_url_ok(url)


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


# --------------------------------------------------------------------------- listing parse


def _date_iso(text: str) -> str | None:
    found = _DATE_TEXT.fullmatch(text)
    if found is None:
        return None
    try:
        return datetime.strptime(f"{found['mon']} {found['d']} {found['y']}", "%B %d %Y").date().isoformat()
    except ValueError:
        return None


def parse_label(label: str) -> dict[str, Any]:
    """Company, project, county and date from a link text; anything unmatched stays absent."""
    parts = [p.strip() for p in _SEPARATOR.split(label) if p.strip()]
    result: dict[str, Any] = {}
    if len(parts) >= 3 and (when := _date_iso(parts[-1])) is not None:
        county = _COUNTY_TEXT.fullmatch(parts[-2])
        if county is not None:
            result = {"company": parts[0][:160], "county": county["c"], "date": when}
            if len(parts) >= 4:
                result["project"] = " ".join(parts[1:-2])[:120]
    return result


def parse_listing(html: bytes) -> list[dict[str, Any]]:
    text = html.decode("utf-8", errors="replace")
    start = text.find(_HEADING)
    if start < 0:
        raise SourceParseError("OCC notice page has no Notice of Intent Submissions list")
    region_start = text.find("<ul", start)
    region_end = text.find("</ul>", region_start) if region_start >= 0 else -1
    if region_start < 0 or region_end < 0:
        raise SourceParseError("OCC notice page has no Notice of Intent Submissions list")
    docs: dict[str, dict[str, Any]] = {}
    for href, label in more.anchors(text[region_start:region_end].encode("utf-8")):
        url = urljoin(ENDPOINT, href)
        if file_url_ok(url):
            docs.setdefault(url, {"url": url, "label": label[:250], "parsed": parse_label(label)})
    return list(docs.values())


def record_for(doc: dict[str, Any], listed_on: str) -> dict[str, Any]:
    parsed = doc["parsed"]
    name = doc["url"].rsplit("/", 1)[-1]
    lines = [
        "Oklahoma Corporation Commission data-center notice of intent submission "
        "(Data Center Customer Ratepayer Protection Act of 2026, 17 O.S. 906).",
        f"Listed on the OCC page as: {doc['label']}",
    ]
    if parsed:
        lines.append(f"Company (per link text): {parsed['company']}")
        if parsed.get("project"):
            lines.append(f"Project (per link text): {parsed['project']}")
        lines.append(f"County (per link text): {parsed['county']}")
        lines.append(f"Date in link text: {parsed['date']}")
    else:
        lines.append("The link text did not match the expected shape; fields are unknown.")
    lines.append(f"Document: {name}")
    lines.append(
        "A notice states a land purchase, not a load: no MW is stated. Adjacent landowners and "
        "attachments are not read or stored."
    )
    return {
        "document_number": "OKOCC-" + hashlib.sha256(doc["url"].encode()).hexdigest()[:16],
        "title": f"OCC data-center notice: {doc['label']}"[:250],
        "abstract": "\n".join(lines),
        "publication_date": parsed.get("date"),
        "event_date": None,
        "html_url": doc["url"],
        "extraction_location": "OCC Notice of Intent Submissions list",
        "source_hash": hashlib.sha256(f"{doc['url']}|{doc['label']}".encode()).hexdigest(),
        "state_key": doc["url"],
        "doc_url": doc["url"],
        "doc_kind": "occ_notice",
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
        raise SourceParseError("OCC notice source is not the reviewed endpoint")
    query = source.get("query")
    if not valid_query(query):
        raise SourceParseError("OCC notice configuration is invalid")
    assert isinstance(query, dict)
    listed_on = (today or datetime.now(UTC).date()).isoformat()
    own = client is None
    http = client or stage.new_client()
    try:
        fetcher = EarlyFetcher(http, pacer or shared.Pacer(), url_ok)
        html = more.fetch_page(fetcher, ENDPOINT, query["max_response_bytes"], deadline, "OCC")
    finally:
        if own:
            http.close()
    return [record_for(doc, listed_on) for doc in parse_listing(html)][: query["max_records"]]


# --------------------------------------------------------------------------- form extraction

_FIELDS: dict[str, re.Pattern[str]] = {
    "company": re.compile(
        r"Large Load Customer Company Name:\s*(?P<v>[^:]{2,160}?)\s+Land Purchase Date:"
    ),
    "land_purchase_date": re.compile(
        r"Land Purchase Date:\s*(?P<v>\d{1,2}/\d{1,2}/\d{4})(?!\d)"
    ),
    "county": re.compile(
        r"County\(ies\):\s*(?P<v>[A-Z][A-Za-z .,'-]{1,80}?)\s*_*\s+Planned Utility Provider"
    ),
    "planned_utility": re.compile(
        r"Planned Utility Provider\(s\):\s*(?P<v>[^:]{2,200}?)\s+Data Center Customer Ratepayer"
    ),
}


def _value(name: str, found: re.Match[str]) -> str | None:
    raw = found["v"].strip(" _,")
    if name == "land_purchase_date":
        month, day, year = raw.split("/")
        try:
            return date(int(year), int(month), int(day)).isoformat()
        except ValueError:
            return None
    return raw or None


def extract_form(pages: list[str], scanned: list[int]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for number, page in enumerate(pages[:FORM_PAGES], start=1):
        page_norm = more.norm(page)
        for name, pattern in _FIELDS.items():
            if name in fields:
                continue
            found = pattern.search(page_norm)
            if found is None:
                continue
            value = _value(name, found)
            quote = found.group(0)[: more.MAX_QUOTE]
            again = pattern.search(quote)
            if value is None or again is None or _value(name, again) != value:
                continue
            item = more.evidence(value, "documented", number, quote, page_norm)
            if item is not None:
                fields[name] = item
    lines: list[str] = []
    labels = {
        "company": "Company (form)",
        "land_purchase_date": "Land purchase date (form)",
        "county": "County (form)",
        "planned_utility": "Planned utility provider (form)",
    }
    for name, label in labels.items():
        if name in fields:
            lines.append(f"{label}: {fields[name]['value']} [page {fields[name]['page']}]")
    return {
        "extractor": EXTRACT_VERSION,
        "pages": len(pages),
        "scanned_pages": scanned,
        "fields": fields,
        "summary_lines": lines,
        "fields_found": len(fields),
        "abstain": None
        if fields
        else {"reason": "no attestation form fields", "note": "Abstention, not zero."},
    }


def _extract(
    body: bytes, item: stage.DocItem, prior: dict[str, Any] | None, budget: float, isolate: bool
) -> dict[str, Any]:
    pages, scanned = pdf_text.read_pdf_pages(body, budget, isolate)
    return extract_form(pages, scanned)


EXTRACTORS: dict[str, stage.Extractor] = {"occ_notice": _extract}


def item_for(record: dict[str, Any]) -> stage.DocItem | None:
    url = record.get("doc_url")
    if not file_url_ok(url) or record.get("doc_kind") != "occ_notice":
        return None
    if record.get("state_key") != url:
        return None
    return stage.DocItem(
        key=str(url),
        url=str(url),
        kind="occ_notice",
        max_bytes=MAX_PDF_BYTES,
        media_types=PDF,
        recheck_hours=RECHECK_HOURS,
        meta={"published_at": record.get("publication_date")},
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
