"""Shared, polite, bounded helpers for the sector and regulation sources (workstream 5).

Every source here ships off. Requests go through ``read_public_response`` (exact https host
allowlist, no redirects, byte cap, media-type allowlist, bounded retry) with a pacer that keeps
the run at no more than one request per second. A 429 or 503 whose ``Retry-After`` is longer than
the short retry bound surfaces as ``httpx.HTTPStatusError`` so the worker's diagnostics store the
rest period; nothing here retries it again.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Collection
from datetime import date
from typing import Any
from urllib.parse import urlsplit

import httpx

from gridlens.ingestion.adapters import tceq_http
from gridlens.ingestion.adapters.acquisition_runtime import remaining_seconds
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.public_source_http import USER_AGENT, read_public_response

MIN_REQUEST_INTERVAL_SECONDS = 1.0
MAX_TEXT = 400


class Pacer:
    """At most one request per ``interval`` seconds across one run."""

    def __init__(
        self,
        interval: float = MIN_REQUEST_INTERVAL_SECONDS,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        deadline: float | None = None,
    ) -> None:
        self.interval = interval
        self.deadline = deadline
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None
        self.requests = 0

    def wait(self) -> None:
        remaining_seconds(self.deadline)  # TimeoutError once the job deadline has passed
        now = self._clock()
        if self._last is not None:
            remaining = self.interval - (now - self._last)
            if remaining > 0:
                self._sleep(remaining)
                now = self._clock()
        self._last = now
        self.requests += 1


def fetch(
    client: httpx.Client,
    url: str,
    *,
    hosts: Collection[str],
    max_bytes: int,
    media_types: set[str],
    pacer: Pacer,
    headers: dict[str, str] | None = None,
) -> tuple[httpx.Headers, bytes]:
    """One paced, host-allowlisted, redirect-free, size-capped GET.

    The host must resolve only to public (global) addresses immediately before the request; a
    private, loopback or link-local answer is refused. A single attempt is made: a 429 or 503
    surfaces at once so the worker's diagnostics store its ``Retry-After`` instead of this
    helper retrying inside the one-request-per-second budget.
    """
    host = urlsplit(url).hostname or ""
    if host not in {h.casefold().rstrip(".") for h in hosts}:
        raise SourceParseError("Public source host is not allowed")
    resolve_public(host)
    pacer.wait()
    return read_public_response(
        client,
        url,
        max_bytes=max_bytes,
        allowed_media_types=media_types,
        allowed_hosts=hosts,
        headers=headers,
        attempts=1,
    )


def resolve_public(host: str) -> str:
    """Refuse a host whose DNS answer includes any non-global address (SSRF guard)."""
    return tceq_http._public_ip(host)


def new_client() -> httpx.Client:
    return httpx.Client(timeout=60, follow_redirects=False, trust_env=False)


def semantic_hash(value: Any) -> str:
    """Stable hash of the fields that carry meaning; fetch times and file dates are excluded."""
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def clean(value: Any, limit: int = MAX_TEXT) -> str | None:
    """Control characters removed, whitespace collapsed, length capped; empty becomes None."""
    if value is None:
        return None
    text = "".join(ch if ch.isprintable() else " " for ch in str(value))
    text = " ".join(text.split())[:limit]
    return text or None


def iso_date(value: Any) -> str | None:
    """A date from ``YYYY-MM-DD`` (a trailing time is ignored); anything else is unknown."""
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError:
        return None


def number(value: Any) -> float | None:
    """A finite number, or None. Blank and malformed values stay unknown, never zero."""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(str(value).replace(",", "").strip())
    except ValueError:
        return None
    return result if result == result and abs(result) != float("inf") else None


def candidate_record(
    *,
    source_id: str,
    row_id: str,
    title: str,
    abstract_lines: list[str],
    url: str,
    extraction_location: str,
    semantic: dict[str, Any],
    permit: dict[str, Any],
    publication_date: str | None = None,
    event_date: str | None = None,
    event_date_label: str | None = None,
) -> dict[str, Any]:
    """The record shape the ingestion service already consumes for evidence-only sources.

    ``data_center`` is always false and no power-signal tag is set: these sources describe
    proximity, registration, award or aggregate facts, never a demand claim.
    """
    body = {
        "source_type": source_id,
        "row_id": row_id,
        "applicant": None,
        "facility": None,
        "permit_numbers": [row_id],
        "status": None,
        "description": title,
        "location": None,
        "state": None,
        "data_center": False,
        "power_signals": [],
        "document_links": {"source": url},
    }
    body.update(permit)
    body["source_type"] = source_id
    body["data_center"] = False
    body["power_signals"] = []
    return {
        "document_number": row_id,
        "title": title,
        "abstract": "\n".join(abstract_lines),
        "publication_date": publication_date,
        "event_date": event_date,
        "event_date_label": event_date_label,
        "html_url": url,
        "extraction_location": extraction_location,
        "source_hash": semantic_hash(semantic),
        "permit": body,
    }


def require_source(source: dict[str, Any], source_id: str, endpoint: str) -> dict[str, Any]:
    if source.get("id") != source_id or source.get("endpoint") != endpoint:
        raise SourceParseError(f"{source_id} source ID or endpoint is not configured")
    query = source.get("query")
    if not isinstance(query, dict):
        raise SourceParseError(f"{source_id} query is invalid")
    return query


__all__ = [
    "USER_AGENT",
    "Pacer",
    "candidate_record",
    "clean",
    "fetch",
    "iso_date",
    "new_client",
    "number",
    "require_source",
    "semantic_hash",
]
