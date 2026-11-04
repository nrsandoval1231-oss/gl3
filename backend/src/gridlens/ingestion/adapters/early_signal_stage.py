"""Shared document stage for the early-signal sources (ERCOT planning, PUCT certificate dockets).

A source lists documents cheaply (``retrieve``); this stage reads the documents. It follows the
TCEQ, OK DEQ and NMED discipline and reuses their pacer, typed failures, validators and report:

* at most one request per second, a declared generic user agent, no redirects, exact host and path
  policy, size caps by Content-Length and by running count (``early_signal_http``);
* a conditional GET when validators are known; unchanged by validators or by content hash is
  skipped and keeps its earlier state, so an unchanged re-run is idempotent;
* changed bytes make a new state that keeps ``first_seen_at`` and lists the earlier hash in
  ``replaced_sha256``; the document SHA-256 is a line of the evidence text, so changed bytes
  always yield a new evidence version while the earlier one stays;
* a 429 or 503 stops the stage at once and stores ``not_before`` (Retry-After, else one hour) in
  the check index; until it passes the stage makes no request;
* permanent failures are remembered with validators and hash and not retried until the bytes
  change; environment failures retry three times, then rest seven days;
* a document that was listed but not read in this run (budget, deadline, rate limit, failure) is
  left out of this run's records rather than stored as an empty record; the report names why and
  the next run asks again;
* no response content or exception text is ever stored; only codes and small integers.

State per document lives in ``Evidence.provenance["early_signal"]`` and the check index in
``Source.health["early_signal"]``, so a re-check never changes an evidence hash.
"""

from __future__ import annotations

import copy
import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from gridlens.ingestion.adapters import tceq_application_documents as shared
from gridlens.ingestion.adapters.early_signal_http import EarlyFetcher
from gridlens.ingestion.adapters.tceq_application_documents import (
    DocumentFailure,
    Pacer,
    StageReport,
)

VERSION = "early-signal-v1"
STAGE = "early_signal"
STATE_KEY = "early_signal"
HEALTH_KEY = "early_signal"
MAX_INDEX_ENTRIES = 600
MAX_CHECKS_PER_RUN = 60
MAX_DOWNLOADS_PER_RUN = 12
MAX_SEED_URLS = 20
MIN_EXTRACT_SECONDS = 30
MAX_EXTRACT_SECONDS = 600
DEFAULT_REST_SECONDS = 3600
RETRY_ATTEMPTS = shared.RETRY_ATTEMPTS
RETRY_BACKOFF_DAYS = shared.RETRY_BACKOFF_DAYS
RECHECK_FAILED_DAYS = 7
NOTICE_CODES = frozenset({"zero_fields_extracted", "listing_shrink"})
HEAVY_RESERVE_SECONDS = 60.0


class EarlyStageReport(StageReport):
    """Stage report plus the check index to persist."""

    def __init__(self) -> None:
        super().__init__()
        self.index: dict[str, Any] = {}

    def reject(self, project: str, code: str, **raw: int | str) -> None:
        values = {name: str(value)[:40] for name, value in raw.items()}
        notice = code in NOTICE_CODES
        self.bump(f"notice_{code}" if notice else f"failure_{code}")
        target = self.notices if notice else self.rejections
        if len(target) < 50:
            target.append(
                {
                    "identity": f"EARLY-DOC-{project}",
                    "stage": STAGE,
                    "error_code": code,
                    "selected_fields": sorted(values),
                    "omitted_fields": [],
                    "raw": values,
                }
            )


class StageAbort(Exception):
    """The publisher rate-limited the stage: stop making requests this run."""


class StageDeadline(Exception):
    """The stage ran out of its own time: keep what is done and stop for this run."""


@dataclass(frozen=True, slots=True)
class StageConfig:
    max_downloads: int
    max_checks: int
    extract_seconds: float
    seed_urls: tuple[str, ...] = ()
    isolate: bool = True


def valid_config(raw: Any, seed_ok: Callable[[Any], bool] | None = None) -> bool:
    """The registry ``query.documents`` object."""
    if not isinstance(raw, dict) or set(raw) != {
        "enabled",
        "max_downloads",
        "max_checks",
        "extract_seconds",
        "seed_urls",
    }:
        return False
    seeds = raw["seed_urls"]
    return (
        type(raw["enabled"]) is bool
        and type(raw["max_downloads"]) is int
        and 1 <= raw["max_downloads"] <= MAX_DOWNLOADS_PER_RUN
        and type(raw["max_checks"]) is int
        and 1 <= raw["max_checks"] <= MAX_CHECKS_PER_RUN
        and type(raw["extract_seconds"]) is int
        and MIN_EXTRACT_SECONDS <= raw["extract_seconds"] <= MAX_EXTRACT_SECONDS
        and isinstance(seeds, list)
        and len(seeds) <= MAX_SEED_URLS
        and len(set(seeds)) == len(seeds)
        and (not seeds or (seed_ok is not None and all(seed_ok(url) for url in seeds)))
    )


def config_from(raw: Any) -> StageConfig | None:
    if not isinstance(raw, dict) or raw.get("enabled") is not True:
        return None
    return StageConfig(
        max_downloads=raw["max_downloads"],
        max_checks=raw["max_checks"],
        extract_seconds=float(raw["extract_seconds"]),
        seed_urls=tuple(raw["seed_urls"]),
    )


# --------------------------------------------------------------------------- state


def iso(moment: datetime) -> str:
    return moment.isoformat()


def parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def ident(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def state_digest(state: dict[str, Any]) -> str:
    """Content digest that ignores fetch times, so a re-run is idempotent."""
    copy_ = json.loads(json.dumps(state, default=str))
    document = copy_.get("document")
    if isinstance(document, dict):
        document.pop("fetched_at", None)
        document.pop("validators", None)
    copy_.pop("first_seen_at", None)
    return hashlib.sha256(
        json.dumps(copy_, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def build_state(
    prior: dict[str, Any] | None,
    *,
    item: DocItem,
    sha256: str,
    size: int,
    validators: dict[str, Any],
    extraction: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    base = copy.deepcopy(prior) if prior else {}
    old = (base.get("document") or {}).get("sha256")
    replaced = list(((base.get("document") or {}).get("replaced_sha256")) or [])
    if old and old != sha256:
        replaced = [*replaced, old][-5:]
    base.update(
        {
            "version": VERSION,
            "kind": item.kind,
            "key": item.key,
            "url": item.url,
            "stateful": True,
            "published_at": item.meta.get("published_at"),
            # Never rewritten once set.
            "first_seen_at": base.get("first_seen_at") or iso(now),
            "document": {
                "sha256": sha256,
                "size": size,
                "validators": validators,
                "fetched_at": iso(now),
                "replaced_sha256": replaced,
                "extraction": extraction,
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
    document = state.get("document") or {}
    lines = list((document.get("extraction") or {}).get("summary_lines") or [])
    abstract = base["abstract"] or ""
    if lines:
        abstract = f"{abstract}\n" + "\n".join(lines)
    # The document hash is part of the evidence text, so changed bytes always produce a new
    # evidence version (the generic content hash covers title, abstract, date and URL only).
    if document.get("sha256"):
        abstract = f"{abstract}\nSource document SHA-256: {document['sha256']}"
    record["_document_base"] = base
    record[STATE_KEY] = copy.deepcopy(state)
    record["abstract"] = abstract
    record["source_hash"] = hashlib.sha256(
        f"{base['source_hash']}:{state_digest(state)}".encode()
    ).hexdigest()


# --------------------------------------------------------------------------- runner


@dataclass(frozen=True, slots=True)
class DocItem:
    key: str  # state key: the document URL for ERCOT, the control number for PUCT
    url: str
    kind: str
    max_bytes: int
    media_types: frozenset[str]
    recheck_hours: float  # minimum age of the last check before the document is asked again
    meta: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)


# extractor(body, item, prior_extraction, budget_seconds, isolate) -> extraction dict
Extractor = Callable[[bytes, DocItem, "dict[str, Any] | None", float, bool], dict[str, Any]]


@dataclass(slots=True)
class Run:
    fetcher: EarlyFetcher
    config: StageConfig
    stage_deadline: float | None
    now: datetime
    report: EarlyStageReport
    urls: dict[str, dict[str, Any]]
    states: dict[str, dict[str, Any]]
    extractors: dict[str, Extractor]
    downloads: int = 0

    def left(self) -> float:
        if self.stage_deadline is None:
            return float("inf")
        return self.stage_deadline - time.monotonic()


def make_run(
    *,
    client: httpx.Client,
    pacer: Callable[[], None],
    policy: Callable[[str], bool],
    config: StageConfig,
    deadline: float | None,
    record_count: int,
    index: dict[str, Any] | None,
    states: dict[str, dict[str, Any]],
    extractors: dict[str, Extractor],
    now: datetime,
) -> Run:
    stored = (index or {}).get("urls") or {}
    urls = {str(k): dict(v) for k, v in stored.items() if isinstance(v, dict)}
    return Run(
        fetcher=EarlyFetcher(client, pacer, policy),
        config=config,
        stage_deadline=None
        if deadline is None
        else deadline - shared.persist_reserve(record_count),
        now=now,
        report=EarlyStageReport(),
        urls=urls,
        states={k: copy.deepcopy(v) for k, v in states.items()},
        extractors=extractors,
    )


def new_client() -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(
            connect=15.0, read=shared.HTTP_READ_TIMEOUT_SECONDS, write=30.0, pool=15.0
        ),
        follow_redirects=False,
        trust_env=False,
    )


def default_pacer() -> Callable[[], None]:
    return Pacer()


def _write(run: Run, key: str, **fields: Any) -> dict[str, Any]:
    entry = {**fields, "at": iso(run.now)}
    run.urls[key] = entry
    return entry


def _note_rate_limit(report: EarlyStageReport, key: str, failure: DocumentFailure) -> None:
    report.reject(ident(key), failure.code)
    report.bump("aborted_rate_limited")
    if failure.retry_after is not None:
        report.retry_after_seconds = max(report.retry_after_seconds or 0, failure.retry_after)


def _failed_due(run: Run, entry: dict[str, Any]) -> bool:
    at = parse_time(entry.get("at"))
    return at is None or run.now - at >= timedelta(days=RECHECK_FAILED_DAYS)


def due(run: Run, item: DocItem) -> bool:
    """Whether the document is asked again this run (never-seen, unfinished, or old enough)."""
    entry = run.urls.get(item.key)
    if entry is None:
        return True
    if item.key in run.states:
        at = parse_time(entry.get("at"))
        return at is None or run.now - at >= timedelta(hours=item.recheck_hours)
    if entry.get("status") in {"failed", "absent"}:
        return _failed_due(run, entry)
    return True


def order(run: Run, items: list[DocItem]) -> list[DocItem]:
    """Never-seen first (as listed), then unfinished, then oldest re-validation."""
    fresh = [i for i in items if i.key not in run.urls and i.key not in run.states]
    unfinished = [
        i
        for i in items
        if i.key in run.urls
        and i.key not in run.states
        and run.urls[i.key].get("status") != "absent"
    ]
    rest = [i for i in items if i.key in run.states]
    unfinished.sort(key=lambda i: str(run.urls[i.key].get("at") or ""))
    rest.sort(key=lambda i: str(run.urls.get(i.key, {}).get("at") or ""))
    return [*fresh, *unfinished, *rest]


def run_documents(run: Run, items: list[DocItem]) -> None:
    """Examine documents in priority order within the check, download and time budgets."""
    report = run.report
    checked = 0
    try:
        for item in order(run, items):
            if not due(run, item):
                failed = (run.urls.get(item.key) or {}).get("status") == "failed"
                report.bump("known_failed" if failed else "fresh_skipped")
                continue
            if (
                checked >= run.config.max_checks
                or run.left() < shared.HTTP_READ_TIMEOUT_SECONDS + 10
            ):
                report.bump("deferred_check_budget")
                break
            checked += 1
            try:
                _examine(run, item)
            except (TimeoutError, StageDeadline):
                report.bump("deferred_deadline")
                break
    except StageAbort:
        pass


def _examine(run: Run, item: DocItem) -> None:
    report = run.report
    report.bump("checked")
    entry = run.urls.get(item.key) or {}
    state = run.states.get(item.key)
    document = (state or {}).get("document") or {}
    retry = entry.get("retry") or {}
    if retry.get("attempts", 0) >= RETRY_ATTEMPTS:
        rested = parse_time(retry.get("at"))
        if rested is not None and run.now < rested + timedelta(days=RETRY_BACKOFF_DAYS):
            report.bump("backed_off")
            return
    if run.downloads >= run.config.max_downloads:
        report.bump("deferred_download_budget")
        if item.key not in run.urls:
            _write(run, item.key, status="pending")
        return
    known = document.get("validators") if document else entry.get("validators")
    try:
        run.downloads += 1
        fetched = run.fetcher.get(
            item.url,
            max_bytes=item.max_bytes,
            media_types=item.media_types,
            known=known if isinstance(known, dict) else None,
        )
    except DocumentFailure as failure:
        _on_failure(run, item, entry, failure, None)
        return
    if fetched.status == 304 and state is not None:
        report.bump("unchanged")
        run.urls[item.key] = {**entry, "status": "document", "at": iso(run.now)}
        run.urls[item.key].pop("retry", None)
        return
    if fetched.status == 304 or fetched.sha256 is None:
        report.reject(ident(item.key), "unexpected_not_modified")
        return
    if state is not None and document.get("sha256") == fetched.sha256:
        report.bump("unchanged_by_hash")
        run.urls[item.key] = {
            "status": "document",
            "sha256": fetched.sha256,
            "validators": fetched.validators,
            "at": iso(run.now),
        }
        return
    if entry.get("status") == "failed" and entry.get("sha256") == fetched.sha256:
        report.bump("known_failed")
        run.urls[item.key] = {**entry, "at": iso(run.now)}
        return
    budget = min(
        run.config.extract_seconds,
        run.left() - shared.STAGE_MARGIN_SECONDS - shared.CHILD_GRACE_SECONDS,
    )
    if budget < shared.MIN_EXTRACT_SECONDS:
        report.bump("deferred_deadline")
        _write(run, item.key, status="pending", validators=fetched.validators)
        raise StageDeadline
    try:
        extraction = run.extractors[item.kind](
            fetched.body,
            item,
            (state or {}).get("document", {}).get("extraction"),
            budget,
            run.config.isolate,
        )
    except DocumentFailure as failure:
        failure.budget_limited = budget < run.config.extract_seconds
        _on_failure(run, item, entry, failure, fetched)
        return
    if extraction.get("fields_found", 1) == 0:
        report.reject(ident(item.key), "zero_fields_extracted")
    run.states[item.key] = build_state(
        state,
        item=item,
        sha256=fetched.sha256,
        size=len(fetched.body),
        validators=fetched.validators,
        extraction=extraction,
        now=run.now,
    )
    _write(run, item.key, status="document", sha256=fetched.sha256, validators=fetched.validators)
    report.bump("updated" if state else "new")


def _on_failure(
    run: Run, item: DocItem, entry: dict[str, Any], failure: DocumentFailure, fetched: Any
) -> None:
    report = run.report
    if failure.rate_limited:
        _note_rate_limit(report, item.key, failure)
        raise StageAbort from failure
    if failure.code == "http_status_404":
        report.bump("absent")
        _write(run, item.key, status="absent")
        return
    report.reject(ident(item.key), failure.code)
    sha = fetched.sha256 if fetched is not None else None
    validators = fetched.validators if fetched is not None else failure.validators
    if failure.retryable:
        counted = 0 if failure.budget_limited else 1
        current = dict(entry.get("retry") or {})
        fields = {k: v for k, v in entry.items() if k not in {"retry", "at"}}
        fields.setdefault("status", "pending")
        run.urls[item.key] = {
            **fields,
            "at": iso(run.now),
            "retry": {
                "code": failure.code,
                "attempts": int(current.get("attempts", 0)) + counted,
                "at": iso(run.now),
            },
        }
        return
    if entry.get("status") == "document":
        run.urls[item.key] = {
            **entry,
            "last_failure": {"code": failure.code, "sha256": sha},
            "at": iso(run.now),
        }
        return
    _write(run, item.key, status="failed", code=failure.code, sha256=sha, validators=validators)


def finish(run: Run, stored_index: dict[str, Any] | None) -> EarlyStageReport:
    """Persist-ready report: the check index and, after a 429/503 or while resting, not_before."""
    report = run.report
    report.counts["downloads"] = run.downloads
    report.counts["requests"] = run.fetcher.requests
    keep = dict(sorted(run.urls.items(), key=lambda kv: str(kv[1].get("at") or ""), reverse=True))
    index: dict[str, Any] = {"urls": dict(list(keep.items())[:MAX_INDEX_ENTRIES])}
    resting = parse_time((stored_index or {}).get("not_before"))
    if resting is not None and run.now < resting:
        index["not_before"] = iso(resting)
    elif report.counts.get("aborted_rate_limited"):
        index["not_before"] = iso(
            run.now + timedelta(seconds=report.retry_after_seconds or DEFAULT_REST_SECONDS)
        )
    report.index = index
    return report


def resting(index: dict[str, Any] | None, now: datetime) -> bool:
    until = parse_time((index or {}).get("not_before"))
    return until is not None and now < until
