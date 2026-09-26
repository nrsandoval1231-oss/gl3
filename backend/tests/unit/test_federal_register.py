from datetime import date

import httpx
import pytest

from gridlens.ingestion.adapters.federal_register import SourceParseError, retrieve
from gridlens.ingestion.registry import load_registry


def test_complete_pagination_preserves_published_date():
    source = load_registry()[0]
    requested = []

    def responder(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        requested.append(page)
        return httpx.Response(
            200,
            json={
                "total_pages": 2,
                "count": 2,
                "results": [
                    {
                        "document_number": str(page),
                        "title": "Test Mine",
                        "publication_date": "2026-09-14",
                        "html_url": "https://www.federalregister.gov/test",
                        "abstract": "proposed development of mine",
                    }
                ],
            },
        )

    rows = retrieve(source, httpx.Client(transport=httpx.MockTransport(responder)))
    assert requested == [1, 2]
    assert all(date.fromisoformat(row["publication_date"]) == date(2026, 9, 14) for row in rows)


def test_overlarge_bounded_result_fails_closed():
    source = load_registry()[0]
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"total_pages": 11, "count": 1, "results": [{"document_number": "1"}]}
            )
        )
    )
    with pytest.raises(SourceParseError, match="requires 11 pages"):
        retrieve(source, client)


def test_unexpected_empty_page_is_failure():
    source = load_registry()[0]
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"total_pages": 1, "count": 1, "results": []})
        )
    )
    with pytest.raises(SourceParseError, match="empty"):
        retrieve(source, client)


def test_oversized_response_fails_before_json_decode():
    source = load_registry()[0]
    source = {
        **source,
        "query": {
            **source["query"],
            "max_response_bytes": 1024,
            "max_run_bytes": 2048,
        },
    }
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"{" + b"x" * 1200 + b"}")
        )
    )
    with pytest.raises(SourceParseError, match="exceeds 1024 bytes"):
        retrieve(source, client)
