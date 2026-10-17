"""Disposable DB only. Window selection is deterministic and calls no provider."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.market_window import build_window, today_central
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    Evidence,
    MarketNewsletter,
    MarketNewsletterBudget,
    Observation,
    Source,
)
from gridlens.settings import settings

NOW = datetime(2026, 10, 14, 18, 0, tzinfo=UTC)
TODAY = today_central(NOW)


@pytest.fixture
def factory():
    engine = create_engine(settings.test_database_url)
    assert engine.url.database.endswith("_test")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False)
    engine.dispose()


def _source(session, source_id, endpoint, family="news", geography="United States"):
    if session.get(Source, source_id) is None:
        session.add(
            Source(
                id=source_id,
                publisher=source_id,
                endpoint=endpoint,
                family=family,
                geography=geography,
                industries=["energy"],
                retrieval_method="publisher-rss",
            )
        )
        session.flush()


def _item(
    session,
    source_id,
    title,
    abstract="",
    days_ago=1,
    host="www.utilitydive.com",
    path=None,
    published=True,
    observed_at=None,
    obs_id=None,
    content_hash=None,
):
    obs_id = obs_id or uuid4()
    url = f"https://{host}/{path or uuid4().hex}/"
    digest = content_hash or uuid4().hex + uuid4().hex
    when = observed_at or NOW
    published_at = TODAY - timedelta(days=days_ago) if published else None
    if session.get(Observation, obs_id) is None:
        session.add(
            Observation(
                id=obs_id,
                source_id=source_id,
                external_id=str(obs_id),
                title=title,
                abstract=abstract,
                url=url,
                content_hash=digest,
                published_at=published_at,
                first_seen_at=when - timedelta(hours=1),
            )
        )
        session.flush()
    evidence_id = uuid4()
    session.add(
        Evidence(
            id=evidence_id,
            observation_id=obs_id,
            title=title,
            abstract=abstract,
            url=url,
            content_hash=digest,
            published_at=published_at,
            observed_at=when,
        )
    )
    session.flush()
    return str(evidence_id)


def test_window_selects_eligible_recent_power_items_and_reports_exclusions(factory):
    with factory.begin() as s:
        _source(s, "utility-dive-news", "https://www.utilitydive.com/feeds/news/")
        _source(s, "dcd-news", "https://www.datacenterdynamics.com/en/rss/news/")
        _source(s, "boston-building-permits", "https://data.boston.gov/x", "construction-permits")
        # Same-day duplicates resolve deterministically: the lowest source id wins.
        keep = _item(
            s,
            "dcd-news",
            "ERCOT wholesale prices spike",
            "Texas grid demand.",
            host="www.datacenterdynamics.com",
        )
        old = _item(s, "utility-dive-news", "PJM capacity auction clears", "Power prices.", 9)
        undated = _item(s, "utility-dive-news", "PJM grid plan", "Power.", published=False)
        offtopic = _item(s, "utility-dive-news", "Bakery opens", "Fresh bread.")
        offhost = _item(s, "utility-dive-news", "ERCOT grid news", "Power.", host="evil.example")
        permit = _item(
            s, "boston-building-permits", "Electric grid permit", "Power.", host="data.boston.gov"
        )
        dup = _item(
            s,
            "utility-dive-news",
            "ERCOT Wholesale Prices Spike!",
            "Power, same story.",
        )
    with factory() as s:
        window = build_window(s, NOW)
    assert set(window.items) == {keep}
    assert window.items[keep]["region"] == "ercot"
    assert window.items[keep]["topic"] == "prices-markets"
    assert window.coverage["excluded"] == {
        "duplicate": 1,
        "not_power_market": 1,
        "source_not_authorized": 1,
    }
    assert window.coverage["by_source"] == {"dcd-news": 1}
    assert all(i not in window.items for i in (old, undated, offtopic, offhost, permit, dup))
    assert window.groups[0]["item_ids"] == [keep]
    assert window.end == TODAY and (window.end - window.start).days == 7


def test_only_latest_evidence_version_counts(factory):
    obs_id = uuid4()
    with factory.begin() as s:
        _source(s, "utility-dive-news", "https://www.utilitydive.com/feeds/news/")
        _item(
            s,
            "utility-dive-news",
            "Old title grid",
            "Power.",
            obs_id=obs_id,
            observed_at=NOW - timedelta(hours=5),
            path="same",
        )
        new = _item(
            s,
            "utility-dive-news",
            "New title grid transmission",
            "Power lines.",
            obs_id=obs_id,
            observed_at=NOW,
            path="same",
        )
    with factory() as s:
        window = build_window(s, NOW)
    assert list(window.items) == [new]


def test_fingerprint_is_stable_and_changes_with_evidence(factory):
    with factory.begin() as s:
        _source(s, "utility-dive-news", "https://www.utilitydive.com/feeds/news/")
        _item(s, "utility-dive-news", "PJM grid transmission plan", "Power lines.")
    with factory() as s:
        first, second = build_window(s, NOW), build_window(s, NOW)
    assert first.fingerprint == second.fingerprint and len(first.fingerprint) == 64
    with factory.begin() as s:
        _item(s, "utility-dive-news", "MISO generation solar farm", "Electric power.")
    with factory() as s:
        assert build_window(s, NOW).fingerprint != first.fingerprint


def test_caps_are_reported_not_silent(factory):
    with factory.begin() as s:
        _source(s, "utility-dive-news", "https://www.utilitydive.com/feeds/news/")
        for i in range(11):
            _item(s, "utility-dive-news", f"ERCOT wholesale price story {i}", f"Power {i}.")
    with factory() as s:
        window = build_window(s, NOW)
    assert window.coverage["included_items"] == 8
    assert window.coverage["omitted_by_caps"] == 3
    assert window.groups[0]["omitted_items"] == 3


def test_empty_window_has_no_groups(factory):
    with factory() as s:
        window = build_window(s, NOW)
    assert window.groups == [] and window.items == {}


def test_newsletter_schema_allows_one_live_row_per_fingerprint(factory):
    base = dict(
        input_fingerprint="a" * 64,
        window_start=TODAY,
        window_end=TODAY,
        policy_version="p",
        schema_version="s",
        model="m",
    )
    with factory.begin() as s:
        s.add(MarketNewsletter(status="failed", **base))
        s.add(MarketNewsletter(status="draft", **base))
        s.add(MarketNewsletterBudget(day=TODAY, reserved_requests=0))
    with pytest.raises(Exception, match="uq_market_newsletter_live_fingerprint"):
        with factory.begin() as s:
            s.add(MarketNewsletter(status="queued", **base))
