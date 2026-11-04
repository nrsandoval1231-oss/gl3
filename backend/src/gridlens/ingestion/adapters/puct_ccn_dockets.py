"""PUCT certificate (CCN) dockets for transmission lines and substations (early signal).

**Compliance finding (verified live 2026-11-04).** ``interchange.puc.texas.gov/robots.txt`` is a
404 (no crawl restrictions published), the search pages and Excel exports are plain server-rendered
HTML and OOXML with no challenge, and filing documents are public PDFs. The site footer links "Site
Policies"; this source makes a handful of requests per run, at most one per second, with a declared
generic user agent, and never retries around a refusal. If the site ever answers with a bot
challenge or a policy change, the typed failure stops the run and nothing is bypassed.

**Volume (counted live 2026-11-04).** Electric dockets whose case style names a transmission line
or a substation, with a filing in each month of 2026: 22 to 38 dockets per month (73 distinct from
January to October 2026), of which roughly 1 to 10 were first seen in a month. The default 60-day
window therefore yields well under 100 dockets.

Listing (``retrieve``) uses the Interchange case-style search plus its Excel export, cross-checked
exactly as ``puct_docket_index`` does, restricted by ``DateFiledFrom`` and ``DateFiledTo`` to
certificate-of-convenience-and-necessity styles that name a transmission line or substation. The
document stage reads, for a bounded number of dockets, the filings list and the first PDF of the
initial application and of the preliminary order. Case-style facts are kept even when no document
is read. Nothing links a docket to a customer, and nothing is called demand: a stated customer
request is documented text, with its verbatim quote, page and document hash.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from html import unescape
from typing import Any
from urllib.parse import quote, urlencode, urljoin

import httpx

from gridlens.ingestion.adapters import early_signal_link as link
from gridlens.ingestion.adapters import early_signal_stage as stage
from gridlens.ingestion.adapters import ercot_rpg_extract as rpg_extract
from gridlens.ingestion.adapters import puct_ccn_extract as ex
from gridlens.ingestion.adapters import tceq_application_documents as shared
from gridlens.ingestion.adapters.early_signal_http import HTML, PDF, EarlyFetcher
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.puct_docket_index import parse_export, parse_search
from gridlens.ingestion.adapters.tceq_application_documents import DocumentFailure

SOURCE_ID = "texas-puct-ccn-transmission-dockets"
RETRIEVAL_METHOD = "puct-ccn-dockets"
ENDPOINT = "https://interchange.puc.texas.gov/search/dockets/"
HOST_URL = "https://interchange.puc.texas.gov"
MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DESCRIPTIONS = ("transmission line", "substation")
MAX_LISTING_BYTES = 2_000_000
MAX_RECORDS = 100
MAX_WINDOW_DAYS = 90
MAX_PDF_BYTES = 15 * 1024 * 1024
RECHECK_HOURS = 24.0 * 7
STATE_VERSION = "puct-ccn-docket-v1"

_SEARCH = re.compile(
    r"https://interchange\.puc\.texas\.gov/search/dockets/\?UtilityType=E&ItemMatch=Equal"
    r"&DocumentType=ALL&Description=(?:transmission%20line|substation)"
    r"&DateFiledFrom=\d{4}-\d{2}-\d{2}&DateFiledTo=\d{4}-\d{2}-\d{2}&SortOrder=Ascending"
)
_EXPORT = re.compile(
    r"https://interchange\.puc\.texas\.gov/search/exportdockets/\?UtilityType=E&ItemMatch=Equal"
    r"&DocumentType=ALL&Description=(?:transmission%20line|substation)"
    r"&DateFiledFrom=\d{4}-\d{2}-\d{2}&DateFiledTo=\d{4}-\d{2}-\d{2}"
    r"&SortBy=ControlNumber&SortOrder=Ascending"
)
_FILINGS = re.compile(r"https://interchange\.puc\.texas\.gov/Search/Filings\?ControlNumber=\d{1,6}")
_DOC_PAGE = re.compile(
    r"https://interchange\.puc\.texas\.gov/search/documents/\?controlNumber=\d{1,6}"
    r"&itemNumber=\d{1,4}"
)
_DOC_FILE = re.compile(
    r"https://interchange\.puc\.texas\.gov/Documents/(?P<c>\d{1,6})_(?P<i>\d{1,4})_\d{1,9}\.PDF"
)


# --------------------------------------------------------------------------- URL policy


def url_ok(url: Any) -> bool:
    if not isinstance(url, str) or len(url) > 600:
        return False
    return any(
        pattern.fullmatch(url) is not None
        for pattern in (_SEARCH, _EXPORT, _FILINGS, _DOC_PAGE, _DOC_FILE)
    )


def search_url(description: str, start: date, end: date) -> str:
    return (
        ENDPOINT
        + "?"
        + urlencode(
            {
                "UtilityType": "E",
                "ItemMatch": "Equal",
                "DocumentType": "ALL",
                "Description": description,
                "DateFiledFrom": start.isoformat(),
                "DateFiledTo": end.isoformat(),
                "SortOrder": "Ascending",
            },
            quote_via=quote,
        )
    )


def export_url(description: str, start: date, end: date) -> str:
    return (
        HOST_URL
        + "/search/exportdockets/?"
        + urlencode(
            {
                "UtilityType": "E",
                "ItemMatch": "Equal",
                "DocumentType": "ALL",
                "Description": description,
                "DateFiledFrom": start.isoformat(),
                "DateFiledTo": end.isoformat(),
                "SortBy": "ControlNumber",
                "SortOrder": "Ascending",
            },
            quote_via=quote,
        )
    )


def filings_url(control: str) -> str:
    return f"{HOST_URL}/Search/Filings?ControlNumber={control}"


def doc_page_url(control: str, item: str) -> str:
    return f"{HOST_URL}/search/documents/?controlNumber={control}&itemNumber={item}"


# --------------------------------------------------------------------------- configuration


def valid_query(query: Any) -> bool:
    if not isinstance(query, dict):
        return False
    return (
        set(query)
        == {"max_response_bytes", "max_records", "window_days", "descriptions", "documents"}
        and query["max_response_bytes"] == MAX_LISTING_BYTES
        and type(query["max_records"]) is int
        and 1 <= query["max_records"] <= MAX_RECORDS
        and type(query["window_days"]) is int
        and 1 <= query["window_days"] <= MAX_WINDOW_DAYS
        and tuple(query["descriptions"] or ()) == DESCRIPTIONS
        and stage.valid_config(query["documents"], None)
    )


def config_from_source(source: dict[str, Any]) -> stage.StageConfig | None:
    return stage.config_from((source.get("query") or {}).get("documents"))


# --------------------------------------------------------------------------- records


def record_for(row: dict[str, str], *, listed_on: str) -> dict[str, Any]:
    control = row["control"]
    fields = ex.case_style_fields(row["description"])
    lines = [
        f"Control number: {control}",
        f"Case style: {row['description']}",
        f"Utility: {row['utility']}",
        f"Filings on the docket index: {row['filings']}",
        "Counties named in the case style: "
        + (", ".join(e["value"] for e in fields["counties"]) or "unknown"),
        "Voltage named in the case style: "
        + (", ".join(f"{e['value']} kV" for e in fields["voltage_kv"]) or "unknown"),
        "Customer, load MW and cost: read from filings only; unknown until then.",
    ]
    return {
        "document_number": f"PUCT-CCN-{control}",
        "title": f"PUCT {control} — {row['utility']}"[:250],
        "abstract": "\n".join(lines),
        "publication_date": None,
        "event_date": None,
        "html_url": filings_url(control),
        "extraction_location": "PUCT Interchange docket search and Excel export",
        "source_hash": hashlib.sha256(
            f"{control}|{row['filings']}|{row['utility']}|{row['description']}".encode()
        ).hexdigest(),
        "state_key": control,
        "doc_kind": "puct_docket",
        "listed_on": listed_on,
        "case_style_fields": fields,
        "filings": row["filings"],
        "utility": row["utility"],
    }


# --------------------------------------------------------------------------- retrieve (listing)


def _listing_error(failure: DocumentFailure) -> SourceParseError:
    error = SourceParseError(f"PUCT listing fetch failed: {failure.code}")
    if failure.rate_limited:
        error.acquisition_code = failure.code  # type: ignore[attr-defined]
        if failure.retry_after is not None:
            error.acquisition_retry_after_seconds = failure.retry_after  # type: ignore[attr-defined]
    return error


def retrieve(
    source: dict[str, Any],
    client: httpx.Client | None = None,
    *,
    deadline: float | None = None,
    pacer: Callable[[], None] | None = None,
    today: date | None = None,
) -> list[dict[str, Any]]:
    if source.get("id") != SOURCE_ID or source.get("endpoint") != ENDPOINT:
        raise SourceParseError("PUCT CCN source is not the reviewed endpoint")
    query = source.get("query")
    if not valid_query(query):
        raise SourceParseError("PUCT CCN configuration is invalid")
    assert isinstance(query, dict)
    end = today or datetime.now(UTC).date()
    start = end - timedelta(days=query["window_days"])
    own = client is None
    http = client or stage.new_client()
    try:
        fetcher = EarlyFetcher(http, pacer or shared.Pacer(), url_ok)

        def get(url: str, media: frozenset[str]) -> bytes:
            try:
                return fetcher.get(
                    url, max_bytes=query["max_response_bytes"], media_types=media
                ).body
            except DocumentFailure as failure:
                raise _listing_error(failure) from failure

        rows: dict[str, dict[str, str]] = {}
        for description in DESCRIPTIONS:
            page = get(search_url(description, start, end), HTML)
            workbook = get(export_url(description, start, end), frozenset({MEDIA_TYPE}))
            listed = parse_search(page)
            exported = parse_export(workbook)
            if listed != exported:
                raise SourceParseError("PUCT docket search and Excel export disagree")
            for row in exported:
                if ex.style_is_relevant(row["description"]):
                    rows.setdefault(row["control"], row)
        ordered = sorted(rows.values(), key=lambda r: int(r["control"]), reverse=True)
        return [record_for(r, listed_on=end.isoformat()) for r in ordered[: query["max_records"]]]
    finally:
        if own:
            http.close()


# --------------------------------------------------------------------------- filings and documents


def parse_items(body: bytes, control: str) -> list[dict[str, str]]:
    """Filing items (number, date, party, type, description) on the first filings page."""
    text = body.decode("utf-8", errors="replace")
    items: list[dict[str, str]] = []
    pattern = re.compile(
        rf'controlNumber={control}&amp;itemNumber=(\d{{1,4}})"[^>]*>\s*\1\s*</a>([\s\S]*?)</tr>',
        re.I,
    )
    for item, rest in pattern.findall(text):
        cells = [
            " ".join(unescape(re.sub(r"<[^>]+>", " ", cell)).split())
            for cell in re.findall(r"<td[^>]*>([\s\S]*?)</td>", rest, re.I)
        ]
        if len(cells) < 4:
            continue
        try:
            filed = datetime.strptime(cells[0], "%m/%d/%Y").date().isoformat()
        except ValueError:
            continue
        items.append(
            {
                "item": item,
                "filed": filed,
                "party": cells[1][:200],
                "type": cells[2][:12],
                "description": cells[3][:500],
            }
        )
    return items


def pick_items(items: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    """The initial application and the preliminary order, by their filing descriptions."""
    picked: dict[str, dict[str, str]] = {}
    for item in sorted(items, key=lambda i: int(i["item"])):
        description = item["description"].upper()
        if "application" not in picked and description.startswith(
            ("APPLICATION OF", "JOINT APPLICATION OF")
        ):
            picked["application"] = item
        elif "order" not in picked and re.search(
            r"PRELIMINARY ORDER|ORDER OF REFERRAL", description
        ):
            picked["order"] = item
    return picked


def first_pdf(body: bytes, control: str, item: str) -> str | None:
    text = body.decode("utf-8", errors="replace")
    for href in re.findall(r'href="([^"]{1,300})"', text):
        absolute = urljoin(HOST_URL + "/", unescape(href))
        found = _DOC_FILE.fullmatch(absolute)
        if found and found["c"] == control and found["i"] == item:
            return absolute
    return None


def _read_pdf(
    fetcher: EarlyFetcher, url: str, budget: float, isolate: bool
) -> tuple[list[str], str]:
    fetched = fetcher.get(url, max_bytes=MAX_PDF_BYTES, media_types=PDF)
    assert fetched.sha256 is not None
    pages, _scanned = rpg_extract.read_pdf_pages(fetched.body, budget, isolate)
    return pages, fetched.sha256


# --------------------------------------------------------------------------- document stage


def read_docket(
    fetcher: EarlyFetcher,
    record: dict[str, Any],
    prior: dict[str, Any] | None,
    budget: float,
    isolate: bool,
) -> dict[str, Any]:
    """Filings list, then the application and order PDFs not yet read. Raises DocumentFailure."""
    control = str(record["state_key"])
    page = fetcher.get(filings_url(control), max_bytes=2_000_000, media_types=HTML).body
    items = parse_items(page, control)
    picked = pick_items(items)
    previous = ((prior or {}).get("document") or {}).get("extraction") or {}
    read: list[dict[str, Any]] = list(previous.get("documents") or [])
    done = {d["role"] for d in read}
    previous_text: dict[str, Any] = previous.get("text_fields") or {}
    new_text: list[dict[str, Any]] = []
    for role in ("application", "order"):
        item = picked.get(role)
        if item is None or role in done:
            continue
        listing = fetcher.get(
            doc_page_url(control, item["item"]), max_bytes=500_000, media_types=HTML
        )
        url = first_pdf(listing.body, control, item["item"])
        if url is None:
            continue
        pages, sha = _read_pdf(fetcher, url, budget, isolate)
        new_text.append(ex.text_fields(pages))
        read.append(
            {
                "role": role,
                "item": item["item"],
                "filed": item["filed"],
                "url": url,
                "sha256": sha,
                "pages_read": len(pages),
            }
        )
    text_fields = ex.merge_fields(previous_text, *new_text) if (previous_text or new_text) else {}
    style = record["case_style_fields"]
    fields = ex.merge_fields(style, text_fields)
    first_filed = min((i["filed"] for i in items), default=None)
    digest = hashlib.sha256(
        "|".join(sorted(f"{d['role']}:{d['sha256']}" for d in read)).encode()
    ).hexdigest()
    return {
        "extractor": ex.VERSION,
        "fields": fields,
        "text_fields": text_fields,
        "documents": read,
        "filing_items_seen": len(items),
        "first_filing_date": first_filed,
        "combined_sha256": digest,
        "summary_lines": ex.summary_lines(control, fields),
        "fields_found": ex.count_fields(fields),
    }


def run_stage(
    records: list[dict[str, Any]],
    prior_states: dict[str, dict[str, Any]],
    *,
    client: httpx.Client | None,
    config: stage.StageConfig,
    index: dict[str, Any] | None = None,
    peers: list[dict[str, Any]] | None = None,
    deadline: float | None = None,
    pacer: Callable[[], None] | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> stage.EarlyStageReport:
    started = now()
    in_scope = {str(r["state_key"]) for r in records if r.get("doc_kind") == "puct_docket"}
    states = {k: v for k, v in prior_states.items() if k in in_scope}
    owns = client is None
    http = client or stage.new_client()
    try:
        run = stage.make_run(
            client=http,
            pacer=pacer or stage.default_pacer(),
            policy=url_ok,
            config=config,
            deadline=deadline,
            record_count=len(records),
            index=index,
            states=states,
            extractors={},
            now=started,
        )
        run.report.counts["in_scope"] = len(in_scope)
        if stage.resting(index, started):
            run.report.bump("skipped_retry_after")
        else:
            _read_dockets(run, records)
        report = stage.finish(run, index)
    finally:
        if owns:
            http.close()
    for record in records:
        state = run.states.get(str(record.get("state_key")))
        if state is None:
            continue
        stage.apply_state(record, state)
        _apply_style_only(record, state)
    records.extend(link_records(records, run.states, peers or [], report))
    return report


def _needs_read(run: stage.Run, record: dict[str, Any]) -> bool:
    key = str(record["state_key"])
    state = run.states.get(key)
    entry = run.urls.get(key) or {}
    if state is None:
        if entry.get("status") == "failed":
            at = stage.parse_time(entry.get("at"))
            return at is None or run.now - at >= timedelta(days=stage.RECHECK_FAILED_DAYS)
        return True
    extraction = state["document"]["extraction"]
    roles = {d["role"] for d in extraction.get("documents") or []}
    if roles >= {"application", "order"}:
        return False
    at = stage.parse_time(entry.get("at"))
    return (str(record.get("filings")) != str(state.get("filings_listed"))) and (
        at is None or run.now - at >= timedelta(hours=RECHECK_HOURS)
    )


def _read_dockets(run: stage.Run, records: list[dict[str, Any]]) -> None:
    report = run.report
    fetcher = run.fetcher
    reads = 0
    todo = [r for r in records if r.get("doc_kind") == "puct_docket" and _needs_read(run, r)]
    todo.sort(key=lambda r: (str(r["state_key"]) in run.states, -int(r["state_key"])))
    for record in todo:
        key = str(record["state_key"])
        entry = run.urls.get(key) or {}
        retry = entry.get("retry") or {}
        if retry.get("attempts", 0) >= stage.RETRY_ATTEMPTS:
            rested = stage.parse_time(retry.get("at"))
            if rested is not None and run.now < rested + timedelta(days=stage.RETRY_BACKOFF_DAYS):
                report.bump("backed_off")
                continue
        if reads >= run.config.max_downloads:
            report.bump("deferred_download_budget")
            break
        if run.left() < shared.HTTP_READ_TIMEOUT_SECONDS + 10:
            report.bump("deferred_deadline")
            break
        budget = min(
            run.config.extract_seconds,
            run.left() - shared.STAGE_MARGIN_SECONDS - shared.CHILD_GRACE_SECONDS,
        )
        if budget < shared.MIN_EXTRACT_SECONDS:
            report.bump("deferred_deadline")
            break
        reads += 1
        report.bump("checked")
        item = stage.DocItem(
            key=key,
            url=filings_url(key),
            kind="puct_docket",
            max_bytes=MAX_PDF_BYTES,
            media_types=PDF,
            recheck_hours=RECHECK_HOURS,
            meta={"published_at": record.get("publication_date")},
        )
        prior = run.states.get(key)
        try:
            extraction = read_docket(fetcher, record, prior, budget, run.config.isolate)
        except DocumentFailure as failure:
            failure.budget_limited = budget < run.config.extract_seconds
            try:
                stage._on_failure(run, item, entry, failure, None)
            except stage.StageAbort:
                break
            continue
        state = stage.build_state(
            prior,
            item=item,
            sha256=extraction["combined_sha256"],
            size=sum(d.get("pages_read", 0) for d in extraction["documents"]),
            validators={},
            extraction=extraction,
            now=run.now,
        )
        state["version"] = STATE_VERSION
        state["filings_listed"] = str(record.get("filings"))
        state["published_at"] = extraction.get("first_filing_date")
        run.states[key] = state
        stage._write(run, key, status="document", sha256=extraction["combined_sha256"])
        report.bump("updated" if prior else "new")
        if extraction.get("fields_found", 1) == 0:
            report.reject(stage.ident(key), "zero_fields_extracted")


def _apply_style_only(record: dict[str, Any], state: dict[str, Any]) -> None:
    published = state.get("published_at")
    if published:
        record["publication_date"] = published


def apply_prior_states(records: list[dict[str, Any]], prior: dict[str, dict[str, Any]]) -> None:
    for record in records:
        state = prior.get(str(record.get("state_key")))
        if state is not None:
            stage.apply_state(record, state)
            _apply_style_only(record, state)


# --------------------------------------------------------------------------- links


def docket_summaries(
    records: list[dict[str, Any]], states: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for record in records:
        key = str(record.get("state_key"))
        if record.get("doc_kind") != "puct_docket":
            continue
        state = states.get(key)
        fields = state["document"]["extraction"]["fields"] if state else record["case_style_fields"]
        sha = state["document"]["sha256"] if state else None
        out.append(
            {
                "control": key,
                "fields": fields,
                "document_sha256": sha,
                "url": filings_url(key),
                "utility": record.get("utility"),
            }
        )
    return out


def link_records(
    records: list[dict[str, Any]],
    states: dict[str, dict[str, Any]],
    peers: list[dict[str, Any]],
    report: stage.EarlyStageReport,
) -> list[dict[str, Any]]:
    """One record per deterministic docket-to-project link; unknown links are only counted."""
    out: list[dict[str, Any]] = []
    for docket in docket_summaries(records, states):
        decision = link.link_docket(docket, peers)
        report.bump(f"link_{decision['status']}")
        if decision["status"] != "linked":
            if decision["reason"] == "ambiguous_candidates":
                report.bump("link_ambiguous")
            continue
        out.append(link.link_record(docket, decision))
    return out
