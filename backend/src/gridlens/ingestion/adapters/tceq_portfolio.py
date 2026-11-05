"""Safe enumeration and extraction of PDF Portfolio attachments (untrusted input).

TCEQ application files are PDF Portfolios: a one-page cover that wraps embedded files (an
inner composite PDF, Excel workbooks, a read-me). The outer file and every embedded stream
are treated as hostile. Embedded names are only ever sanitised for display; files are written
under generated names inside one caller-supplied directory, never under a name taken from the
PDF. Nothing is executed or opened with an application. Unknown types are listed and ignored.

pypdf refuses declared streams over 75 MB by default. The bound here is explicit and no
higher than ``MAX_EMBEDDED_FILE_BYTES``; any stream above it is listed as oversize, not read.
"""

from __future__ import annotations

import hashlib
import importlib
import multiprocessing
import multiprocessing.connection
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

MAX_EMBEDDED_FILES = 64
MAX_EMBEDDED_FILE_BYTES = 128 * 1024 * 1024
MAX_TOTAL_EMBEDDED_BYTES = 512 * 1024 * 1024
UNPACK_SECONDS = 240.0
UNPACK_MEMORY_BYTES = 2 * 1024**3  # POSIX RLIMIT_AS for the child; Windows has none
_SPAWN_GRACE_SECONDS = 20.0
_MAX_NAME_CHARS = 120
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ ()+\-]")

# Embedded file statuses recorded in the manifest.
EXTRACTED = "extracted"
IGNORED = "ignored_type"
OVERSIZE = "skipped_oversize"
TOTAL_LIMIT = "skipped_total_limit"
COUNT_LIMIT = "skipped_count_limit"
UNREADABLE = "unreadable"


@dataclass(slots=True)
class EmbeddedFile:
    index: int
    name: str  # sanitised, display only
    name_changed: bool
    size: int | None
    sha256: str | None
    kind: str  # pdf | xlsx | other
    status: str
    path: str | None = None  # generated name inside the output directory
    detail: str | None = None


@dataclass(slots=True)
class PortfolioResult:
    files: list[EmbeddedFile]
    is_portfolio: bool
    failure: str | None = None  # typed code when the outer file cannot be read at all
    detail: str | None = None

    def manifest(self) -> list[dict[str, Any]]:
        """JSON-safe manifest without local paths."""
        return [
            {key: value for key, value in asdict(item).items() if key != "path"}
            for item in self.files
        ]


def sanitize_name(raw: object) -> tuple[str, bool]:
    """Display-safe last path component. Returns (name, changed)."""
    text = raw if isinstance(raw, str) else ""
    base = re.split(r"[\\/]", text)[-1]
    cleaned = _SAFE_NAME.sub("_", base).strip(" .")
    cleaned = re.sub(r"_{2,}", "_", cleaned)[:_MAX_NAME_CHARS] or "unnamed"
    return cleaned, cleaned != text


def _kind(name: str, head: bytes) -> str:
    lowered = name.lower()
    if head.startswith(b"%PDF-") and lowered.endswith(".pdf"):
        return "pdf"
    if head.startswith(b"PK\x03\x04") and lowered.endswith(".xlsx"):
        return "xlsx"
    return "other"


def _unpack(path: str, out_dir: str) -> PortfolioResult:
    from pypdf import PdfReader, apply_configuration
    from pypdf.errors import LimitReachedError, PdfReadError

    out = Path(out_dir)
    files: list[EmbeddedFile] = []
    total = 0
    with apply_configuration(
        maximum_declared_stream_length=MAX_EMBEDDED_FILE_BYTES,
        zlib_maximum_output_length=MAX_EMBEDDED_FILE_BYTES,
        array_based_stream_maximum_output_length=MAX_EMBEDDED_FILE_BYTES,
    ):
        try:
            # A file object, not a path: pypdf reads a path fully into memory.
            with open(path, "rb") as handle:
                reader = PdfReader(handle, strict=False)
                if reader.is_encrypted:
                    return PortfolioResult([], False, "encrypted", "outer PDF is encrypted")
                entries = reader.attachment_list
                for index, entry in enumerate(entries):
                    display, changed = sanitize_name(getattr(entry, "name", ""))
                    if index >= MAX_EMBEDDED_FILES:
                        files.append(
                            EmbeddedFile(index, display, changed, None, None, "other", COUNT_LIMIT)
                        )
                        continue
                    try:
                        declared = entry.size
                    except Exception:  # malformed /Params is data, not a failure
                        declared = None
                    if isinstance(declared, int) and declared > MAX_EMBEDDED_FILE_BYTES:
                        files.append(
                            EmbeddedFile(index, display, changed, declared, None, "other", OVERSIZE)
                        )
                        continue
                    try:
                        content = entry.content
                    except LimitReachedError:
                        files.append(
                            EmbeddedFile(
                                index,
                                display,
                                changed,
                                declared if isinstance(declared, int) else None,
                                None,
                                "other",
                                OVERSIZE,
                                detail="LimitReachedError",
                            )
                        )
                        continue
                    except Exception as exc:
                        files.append(
                            EmbeddedFile(
                                index,
                                display,
                                changed,
                                declared if isinstance(declared, int) else None,
                                None,
                                "other",
                                UNREADABLE,
                                detail=type(exc).__name__,
                            )
                        )
                        continue
                    size = len(content)
                    if size > MAX_EMBEDDED_FILE_BYTES:
                        files.append(
                            EmbeddedFile(index, display, changed, size, None, "other", OVERSIZE)
                        )
                        continue
                    if total + size > MAX_TOTAL_EMBEDDED_BYTES:
                        files.append(
                            EmbeddedFile(index, display, changed, size, None, "other", TOTAL_LIMIT)
                        )
                        continue
                    total += size
                    digest = hashlib.sha256(content).hexdigest()
                    kind = _kind(display, content[:8])
                    if kind == "other":
                        files.append(
                            EmbeddedFile(index, display, changed, size, digest, kind, IGNORED)
                        )
                        continue
                    target = out / f"emb-{index:03d}.{kind}"
                    target.write_bytes(content)
                    files.append(
                        EmbeddedFile(
                            index, display, changed, size, digest, kind, EXTRACTED, target.name
                        )
                    )
        except PdfReadError as exc:
            return PortfolioResult(files, bool(files), "unreadable_stream", type(exc).__name__)
        except (OSError, ValueError, RecursionError, KeyError, TypeError) as exc:
            return PortfolioResult(files, bool(files), "unreadable_stream", type(exc).__name__)
    return PortfolioResult(files, bool(files))


def cap_address_space(limit: int) -> None:
    """POSIX address-space cap for a child. Windows has no RLIMIT_AS: there the bound is
    the byte, count and time limits only."""
    try:
        resource: Any = importlib.import_module("resource")
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    except (ImportError, ValueError, OSError):
        pass


def _worker(sender: multiprocessing.connection.Connection, path: str, out_dir: str) -> None:
    cap_address_space(UNPACK_MEMORY_BYTES)
    try:
        sender.send(_unpack(path, out_dir))
    except BaseException as exc:  # the parent reads any failure as a typed result
        sender.send(PortfolioResult([], False, "unreadable_stream", type(exc).__name__))
    finally:
        sender.close()


def unpack_portfolio(
    path: Path,
    out_dir: Path,
    *,
    isolate: bool = True,
    max_seconds: float = UNPACK_SECONDS,
) -> PortfolioResult:
    """Enumerate and extract embedded files into ``out_dir``.

    With ``isolate`` the parse runs in a spawned child that the parent kills at the time
    bound, so a hostile outer file cannot hang the caller. Callers that spawn from a script
    must guard their entry point with ``if __name__ == "__main__":``.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    if not isolate:
        return _unpack(str(path), str(out_dir))
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    child = context.Process(target=_worker, args=(sender, str(path), str(out_dir)), daemon=True)
    child.start()
    sender.close()
    outcome: PortfolioResult
    try:
        if receiver.poll(max_seconds + _SPAWN_GRACE_SECONDS):
            try:
                outcome = receiver.recv()
            except (EOFError, OSError):
                outcome = PortfolioResult([], False, "unreadable_stream", "worker exited")
        else:
            outcome = PortfolioResult([], False, "unpack_time_budget", "worker killed")
    finally:
        receiver.close()
        if child.is_alive():
            child.kill()
        child.join(5)
    return outcome
