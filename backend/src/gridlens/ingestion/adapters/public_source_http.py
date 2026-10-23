"""Bounded public fetches for regional source adapters.

Timeouts come from the caller client. This helper adds a polite User-Agent,
per-request headers, a byte cap, a content-type allowlist, and a short retry
on retryable statuses. A 429 waits for Retry-After when that header is a
delta-seconds value or an HTTP-date, capped, and otherwise uses the backoff.
The request host and any redirect target must be an exact allowlist entry.
Redirects are not followed. The shared client header map is never mutated.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Collection
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit

import httpx

from gridlens.ingestion.adapters.federal_register import SourceParseError

USER_AGENT = "GridLens public source reader/1.0"
MAX_RETRY_AFTER_SECONDS = 60
_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
_DELTA_SECONDS = re.compile(r"[0-9]{1,10}")


def _exact_hosts(allowed_hosts: Collection[str]) -> set[str]:
    if not isinstance(allowed_hosts, Collection) or isinstance(allowed_hosts, str):
        raise SourceParseError("Public source host allowlist is invalid")
    exact: set[str] = set()
    for host in allowed_hosts:
        if not isinstance(host, str):
            raise SourceParseError("Public source host allowlist is invalid")
        normalized = host.strip().casefold().rstrip(".")
        if (
            not normalized
            or any(char in normalized for char in "/\\@:?# \t")
            or normalized.startswith(".")
            or ".." in normalized
        ):
            raise SourceParseError("Public source host allowlist is invalid")
        exact.add(normalized)
    if not exact:
        raise SourceParseError("Public source host allowlist is empty")
    return exact


def _require_allowed(url: str, allowed: set[str], *, redirect: bool) -> None:
    parts = urlsplit(url)
    host = (parts.hostname or "").casefold().rstrip(".")
    if (
        parts.scheme != "https"
        or not host
        or host not in allowed
        or parts.username is not None
        or parts.password is not None
        or parts.port not in (None, 443)
    ):
        message = (
            "Public source redirect host is not allowed"
            if redirect
            else "Public source host is not allowed"
        )
        raise SourceParseError(message)


def _reject_redirect(request_url: str, response: httpx.Response, allowed: set[str]) -> None:
    location = response.headers.get("location", "").strip()
    if not location or location.startswith("//") or "\\" in location or "\n" in location:
        raise SourceParseError("Public source redirect host is not allowed")
    _require_allowed(urljoin(request_url, location), allowed, redirect=True)
    raise SourceParseError("Public source redirects are not followed")


def _retry_after_delay(header: str | None, *, now: datetime) -> float | None:
    if header is None:
        return None
    raw = header.strip()
    if not raw or len(raw) > 128:
        return None
    if _DELTA_SECONDS.fullmatch(raw):
        return float(min(int(raw), MAX_RETRY_AFTER_SECONDS))
    try:
        retry_at = parsedate_to_datetime(raw)
    except (TypeError, ValueError, OverflowError, IndexError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    delay = max(0.0, (retry_at - now).total_seconds())
    return min(delay, float(MAX_RETRY_AFTER_SECONDS))


def read_public_response(
    client: httpx.Client,
    url: str,
    *,
    max_bytes: int,
    allowed_media_types: set[str],
    allowed_hosts: Collection[str],
    method: str = "GET",
    content: bytes | None = None,
    headers: dict[str, str] | None = None,
    attempts: int = 3,
    backoff_seconds: float = 0.4,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] | None = None,
) -> tuple[httpx.Headers, bytes]:
    """Read one allowlisted response or fail closed."""
    if client.follow_redirects:
        raise SourceParseError("Public source client must not automatically follow redirects")
    if method not in {"GET", "POST"}:
        raise SourceParseError("Public source method is not allowed")
    if attempts < 1 or attempts > 4:
        raise SourceParseError("Public source retry bound is invalid")
    if max_bytes < 1:
        raise SourceParseError("Public source byte bound is invalid")
    allowed = _exact_hosts(allowed_hosts)
    _require_allowed(url, allowed, redirect=False)
    clock = now or (lambda: datetime.now(UTC))
    request_headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if headers:
        request_headers.update(headers)
    last_status: int | None = None
    for attempt in range(attempts):
        try:
            with client.stream(
                method,
                url,
                content=content,
                headers=request_headers,
                follow_redirects=False,
            ) as response:
                if 300 <= response.status_code < 400:
                    _reject_redirect(url, response, allowed)
                if response.status_code in _RETRYABLE_STATUS and attempt + 1 < attempts:
                    last_status = response.status_code
                    delay = backoff_seconds * (2**attempt)
                    if response.status_code == 429:
                        honored = _retry_after_delay(
                            response.headers.get("retry-after"), now=clock()
                        )
                        if honored is not None:
                            delay = honored
                    response.read()
                    sleep(delay)
                    continue
                response.raise_for_status()
                raw_type = response.headers.get("content-type", "")
                media_type = raw_type.split(";", 1)[0].strip().lower()
                if media_type not in allowed_media_types:
                    raise SourceParseError("Public source response has an unexpected media type")
                declared = response.headers.get("content-length")
                if declared:
                    try:
                        declared_size = int(declared)
                    except ValueError as exc:
                        raise SourceParseError("Public source Content-Length is malformed") from exc
                    if declared_size > max_bytes:
                        raise SourceParseError("Public source response exceeds its byte limit")
                parts: list[bytes] = []
                size = 0
                for part in response.iter_bytes():
                    size += len(part)
                    if size > max_bytes:
                        raise SourceParseError("Public source response exceeds its byte limit")
                    parts.append(part)
                return response.headers, b"".join(parts)
        except httpx.TransportError:
            if attempt + 1 >= attempts:
                raise
            sleep(backoff_seconds * (2**attempt))
    raise SourceParseError(
        "Public source response was not readable"
        if last_status is None
        else f"Public source response was not readable after HTTP {last_status}"
    )
