import hashlib
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from db_reset import reset_test_database
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.ingestion.compare_acquisition import compare_case, report_complete
from gridlens.settings import settings


@pytest.fixture
def comparison_database(monkeypatch):
    target = make_url(settings.test_database_url)
    assert target.database and target.database.endswith("_test")
    assert target != make_url(settings.database_url)
    engine = create_engine(settings.test_database_url)
    reset_test_database(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("gridlens.persistence.database.SessionLocal", factory)
    monkeypatch.setattr("gridlens.integrations.legacy_calls.SessionLocal", factory)
    yield engine
    engine.dispose()


def test_missing_native_capture_and_unknown_paid_call_keep_report_incomplete(comparison_database):
    digest = hashlib.sha256(b"adapter text").hexdigest()
    case = {
        "case_id": "x",
        "source_id": "s",
        "external_id": "1",
        "url": "https://example.gov/1",
        "media_type": "text/html",
        "identity_kind": "native_record_id",
        "max_bytes": 1000000,
        "recovery_terms": [],
    }
    capture = {
        "case_id": "x",
        "source_id": "s",
        "external_id": "1",
        "capture_id": "capture-1",
        "capture_hash": digest,
        "capture_kind": "COMPLETE_DOCUMENT",
        "evidence_id": None,
        "evidence_content_hash": None,
        "url": case["url"],
        "content_type": "text/html",
        "title": "Page",
        "text": "adapter text",
        "observed_at": datetime.now(UTC).isoformat(),
        "content_hash": digest,
    }
    row = compare_case(
        case, capture, firecrawl={"status": "UNKNOWN", "logical_call_id": "call-123"}
    )
    assert row["firecrawl"]["logical_call_id"] == "call-123"
    assert not report_complete([row])


@pytest.mark.parametrize("interrupt", [False, True])
def test_ledger_replay_caches_completed_and_blocks_unknown_without_second_dispatch(
    comparison_database, monkeypatch, interrupt
):
    from sqlalchemy import select

    from gridlens.ingestion import compare_acquisition
    from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
    from gridlens.persistence.models import LogicalCall

    for name, value in {
        "intelligence_enabled": True,
        "intelligence_mode": "evaluation",
        "intelligence_enabled_contracts": "FIRECRAWL_SCRAPE_V2",
        "intelligence_research_enabled": True,
        "intelligence_max_active_calls": 2,
        "intelligence_max_call_usd": Decimal("0.1"),
        "firecrawl_api_key": SecretStr("fixture-key"),
        "firecrawl_scrape_cost_usd": Decimal("0.01"),
    }.items():
        monkeypatch.setattr(settings, name, value)
    for scope in ("global", "provider", "model", "source", "project"):
        for period in ("daily", "monthly"):
            monkeypatch.setattr(settings, f"intelligence_{scope}_{period}_calls", 10)
            monkeypatch.setattr(settings, f"intelligence_{scope}_{period}_usd", Decimal("1"))
    calls = []

    def extract(*_args, **_kwargs):
        calls.append(1)
        if interrupt:
            raise RuntimeError("simulated transport interruption")
        return PublicDocument(
            url="https://example.gov/page", title="Page", text="complete source text"
        )

    monkeypatch.setattr(
        compare_acquisition,
        "SessionLocal",
        __import__("gridlens.persistence.database", fromlist=["SessionLocal"]).SessionLocal,
        raising=False,
    )
    monkeypatch.setattr(
        "gridlens.ingestion.adapters.pursuit_acquisition.extract_public_document", extract
    )
    case = {"case_id": "replay-case", "url": "https://example.gov/page", "eligible_html": True}
    first = compare_acquisition.scrape_html(case, api_key="fixture", cost_cap_usd=Decimal("0.02"))
    monkeypatch.setattr(settings, "firecrawl_scrape_cost_usd", Decimal("0.02"))
    second = compare_acquisition.scrape_html(case, api_key="fixture", cost_cap_usd=Decimal("0.02"))
    assert first.get("status") != "INCOMPLETE", first
    with __import__(
        "gridlens.persistence.database", fromlist=["SessionLocal"]
    ).SessionLocal() as session:
        logical = session.scalar(select(LogicalCall))
    assert logical is not None and first["logical_call_id"] == second["logical_call_id"] == str(
        logical.id
    )
    if interrupt:
        assert first["status"] == second["status"] == "UNKNOWN"
        assert logical.status == "SENT_OUTCOME_UNKNOWN"
    else:
        assert first["status"] == second["status"] == "COMPLETED"
        assert logical.status == "COMPLETED"
    assert len(calls) == 1
    if not interrupt:
        assert first["reserved_cost_usd"] == second["reserved_cost_usd"] == "0.010000"
