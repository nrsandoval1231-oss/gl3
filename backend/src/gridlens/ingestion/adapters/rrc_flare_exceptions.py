"""Bounded recent SWR 32 flare/vent exception application query."""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup, Tag

from gridlens.ingestion.adapters.bounded_http import ResponseTooLarge, read_bounded_response
from gridlens.ingestion.adapters.federal_register import SourceParseError

SOURCE_ID = "texas-rrc-flare-vent-exceptions"
QUERY_URL = "https://webapps.rrc.state.tx.us/swr32/publicquery.xhtml"
MAX_RESPONSE_BYTES = 2_000_000
MAX_RUN_BYTES = 20_000_000
PAGE_SIZE = 10
MAX_PAGES = 50
MAX_ROWS = PAGE_SIZE * MAX_PAGES
_DATE = re.compile(r"\d{2}/\d{2}/\d{4}")
_TOTAL = re.compile(r"Showing\s+(\d+)-(\d+)\s+out of\s+(\d+)\s+records")


def _hidden_form_values(form: Tag) -> dict[str, str]:
    values: dict[str, str] = {}
    for item in form.select("input[type=hidden]"):
        name = item.get("name")
        if not isinstance(name, str):
            continue
        value = item.get("value", "")
        if not isinstance(value, str):
            raise SourceParseError("RRC flare form contains a malformed hidden input")
        values[name] = value
    return values


def _date(value: str) -> date:
    try:
        return datetime.strptime(value, "%m/%d/%Y").date()
    except ValueError as exc:
        raise SourceParseError("RRC flare query returned a malformed date") from exc


def _post(
    client: httpx.Client,
    url: str,
    data: dict[str, str],
    state: dict[str, int],
    headers: dict[str, str] | None = None,
) -> tuple[httpx.Headers, bytes]:
    try:
        with client.stream("POST", url, data=data, headers=headers) as response:
            response.raise_for_status()
            size = 0
            parts = []
            for part in response.iter_bytes():
                size += len(part)
                state["bytes"] += len(part)
                if size > MAX_RESPONSE_BYTES or state["bytes"] > MAX_RUN_BYTES:
                    raise ResponseTooLarge("RRC flare response exceeds configured bound")
                parts.append(part)
            body = b"".join(parts)
    except (httpx.HTTPError, ResponseTooLarge) as exc:
        raise SourceParseError(f"RRC flare query failed: {type(exc).__name__}") from exc
    content_type = response.headers.get("content-type", "").lower()
    if not any(kind in content_type for kind in ("text/html", "text/xml", "application/xml")):
        raise SourceParseError("RRC flare query returned an unexpected content type")
    return response.headers, body


def parse_results(
    body: bytes,
    *,
    start: date,
    end: date,
    query_url: str = QUERY_URL,
    expected_first: int | None = None,
    expected_total: int | None = None,
) -> tuple[int, list[dict[str, Any]]]:
    if not body or len(body) > MAX_RESPONSE_BYTES:
        raise SourceParseError("RRC flare result page is empty or oversized")
    if body.lstrip().startswith(b"<?xml"):
        try:
            root = ET.fromstring(body)
        except ET.ParseError as exc:
            raise SourceParseError("RRC flare paginator response XML changed") from exc
        update = root.find('.//update[@id="pbqueryForm:pQueryTable"]')
        if update is None or update.text is None:
            raise SourceParseError("RRC flare paginator response omitted the results table")
        body = update.text.encode()
    soup = BeautifulSoup(body, "html.parser")
    paginator = soup.select_one("#pbqueryForm\\:pQueryTable_paginator_bottom .ui-paginator-current")
    match = _TOTAL.fullmatch(paginator.get_text(" ", strip=True) if paginator else "")
    if match:
        first, last, total = map(int, match.groups())
    elif expected_first is not None and expected_total is not None:
        first, total = expected_first, expected_total
        last = first + len(soup.select("tr[data-ri]")) - 1
    else:
        raise SourceParseError("RRC flare result count is missing or changed")
    rows = soup.select("#pbqueryForm\\:pQueryTable_data tr[data-ri]")
    if not rows and expected_first is not None:
        rows = soup.select("tr[data-ri]")
    if total == 0:
        empty = soup.select_one("#pbqueryForm\\:pQueryTable_data tr.ui-datatable-empty-message")
        if (
            first != 0
            or last != 0
            or rows
            or empty is None
            or "no results" not in empty.get_text(" ", strip=True).lower()
        ):
            raise SourceParseError("RRC flare zero-result page shape changed")
        return 0, []
    if (
        not rows
        or first < 1
        or last < first
        or last - first + 1 != len(rows)
        or (expected_first is not None and first != expected_first)
    ):
        raise SourceParseError("RRC flare query returned an unexpected empty or partial page")
    row_indexes = []
    for row in rows:
        row_index = row.get("data-ri")
        if not isinstance(row_index, str) or not row_index.isdigit():
            raise SourceParseError("RRC flare result row has a malformed offset")
        row_indexes.append(int(row_index))
    if row_indexes != list(range(first - 1, last)):
        raise SourceParseError("RRC flare result row offsets changed or repeated")
    output = []
    seen_filing_numbers: set[str] = set()
    for offset, row in enumerate(rows):
        cells = [" ".join(cell.stripped_strings) for cell in row.select(":scope > td")]
        if len(cells) != 12:
            raise SourceParseError("RRC flare result row schema changed")
        (
            _,
            _view,
            submitted_raw,
            filing,
            status,
            filing_type,
            operator_number,
            operator,
            property_name,
            effective_raw,
            expiration_raw,
            flare_district,
        ) = cells
        if (
            not filing.isdigit()
            or not operator_number.isdigit()
            or not operator
            or not property_name
            or filing in seen_filing_numbers
        ):
            raise SourceParseError(
                "RRC flare result lacks stable filing, operator, or property identity"
            )
        seen_filing_numbers.add(filing)
        submitted = _date(submitted_raw)
        if submitted < start or submitted > end:
            raise SourceParseError("RRC flare result escaped its submitted-date window")
        if status not in {
            "Submitted",
            "Under Review",
            "Returned",
            "Hearing Pending",
            "Denied",
            "Approved",
            "Resubmitted",
            "Cancelled",
            "Hearing Requested",
            "Cancel Pending",
        }:
            raise SourceParseError("RRC flare result has an unknown application status")
        effective = _date(effective_raw) if effective_raw else None
        expiration = _date(expiration_raw) if expiration_raw else None
        external_id = filing
        semantic = {
            "filing_number": filing,
            "submittal_date": submitted.isoformat(),
            "status": status,
            "filing_type": filing_type,
            "operator_number": operator_number,
            "operator": operator,
            "property": property_name,
            "authorized_effective_date": effective.isoformat() if effective else None,
            "authorized_expiration_date": expiration.isoformat() if expiration else None,
            "flare_vent_district": flare_district,
        }
        title = f"Texas SWR 32 flare/vent exception application {filing} — {operator}"
        abstract = "\n".join(
            [
                f"Filing number: {filing}",
                f"Submittal date: {submitted.isoformat()}",
                f"Application status: {status}",
                f"Filing type: {filing_type}",
                f"Operator number: {operator_number}",
                f"Operator: {operator}",
                f"Property: {property_name}",
                "Authorized effective date (list field): "
                f"{effective.isoformat() if effective else 'Unknown'}",
                "Authorized expiration date (list field): "
                f"{expiration.isoformat() if expiration else 'Unknown'}",
                f"Flare/vent location district: {flare_district or 'Unknown'}",
                "This is an R-32 exception application record, not measured or confirmed actual "
                "flaring/venting. Requested gas volume, composition, continuous flow, generator "
                "fit, MW, rental demand, buyer, and buying authority are Unknown.",
            ]
        )
        output.append(
            {
                "document_number": external_id,
                "title": title,
                "abstract": abstract,
                "publication_date": None,
                "event_date": submitted.isoformat(),
                "event_date_label": "RRC R-32 application submittal date",
                "html_url": query_url,
                "extraction_location": (
                    f"RRC SWR 32 public query result row {first + offset}; "
                    f"filing {filing}; operator {operator_number}"
                ),
                "source_hash": hashlib.sha256(
                    json.dumps(semantic, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
                "permit": {
                    "source_type": SOURCE_ID,
                    "application_number": filing,
                    "row_id": external_id,
                    "operator": operator,
                    "operator_number": operator_number,
                    "property": property_name,
                    "status": status,
                    "filing_type": filing_type,
                    "submittal_date": submitted.isoformat(),
                    "authorized_effective_date": effective.isoformat() if effective else None,
                    "authorized_expiration_date": expiration.isoformat() if expiration else None,
                    "flare_vent_district": flare_district or None,
                    "location": (
                        "Texas RRC SWR 32 application; physical flare/vent location Unknown"
                    ),
                },
            }
        )
    return total, output


def retrieve(
    source: dict[str, Any], client: httpx.Client | None = None, *, today: date | None = None
) -> list[dict[str, Any]]:
    if (
        source.get("id") != SOURCE_ID
        or source.get("endpoint") != QUERY_URL
        or source.get("retrieval_method") != "rrc-flare-exceptions"
    ):
        raise SourceParseError("RRC flare source is outside its reviewed official endpoint")
    query = source.get("query", {})
    window = query.get("window_days")
    if (
        not isinstance(window, int)
        or not 1 <= window <= 7
        or query.get("rows_per_page") != PAGE_SIZE
        or query.get("max_pages") != MAX_PAGES
        or query.get("max_records") != MAX_ROWS
        or query.get("max_response_bytes") != MAX_RESPONSE_BYTES
        or query.get("max_run_bytes") != MAX_RUN_BYTES
    ):
        raise SourceParseError("RRC flare query exceeds the reviewed bounded configuration")
    parsed = urlparse(QUERY_URL)
    if parsed.scheme != "https" or parsed.hostname != "webapps.rrc.state.tx.us":
        raise SourceParseError("RRC flare host is not the reviewed official host")
    end = today or datetime.now(UTC).astimezone(ZoneInfo("America/Chicago")).date()
    start = end - timedelta(days=window - 1)
    http = client or httpx.Client(
        timeout=25, follow_redirects=False, headers={"Accept": "text/html"}
    )
    try:
        state = {"bytes": 0}
        response, body = read_bounded_response(http, QUERY_URL, MAX_RESPONSE_BYTES)
        state["bytes"] = len(body)
        if state["bytes"] > MAX_RUN_BYTES:
            raise SourceParseError("RRC flare run exceeded its byte bound")
        if "text/html" not in response.get("content-type", "").lower():
            raise SourceParseError("RRC flare query landing page is not HTML")
        soup = BeautifulSoup(body, "html.parser")
        form = soup.select_one("form#pbqueryForm")
        if form is None:
            raise SourceParseError("RRC flare query form changed")
        action = form.get("action") or QUERY_URL
        from_input = soup.select_one("input[name='pbqueryForm:submittalDateFrom_input']")
        to_input = soup.select_one("input[name='pbqueryForm:submittalDateTo_input']")
        if from_input is None or to_input is None:
            raise SourceParseError("RRC flare submittal date fields changed")
        data = _hidden_form_values(form)
        for item in form.select("select[name]"):
            name = item.get("name")
            if not isinstance(name, str):
                raise SourceParseError("RRC flare form contains a malformed select field")
            selected = item.select_one("option[selected]")
            value = selected.get("value", "") if selected is not None else ""
            if not isinstance(value, str):
                raise SourceParseError("RRC flare form contains a malformed select value")
            data[name] = value
        data.update(
            {
                "pbqueryForm:submittalDateFrom_input": start.strftime("%m/%d/%Y"),
                "pbqueryForm:submittalDateTo_input": end.strftime("%m/%d/%Y"),
                "pbqueryForm:pQueryTable_rppDD": str(PAGE_SIZE),
                "pbqueryForm:searchExceptions": "pbqueryForm:searchExceptions",
            }
        )
        target = str(httpx.URL(QUERY_URL).join(httpx.URL(str(action))))
        parsed_target = urlparse(target)
        if (
            parsed_target.scheme != "https"
            or parsed_target.hostname != "webapps.rrc.state.tx.us"
            or parsed_target.path != "/swr32/publicquery.xhtml"
        ):
            raise SourceParseError(
                "RRC flare query form action changed outside its official endpoint"
            )
        response, page = _post(http, target, data, state)
        total, records = parse_results(page, start=start, end=end, query_url=QUERY_URL)
        if total > min(MAX_ROWS, int(query["max_records"])):
            raise SourceParseError(
                "RRC flare recent-window result exceeds its complete paging bound"
            )
        if len(records) != min(total, PAGE_SIZE):
            raise SourceParseError("RRC flare first result page is incomplete")
        result_soup = BeautifulSoup(page, "html.parser")
        result_form = result_soup.select_one("form#pbqueryForm")
        if result_form is None:
            raise SourceParseError("RRC flare search response lost its form state")
        page_state = _hidden_form_values(result_form)
        if not page_state.get("javax.faces.ViewState"):
            raise SourceParseError("RRC flare search response omitted JSF state")
        for offset in range(PAGE_SIZE, total, PAGE_SIZE):
            partial = {
                key: value
                for key, value in page_state.items()
                if key.startswith("pbqueryForm:pQueryTable_")
                or key in {"pbqueryForm", "javax.faces.ViewState"}
            }
            partial.update(
                {
                    "javax.faces.partial.ajax": "true",
                    "javax.faces.source": "pbqueryForm:pQueryTable",
                    "javax.faces.partial.execute": "pbqueryForm:pQueryTable",
                    "javax.faces.partial.render": "pbqueryForm:pQueryTable",
                    "javax.faces.behavior.event": "page",
                    "javax.faces.partial.event": "page",
                    "pbqueryForm:pQueryTable_pagination": "true",
                    "pbqueryForm:pQueryTable_first": str(offset),
                    "pbqueryForm:pQueryTable_rows": str(PAGE_SIZE),
                    "pbqueryForm:pQueryTable_skipChildren": "true",
                    "pbqueryForm:pQueryTable_encodeFeature": "true",
                }
            )
            headers, xml_body = _post(
                http,
                target,
                partial,
                state,
                {
                    "Faces-Request": "partial/ajax",
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "application/xml, text/xml, */*; q=0.01",
                },
            )
            if "xml" not in headers.get("content-type", "").lower():
                raise SourceParseError("RRC flare page response was not JSF partial XML")
            page_total, page_records = parse_results(
                xml_body,
                start=start,
                end=end,
                query_url=QUERY_URL,
                expected_first=offset + 1,
                expected_total=total,
            )
            expected_page_records = min(PAGE_SIZE, total - offset)
            if page_total != total or len(page_records) != expected_page_records:
                raise SourceParseError("RRC flare paginator count or page length changed")
            try:
                xml_root = ET.fromstring(xml_body)
            except ET.ParseError as exc:
                raise SourceParseError("RRC flare paginator response XML changed") from exc
            view_state = next(
                (
                    node
                    for node in xml_root.findall(".//update")
                    if "javax.faces.ViewState" in node.attrib.get("id", "")
                ),
                None,
            )
            if view_state is None or not view_state.text:
                raise SourceParseError("RRC flare paginator response omitted JSF state")
            page_state["javax.faces.ViewState"] = view_state.text
            records.extend(page_records)
            if len({record["document_number"] for record in records}) != len(records):
                raise SourceParseError("RRC flare filing identity repeated across pages")
        if len(records) != total:
            raise SourceParseError("RRC flare recent-window result set is incomplete")
        return records
    finally:
        if client is None:
            http.close()
