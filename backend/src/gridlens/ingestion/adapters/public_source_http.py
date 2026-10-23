"""Bounded public fetches for regional source adapters.

Timeouts come from the caller client. This helper adds a polite User-Agent,
per-request headers, a byte cap, a content-type allowlist, and a short retry
on retryable statuses. Redirects are not followed. The shared client header
map is never mutated.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx

from gridlens.ingestion.adapters.federal_register import SourceParseError

USER_AGENT = "GridLens public source reader/1.0"
_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


def read_public_response(
    client: httpx.Client,
    url: str,
    *,
    max_bytes: int,
    allowed_media_types: set[str],
    method: str = "GET",
    content: bytes | None = None,
    headers: dict[str, str] | None = None,
    attempts: int = 3,
    backoff_seconds: float = 0.4,
    sleep: Callable[[float], None] = time.sleep,
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
                    raise SourceParseError("Public source redirects are not followed")
                if response.status_code in _RETRYABLE_STATUS and attempt + 1 < attempts:
                    last_status = response.status_code
                    response.read()
                    sleep(backoff_seconds * (2**attempt))
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
