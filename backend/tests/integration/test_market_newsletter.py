"""Disposable DB only. The provider is always a local fake; no network call is possible."""

import json
from datetime import UTC, datetime, timedelta
from importlib import import_module
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from gridlens.jobs.queue import lease_one
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    Evidence,
    Job,
    MarketNewsletter,
    MarketNewsletterBudget,
    Observation,
    Source,
)
from gridlens.settings import settings

NOW = datetime(2026, 10, 14, 18, 0, tzinfo=UTC)
TODAY = NOW.astimezone(ZoneInfo("America/Chicago")).date()
STORIES = [
    (
        "ERCOT large load requests reach 200 GW as data center demand grows",
        "The Texas grid operator said data center requests reached 200 GW on Oct. 14.",
    ),
    (
        "ERCOT wholesale prices rise 12% during evening peak",
        "Power prices in Texas climbed 12% on Tuesday evening.",
    ),
    (
        "PJM interconnection queue reform clears FERC",
        "FERC approved the PJM interconnection queue changes for generation projects.",
    ),
]


@pytest.fixture
def runtime(monkeypatch):
    engine = create_engine(settings.test_database_url)
    assert engine.url.database.endswith("_test")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    service = import_module("gridlens.intelligence.market_newsletter")
    monkeypatch.setattr(service, "SessionLocal", factory)
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("synthetic-key"))

    def no_network(*args, **kwargs):
        raise AssertionError("tests must never reach a real provider")

    monkeypatch.setattr(httpx.Client, "send", no_network)
    with factory.begin() as session:
        session.add(
            Source(
                id="utility-dive-news",
                publisher="Utility Dive",
                endpoint="https://www.utilitydive.com/feeds/news/",
                family="news",
                geography="United States",
                industries=["utilities"],
                retrieval_method="publisher-rss",
            )
        )
        session.flush()
        for title, abstract in STORIES:
            _evidence(session, title, abstract)
    yield factory, service
    engine.dispose()


def _evidence(session, title, abstract):
    obs_id, ev_id = uuid4(), uuid4()
    url = f"https://www.utilitydive.com/news/{obs_id.hex}/"
    digest = obs_id.hex + ev_id.hex
    day = TODAY - timedelta(days=1)
    session.add(
        Observation(
            id=obs_id,
            source_id="utility-dive-news",
            external_id=str(obs_id),
            title=title,
            abstract=abstract,
            url=url,
            content_hash=digest,
            published_at=day,
            first_seen_at=NOW - timedelta(hours=2),
        )
    )
    session.flush()
    session.add(
        Evidence(
            id=ev_id,
            observation_id=obs_id,
            title=title,
            abstract=abstract,
            url=url,
            content_hash=digest,
            published_at=day,
            observed_at=NOW,
        )
    )
    session.flush()


class FakeProvider:
    """Deterministic stand-in for the two model steps; mutate behaviour per test."""

    def __init__(self):
        self.calls = []
        self.bad_group_claim = False
        self.bad_headline = False
        self.raise_on_call = None

    def __call__(self, name, schema, system, user, max_tokens):
        self.calls.append(name)
        if self.raise_on_call == len(self.calls):
            raise httpx.HTTPError("boom")
        if name == "gridlens_market_group":
            claims = []
            for item in user["items"][:2]:
                text = item["title"] + "."
                if self.bad_group_claim:
                    text = "Dominion said requests reached 999 GW this fall."
                claims.append({"text": text, "evidence_ids": [item["id"]]})
            return {"claims": claims}, 100, 50
        assert name == "gridlens_market_newsletter"
        sections = [
            {
                "group_key": g["group_key"],
                "paragraphs": [{"claims": g["claims"][:2]}],
            }
            for g in user["groups"]
        ]
        top = [g["claims"][0] for g in user["groups"]][:3]
        headline = (
            "Dominion unveils 999 GW grid plan"
            if self.bad_headline
            else ("ERCOT demand and PJM queue reform lead the week")
        )
        return {"headline": headline, "top_summary": top, "sections": sections}, 400, 300


@pytest.fixture
def provider(runtime, monkeypatch):
    _, service = runtime
    fake = FakeProvider()
    monkeypatch.setattr(service, "_call_model", fake)
    return fake


def _request(factory, service):
    with factory.begin() as session:
        return service.request_newsletter(session, NOW)


def _run(factory, service, job_id):
    with factory.begin() as session:
        leased = lease_one(session, "newsletter-test-worker", job_ids=[UUID(job_id)])
    assert leased
    job, fence = leased
    service.process_newsletter_job(job.id, "newsletter-test-worker", fence)
    return job.id


def test_request_creates_one_queued_row_and_job_then_serves_cache(runtime, provider):
    factory, service = runtime
    first = _request(factory, service)
    assert first["status"] == "queued" and first["cached"] is False and first["job_id"]
    again = _request(factory, service)
    assert again["newsletter_id"] == first["newsletter_id"]
    assert again["cached"] is True and again["job_id"] == first["job_id"]
    assert provider.calls == []
    with factory() as session:
        assert len(session.scalars(select(MarketNewsletter)).all()) == 1
        assert len(session.scalars(select(Job).where(Job.kind == "market_newsletter")).all()) == 1


def test_request_requires_openai_key_only_when_a_new_draft_is_needed(runtime, monkeypatch):
    factory, service = runtime
    monkeypatch.setattr(settings, "openai_api_key", None)
    with pytest.raises(service.NewsletterUnavailable, match="provider_not_configured"):
        _request(factory, service)
    with factory() as session:
        assert session.scalars(select(MarketNewsletter)).all() == []


def test_empty_window_is_unavailable(runtime, provider):
    factory, service = runtime
    with pytest.raises(service.NewsletterUnavailable, match="no_eligible_items"):
        with factory.begin() as session:
            service.request_newsletter(session, NOW + timedelta(days=30))


def test_generation_stores_a_draft_with_server_rendered_citations(runtime, provider):
    factory, service = runtime
    queued = _request(factory, service)
    job_id = _run(factory, service, queued["job_id"])
    with factory() as session:
        row = session.get(MarketNewsletter, UUID(queued["newsletter_id"]))
        assert row.status == "draft" and row.error is None and row.generated_at
        assert session.get(Job, job_id).status == "succeeded"
        result = row.result
        assert result["headline"] == "ERCOT demand and PJM queue reform lead the week"
        assert "AI-drafted" in result["disclosure"]
        assert result["markdown"].startswith("# ERCOT demand")
        assert result["sections"] and result["top_summary"]
        assert result["validation"]["claims_dropped"] == 0
        assert {c["url"] for c in row.citations} <= {
            o.url.rstrip("/")
            for o in session.scalars(select(Observation))
        }
        assert row.input_tokens > 0 and row.output_tokens > 0
        budget = session.scalars(select(MarketNewsletterBudget)).one()
        # One request per group plus one synthesis, reserved up front.
        assert budget.reserved_requests == len(provider.calls)
    assert provider.calls[-1] == "gridlens_market_newsletter"
    assert provider.calls.count("gridlens_market_group") == len(provider.calls) - 1


def test_draft_is_cached_and_never_regenerated_for_unchanged_input(runtime, provider):
    factory, service = runtime
    queued = _request(factory, service)
    _run(factory, service, queued["job_id"])
    used = len(provider.calls)
    again = _request(factory, service)
    assert again["cached"] is True and again["status"] == "draft" and again["job_id"] is None
    assert len(provider.calls) == used


def test_ungrounded_group_claims_are_dropped_and_total_loss_fails_without_retry(runtime, provider):
    factory, service = runtime
    provider.bad_group_claim = True
    queued = _request(factory, service)
    _run(factory, service, queued["job_id"])
    with factory() as session:
        row = session.get(MarketNewsletter, UUID(queued["newsletter_id"]))
        assert row.status == "failed" and row.error == "no_valid_group_summaries"
        assert row.result is None
    assert "gridlens_market_newsletter" not in provider.calls
    # A failed run frees the fingerprint so the owner can request again.
    assert _request(factory, service)["cached"] is False


def test_ungrounded_headline_fails_the_draft(runtime, provider):
    factory, service = runtime
    provider.bad_headline = True
    queued = _request(factory, service)
    _run(factory, service, queued["job_id"])
    with factory() as session:
        row = session.get(MarketNewsletter, UUID(queued["newsletter_id"]))
        assert row.status == "failed" and row.error == "invalid_headline"
        assert row.input_tokens > 0


def test_provider_error_is_terminal_with_a_safe_code(runtime, provider):
    factory, service = runtime
    provider.raise_on_call = 1
    queued = _request(factory, service)
    job_id = _run(factory, service, queued["job_id"])
    with factory() as session:
        row = session.get(MarketNewsletter, UUID(queued["newsletter_id"]))
        assert row.status == "failed" and row.error == "request_failed"
        assert session.get(Job, job_id).status == "failed"
    assert len(provider.calls) == 1


def test_daily_cap_is_separate_from_brief_budget_and_blocks_before_any_call(
    runtime, provider, monkeypatch
):
    factory, service = runtime
    monkeypatch.setattr(settings, "newsletter_daily_request_limit", 2)
    queued = _request(factory, service)
    _run(factory, service, queued["job_id"])
    with factory() as session:
        row = session.get(MarketNewsletter, UUID(queued["newsletter_id"]))
        assert row.status == "failed" and row.error == "daily_budget_exhausted"
        assert session.scalars(select(MarketNewsletterBudget)).one().reserved_requests == 0
    assert provider.calls == []


def test_reserved_job_that_is_leased_again_never_repeats_a_billable_call(runtime, provider):
    factory, service = runtime
    queued = _request(factory, service)
    with factory.begin() as session:
        job = session.get(Job, UUID(queued["job_id"]))
        checkpoint = json.loads(job.checkpoint)
        job.checkpoint = json.dumps({**checkpoint, "reserved": True})
    _run(factory, service, queued["job_id"])
    with factory() as session:
        row = session.get(MarketNewsletter, UUID(queued["newsletter_id"]))
        assert row.status == "failed" and row.error == "ambiguous_prior_request"
    assert provider.calls == []


def test_changed_inputs_produce_a_new_fingerprint_and_new_draft(runtime, provider):
    factory, service = runtime
    first = _request(factory, service)
    _run(factory, service, first["job_id"])
    with factory.begin() as session:
        _evidence(
            session, "MISO generation additions top 3 GW this year", "Power plants in Louisiana."
        )
    second = _request(factory, service)
    assert second["cached"] is False and second["newsletter_id"] != first["newsletter_id"]


def test_real_http_path_is_unreachable_in_tests(runtime):
    _, service = runtime
    with pytest.raises(AssertionError, match="never reach a real provider"):
        service._call_model("n", {}, "s", {}, 10)
