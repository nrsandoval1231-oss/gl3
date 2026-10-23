"""Texas Comptroller JETI application index.

The applications page loads https://api.comptroller.texas.gov/open-data/v1/tables/jeti.
Each row names an applicant and a school district and links posted PDFs. It does
not name a street, city, or county, so this adapter does not invent a Texas site.
Rows stay evidence until a record states a place.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any

import httpx

from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.power_signals import power_signal_tags
from gridlens.ingestion.adapters.public_source_http import read_public_response

SOURCE_ID = "texas-jeti-applications"
API_URL = "https://api.comptroller.texas.gov/open-data/v1/tables/jeti"
ALLOWED_HOSTS = frozenset({"api.comptroller.texas.gov"})
INDEX_URL = "https://comptroller.texas.gov/economy/development/prop-tax/jeti/applications.php"
PDF_ROOT = "https://assets.comptroller.texas.gov/open-data/jeti/"
MAX_RESPONSE_BYTES = 2_000_000
MAX_RECORDS = 200
_FILE_NAME = re.compile(r"^J\d+/[A-Za-z0-9][A-Za-z0-9._-]*\.pdf$")
_DATA_CENTER = re.compile(r"data\s*cent(?:er|re)|hyperscale", re.IGNORECASE)


def _posted(value: str) -> str:
    try:
        return datetime.strptime(value, "%m/%d/%Y").date().isoformat()
    except ValueError as exc:
        raise SourceParseError("JETI posted date is malformed") from exc


def _created(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SourceParseError("JETI createdAt is malformed") from exc
    return parsed.date().isoformat()


def _documents(row: dict[str, Any]) -> tuple[list[tuple[str, str, str | None]], str | None]:
    phases = row.get("files")
    if not isinstance(phases, list):
        raise SourceParseError("JETI row files are not a list")
    documents: list[tuple[str, str, str | None]] = []
    application_dates: list[str] = []
    for phase_map in phases:
        if not isinstance(phase_map, dict):
            raise SourceParseError("JETI file phase is not an object")
        for phase, docs in phase_map.items():
            if not isinstance(docs, list):
                raise SourceParseError("JETI file phase is not a list")
            for doc in docs:
                if not isinstance(doc, dict):
                    raise SourceParseError("JETI file entry is not an object")
                file_name = doc.get("file_nm")
                if not isinstance(file_name, str) or not _FILE_NAME.fullmatch(file_name):
                    raise SourceParseError("JETI file name is not a project PDF path")
                posted = doc.get("posted_date")
                posted_iso = _posted(posted) if isinstance(posted, str) and posted else None
                label = str(doc.get("name") or phase)
                documents.append((f"{phase}: {label}", PDF_ROOT + file_name, posted_iso))
                if phase == "Application Phase" and posted_iso:
                    application_dates.append(posted_iso)
    application = min(application_dates) if application_dates else None
    return documents, application


def parse_index(body: bytes) -> list[dict[str, Any]]:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise SourceParseError("JETI index is not JSON") from exc
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise SourceParseError("JETI index did not report success")
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise SourceParseError("JETI index has no data list")
    if payload.get("count") != len(rows):
        raise SourceParseError("JETI index count does not match its rows")
    parsed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise SourceParseError("JETI row is not an object")
        application_id = str(row.get("id") or "")
        applicant = str(row.get("applicant") or "").strip()
        district = str(row.get("school_district") or "").strip()
        if not re.fullmatch(r"J\d+", application_id) or not applicant or not district:
            raise SourceParseError("JETI row is missing id, applicant, or school district")
        if application_id in seen:
            raise SourceParseError("JETI index has a duplicate application id")
        seen.add(application_id)
        documents, application_date = _documents(row)
        created = row.get("createdAt")
        if not isinstance(created, str):
            raise SourceParseError("JETI row has no createdAt")
        event_date = application_date or _created(created)
        text = f"{applicant} {district}"
        parsed.append(
            {
                "id": application_id,
                "applicant": applicant,
                "school_district": district,
                "negative": bool(row.get("negative")),
                "event_date": event_date,
                "event_date_label": (
                    "JETI application posted date" if application_date else "JETI record createdAt"
                ),
                "documents": documents,
                "api_last_updated": payload.get("lastUpdated"),
                "tags": power_signal_tags(text),
                "data_center": bool(_DATA_CENTER.search(text)),
            }
        )
    return parsed


def _record(row: dict[str, Any]) -> dict[str, Any]:
    row_id = f"JETI-{row['id']}"
    links = {label: url for label, url, _posted_date in row["documents"]}
    links["JETI applications"] = INDEX_URL
    first_pdf = next((url for _label, url, _posted in row["documents"]), INDEX_URL)
    semantic = {
        "id": row["id"],
        "applicant": row["applicant"],
        "school_district": row["school_district"],
        "negative": row["negative"],
        "event_date": row["event_date"],
        "documents": sorted(links.items()),
        "power_signals": row["tags"],
        "data_center": row["data_center"],
    }
    return {
        "document_number": row_id,
        "title": f"{row['id']} — {row['applicant']}",
        "abstract": "\n".join(
            [
                f"Application: {row['id']}",
                f"Applicant: {row['applicant']}",
                f"School district: {row['school_district']}",
                f"Comptroller negative recommendation: {row['negative']}",
                "Project site: not stated in the JETI index",
                f"API lastUpdated field: {row['api_last_updated'] or 'not stated'}",
                f"Power signal tags: {', '.join(row['tags']) or 'none'}",
            ]
        ),
        "publication_date": None,
        "event_date": row["event_date"],
        "event_date_label": row["event_date_label"],
        "html_url": first_pdf,
        "extraction_location": "Texas Comptroller JETI open-data table",
        "source_hash": hashlib.sha256(
            json.dumps(semantic, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "permit": {
            "source_type": SOURCE_ID,
            "row_id": row_id,
            "applicant": row["applicant"],
            "facility": row["applicant"],
            "permit_numbers": [row["id"]],
            "permit_type": "JETI application",
            "status": "negative recommendation" if row["negative"] else None,
            "description": f"{row['applicant']} ({row['school_district']})",
            "location": None,
            "school_district": row["school_district"],
            "state": None,
            "data_center": row["data_center"],
            "power_signals": row["tags"],
            "document_links": links,
            "source_fields": {
                "applicant": "applicant",
                "school_district": "school_district",
                "event_date": row["event_date_label"],
                "location": "not present in the JETI index",
            },
        },
    }


def retrieve(source: dict[str, Any], client: httpx.Client | None = None) -> list[dict[str, Any]]:
    if source.get("id") != SOURCE_ID or source.get("endpoint") != API_URL:
        raise SourceParseError("JETI source ID or endpoint is not configured")
    query = source.get("query", {})
    if (
        query.get("max_response_bytes") != MAX_RESPONSE_BYTES
        or query.get("max_records") != MAX_RECORDS
    ):
        raise SourceParseError("JETI query bounds are invalid")
    http = client or httpx.Client(timeout=60, follow_redirects=False, trust_env=False)
    try:
        _, body = read_public_response(
            http,
            API_URL,
            max_bytes=MAX_RESPONSE_BYTES,
            allowed_media_types={"application/json"},
            allowed_hosts=ALLOWED_HOSTS,
        )
        rows = parse_index(body)
        if len(rows) > MAX_RECORDS:
            raise SourceParseError("JETI row count exceeds its bound")
        return [_record(row) for row in rows]
    finally:
        if client is None:
            http.close()
