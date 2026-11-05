"""SEC EDGAR: explicit, quoted site MW statements from an owner-listed set of registrants.

Live check 2026-11-04 (generic project user agent, one request per second):
``https://data.sec.gov/submissions/CIK0001167419.json`` answered 200 (163 KB, filing index with
accession numbers and primary documents); the primary 10-K at ``www.sec.gov/Archives/edgar/data/
.../riot-20251231x10k.htm`` answered 200 (3.9 MB); the undocumented full-text search host
``efts.sec.gov`` answered **403** and is not used.

SEC fair-access policy asks automated clients to declare who they are with a contact in the
User-Agent. The project's generic agent has none, and this repository hardcodes no personal
address. The reader therefore **refuses to run until the owner sets** ``SEC_EDGAR_CONTACT``
(setting ``sec_edgar_contact``); the contact is appended to the generic agent. Rate is at most one
request per second (SEC allows ten).

Extraction is deliberately narrow. A statement is a single sentence of the filing's own text that
contains a megawatt or gigawatt figure *and* names a site ("... Facility", "... Campus", "... Data
Center", ...). The verbatim sentence, its filing, accession number and character span in the
normalised text are kept, and the span is re-checked against the text. Anything else (a figure
without a named site, a total across sites, a table) yields nothing: unknown, never zero. The
sentence is not classified: whether a figure is developed capacity, interconnection, IT load or a
target is left to the quote.
"""

from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from typing import Any

import httpx

from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.sector_common import (
    USER_AGENT,
    Pacer,
    candidate_record,
    clean,
    fetch,
    iso_date,
    new_client,
    require_source,
)

SOURCE_ID = "sec-edgar-site-mw"
ENDPOINT = "https://data.sec.gov/submissions/"
HOSTS = frozenset({"data.sec.gov", "www.sec.gov"})
FORMS = frozenset({"10-K", "10-Q"})
MAX_QUOTE = 600
_CIK = re.compile(r"^[0-9]{10}$")
_ACCESSION = re.compile(r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
_PRIMARY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.htm$")
_BLOCK = {
    "p",
    "div",
    "br",
    "tr",
    "td",
    "th",
    "li",
    "ul",
    "ol",
    "table",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "section",
    "article",
    "body",
}
_SKIP = {"script", "style", "head", "ix:header", "title"}
_FIGURE = re.compile(
    r"(?<![\w.,])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s*(MW|GW|megawatts?|gigawatts?)\b"
    r"(?![-\s]?h(?:ours?)?\b)"  # megawatt-hours and GWh are energy, not a power rating
)
_SENTENCE_OK = re.compile(r"[.!?][\"”’)]*$")
# Words that make a "... Facility" a financing instrument, not a site.
_FINANCING = {
    "Credit",
    "Loan",
    "Loans",
    "Revolving",
    "Term",
    "Financing",
    "Lending",
    "Senior",
    "Note",
    "Notes",
    "Debt",
    "Bridge",
    "Warehouse",
    "Lease",
    "Equipment",
    "Receivables",
    "Delayed",
    "Draw",
    "Secured",
    "Convertible",
    "Purchase",
}
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z“\"(])")
_SITE = re.compile(
    r"\b((?:[A-Z][A-Za-z0-9&'’-]*\s+){1,3}?)(Facility|Campus|Data Center|Site|Project|Plant)\b"
)
_LEADING_STOP = {
    "The",
    "Our",
    "This",
    "That",
    "Each",
    "Its",
    "A",
    "An",
    "Of",
    "At",
    "In",
    "For",
    "These",
    "Those",
    "Both",
    "Such",
    "Their",
    "Any",
    "All",
    "Another",
    "With",
}


def valid_query(source: dict[str, Any]) -> bool:
    query = source.get("query")
    return (
        isinstance(query, dict)
        and source.get("id") == SOURCE_ID
        and source.get("endpoint") == ENDPOINT
        and source.get("cadence_hours") == 24
        and source.get("family") == "company-filings"
        and set(query)
        == {
            "ciks",
            "forms",
            "max_filings_per_cik",
            "max_submission_bytes",
            "max_document_bytes",
            "max_statements",
        }
        and isinstance(query["ciks"], list)
        and len(query["ciks"]) <= 10
        and all(isinstance(c, str) and _CIK.fullmatch(c) for c in query["ciks"])
        and len(set(query["ciks"])) == len(query["ciks"])
        and isinstance(query["forms"], list)
        and 1 <= len(query["forms"]) <= 2
        and all(f in FORMS for f in query["forms"])
        and type(query["max_filings_per_cik"]) is int
        and 1 <= query["max_filings_per_cik"] <= 2
        and query["max_submission_bytes"] == 2_000_000
        and type(query["max_document_bytes"]) is int
        and 1_000_000 <= query["max_document_bytes"] <= 12_000_000
        and type(query["max_statements"]) is int
        and 1 <= query["max_statements"] <= 200
    )


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0
        self._cell = 0  # table cells are not read: a figure in a table is not a sentence

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP:
            self._skip += 1
        elif tag in _BLOCK:
            self.parts.append(" ")
        if tag in {"td", "th"}:
            self._cell += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP and self._skip:
            self._skip -= 1
        elif tag in _BLOCK:
            self.parts.append(" ")
        if tag in {"td", "th"} and self._cell:
            self._cell -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip and not self._cell:
            self.parts.append(data)


def filing_text(body: bytes) -> str:
    """Visible text of one filing, whitespace-normalised; hidden iXBRL headers are dropped."""
    parser = _Text()
    parser.feed(body.decode("utf-8", errors="replace"))
    parser.close()
    return " ".join("".join(parser.parts).replace("\xa0", " ").split())


def _site_names(sentence: str) -> set[str]:
    """Distinct site names in the sentence; financing "facilities" are not sites."""
    names: set[str] = set()
    for found in _SITE.finditer(sentence):
        words = found.group(1).split()
        while words and words[0] in _LEADING_STOP:
            words.pop(0)
        if words and not any(word in _FINANCING for word in words):
            names.add(" ".join([*words, found.group(2)]))
    return names


def extract_statements(text: str, *, limit: int) -> list[dict[str, Any]]:
    """Single sentences that state a MW/GW figure and name a site, with verified spans."""
    out: list[dict[str, Any]] = []
    start = 0
    bounds = [m.end() for m in _SENTENCE_END.finditer(text)]
    for end_pos in [*bounds, len(text)]:
        sentence = text[start:end_pos].strip()
        begin = start + (len(text[start:end_pos]) - len(text[start:end_pos].lstrip()))
        start = end_pos
        if not sentence or len(sentence) > MAX_QUOTE:
            continue
        figures = [
            {
                "stated": found.group(0),
                "value": float(found.group(1).replace(",", "") + (found.group(2) or "")),
                "unit": "GW" if found.group(3).lower().startswith("g") else "MW",
            }
            for found in _FIGURE.finditer(sentence)
        ]
        names = _site_names(sentence)
        # One sentence, one site: a sentence naming two sites cannot say which figure is whose.
        if not figures or len(names) != 1 or not _SENTENCE_OK.search(sentence):
            continue
        site = next(iter(names))
        stop = begin + len(sentence)
        if text[begin:stop] != sentence:
            continue  # never keep a quote that is not exactly the text at its span
        out.append(
            {"quote": sentence, "start": begin, "end": stop, "site": site, "figures": figures}
        )
        if len(out) >= limit:
            break
    return out


def _recent_filings(
    submission: dict[str, Any], forms: list[str], limit: int
) -> list[dict[str, str]]:
    recent = submission.get("filings", {}).get("recent") if isinstance(submission, dict) else None
    if not isinstance(recent, dict):
        raise SourceParseError("SEC submissions lack a recent filing list")
    columns = ("accessionNumber", "filingDate", "reportDate", "form", "primaryDocument")
    if not all(isinstance(recent.get(name), list) for name in columns):
        raise SourceParseError("SEC submissions lack reviewed filing columns")
    found: list[dict[str, str]] = []
    for i, form in enumerate(recent["form"]):
        if form not in forms:
            continue
        row = {name: recent[name][i] if i < len(recent[name]) else "" for name in columns}
        if (
            isinstance(row["accessionNumber"], str)
            and _ACCESSION.fullmatch(row["accessionNumber"])
            and isinstance(row["primaryDocument"], str)
            and _PRIMARY.fullmatch(row["primaryDocument"])
            and iso_date(row["filingDate"])
        ):
            found.append({k: str(v) for k, v in row.items()})
        if len(found) >= limit:
            break
    return found


def build_record(
    statement: dict[str, Any], *, company: str | None, cik: str, filing: dict[str, str], url: str
) -> dict[str, Any]:
    accession = filing["accessionNumber"]
    start = statement["start"]
    digest = hashlib.sha256(statement["quote"].encode()).hexdigest()[:12]
    row_id = f"SEC-{cik}-{accession}-{digest}"
    lines = [
        f"{company or cik} {filing['form']} filed {filing['filingDate']} (accession {accession})",
        f"Site named in the sentence: {statement['site']}",
        f"Figures stated: {'; '.join(f['stated'] for f in statement['figures'])}",
        f"Quote (characters {start}-{statement['end']} of the normalised filing text):",
        f'"{statement["quote"]}"',
        "The sentence is kept verbatim and is not classified as capacity, load or target.",
    ]
    return candidate_record(
        source_id=SOURCE_ID,
        row_id=row_id,
        title=f"{company or cik} {filing['form']} — {statement['site']}: "
        + ", ".join(f["stated"] for f in statement["figures"]),
        abstract_lines=lines,
        url=url,
        extraction_location=f"{filing['form']} {accession}, characters {start}-{statement['end']}",
        semantic={"cik": cik, "accession": accession, "statement": statement},
        publication_date=iso_date(filing["filingDate"]),
        event_date=iso_date(filing.get("reportDate")),
        event_date_label="SEC report period end",
        permit={
            "applicant": company,
            "facility": statement["site"],
            "status": None,
            "location": None,
            "state": None,
            "permit_type": f"SEC {filing['form']} site statement",
            "quote": statement["quote"],
            "quote_span": [start, statement["end"]],
            "stated_figures": statement["figures"],
            "accession_number": accession,
            "source_fields": {
                "facility": "named in the quoted sentence",
                "event_date": "reportDate",
                "publication_date": "filingDate",
            },
        },
    )


def retrieve(
    source: dict[str, Any],
    client: httpx.Client | None = None,
    *,
    contact: Any = None,
    pacer: Pacer | None = None,
    deadline: float | None = None,
) -> list[dict[str, Any]]:
    require_source(source, SOURCE_ID, ENDPOINT)
    if not valid_query(source):
        raise SourceParseError("SEC query bounds are invalid")
    known = source.get("known_accessions", [])
    if (
        not isinstance(known, list)
        or len(known) > 5000
        or not all(isinstance(a, str) and _ACCESSION.fullmatch(a) for a in known)
    ):
        raise SourceParseError("SEC known accession list is invalid")
    if contact is None:
        from gridlens.settings import get_settings

        contact = get_settings().sec_edgar_contact
    if hasattr(contact, "get_secret_value"):
        contact = contact.get_secret_value()
    contact = (contact or "").strip()
    if not contact or len(contact) > 200 or not contact.isascii() or not contact.isprintable():
        raise SourceParseError("SEC_EDGAR_CONTACT is not configured (SEC fair access)")
    headers = {"User-Agent": f"{USER_AGENT} ({contact})"}
    query = source["query"]
    http = client or new_client()
    pace = pacer or Pacer(deadline=deadline)
    records: list[dict[str, Any]] = []
    try:
        for cik in query["ciks"]:
            _, body = fetch(
                http,
                f"{ENDPOINT}CIK{cik}.json",
                hosts=HOSTS,
                max_bytes=query["max_submission_bytes"],
                media_types={"application/json"},
                pacer=pace,
                headers=headers,
            )
            try:
                submission = json.loads(body)
            except ValueError as exc:
                raise SourceParseError("SEC submissions are not JSON") from exc
            company = clean(submission.get("name"), 120) if isinstance(submission, dict) else None
            if isinstance(submission, dict) and str(submission.get("cik", "")).zfill(10) != cik:
                raise SourceParseError("SEC submissions answer for a different CIK")
            for filing in _recent_filings(submission, query["forms"], query["max_filings_per_cik"]):
                accession = filing["accessionNumber"]
                if accession in known:
                    continue  # an accession is immutable: already ingested, so not fetched again
                url = (
                    f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                    f"{accession.replace('-', '')}/{filing['primaryDocument']}"
                )
                _, doc = fetch(
                    http,
                    url,
                    hosts=HOSTS,
                    max_bytes=query["max_document_bytes"],
                    media_types={"text/html", "application/xhtml+xml"},
                    pacer=pace,
                    headers=headers,
                )
                text = filing_text(doc)
                for statement in extract_statements(text, limit=query["max_statements"]):
                    records.append(
                        build_record(statement, company=company, cik=cik, filing=filing, url=url)
                    )
        return sorted(records, key=lambda r: r["document_number"])
    finally:
        if client is None:
            http.close()
