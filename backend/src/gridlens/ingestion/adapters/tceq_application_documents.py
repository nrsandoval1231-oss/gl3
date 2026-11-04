"""TCEQ application-document stage: discover, check, fetch, unpack, extract, describe.

Pure with respect to the database. The caller supplies prior per-project state (read from the
retained evidence) and receives, per in-scope pending NSR record, an updated state plus typed
diagnostics. ``apply_state`` then folds a state into the NSR record the existing ingestion
service persists, so ``Evidence.abstract`` carries the verified equipment schedule text and
``Evidence.provenance`` carries the document, portfolio manifest and workbook summary.

Bounds (all explicit, see the constants): at most one request per second to TCEQ, outer file
300 MB streamed to a temp file, embedded file 128 MB, a few downloads per run, and work stops
at the job deadline. Unchanged documents are skipped from a HEAD comparison of ETag or
Last-Modified plus length, and from the content hash after a download. A failure never
replaces an accepted state; a non-retryable failure is remembered with its validators so the
same bytes are not fetched again.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx

from gridlens.ingestion.adapters import tceq_portfolio as portfolio
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.tceq_http import open_tceq_application
from gridlens.ingestion.adapters.tceq_nsr_pending import RELEVANT_NAME
from gridlens.ingestion.adapters.tceq_pi1_workbook import (
    UNIT_SHEET,
    WorkbookError,
    read_pi1_workbook,
)

VERSION = "tceq-application-document-v1"
STAGE = "tceq_application_document"
USER_AGENT = "GridLens public source reader/1.0"
MIN_REQUEST_INTERVAL_SECONDS = 1.0
MAX_OUTER_BYTES = 300 * 1024 * 1024
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
MAX_CHECKS_PER_RUN = 120
MAX_DOWNLOADS_PER_RUN = 5
HEAVY_RESERVE_SECONDS = 240.0  # remaining job time below which no download starts
MAX_EXTRACT_SECONDS = 900.0
MAX_WORKBOOKS_PARSED = 2
MAX_SUPPLY_ROWS_KEPT = 200
MAX_ISSUES_KEPT = 25
SHRINK_MIN_PRIOR = 4
SHRINK_RATIO = 0.5
_READ_FIRST = re.compile(r"read[ _]this[ _]first", re.IGNORECASE)
_APPLICATION_URL = re.compile(
    r"https://www\.tceq\.texas\.gov/assets/public/permitting/air/reports/applications/"
    r"([0-9]{1,12})-(ac|tc)\.pdf",
    re.IGNORECASE,
)
_HTML_TYPES = frozenset({"text/html", "application/xhtml+xml", "text/javascript"})
_MARKUP_START = (b"<!doctype", b"<html", b"<script", b"<?xml", b"<head", b"<body")
RETRYABLE_CODES = frozenset(
    {"network_error", "acquisition_timeout", "text_layer_worker_failed", "unpack_time_budget"}
)
# Notice codes: recorded and visible, but they describe a result, not a failed fetch.
NOTICE_CODES = frozenset({"zero_verified_rows", "listing_shrink"})


class DocumentFailure(Exception):
    """A typed document failure. ``code`` is safe to persist; ``detail`` is not."""

    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail

    @property
    def retryable(self) -> bool:
        status = self.code.removeprefix("http_status_")
        if status != self.code and status.isdigit():
            return int(status) in {408, 425, 429} or int(status) >= 500
        return self.code in RETRYABLE_CODES


@dataclass(frozen=True, slots=True)
class StageConfig:
    max_downloads: int = 2
    max_checks: int = 60
    extract_seconds: float = 420.0
    isolate: bool = True


def config_from_source(source: dict[str, Any]) -> StageConfig | None:
    """The registry ``query.application_documents`` object, or None when not configured."""
    raw = (source.get("query") or {}).get("application_documents")
    if not isinstance(raw, dict):
        return None
    downloads, checks = raw.get("max_downloads"), raw.get("max_checks")
    seconds = raw.get("extract_seconds")
    if (
        type(downloads) is not int
        or not 1 <= downloads <= MAX_DOWNLOADS_PER_RUN
        or type(checks) is not int
        or not 1 <= checks <= MAX_CHECKS_PER_RUN
        or type(seconds) is not int
        or not 60 <= seconds <= MAX_EXTRACT_SECONDS
    ):
        raise SourceParseError("TCEQ application document bounds are invalid")
    return StageConfig(max_downloads=downloads, max_checks=checks, extract_seconds=float(seconds))


@dataclass(frozen=True, slots=True)
class ApplicationLink:
    project: str
    kind: str  # ac | tc
    url: str
    applicant: str
    facility: str
    permits: tuple[str, ...]
    received: date
    base_location: str


@dataclass(slots=True)
class StageReport:
    counts: dict[str, int] = field(default_factory=dict)
    rejections: list[dict[str, Any]] = field(default_factory=list)
    known_failed: list[str] = field(default_factory=list)

    def bump(self, key: str, amount: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + amount

    def reject(self, project: str, code: str, **raw: object) -> None:
        values = {key: str(value)[:120] for key, value in raw.items() if value is not None}
        self.bump(f"failure_{code}" if code not in NOTICE_CODES else f"notice_{code}")
        if len(self.rejections) < 50:
            self.rejections.append(
                {
                    "identity": f"TCEQ-{project}",
                    "stage": STAGE,
                    "error_code": code,
                    "selected_fields": sorted(values),
                    "omitted_fields": [],
                    "raw": values,
                }
            )


class Pacer:
    """At most one request per ``interval`` seconds, with an injectable clock for tests."""

    def __init__(
        self,
        interval: float = MIN_REQUEST_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.interval = interval
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = self._clock()  # the listing was just read

    def __call__(self) -> None:
        now = self._clock()
        if self._last is not None and now - self._last < self.interval:
            self._sleep(self.interval - (now - self._last))
            now = self._clock()
        self._last = now


# --------------------------------------------------------------------------- discovery


def discover(records: list[dict[str, Any]]) -> list[ApplicationLink]:
    """In-scope pending NSR filings with an AC/TC link, newest received first.

    Scope is the adapter's own relevance test on applicant and facility names: the same rows
    that already receive the plain-language-summary fetch. Admission stays in the domain layer.
    """
    links: list[ApplicationLink] = []
    for record in records:
        permit = record.get("permit")
        if not isinstance(permit, dict) or record.get("presence_only"):
            continue
        applicant, facility = str(permit.get("applicant") or ""), str(permit.get("facility") or "")
        if not RELEVANT_NAME.search(f"{applicant} {facility}"):
            continue
        url = str((permit.get("document_links") or {}).get("application") or "")
        match = _APPLICATION_URL.fullmatch(url)
        project = str(permit.get("project") or "")
        try:
            received = date.fromisoformat(str(record.get("event_date")))
        except ValueError:
            continue
        if match is None or match.group(1) != project:
            continue
        links.append(
            ApplicationLink(
                project=project,
                kind=match.group(2).lower(),
                url=url,
                applicant=applicant,
                facility=facility,
                permits=tuple(str(item) for item in permit.get("permit_numbers") or ()),
                received=received,
                base_location="TCEQ NSR pending-application listing row",
            )
        )
    return sorted(links, key=lambda link: (link.received, link.project), reverse=True)


# --------------------------------------------------------------------------- fetch


def _validators(headers: httpx.Headers) -> dict[str, Any]:
    length = headers.get("content-length", "")
    return {
        "etag": (headers.get("etag") or "")[:200] or None,
        "last_modified": (headers.get("last-modified") or "")[:80] or None,
        "content_length": int(length) if length.isdigit() else None,
    }


def validators_match(known: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    """Unchanged only on positive evidence: same ETag, or same Last-Modified and length."""
    if not known:
        return False
    if known.get("etag") and current.get("etag"):
        return bool(known["etag"] == current["etag"])
    return bool(
        known.get("last_modified")
        and current.get("last_modified")
        and known.get("content_length") is not None
        and current.get("content_length") is not None
        and known["last_modified"] == current["last_modified"]
        and known["content_length"] == current["content_length"]
    )


def _media_type(headers: httpx.Headers) -> str:
    return headers.get("content-type", "").split(";", 1)[0].strip().lower()


def _classify_type(media_type: str) -> None:
    if media_type in _HTML_TYPES:
        raise DocumentFailure("js_shell", media_type)
    if media_type not in {"application/pdf", "application/x-pdf"}:
        raise DocumentFailure("wrong_content_type", media_type[:60])


def _status_failure(status: int) -> DocumentFailure:
    return DocumentFailure(f"http_status_{status}")


def _guard_network(function: Callable[[], Any]) -> Any:
    try:
        return function()
    except DocumentFailure:
        raise
    except SourceParseError as exc:
        raise DocumentFailure("url_policy", str(exc)[:80]) from exc
    except httpx.TimeoutException as exc:
        raise DocumentFailure("acquisition_timeout") from exc
    except httpx.RequestError as exc:
        raise DocumentFailure("network_error") from exc


def head_document(
    client: httpx.Client, url: str, pacer: Callable[[], None]
) -> dict[str, Any] | None:
    """Validators from a HEAD request, or None when the server does not answer HEAD."""

    def run() -> dict[str, Any] | None:
        headers = {"User-Agent": USER_AGENT, "Accept": "application/pdf"}
        with open_tceq_application(
            client, url, method="HEAD", headers=headers, before_request=pacer
        ) as response:
            if response.status_code in {405, 501}:
                return None
            if response.status_code != 200:
                raise _status_failure(response.status_code)
            _classify_type(_media_type(response.headers))
            result = _validators(response.headers)
            if (result["content_length"] or 0) > MAX_OUTER_BYTES:
                raise DocumentFailure("oversize", str(result["content_length"]))
            return result

    value: dict[str, Any] | None = _guard_network(run)
    return value


@dataclass(slots=True)
class Download:
    path: Path
    sha256: str
    size: int
    validators: dict[str, Any]


def download_document(
    client: httpx.Client,
    url: str,
    destination: Path,
    pacer: Callable[[], None],
    deadline: float | None,
) -> Download:
    """Stream to ``destination`` (never into memory), hashing as it goes."""

    def run() -> Download:
        headers = {"User-Agent": USER_AGENT, "Accept": "application/pdf"}
        digest = hashlib.sha256()
        size = 0
        with open_tceq_application(client, url, headers=headers, before_request=pacer) as response:
            if response.status_code != 200:
                raise _status_failure(response.status_code)
            _classify_type(_media_type(response.headers))
            validators = _validators(response.headers)
            if (validators["content_length"] or 0) > MAX_OUTER_BYTES:
                raise DocumentFailure("oversize", str(validators["content_length"]))
            with destination.open("wb") as handle:
                for chunk in response.iter_bytes(DOWNLOAD_CHUNK_BYTES):
                    if deadline is not None and time.monotonic() >= deadline:
                        raise TimeoutError("TCEQ document download deadline exhausted")
                    if size == 0:
                        head = chunk.lstrip()[:16].lower()
                        if not chunk.startswith(b"%PDF-"):
                            if head.startswith(_MARKUP_START):
                                raise DocumentFailure("js_shell", "markup body")
                            raise DocumentFailure("not_pdf_signature")
                    size += len(chunk)
                    if size > MAX_OUTER_BYTES:
                        raise DocumentFailure("oversize", str(size))
                    digest.update(chunk)
                    handle.write(chunk)
        if size == 0:
            raise DocumentFailure("not_pdf_signature", "empty body")
        return Download(destination, digest.hexdigest(), size, validators)

    value: Download = _guard_network(run)
    return value


# --------------------------------------------------------------------------- extraction


def _json_default(value: object) -> str:
    return str(value)


def _supply_json(rows: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "equipment_id": row.equipment_id,
            "equipment_type": row.equipment_type,
            "drive": row.drive,
            "rating": str(row.rating),
            "unit": row.unit,
            "count": row.count,
            "state": row.state,
            "origin": row.origin,
            "role": "supply_or_other",
            "evidence": {
                name: {
                    "value": ev.value,
                    "quote": ev.quote[:300],
                    "start": ev.start,
                    "end": ev.end,
                    "page": ev.page,
                }
                for name, ev in row.evidence.items()
            },
        }
        for row in rows[:MAX_SUPPLY_ROWS_KEPT]
    ]


def _extract_pdf(
    pdf_path: Path,
    file_name: str,
    outer_sha: str,
    link: ApplicationLink,
    budget_seconds: float,
    isolate: bool,
) -> dict[str, Any]:
    from gridlens.ingestion.parsers.permit_docs import extract_permit_document
    from gridlens.ingestion.parsers.permit_docs.text_layer import TextLayerLimits

    data = pdf_path.read_bytes()
    inner_sha = hashlib.sha256(data).hexdigest()
    limits = TextLayerLimits(
        max_bytes=portfolio.MAX_EMBEDDED_FILE_BYTES,
        max_seconds=max(30.0, budget_seconds),
        max_seconds_per_page=60.0,  # large composite pages; the total bound still applies
    )
    result = extract_permit_document(
        data,
        document_hash=inner_sha,
        company=link.applicant,
        facility=None,  # the NSR abstract already carries the one Facility header
        as_of=link.received.isoformat(),
        limits=limits,
        isolate=isolate,
    )
    del data
    if result.failure is not None:
        raise DocumentFailure(f"text_layer_{result.failure.code}", result.failure.message[:80])
    if result.pages and result.scanned_pages >= result.pages:
        raise DocumentFailure("empty_text_layer", f"{result.pages} pages without text")
    lines = {
        str(index): {**entry, "embedded_file": file_name, "outer_sha256": outer_sha}
        for index, entry in result.provenance.items()
    }
    pages = sorted(entry["page"] for entry in lines.values())
    return {
        "file": file_name,
        "file_sha256": inner_sha,
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
        "issues": [issue[:300] for issue in result.issues[:MAX_ISSUES_KEPT]],
        "schedule_text": result.schedule_text,
        "line_provenance": lines,
        "supply": _supply_json(result.supply_rows),
        "supply_total": len(result.supply_rows),
    }


def build_state(
    link: ApplicationLink,
    download: Download,
    workdir: Path,
    config: StageConfig,
    deadline: float | None,
    now: datetime,
    report: StageReport,
) -> dict[str, Any]:
    """Unpack the portfolio and describe it. Raises ``DocumentFailure``."""
    unpacked = portfolio.unpack_portfolio(
        download.path, workdir / "embedded", isolate=config.isolate
    )
    if unpacked.failure is not None and not unpacked.files:
        raise DocumentFailure(unpacked.failure, unpacked.detail)
    manifest = unpacked.manifest()
    paths = {item.index: workdir / "embedded" / item.path for item in unpacked.files if item.path}
    if unpacked.is_portfolio:
        pdfs = [
            item
            for item in unpacked.files
            if item.kind == "pdf" and item.status == portfolio.EXTRACTED
        ]
        composite = [item for item in pdfs if not _READ_FIRST.search(item.name)]
        if not composite:
            hidden = [
                item
                for item in unpacked.files
                if item.status == portfolio.OVERSIZE and item.name.lower().endswith(".pdf")
            ]
            raise DocumentFailure("embedded_oversize" if hidden else "no_composite_pdf")
        chosen = composite[0]
        pdf_path, pdf_name = paths[chosen.index], chosen.name
    else:
        # Not a portfolio: the outer file itself is the document.
        if download.size > portfolio.MAX_EMBEDDED_FILE_BYTES:
            raise DocumentFailure("embedded_oversize", str(download.size))
        pdf_path, pdf_name, chosen = download.path, f"{link.project}-{link.kind}.pdf", None
    for item_manifest in manifest:
        if chosen is not None and item_manifest["index"] == chosen.index:
            item_manifest["role"] = "composite_pdf"
        elif item_manifest["kind"] == "pdf" and item_manifest["status"] == portfolio.EXTRACTED:
            item_manifest["role"] = (
                "readme" if _READ_FIRST.search(item_manifest["name"]) else ("pdf_not_extracted")
            )
        elif item_manifest["kind"] == "xlsx" and item_manifest["status"] == portfolio.EXTRACTED:
            item_manifest["role"] = "workbook"
        else:
            item_manifest["role"] = "not_used"

    remaining = None if deadline is None else deadline - time.monotonic()
    budget = (
        config.extract_seconds if remaining is None else min(config.extract_seconds, remaining - 60)
    )
    if budget < 30:
        raise TimeoutError("not enough job time left to extract")
    extraction = _extract_pdf(pdf_path, pdf_name, download.sha256, link, budget, config.isolate)

    workbooks: list[dict[str, Any]] = []
    workbook_errors: dict[str, int] = {}
    parsed = 0
    workbook_items = sorted(
        (
            item
            for item in unpacked.files
            if item.kind == "xlsx" and item.status == portfolio.EXTRACTED
        ),
        key=lambda item: item.name,
        reverse=True,  # filenames start with a date stamp: latest submission first
    )
    for item in workbook_items:
        if parsed >= MAX_WORKBOOKS_PARSED or (deadline and time.monotonic() >= deadline - 30):
            break
        try:
            summary = read_pi1_workbook(paths[item.index], item.name)
        except WorkbookError as exc:
            workbook_errors[exc.code] = workbook_errors.get(exc.code, 0) + 1
            continue
        if summary.sheet != UNIT_SHEET:
            continue  # fugitives, stack and calculation workbooks
        workbooks.append({**summary.as_json(), "file_sha256": item.sha256})
        parsed += 1
        for entry in manifest:
            if entry["index"] == item.index:
                entry["role"] = "workbook_parsed"
    for code, count in workbook_errors.items():
        report.bump(f"workbook_{code}", count)

    abstain = None
    if not extraction["schedule_text"]:
        abstain = {
            "reason": "no equipment schedule found",
            "scope": "verified electric-driven compressor or pump rows with a stated rating",
            "verified_rows": extraction["verified_rows"],
            "supply_rows": extraction["supply_total"],
            "scanned_pages": extraction["scanned_pages"],
            "note": "Abstention, not zero demand: unknown is not zero.",
        }
        if extraction["verified_rows"] == 0 and extraction["supply_total"] == 0:
            report.reject(link.project, "zero_verified_rows", pages=extraction["pages"])
    return {
        "version": VERSION,
        "project": link.project,
        "kind": link.kind,
        "url": link.url,
        "document": {
            "status": "extracted" if extraction["schedule_text"] else "no_equipment_schedule",
            "sha256": download.sha256,
            "size": download.size,
            "validators": download.validators,
            "fetched_at": now.isoformat(),
            "is_portfolio": unpacked.is_portfolio,
            "manifest": manifest,
            "extraction": extraction,
            "workbooks": workbooks,
            "workbook_errors": workbook_errors,
            "abstain": abstain,
        },
        "last_attempt": None,
        "dates": {
            "listing_received": link.received.isoformat(),
            "published_at": None,
            "published_at_basis": "TCEQ states no publication date; Last-Modified is a validator",
            "last_modified": download.validators.get("last_modified"),
        },
    }


# --------------------------------------------------------------------------- orchestration


def state_digest(state: dict[str, Any]) -> str:
    """Content digest that ignores fetch time, so an unchanged re-run is idempotent."""
    copy = json.loads(json.dumps(state, default=_json_default))
    if isinstance(copy.get("document"), dict):
        copy["document"].pop("fetched_at", None)
    return hashlib.sha256(
        json.dumps(copy, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _failed_state(
    link: ApplicationLink,
    prior: dict[str, Any] | None,
    failure: DocumentFailure,
    validators: dict[str, Any] | None,
) -> dict[str, Any]:
    """Keep any accepted document; note the failed attempt so the same bytes are not refetched."""
    state = (
        json.loads(json.dumps(prior, default=_json_default))
        if prior
        else {
            "version": VERSION,
            "project": link.project,
            "kind": link.kind,
            "url": link.url,
            "document": None,
            "dates": {"listing_received": link.received.isoformat(), "published_at": None},
        }
    )
    state["last_attempt"] = {
        "status": "failed",
        "code": failure.code,
        "validators": validators,
    }
    return state


def run_stage(
    records: list[dict[str, Any]],
    prior_states: dict[str, dict[str, Any]],
    *,
    client: httpx.Client | None,
    config: StageConfig,
    deadline: float | None = None,
    pacer: Callable[[], None] | None = None,
    work_root: Path | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> StageReport:
    """Run the stage over NSR records and fold each resulting state into its record."""
    report = StageReport()
    links = discover(records)
    by_project = {
        str(r["permit"]["project"]): r for r in records if isinstance(r.get("permit"), dict)
    }
    report.counts["in_scope"] = len(links)
    pace = pacer or Pacer()
    owns_client = client is None
    http = client or httpx.Client(
        timeout=httpx.Timeout(connect=15.0, read=60.0, write=30.0, pool=15.0),
        follow_redirects=False,
        trust_env=False,
    )
    root = Path(tempfile.mkdtemp(prefix="tceq-docs-", dir=work_root))
    downloads = 0
    chosen: dict[str, dict[str, Any]] = {}
    try:
        _check_shrink(links, prior_states, report)
        for position, link in enumerate(links):
            prior = prior_states.get(link.project)
            state = prior
            if position >= config.max_checks:
                report.bump("deferred_check_budget")
            elif deadline is not None and deadline - time.monotonic() < 20.0:
                report.bump("deferred_deadline")
            else:
                try:
                    state, downloaded = _examine(
                        link,
                        prior,
                        http,
                        pace,
                        root,
                        config,
                        deadline,
                        now(),
                        report,
                        allow_download=downloads < config.max_downloads,
                    )
                    downloads += int(downloaded)
                except TimeoutError:
                    report.bump("deferred_deadline")
            if state is not None:
                chosen[link.project] = state
    finally:
        shutil.rmtree(root, ignore_errors=True)
        if owns_client:
            http.close()
    # Records change only after the whole loop succeeds, so a fault leaves them untouched.
    for project, state in chosen.items():
        apply_state(by_project[project], state)
    report.counts["downloads"] = downloads
    return report


def apply_prior_states(
    records: list[dict[str, Any]], prior_states: dict[str, dict[str, Any]]
) -> int:
    """Fallback after a stage fault: keep every retained state on its record."""
    applied = 0
    for record in records:
        permit = record.get("permit")
        state = prior_states.get(str(permit.get("project"))) if isinstance(permit, dict) else None
        if state is not None and not record.get("presence_only"):
            apply_state(record, state)
            applied += 1
    return applied


def _check_shrink(
    links: list[ApplicationLink], prior: dict[str, dict[str, Any]], report: StageReport
) -> None:
    accepted = {p for p, state in prior.items() if state.get("document")}
    if len(accepted) < SHRINK_MIN_PRIOR:
        return
    listed = {link.project for link in links} & accepted
    if len(listed) < len(accepted) * SHRINK_RATIO:
        report.reject("listing", "listing_shrink", previously=len(accepted), listed_now=len(listed))


def _examine(
    link: ApplicationLink,
    prior: dict[str, Any] | None,
    client: httpx.Client,
    pacer: Callable[[], None],
    root: Path,
    config: StageConfig,
    deadline: float | None,
    now: datetime,
    report: StageReport,
    *,
    allow_download: bool,
) -> tuple[dict[str, Any] | None, bool]:
    """Check one document. Returns (state to apply, whether a download was started)."""
    report.bump("checked")
    known_doc = (prior or {}).get("document") or {}
    known_validators = known_doc.get("validators")
    attempt = (prior or {}).get("last_attempt") or {}
    validators: dict[str, Any] | None = None
    try:
        validators = head_document(client, link.url, pacer)
    except DocumentFailure as failure:
        if failure.retryable or failure.code.startswith("http_status_"):
            report.reject(link.project, failure.code, stage="head")
            return prior, False
        if attempt.get("code") == failure.code:
            report.bump("known_failed")
            report.known_failed.append(link.project)
            return prior, False
        report.reject(link.project, failure.code, stage="head")
        return _failed_state(link, prior, failure, None), False
    if validators is not None:
        if known_doc and validators_match(known_validators, validators):
            report.bump("unchanged")
            return prior, False
        if attempt and validators_match(attempt.get("validators"), validators):
            report.bump("known_failed")
            report.known_failed.append(link.project)
            return prior, False
    if not allow_download:
        report.bump("deferred_download_budget")
        return prior, False
    remaining = None if deadline is None else deadline - time.monotonic()
    if remaining is not None and remaining < HEAVY_RESERVE_SECONDS:
        report.bump("deferred_deadline")
        return prior, False
    workdir = root / link.project
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        download = download_document(client, link.url, workdir / "outer.pdf", pacer, deadline)
        if known_doc and known_doc.get("sha256") == download.sha256:
            report.bump("unchanged_by_hash")
            state = json.loads(json.dumps(prior, default=_json_default))
            if state["document"]["validators"] != download.validators:
                state["document"]["validators"] = download.validators
            state["last_attempt"] = None
            return state, True
        state = build_state(link, download, workdir, config, deadline, now, report)
        report.bump("updated" if known_doc else "new")
        report.bump(f"status_{state['document']['status']}")
        return state, True
    except DocumentFailure as failure:
        report.reject(link.project, failure.code, stage="fetch", detail=failure.detail)
        if failure.retryable:
            return prior, True
        return _failed_state(link, prior, failure, validators), True
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# --------------------------------------------------------------------------- record folding


def _extraction_location(base: str, state: dict[str, Any]) -> str:
    """Names the embedded file and page range, within the 100-character column."""
    document = state.get("document") or {}
    extraction = document.get("extraction") or {}
    name = str(extraction.get("file") or "")
    pages = extraction.get("page_range")
    suffix = f" pp.{pages[0]}-{pages[1]}" if pages else " (no equipment schedule found)"
    head = f"{base}; "
    room = 100 - len(head) - len(suffix)
    if not name or room < 8:
        return base
    return f"{head}{name[:room]}{suffix}"[:100]


def apply_state(record: dict[str, Any], state: dict[str, Any]) -> None:
    """Fold a document state into one NSR record: abstract, hash, location and provenance.

    The schedule text is appended to the abstract so the existing equipment parser reads it
    unchanged. Supply rows, the manifest and workbook counts live only in provenance.
    """
    document = state.get("document") or {}
    schedule = ((document.get("extraction") or {}).get("schedule_text") or "").rstrip("\n")
    if schedule and schedule not in (record.get("abstract") or ""):
        record["abstract"] = f"{record.get('abstract') or ''}\n{schedule}"
    base_hash = record.get("source_hash")
    record["application_document"] = state
    record["source_hash"] = hashlib.sha256(
        f"{base_hash}:{state_digest(state)}".encode()
    ).hexdigest()
    if document:
        record["extraction_location"] = _extraction_location(
            str(record.get("extraction_location") or ""), state
        )
