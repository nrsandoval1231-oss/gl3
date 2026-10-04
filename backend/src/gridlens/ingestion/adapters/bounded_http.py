"""HTTP response limits shared by the public-source readers."""

from __future__ import annotations

import importlib
import multiprocessing
import time
from collections.abc import Iterator
from typing import Any

import httpx


class ResponseTooLarge(ValueError):
    pass


def _isolated_entry(connection, function_path: str, args: tuple, kwargs: dict) -> None:
    """Only acquisition code runs here; no database sessions or callbacks cross."""
    try:
        import resource

        # Public PDFs can contain compressed streams much larger than their wire
        # representation. Bound parser memory as well as time and input bytes.
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024**2, 512 * 1024**2))
        module, name = function_path.split(":", 1)
        result = getattr(importlib.import_module(module), name)(*args, **kwargs)
        connection.send((True, result))
    except BaseException as exc:
        # Exceptions contain no HTTP authorization headers in retained receipts.
        # Transport exceptions can reference unpicklable streams; use a safe
        # class/code representation instead of serializing the request object.
        import httpx

        error: BaseException
        if isinstance(exc, httpx.HTTPStatusError):
            error = AcquisitionFailure(f"http_status_{exc.response.status_code}")
        elif isinstance(exc, httpx.TimeoutException):
            error = TimeoutError("Acquisition transport timeout")
        elif isinstance(exc, httpx.RequestError):
            error = AcquisitionFailure("network_error")
        else:
            error = exc
        try:
            connection.send((False, error))
        except Exception:
            connection.send((False, AcquisitionFailure(type(exc).__name__)))
    finally:
        connection.close()


class AcquisitionFailure(ValueError):
    """Safe acquisition error code; never includes a credential-bearing request."""


def run_isolated(
    function_path: str, args: tuple, kwargs: dict, *, deadline: float
) -> Any:
    """Killable, single-operation boundary for synchronous DNS/HTTP and parsing.

    The caller persists its budget reservation before entering. Spawn avoids
    inheriting database connections; only a bounded result returns to the parent,
    where all canonical writes and lease checks occur. This is not a job runner.
    """
    remaining_seconds(deadline)
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_isolated_entry, args=(sender, function_path, args, kwargs), daemon=True
    )
    try:
        process.start()
        sender.close()
        remaining = remaining_seconds(deadline)
        if not receiver.poll(remaining):
            raise TimeoutError("Acquisition wall-clock deadline exhausted")
        try:
            success, result = receiver.recv()
        except EOFError as exc:
            raise AcquisitionFailure("acquisition_process_failed") from exc
        remaining_seconds(deadline)
        if not success:
            raise result
        return result
    finally:
        receiver.close()
        sender.close()
        if process.pid is not None:
            if process.is_alive():
                process.kill()
            process.join(timeout=0.2)
            if not process.is_alive():
                process.close()


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
