import json
from datetime import date

import httpx
import pytest

from gridlens.ingestion.adapters import federal_register, retrieve_source
from gridlens.ingestion.adapters.federal_register import SourceParseError, retrieve
from gridlens.ingestion.registry import load_registry


def federal_register_source():
    source = next(source for source in load_registry() if source["id"] == "federal-register-eis")
    # Retain a legacy single-lane source for baseline pagination assertions.
    source["query"].pop("supplemental_queries", None)
    return source


def row(document_number="2024-12869", *, title="Test Notice", abstract="test"):
    return {
        "document_number": document_number,
        "title": title,
        "publication_date": "2024-06-12",
        "html_url": f"https://www.federalregister.gov/documents/{document_number}",
        "abstract": abstract,
    }


def supplemental_source(**query_overrides):
    source = federal_register_source()
    source["query"] = {
        **source["query"],
        "supplemental_queries": [
            {
                "term": "environmental assessment",
                "agency": "federal-energy-regulatory-commission",
            }
        ],
        **query_overrides,
    }
    return source


def test_complete_pagination_preserves_published_date():
    source = federal_register_source()
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
    source = federal_register_source()
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"total_pages": 11, "count": 1, "results": [{"document_number": "1"}]}
            )
        )
    )
    with pytest.raises(SourceParseError, match="require 11 pages"):
        retrieve(source, client)


def test_unexpected_empty_page_is_failure():
    source = federal_register_source()
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"total_pages": 1, "count": 1, "results": []})
        )
    )
    with pytest.raises(SourceParseError, match="empty"):
        retrieve(source, client)


def test_oversized_response_fails_before_json_decode():
    source = federal_register_source()
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


def test_supplemental_query_preserves_primary_search_and_adds_official_agency_filter():
    source = supplemental_source()
    seen = []

    def responder(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        seen.append(dict(params))
        if params.get("conditions[agencies][]"):
            return httpx.Response(200, json={"total_pages": 1, "count": 1, "results": [row()]})
        return httpx.Response(
            200,
            json={"total_pages": 1, "count": 1, "results": [row("PRIMARY")]},
        )

    records = retrieve(source, httpx.Client(transport=httpx.MockTransport(responder)))

    assert len(records) == 2
    assert seen[0]["conditions[term]"] == "environmental impact statement"
    assert "conditions[agencies][]" not in seen[0]
    assert seen[1]["conditions[term]"] == "environmental assessment"
    assert seen[1]["conditions[agencies][]"] == "federal-energy-regulatory-commission"
    for params in seen:
        assert params["conditions[type][]"] == "NOTICE"
        assert params["order"] == "newest"
        assert params["per_page"] == "100"


@pytest.mark.parametrize("pages", [0, 1])
def test_empty_supplemental_lane_is_healthy_for_zero_count(pages):
    source = supplemental_source()
    requested = []

    def responder(request: httpx.Request) -> httpx.Response:
        lane = "supplemental" if request.url.params.get("conditions[agencies][]") else "primary"
        requested.append(lane)
        if lane == "supplemental":
            return httpx.Response(200, json={"total_pages": pages, "count": 0, "results": []})
        return httpx.Response(200, json={"total_pages": 1, "count": 1, "results": [row()]})

    records = retrieve(source, httpx.Client(transport=httpx.MockTransport(responder)))
    assert len(records) == 1
    assert requested == ["primary", "supplemental"]


def test_malformed_empty_lane_fails_whole_acquisition():
    source = supplemental_source()
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"total_pages": 2, "count": 0, "results": []})
        )
    )
    with pytest.raises(SourceParseError, match="empty or malformed"):
        retrieve(source, client)


def test_exact_cross_query_duplicates_deduplicate_but_conflicting_same_id_rows_survive():
    source = supplemental_source()
    exact = row()

    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"total_pages": 1, "count": 1, "results": [exact]})

    records = retrieve(source, httpx.Client(transport=httpx.MockTransport(responder)))
    assert len(records) == 1

    def conflicting(request: httpx.Request) -> httpx.Response:
        body = dict(exact)
        if request.url.params.get("conditions[agencies][]"):
            body["abstract"] = "conflicting source text"
        return httpx.Response(200, json={"total_pages": 1, "count": 1, "results": [body]})

    conflicts = retrieve(source, httpx.Client(transport=httpx.MockTransport(conflicting)))
    assert len(conflicts) == 2
    assert [item["document_number"] for item in conflicts] == ["2024-12869", "2024-12869"]
    assert {item["abstract"] for item in conflicts} == {"test", "conflicting source text"}


def test_same_lane_duplicate_is_rejected_and_cross_lane_overlap_cannot_hide_incomplete_count():
    source = federal_register_source()
    repeated = row()
    same_lane = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"total_pages": 1, "count": 2, "results": [repeated, repeated]}
            )
        )
    )
    with pytest.raises(SourceParseError, match="repeated an identical record"):
        retrieve(source, same_lane)

    source = supplemental_source()

    def incomplete(request: httpx.Request) -> httpx.Response:
        count = 2 if not request.url.params.get("conditions[agencies][]") else 1
        return httpx.Response(200, json={"total_pages": 1, "count": count, "results": [repeated]})

    with pytest.raises(SourceParseError, match="pagination was incomplete"):
        retrieve(source, httpx.Client(transport=httpx.MockTransport(incomplete)))


def test_shared_page_budget_counts_first_page_probes_for_every_lane():
    source = supplemental_source(max_pages=2)
    requests = []

    def responder(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"total_pages": 2, "count": 2, "results": [row()]})

    with pytest.raises(SourceParseError, match="shared maximum is 2"):
        retrieve(source, httpx.Client(transport=httpx.MockTransport(responder)))
    assert len(requests) == 2


def test_shared_run_byte_bound_covers_empty_first_page_probes():
    source = supplemental_source(max_response_bytes=1024, max_run_bytes=1024)
    padded = json.dumps({"total_pages": 0, "count": 0, "results": []}).encode() + b" " * 700
    requests = []

    def responder(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=padded)

    with pytest.raises(SourceParseError, match="exceeds"):
        retrieve(source, httpx.Client(transport=httpx.MockTransport(responder)))
    assert len(requests) == 2


def test_run_byte_limit_clamps_response_reads_and_exact_budget_stops_before_next_request():
    source = federal_register_source()
    source["query"]["max_response_bytes"] = 1024
    source["query"]["max_run_bytes"] = 1024
    requests = []

    def exact_budget(request: httpx.Request) -> httpx.Response:
        requests.append(int(request.url.params["page"]))
        body = json.dumps({"total_pages": 2, "count": 2, "results": [row("first")]}).encode()
        return httpx.Response(200, content=body + b" " * (1024 - len(body)))

    with pytest.raises(SourceParseError, match="run bound"):
        retrieve(source, httpx.Client(transport=httpx.MockTransport(exact_budget)))
    assert requests == [1]

    source["query"]["max_run_bytes"] = 1100
    requests.clear()

    def partial_budget(request: httpx.Request) -> httpx.Response:
        requests.append(int(request.url.params["page"]))
        if len(requests) == 1:
            body = json.dumps({"total_pages": 2, "count": 2, "results": [row("first")]}).encode()
            return httpx.Response(200, content=body + b" " * (800 - len(body)))
        return httpx.Response(
            200,
            content=json.dumps({"total_pages": 2, "count": 2, "results": [row("second")]}).encode()
            + b" " * 250,
        )

    with pytest.raises(SourceParseError, match="exceeds 300 bytes"):
        retrieve(source, httpx.Client(transport=httpx.MockTransport(partial_budget)))
    assert requests == [1, 2]


def test_legacy_run_byte_ceiling_remains_100mb():
    source = federal_register_source()
    source["query"]["max_run_bytes"] = 100_000_000
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"total_pages": 0, "count": 0, "results": []})
        )
    )
    assert retrieve(source, client) == []


def test_later_page_metadata_must_match_and_every_request_gets_deadline(monkeypatch):
    source = federal_register_source()
    calls = []

    def responder(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        count = 2
        pages = 2 if page == 1 else 3
        return httpx.Response(
            200,
            json={"total_pages": pages, "count": count, "results": [row(str(page))]},
        )

    with pytest.raises(SourceParseError, match="metadata changed"):
        retrieve(source, httpx.Client(transport=httpx.MockTransport(responder)))

    def bounded(client, url, limit, params, *, deadline=None, **kwargs):
        calls.append(deadline)
        page = params["page"]
        payload = {"total_pages": 2, "count": 2, "results": [row(str(page))]}
        return httpx.Headers(), json.dumps(payload).encode()

    monkeypatch.setattr(federal_register, "read_bounded_response", bounded)
    retrieve_source(source, httpx.Client(), deadline=123.0)
    assert calls == [123.0, 123.0]


@pytest.mark.parametrize(
    "key,value",
    [
        ("max_pages", True),
        ("per_page", 100.0),
        ("window_days", False),
        ("max_run_bytes", True),
    ],
)
def test_query_bounds_reject_bool_and_noninteger_values(key, value):
    source = federal_register_source()
    source["query"] = {**source["query"], key: value}
    with pytest.raises(SourceParseError):
        retrieve(source, httpx.Client())


def test_supplemental_query_shape_and_source_scope_are_strict():
    source = supplemental_source()
    source["query"]["supplemental_queries"].append(
        {"term": "other", "agency": "federal-energy-regulatory-commission"}
    )
    with pytest.raises(SourceParseError, match="supplemental queries"):
        retrieve(source, httpx.Client())

    source = federal_register_source()
    source["id"] = "other-federal-register"
    source["query"]["supplemental_queries"] = [
        {"term": "environmental assessment", "agency": "federal-energy-regulatory-commission"}
    ]
    with pytest.raises(SourceParseError, match="not enabled"):
        retrieve(source, httpx.Client())

    source = federal_register_source()
    source["query"]["unreviewed_extra"] = "ignored if allowed"
    with pytest.raises(SourceParseError, match="query fields"):
        retrieve(source, httpx.Client())

    source = supplemental_source()
    source["endpoint"] = "https://example.com/api/v1/documents.json"
    with pytest.raises(SourceParseError, match="reviewed JSON API endpoint"):
        retrieve(source, httpx.Client())

    source = supplemental_source()
    source["retrieval_method"] = "federal-register-json"
    with pytest.raises(SourceParseError, match="reviewed JSON API endpoint"):
        retrieve(source, httpx.Client())
