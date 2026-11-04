"""NMED air-quality application documents: dated WordPress uploads, routed to the permit_docs core.

**Discovery (verified live 2026-11-04).** NMED publishes no machine-readable listing of
application PDFs. The WordPress media REST endpoint of the air-quality site lists only five PDFs
(the application files are not in that library), and directory listings are not offered. What is
public is the *public notices* page ``https://www.env.nm.gov/public-notices/`` (about 1.3 MB of
HTML), which links hundreds of PDFs, 54 of them under the air-quality uploads path and about ten
named as applications. Those links are dated only by the WordPress upload path
(``.../uploads/sites/2/YYYY/MM/<name>.pdf``), so the upload month is the only date; it is kept as
the month, never as a publication day. This source reads that one page, keeps links that match
the exact upload-path policy and look like applications, and adds an owner-curated ``seed_urls``
list (at most 50) for applications the page does not link.

**Stage.** The ``application_documents`` stage mirrors the TCEQ and OK DEQ stages and reuses their
pacer, typed failures, validators, report shape and 1a extractor: at most one request per second;
HEAD for validators, then a conditional streamed download with a running SHA-256, never in memory;
the text layer is read in the killable child; verified rows only; supply (anything without a stated
electric drive, and every generator, engine or turbine) is kept apart from demand; a document with
no verified schedule is an explicit abstention, never zero. A 429 or 503 stops the stage and
stores ``not_before`` from Retry-After. The state per document lives in the evidence provenance
(``nmed_document``) and the check index in source health, so evidence hashes do not move on a
re-check.

The facility behind an application is **not** identified here: the NMED facility layers publish no
AI or permit number (see ``nmed_air_facilities``), so no join is made and nothing is guessed from
file names. Equipment demand admission for these records is not defined; they are retained
evidence until a separate, reviewed NMED admission rule exists.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from gridlens.ingestion.adapters import nmed_http
from gridlens.ingestion.adapters import tceq_application_documents as shared
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.tceq_application_documents import (
    DocumentFailure,
    Pacer,
    StageReport,
)

VERSION = "nmed-application-document-v1"
STAGE = "nmed_document"
STATE_KEY = "nmed_document"
HEALTH_KEY = "nmed_documents"
SOURCE_ID = "new-mexico-nmed-air-applications"
RETRIEVAL_METHOD = "nmed-air-applications"
HOST = nmed_http.SITE_HOST
LISTING_URL = f"https://{HOST}/public-notices/"
MAX_LISTING_BYTES = 3_000_000
MAX_LISTING_RECORDS = 200
MAX_PDF_BYTES = 40 * 1024 * 1024
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
MAX_CHECKS_PER_RUN = 60
MAX_DOWNLOADS_PER_RUN = 5
MAX_SEED_URLS = 50
MAX_INDEX_URLS = 400
MIN_EXTRACT_SECONDS_CONFIG = 60
MAX_EXTRACT_SECONDS = 900.0
HEAVY_RESERVE_SECONDS = 150.0
DEFAULT_RATE_LIMIT_REST_SECONDS = 3600
RETRY_ATTEMPTS = shared.RETRY_ATTEMPTS
RETRY_BACKOFF_DAYS = shared.RETRY_BACKOFF_DAYS
RECHECK_DAYS = 7
NOTICE_CODES = frozenset({"zero_verified_rows"})

# Exact upload-path policy: the two WordPress sites NMED uses for air-quality notices.
_UPLOAD_PATH = re.compile(
    r"/(?:air-quality/wp-content/uploads/sites/2|public-notices/wp-content/uploads/sites/32)"
    r"/(?P<year>20\d{2})/(?P<month>0[1-9]|1[0-2])/(?P<name>[A-Za-z0-9][A-Za-z0-9._()+-]{0,150})\.pdf"
)
_APPLICATION_NAME = re.compile(r"application", re.I)
_NOT_AN_APPLICATION = re.compile(
    r"approval|letter|hearing|\bnotice[-_ ]of\b|public[-_ ]notice|spanish|transmittal|comment",
    re.I,
)


# --------------------------------------------------------------------------- URL policy


def document_url_ok(url: Any) -> bool:
    """Exact host, https, an upload-path PDF, no query, fragment, userinfo or odd port."""
    if not isinstance(url, str):
        return False
    try:
        nmed_http.check_host(url, HOST)
        parts = urlsplit(url)
    except (SourceParseError, ValueError):
        return False
    return not parts.query and _UPLOAD_PATH.fullmatch(parts.path) is not None


def upload_month(url: str) -> str | None:
    match = _UPLOAD_PATH.fullmatch(urlsplit(url).path) if document_url_ok(url) else None
    return f"{match['year']}-{match['month']}" if match else None


def looks_like_application(url: str) -> bool:
    match = _UPLOAD_PATH.fullmatch(urlsplit(url).path)
    if match is None:
        return False
    name = match["name"]
    return bool(_APPLICATION_NAME.search(name)) and not _NOT_AN_APPLICATION.search(name)


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            for name, value in attrs:
                if name == "href" and value and len(value) <= 600:
                    self.hrefs.append(value)


def parse_listing_links(html: bytes, base_url: str = LISTING_URL) -> list[str]:
    """Application PDF links on the page, newest upload month first, deduplicated."""
    parser = _Links()
    try:
        parser.feed(html.decode("utf-8", errors="replace"))
    except Exception as exc:  # html.parser is lenient; anything else is a schema fault
        raise SourceParseError("NMED listing page could not be parsed") from exc
    seen: dict[str, None] = {}
    for href in parser.hrefs:
        try:
            absolute = urljoin(base_url, href.strip())
        except ValueError:
            continue
        if document_url_ok(absolute) and looks_like_application(absolute):
            seen.setdefault(absolute, None)
    return sorted(seen, key=lambda url: (upload_month(url) or "", url), reverse=True)


def record_for(url: str) -> dict[str, Any]:
    """The listing record for one application PDF. Dated only by its upload month."""
    month = upload_month(url)
    if month is None:
        raise SourceParseError("NMED document URL is outside the upload-path policy")
    stem = _UPLOAD_PATH.fullmatch(urlsplit(url).path)["name"]  # type: ignore[index]
    return {
        "document_number": "NMED-AQ-" + hashlib.sha256(url.encode()).hexdigest()[:16],
        "title": f"NMED air quality application document {stem}"[:250],
        "abstract": (
            "New Mexico Environment Department air quality application document "
            f"{stem}. Dated only by its upload month {month}; the application date, "
            "applicant and facility are not read from this listing."
        ),
        "publication_date": f"{month}-01",
        "publication_date_precision": "month",
        "html_url": url,
        "pdf_url": url,
        "source_hash": hashlib.sha256(f"{url}|{month}".encode()).hexdigest(),
    }


# --------------------------------------------------------------------------- configuration


@dataclass(frozen=True, slots=True)
class StageConfig:
    max_downloads: int
    max_checks: int
    extract_seconds: float
    seed_urls: tuple[str, ...] = ()
    isolate: bool = True


def valid_config(raw: Any) -> bool:
    if not isinstance(raw, dict):
        return False
    if set(raw) != {"enabled", "max_downloads", "max_checks", "extract_seconds", "seed_urls"}:
        return False
    seeds = raw["seed_urls"]
    return (
        type(raw["enabled"]) is bool
        and type(raw["max_downloads"]) is int
        and 1 <= raw["max_downloads"] <= MAX_DOWNLOADS_PER_RUN
        and type(raw["max_checks"]) is int
        and 1 <= raw["max_checks"] <= MAX_CHECKS_PER_RUN
        and type(raw["extract_seconds"]) is int
        and MIN_EXTRACT_SECONDS_CONFIG <= raw["extract_seconds"] <= MAX_EXTRACT_SECONDS
        and isinstance(seeds, list)
        and len(seeds) <= MAX_SEED_URLS
        and len(set(seeds)) == len(seeds)
        and all(document_url_ok(url) for url in seeds)
    )


def valid_query(query: Any) -> bool:
    """Registry bounds for the whole source query."""
    if not isinstance(query, dict):
        return False
    return (
        set(query) == {"max_response_bytes", "max_records", "application_documents"}
        and query["max_response_bytes"] == MAX_LISTING_BYTES
        and type(query["max_records"]) is int
        and 1 <= query["max_records"] <= MAX_LISTING_RECORDS
        and valid_config(query["application_documents"])
    )


def config_from_source(source: dict[str, Any]) -> StageConfig | None:
    raw = (source.get("query") or {}).get("application_documents")
    if raw is None or not valid_config(raw) or raw["enabled"] is not True:
        return None
    return StageConfig(
        max_downloads=raw["max_downloads"],
        max_checks=raw["max_checks"],
        extract_seconds=float(raw["extract_seconds"]),
        seed_urls=tuple(raw["seed_urls"]),
    )


# --------------------------------------------------------------------------- listing


def retrieve(
    source: dict[str, Any], client: httpx.Client | None = None, *, deadline: float | None = None
) -> list[dict[str, Any]]:
    """One request for the notices page, plus the owner's seed URLs. No PDF is fetched here."""
    if source.get("id") != SOURCE_ID or source.get("endpoint") != LISTING_URL:
        raise SourceParseError("NMED listing source is not the reviewed endpoint")
    query = source.get("query")
    if not valid_query(query):
        raise SourceParseError("NMED listing configuration is invalid")
    assert isinstance(query, dict)
    own = client is None
    http = client or httpx.Client(timeout=30.0, follow_redirects=False, trust_env=False)
    try:

        def run() -> bytes:
            with nmed_http.open_pinned(
                http, LISTING_URL, HOST, headers={"Accept": "text/html"}
            ) as r:
                nmed_http.check_status(r)
                if shared._media_type(r.headers) not in {"text/html", "application/xhtml+xml"}:
                    raise DocumentFailure("wrong_content_type")
                return nmed_http.read_limited(r, query["max_response_bytes"])

        try:
            body: bytes = shared._guard_network(run)
        except DocumentFailure as failure:
            raise SourceParseError(f"NMED listing fetch failed: {failure.code}") from failure
        links = parse_listing_links(body)
        seeds = query["application_documents"]["seed_urls"]
        ordered = list(dict.fromkeys([*seeds, *links]))[: query["max_records"]]
        return [record_for(url) for url in ordered]
    finally:
        if own:
            http.close()


# --------------------------------------------------------------------------- report


@dataclass(slots=True)
class NmedStageReport(StageReport):
    index: dict[str, Any] = field(default_factory=dict)

    def reject(self, project: str, code: str, **raw: int | str) -> None:
        values = {name: str(value)[:40] for name, value in raw.items()}
        notice = code in NOTICE_CODES
        self.bump(f"notice_{code}" if notice else f"failure_{code}")
        target = self.notices if notice else self.rejections
        if len(target) < 50:
            target.append(
                {
                    "identity": f"NMED-DOC-{project}",
                    "stage": STAGE,
                    "error_code": code,
                    "selected_fields": sorted(values),
                    "omitted_fields": [],
                    "raw": values,
                }
            )


class _StageAbort(Exception):
    """The publisher rate-limited the stage: stop making requests this run."""


def _ident(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:12]


# --------------------------------------------------------------------------- fetch


def head_document(
    client: httpx.Client, url: str, pacer: Callable[[], None]
) -> dict[str, Any] | None:
    def run() -> dict[str, Any] | None:
        with nmed_http.open_pinned(
            client,
            url,
            HOST,
            method="HEAD",
            headers={"Accept": "application/pdf"},
            before_request=pacer,
        ) as response:
            if response.status_code in {405, 501}:
                return None
            nmed_http.check_status(response)
            shared._classify_type(shared._media_type(response.headers))
            result = shared._validators(response.headers)
            if (result["content_length"] or 0) > MAX_PDF_BYTES:
                raise DocumentFailure("oversize", str(result["content_length"]))
            return result

    value: dict[str, Any] | None = shared._guard_network(run)
    return value


@dataclass(slots=True)
class Download:
    path: Path
    sha256: str
    size: int
    validators: dict[str, Any]


def _stream_body(
    response: httpx.Response, destination: Path, deadline: float | None, validators: dict[str, Any]
) -> Download:
    digest = hashlib.sha256()
    size = 0
    with destination.open("wb") as handle:
        for chunk in response.iter_bytes(DOWNLOAD_CHUNK_BYTES):
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("NMED document download deadline exhausted")
            if size == 0 and not chunk.startswith(b"%PDF-"):
                if chunk.lstrip()[:16].lower().startswith(shared._MARKUP_START):
                    raise DocumentFailure("js_shell", "markup body")
                raise DocumentFailure("not_pdf_signature")
            size += len(chunk)
            if size > MAX_PDF_BYTES:
                raise DocumentFailure("oversize", str(size))
            digest.update(chunk)
            handle.write(chunk)
    if size == 0:
        raise DocumentFailure("not_pdf_signature", "empty body")
    return Download(destination, digest.hexdigest(), size, validators)


def download_document(
    client: httpx.Client,
    url: str,
    destination: Path,
    pacer: Callable[[], None],
    deadline: float | None,
    skip_if: Callable[[dict[str, Any]], bool] | None = None,
) -> Download | None:
    def run() -> Download | None:
        with nmed_http.open_pinned(
            client, url, HOST, headers={"Accept": "application/pdf"}, before_request=pacer
        ) as response:
            nmed_http.check_status(response)
            shared._classify_type(shared._media_type(response.headers))
            validators = shared._validators(response.headers)
            if (validators["content_length"] or 0) > MAX_PDF_BYTES:
                raise DocumentFailure("oversize", str(validators["content_length"]))
            if skip_if is not None and skip_if(validators):
                return None
            try:
                return _stream_body(response, destination, deadline, validators)
            except DocumentFailure as failure:
                failure.validators = validators
                raise

    value: Download | None = shared._guard_network(run)
    return value


# --------------------------------------------------------------------------- extraction


def read_and_extract(
    pdf_path: Path, url: str, budget_seconds: float, isolate: bool
) -> dict[str, Any]:
    """Canonical text in the killable child, then the 1a extractor. Raises DocumentFailure."""
    from gridlens.ingestion.parsers.permit_docs import extract_from_canonical
    from gridlens.ingestion.parsers.permit_docs.text_layer import (
        TextLayerFailure,
        TextLayerLimits,
        build_canonical_text,
    )

    data = pdf_path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    limits = TextLayerLimits(
        max_bytes=MAX_PDF_BYTES, max_seconds=budget_seconds, max_seconds_per_page=60.0
    )
    canon = build_canonical_text(data, limits, isolate=isolate)
    del data
    if isinstance(canon, TextLayerFailure):
        raise DocumentFailure(f"text_layer_{canon.code}")
    if canon.pages and len(canon.scanned_pages) >= len(canon.pages):
        raise DocumentFailure("empty_text_layer")
    result = extract_from_canonical(canon, document_hash=sha, company=None, facility=None)
    name = urlsplit(url).path.rsplit("/", 1)[-1]
    lines = {
        str(index): {**entry, "embedded_file": name, "outer_sha256": sha}
        for index, entry in result.provenance.items()
    }
    pages = sorted(entry["page"] for entry in lines.values())
    return {
        "file": name,
        "file_sha256": sha,
        "extractor": "permit-doc-extract-v1",
        "pages": result.pages,
        "scanned_pages": result.scanned_pages,
        "needs_ocr_pages": result.needs_ocr_pages[:200],
        "routes": result.routes,
        "verified_rows": result.verified,
        "rejected_rows": result.rejected,
        "duplicates": result.duplicates,
        "demand_lines": len(lines),
        "page_range": [pages[0], pages[-1]] if pages else None,
        "issues": [issue[:300] for issue in result.issues[: shared.MAX_ISSUES_KEPT]],
        "schedule_text": result.schedule_text,
        "line_provenance": lines,
        "supply": shared._supply_json(result.supply_rows),
        "supply_total": len(result.supply_rows),
    }


# --------------------------------------------------------------------------- state


def _iso(moment: datetime) -> str:
    return moment.isoformat()


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def state_digest(state: dict[str, Any]) -> str:
    """Content digest that ignores fetch times, so a re-run is idempotent."""
    copy_ = json.loads(json.dumps(state, default=str))
    if isinstance(copy_.get("document"), dict):
        copy_["document"].pop("fetched_at", None)
        copy_["document"].pop("validators", None)
    copy_.pop("first_seen_at", None)
    return hashlib.sha256(
        json.dumps(copy_, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def build_state(
    prior: dict[str, Any] | None,
    *,
    url: str,
    download: Download,
    extraction: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    base = copy.deepcopy(prior) if prior else {}
    status = "extracted" if extraction["schedule_text"] else "no_equipment_schedule"
    replaced = list(((base.get("document") or {}).get("replaced_sha256")) or [])
    old = (base.get("document") or {}).get("sha256")
    if old and old != download.sha256:
        replaced = [*replaced, old][-5:]
    base.update(
        {
            "version": VERSION,
            "url": url,
            "upload_month": upload_month(url),
            # Never rewritten once set.
            "first_seen_at": base.get("first_seen_at") or _iso(now),
            "document": {
                "status": status,
                "sha256": download.sha256,
                "size": download.size,
                "validators": download.validators,
                "fetched_at": _iso(now),
                "replaced_sha256": replaced,
                "extraction": extraction,
                "abstain": None
                if extraction["schedule_text"]
                else {
                    "reason": "no equipment schedule found",
                    "scope": "verified electric-driven compressor or pump rows with a rating",
                    "verified_rows": extraction["verified_rows"],
                    "supply_rows": extraction["supply_total"],
                    "scanned_pages": extraction["scanned_pages"],
                    "note": "Abstention, not zero demand: unknown is not zero.",
                },
            },
        }
    )
    return base


def apply_state(record: dict[str, Any], state: dict[str, Any]) -> None:
    """Fold a document state into its listing record: abstract, hash and provenance.

    Atomic and repeatable: everything is computed from the record's pre-document values.
    """
    base = record.get("_document_base") or {
        "abstract": record.get("abstract"),
        "source_hash": record.get("source_hash"),
    }
    schedule = (
        ((state.get("document") or {}).get("extraction") or {}).get("schedule_text") or ""
    ).rstrip("\n")
    abstract = base["abstract"]
    if schedule:
        abstract = f"{abstract or ''}\n{schedule}"
    record["_document_base"] = base
    record[STATE_KEY] = copy.deepcopy(state)
    record["abstract"] = abstract
    record["source_hash"] = hashlib.sha256(
        f"{base['source_hash']}:{state_digest(state)}".encode()
    ).hexdigest()


def apply_prior_states(records: list[dict[str, Any]], prior: dict[str, dict[str, Any]]) -> int:
    applied = 0
    for record in records:
        state = prior.get(str(record.get("pdf_url")))
        if state is not None:
            apply_state(record, state)
            applied += 1
    return applied


# --------------------------------------------------------------------------- orchestration


def persist_reserve(record_count: int) -> float:
    return shared.persist_reserve(record_count)


@dataclass(slots=True)
class _Run:
    client: httpx.Client
    pace: Callable[[], None]
    root: Path
    config: StageConfig
    stage_deadline: float | None
    now: datetime
    report: NmedStageReport
    urls: dict[str, dict[str, Any]]
    states: dict[str, dict[str, Any]]
    downloads: int = 0

    def left(self) -> float:
        if self.stage_deadline is None:
            return float("inf")
        return self.stage_deadline - time.monotonic()

    def have_state(self, url: str, entry: dict[str, Any]) -> bool:
        state = self.states.get(url)
        document = (state or {}).get("document") or {}
        return document.get("sha256") == entry.get("sha256") and bool(document)


def _write(run: _Run, url: str, **fields: Any) -> dict[str, Any]:
    entry = {**fields, "at": _iso(run.now)}
    run.urls[url] = entry
    return entry


def _failure_note(entry: dict[str, Any]) -> dict[str, Any] | None:
    if entry.get("status") == "failed":
        return {
            "code": entry.get("code"),
            "validators": entry.get("validators"),
            "sha256": entry.get("sha256"),
        }
    note = entry.get("last_failure")
    return note if isinstance(note, dict) else None


def _record_failure(
    run: _Run, url: str, entry: dict[str, Any], code: str, validators: Any, sha: str | None
) -> None:
    if entry.get("status") == "document":
        note = {"code": code, "validators": validators, "sha256": sha}
        run.urls[url] = {**entry, "last_failure": note, "at": _iso(run.now)}
    else:
        _write(run, url, status="failed", code=code, validators=validators, sha256=sha)


def _note_rate_limit(report: NmedStageReport, url: str, failure: DocumentFailure) -> None:
    report.reject(_ident(url), failure.code)
    report.bump("aborted_rate_limited")
    if failure.retry_after is not None:
        report.retry_after_seconds = max(report.retry_after_seconds or 0, failure.retry_after)


def _order(run: _Run, records: list[dict[str, Any]]) -> list[str]:
    """Unfinished first, then never-seen (newest upload first), then oldest re-validation."""
    unfinished: list[str] = []
    fresh: list[str] = []
    revalidate: list[tuple[str, str]] = []
    for record in records:
        url = str(record["pdf_url"])
        entry = run.urls.get(url)
        if entry is None:
            fresh.append(url)
        elif entry.get("status") == "pending" or (
            entry.get("status") == "document" and not run.have_state(url, entry)
        ):
            unfinished.append(url)
        elif entry.get("status") in {"document", "absent", "failed"}:
            at = _parse_time(entry.get("at"))
            if (
                entry.get("status") == "document"
                or at is None
                or (run.now - at >= timedelta(days=RECHECK_DAYS))
            ):
                revalidate.append((str(entry.get("at") or ""), url))
    return [*unfinished, *fresh, *(url for _, url in sorted(revalidate))]


def run_stage(
    records: list[dict[str, Any]],
    prior_states: dict[str, dict[str, Any]],
    *,
    client: httpx.Client | None,
    config: StageConfig,
    index: dict[str, Any] | None = None,
    deadline: float | None = None,
    pacer: Callable[[], None] | None = None,
    work_root: Path | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> NmedStageReport:
    report = NmedStageReport()
    stored = index or {}
    urls = {
        str(k): dict(v)
        for k, v in (stored.get("urls") or {}).items()
        if document_url_ok(k) and isinstance(v, dict)
    }
    in_scope = {str(r["pdf_url"]) for r in records if document_url_ok(r.get("pdf_url"))}
    states = {u: copy.deepcopy(s) for u, s in prior_states.items() if u in in_scope}
    report.counts["in_scope"] = len(in_scope)
    owns = client is None
    http = client or httpx.Client(
        timeout=httpx.Timeout(
            connect=15.0, read=shared.HTTP_READ_TIMEOUT_SECONDS, write=30.0, pool=15.0
        ),
        follow_redirects=False,
        trust_env=False,
    )
    root = Path(tempfile.mkdtemp(prefix="nmed-docs-", dir=work_root))
    run = _Run(
        client=http,
        pace=pacer or Pacer(),
        root=root,
        config=config,
        stage_deadline=None if deadline is None else deadline - persist_reserve(len(records)),
        now=now(),
        report=report,
        urls=urls,
        states=states,
    )
    not_before = _parse_time(stored.get("not_before"))
    resting = not_before is not None and run.now < not_before
    if resting:
        report.bump("skipped_retry_after")
    try:
        if not resting:
            checked = 0
            for url in _order(run, [r for r in records if str(r["pdf_url"]) in in_scope]):
                if (
                    checked >= config.max_checks
                    or run.left() < shared.HTTP_READ_TIMEOUT_SECONDS + 10
                ):
                    report.bump("deferred_check_budget")
                    break
                checked += 1
                _examine(run, url)
    except _StageAbort:
        pass
    finally:
        shutil.rmtree(root, ignore_errors=True)
        if owns:
            http.close()
    for record in records:
        state = states.get(str(record.get("pdf_url")))
        if state is not None:
            apply_state(record, state)
    report.counts["downloads"] = run.downloads
    keep = dict(sorted(urls.items(), key=lambda kv: str(kv[1].get("at") or ""), reverse=True))
    report.index = {"urls": dict(list(keep.items())[:MAX_INDEX_URLS])}
    if resting and not_before is not None:
        report.index["not_before"] = _iso(not_before)
    elif report.counts.get("aborted_rate_limited"):
        seconds = report.retry_after_seconds or DEFAULT_RATE_LIMIT_REST_SECONDS
        report.index["not_before"] = _iso(run.now + timedelta(seconds=seconds))
    return report


def _examine(run: _Run, url: str) -> None:
    report = run.report
    report.bump("checked")
    entry = run.urls.get(url) or {}
    validators: dict[str, Any] | None = None
    try:
        validators = head_document(run.client, url, run.pace)
    except DocumentFailure as failure:
        if failure.rate_limited:
            _note_rate_limit(report, url, failure)
            raise _StageAbort from failure
        if failure.code == "http_status_404":
            report.bump("absent")
            _write(run, url, status="absent")
            return
        if failure.retryable or failure.code.startswith("http_status_"):
            report.reject(_ident(url), failure.code, stage=1)
            return
        note = _failure_note(entry)
        if note is not None and note["code"] == failure.code:
            report.bump("known_failed")
            return
        report.reject(_ident(url), failure.code, stage=1)
        _record_failure(run, url, entry, failure.code, None, None)
        return
    if validators is not None and entry.get("status") == "document":
        if shared.validators_match(entry.get("validators"), validators) and run.have_state(
            url, entry
        ):
            report.bump("unchanged")
            run.urls[url] = {**entry, "at": _iso(run.now)}
            run.urls[url].pop("retry", None)
            run.urls[url].pop("last_failure", None)
            return
    note = _failure_note(entry)
    if (
        validators is not None
        and note is not None
        and shared.validators_match(note.get("validators"), validators)
    ):
        report.bump("known_failed")
        return
    retry = entry.get("retry") or {}
    if retry.get("attempts", 0) >= RETRY_ATTEMPTS:
        rested = _parse_time(retry.get("at"))
        changed = validators is not None and not shared.validators_match(
            retry.get("validators"), validators
        )
        if (
            rested is not None
            and run.now < rested + timedelta(days=RETRY_BACKOFF_DAYS)
            and not changed
        ):
            report.bump("backed_off")
            return
    deferred = None
    if run.downloads >= run.config.max_downloads:
        deferred = "deferred_download_budget"
    elif run.left() < HEAVY_RESERVE_SECONDS:
        deferred = "deferred_deadline"
    if deferred is not None:
        report.bump(deferred)
        if validators is not None and entry.get("status") not in {"document", "failed"}:
            _write(run, url, status="pending", validators=validators)
        return
    _download_and_read(run, url, entry, validators)


def _download_and_read(
    run: _Run, url: str, entry: dict[str, Any], validators: dict[str, Any] | None
) -> None:
    report = run.report
    workdir = run.root / _ident(url)
    workdir.mkdir(parents=True, exist_ok=True)

    def already_known(candidate: dict[str, Any]) -> bool:
        note = _failure_note(entry)
        if note is not None and shared.validators_match(note.get("validators"), candidate):
            return True
        return (
            entry.get("status") == "document"
            and shared.validators_match(entry.get("validators"), candidate)
            and run.have_state(url, entry)
        )

    download: Download | None = None
    try:
        run.downloads += 1
        download = download_document(
            run.client, url, workdir / "doc.pdf", run.pace, run.stage_deadline, already_known
        )
        if download is None:
            report.bump("unchanged")
            return
        if (
            entry.get("status") == "document"
            and entry.get("sha256") == download.sha256
            and run.have_state(url, entry)
        ):
            report.bump("unchanged_by_hash")
            run.urls[url] = {**entry, "validators": download.validators, "at": _iso(run.now)}
            run.urls[url].pop("retry", None)
            run.urls[url].pop("last_failure", None)
            return
        note = _failure_note(entry)
        if note is not None and note.get("sha256") == download.sha256:
            report.bump("known_failed")
            return
        budget = min(
            run.config.extract_seconds,
            run.left() - shared.STAGE_MARGIN_SECONDS - shared.CHILD_GRACE_SECONDS,
        )
        if budget < shared.MIN_EXTRACT_SECONDS:
            raise TimeoutError("not enough stage time left to read the document")
        try:
            extraction = read_and_extract(download.path, url, budget, run.config.isolate)
        except DocumentFailure as failure:
            failure.budget_limited = budget < run.config.extract_seconds
            raise
        if extraction["verified_rows"] == 0 and extraction["supply_total"] == 0:
            report.reject(_ident(url), "zero_verified_rows", pages=extraction["pages"])
        prior = run.states.get(url)
        run.states[url] = build_state(
            prior, url=url, download=download, extraction=extraction, now=run.now
        )
        _write(run, url, status="document", sha256=download.sha256, validators=download.validators)
        report.bump("updated" if prior and prior.get("document") else "new")
        report.bump(f"status_{run.states[url]['document']['status']}")
    except DocumentFailure as failure:
        if failure.rate_limited:
            _note_rate_limit(report, url, failure)
            raise _StageAbort from failure
        if failure.code == "http_status_404":
            report.bump("absent")
            _write(run, url, status="absent")
            return
        report.reject(_ident(url), failure.code, stage=2)
        sha = download.sha256 if download is not None else None
        used = download.validators if download is not None else failure.validators or validators
        if failure.retryable:
            counted = 0 if failure.budget_limited else 1
            current = dict(entry.get("retry") or {})
            fields = {k: v for k, v in entry.items() if k not in {"retry", "at"}}
            fields.setdefault("status", "pending")
            run.urls[url] = {
                **fields,
                "at": entry.get("at") or _iso(run.now),
                "retry": {
                    "code": failure.code,
                    "attempts": int(current.get("attempts", 0)) + counted,
                    "at": _iso(run.now),
                    "sha256": sha,
                    "validators": used,
                },
            }
            return
        _record_failure(run, url, entry, failure.code, used, sha)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
