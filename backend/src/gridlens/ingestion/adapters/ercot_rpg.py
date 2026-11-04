"""ERCOT Regional Planning Group (RPG) projects, TPIT and System Planning aggregates.

**Discovery (verified live 2026-11-04; see docs/engineering/early-signal-sources-20261103.md).**
ERCOT does publish listing pages, so files are *not* discovered by guessing date paths:

* ``https://www.ercot.com/committees/other/rpg`` lists the current year's RPG meetings, each a
  ``/calendar/MMDDYYYY-RPG-Meeting...`` page; earlier years are ``/committees/other/rpg/YYYY``.
* A meeting page lists its "Key Documents": PDF links under ``/files/docs/YYYY/MM/DD/`` with a
  listed date ("Jul 17, 2026"), type and size. Project PDFs carry IDs such as ``25RPG020`` inside.
* ``https://www.ercot.com/gridinfo/planning`` links the Transmission Project and Information
  Tracking (TPIT) workbook at one stable URL whose content (and listed date) change monthly.

Everything here is read-only public documents, one request per second at most, a declared generic
user agent, no redirects, exact host and path policy. The source ships off. No customer name, load
type or requested energization date is given by RPG project totals; none is inferred.
"""

from __future__ import annotations

import copy
import hashlib
import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from html import unescape
from typing import Any
from urllib.parse import urljoin

import httpx

from gridlens.ingestion.adapters import early_signal_stage as stage
from gridlens.ingestion.adapters import ercot_rpg_extract as extract
from gridlens.ingestion.adapters import ercot_tpit as tpit
from gridlens.ingestion.adapters import tceq_application_documents as shared
from gridlens.ingestion.adapters.early_signal_http import (
    HTML,
    PDF,
    XLSX,
    EarlyFetcher,
)
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.tceq_application_documents import DocumentFailure

SOURCE_ID = "texas-ercot-rpg-projects"
RETRIEVAL_METHOD = "ercot-rpg-projects"
HUB_URL = "https://www.ercot.com/committees/other/rpg"
PLANNING_URL = "https://www.ercot.com/gridinfo/planning"
MAX_LISTING_BYTES = 3_000_000
MAX_PDF_BYTES = 40 * 1024 * 1024
MAX_XLSX_BYTES = tpit.MAX_BYTES
MAX_MEETINGS = 6
MAX_RECORDS = 200
PDF_RECHECK_HOURS = 24.0 * 14
TPIT_RECHECK_HOURS = 20.0
TPIT_TITLE = "Transmission Project and Information Tracking"

_MEETING = re.compile(
    r"https://www\.ercot\.com/calendar/(?P<m>\d{2})(?P<d>\d{2})(?P<y>20\d{2})"
    r"-RPG-Meeting[A-Za-z0-9_.%-]{0,60}"
)
_FILE = re.compile(
    r"https://www\.ercot\.com/files/docs/(?P<y>20\d{2})/(?P<m>\d{2})/(?P<d>\d{2})/"
    r"(?P<name>[A-Za-z0-9][A-Za-z0-9._()%+,-]{0,200})\.(?P<ext>pdf|xlsx)"
)
_ANCHOR = re.compile(
    r'<a\b[^>]*?href="(?P<href>[^"]{1,600})"[^>]*>(?P<text>.*?)</a>'
    r'(?P<tail>[\s\S]{0,700}?)<span class="">(?P<date>[A-Z][a-z]{2} \d{1,2}, \d{4}) - '
    r"(?P<ext>\w{2,5}) - (?P<size>[\d.]+ [KM]B)</span>",
    re.S,
)
_NOT_PROJECT_DOC = re.compile(r"agenda|minutes|charter|contact|notes|calendar|roster", re.I)


# --------------------------------------------------------------------------- URL policy


def meeting_url_ok(url: Any) -> bool:
    return isinstance(url, str) and _MEETING.fullmatch(url) is not None


def file_url_ok(url: Any) -> bool:
    if not isinstance(url, str) or len(url) > 600:
        return False
    found = _FILE.fullmatch(url)
    if found is None:
        return False
    try:
        date(int(found["y"]), int(found["m"]), int(found["d"]))
    except ValueError:
        return False
    return True


def pdf_url_ok(url: Any) -> bool:
    return file_url_ok(url) and str(url).lower().endswith(".pdf")


def url_ok(url: Any) -> bool:
    """Every page and file this source may request, by exact shape."""
    return url in {HUB_URL, PLANNING_URL} or meeting_url_ok(url) or file_url_ok(url)


def year_url_ok(url: Any) -> bool:
    return isinstance(url, str) and re.fullmatch(
        r"https://www\.ercot\.com/committees/other/rpg/20\d{2}", url
    ) is not None


# --------------------------------------------------------------------------- configuration


def valid_query(query: Any) -> bool:
    if not isinstance(query, dict):
        return False
    return (
        set(query) == {"max_response_bytes", "max_records", "max_meetings", "documents"}
        and query["max_response_bytes"] == MAX_LISTING_BYTES
        and type(query["max_records"]) is int
        and 1 <= query["max_records"] <= MAX_RECORDS
        and type(query["max_meetings"]) is int
        and 1 <= query["max_meetings"] <= MAX_MEETINGS
        and stage.valid_config(query["documents"], pdf_url_ok)
    )


def config_from_source(source: dict[str, Any]) -> stage.StageConfig | None:
    return stage.config_from((source.get("query") or {}).get("documents"))


# --------------------------------------------------------------------------- listing parse


def _text(fragment: str) -> str:
    plain = re.sub(r"<[^>]+>", " ", fragment)
    return "".join(ch if ch.isprintable() else " " for ch in " ".join(unescape(plain).split()))[
        :250
    ]


def _listed(value: str) -> str | None:
    try:
        return datetime.strptime(value, "%b %d, %Y").date().isoformat()
    except ValueError:
        return None


def parse_meetings(html: bytes, base: str = HUB_URL) -> list[str]:
    """Meeting page URLs on the hub, newest first, deduplicated."""
    text = html.decode("utf-8", errors="replace")
    found: dict[str, tuple[int, int, int]] = {}
    for href in re.findall(r'href="([^"]{1,300})"', text):
        absolute = urljoin(base, unescape(href))
        match = _MEETING.fullmatch(absolute)
        if match:
            found[absolute] = (int(match["y"]), int(match["m"]), int(match["d"]))
    return sorted(found, key=lambda url: (found[url], url), reverse=True)


def parse_documents(html: bytes, base: str) -> list[dict[str, Any]]:
    """Linked ERCOT files with their listed date, title and extension. Policy-checked."""
    text = html.decode("utf-8", errors="replace")
    docs: dict[str, dict[str, Any]] = {}
    for match in _ANCHOR.finditer(text):
        url = urljoin(base, unescape(match["href"]))
        if not file_url_ok(url):
            continue
        listed = _listed(match["date"])
        docs.setdefault(
            url,
            {
                "url": url,
                "title": _text(match["text"]),
                "listed": listed,
                "ext": url.rsplit(".", 1)[-1].lower(),
            },
        )
    return list(docs.values())


def meeting_date(url: str) -> str | None:
    match = _MEETING.fullmatch(url)
    if match is None:
        return None
    try:
        return date(int(match["y"]), int(match["m"]), int(match["d"])).isoformat()
    except ValueError:
        return None


def find_tpit(html: bytes, base: str = PLANNING_URL) -> dict[str, Any] | None:
    for doc in parse_documents(html, base):
        if doc["ext"] == "xlsx" and TPIT_TITLE.casefold() in doc["title"].casefold():
            if "archiv" in doc["title"].casefold():
                continue
            return doc
    return None


# --------------------------------------------------------------------------- records


def _doc_id(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def record_for(
    doc: dict[str, Any], *, kind: str, meeting: str | None, listed_on: str
) -> dict[str, Any]:
    url = doc["url"]
    label = {
        "rpg_pdf": "ERCOT RPG meeting document",
        "tpit": "ERCOT TPIT workbook",
        "system_planning": "ERCOT System Planning update",
    }[kind]
    lines = [
        f"{label}: {doc['title'] or url.rsplit('/', 1)[-1]}",
        "Public ERCOT document; project totals only. Customer names, load type and requested "
        "energization dates are not given and are not inferred.",
    ]
    if meeting:
        lines.append(f"RPG meeting date: {meeting}")
    if doc.get("listed"):
        lines.append(f"Listed by ERCOT: {doc['listed']}")
    return {
        "document_number": ("ERCOT-TPIT-" if kind == "tpit" else "ERCOT-RPG-") + _doc_id(url),
        "title": f"{label}: {doc['title'] or url.rsplit('/', 1)[-1]}"[:250],
        "abstract": "\n".join(lines),
        "publication_date": doc.get("listed"),
        "event_date": meeting,
        "event_date_label": "RPG meeting" if meeting else None,
        "html_url": url,
        "extraction_location": "ERCOT planning document",
        "source_hash": hashlib.sha256(f"{url}|{doc.get('listed')}".encode()).hexdigest(),
        "state_key": url,
        "doc_kind": kind,
        "listed_on": listed_on,
    }


# --------------------------------------------------------------------------- retrieve (listing)


def _listing_error(failure: DocumentFailure) -> SourceParseError:
    error = SourceParseError(f"ERCOT listing fetch failed: {failure.code}")
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
    """Listing only: hub, recent meeting pages, the planning page. No document is read here."""
    if source.get("id") != SOURCE_ID or source.get("endpoint") != HUB_URL:
        raise SourceParseError("ERCOT RPG source is not the reviewed endpoint")
    query = source.get("query")
    if not valid_query(query):
        raise SourceParseError("ERCOT RPG configuration is invalid")
    assert isinstance(query, dict)
    listed_on = (today or datetime.now(UTC).date()).isoformat()
    own = client is None
    http = client or stage.new_client()
    try:
        fetcher = EarlyFetcher(http, pacer or shared.Pacer(), url_ok)

        def page(url: str) -> bytes:
            try:
                return fetcher.get(
                    url,
                    max_bytes=query["max_response_bytes"],
                    media_types=HTML,
                    accept="text/html",
                ).body
            except DocumentFailure as failure:
                raise _listing_error(failure) from failure

        meetings = parse_meetings(page(HUB_URL))[: query["max_meetings"]]
        records: dict[str, dict[str, Any]] = {}
        for url in meetings:
            when = meeting_date(url)
            for doc in parse_documents(page(url), url):
                if doc["ext"] != "pdf" or _NOT_PROJECT_DOC.search(doc["title"] or doc["url"]):
                    continue
                records.setdefault(
                    doc["url"],
                    record_for(doc, kind="rpg_pdf", meeting=when, listed_on=listed_on),
                )
        planning = find_tpit(page(PLANNING_URL))
        if planning is not None:
            records.setdefault(
                planning["url"],
                record_for(planning, kind="tpit", meeting=None, listed_on=listed_on),
            )
        for seed in query["documents"]["seed_urls"]:
            doc = {"url": seed, "title": seed.rsplit("/", 1)[-1][:-4], "listed": None, "ext": "pdf"}
            records.setdefault(
                seed, record_for(doc, kind="system_planning", meeting=None, listed_on=listed_on)
            )
        return list(records.values())[: query["max_records"]]
    finally:
        if own:
            http.close()


# --------------------------------------------------------------------------- document stage


def _item_for(record: dict[str, Any]) -> stage.DocItem | None:
    url = record.get("state_key")
    kind = record.get("doc_kind")
    if not file_url_ok(url) or kind not in {"rpg_pdf", "tpit", "system_planning"}:
        return None
    if (kind == "tpit") != str(url).lower().endswith(".xlsx"):
        return None
    return stage.DocItem(
        key=str(url),
        url=str(url),
        kind=str(kind),
        max_bytes=MAX_XLSX_BYTES if kind == "tpit" else MAX_PDF_BYTES,
        media_types=XLSX if kind == "tpit" else PDF,
        recheck_hours=TPIT_RECHECK_HOURS if kind == "tpit" else PDF_RECHECK_HOURS,
        meta={
            "published_at": record.get("publication_date"),
            "listed_on": record.get("listed_on"),
        },
    )


def _extract_rpg(
    body: bytes, item: stage.DocItem, prior: dict[str, Any] | None, budget: float, isolate: bool
) -> dict[str, Any]:
    pages, scanned = extract.read_pdf_pages(body, budget, isolate)
    return extract.rpg_project_extraction(pages, scanned)


def _extract_system_planning(
    body: bytes, item: stage.DocItem, prior: dict[str, Any] | None, budget: float, isolate: bool
) -> dict[str, Any]:
    pages, scanned = extract.read_pdf_pages(body, budget, isolate)
    return extract.system_planning_extraction(pages, scanned)


def _extract_tpit(
    body: bytes, item: stage.DocItem, prior: dict[str, Any] | None, budget: float, isolate: bool
) -> dict[str, Any]:
    return tpit.tpit_extraction(
        body, prior, budget, isolate, str(item.meta.get("listed_on") or date.today().isoformat())
    )


EXTRACTORS: dict[str, stage.Extractor] = {
    "rpg_pdf": _extract_rpg,
    "system_planning": _extract_system_planning,
    "tpit": _extract_tpit,
}


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
    """Read documents, fold their states into the records, add TPIT row records.

    Documents not read this run (budget, deadline, rate limit) keep their earlier state when there
    is one, else the record is withheld as ``presence_only`` rather than stored empty.
    """
    started = now()
    items = [item for record in records if (item := _item_for(record)) is not None]
    in_scope = {item.key for item in items}
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
            extractors=EXTRACTORS,
            now=started,
        )
        run.report.counts["in_scope"] = len(items)
        if stage.resting(index, started):
            run.report.bump("skipped_retry_after")
        else:
            stage.run_documents(run, items)
        report = stage.finish(run, index)
    finally:
        if owns:
            http.close()
    extra: list[dict[str, Any]] = []
    for record in records:
        key = record.get("state_key")
        state = run.states.get(str(key))
        if state is None:
            if _item_for(record) is not None:
                record["presence_only"] = True
            continue
        stage.apply_state(record, state)
        if record.get("doc_kind") == "tpit":
            extra.extend(
                tpit_row_records(state, prior_states.get(str(key)), record.get("publication_date"))
            )
    seen = {r["document_number"] for r in records}
    records.extend(r for r in extra if r["document_number"] not in seen)
    return report


def apply_prior_states(records: list[dict[str, Any]], prior: dict[str, dict[str, Any]]) -> None:
    """Fold retained states into the records when the stage did not run (fault, disabled)."""
    for record in records:
        state = prior.get(str(record.get("state_key")))
        if state is not None:
            stage.apply_state(record, state)
        elif _item_for(record) is not None:
            record["presence_only"] = True


# --------------------------------------------------------------------------- TPIT row records


def _safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", value)[:40]


def tpit_row_records(
    state: dict[str, Any], prior: dict[str, Any] | None, published_at: str | None
) -> list[dict[str, Any]]:
    """Baseline rows or the monthly diff of a changed snapshot, as individual observations."""
    document = state["document"]
    sha = document["sha256"]
    if prior is not None and (prior.get("document") or {}).get("sha256") == sha:
        return []
    extraction = document["extraction"]
    rows: dict[str, dict[str, Any]] = extraction["rows"]
    before_rows: dict[str, dict[str, Any]] = (
        ((prior or {}).get("document") or {}).get("extraction") or {}
    ).get("rows") or {}
    if extraction.get("baseline"):
        changes = [{"project": n, "change": "baseline"} for n in sorted(rows)]
    else:
        changes = list(extraction.get("diff") or [])
    records: list[dict[str, Any]] = []
    for change in changes:
        number = change["project"]
        row = rows.get(number) or before_rows.get(number) or {}
        label = change["change"]
        head = {
            "baseline": "present in the first snapshot read (a baseline, not a new project)",
            "new": "new since the previous snapshot",
            "changed": "changed since the previous snapshot",
            "removed": "absent from this snapshot",
        }[label]
        lines = [
            f"ERCOT TPIT project {number}: {head}",
            f"Title: {row.get('title') or 'unknown'}",
            f"Transmission owner: {row.get('owner') or 'unknown'}",
            f"Status: {row.get('status') or 'unknown'}; lifecycle sheet: {row.get('sheet') or 'unknown'}",
            f"Service level kV: {row.get('kv') or 'unknown'}; planning tier: "
            f"{row.get('tier') or 'unknown'}; RPG number: {row.get('rpg') or 'unknown'}",
            f"County: {row.get('county') or 'unknown'}; ending county: "
            f"{row.get('county_end') or 'unknown'}",
            f"Projected in-service: {row.get('isd') or 'unknown'}; actual in-service: "
            f"{row.get('actual') or 'unknown'}",
            "Load MW: not stated in TPIT; unknown is not zero.",
        ]
        if label == "changed":
            lines.append("Fields changed: " + ", ".join(change.get("fields") or []))
        if label == "removed":
            lines.append(f"Last seen in the previous snapshot (first seen {row.get('fs')}).")
        records.append(
            {
                "document_number": f"ERCOT-TPIT-{sha[:10]}-{_safe(number)}",
                "title": f"ERCOT TPIT {label} {number}: {row.get('title') or 'project'}"[:250],
                "abstract": "\n".join(lines),
                "publication_date": published_at,
                "event_date": None,
                "html_url": state["url"],
                "extraction_location": f"workbook sheet {row.get('sheet') or 'unknown'}",
                "source_hash": hashlib.sha256(f"{sha}|{number}|{label}".encode()).hexdigest(),
                stage.STATE_KEY: {
                    "version": stage.VERSION,
                    "kind": "tpit_row",
                    "key": f"tpit-row:{sha[:10]}:{number}",
                    "stateful": False,
                    "change": label,
                    "project": number,
                    "snapshot_sha256": sha,
                    "location": f"ERCOT Project Number {number}",
                    "first_seen_at": row.get("fs"),
                    "basis": "documented",
                    "row": copy.deepcopy(row),
                },
            }
        )
    return records
