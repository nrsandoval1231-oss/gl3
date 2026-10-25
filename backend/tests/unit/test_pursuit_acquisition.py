import json
import time

import httpx
import pytest

from gridlens.ingestion.adapters.bounded_http import ResponseTooLarge
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.pursuit_acquisition import acquire_registered_record, discover_urls
from gridlens.ingestion.adapters.socrata_permits import render_record


def permit_row(source_id):
    if source_id == "austin-building-permits":
        return {
            "permit_number": "2026-0001",
            "issue_date": "2026-01-01",
            "description": "Temporary construction power for data center",
            "original_address1": "811 Clayton Ln",
            "status_current": "Active",
        }
    return {
        "id": "2026-0001",
        "issue_date": "2026-01-01",
        "work_description": "Data center conversion",
        "street_number": "400",
        "street_direction": "S",
        "street_name": "LASALLE",
        "permit_status": "ACTIVE",
    }


@pytest.mark.parametrize("source_id", ["austin-building-permits", "chicago-building-permits"])
def test_exact_record_reuses_ingestion_rendering_and_debits_first(source_id):
    events = []
    row = permit_row(source_id)

    def handler(request):
        assert events and events[0].startswith("https://data.")
        events.append("request")
        assert request.url.params["$limit"] == "2"
        assert "2026-0001" in request.url.params["$where"]
        assert "issue_date >=" not in request.url.params["$where"]
        return httpx.Response(200, json=[row])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        source, record = acquire_registered_record(
            source_id,
            "2026-0001",
            deadline=time.monotonic() + 5,
            before_request=events.append,
            client=client,
        )
    assert events[-1] == "request"
    assert record == render_record(source, row)
    assert record["document_number"] == "2026-0001"
    assert record["source_hash"]


@pytest.mark.parametrize("rows", [[], [{"permit_number": "OTHER"}], [{}, {}], {}])
def test_exact_record_rejects_missing_ambiguous_or_escaped_id(rows):
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=rows))
    ) as client:
        with pytest.raises(SourceParseError):
            acquire_registered_record(
                "austin-building-permits", "2026-0001", deadline=time.monotonic() + 5, client=client
            )


@pytest.mark.parametrize("identifier", ["x' OR 1=1", "x\n", "", "x" * 101])
def test_identifier_validation_precedes_requests(identifier):
    with pytest.raises(ValueError):
        acquire_registered_record(
            "austin-building-permits",
            identifier,
            deadline=time.monotonic() + 5,
            before_request=lambda _: pytest.fail("Request attempted"),
        )


def test_deadline_and_debit_rejection_prevent_request():
    def handler(_):
        pytest.fail("Request must not occur")

    def debit(_):
        raise RuntimeError("Persisted budget exhausted")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(TimeoutError):
            acquire_registered_record(
                "austin-building-permits", "2026-0001", deadline=time.monotonic() - 1, client=client
            )
        with pytest.raises(RuntimeError, match="budget"):
            acquire_registered_record(
                "austin-building-permits",
                "2026-0001",
                deadline=time.monotonic() + 5,
                client=client,
                before_request=debit,
            )


def test_exact_permit_byte_bound():
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 101))
    ) as client:
        with pytest.raises(ResponseTooLarge):
            acquire_registered_record(
                "austin-building-permits",
                "2026-0001",
                deadline=time.monotonic() + 5,
                client=client,
                max_bytes=100,
            )


def test_search_retains_only_safe_deduplicated_urls_and_never_snippets():
    debit = []

    def handler(request):
        assert debit == ["https://api.firecrawl.dev/v2/search"]
        assert request.method == "POST"
        body = json.loads(request.content)
        assert body["limit"] == 5
        assert body["sources"] == [{"type": "web"}]
        assert "scrapeOptions" not in body
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "web": [
                        {"url": "https://example.com/project", "description": "not evidence"},
                        {"url": "https://example.com/project#copy"},
                        {"url": "https://127.0.0.1/private"},
                        {"url": "http://example.com/unsafe"},
                    ]
                },
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        urls = discover_urls(
            '"811 Clayton Ln" electrical contractor',
            api_key="test",
            deadline=time.monotonic() + 5,
            before_request=debit.append,
            client=client,
            limit=5,
        )
    assert urls == ["https://example.com/project"]


def test_search_missing_configuration_is_visible_without_request():
    with pytest.raises(ValueError, match="not configured"):
        discover_urls(
            "project",
            api_key=None,
            deadline=time.monotonic() + 5,
            before_request=lambda _: pytest.fail("Request attempted"),
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"success": False},
        {"success": True, "data": {}},
        {"success": True, "data": {"web": [{}, {}]}},
    ],
)
def test_search_provider_failure_or_overlong_result_is_visible(payload):
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as client:
        with pytest.raises(SourceParseError):
            discover_urls(
                "project",
                api_key="test",
                deadline=time.monotonic() + 5,
                before_request=lambda _: None,
                client=client,
                limit=1,
            )
