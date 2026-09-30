"""HTTP response limits shared by the public-source readers."""

from __future__ import annotations

import time
from collections.abc import Iterator

import httpx


class ResponseTooLarge(ValueError):
    pass


def remaining_seconds(deadline: float | None) -> float | None:
    """Check an absolute monotonic deadline shared by a whole research pass."""
    if deadline is None:
        return None
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Public-source research deadline exhausted")
    return remaining


def _clamp_timeouts(timeouts: dict, remaining: float) -> dict:
    return {
        phase: remaining if timeout is None else min(timeout, remaining)
        for phase, timeout in timeouts.items()
    }


class _DeadlineStream(httpx.SyncByteStream):
    """Check every raw chunk, even when decompression yields no decoded bytes."""

    def __init__(self, stream: httpx.SyncByteStream, deadline: float):
        self.stream = stream
        self.deadline = deadline

    def __iter__(self) -> Iterator[bytes]:
        chunks = iter(self.stream)
        while True:
            remaining_seconds(self.deadline)
            try:
                chunk = next(chunks)
            except StopIteration:
                remaining_seconds(self.deadline)
                return
            remaining_seconds(self.deadline)
            yield chunk

    def close(self) -> None:
        self.stream.close()


def read_bounded_response(
    client: httpx.Client,
    url: str,
    max_bytes: int,
    params: dict[str, str | int] | None = None,
    *,
    extensions: dict | None = None,
    deadline: float | None = None,
) -> tuple[httpx.Headers, bytes]:
    """Read within byte limits and, optionally, a shared monotonic deadline.

    The deadline is cooperative: HTTPX's synchronous transport cannot preempt
    an in-progress phase. Clamp its per-operation timeouts at request/body
    boundaries, and check each raw body chunk so slow drips cannot keep the
    response alive indefinitely by repeatedly resetting the idle timeout.
    """
    remaining = remaining_seconds(deadline)
    if remaining is not None:
        extensions = dict(extensions or {})
        timeouts = client.timeout.as_dict() | extensions.get("timeout", {})
        extensions["timeout"] = _clamp_timeouts(timeouts, remaining)
    with client.stream("GET", url, params=params, extensions=extensions) as response:
        remaining = remaining_seconds(deadline)
        if remaining is not None:
            # HTTPX/httpcore reads the body timeout when iteration starts. Keep
            # it within the budget left after connecting/receiving headers.
            timeouts = response.request.extensions["timeout"]
            response.request.extensions["timeout"] = _clamp_timeouts(timeouts, remaining)
            assert deadline is not None
            assert isinstance(response.stream, httpx.SyncByteStream)
            response.stream = _DeadlineStream(response.stream, deadline)
        response.raise_for_status()
        declared = response.headers.get("content-length")
        if declared:
            try:
                declared_size = int(declared)
            except ValueError as exc:
                raise ResponseTooLarge("Response Content-Length is malformed") from exc
            if declared_size > max_bytes:
                raise ResponseTooLarge(f"Response Content-Length exceeds {max_bytes} bytes")
        parts: list[bytes] = []
        size = 0
        for part in response.iter_bytes():
            remaining_seconds(deadline)
            size += len(part)
            if size > max_bytes:
                raise ResponseTooLarge(f"Response exceeds {max_bytes} bytes")
            parts.append(part)
        remaining_seconds(deadline)
        return response.headers, b"".join(parts)
