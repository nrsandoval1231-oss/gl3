"""Bounded, fixed-query retrieval for official city permit datasets."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import httpx

from gridlens.ingestion.adapters.bounded_http import ResponseTooLarge, read_bounded_response
from gridlens.ingestion.adapters.federal_register import SourceParseError

HOSTS = {
    "austin-building-permits": "data.austintexas.gov",
    "seattle-building-permits": "data.seattle.gov",
    "chicago-building-permits": "data.cityofchicago.org",
}
MAPS: dict[str, dict[str, Any]] = {
    "austin-building-permits": {
        "row": "permit_number",
        "date": "issue_date",
        "modified_date": "statusdate",
        "description": "description",
        "class": "permit_class_mapped",
        "work": "work_class",
        "type": "permit_type_desc",
        "status": "status_current",
        "address": "original_address1",
        "city": "original_city",
        "state": "original_state",
        "link": "link",
        "project": "project_id",
        "cost": "total_job_valuation",
        "area": "total_new_add_sqft",
    },
    "seattle-building-permits": {
        "row": "permitnum",
        "date": "issueddate",
        "modified_date": None,
        "description": "description",
        "class": "permitclassmapped",
        "work": "permittypemapped",
        "type": "permittypedesc",
        "status": "statuscurrent",
        "address": "originaladdress1",
        "city": None,
        "state": None,
        "link": "link",
        "project": "parentpermitnum",
        "cost": "estprojectcost",
        "area": None,
    },
    "chicago-building-permits": {
        "row": "id",
        "date": "issue_date",
        "modified_date": ":updated_at",
        "description": "work_description",
        "class": None,
        "work": "work_type",
        "type": "permit_type",
        "status": "permit_status",
        "address": "street_number",
        "street_direction": "street_direction",
        "street_name": "street_name",
        "city": None,
        "state": None,
        "link": None,
        "project": "permit_",
        "cost": "reported_cost",
        "area": None,
    },
}
SYSTEM_FIELD_SELECTS = {"chicago-building-permits": "*, :updated_at"}
PAGE_SIZE = 1000
MAX_RESPONSE = 2_000_000
MAX_RUN = 20_000_000
MAX_PAGES = 20


def _field(row: dict[str, Any], key: str | None) -> str:
    value = row.get(key) if key else None
    if isinstance(value, dict):
        value = value.get("url")
    return " ".join(str(value or "").split())


def _date(value: str) -> date:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError as exc:
        raise SourceParseError("Permit row has malformed issue date") from exc


def retrieve(source: dict[str, Any], client: httpx.Client | None = None) -> list[dict[str, Any]]:
    source_id = source.get("id")
    if not isinstance(source_id, str) or source_id not in HOSTS or source_id not in MAPS:
        raise SourceParseError("Permit source ID is not configured")
    expected_host = HOSTS[source_id]
    parsed = urlparse(source.get("endpoint", ""))
    if not expected_host or parsed.scheme != "https" or parsed.hostname != expected_host:
        raise SourceParseError("Permit endpoint is outside its configured official host")
    fields = MAPS[source_id]
    query = source.get("query", {})
    window = int(query.get("window_days", 30))
    if not 1 <= window <= 90:
        raise SourceParseError("Permit issue-date window is out of bounds")
    modified_window = int(query.get("modified_window_days", 7))
    if not 1 <= modified_window <= 90:
        raise SourceParseError("Permit modification window is out of bounds")
    today = datetime.now(UTC).date()
    start = today - timedelta(days=window)
    modified_start = today - timedelta(days=modified_window)
    # Fixed field name from the reviewed map; only a literal date enters SoQL.
    date_field = fields["date"]
    class_filters = {
        "austin-building-permits": (
            "permit_class_mapped='Commercial' AND permit_type_desc='Building Permit'"
        ),
        "seattle-building-permits": (
            "permitclassmapped='Non-Residential' AND permittypemapped='Building'"
        ),
        "chicago-building-permits": (
            "permit_type IN ('PERMIT - NEW CONSTRUCTION','PERMIT - RENOVATION/ALTERATION')"
        ),
    }
    issue_filter = (
        f"({date_field} >= '{start.isoformat()}T00:00:00.000' "
        f"AND {date_field} <= '{today.isoformat()}T23:59:59.999')"
    )
    modified_field = fields.get("modified_date")
    modified_timestamp_suffix = "Z" if modified_field and modified_field.startswith(":") else ""
    modified_lower = (
        f"{modified_start.isoformat()}T00:00:00.000{modified_timestamp_suffix}"
    )
    modified_upper = f"{today.isoformat()}T23:59:59.999{modified_timestamp_suffix}"
    modified_filter = (
        f" OR ({modified_field} >= '{modified_lower}' AND {modified_field} <= '{modified_upper}')"
        if modified_field
        else ""
    )
    where = (
        f"{date_field} IS NOT NULL AND {date_field} <= '{today.isoformat()}T23:59:59.999' "
        f"AND ({issue_filter}{modified_filter}) AND ({class_filters[source_id]})"
    )
    params_base: dict[str, str | int] = {
        "$where": where,
        "$order": f"{date_field} ASC,{fields['row']} ASC",
        "$limit": PAGE_SIZE,
    }
    if source_id in SYSTEM_FIELD_SELECTS:
        params_base["$select"] = SYSTEM_FIELD_SELECTS[source_id]
    http = client or httpx.Client(
        timeout=20, follow_redirects=False, headers={"Accept": "application/json"}
    )
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    run_bytes = 0

    def read_count() -> int:
        nonlocal run_bytes
        try:
            count_params: dict[str, str | int] = {
                "$select": "count(*) AS row_count",
                "$where": where,
            }
            headers, body = read_bounded_response(
                http,
                source["endpoint"],
                MAX_RESPONSE,
                count_params,
            )
            run_bytes += len(body)
            if run_bytes > MAX_RUN or "json" not in headers.get("content-type", "").lower():
                raise SourceParseError("Permit completeness count exceeded bounds or was non-JSON")
            count_rows = json.loads(body)
            return int(count_rows[0]["row_count"])
        except (
            httpx.HTTPError,
            ResponseTooLarge,
            ValueError,
            KeyError,
            IndexError,
            TypeError,
        ) as exc:
            if isinstance(exc, SourceParseError):
                raise
            raise SourceParseError("Permit completeness count failed") from exc

    try:
        expected_count = read_count()
        if expected_count < 1 or expected_count > PAGE_SIZE * MAX_PAGES:
            raise SourceParseError("Permit issue-date query is empty or exceeds pagination bound")
        for page in range(MAX_PAGES):
            params = {**params_base, "$offset": page * PAGE_SIZE}
            try:
                headers, body = read_bounded_response(
                    http, source["endpoint"], MAX_RESPONSE, params
                )
            except (httpx.HTTPError, ResponseTooLarge) as exc:
                raise SourceParseError(
                    f"Permit page retrieval failed: {type(exc).__name__}"
                ) from exc
            run_bytes += len(body)
            if run_bytes > MAX_RUN:
                raise SourceParseError("Permit run exceeded byte limit")
            if "json" not in headers.get("content-type", "").lower():
                raise SourceParseError("Permit source returned non-JSON content")
            try:
                rows = json.loads(body)
            except (ValueError, UnicodeDecodeError) as exc:
                raise SourceParseError("Permit source returned malformed JSON") from exc
            if not isinstance(rows, list):
                raise SourceParseError("Permit response is not a row array")
            if not rows:
                if page == 0:
                    raise SourceParseError(
                        "Permit source returned an unexpected empty issue-date window"
                    )
                raise SourceParseError("Permit pages ended before the exact count")
            for row in rows:
                if not isinstance(row, dict):
                    raise SourceParseError("Permit row has invalid shape")
                missing = [
                    fields[k]
                    for k in ("row", "date", "description")
                    if fields[k] and fields[k] not in row
                ]
                if missing:
                    raise SourceParseError("Permit response schema changed")
                row_id = _field(row, fields["row"])
                issue_date = _date(_field(row, fields["date"]))
                modified_value = _field(row, modified_field)
                modified_date = _date(modified_value) if modified_value else None
                in_issue_window = start <= issue_date <= today
                in_modified_window = bool(
                    modified_date and modified_start <= modified_date <= today
                )
                if not in_issue_window and not in_modified_window:
                    raise SourceParseError("Permit row escaped issue and modification windows")
                if not row_id or row_id in seen:
                    raise SourceParseError("Permit page has missing or duplicate stable row ID")
                seen.add(row_id)
                sort_key = (issue_date, row_id)
                prior_sort_key = (
                    (
                        date.fromisoformat(output[-1]["event_date"]),
                        output[-1]["document_number"],
                    )
                    if output
                    else None
                )
                if prior_sort_key is not None and sort_key < prior_sort_key:
                    raise SourceParseError("Permit rows are not in requested date and ID order")
                address = _field(row, fields["address"])
                if source_id == "chicago-building-permits":
                    address = " ".join(
                        filter(
                            None,
                            [address, _field(row, "street_direction"), _field(row, "street_name")],
                        )
                    )
                city = _field(row, fields["city"]) or source["city"]
                state = _field(row, fields["state"]) or source["state"]
                link = _field(row, fields["link"])
                link_host = urlparse(link).hostname if link else None
                if link and link_host not in {expected_host, source.get("record_link_host")}:
                    link = ""
                citation = link or source["endpoint"]
                semantic = {key: _field(row, name) for key, name in fields.items() if name}
                retained_fields = {
                    label: _field(row, field_name)
                    for label, field_name in fields.items()
                    if field_name and _field(row, field_name)
                }
                abstract = "\n".join(
                    f"{label}: {value}" for label, value in retained_fields.items()
                )
                permit_type = _field(row, fields["type"]) or _field(row, fields["work"]) or "permit"
                title = f"{source['city']} building permit {row_id} — {permit_type[:120]}"
                output.append(
                    {
                        "document_number": row_id,
                        "title": title,
                        "abstract": abstract,
                        "publication_date": issue_date.isoformat(),
                        "html_url": citation,
                        "extraction_location": (
                            f"Official {source['city']} permit fields; dated issue and row ID"
                        ),
                        "event_date": issue_date.isoformat(),
                        "permit": {
                            "city": city,
                            "state": state,
                            "address": address,
                            "class": _field(row, fields["class"]),
                            "work": _field(row, fields["work"]),
                            "type": _field(row, fields["type"]),
                            "status": _field(row, fields["status"]) or "Unknown",
                            "source_modified_at": _field(row, modified_field) or None,
                            "description": _field(row, fields["description"]),
                            "cost": _field(row, fields["cost"]),
                            "area": _field(row, fields["area"]),
                            "project": _field(row, fields["project"]),
                            "row_id": row_id,
                            "source_fields": {key: name for key, name in fields.items() if name},
                        },
                        "source_hash": hashlib.sha256(
                            json.dumps(
                                semantic, sort_keys=True, ensure_ascii=False, separators=(",", ":")
                            ).encode()
                        ).hexdigest(),
                    }
                )
            if len(output) == expected_count:
                if read_count() != expected_count:
                    raise SourceParseError("Permit count changed during pagination")
                return output
            if len(rows) < PAGE_SIZE:
                raise SourceParseError("Permit pages ended before the exact count")
        raise SourceParseError("Permit result exceeded pagination bound; run is incomplete")
    finally:
        if client is None:
            http.close()
