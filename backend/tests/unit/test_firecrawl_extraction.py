"""Bounded extraction transport and fallback boundaries; no provider calls."""

import json
import time
from contextlib import nullcontext
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr

from gridlens.ingestion.adapters.bounded_http import AcquisitionFailure, ResponseTooLarge
from gridlens.ingestion.adapters.buying_chain_public import (
    PublicAccessRestricted,
    PublicDocument,
    PublicExtractionUnavailable,
)
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.pursuit_acquisition import (
    extract_public_document,
    retrieval_failure,
)

URL = "https://example.com/project"


def payload():
    return {
        "success": True,
        "data": {
            "markdown": "Complete project text.",
            "metadata": {
                "sourceURL": URL,
                "url": URL,
                "statusCode": 200,
                "title": "Project update",
                "contentType": "text/html",
            },
        },
    }


def test_extraction_contract_is_bounded_markdown_no_actions_models_or_enhanced_proxy():
    debits = []

    def handler(request):
        assert debits == ["https://api.firecrawl.dev/v2/scrape"]
        body = json.loads(request.content)
        assert body["formats"] == ["markdown"]
        assert body["parsers"] == [] and body["proxy"] == "basic"
        assert body["maxAge"] == 0 and body["storeInCache"] is False
        assert body["onlyMainContent"] is False and body["skipTlsVerification"] is False
        assert "actions" not in body and "headers" not in body and "profile" not in body
        assert 1000 <= body["timeout"] <= 5000
        return httpx.Response(200, json=payload())

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        document = extract_public_document(
            URL,
            api_key="test",
            deadline=time.monotonic() + 5,
            before_request=debits.append,
            client=client,
        )
    assert document.url == URL and document.text == "Complete project text."
    assert document.published_at is None


@pytest.mark.parametrize(
    "defect",
    [
        "foreign_url",
        "foreign_source",
        "denied",
        "warning",
        "captcha",
        "late_captcha",
        "empty",
        "text_cap",
        "pdf",
    ],
)
def test_extraction_cannot_convert_untrusted_or_incomplete_response_into_document(defect):
    data = payload()
    if defect == "foreign_url":
        data["data"]["metadata"]["url"] = "https://other.example/project"
    elif defect == "foreign_source":
        data["data"]["metadata"]["sourceURL"] = "https://other.example/project"
    elif defect == "denied":
        data["data"]["metadata"]["statusCode"] = 403
    elif defect == "warning":
        data["data"]["warning"] = "Incomplete text"
    elif defect == "captcha":
        data["data"]["markdown"] = "Verify you are human. CAPTCHA."
    elif defect == "late_captcha":
        data["data"]["markdown"] = "Project update. " * 100 + "Verify you are human. CAPTCHA."
    elif defect == "empty":
        data["data"]["markdown"] = ""
    elif defect == "text_cap":
        data["data"]["markdown"] = "x" * 30001
    else:
        data["data"]["metadata"]["contentType"] = "application/pdf"
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=data))
    ) as client:
        with pytest.raises((SourceParseError, PublicAccessRestricted, ResponseTooLarge)):
            extract_public_document(
                URL,
                api_key="test",
                deadline=time.monotonic() + 5,
                before_request=lambda _: None,
                client=client,
            )


def test_extraction_byte_deadline_and_budget_prevent_unbounded_request():
    calls = []
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: calls.append(request) or httpx.Response(200, json=payload())
        )
    ) as client:
        with pytest.raises(TimeoutError):
            extract_public_document(
                URL,
                api_key="test",
                deadline=time.monotonic() - 1,
                before_request=lambda _: None,
                client=client,
            )
        with pytest.raises(RuntimeError):
            extract_public_document(
                URL,
                api_key="test",
                deadline=time.monotonic() + 5,
                before_request=lambda _: (_ for _ in ()).throw(RuntimeError()),
                client=client,
            )
        assert not calls
        with pytest.raises(ResponseTooLarge):
            extract_public_document(
                URL,
                api_key="test",
                deadline=time.monotonic() + 5,
                before_request=lambda _: None,
                client=client,
                max_bytes=10,
            )
        assert len(calls) == 1


@pytest.mark.parametrize(
    "error,code",
    [
        (AcquisitionFailure("http_status_403"), "access_restricted"),
        (AcquisitionFailure("http_status_404"), "not_found"),
        (AcquisitionFailure("http_status_429"), "rate_limited"),
        (AcquisitionFailure("network_error"), "network_error"),
        (TimeoutError("secret forbidden from receipt"), "deadline_or_transport_timeout"),
        (ResponseTooLarge("secret forbidden from receipt"), "document_budget_exceeded"),
    ],
)
def test_failure_receipt_uses_stable_codes_without_sensitive_exception_text(error, code):
    receipt = retrieval_failure(error)
    assert receipt["failure_code"] == code
    assert "secret" not in json.dumps(receipt)


@pytest.mark.parametrize("eligible", [True, False])
def test_worker_scrape_fallback_only_for_explicit_javascript_shell(monkeypatch, eligible):
    from gridlens.ingestion.adapters import pursuit_acquisition
    from gridlens.integrations import legacy_calls
    from gridlens.intelligence import autonomous_research as worker
    from gridlens.settings import settings

    events = []
    receipts = []
    question = SimpleNamespace(project_id="p", need_id="n", status="SEARCHING", receipt={})

    def get_record(model, *_):
        if model.__name__ == "PursuitResearchQuestion":
            return question
        return SimpleNamespace(id="p" if model.__name__ == "Project" else "n")

    session = SimpleNamespace(get=get_record)

    class SessionFactory:
        def begin(self):
            return nullcontext(session)

        def __call__(self):
            return nullcontext(session)

    monkeypatch.setattr(worker, "SessionLocal", SessionFactory())
    monkeypatch.setattr(worker, "_lock_acquisition", lambda *_: None)
    monkeypatch.setattr(worker, "enrich_buying_chain", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        worker, "retain_research_document", lambda *args: {"disposition": "ACCEPTED"}
    )
    monkeypatch.setattr(settings, "firecrawl_api_key", SecretStr("test"))
    monkeypatch.setattr(settings, "firecrawl_scrape_cost_usd", Decimal("0.01"))
    monkeypatch.setattr(settings, "intelligence_enabled", True)
    monkeypatch.setattr(settings, "intelligence_mode", "advisory")
    monkeypatch.setattr(settings, "intelligence_research_enabled", True)
    monkeypatch.setattr(settings, "intelligence_enabled_contracts", "FIRECRAWL_SCRAPE_V2")

    def retrieve(*_args, **_kwargs):
        events.append("direct")
        if eligible:
            raise PublicExtractionUnavailable("JavaScript shell")
        raise PublicAccessRestricted("Login required")

    def extract(*_args, **kwargs):
        assert kwargs["api_key"] == "test"
        assert kwargs["max_bytes"] == 750000
        assert callable(kwargs["before_request"])
        events.append("scrape")
        return PublicDocument(URL, "Public project", "Full supported text")

    call_id = UUID(int=1)

    def perform_legacy_call(**kwargs):
        assert kwargs["task_type"] == "FIRECRAWL_SCRAPE_V2"
        kwargs["before_dispatch"](call_id)
        payload, input_tokens, output_tokens = kwargs["invoke"]()
        assert input_tokens is output_tokens is None
        return SimpleNamespace(logical_call_id=call_id, result=payload)

    monkeypatch.setattr(worker, "retrieve", retrieve)
    monkeypatch.setattr(pursuit_acquisition, "extract_public_document", extract)
    monkeypatch.setattr(legacy_calls, "perform_legacy_call", perform_legacy_call)
    monkeypatch.setattr(worker, "SessionLocal", SessionFactory())
    run = worker.QuestionRun(
        "j",
        "w",
        1,
        "q",
        time.monotonic(),
        {"timeout_seconds": 5, "document_bytes": 750000, "documents": 2, "max_cost_usd": "1"},
    )
    monkeypatch.setattr(run, "cached", lambda _: None)
    monkeypatch.setattr(run, "reserve", lambda *_args, **_kwargs: events.append("direct_reserved"))
    monkeypatch.setattr(run, "row", lambda _: question)
    monkeypatch.setattr(
        run,
        "_reserve_paid",
        lambda *_args, **_kwargs: events.append("scrape_reserved"),
    )
    monkeypatch.setattr(run, "_finish_paid", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(run, "record", receipts.append)
    worker._research_public_url(run, URL)
    assert events == (
        ["direct_reserved", "direct", "scrape_reserved", "scrape"]
        if eligible
        else ["direct_reserved", "direct"]
    )
    assert receipts[0]["disposition"] == ("ACCEPTED" if eligible else "FAILED")
    if not eligible:
        assert receipts[0]["failure_code"] == "access_restricted"
        assert receipts[0]["effect_status"] == "NOT_SENT"


@pytest.mark.parametrize("exhausted", [None, "documents", "cost", "deadline"])
def test_extraction_reservation_debits_document_and_cost_before_request(monkeypatch, exhausted):
    from gridlens.intelligence import autonomous_research as worker
    from gridlens.settings import settings

    receipt = {"retrieval_attempts": 1, "reserved_cost_usd": "0.01", "cost_usd": "0"}
    row = SimpleNamespace(receipt=receipt)
    monkeypatch.setattr(worker, "SessionLocal", SimpleNamespace(begin=lambda: nullcontext(None)))
    monkeypatch.setattr(settings, "firecrawl_scrape_cost_usd", Decimal("0.02"))
    budget = {
        "timeout_seconds": 20,
        "documents": 1 if exhausted == "documents" else 2,
        "max_cost_usd": "0.02" if exhausted == "cost" else "0.03",
    }
    run = worker.QuestionRun(
        "j",
        "w",
        1,
        "q",
        time.monotonic() - 30 if exhausted == "deadline" else time.monotonic(),
        budget,
    )
    monkeypatch.setattr(run, "row", lambda _: row)
    if exhausted:
        with pytest.raises(worker.BudgetExceeded):
            run.reserve_extraction("https://api.firecrawl.dev/v2/scrape")
        assert row.receipt == receipt
    else:
        run.reserve_extraction("https://api.firecrawl.dev/v2/scrape")
        assert row.receipt["retrieval_attempts"] == 2
        assert row.receipt["reserved_cost_usd"] == "0.03"
        assert row.receipt["firecrawl_extractions"] == 1
        assert row.receipt["cost_usd"] is None


@pytest.mark.parametrize("operation", ["native", "search", "extract"])
def test_production_transport_isolation_follows_parent_reservation(monkeypatch, operation):
    from gridlens.ingestion.adapters import pursuit_acquisition as adapter

    events = []

    def isolate(path, args, kwargs, *, deadline):
        assert events == ["reserved"]
        assert path.startswith("gridlens.ingestion.adapters.pursuit_acquisition:_")
        assert "before_request" not in kwargs and "client" not in kwargs
        events.append("isolated")
        return "bounded-result"

    monkeypatch.setattr(adapter, "run_isolated", isolate)
    common = {
        "deadline": time.monotonic() + 5,
        "before_request": lambda _: events.append("reserved"),
    }
    if operation == "native":
        result = adapter.acquire_registered_record("seattle-building-permits", "EXACT-1", **common)
    elif operation == "search":
        result = adapter.discover_urls('"Exact site"', api_key="test", **common)
    else:
        result = adapter.extract_public_document(URL, api_key="test", **common)
    assert result == "bounded-result" and events == ["reserved", "isolated"]
