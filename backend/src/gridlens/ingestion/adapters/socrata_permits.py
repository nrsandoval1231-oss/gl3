"""Bounded, fixed-query retrieval for official city permit datasets."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlparse

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
        **{
            key: key
            for key in (
                "contractor_trade",
                "contractor_company_name",
                "contractor_full_name",
                "contractor_phone",
                "applicant_full_name",
                "applicant_org",
                "applicant_phone",
            )
        },
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
        "parcel": "pin_list",
        "application_start": "application_start_date",
        "milestone": "permit_milestone",
        **{
            f"contact_{i}_{part}": f"contact_{i}_{part}"
            for i in range(1, 16)
            for part in ("type", "name")
        },
    },
}
SYSTEM_FIELD_SELECTS = {
    "chicago-building-permits": (
        "id,issue_date,work_description,work_type,permit_type,permit_status,"
        "street_number,street_direction,street_name,permit_,reported_cost,pin_list,:updated_at,"
        "application_start_date,permit_milestone,"
        + ",".join(f"contact_{i}_{part}" for i in range(1, 16) for part in ("type", "name"))
    )
}
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
            "permit_class_mapped='Commercial' "
            "AND permit_type_desc IN ('Building Permit','Electrical Permit')"
        ),
        "seattle-building-permits": (
            "permitclassmapped='Non-Residential' AND permittypemapped='Building'"
        ),
        "chicago-building-permits": (
            "(permit_type IN ('PERMIT - NEW CONSTRUCTION','PERMIT - RENOVATION/ALTERATION') "
            "OR (permit_type='PERMIT – EXPRESS PERMIT PROGRAM' "
            "AND work_type='Electrical Work'))"
        ),
    }
    issue_filter = (
        f"({date_field} >= '{start.isoformat()}T00:00:00.000' "
        f"AND {date_field} <= '{today.isoformat()}T23:59:59.999')"
    )
    modified_field = fields.get("modified_date")
    modified_timestamp_suffix = "Z" if modified_field and modified_field.startswith(":") else ""
    modified_lower = f"{modified_start.isoformat()}T00:00:00.000{modified_timestamp_suffix}"
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
    backfill = query.get("data_center_backfill")
    if backfill is not None:
        if source_id != "austin-building-permits" or not isinstance(backfill, dict):
            raise SourceParseError("Unsupported permit backfill")
        try:
            backfill_start = date.fromisoformat(backfill["start"])
            backfill_end = date.fromisoformat(backfill["end"])
        except (ValueError, KeyError, TypeError) as exc:
            raise SourceParseError("Malformed permit backfill dates") from exc
        if (
            not backfill_start <= backfill_end <= today
            or (backfill_end - backfill_start).days > 365
        ):
            raise SourceParseError("Permit backfill exceeds one year or includes future dates")
        backfill_terms = ["data center", "data centre"]
        if backfill.get("include_explicit_power") is True:
            backfill_terms += ["construction power", "temporary service", "t-pole"]
        backfill_predicate = " OR ".join(
            f"lower(description) LIKE '%{term}%'" for term in backfill_terms
        )
        backfill_where = (
            f"{date_field} >= '{backfill_start.isoformat()}T00:00:00.000' "
            f"AND {date_field} <= '{backfill_end.isoformat()}T23:59:59.999' "
            f"AND ({class_filters[source_id]}) "
            f"AND ({backfill_predicate})"
        )
        where = f"({where}) OR ({backfill_where})"
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
                in_backfill = bool(
                    backfill is not None
                    and backfill_start <= issue_date <= backfill_end
                    and any(
                        term in _field(row, fields["description"]).lower()
                        for term in backfill_terms
                    )
                )
                if not in_issue_window and not in_modified_window and not in_backfill:
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
                output.append(render_record(source, row))
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


def retrieve_collection_segment(
    source: dict[str, Any],
    lane: str,
    window_start: date,
    window_end: date,
    cursor: dict[str, Any],
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Fetch at most one date/page segment for durable ingestion recovery."""
    source_id = source.get("id")
    if not isinstance(source_id, str) or source_id not in HOSTS:
        raise SourceParseError("Permit source ID is not configured")
    expected_host = HOSTS[source_id]
    parsed = urlparse(str(source.get("endpoint") or ""))
    if parsed.scheme != "https" or parsed.hostname != expected_host or parsed.query:
        raise SourceParseError("Permit endpoint is outside its configured official host")
    fields = MAPS[source_id]
    modified_field = fields.get("modified_date")
    is_modified = lane.startswith("modified_")
    if (is_modified and not modified_field) or lane not in {
        "issue_recent",
        "issue_history",
        "issue_backfill",
        "modified_recent",
        "modified_history",
    }:
        raise SourceParseError("Permit collection lane is unsupported")
    if window_end < window_start or (window_end - window_start).days >= 7:
        raise SourceParseError("Permit collection window exceeds seven days")
    if window_end > datetime.now(UTC).date():
        raise SourceParseError("Permit collection window extends into the future")
    query = source.get("query", {})
    if (
        query.get("per_page") != PAGE_SIZE
        or not 1 <= query.get("max_pages", 0) <= MAX_PAGES
        or query.get("max_response_bytes") != MAX_RESPONSE
        or query.get("max_run_bytes") != MAX_RUN
    ):
        raise SourceParseError("Permit collection bounds differ from the reviewed configuration")
    day_value = cursor.get("day", window_start.isoformat())
    try:
        day = date.fromisoformat(str(day_value))
    except ValueError as exc:
        raise SourceParseError("Permit collection cursor has an invalid date") from exc
    if not window_start <= day <= window_end:
        raise SourceParseError("Permit collection cursor escaped its date window")

    row_field = fields["row"]
    date_field = modified_field if is_modified else fields["date"]
    class_filters = {
        "austin-building-permits": (
            "permit_class_mapped='Commercial' "
            "AND permit_type_desc IN ('Building Permit','Electrical Permit')"
        ),
        "seattle-building-permits": (
            "permitclassmapped='Non-Residential' AND permittypemapped='Building'"
        ),
        "chicago-building-permits": (
            "(permit_type IN ('PERMIT - NEW CONSTRUCTION','PERMIT - RENOVATION/ALTERATION') "
            "OR (permit_type='PERMIT – EXPRESS PERMIT PROGRAM' "
            "AND work_type='Electrical Work'))"
        ),
    }
    suffix = "Z" if source_id == "chicago-building-permits" and is_modified else ""
    lower = f"{day.isoformat()}T00:00:00.000{suffix}"
    upper = f"{day.isoformat()}T23:59:59.999{suffix}"
    if lane == "issue_backfill":
        backfill = query.get("data_center_backfill")
        if source_id != "austin-building-permits" or not isinstance(backfill, dict):
            raise SourceParseError("Permit backfill lane is not configured for this source")
        try:
            backfill_start = date.fromisoformat(backfill["start"])
            backfill_end = date.fromisoformat(backfill["end"])
        except (ValueError, KeyError, TypeError) as exc:
            raise SourceParseError("Permit backfill dates are malformed") from exc
        if (
            not backfill_start <= day <= backfill_end <= datetime.now(UTC).date()
            or (backfill_end - backfill_start).days > 365
        ):
            raise SourceParseError("Permit backfill window exceeds its configured bound")
        terms = ["data center", "data centre"]
        if backfill.get("include_explicit_power") is True:
            terms.extend(("construction power", "temporary service", "t-pole"))
        predicate = " OR ".join(f"lower({fields['description']}) LIKE '%{term}%'" for term in terms)
        base_where = (
            f"{fields['date']} >= '{lower}' AND {fields['date']} <= '{upper}' "
            f"AND ({class_filters[source_id]}) AND ({predicate})"
        )
    elif is_modified:
        base_where = (
            f"{fields['date']} IS NOT NULL AND {fields['date']} <= "
            f"'{datetime.now(UTC).date().isoformat()}T23:59:59.999' "
            f"AND {date_field} >= '{lower}' AND {date_field} <= '{upper}' "
            f"AND ({class_filters[source_id]})"
        )
    else:
        base_where = (
            f"{date_field} >= '{lower}' AND {date_field} <= '{upper}' "
            f"AND ({class_filters[source_id]})"
        )
    where = base_where
    after_value = cursor.get("after_value") if is_modified else day.isoformat()
    after_id = cursor.get("after_id")
    if after_id is not None:
        if not isinstance(after_id, str) or not after_id:
            raise SourceParseError("Permit collection cursor has an invalid row key")
        if len(after_id) > 256:
            raise SourceParseError("Permit collection cursor row key is too long")
        # Publisher row keys are opaque text, including Chicago Express IDs.
        row_literal = "'" + after_id.replace("'", "''") + "'"
        if is_modified:
            if not isinstance(after_value, str):
                raise SourceParseError("Permit modification cursor has no timestamp key")
            escaped = after_value.replace("'", "''")
            where += (
                f" AND ({date_field} > '{escaped}' OR ({date_field} = '{escaped}' "
                f"AND {row_field} > {row_literal}))"
            )
        else:
            where += f" AND {row_field} > {row_literal}"

    select_fields = SYSTEM_FIELD_SELECTS.get(source_id)
    params_rows: dict[str, str | int] = {
        "$where": where,
        "$order": f"{date_field} ASC,{row_field} ASC",
        "$limit": PAGE_SIZE,
    }
    if select_fields:
        params_rows["$select"] = select_fields
    http = client or httpx.Client(
        timeout=20, follow_redirects=False, headers={"Accept": "application/json"}
    )
    run_bytes = 0

    def count_rows(count_where: str) -> int:
        nonlocal run_bytes
        try:
            headers, body = read_bounded_response(
                http,
                source["endpoint"],
                MAX_RESPONSE,
                {"$select": "count(*) AS row_count", "$where": count_where},
            )
        except (httpx.HTTPError, ResponseTooLarge) as exc:
            raise SourceParseError(f"Permit segment count failed: {type(exc).__name__}") from exc
        run_bytes += len(body)
        if run_bytes > MAX_RUN or "json" not in headers.get("content-type", "").lower():
            raise SourceParseError("Permit segment count exceeded bounds or was non-JSON")
        try:
            payload = json.loads(body)
            count = int(payload[0]["row_count"])
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            raise SourceParseError("Permit segment count response is malformed") from exc
        if count < 0:
            raise SourceParseError("Permit segment count is negative")
        return count

    def reset_cursor(expected: int) -> dict[str, Any]:
        return {"day": day.isoformat(), "expected": expected, "scanned": 0}

    try:
        expected = count_rows(base_where)
        prior_expected = cursor.get("expected")
        scanned = cursor.get("scanned", 0)
        if type(scanned) is not int or scanned < 0:
            raise SourceParseError("Permit collection cursor has an invalid count")
        count_where = base_where
        if prior_expected is not None and (
            type(prior_expected) is not int or prior_expected != expected
        ):
            return {
                "records": [],
                "cursor": reset_cursor(expected),
                "partial": True,
                "error_class": "ResultCountChanged",
                "window_complete": False,
                "expected_count": expected,
                "observed_count": scanned,
            }
        expected = expected if prior_expected is None else prior_expected
        if expected == 0:
            next_day = day + timedelta(days=1)
            return {
                "records": [],
                "cursor": {"day": next_day.isoformat()} if next_day <= window_end else {},
                "partial": False,
                "window_complete": next_day > window_end,
                "expected_count": 0,
                "observed_count": 0,
            }
        if scanned >= expected:
            raise SourceParseError("Permit collection cursor exceeds the declared row count")
        try:
            headers, body = read_bounded_response(
                http, source["endpoint"], MAX_RESPONSE, params_rows
            )
        except (httpx.HTTPError, ResponseTooLarge) as exc:
            raise SourceParseError(f"Permit segment page failed: {type(exc).__name__}") from exc
        run_bytes += len(body)
        if run_bytes > MAX_RUN or "json" not in headers.get("content-type", "").lower():
            raise SourceParseError("Permit segment exceeded bounds or returned non-JSON")
        try:
            rows = json.loads(body)
        except (ValueError, UnicodeDecodeError) as exc:
            raise SourceParseError("Permit segment returned malformed JSON") from exc
        if not isinstance(rows, list) or not rows or len(rows) > PAGE_SIZE:
            raise SourceParseError("Permit segment page is empty or exceeds its row bound")
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        previous: tuple[str, str] | None = None
        for row in rows:
            if not isinstance(row, dict):
                raise SourceParseError("Permit segment row has invalid shape")
            missing = [fields[key] for key in ("row", "date", "description") if fields[key]]
            if any(name not in row for name in missing):
                raise SourceParseError("Permit segment response schema changed")
            row_id = _field(row, row_field)
            issue_day = _date(_field(row, fields["date"]))
            modified_value = _field(row, modified_field)
            sort_date = _date(modified_value) if is_modified else issue_day
            if not row_id or row_id in seen or issue_day > datetime.now(UTC).date():
                raise SourceParseError("Permit segment has invalid or duplicate row identity")
            if source_id == "austin-building-permits":
                class_valid = _field(row, fields["class"]) == "Commercial" and _field(
                    row, fields["type"]
                ) in {"Building Permit", "Electrical Permit"}
            elif source_id == "seattle-building-permits":
                class_valid = (
                    _field(row, fields["class"]) == "Non-Residential"
                    and _field(row, fields["work"]) == "Building"
                )
            else:
                permit_type = _field(row, fields["type"])
                class_valid = permit_type in {
                    "PERMIT - NEW CONSTRUCTION",
                    "PERMIT - RENOVATION/ALTERATION",
                } or (
                    permit_type == "PERMIT – EXPRESS PERMIT PROGRAM"
                    and _field(row, fields["work"]) == "Electrical Work"
                )
            if not class_valid:
                raise SourceParseError("Permit segment row escaped the reviewed class filter")
            if lane == "issue_backfill":
                backfill = query.get("data_center_backfill", {})
                terms = ["data center", "data centre"]
                if backfill.get("include_explicit_power") is True:
                    terms.extend(("construction power", "temporary service", "t-pole"))
                description = _field(row, fields["description"]).lower()
                if not any(term in description for term in terms):
                    raise SourceParseError("Permit segment row escaped the backfill keyword filter")
            if sort_date != day:
                raise SourceParseError("Permit segment row escaped its date window")
            sort_key = (
                modified_value if is_modified else issue_day.isoformat(),
                row_id,
            )
            if previous is not None and sort_key < previous:
                raise SourceParseError("Permit segment rows are out of stable key order")
            if after_id is not None:
                prior_key = (str(after_value) if is_modified else day.isoformat(), after_id)
                if sort_key <= prior_key:
                    raise SourceParseError("Permit segment row did not advance its keyset")
            seen.add(row_id)
            previous = sort_key
            records.append(render_record(source, row))
        after_count = count_rows(count_where)
        page_total = scanned + len(rows)
        if after_count != expected or page_total > expected:
            return {
                "records": records,
                "cursor": reset_cursor(after_count),
                "partial": True,
                "error_class": "ResultCountChanged",
                "window_complete": False,
                "expected_count": after_count,
                "observed_count": page_total,
            }
        day_complete = page_total == expected
        if not day_complete and len(rows) != PAGE_SIZE:
            raise SourceParseError("Permit segment ended before the declared count")
        next_cursor: dict[str, Any]
        if day_complete:
            next_day = day + timedelta(days=1)
            next_cursor = {"day": next_day.isoformat()} if next_day <= window_end else {}
            window_complete = next_day > window_end
        else:
            last_row = rows[-1]
            next_cursor = {
                "day": day.isoformat(),
                "expected": expected,
                "scanned": page_total,
                "after_id": _field(last_row, row_field),
                **({"after_value": _field(last_row, modified_field)} if is_modified else {}),
            }
            window_complete = False
        return {
            "records": records,
            "cursor": next_cursor,
            "partial": False,
            "window_complete": window_complete,
            "expected_count": expected,
            "observed_count": page_total,
        }
    finally:
        if client is None:
            http.close()


def render_record(source: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    """Render a validated official row identically for ingestion and exact research."""
    source_id = source["id"]
    fields = MAPS[source_id]
    expected_host = HOSTS[source_id]
    modified_field = fields.get("modified_date")
    if any(fields[k] not in row for k in ("row", "date", "description")):
        raise SourceParseError("Permit response schema changed")
    row_id = _field(row, fields["row"])
    issue_date = _date(_field(row, fields["date"]))
    if not row_id or issue_date > datetime.now(UTC).date():
        raise SourceParseError("Permit identity or issue date is invalid")
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
    if source_id == "chicago-building-permits":
        citation = (
            source["endpoint"]
            + "?"
            + urlencode({"$where": "id='" + row_id.replace("'", "''") + "'", "$limit": 1})
        )
    semantic = {key: _field(row, name) for key, name in fields.items() if name}
    retained_fields = {
        label: _field(row, field_name)
        for label, field_name in fields.items()
        if field_name and _field(row, field_name)
    }
    retained_fields["address"] = address
    abstract = "\n".join(f"{label}: {value}" for label, value in retained_fields.items())
    permit_type = _field(row, fields["type"]) or _field(row, fields["work"]) or "permit"
    title = f"{source['city']} building permit {row_id} — {permit_type[:120]}"
    return {
        "document_number": row_id,
        "title": title,
        "abstract": abstract,
        "publication_date": issue_date.isoformat(),
        "html_url": citation,
        "extraction_location": (f"Official {source['city']} permit fields; dated issue and row ID"),
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
            json.dumps(semantic, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest(),
    }
