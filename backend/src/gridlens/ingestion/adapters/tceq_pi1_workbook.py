"""Read-only reader for TCEQ PI-1 / NSR application workbooks.

Reads only the "Unit Types - Emission Rates" sheet (facility ID, EPN, source name, unit type)
and a few descriptive text cells. Every fact carries its sheet and cell. A unit type is the
applicant's own dropdown label (for example ``Engine: Internal Combustion Engine, Spark
Ignited``). These workbooks list emission units. They almost never carry a numeric rating, so
this reader never reports one: ratings, if stated at all, are in free text or the PDF.

Counts here are counts of listed units (distinct FINs) and are labelled ``documented``. A row
can stand for several physical units, so a count is never treated as an equipment quantity.
Combustion units are supply: they never feed demand.
"""

from __future__ import annotations

import re
import warnings
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAX_WORKBOOK_BYTES = 64 * 1024 * 1024
MAX_ZIP_UNCOMPRESSED_BYTES = 400 * 1024 * 1024
MAX_ZIP_MEMBERS = 2_000
MAX_UNIT_ROWS = 20_000
MAX_UNITS_LISTED = 400
MAX_DESCRIPTIONS = 5
MAX_DESCRIPTION_CHARS = 400
MAX_TEXT_ROWS = 200
UNIT_SHEET = "Unit Types - Emission Rates"
TEXT_SHEETS = ("General", "Technical Review", "Federal Applicability", "Public Notice")
VERSION = "tceq-pi1-workbook-v1"
BASIS = "documented"

_KEYWORDS = re.compile(
    r"\bMW\b|megawatt|\bhp\b|horsepower|\bkW\b|engine|turbine|generator|data\s*center",
    re.IGNORECASE,
)
_UNIT_COUNT = re.compile(
    r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d{1,6})\s+(?:[A-Za-z][A-Za-z\-]*\s+){0,4}?"
    r"(engines?|generators?|turbines?|boilers?|heaters?)\b",
    re.IGNORECASE,
)
_MW = re.compile(
    r"\b(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*(MW|megawatts?)\b", re.IGNORECASE
)


class WorkbookError(Exception):
    """Typed, bounded failure. ``code`` is safe to persist; the message is not."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(slots=True)
class WorkbookSummary:
    file: str
    sheet: str | None
    unit_count: int = 0
    units_by_type: dict[str, int] = field(default_factory=dict)
    units: list[dict[str, Any]] = field(default_factory=list)
    units_truncated: bool = False
    descriptions: list[dict[str, str]] = field(default_factory=list)
    stated_counts: list[dict[str, Any]] = field(default_factory=list)
    stated_mw: list[dict[str, Any]] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {
            "version": VERSION,
            "basis": BASIS,
            "file": self.file,
            "sheet": self.sheet,
            "unit_count": self.unit_count,
            "units_by_type": self.units_by_type,
            "units": self.units,
            "units_truncated": self.units_truncated,
            "descriptions": self.descriptions,
            "stated_counts": self.stated_counts,
            "stated_mw": self.stated_mw,
            "ratings": "not read: workbooks list units; ratings are not in a numeric column",
        }


def _text(value: object) -> str:
    return " ".join(str(value).split()) if value not in (None, "") else ""


def _family(unit_type: str) -> str:
    """Leading label of a dropdown unit type (``Engine`` of ``Engine: ...``)."""
    return unit_type.split(":", 1)[0].strip()[:60] or "Unspecified"


def _check_zip(path: Path) -> None:
    if path.stat().st_size > MAX_WORKBOOK_BYTES:
        raise WorkbookError("workbook_oversize")
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > MAX_ZIP_MEMBERS:
                raise WorkbookError("workbook_unsafe")
            if sum(item.file_size for item in members) > MAX_ZIP_UNCOMPRESSED_BYTES:
                raise WorkbookError("workbook_unsafe")
            if any("vbaproject" in item.filename.lower() for item in members):
                # Macros are never read or run.
                raise WorkbookError("workbook_unsafe")
    except zipfile.BadZipFile as exc:
        raise WorkbookError("workbook_unreadable") from exc


def read_pi1_workbook(path: Path, display_name: str) -> WorkbookSummary:
    """Summarise one workbook. Raises ``WorkbookError`` for unsafe or unreadable files."""
    from openpyxl import load_workbook

    _check_zip(path)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            book = load_workbook(path, read_only=True, data_only=True, keep_links=False)
        except Exception as exc:
            raise WorkbookError("workbook_unreadable") from exc
        try:
            summary = WorkbookSummary(file=display_name, sheet=None)
            if UNIT_SHEET in book.sheetnames:
                summary.sheet = UNIT_SHEET
                _read_units(book[UNIT_SHEET], summary)
            _read_text(book, summary)
        except WorkbookError:
            raise
        except Exception as exc:
            raise WorkbookError("workbook_unreadable") from exc
        finally:
            book.close()
    return summary


def _read_units(sheet: Any, summary: WorkbookSummary) -> None:
    columns: dict[str, int] = {}
    header_row = 0
    current: dict[str, Any] | None = None
    seen: set[str] = set()
    for row_number, row in enumerate(sheet.iter_rows(max_row=MAX_UNIT_ROWS), start=1):
        cells = {cell.column - 1: cell for cell in row if _text(cell.value)}
        if not columns:
            # The header row names the FIN column; its unit-type column is labelled "Unit Type".
            labels = {index: _text(cell.value).lower() for index, cell in cells.items()}
            fin_columns = [i for i, label in labels.items() if "facility id number" in label]
            if fin_columns:
                header_row = row_number
                columns = {"fin": fin_columns[0]}
                for index, label in labels.items():
                    if "emission point number" in label:
                        columns["epn"] = index
                    elif label == "source name":
                        columns["name"] = index
                    elif label.startswith("action requested"):
                        columns["action"] = index
                    elif label.startswith("unit type") and "notes" not in label:
                        columns["type"] = index
            continue
        if "type" not in columns or row_number <= header_row:
            continue
        fin_cell = cells.get(columns["fin"])
        if fin_cell is not None:
            fin = _text(fin_cell.value)[:60]
            if fin in seen:
                current = None  # another operating scenario for a FIN already listed
                continue
            seen.add(fin)
            action = cells.get(columns.get("action", -1))
            name = cells.get(columns.get("name", -1))
            epn = cells.get(columns.get("epn", -1))
            current = {
                "fin": fin,
                "epn": _text(epn.value)[:60] if epn is not None else None,
                "name": _text(name.value)[:160] if name is not None else None,
                "action": _text(action.value)[:40] if action is not None else None,
                "type": None,
                "cell": fin_cell.coordinate,
            }
            summary.unit_count += 1
            if len(summary.units) < MAX_UNITS_LISTED:
                summary.units.append(current)
            else:
                summary.units_truncated = True
        type_cell = cells.get(columns["type"])
        if current is not None and type_cell is not None and current["type"] is None:
            unit_type = _text(type_cell.value)[:120]
            current["type"] = unit_type
            current["type_cell"] = type_cell.coordinate
            family = _family(unit_type)
            summary.units_by_type[family] = summary.units_by_type.get(family, 0) + 1
    if not columns:
        raise WorkbookError("workbook_layout_unrecognised")


def _read_text(book: Any, summary: WorkbookSummary) -> None:
    for name in TEXT_SHEETS:
        if name not in book.sheetnames or len(summary.descriptions) >= MAX_DESCRIPTIONS:
            continue
        for row in book[name].iter_rows(max_row=MAX_TEXT_ROWS):
            for cell in row:
                value = cell.value
                if not isinstance(value, str) or not 60 <= len(value) <= 6_000:
                    continue
                text = _text(value)
                # The sheet's own instructions mention engines and MW. Keep applicant text.
                if not _KEYWORDS.search(text) or text.startswith(
                    ("This sheet", "Instructions", "Select from")
                ):
                    continue
                if len(summary.descriptions) >= MAX_DESCRIPTIONS:
                    break
                location = f"{name}!{cell.coordinate}"
                summary.descriptions.append(
                    {"sheet_cell": location, "text": text[:MAX_DESCRIPTION_CHARS]}
                )
                for match in _UNIT_COUNT.finditer(text):
                    if len(summary.stated_counts) < 20:
                        summary.stated_counts.append(
                            {
                                "count": int(match.group(1).replace(",", "")),
                                "noun": match.group(2).lower(),
                                "quote": match.group(0)[:160],
                                "sheet_cell": location,
                            }
                        )
                for match in _MW.finditer(text):
                    if len(summary.stated_mw) < 20:
                        summary.stated_mw.append(
                            {
                                "value": match.group(1),
                                "quote": text[max(0, match.start() - 60) : match.end() + 40],
                                "sheet_cell": location,
                                "note": "text mention; whether supply or demand is not stated here",
                            }
                        )
