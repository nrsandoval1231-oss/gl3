"""MSHA Mines.zip: weekly mine register, reduced to in-scope mines.

Live check 2026-11-04: ``https://arlweb.msha.gov/OpenGovernmentData/DataSets/Mines.zip`` answers
200 keyless, 7.3 MB, one member ``Mines.txt`` (39 MB, 92,101 rows, pipe-delimited, quoted, 70
columns, Latin-1). MSHA says the files update every Friday afternoon. The source is registered
with a 168-hour cadence, so it is downloaded at most once a week, once per run, never twice.

Diff: the record hash covers the reviewed stated fields only (not the file date or row order), so
the ingestion service's own change detection yields exactly the new and the changed mines on a
weekly replay and nothing for an unchanged mine. This module keeps no prior snapshot.

The archive is untrusted: exactly one member named ``Mines.txt``, declared and streamed size
caps, a compression-ratio cap, no extraction to disk, no nested archives.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from typing import Any

import httpx

from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.sector_common import (
    Pacer,
    candidate_record,
    clean,
    fetch,
    iso_date,
    new_client,
    number,
    require_source,
)

SOURCE_ID = "msha-mines"
HOST = "arlweb.msha.gov"
ENDPOINT = "https://arlweb.msha.gov/OpenGovernmentData/DataSets/Mines.zip"
DEFINITION_URL = "https://arlweb.msha.gov/OpenGovernmentData/DataSets/Mines_Definition_File.txt"
MEMBER = "Mines.txt"
MAX_RATIO = 30
MAX_MALFORMED_ROWS = 10
STATES = frozenset({"TX", "OK", "NM"})
STATUSES = frozenset({"Active", "New Mine", "Intermittent", "Temporarily Idled", "NonProducing"})
_MINE_ID = re.compile(r"^[0-9]{7}$")
_COLUMNS = (
    "MINE_ID",
    "CURRENT_MINE_NAME",
    "COAL_METAL_IND",
    "CURRENT_MINE_TYPE",
    "CURRENT_MINE_STATUS",
    "CURRENT_STATUS_DT",
    "CURRENT_OPERATOR_ID",
    "CURRENT_OPERATOR_NAME",
    "CURRENT_CONTROLLER_NAME",
    "STATE",
    "FIPS_CNTY_NM",
    "PRIMARY_SIC",
    "PRIMARY_CANVASS",
    "PORTABLE_OPERATION",
    "DAYS_PER_WEEK",
    "HOURS_PER_SHIFT",
    "PROD_SHIFTS_PER_DAY",
    "NO_EMPLOYEES",
    "LONGITUDE",
    "LATITUDE",
    "NEAREST_TOWN",
)


def valid_query(source: dict[str, Any]) -> bool:
    query = source.get("query")
    return (
        isinstance(query, dict)
        and source.get("id") == SOURCE_ID
        and source.get("endpoint") == ENDPOINT
        and source.get("cadence_hours") == 168
        and source.get("family") == "structured-government"
        and set(query)
        == {"max_zip_bytes", "max_uncompressed_bytes", "max_records", "states", "statuses"}
        and type(query["max_zip_bytes"]) is int
        and 1_000_000 <= query["max_zip_bytes"] <= 20_000_000
        and type(query["max_uncompressed_bytes"]) is int
        and 1_000_000 <= query["max_uncompressed_bytes"] <= 80_000_000
        and type(query["max_records"]) is int
        and 1 <= query["max_records"] <= 5000
        and isinstance(query["states"], list)
        and 1 <= len(query["states"]) <= 5
        and all(item in STATES for item in query["states"])
        and isinstance(query["statuses"], list)
        and 1 <= len(query["statuses"]) <= 5
        and all(item in STATUSES for item in query["statuses"])
    )


def _us_date(value: str | None) -> str | None:
    """MSHA dates are MM/DD/YYYY; anything else is unknown."""
    match = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", (value or "").strip())
    return iso_date(f"{match[3]}-{match[1]}-{match[2]}") if match else None


def read_member(archive: bytes, *, max_uncompressed: int) -> bytes:
    """The single ``Mines.txt`` member, bounded by declared size, ratio and streamed count."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(archive))
    except zipfile.BadZipFile as exc:
        raise SourceParseError("MSHA archive is not a zip file") from exc
    infos = zf.infolist()
    if len(infos) != 1 or infos[0].filename != MEMBER or infos[0].is_dir():
        raise SourceParseError("MSHA archive does not contain exactly Mines.txt")
    info = infos[0]
    if info.flag_bits & 0x1:
        raise SourceParseError("MSHA archive member is encrypted")
    if info.file_size > max_uncompressed:
        raise SourceParseError("MSHA archive member exceeds its size bound")
    if info.compress_size and info.file_size / info.compress_size > MAX_RATIO:
        raise SourceParseError("MSHA archive member exceeds its compression-ratio bound")
    with zf.open(info) as handle:
        data = handle.read(max_uncompressed + 1)
    if len(data) > max_uncompressed or len(data) != info.file_size:
        raise SourceParseError("MSHA archive member size does not match its header")
    return data


def parse_mines(
    data: bytes, *, states: list[str], statuses: list[str], max_records: int
) -> list[dict[str, str | None]]:
    text = io.TextIOWrapper(io.BytesIO(data), encoding="latin-1", newline="")
    reader = csv.reader(text, delimiter="|", quotechar='"')
    try:
        header = next(reader)
    except (StopIteration, csv.Error) as exc:
        raise SourceParseError("MSHA Mines.txt is empty") from exc
    index = {name: position for position, name in enumerate(header)}
    missing = [name for name in _COLUMNS if name not in index]
    if missing:
        raise SourceParseError("MSHA Mines.txt lacks reviewed columns")
    rows: list[dict[str, str | None]] = []
    seen: set[str] = set()
    malformed = 0
    try:
        for raw in reader:
            if len(raw) != len(header):
                malformed += 1
                if malformed > MAX_MALFORMED_ROWS:
                    raise SourceParseError("MSHA Mines.txt has too many malformed rows")
                continue
            row = {name: clean(raw[index[name]], 200) for name in _COLUMNS}
            if row["STATE"] not in states or row["CURRENT_MINE_STATUS"] not in statuses:
                continue
            mine_id = row["MINE_ID"] or ""
            if not _MINE_ID.fullmatch(mine_id) or mine_id in seen:
                raise SourceParseError("MSHA Mines.txt has a missing or duplicate mine ID")
            seen.add(mine_id)
            rows.append(row)
            if len(rows) > max_records:
                raise SourceParseError("MSHA in-scope mine count exceeds its bound")
    except csv.Error as exc:
        raise SourceParseError("MSHA Mines.txt is malformed") from exc
    return rows


def build_record(row: dict[str, str | None], last_modified: str | None) -> dict[str, Any]:
    mine_id = row["MINE_ID"] or ""
    lat, lon = number(row["LATITUDE"]), number(row["LONGITUDE"])
    coordinates_ok = lat is not None and lon is not None and 18 <= lat <= 72 and -180 <= lon <= -60
    status_date = _us_date(row["CURRENT_STATUS_DT"])
    county = row["FIPS_CNTY_NM"]
    state = row["STATE"]
    lines = [
        f"MSHA mine {mine_id}: {row['CURRENT_MINE_NAME'] or 'name not stated'}",
        f"Status: {row['CURRENT_MINE_STATUS']} since {status_date or 'date not stated'}",
        f"Type: {row['CURRENT_MINE_TYPE'] or 'not stated'}; "
        f"commodity: {row['PRIMARY_SIC'] or 'not stated'}",
        f"Operator: {row['CURRENT_OPERATOR_NAME'] or 'not stated'}"
        f" ({row['CURRENT_OPERATOR_ID'] or 'no ID'})",
        f"Controller: {row['CURRENT_CONTROLLER_NAME'] or 'not stated'}",
        f"Location: {county or 'county not stated'}, {state}"
        + (f" ({lat:g}, {lon:g})" if coordinates_ok and lat is not None else ""),
        f"Portable operation: {row['PORTABLE_OPERATION'] or 'not stated'}; "
        f"employees: {row['NO_EMPLOYEES'] or 'not stated'}; "
        f"days/week: {row['DAYS_PER_WEEK'] or 'not stated'}; "
        f"hours/shift: {row['HOURS_PER_SHIFT'] or 'not stated'}; "
        f"production shifts/day: {row['PROD_SHIFTS_PER_DAY'] or 'not stated'}",
        "Activity register only: MSHA states no equipment or electrical demand.",
    ]
    return candidate_record(
        source_id=SOURCE_ID,
        row_id=f"MSHA-{mine_id}",
        title=f"MSHA mine {mine_id} — {row['CURRENT_MINE_NAME'] or 'unnamed'} "
        f"({row['CURRENT_MINE_STATUS']})",
        abstract_lines=lines,
        url=ENDPOINT,
        extraction_location=f"MSHA Mines.txt row MINE_ID {mine_id}",
        semantic={"row": row},
        event_date=status_date,
        event_date_label="MSHA current status date",
        permit={
            "applicant": row["CURRENT_OPERATOR_NAME"],
            "facility": row["CURRENT_MINE_NAME"],
            "status": row["CURRENT_MINE_STATUS"],
            "location": f"{county}, {state}" if county else None,
            "state": state,
            "county": county,
            "permit_type": "MSHA mine register",
            "latitude": lat if coordinates_ok else None,
            "longitude": lon if coordinates_ok else None,
            "snapshot_last_modified": last_modified,
            "source_fields": {
                "facility": "CURRENT_MINE_NAME",
                "event_date": "CURRENT_STATUS_DT",
                "status": "CURRENT_MINE_STATUS",
            },
        },
    )


def retrieve(
    source: dict[str, Any],
    client: httpx.Client | None = None,
    *,
    pacer: Pacer | None = None,
    deadline: float | None = None,
) -> list[dict[str, Any]]:
    require_source(source, SOURCE_ID, ENDPOINT)
    if not valid_query(source):
        raise SourceParseError("MSHA query bounds are invalid")
    query = source["query"]
    http = client or new_client()
    try:
        headers, body = fetch(
            http,
            ENDPOINT,
            hosts={HOST},
            max_bytes=query["max_zip_bytes"],
            media_types={"application/x-zip-compressed", "application/zip"},
            pacer=pacer or Pacer(deadline=deadline),
        )
        data = read_member(body, max_uncompressed=query["max_uncompressed_bytes"])
        rows = parse_mines(
            data,
            states=query["states"],
            statuses=query["statuses"],
            max_records=query["max_records"],
        )
        modified = clean(headers.get("last-modified"), 40)
        return [
            build_record(row, modified) for row in sorted(rows, key=lambda r: r["MINE_ID"] or "")
        ]
    finally:
        if client is None:
            http.close()
