"""ERCOT Transmission Project and Information Tracking (TPIT) workbook: rows and monthly diff.

The public "no cost" TPIT workbook is replaced in place at one stable URL each month (the listing
shows a new date and size), so the content hash is the only reliable change signal. It has one
sheet per lifecycle list (Future, Planned, Completed, Cancelled) with identical columns. This reader
keeps the project number, title, description, status, owner, kV, counties, tier, RPG number and
dates. It never reads the contact column (personal names and e-mail addresses). MVA is a
transformer rating, not load, so no MW is derived from this workbook.

Only "relevant" rows are kept in the monthly snapshot: an RPG number, Tier 1 or 2, or wording about
a load, customer or data center. Each kept row stores a hash of its kept fields; the next month's
diff is new / changed / removed relative to the previous snapshot's kept rows. The first snapshot is
a baseline, not a diff.
"""

from __future__ import annotations

import hashlib
import io
import json
import multiprocessing
import re
import zipfile
from datetime import date, datetime
from typing import Any

from gridlens.ingestion.adapters.tceq_application_documents import DocumentFailure

VERSION = "ercot-tpit-v1"
MAX_BYTES = 12 * 1024 * 1024
MAX_UNCOMPRESSED = 120 * 1024 * 1024
MAX_ROWS_PER_SHEET = 6000
MAX_KEPT_ROWS = 1500
MAX_DIFF_ROWS = 400
MAX_TEXT = 300
_SHEET_ORDER = ("Future", "Planned", "Completed", "Cancelled")
_PRECEDENCE = {"Completed": 3, "Cancelled": 2, "Planned": 1, "Future": 0}
_RELEVANT_TEXT = re.compile(r"\bload\b|customer|data[ -]?cent(?:er|re)", re.I)
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,29}")

# column key -> normalised header prefix
_COLUMNS = {
    "number": "ercot project number",
    "title": "project title",
    "description": "project description",
    "comments": "comments/reasons",
    "from": 'terminal "from" location',
    "to": 'terminal "to" location',
    "status": "transmission status",
    "owner": "transmission owner (text)",
    "isd": "projected in-service date",
    "actual": "actual in-service date",
    "kv": "service level kv",
    "mva": "autotransformer capacity",
    "county": "county location for substation",
    "county_end": "county location for ending",
    "tier": "planning charter tier",
    "rpg": "rpg number",
}
_COMPARED = (
    "sheet",
    "title",
    "description",
    "status",
    "owner",
    "isd",
    "actual",
    "kv",
    "mva",
    "county",
    "county_end",
    "tier",
    "rpg",
    "from",
    "to",
)


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime | date):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    text = "".join(ch if ch.isprintable() else " " for ch in str(value))
    text = " ".join(text.split())
    return text[:MAX_TEXT] or None


def _header_map(header: tuple[Any, ...]) -> dict[str, int]:
    found: dict[str, int] = {}
    for index, cell in enumerate(header):
        name = " ".join(str(cell or "").lower().split())
        for key, prefix in _COLUMNS.items():
            if key not in found and name.startswith(prefix):
                found[key] = index
    return found


def read_workbook(body: bytes) -> dict[str, Any]:
    """Kept-field rows by sheet name. Raises DocumentFailure with a code, never row content."""
    if not body.startswith(b"PK"):
        raise DocumentFailure("not_xlsx_signature")
    if len(body) > MAX_BYTES:
        raise DocumentFailure("oversize")
    try:
        archive = zipfile.ZipFile(io.BytesIO(body))
        if sum(info.file_size for info in archive.infolist()) > MAX_UNCOMPRESSED:
            raise DocumentFailure("workbook_too_large_uncompressed")
    except zipfile.BadZipFile as exc:
        raise DocumentFailure("workbook_unreadable") from exc
    import openpyxl

    try:
        book = openpyxl.load_workbook(io.BytesIO(body), read_only=True, data_only=True)
    except Exception as exc:
        raise DocumentFailure("workbook_unreadable") from exc
    sheets: dict[str, list[dict[str, Any]]] = {}
    try:
        for family in _SHEET_ORDER:
            name = next((n for n in book.sheetnames if n.startswith(family) and "TPIT" in n), None)
            if name is None:
                continue
            rows_iter = book[name].iter_rows(values_only=True)
            next(rows_iter, None)  # title row
            header = next(rows_iter, None)
            columns = _header_map(header or ())
            if not {"number", "status", "tier"}.issubset(columns):
                raise DocumentFailure("workbook_columns_changed")
            rows: list[dict[str, Any]] = []
            for count, raw in enumerate(rows_iter):
                if count >= MAX_ROWS_PER_SHEET:
                    raise DocumentFailure("workbook_too_many_rows")
                number = _clean(raw[columns["number"]]) if len(raw) > columns["number"] else None
                if not number or not _SAFE_ID.fullmatch(number):
                    continue
                row: dict[str, str | None] = {"sheet": family, "number": number}
                for key, index in columns.items():
                    if key != "number":
                        row[key] = _clean(raw[index]) if index < len(raw) else None
                rows.append(row)
            sheets[family] = rows
    finally:
        book.close()
    if not sheets:
        raise DocumentFailure("workbook_columns_changed")
    return {"sheets": sheets}


def _worker(sender: Any, body: bytes) -> None:
    try:
        sender.send(("ok", read_workbook(body)))
    except DocumentFailure as failure:
        sender.send(("error", failure.code))
    except BaseException:  # the parent reads any fault as a typed failure
        sender.send(("error", "workbook_unreadable"))
    finally:
        sender.close()


def read_workbook_isolated(body: bytes, seconds: float, isolate: bool) -> dict[str, Any]:
    if not isolate:
        return read_workbook(body)
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    child = context.Process(target=_worker, args=(sender, body), daemon=True)
    child.start()
    sender.close()
    try:
        if not receiver.poll(seconds + 20.0):
            raise DocumentFailure("workbook_time_budget")
        try:
            kind, value = receiver.recv()
        except (EOFError, OSError) as exc:
            raise DocumentFailure("workbook_unreadable") from exc
    finally:
        receiver.close()
        if child.is_alive():
            child.kill()
        child.join(5)
    if kind == "ok":
        result: dict[str, Any] = value
        return result
    raise DocumentFailure(str(value))


def _relevant(row: dict[str, Any]) -> bool:
    if row.get("rpg") or row.get("tier") in {"Tier 1", "Tier 2"}:
        return True
    text = " ".join(str(row.get(k) or "") for k in ("title", "description", "comments"))
    return bool(_RELEVANT_TEXT.search(text))


def row_hash(row: dict[str, Any]) -> str:
    kept = {key: row.get(key) for key in _COMPARED}
    return hashlib.sha256(json.dumps(kept, sort_keys=True).encode()).hexdigest()[:16]


def kept_rows(sheets: dict[str, list[dict[str, Any]]]) -> tuple[dict[str, dict[str, Any]], int]:
    """Relevant rows by project number (later-lifecycle sheet wins a duplicate) and the total."""
    chosen: dict[str, dict[str, Any]] = {}
    total = 0
    for rows in sheets.values():
        for row in rows:
            total += 1
            current = chosen.get(row["number"])
            if current is None or _PRECEDENCE[row["sheet"]] > _PRECEDENCE[current["sheet"]]:
                chosen[row["number"]] = row
    kept = {number: row for number, row in chosen.items() if _relevant(row)}
    return kept, total


def diff(
    prior: dict[str, dict[str, Any]] | None, current: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """New / changed / removed kept rows. ``prior`` None means a baseline, not a diff."""
    if prior is None:
        return []
    changes: list[dict[str, Any]] = []
    for number in sorted(current):
        before = prior.get(number)
        if before is None:
            changes.append({"project": number, "change": "new"})
        elif before.get("h") != current[number]["h"]:
            moved = [key for key in _COMPARED if before.get(key) != current[number].get(key)]
            changes.append({"project": number, "change": "changed", "fields": moved[:16]})
    for number in sorted(set(prior) - set(current)):
        changes.append({"project": number, "change": "removed"})
    return changes[:MAX_DIFF_ROWS]


def tpit_extraction(
    body: bytes,
    prior_extraction: dict[str, Any] | None,
    seconds: float,
    isolate: bool,
    observed_on: str,
) -> dict[str, Any]:
    data = read_workbook_isolated(body, seconds, isolate)
    kept, total = kept_rows(data["sheets"])
    if len(kept) > MAX_KEPT_ROWS:
        raise DocumentFailure("workbook_too_many_relevant_rows")
    prior_rows = (prior_extraction or {}).get("rows") if prior_extraction else None
    rows: dict[str, dict[str, Any]] = {}
    for number, row in kept.items():
        entry: dict[str, Any] = {key: row.get(key) for key in _COMPARED if row.get(key) is not None}
        entry["h"] = row_hash(row)  # over the full kept fields
        if entry.get("description"):
            entry["description"] = entry["description"][:160]
        before = (prior_rows or {}).get(number)
        # Carried forward from the first snapshot that showed the row; never rewritten.
        entry["fs"] = (before or {}).get("fs") or observed_on
        rows[number] = entry
    changes = diff(prior_rows, rows)
    counts = {name: len(items) for name, items in data["sheets"].items()}
    first = prior_rows is None
    lines = [
        "ERCOT TPIT snapshot: "
        + ", ".join(f"{name} {count}" for name, count in counts.items())
        + f" rows; {len(rows)} relevant kept",
        "TPIT diff: baseline snapshot (no earlier snapshot to compare)"
        if first
        else "TPIT diff: "
        + ", ".join(
            f"{kind} {sum(1 for c in changes if c['change'] == kind)}"
            for kind in ("new", "changed", "removed")
        ),
        "MVA is a transformer rating, not load; no MW is derived from this workbook.",
    ]
    return {
        "extractor": VERSION,
        "sheet_counts": counts,
        "rows_total": total,
        "rows_kept": len(rows),
        "rows": rows,
        "baseline": first,
        "diff": changes,
        "summary_lines": lines,
        "fields_found": len(rows),
    }
