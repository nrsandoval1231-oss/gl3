from datetime import date

import httpx
import pytest
from bs4 import BeautifulSoup

from gridlens.domain.permit_interpretation import assess_permit, evaluator_version
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.rrc_flare_exceptions import (
    QUERY_URL,
    SOURCE_ID,
    parse_results,
    retrieve,
    retrieve_collection_segment,
)
from gridlens.ingestion.registry import load_registry

TODAY = date(2026, 10, 1)
SOURCE = next(item for item in load_registry() if item["id"] == SOURCE_ID)


def _row(
    *,
    filing: str = "35964",
    submittal: str = "10/01/2026",
    status: str = "Approved",
    filing_type: str = "New Exception",
    operator_no: str = "728874",
    operator: str = "ROSEWOOD RESOURCES, INC.",
    prop: str = "Gas Lease-03-5713",
    effective: str = "09/30/2026",
    expiration: str = "10/30/2026",
    district: str = "03",
) -> str:
    values = [
        "",
        "",
        submittal,
        filing,
        status,
        filing_type,
        operator_no,
        operator,
        prop,
        effective,
        expiration,
        district,
    ]
    cells = "".join(f"<td>{value}</td>" for value in values)
    return f'<tr data-ri="0">{cells}</tr>'


def _page(rows: str, total: int = 1, first: int = 1) -> bytes:
    if total == 0:
        return (
            b'<div id="pbqueryForm:pQueryTable_paginator_bottom">'
            b'<span class="ui-paginator-current">Showing 0-0 out of 0 records</span></div>'
            b'<tbody id="pbqueryForm:pQueryTable_data">'
            b'<tr class="ui-datatable-empty-message"><td>No results found for search.</td></tr>'
            b"</tbody>"
        )
    last = first + len(BeautifulSoup(rows, "html.parser").select("tr")) - 1
    return (
        '<form id="pbqueryForm">'
        '<input type="hidden" name="pbqueryForm" value="pbqueryForm">'
        '<input type="hidden" name="javax.faces.ViewState" value="test-view-state">'
        '<div id="pbqueryForm:pQueryTable_paginator_bottom">'
        + f'<span class="ui-paginator-current">Showing {first}-{last} '
        + f"out of {total} records</span></div>"
        + f'<table><tbody id="pbqueryForm:pQueryTable_data">{rows}</tbody></table></form>'
    ).encode()


def test_application_evidence_is_not_interpreted_as_gas_or_power_claims():
    _, records = parse_results(_page(_row()), start=TODAY, end=TODAY)
    record = records[0]
    assert record["document_number"] == "35964"
    assert "application status: approved" in record["abstract"].lower()
    assert "actual flaring/venting" in record["abstract"]
    assessment = assess_permit(record, as_of=TODAY)
    assert assessment["decision"] == "rejected"
    assert assessment["power_activity"] is None
    assert assessment["authorized_expiration_date"] == "2026-10-30"
    assert "MW" in assessment["missing_facts"]
    assert assessment["rental_hypothesis"] is None
    assert evaluator_version(record) == "rrc-flare-application-evidence-v1"
    assert "physical flare/vent or well location" in assessment["missing_facts"]


def test_verified_zero_result_window_is_a_valid_empty_snapshot():
    total, records = parse_results(_page("", total=0), start=TODAY, end=TODAY)
    assert total == 0
    assert records == []


def test_same_filing_status_update_keeps_identity_and_changes_evidence_hash():
    _, first = parse_results(_page(_row(status="Submitted")), start=TODAY, end=TODAY)
    _, amended = parse_results(_page(_row(status="Approved")), start=TODAY, end=TODAY)
    assert first[0]["document_number"] == amended[0]["document_number"] == "35964"
    assert first[0]["source_hash"] != amended[0]["source_hash"]


def test_historical_segment_accepts_at_most_seven_days_and_replays_failure(monkeypatch):
    from datetime import timedelta

    start = date(2026, 7, 1)
    end = start + timedelta(days=6)
    calls = []

    def successful(source, client, *, window_start, window_end):
        calls.append((window_start, window_end))
        return [{"document_number": "35964"}]

    monkeypatch.setattr("gridlens.ingestion.adapters.rrc_flare_exceptions.retrieve", successful)
    result = retrieve_collection_segment(SOURCE, "issue_history", start, end, {})
    assert result["window_complete"] is True
    assert result["partial"] is False
    assert result["cursor"] == {}
    assert result["records"] == [{"document_number": "35964"}]
    assert calls == [(start, end)]

    # A source exception propagates; the caller must retain its prior progress cursor.
    def unavailable(*_args, **_kwargs):
        raise SourceParseError("synthetic outage")

    monkeypatch.setattr("gridlens.ingestion.adapters.rrc_flare_exceptions.retrieve", unavailable)
    with pytest.raises(SourceParseError, match="synthetic outage"):
        retrieve_collection_segment(SOURCE, "issue_history", start, end, {})

    with pytest.raises(SourceParseError, match="window"):
        retrieve_collection_segment(SOURCE, "issue_history", start, end + timedelta(days=1), {})


def test_paginator_partial_xml_checks_page_offset_and_rotating_state():
    def rows(offset: int, count: int) -> str:
        return "".join(
            _row(filing=str(36000 + index), submittal="09/30/2026").replace(
                'data-ri="0"', f'data-ri="{index}"'
            )
            for index in range(offset, offset + count)
        )

    def partial(offset: int, count: int, rotated_state: str) -> bytes:
        table = rows(offset, count)
        return (
            "<?xml version='1.0' encoding='UTF-8'?><partial-response><changes>"
            f'<update id="pbqueryForm:pQueryTable"><![CDATA[{table}]]></update>'
            f'<update id="j_id1:javax.faces.ViewState:0">{rotated_state}</update>'
            "</changes></partial-response>"
        ).encode()

    class MockClient:
        def __init__(self):
            self.requests = []

        def stream(self, method, url, **kwargs):
            self.requests.append((method, url, kwargs))
            data = kwargs.get("data", {})
            if method == "GET":
                content = (
                    b'<form id="pbqueryForm" action="/swr32/publicquery.xhtml">'
                    b'<input type="hidden" name="pbqueryForm" value="pbqueryForm">'
                    b'<input name="pbqueryForm:submittalDateFrom_input">'
                    b'<input name="pbqueryForm:submittalDateTo_input"></form>'
                )
                content_type = "text/html"
            elif data.get("pbqueryForm:searchExceptions"):
                hidden = '<input type="hidden" name="javax.faces.ViewState" value="search-state">'
                content = (
                    _page(rows(0, 10), total=21)
                    .decode()
                    .replace(
                        '<input type="hidden" name="javax.faces.ViewState" '
                        'value="test-view-state">',
                        hidden,
                    )
                    .encode()
                )
                content_type = "text/html"
            else:
                offset = int(data["pbqueryForm:pQueryTable_first"])
                state = "rotated-one" if offset == 10 else "rotated-two"
                content = partial(offset, 10 if offset == 10 else 1, state)
                content_type = "text/xml"

            class Response:
                headers = httpx.Headers({"content-type": content_type})

                def __enter__(self):
                    return self

                def __exit__(self, *_):
                    return None

                def raise_for_status(self):
                    return None

                def iter_bytes(self):
                    return iter([content])

            return Response()

    mock = MockClient()
    records = retrieve(SOURCE, mock, today=TODAY)
    assert len(records) == 21
    assert mock.requests[2][2]["data"]["javax.faces.ViewState"] == "search-state"
    assert mock.requests[3][2]["data"]["javax.faces.ViewState"] == "rotated-one"
    bad_offset = partial(0, 1, "rotated-three")
    with pytest.raises(SourceParseError):
        parse_results(
            bad_offset,
            start=TODAY,
            end=TODAY,
            expected_first=21,
            expected_total=21,
        )


@pytest.mark.parametrize(
    "body",
    [
        b"<html>changed page</html>",
        _page("", total=1),
        _page(_row(filing="not-a-number")),
        _page(_row(submittal="bad-date")),
        _page(_row(status="Unexpected")),
        _page(_row() + _row(), total=2),
        _page(_row(effective="not-a-date")),
        _page(_row(expiration="99/99/2026")),
    ],
)
def test_changed_empty_malformed_or_over_bound_list_fails_closed(body: bytes):
    with pytest.raises(SourceParseError):
        parse_results(body, start=TODAY, end=TODAY)


def test_retrieve_uses_official_public_form_and_recent_submittal_window():
    class MockClient:
        def __init__(self):
            self.closed = False
            self.requests = []

        def get(self, url, **kwargs):
            self.requests.append(("GET", url, kwargs))
            return httpx.Response(
                200,
                request=httpx.Request("GET", url),
                headers={"content-type": "text/html"},
                content=(
                    b'<form id="pbqueryForm" action="/swr32/publicquery.xhtml">'
                    b'<input type="hidden" name="pbqueryForm" value="pbqueryForm">'
                    b'<input name="pbqueryForm:submittalDateFrom_input">'
                    b'<input name="pbqueryForm:submittalDateTo_input">'
                    b"</form>"
                ),
            )

        def stream(self, method, url, **kwargs):
            self.requests.append((method, url, kwargs))

            class StreamResponse:
                def __enter__(self):
                    return self

                def __exit__(self, *_):
                    pass

                def raise_for_status(self):
                    pass

                headers = httpx.Headers({"content-type": "text/html"})
                request = httpx.Request(method, url)

                def iter_bytes(self):
                    if method == "GET":
                        return iter(
                            [
                                b'<form id="pbqueryForm" action="/swr32/publicquery.xhtml">'
                                b'<input type="hidden" name="pbqueryForm" value="pbqueryForm">'
                                b'<input name="pbqueryForm:submittalDateFrom_input">'
                                b'<input name="pbqueryForm:submittalDateTo_input"></form>'
                            ]
                        )
                    return iter([_page(_row())])

            return StreamResponse()

        def close(self):
            self.closed = True

    mock = MockClient()
    records = retrieve(SOURCE, mock, today=TODAY)
    assert len(records) == 1
    request_data = mock.requests[1][2]["data"]
    assert request_data["pbqueryForm:submittalDateFrom_input"] == "09/29/2026"
    assert request_data["pbqueryForm:submittalDateTo_input"] == "10/01/2026"
    assert request_data["pbqueryForm:pQueryTable_rppDD"] == "10"
    assert mock.requests[0][1] == QUERY_URL
