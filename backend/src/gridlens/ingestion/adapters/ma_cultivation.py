"""Bounded reader for the Massachusetts CCC cultivation application snapshot."""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import date, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from gridlens.ingestion.adapters.bounded_http import ResponseTooLarge, read_bounded_response
from gridlens.ingestion.adapters.federal_register import SourceParseError

HOST = "masscannabiscontrol.com"
PATH = "/resource/l_applications_all_details.json"
SOURCE_ID = "ma-ccc-cultivation-applications"
LICENSE_TYPE = "Marijuana Cultivator"
_SOURCE_DATE = re.compile(
    r"^[A-Za-z]{3} ([A-Za-z]{3}) (\d{1,2}) (\d{4}) "
    r"(\d{2}:\d{2}:\d{2}) GMT([+-]\d{4}) \([^)]+\)$"
)
_MONTHS = {
    name: number
    for number, name in enumerate(
        ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
        start=1,
    )
}
_SEMANTIC_FIELDS = (
    "LICENSE_NUMBER",
    "APPLICATION_NUMBER",
    "LICENSE_TYPE",
    "APPLICATION_STATUS",
    "APPROVED_LICENSE_STAGE",
    "SUBMITTED_DATE",
    "ORIGINAL_SUBMITTED_DATE",
    "APPLICATION_CREATED_DATE",
    "APPLICATION_APPROVED_DATE",
    "APPLICATION_DENIED_DATE",
    "BUSINESS_NAME",
    "BUSINESS_EMAIL",
    "BUSINESS_PHONE",
    "ESTABLISHMENT_ADDRESS_1",
    "ESTABLISHMENT_ADDRESS_2",
    "ESTABLISHMENT_CITY",
    "ESTABLISHMENT_STATE",
    "ESTABLISHMENT_ZIP",
    "LICENSE_STATUS",
    "COMMENCE_OPERATIONS_DATE",
    "CNB_DATE_OF_FINAL_LICENSURE",
    "LIC_START_DATE",
    "LIC_ORIGINAL_START_DATE",
    "LIC_EXPIRATION_DATE",
    "LIC_REVOCATION_DATE",
    "LIC_REVOKE_DATE",
    "LIC_SURRENDERED_DATE",
    "LIC_SURRENDER_DATE",
    "LIC_SUSPENDED_START_DATE",
    "LIC_SUSPENDED_END_DATE",
    "LIC_SUSPENSION_START_DATE",
    "LIC_SUSPENSION_END_DATE",
)
_OUTPUT_FIELDS = (
    "LICENSE_NUMBER",
    "APPLICATION_NUMBER",
    "LICENSE_TYPE",
    "APPLICATION_STATUS",
    "APPROVED_LICENSE_STAGE",
    "SUBMITTED_DATE",
    "ORIGINAL_SUBMITTED_DATE",
    "APPLICATION_CREATED_DATE",
    "APPLICATION_APPROVED_DATE",
    "APPLICATION_DENIED_DATE",
    "BUSINESS_NAME",
    "BUSINESS_EMAIL",
    "BUSINESS_PHONE",
    "ESTABLISHMENT_ADDRESS_1",
    "ESTABLISHMENT_ADDRESS_2",
    "ESTABLISHMENT_CITY",
    "ESTABLISHMENT_STATE",
    "ESTABLISHMENT_ZIP",
    "LICENSE_STATUS",
    "COMMENCE_OPERATIONS_DATE",
    "CNB_DATE_OF_FINAL_LICENSURE",
    "LIC_START_DATE",
    "LIC_ORIGINAL_START_DATE",
    "LIC_EXPIRATION_DATE",
    "LIC_REVOCATION_DATE",
    "LIC_REVOKE_DATE",
    "LIC_SURRENDERED_DATE",
    "LIC_SURRENDER_DATE",
    "LIC_SUSPENDED_START_DATE",
    "LIC_SUSPENDED_END_DATE",
    "LIC_SUSPENSION_START_DATE",
    "LIC_SUSPENSION_END_DATE",
    "CCCLastUpdated",
)
_REQUIRED_FIELDS = {
    "LICENSE_TYPE",
    "APPLICATION_NUMBER",
    "LICENSE_NUMBER",
    "APPLICATION_STATUS",
    "SUBMITTED_DATE",
    "CCCLastUpdated",
    "BUSINESS_NAME",
    "ESTABLISHMENT_ADDRESS_1",
    "ESTABLISHMENT_CITY",
    "ESTABLISHMENT_STATE",
}


def _text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def _source_datetime(value: str) -> datetime:
    match = _SOURCE_DATE.fullmatch(value.strip())
    if not match:
        raise SourceParseError("CCC application row has malformed source date")
    month_name, day, year, clock, offset = match.groups()
    month = _MONTHS.get(month_name)
    if month is None:
        raise SourceParseError("CCC application row has malformed source date")
    try:
        return datetime.strptime(
            f"{year}-{month:02d}-{int(day):02d} {clock} {offset}",
            "%Y-%m-%d %H:%M:%S %z",
        )
    except ValueError as exc:
        raise SourceParseError("CCC application row has malformed source date") from exc


def _safe_row(row: dict[str, Any]) -> dict[str, str]:
    # Explicit allowlist: the CCC snapshot also contains personal contacts and EINs.
    if any(isinstance(row.get(key), dict | list | bool) for key in _OUTPUT_FIELDS):
        raise SourceParseError("CCC application row has a malformed whitelisted value")
    return {key: _text(row.get(key)) for key in _OUTPUT_FIELDS}


def _abstract(row: dict[str, str], event_label: str) -> str:
    values = {
        "applicant_org": row["BUSINESS_NAME"],
        "applicant_role": "Applicant organization (CCC cultivation application)",
        "business_email": row["BUSINESS_EMAIL"],
        "business_phone": row["BUSINESS_PHONE"],
        "application_number": row["APPLICATION_NUMBER"] or row["LICENSE_NUMBER"],
        "license_number": row["LICENSE_NUMBER"],
        "license_type": row["LICENSE_TYPE"],
        "application_status": row["APPLICATION_STATUS"],
        "application_stage": row["APPROVED_LICENSE_STAGE"],
        "event_date": row["SUBMITTED_DATE"],
        "event_date_label": event_label,
        "original_submitted_date": row["ORIGINAL_SUBMITTED_DATE"],
        "application_created_date": row["APPLICATION_CREATED_DATE"],
        "application_approved_date": row["APPLICATION_APPROVED_DATE"],
        "application_denied_date": row["APPLICATION_DENIED_DATE"],
        "establishment_address": " ".join(
            part
            for part in (row["ESTABLISHMENT_ADDRESS_1"], row["ESTABLISHMENT_ADDRESS_2"])
            if part
        ),
        "city": row["ESTABLISHMENT_CITY"],
        "state": row["ESTABLISHMENT_STATE"],
        "zip": row["ESTABLISHMENT_ZIP"],
        "license_status": row["LICENSE_STATUS"],
        "commence_operations_date": row["COMMENCE_OPERATIONS_DATE"],
        "final_licensure_date": row["CNB_DATE_OF_FINAL_LICENSURE"],
        "license_start_date": row["LIC_START_DATE"],
        "license_original_start_date": row["LIC_ORIGINAL_START_DATE"],
        "license_expiration_date": row["LIC_EXPIRATION_DATE"],
        "license_revocation_date": row["LIC_REVOCATION_DATE"] or row["LIC_REVOKE_DATE"],
        "license_surrendered_date": row["LIC_SURRENDERED_DATE"] or row["LIC_SURRENDER_DATE"],
        "license_suspended_start_date": row["LIC_SUSPENDED_START_DATE"]
        or row["LIC_SUSPENSION_START_DATE"],
        "license_suspended_end_date": row["LIC_SUSPENDED_END_DATE"]
        or row["LIC_SUSPENSION_END_DATE"],
        "snapshot_updated": row["CCCLastUpdated"],
    }
    address = values["establishment_address"]
    site = ", ".join(
        part for part in (address, values["city"], values["state"], values["zip"]) if part
    )
    values["site"] = site
    return "\n".join(f"{key}: {value}" for key, value in values.items() if value)


def retrieve(
    source: dict[str, Any], client: httpx.Client | None = None, *, today: date | None = None
) -> list[dict[str, Any]]:
    if (
        source.get("id") != SOURCE_ID
        or source.get("retrieval_method") != "ma-cultivation-applications"
    ):
        raise SourceParseError("CCC cultivation source ID or method is not configured")
    parsed = urlparse(str(source.get("endpoint") or ""))
    if parsed.scheme != "https" or parsed.hostname != HOST or parsed.path != PATH or parsed.query:
        raise SourceParseError("CCC endpoint is outside its configured official resource")
    query = source.get("query") or {}
    max_bytes = query.get("max_snapshot_bytes")
    max_records = query.get("max_records")
    max_age_days = query.get("max_snapshot_age_days")
    max_event_age_days = query.get("max_application_event_age_days")
    if (
        not isinstance(max_bytes, int)
        or not 1024 <= max_bytes <= 20_000_000
        or not isinstance(max_records, int)
        or not 1 <= max_records <= 5000
        or not isinstance(max_age_days, int)
        or not 1 <= max_age_days <= 60
        or not isinstance(max_event_age_days, int)
        or not 1 <= max_event_age_days <= 365
    ):
        raise SourceParseError("CCC source bounds are invalid")
    own_client = client is None
    client = client or httpx.Client(
        timeout=20.0,
        follow_redirects=False,
        headers={"User-Agent": "GridLens public-data reader/1.0"},
    )
    try:
        try:
            headers, content = read_bounded_response(
                client, source["endpoint"], max_bytes, deadline=time.monotonic() + 30
            )
        except (ResponseTooLarge, TimeoutError, httpx.HTTPError) as exc:
            raise SourceParseError(str(exc)) from exc
        if "json" not in headers.get("content-type", "").casefold():
            raise SourceParseError("CCC snapshot content type is not JSON")
        snapshot_hash = hashlib.sha256(content).hexdigest()
        try:
            payload = json.loads(content)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SourceParseError("CCC snapshot is not valid JSON") from exc
        if not isinstance(payload, list) or not payload or len(payload) > max_records:
            raise SourceParseError("CCC snapshot row count or top-level schema is invalid")
        if any(not isinstance(row, dict) for row in payload):
            raise SourceParseError("CCC snapshot contains a malformed row")
        if not _REQUIRED_FIELDS.issubset(set().union(*(row.keys() for row in payload))):
            raise SourceParseError("CCC snapshot is missing required application fields")
        dates = {_text(row.get("CCCLastUpdated")) for row in payload}
        if len(dates) != 1:
            raise SourceParseError("CCC snapshot update date is missing or inconsistent")
        try:
            updated = date.fromisoformat(next(iter(dates)))
        except ValueError as exc:
            raise SourceParseError("CCC snapshot update date is malformed") from exc
        as_of = today or date.today()
        age = (as_of - updated).days
        if age < 0 or age > max_age_days:
            raise SourceParseError("CCC snapshot is stale or has a future update date")

        cultivation = [row for row in payload if _text(row.get("LICENSE_TYPE")) == LICENSE_TYPE]
        if not cultivation:
            raise SourceParseError("CCC snapshot has no cultivation rows")
        seen: set[str] = set()
        output: list[dict[str, Any]] = []
        for raw in cultivation:
            row = _safe_row(raw)
            external_id = row["APPLICATION_NUMBER"] or row["LICENSE_NUMBER"]
            if not external_id or external_id in seen:
                raise SourceParseError("CCC cultivation application ID is missing or duplicated")
            seen.add(external_id)
            if not row["SUBMITTED_DATE"]:
                # Keep undated rows as history; assessment will reject them.
                event_date = None
                event_label = None
            else:
                event_datetime = _source_datetime(row["SUBMITTED_DATE"])
                event_date = event_datetime.date().isoformat()
                if event_datetime.date() > as_of:
                    raise SourceParseError("CCC application date is in the future")
                original = row["ORIGINAL_SUBMITTED_DATE"]
                original_day = _source_datetime(original).date() if original else None
                if original_day and original_day > event_datetime.date():
                    raise SourceParseError(
                        "CCC original filing date is later than the submitted event"
                    )
                event_label = (
                    "Application resubmitted date"
                    if original_day and original_day < event_datetime.date()
                    else "Application submitted date"
                )
                if (as_of - event_datetime.date()).days > max_event_age_days:
                    # Old application rows remain available as evidence/history, but do not
                    # enter an active discovery path solely because the snapshot is fresh.
                    event_label = f"Stale {event_label.lower()}"
            semantic = {key: row[key] for key in _SEMANTIC_FIELDS}
            semantic_hash = hashlib.sha256(
                json.dumps(semantic, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            safe_identity = row["APPLICATION_NUMBER"] or row["LICENSE_NUMBER"]
            event_title = (
                f"{row['BUSINESS_NAME']} — Massachusetts cultivation application {safe_identity}"
            )
            abstract = _abstract(row, event_label or "")
            permit = {
                "source_type": SOURCE_ID,
                "application_number": row["APPLICATION_NUMBER"],
                "license_number": row["LICENSE_NUMBER"],
                "business_name": row["BUSINESS_NAME"],
                "business_email": row["BUSINESS_EMAIL"],
                "business_phone": row["BUSINESS_PHONE"],
                "applicant_org": row["BUSINESS_NAME"],
                "applicant_role": "applicant organization",
                "application_status": row["APPLICATION_STATUS"],
                "application_stage": row["APPROVED_LICENSE_STAGE"],
                "license_status": row["LICENSE_STATUS"],
                "commence_operations_date": row["COMMENCE_OPERATIONS_DATE"],
                "final_licensure_date": row["CNB_DATE_OF_FINAL_LICENSURE"],
                "license_start_date": row["LIC_START_DATE"],
                "license_original_start_date": row["LIC_ORIGINAL_START_DATE"],
                "license_expiration_date": row["LIC_EXPIRATION_DATE"],
                "license_revocation_date": row["LIC_REVOCATION_DATE"] or row["LIC_REVOKE_DATE"],
                "license_surrendered_date": row["LIC_SURRENDERED_DATE"]
                or row["LIC_SURRENDER_DATE"],
                "license_suspended_start_date": row["LIC_SUSPENDED_START_DATE"]
                or row["LIC_SUSPENSION_START_DATE"],
                "license_suspended_end_date": row["LIC_SUSPENDED_END_DATE"]
                or row["LIC_SUSPENSION_END_DATE"],
                "address": " ".join(
                    part
                    for part in (row["ESTABLISHMENT_ADDRESS_1"], row["ESTABLISHMENT_ADDRESS_2"])
                    if part
                ),
                "city": row["ESTABLISHMENT_CITY"],
                "state": row["ESTABLISHMENT_STATE"],
                "zip": row["ESTABLISHMENT_ZIP"],
                "source_updated_date": updated.isoformat(),
                "source_fields": {
                    key: f"{key}: {value}" for key, value in semantic.items() if value
                },
            }
            output.append(
                {
                    "document_number": safe_identity,
                    "title": event_title,
                    "abstract": abstract,
                    "publication_date": None,
                    "event_date": event_date,
                    "event_date_label": event_label,
                    "html_url": source["endpoint"],
                    "extraction_location": f"CCC snapshot SHA-256 {snapshot_hash}",
                    "source_hash": semantic_hash,
                    "source_snapshot_hash": snapshot_hash,
                    "permit": permit,
                }
            )
        return output
    finally:
        if own_client:
            client.close()
