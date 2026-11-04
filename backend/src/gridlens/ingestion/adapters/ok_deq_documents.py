"""Oklahoma DEQ permit-document stage: check, fetch, read the memo header, extract, describe.

Pure with respect to the database, like the TCEQ stage it mirrors
(``tceq_application_documents``), whose fetch helpers, pacer and typed failures it reuses.
The caller supplies the retained per-permit states and the retained key index and receives
updated ones.

**Discovery.** The public-review listing does not expose the ``storedpermits/{N}.pdf`` key.
Each listing row links only to ``permitinformation.aspx?id=...``, whose "Related Documents"
frame is a JavaScript OnBase viewer served from a different, third-party host. So this stage
never derives a document from a listing row. Documents come from, in order of preference:

1. ``seed_keys``: an owner-curated list of keys in the registry;
2. keys already in the retained key index that join a listing row;
3. an explicit, capped forward probe from a recorded frontier (``probe``, default OFF).

The join to the listing is the permit number read from the memo's own SUBJECT line, never the
integer key. A document whose permit number cannot be read is retained as unverified and joined
to nothing.

**Lineage.** Several keys can carry one permit number (a draft and its revisions). They are
versions of one permit state; the highest key is current; a lower key found later is added to
the version list without replacing the current document, and a version's ``first_seen_at`` is
never rewritten.

Bounds: at most one request per second; exact host and path; 40 MB per file; a few downloads
per run; work stops at the job deadline minus a persistence reserve; the first 429 or 503 ends
the stage.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from gridlens.ingestion.adapters import ok_deq_data_center_page as dc_page
from gridlens.ingestion.adapters import tceq_application_documents as shared
from gridlens.ingestion.adapters import tceq_http
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.ok_deq_memo import MemoHeader, normalize_permit, parse_memo_header
from gridlens.ingestion.adapters.tceq_application_documents import (
    DocumentFailure,
    Pacer,
    StageReport,
)

VERSION = "okdeq-permit-document-v1"
STAGE = "okdeq_document"
HOST = "applications.deq.ok.gov"
DOCUMENT_PREFIX = f"https://{HOST}/permitspublic/storedpermits/"
_DOCUMENT_PATH = re.compile(r"/permitspublic/storedpermits/([0-9]{1,6})\.pdf")
USER_AGENT = shared.USER_AGENT
MAX_KEY = 999_999
MAX_PDF_BYTES = 40 * 1024 * 1024
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
MAX_CHECKS_PER_RUN = 60
MAX_DOWNLOADS_PER_RUN = 5
MAX_SEED_KEYS = 50
MAX_PROBES_PER_RUN = 20
MAX_PROBE_MISSES = 5
MIN_EXTRACT_SECONDS_CONFIG = 60
MAX_EXTRACT_SECONDS = 900.0
MAX_INDEX_KEYS = 800
MAX_VERSIONS = 20
ABSENT_RECHECK_DAYS = 7
DEFAULT_RATE_LIMIT_REST_SECONDS = 3600  # when a 429/503 carries no usable Retry-After
HEAVY_RESERVE_SECONDS = 150.0  # stage time left below which no download starts
RETRY_ATTEMPTS = shared.RETRY_ATTEMPTS
RETRY_BACKOFF_DAYS = shared.RETRY_BACKOFF_DAYS
NOTICE_CODES = frozenset(
    {"zero_verified_rows", "unverified_permit_number", "ambiguous_permit_number"}
)
HEALTH_KEY = "okdeq_documents"
STATE_KEY = "okdeq_document"
RETRYABLE = shared.RETRYABLE_CODES


def document_url(key: int) -> str:
    return f"{DOCUMENT_PREFIX}{key}.pdf"


def _key_of(url: str) -> int:
    """The key of an exact ``storedpermits`` URL, or a policy error before any DNS lookup."""
    try:
        parts = httpx.URL(url)
    except httpx.InvalidURL as exc:
        raise SourceParseError("Oklahoma DEQ URL is malformed") from exc
    match = _DOCUMENT_PATH.fullmatch(parts.path)
    if (
        parts.scheme != "https"
        or parts.host != HOST
        or parts.port not in (None, 443)
        or parts.query
        or parts.fragment
        or parts.userinfo
        or match is None
    ):
        raise SourceParseError("Oklahoma DEQ URL is outside the verified route allowlist")
    return int(match.group(1))


# --------------------------------------------------------------------------- config


@dataclass(frozen=True, slots=True)
class StageConfig:
    max_downloads: int = 2
    max_checks: int = 40
    extract_seconds: float = 300.0
    seed_keys: tuple[int, ...] = ()
    probe_enabled: bool = False
    probe_frontier: int = 0
    max_probes: int = 0
    max_misses: int = 3
    data_center_page: bool = False
    isolate: bool = True


def valid_config(raw: Any) -> bool:
    """The registry shape; shared by ``config_from_source`` and the registry validator."""
    if not isinstance(raw, dict) or set(raw) != {
        "enabled",
        "max_downloads",
        "max_checks",
        "extract_seconds",
        "seed_keys",
        "probe",
        "data_center_page",
    }:
        return False
    probe, page, seeds = raw["probe"], raw["data_center_page"], raw["seed_keys"]
    if (
        not isinstance(probe, dict)
        or set(probe) != {"enabled", "frontier", "max_probes", "max_misses"}
        or not isinstance(page, dict)
        or set(page) != {"enabled"}
        or not isinstance(seeds, list)
    ):
        return False

    def number(value: Any, low: int, high: int) -> bool:
        return type(value) is int and low <= value <= high

    return (
        type(raw["enabled"]) is bool
        and number(raw["max_downloads"], 1, MAX_DOWNLOADS_PER_RUN)
        and number(raw["max_checks"], 1, MAX_CHECKS_PER_RUN)
        and number(raw["extract_seconds"], MIN_EXTRACT_SECONDS_CONFIG, int(MAX_EXTRACT_SECONDS))
        and len(seeds) <= MAX_SEED_KEYS
        and len(set(seeds)) == len(seeds)
        and all(number(seed, 1, MAX_KEY) for seed in seeds)
        and type(probe["enabled"]) is bool
        and number(probe["frontier"], 1 if probe["enabled"] else 0, MAX_KEY)
        and number(probe["max_probes"], 0, MAX_PROBES_PER_RUN)
        and number(probe["max_misses"], 1, MAX_PROBE_MISSES)
        and type(page["enabled"]) is bool
    )


def config_from_source(source: dict[str, Any]) -> StageConfig | None:
    """The registry ``query.application_documents`` object, or None when not running."""
    raw = (source.get("query") or {}).get("application_documents")
    if not isinstance(raw, dict) or raw.get("enabled") is not True:
        return None  # absent or explicitly off: the stage does not run
    if not valid_config(raw):
        raise SourceParseError("Oklahoma DEQ document stage bounds are invalid")
    probe = raw["probe"]
    return StageConfig(
        max_downloads=raw["max_downloads"],
        max_checks=raw["max_checks"],
        extract_seconds=float(raw["extract_seconds"]),
        seed_keys=tuple(raw["seed_keys"]),
        probe_enabled=probe["enabled"],
        probe_frontier=probe["frontier"],
        max_probes=probe["max_probes"] if probe["enabled"] else 0,
        max_misses=probe["max_misses"],
        data_center_page=raw["data_center_page"]["enabled"],
    )


# --------------------------------------------------------------------------- report


@dataclass(slots=True)
class OkStageReport(StageReport):
    index: dict[str, Any] = field(default_factory=dict)  # retained key index, updated

    def reject(self, project: str, code: str, **raw: int | str) -> None:
        """Record a failure or notice for a document key. Only codes and small numbers."""
        values = {name: str(value)[:40] for name, value in raw.items()}
        notice = code in NOTICE_CODES
        self.bump(f"notice_{code}" if notice else f"failure_{code}")
        target = self.notices if notice else self.rejections
        if len(target) < 50:
            target.append(
                {
                    "identity": f"OKDEQ-DOC-{project}" if project.isdigit() else project,
                    "stage": STAGE,
                    "error_code": code,
                    "selected_fields": sorted(values),
                    "omitted_fields": [],
                    "raw": values,
                }
            )


class _StageAbort(Exception):
    """The publisher rate-limited the stage: stop making requests this run."""


# --------------------------------------------------------------------------- fetch


@contextmanager
def open_document(
    client: httpx.Client,
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    before_request: Callable[[], None] | None = None,
) -> Iterator[httpx.Response]:
    """Open one streamed request to an exact ``storedpermits`` URL.

    Exact host and path, public DNS answer pinned for the connection, redirects never
    followed (the caller sees the 3xx), ``before_request`` run before the hop for pacing.
    """
    if method not in {"GET", "HEAD"}:
        raise SourceParseError("Oklahoma DEQ request method is unsupported")
    if client.follow_redirects:
        raise SourceParseError("Oklahoma DEQ client must not automatically follow redirects")
    _key_of(url)
    ip = tceq_http._public_ip(HOST)
    pinned = httpx.URL(url).copy_with(host=ip)
    if before_request is not None:
        before_request()
    with client.stream(
        method,
        str(pinned),
        headers={"Host": HOST, **(headers or {})},
        extensions={"sni_hostname": HOST},
    ) as response:
        yield response


def _check_status(response: httpx.Response) -> None:
    if 300 <= response.status_code < 400:
        raise DocumentFailure("redirect_not_followed")
    if response.status_code != 200:
        raise shared._status_failure(response)


def head_document(
    client: httpx.Client, url: str, pacer: Callable[[], None]
) -> dict[str, Any] | None:
    """Validators from a HEAD request, or None when the server does not answer HEAD."""

    def run() -> dict[str, Any] | None:
        headers = {"User-Agent": USER_AGENT, "Accept": "application/pdf"}
        with open_document(
            client, url, method="HEAD", headers=headers, before_request=pacer
        ) as response:
            if response.status_code in {405, 501}:
                return None
            _check_status(response)
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
                raise TimeoutError("Oklahoma DEQ document download deadline exhausted")
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
    """Stream to ``destination`` (never into memory), hashing as it goes.

    ``skip_if`` sees the response validators before any body is read; True returns None
    without downloading.
    """

    def run() -> Download | None:
        headers = {"User-Agent": USER_AGENT, "Accept": "application/pdf"}
        with open_document(client, url, headers=headers, before_request=pacer) as response:
            _check_status(response)
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


def fetch_data_center_page(
    client: httpx.Client, pacer: Callable[[], None]
) -> tuple[list[dict[str, Any]], int]:
    """One request for the data-center page rows, with the same host pin as ``open_document``.

    Exact ``oklahoma.gov`` URL, public DNS answer pinned for the connection, redirects never
    followed. Returns the rows and the count of rows rejected for an overlong cell. Raises
    ``DocumentFailure`` for transport and status problems and ``SourceParseError`` when the
    table is absent or its columns changed.
    """
    if client.follow_redirects:
        raise SourceParseError("Oklahoma DEQ client must not automatically follow redirects")

    def run() -> bytes:
        ip = tceq_http._public_ip(dc_page.PAGE_HOST)
        pinned = httpx.URL(dc_page.PAGE_URL).copy_with(host=ip)
        pacer()
        headers = {"Host": dc_page.PAGE_HOST, "User-Agent": USER_AGENT, "Accept": "text/html"}
        with client.stream(
            "GET", str(pinned), headers=headers, extensions={"sni_hostname": dc_page.PAGE_HOST}
        ) as response:
            _check_status(response)
            if shared._media_type(response.headers) != "text/html":
                raise DocumentFailure("wrong_content_type")
            declared = response.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > dc_page.MAX_PAGE_BYTES:
                raise DocumentFailure("oversize", declared)
            parts: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > dc_page.MAX_PAGE_BYTES:
                    raise DocumentFailure("oversize", str(size))
                parts.append(chunk)
        return b"".join(parts)

    body: bytes = shared._guard_network(run)
    return dc_page.parse_page_checked(body)


# --------------------------------------------------------------------------- extraction


def read_document(
    pdf_path: Path, budget_seconds: float, isolate: bool
) -> tuple[Any, MemoHeader, str]:
    """Canonical text (killable child) and the verified memo header. Raises DocumentFailure."""
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
    header = parse_memo_header(canon.text, canon.page_of)
    # Re-check every quoted fact against the text it claims to come from.
    for fact in (header.permit, header.memo_date, header.company, header.facility):
        if fact is not None and canon.text[fact.start : fact.end] != fact.quote:
            raise DocumentFailure("header_quote_mismatch")
    if header.permit is not None and normalize_permit(header.permit.quote) != header.permit_norm:
        raise DocumentFailure("header_quote_mismatch")
    return canon, header, sha


def extract_listing_document(
    canon: Any,
    header: MemoHeader,
    sha: str,
    key: int,
) -> dict[str, Any]:
    """Run the 1a extractor over the memo for a permit that joined the listing."""
    from gridlens.ingestion.parsers.permit_docs import extract_from_canonical

    result = extract_from_canonical(
        canon,
        document_hash=sha,
        # The listing abstract already carries the one Company and Facility header; a second
        # Company line would make the equipment parser's identity ambiguous and drop it.
        company=None,
        facility=None,
        as_of=header.memo_date.value if header.memo_date is not None else None,
    )
    file_name = f"storedpermits/{key}.pdf"
    lines = {
        str(index): {**entry, "embedded_file": file_name, "outer_sha256": sha}
        for index, entry in result.provenance.items()
    }
    pages = sorted(entry["page"] for entry in lines.values())
    return {
        "file": file_name,
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


def state_digest(state: dict[str, Any]) -> str:
    """Content digest that ignores fetch and first-seen times, so a re-run is idempotent."""
    copy_ = json.loads(json.dumps(state, default=str))
    # Recomputed from the listing record on every fold, so never part of the content digest.
    copy_.pop("identity_check", None)
    if isinstance(copy_.get("dates"), dict):
        copy_["dates"].pop("listing_event_date", None)
    if isinstance(copy_.get("document"), dict):
        copy_["document"].pop("identity_check", None)
    if isinstance(copy_.get("document"), dict):
        copy_["document"].pop("fetched_at", None)
    for version in copy_.get("versions") or []:
        version.pop("first_seen_at", None)
    return hashlib.sha256(
        json.dumps(copy_, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _facility_matches(listing: str, memo: str | None) -> bool:
    """Informational only: the join is the permit number, not the facility name."""
    if not listing or not memo:
        return False
    one, two = " ".join(listing.casefold().split()), " ".join(memo.casefold().split())
    return one in two or two in one


def merge_document(
    prior: dict[str, Any] | None,
    *,
    key: int,
    header: MemoHeader,
    download: Download,
    extraction: dict[str, Any],
    record: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    """Fold one extracted document into the permit state; returns the new state."""
    assert header.permit is not None and header.permit_norm is not None
    base = copy.deepcopy(prior) if prior else {}
    versions = {int(item["key"]): item for item in base.get("versions") or []}
    known = versions.get(key)
    status = "extracted" if extraction["schedule_text"] else "no_equipment_schedule"
    version: dict[str, Any] = {
        "key": key,
        "url": document_url(key),
        "sha256": download.sha256,
        "size": download.size,
        "status": status,
        "memo_date": header.memo_date.value if header.memo_date is not None else None,
        "first_seen_at": known["first_seen_at"] if known else _iso(now),
        "verified_rows": extraction["verified_rows"],
        "demand_lines": extraction["demand_lines"],
        "supply_total": extraction["supply_total"],
    }
    if known and known["sha256"] != download.sha256:
        version["replaced_sha256"] = [*known.get("replaced_sha256", []), known["sha256"]][-5:]
    elif known and known.get("replaced_sha256"):
        version["replaced_sha256"] = known["replaced_sha256"]
    prior_current = max(versions) if versions else 0
    versions[key] = version
    kept = sorted(versions.values(), key=lambda item: int(item["key"]))
    current = max(int(item["key"]) for item in kept)
    if len(kept) > MAX_VERSIONS:
        older = [item for item in kept if int(item["key"]) != current]
        kept = [*older[-(MAX_VERSIONS - 1) :], versions[current]]
    state = base
    state.update(
        {
            "version": VERSION,
            "permit_number": header.permit.value,
            "permit_norm": header.permit_norm,
            "versions": kept,
            "current_key": current,
            "last_attempt": None,
        }
    )
    # A newer key replaces the current document; an older key found later only adds a version.
    if key >= prior_current or not state.get("document"):
        state["document"] = {
            "status": status,
            "key": key,
            "url": document_url(key),
            "sha256": download.sha256,
            "size": download.size,
            "validators": download.validators,
            "fetched_at": _iso(now),
            "memo": header.as_json(),
            "extraction": extraction,
            "abstain": None
            if extraction["schedule_text"]
            else {
                "reason": "no equipment schedule found",
                "scope": "verified electric-driven compressor or pump rows with a stated rating",
                "verified_rows": extraction["verified_rows"],
                "supply_rows": extraction["supply_total"],
                "scanned_pages": extraction["scanned_pages"],
                "note": "Abstention, not zero demand: unknown is not zero.",
            },
        }
        memo_date = header.memo_date
        state["dates"] = {
            "memo_date": memo_date.value if memo_date is not None else None,
            "memo_date_quote": memo_date.quote if memo_date is not None else None,
            "published_at": None,
            "published_at_basis": (
                "Evidence.published_at stays null: the memo date is the draft's internal date, "
                "recorded here with its quote, not a verified public posting date"
            ),
        }
    return state


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
    report: OkStageReport
    keys: dict[str, dict[str, Any]]
    joinable: dict[str, dict[str, Any]]
    states: dict[str, dict[str, Any]]
    downloads: int = 0
    frontier: int = 0

    def left(self) -> float:
        if self.stage_deadline is None:
            return float("inf")
        return self.stage_deadline - time.monotonic()

    def have_extraction(self, entry: dict[str, Any], key: int) -> bool:
        norm = entry.get("permit")
        if not norm or norm not in self.joinable:
            return True  # nothing to extract for this key
        state = self.states.get(norm)
        versions = (state or {}).get("versions") or []
        return any(int(v["key"]) == key and v["sha256"] == entry.get("sha256") for v in versions)


def _tier_sort(run: _Run) -> list[int]:
    """Keys to check this run: unfinished first, then new seeds, then oldest re-validation."""
    config = run.config
    unfinished: list[int] = []
    revalidate: list[tuple[str, int]] = []
    for text, entry in run.keys.items():
        key = int(text)
        status = entry.get("status")
        if status == "pending":
            unfinished.append(key)
        elif status == "document" and entry.get("permit") in run.joinable:
            if not run.have_extraction(entry, key):
                unfinished.append(key)
            else:
                revalidate.append((str(entry.get("at") or ""), key))
        elif key in config.seed_keys and (
            status in {"absent", "failed"} or (status == "document" and not entry.get("permit"))
        ):
            # Absent, failed and unverified-permit seeds are looked at again weekly.
            at = _parse_time(entry.get("at"))
            if at is None or run.now - at >= timedelta(days=ABSENT_RECHECK_DAYS):
                revalidate.append((str(entry.get("at") or ""), key))
    fresh = [key for key in config.seed_keys if str(key) not in run.keys]
    ordered = [*dict.fromkeys(unfinished), *fresh, *(key for _, key in sorted(revalidate))]
    return list(dict.fromkeys(ordered))


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _note_rate_limit(report: OkStageReport, key: int | str, failure: DocumentFailure) -> None:
    report.reject(str(key), failure.code)
    report.bump("aborted_rate_limited")
    if failure.retry_after is not None:
        report.retry_after_seconds = max(report.retry_after_seconds or 0, failure.retry_after)


def _prune_index(keys: dict[str, dict[str, Any]], joinable: set[str]) -> dict[str, dict[str, Any]]:
    if len(keys) <= MAX_INDEX_KEYS:
        return keys

    def rank(item: tuple[str, dict[str, Any]]) -> tuple[int, str]:
        entry = item[1]
        useful = entry.get("status") == "document" and entry.get("permit") in joinable
        return (1 if useful else 0, str(entry.get("at") or ""))

    ordered = sorted(keys.items(), key=rank, reverse=True)[:MAX_INDEX_KEYS]
    return dict(sorted(ordered, key=lambda item: int(item[0])))


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
) -> OkStageReport:
    """Run the stage over listing records and fold each resulting state into its record.

    ``deadline`` is the job's monotonic deadline; the stage works to an earlier one of its
    own, leaving ``persist_reserve`` for the ordinary persistence that follows. Records change
    only after the whole loop succeeds, so a fault leaves them untouched.
    """
    report = OkStageReport()
    stored = index or {}
    keys: dict[str, dict[str, Any]] = {
        str(k): dict(v)
        for k, v in (stored.get("keys") or {}).items()
        if str(k).isdigit() and isinstance(v, dict)
    }
    joinable: dict[str, dict[str, Any]] = {}
    collided: set[str] = set()
    for record in records:
        permit = record.get("permit")
        numbers = permit.get("permit_numbers") if isinstance(permit, dict) else None
        if numbers and not record.get("presence_only"):
            norm = normalize_permit(str(numbers[0]))
            if norm in joinable:
                collided.add(norm)
            joinable[norm] = record
    for norm in sorted(collided):
        # Two listing rows with one permit number: a document cannot be assigned to either.
        del joinable[norm]
        report.reject(norm[:40], "ambiguous_permit_number")
    frontier = max(int(stored.get("frontier") or 0), config.probe_frontier)
    report.counts["in_scope"] = len(joinable)
    states = {norm: copy.deepcopy(state) for norm, state in prior_states.items()}
    owns_client = client is None
    http = client or httpx.Client(
        timeout=httpx.Timeout(
            connect=15.0, read=shared.HTTP_READ_TIMEOUT_SECONDS, write=30.0, pool=15.0
        ),
        follow_redirects=False,
        trust_env=False,
    )
    root = Path(tempfile.mkdtemp(prefix="okdeq-docs-", dir=work_root))
    run = _Run(
        client=http,
        pace=pacer or Pacer(),
        root=root,
        config=config,
        stage_deadline=None if deadline is None else deadline - persist_reserve(len(records)),
        now=now(),
        report=report,
        keys=keys,
        joinable=joinable,
        states=states,
        frontier=frontier,
    )
    # A disabled page keeps no block; an enabled one that fails to load keeps the retained one.
    pages: dict[str, dict[str, Any]] | None = None if config.data_center_page else {}
    not_before = _parse_time(stored.get("not_before"))
    resting = not_before is not None and run.now < not_before
    if resting:
        report.bump("skipped_retry_after")  # the publisher asked us to wait: no request at all
    try:
        try:
            if resting:
                raise _StageAbort
            if config.data_center_page and run.left() >= shared.HTTP_READ_TIMEOUT_SECONDS + 10:
                pages = _load_page(run)
            _check_keys(run)
            if config.probe_enabled:
                _probe(run)
        except _StageAbort:
            pass
    finally:
        shutil.rmtree(root, ignore_errors=True)
        if owns_client:
            http.close()
    if pages is not None:  # a failed page fetch keeps each retained block
        for norm in joinable:
            if norm in pages:
                state = states.setdefault(norm, {"version": VERSION, "permit_norm": norm})
                state["data_center_page"] = pages[norm]
            elif norm in states:
                states[norm].pop("data_center_page", None)
    for norm, state in states.items():
        if norm in joinable:
            apply_state(joinable[norm], state)
    report.counts["downloads"] = run.downloads
    report.counts["frontier"] = run.frontier
    report.index = {
        "frontier": run.frontier or None,
        "keys": _prune_index(keys, set(joinable)),
    }
    if resting and not_before is not None:
        report.index["not_before"] = _iso(not_before)
    elif report.counts.get("aborted_rate_limited"):
        seconds = report.retry_after_seconds or DEFAULT_RATE_LIMIT_REST_SECONDS
        report.index["not_before"] = _iso(run.now + timedelta(seconds=seconds))
    return report


def _load_page(run: _Run) -> dict[str, dict[str, Any]] | None:
    try:
        rows, too_long = fetch_data_center_page(run.client, run.pace)
    except DocumentFailure as failure:
        if failure.rate_limited:
            _note_rate_limit(run.report, "data-center-page", failure)
            raise _StageAbort from failure
        run.report.reject("data-center-page", failure.code)
        return None
    except SourceParseError:
        run.report.reject("data-center-page", "page_parse_failed")
        return None
    run.report.counts["data_center_rows"] = len(rows)
    if too_long:
        run.report.counts["data_center_rows_rejected"] = too_long
    blocks = dc_page.page_blocks(rows)
    run.report.counts["data_center_joinable"] = sum(1 for norm in blocks if norm in run.joinable)
    return blocks


def _check_keys(run: _Run) -> None:
    for position, key in enumerate(_tier_sort(run)):
        if position >= run.config.max_checks:
            run.report.bump("deferred_check_budget")
            continue
        if run.left() < shared.HTTP_READ_TIMEOUT_SECONDS + shared.HEAD_MARGIN_SECONDS:
            run.report.bump("deferred_deadline")
            continue
        try:
            _examine(run, key)
        except TimeoutError:
            run.report.bump("deferred_deadline")


def _probe(run: _Run) -> None:
    """Explicit, capped forward probe from the frontier. Stops after consecutive misses."""
    config = run.config
    key, misses, probes = run.frontier + 1, 0, 0
    while probes < config.max_probes and misses < config.max_misses and key <= MAX_KEY:
        if run.left() < shared.HTTP_READ_TIMEOUT_SECONDS + shared.HEAD_MARGIN_SECONDS:
            run.report.bump("deferred_deadline")
            return
        entry = run.keys.get(str(key))
        at = _parse_time((entry or {}).get("at"))
        if (
            entry
            and entry.get("status") == "absent"
            and at is not None
            and run.now - at < timedelta(days=ABSENT_RECHECK_DAYS)
        ):
            misses += 1
            key += 1
            continue
        probes += 1
        run.report.bump("probed")
        try:
            found = _examine(run, key)
        except TimeoutError:
            run.report.bump("deferred_deadline")
            return
        if found is True:
            misses = 0
            run.frontier = max(run.frontier, key)
        elif found is False:
            misses += 1
        else:
            return  # a transient failure: stop sweeping rather than skip past the key
        key += 1


def _write_entry(run: _Run, key: int, **fields: Any) -> dict[str, Any]:
    entry = {**fields, "at": _iso(run.now)}
    run.keys[str(key)] = entry
    return entry


def _failure_note(entry: dict[str, Any]) -> dict[str, Any] | None:
    """The remembered permanent failure for a key: its own, or one noted on an accepted key."""
    if entry.get("status") == "failed":
        return {
            "code": entry.get("code"),
            "validators": entry.get("validators"),
            "sha256": entry.get("sha256"),
        }
    note = entry.get("last_failure")
    return note if isinstance(note, dict) else None


def _record_failure(
    run: _Run,
    key: int,
    entry: dict[str, Any],
    code: str,
    validators: dict[str, Any] | None,
    sha256: str | None,
) -> None:
    """Remember a permanent failure. An accepted document keeps its accepted facts."""
    if entry.get("status") == "document":
        note = {"code": code, "validators": validators, "sha256": sha256}
        run.keys[str(key)] = {**entry, "last_failure": note, "at": _iso(run.now)}
    else:
        _write_entry(run, key, status="failed", code=code, validators=validators, sha256=sha256)


def _examine(run: _Run, key: int) -> bool | None:
    """Check one key. Returns True when a PDF exists, False when absent, None when unknown.

    Raises ``_StageAbort`` when the publisher answers 429 or 503.
    """
    report, url = run.report, document_url(key)
    report.bump("checked")
    entry = run.keys.get(str(key)) or {}
    validators: dict[str, Any] | None = None
    try:
        validators = head_document(run.client, url, run.pace)
    except DocumentFailure as failure:
        if failure.rate_limited:
            _note_rate_limit(report, key, failure)
            raise _StageAbort from failure
        if failure.code == "http_status_404":
            report.bump("absent")
            _write_entry(run, key, status="absent")
            return False
        if failure.retryable or failure.code.startswith("http_status_"):
            report.reject(str(key), failure.code, stage=1)
            return None
        note = _failure_note(entry)
        if note is not None and note["code"] == failure.code:
            report.bump("known_failed")
            report.known_failed.append(str(key))
            return False
        report.reject(str(key), failure.code, stage=1)
        _record_failure(run, key, entry, failure.code, None, None)
        return False
    if validators is not None and entry.get("status") == "document":
        if shared.validators_match(entry.get("validators"), validators) and run.have_extraction(
            entry, key
        ):
            report.bump("unchanged")
            run.keys[str(key)] = {**entry, "at": _iso(run.now)}
            run.keys[str(key)].pop("retry", None)
            run.keys[str(key)].pop("last_failure", None)
            return True
    note = _failure_note(entry)
    if (
        validators is not None
        and note is not None
        and shared.validators_match(note.get("validators"), validators)
    ):
        report.bump("known_failed")
        report.known_failed.append(str(key))
        return False
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
            return True if validators is not None else None
    # Without HEAD validators nothing confirms the key exists: stay unknown, write nothing.
    deferred = None
    if run.downloads >= run.config.max_downloads:
        deferred = "deferred_download_budget"
    elif run.left() < HEAVY_RESERVE_SECONDS:
        deferred = "deferred_deadline"
    if deferred is not None:
        report.bump(deferred)
        if validators is None:
            return None
        if entry.get("status") not in {"document", "failed"}:
            _write_entry(run, key, status="pending", validators=validators)
        return True
    return _download_and_read(run, key, url, entry, validators)


def _download_and_read(
    run: _Run, key: int, url: str, entry: dict[str, Any], validators: dict[str, Any] | None
) -> bool | None:
    report = run.report
    workdir = run.root / str(key)
    workdir.mkdir(parents=True, exist_ok=True)
    seen: list[dict[str, Any]] = []

    def already_known(candidate: dict[str, Any]) -> bool:
        seen.append(candidate)
        note = _failure_note(entry)
        if note is not None and shared.validators_match(note.get("validators"), candidate):
            return True
        return (
            entry.get("status") == "document"
            and shared.validators_match(entry.get("validators"), candidate)
            and run.have_extraction(entry, key)
        )

    download: Download | None = None
    try:
        run.downloads += 1
        download = download_document(
            run.client, url, workdir / "doc.pdf", run.pace, run.stage_deadline, already_known
        )
        if download is None:
            known_failure = _failure_note(entry)
            matched = known_failure is not None and shared.validators_match(
                known_failure.get("validators"), seen[-1]
            )
            report.bump("known_failed" if matched else "unchanged")
            return True
        if (
            entry.get("status") == "document"
            and entry.get("sha256") == download.sha256
            and run.have_extraction(entry, key)
        ):
            report.bump("unchanged_by_hash")
            run.keys[str(key)] = {
                **entry,
                "validators": download.validators,
                "at": _iso(run.now),
            }
            run.keys[str(key)].pop("retry", None)
            run.keys[str(key)].pop("last_failure", None)
            return True
        note = _failure_note(entry)
        if note is not None and note.get("sha256") == download.sha256:
            report.bump("known_failed")
            report.known_failed.append(str(key))
            return True
        _read_and_record(run, key, download, entry)
        return True
    except DocumentFailure as failure:
        if failure.rate_limited:
            _note_rate_limit(report, key, failure)
            raise _StageAbort from failure
        if failure.code == "http_status_404":
            report.bump("absent")
            _write_entry(run, key, status="absent")
            return False
        report.reject(str(key), failure.code, stage=2)
        sha = download.sha256 if download is not None else None
        used = download.validators if download is not None else failure.validators or validators
        if failure.retryable:
            counted = 0 if failure.budget_limited else 1
            current = dict(entry.get("retry") or {})
            fields = {k: v for k, v in entry.items() if k not in {"retry", "at"}}
            fields.setdefault("status", "pending")  # unfinished: picked up again next run
            run.keys[str(key)] = {
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
            return None
        _record_failure(run, key, entry, failure.code, used, sha)
        return False
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _read_and_record(run: _Run, key: int, download: Download, entry: dict[str, Any]) -> None:
    report, config = run.report, run.config
    budget = min(
        config.extract_seconds,
        run.left() - shared.STAGE_MARGIN_SECONDS - shared.CHILD_GRACE_SECONDS,
    )
    if budget < shared.MIN_EXTRACT_SECONDS:
        raise TimeoutError("not enough stage time left to read the document")
    try:
        canon, header, sha = read_document(download.path, budget, config.isolate)
    except DocumentFailure as failure:
        failure.budget_limited = budget < config.extract_seconds
        raise
    norm = header.permit_norm
    if norm is None:
        report.reject(str(key), "unverified_permit_number")
        _write_entry(
            run,
            key,
            status="document",
            permit=None,
            sha256=download.sha256,
            validators=download.validators,
        )
        return
    record = run.joinable.get(norm)
    if record is None:
        report.bump("unjoined")
        _write_entry(
            run,
            key,
            status="document",
            permit=norm,
            sha256=download.sha256,
            validators=download.validators,
            memo_date=header.memo_date.value if header.memo_date is not None else None,
        )
        return
    extraction = extract_listing_document(canon, header, sha, key)
    if extraction["verified_rows"] == 0 and extraction["supply_total"] == 0:
        report.reject(str(key), "zero_verified_rows", pages=extraction["pages"])
    prior = run.states.get(norm)
    run.states[norm] = merge_document(
        prior,
        key=key,
        header=header,
        download=download,
        extraction=extraction,
        record=record,
        now=run.now,
    )
    _write_entry(
        run,
        key,
        status="document",
        permit=norm,
        sha256=download.sha256,
        validators=download.validators,
        memo_date=header.memo_date.value if header.memo_date is not None else None,
    )
    report.bump("updated" if prior and prior.get("document") else "new")
    report.bump(f"status_{run.states[norm]['versions'][-1]['status']}")


# --------------------------------------------------------------------------- record folding


def apply_state(record: dict[str, Any], state: dict[str, Any]) -> None:
    """Fold a permit state into one listing record: abstract, hash, location, provenance.

    The schedule text is appended to the abstract so the existing equipment parser reads it
    unchanged. Supply rows, versions and the data-center page block live only in provenance.
    Atomic and repeatable: everything is computed from the record's pre-document values
    (kept under ``_document_base``), so a second application replaces the first.
    """
    base = record.get("_document_base") or {
        "abstract": record.get("abstract"),
        "source_hash": record.get("source_hash"),
        "extraction_location": record.get("extraction_location"),
    }
    document = state.get("document") or {}
    schedule = ((document.get("extraction") or {}).get("schedule_text") or "").rstrip("\n")
    abstract = base["abstract"]
    if schedule:
        abstract = f"{abstract or ''}\n{schedule}"
    new_hash = hashlib.sha256(f"{base['source_hash']}:{state_digest(state)}".encode()).hexdigest()
    location = base["extraction_location"]
    if document:
        location = shared._extraction_location(str(location or ""), state)
    snapshot = copy.deepcopy(state)
    if document:
        memo_facility = ((document.get("memo") or {}).get("facility") or {}).get("value")
        listing_facility = str((record.get("permit") or {}).get("facility") or "")
        snapshot["document"]["identity_check"] = {
            "listing_facility": listing_facility,
            "memo_facility": memo_facility,
            "facility_matches": _facility_matches(listing_facility, memo_facility),
        }
        snapshot.setdefault("dates", {})["listing_event_date"] = record.get("event_date")
    record["_document_base"] = base
    record[STATE_KEY] = snapshot
    record["source_hash"] = new_hash
    record["abstract"] = abstract
    if location is not None:
        record["extraction_location"] = location


def apply_prior_states(
    records: list[dict[str, Any]], prior_states: dict[str, dict[str, Any]]
) -> int:
    """Fallback after a stage fault or skip: keep every retained state on its record."""
    applied = 0
    for record in records:
        permit = record.get("permit")
        numbers = permit.get("permit_numbers") if isinstance(permit, dict) else None
        state = prior_states.get(normalize_permit(str(numbers[0]))) if numbers else None
        if state is not None and not record.get("presence_only"):
            apply_state(record, state)
            applied += 1
    return applied
