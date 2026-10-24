"""HTTP response limits shared by the public-source readers."""

from __future__ import annotations

import ctypes
import importlib
import multiprocessing
import os
import pickle
from collections.abc import Iterator
from threading import Thread
from typing import Any, Literal, overload

import httpx

from gridlens.ingestion.adapters.acquisition_runtime import remaining_seconds


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
MAX_ISOLATED_RESULT_BYTES = 8 * 1024**2
_RRC_DRILLING_RESULT_BYTES = 64 * 1024**2
_RRC_DRILLING_SOURCE_ID = "texas-rrc-drilling-permits"
_RRC_DRILLING_METHOD = "rrc-drilling-permits"
_windows_job_handle: int | None = None


def _isolated_result_limit(function_path: str, args: tuple) -> int:
    """Select the fixed IPC bound for the one reviewed large-result source."""
    if (
        function_path == "gridlens.ingestion.adapters:_retrieve_source_direct"
        and args
        and isinstance(args[0], dict)
        and args[0].get("id") == _RRC_DRILLING_SOURCE_ID
        and args[0].get("retrieval_method") == _RRC_DRILLING_METHOD
    ):
        return _RRC_DRILLING_RESULT_BYTES
    return MAX_ISOLATED_RESULT_BYTES


def _configure_memory_limit() -> None:
    """Install the hard memory bound before any acquisition module is loaded."""
    if os.name == "nt":
        _install_windows_memory_limit()
        return
    try:
        resource = importlib.import_module("resource")
    except ImportError as exc:
        raise AcquisitionFailure("resource_limits_unavailable") from exc
    resource.setrlimit(resource.RLIMIT_AS, (_ACQUISITION_MEMORY_LIMIT, _ACQUISITION_MEMORY_LIMIT))


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
        _send_bounded_result(connection, True, result, function_path=function_path, args=args)
    except BaseException as exc:
        # Exceptions contain no HTTP authorization headers in retained receipts.
        # Transport exceptions can reference unpicklable streams; use a safe
        # class/code representation instead of serializing the request object.
        _send_bounded_result(
            connection,
            False,
            _safe_acquisition_error(exc),
            function_path=function_path,
            args=args,
        )
    finally:
        connection.close()


class AcquisitionFailure(ValueError):
    """Safe acquisition error code; never includes a credential-bearing request."""


def _safe_acquisition_error(exc: BaseException) -> BaseException:
    from gridlens.ingestion.adapters.diagnostics import (
        acquisition_diagnostics,
        acquisition_error_message,
    )
    from gridlens.ingestion.adapters.federal_register import SourceParseError

    diagnostics = acquisition_diagnostics(exc)
    safe = _redacted_acquisition_error(exc)
    if isinstance(safe, SourceParseError):
        safe.args = (acquisition_error_message(exc),)
    elif isinstance(safe, AcquisitionFailure):
        safe.args = (str(diagnostics["error_code"]),)
    safe.acquisition_code = diagnostics["error_code"]  # type: ignore[attr-defined]
    if "error_stage" in diagnostics:
        safe.acquisition_stage = diagnostics["error_stage"]  # type: ignore[attr-defined]
    if type(diagnostics.get("retry_after_seconds")) is int:
        safe.acquisition_retry_after_seconds = diagnostics["retry_after_seconds"]  # type: ignore[attr-defined]
    if diagnostics.get("retry_after_exceeds_bound") == 1:
        safe.acquisition_retry_after_exceeds_bound = True  # type: ignore[attr-defined]
    return safe


def _redacted_acquisition_error(exc: BaseException) -> BaseException:
    """Keep useful error classes while dropping potentially sensitive messages."""
    if isinstance(exc, httpx.HTTPStatusError):
        return AcquisitionFailure(f"http_status_{exc.response.status_code}")
    if isinstance(exc, httpx.TimeoutException | TimeoutError):
        return TimeoutError("Acquisition transport timeout")
    if isinstance(exc, httpx.RequestError):
        return AcquisitionFailure("network_error")
    if isinstance(exc, AcquisitionFailure):
        code = str(exc)
        if code and all(char.islower() or char.isdigit() or char == "_" for char in code):
            return AcquisitionFailure(code[:80])
        return AcquisitionFailure("acquisition_failed")
    if isinstance(exc, ResponseTooLarge):
        return ResponseTooLarge("Acquisition response exceeded its configured byte bound")
    try:
        from gridlens.ingestion.adapters.buying_chain_public import PublicExtractionUnavailable
        from gridlens.ingestion.adapters.federal_register import SourceParseError

        if isinstance(exc, PublicExtractionUnavailable):
            return PublicExtractionUnavailable("Public page requires configured extraction")
        if isinstance(exc, SourceParseError):
            return SourceParseError("Acquisition source response could not be parsed")
    except ImportError:
        pass
    return AcquisitionFailure(type(exc).__name__.casefold()[:80] or "acquisition_failed")


def _send_bounded_result(
    connection,
    success: bool,
    result: Any,
    *,
    function_path: str,
    args: tuple,
) -> None:
    result_limit = _isolated_result_limit(function_path, args)
    try:
        payload = pickle.dumps((success, result), protocol=5)
    except Exception:
        payload = pickle.dumps(
            (False, AcquisitionFailure("acquisition_result_not_serializable")), protocol=5
        )
    if len(payload) > result_limit:
        payload = pickle.dumps(
            (False, AcquisitionFailure("acquisition_result_too_large")), protocol=5
        )
    connection.send_bytes(payload)


def run_isolated(function_path: str, args: tuple, kwargs: dict, *, deadline: float) -> Any:
    """Killable, single-operation boundary for synchronous DNS/HTTP and parsing.

    The caller persists its budget reservation before entering. Spawn avoids
    inheriting database connections; only a bounded result returns to the parent,
    where all canonical writes and lease checks occur. This is not a job runner.
    """
    remaining = remaining_seconds(deadline)
    result_limit = _isolated_result_limit(function_path, args)
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_isolated_entry, args=(sender, function_path, args, kwargs), daemon=True
    )
    receiver_thread: Thread | None = None
    try:
        process.start()
        sender.close()
        receive_state: list[bytes | BaseException] = []

        def receive_bounded_message() -> None:
            try:
                receive_state.append(receiver.recv_bytes(result_limit))
            except BaseException as exc:
                receive_state.append(exc)

        receiver_thread = Thread(
            target=receive_bounded_message, name="gridlens-acquisition-ipc-receiver", daemon=True
        )
        receiver_thread.start()
        receiver_thread.join(remaining)
        if receiver_thread.is_alive():
            raise TimeoutError("Acquisition wall-clock deadline exhausted")
        if not receive_state:
            raise AcquisitionFailure("acquisition_process_failed")
        message = receive_state[0]
        if isinstance(message, BaseException):
            if isinstance(message, EOFError | OSError):
                raise AcquisitionFailure("acquisition_result_too_large_or_truncated") from None
            raise AcquisitionFailure("acquisition_process_failed") from None
        try:
            success, result = pickle.loads(message)
        except Exception as exc:
            raise AcquisitionFailure("acquisition_result_invalid") from exc
        remaining_seconds(deadline)
        if not success:
            raise result
        return result
    except EOFError as exc:
        raise AcquisitionFailure("acquisition_process_failed") from exc
    finally:
        receiver.close()
        sender.close()
        if process.pid is not None:
            if process.is_alive():
                process.kill()
            process.join(timeout=0.2)
            if not process.is_alive():
                process.close()
        if receiver_thread is not None and receiver_thread.is_alive():
            receiver_thread.join(timeout=0.2)


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
    headers: dict[str, str] | None = None,
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
    headers: dict[str, str] | None = None,
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
    headers: dict[str, str] | None = None,
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
    # Headers are per request. Mutating client.headers is not safe when the
    # same client is used concurrently (the TCEQ Host pin used to do that).
    with client.stream(
        "GET", url, params=params, headers=headers, extensions=extensions
    ) as response:
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
