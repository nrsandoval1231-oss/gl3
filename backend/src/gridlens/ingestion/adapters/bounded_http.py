"""HTTP response limits shared by the public-source readers."""

from __future__ import annotations

import ctypes
import importlib
import multiprocessing
import os
import time
from collections.abc import Iterator
from typing import Any, Literal, overload

import httpx


class ResponseTooLarge(ValueError):
    pass


class _JobBasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _JobIoCounters(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_ulonglong)
        for name in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class _JobExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JobBasicLimitInformation),
        ("IoInfo", _JobIoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


_WINDOWS_JOB_LIMIT = 0x100
_WINDOWS_JOB_EXTENDED_LIMIT_INFORMATION = 9
_ACQUISITION_MEMORY_LIMIT = 512 * 1024**2
_windows_job_handle: int | None = None


def _configure_memory_limit() -> None:
    """Install the hard memory bound before any acquisition module is loaded."""
    if os.name == "nt":
        _install_windows_memory_limit()
        return
    try:
        resource = importlib.import_module("resource")
    except ImportError as exc:
        raise AcquisitionFailure("resource_limits_unavailable") from exc
    resource.setrlimit(
        resource.RLIMIT_AS, (_ACQUISITION_MEMORY_LIMIT, _ACQUISITION_MEMORY_LIMIT)
    )


def _install_windows_memory_limit() -> None:
    """Assign this child to a Job Object capped at 512 MiB of process commit."""
    global _windows_job_handle
    loader = getattr(ctypes, "WinDLL", None)
    if loader is None:
        raise AcquisitionFailure("windows_job_api_unavailable")
    try:
        kernel32 = loader("kernel32", use_last_error=True)
    except OSError as exc:
        raise AcquisitionFailure("windows_job_api_unavailable") from exc

    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    kernel32.CreateJobObjectW.restype = ctypes.c_void_p
    handle = kernel32.CreateJobObjectW(None, None)
    if not handle:
        raise AcquisitionFailure("windows_job_create_failed")

    information = _JobExtendedLimitInformation()
    information.BasicLimitInformation.LimitFlags = _WINDOWS_JOB_LIMIT
    information.ProcessMemoryLimit = _ACQUISITION_MEMORY_LIMIT
    kernel32.SetInformationJobObject.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    kernel32.SetInformationJobObject.restype = ctypes.c_int
    if not kernel32.SetInformationJobObject(
        handle,
        _WINDOWS_JOB_EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(information),
        ctypes.sizeof(information),
    ):
        raise AcquisitionFailure("windows_job_limit_setup_failed")

    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    kernel32.AssignProcessToJobObject.restype = ctypes.c_int
    process = kernel32.GetCurrentProcess()
    if not process:
        raise AcquisitionFailure("windows_current_process_failed")
    if not kernel32.AssignProcessToJobObject(handle, process):
        raise AcquisitionFailure("windows_job_assignment_failed")

    # Keep the handle alive through the acquisition and pipe send. The child
    # process closes it automatically when it exits.
    _windows_job_handle = handle


def _query_windows_job_memory_limit() -> int:
    """Read the active child Job Object cap; used by the Windows regression."""
    if not _windows_job_handle:
        raise AcquisitionFailure("windows_job_handle_missing")
    loader = getattr(ctypes, "WinDLL", None)
    if loader is None:
        raise AcquisitionFailure("windows_job_api_unavailable")
    kernel32 = loader("kernel32", use_last_error=True)
    kernel32.QueryInformationJobObject.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    kernel32.QueryInformationJobObject.restype = ctypes.c_int
    information = _JobExtendedLimitInformation()
    returned = ctypes.c_uint32()
    if not kernel32.QueryInformationJobObject(
        _windows_job_handle,
        _WINDOWS_JOB_EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(information),
        ctypes.sizeof(information),
        ctypes.byref(returned),
    ):
        raise AcquisitionFailure("windows_job_limit_query_failed")
    return information.ProcessMemoryLimit


def _isolated_entry(connection, function_path: str, args: tuple, kwargs: dict) -> None:
    """Only acquisition code runs here; no database sessions or callbacks cross."""
    try:
        _configure_memory_limit()
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


@overload
def read_bounded_response(
    client: httpx.Client,
    url: str,
    max_bytes: int,
    params: dict[str, str | int] | None = None,
    *,
    extensions: dict | None = None,
    deadline: float | None = None,
    allow_not_modified: Literal[False] = False,
) -> tuple[httpx.Headers, bytes]: ...


@overload
def read_bounded_response(
    client: httpx.Client,
    url: str,
    max_bytes: int,
    params: dict[str, str | int] | None = None,
    *,
    extensions: dict | None = None,
    deadline: float | None = None,
    allow_not_modified: Literal[True],
) -> tuple[httpx.Headers, bytes, int]: ...


def read_bounded_response(
    client: httpx.Client,
    url: str,
    max_bytes: int,
    params: dict[str, str | int] | None = None,
    *,
    extensions: dict | None = None,
    deadline: float | None = None,
    allow_not_modified: bool = False,
) -> tuple[httpx.Headers, bytes] | tuple[httpx.Headers, bytes, int]:
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
        if allow_not_modified and response.status_code == 304:
            return response.headers, b"", 304
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
        body = b"".join(parts)
        if allow_not_modified:
            return response.headers, body, response.status_code
        return response.headers, body
