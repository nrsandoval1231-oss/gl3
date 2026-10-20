from copy import deepcopy
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.registry import load_registry
from gridlens.ingestion.service import process_job
from gridlens.persistence.database import Base
from gridlens.persistence.models import Evidence, Job, Observation, Source
from gridlens.settings import settings

SOURCE_DEFINITION = next(row for row in load_registry() if row["id"] == "mjbizdaily-news")


def _feed() -> bytes:
    return (
        b'<?xml version="1.0"?><rss version="2.0"><channel><item>'
        b"<title>A company announces a cultivation facility</title>"
        b"<link>https://mjbizdaily.com/news/conditional-item/</link>"
        b"<pubDate>Fri, 25 Sep 2026 10:00:00 -0400</pubDate>"
        b"<description>Short publisher summary</description>"
        b"</item></channel></rss>"
    )


@pytest.fixture
def db():
    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and (target.database == "test" or target.database.endswith("_test"))
    assert (target.host, target.port, target.database) != (
        application.host,
        application.port,
        application.database,
    ), "Refusing to reset application database"
    engine = create_engine(settings.test_database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(
            Source(
                id=SOURCE_DEFINITION["id"],
                publisher="MJBizDaily",
                endpoint=SOURCE_DEFINITION["endpoint"],
                family="news",
                geography="US-focused with international coverage",
                industries=["cannabis", "energy"],
                retrieval_method="publisher-rss",
                cadence_hours=1,
                health={},
            )
        )
        session.flush()
        job = Job(
            source_id=SOURCE_DEFINITION["id"],
            status="running",
            lease_owner="test",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        first_job = job.id
    yield engine, factory, first_job
    Base.metadata.drop_all(engine)
    engine.dispose()


def _new_job(factory):
    with factory.begin() as session:
        job = Job(
            source_id=SOURCE_DEFINITION["id"],
            status="running",
            lease_owner="test",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        return job.id


def test_rss_304_preserves_retained_facts_and_failed_refresh_keeps_last_good(db):
    _, factory, first_job = db
    request_headers = []
    calls = 0
    active_session = None

    def respond(request):
        nonlocal calls
        calls += 1
        assert active_session is not None and not active_session.in_transaction()
        request_headers.append(dict(request.headers))
        if calls == 1:
            return httpx.Response(
                200,
                headers={
                    "content-type": "application/rss+xml",
                    "etag": '"feed-v1"',
                    "last-modified": "Fri, 25 Sep 2026 14:00:00 GMT",
                },
                content=_feed(),
            )
        if calls == 2:
            assert request.headers["if-none-match"] == '"feed-v1"'
            assert request.headers["if-modified-since"] == "Fri, 25 Sep 2026 14:00:00 GMT"
            return httpx.Response(304, headers={"etag": '"feed-v1"'})
        return httpx.Response(503, headers={"content-type": "text/plain"}, content=b"offline")

    client = httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=False)
    definition = deepcopy(SOURCE_DEFINITION)
    try:
        with factory() as session:
            active_session = session
            first = process_job(session, first_job, "test", 1, definition, client)
            session.commit()
            assert first["new"] == 1
        with factory() as session:
            active_session = session
            source = session.get(Source, definition["id"])
            assert source is not None
            last_good = source.health["publisher_rss_conditional"]
            assert last_good["complete"] is True
            assert last_good["etag"] == '"feed-v1"'
            second_job = _new_job(factory)
            second = process_job(session, second_job, "test", 1, definition, client)
            session.commit()
            assert second["conditional_checked"] is True
            assert second["snapshot_item_count"] == 1
        with factory() as session:
            active_session = session
            assert session.scalar(select(func.count(Observation.id))) == 1
            assert session.scalar(select(func.count(Evidence.id))) == 1
            source = session.get(Source, definition["id"])
            assert source is not None
            after_304 = source.health["publisher_rss_conditional"]
            assert after_304["snapshot_digest"] == last_good["snapshot_digest"]
            assert after_304["last_checked_at"]
            third_job = _new_job(factory)
            with pytest.raises(SourceParseError, match="retrieval failed"):
                process_job(session, third_job, "test", 1, definition, client)
        with factory() as session:
            active_session = session
            source = session.get(Source, definition["id"])
            assert source is not None
            after_failure = source.health["publisher_rss_conditional"]
            assert after_failure["snapshot_digest"] == last_good["snapshot_digest"]
            assert after_failure["etag"] == '"feed-v1"'
            assert session.scalar(select(func.count(Observation.id))) == 1
    finally:
        client.close()


def test_rss_force_and_policy_revision_bypass_saved_validator(db, monkeypatch):
    _, factory, first_job = db
    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "application/rss+xml", "etag": '"feed-v1"'},
            content=_feed(),
        )

    client = httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=False)
    definition = deepcopy(SOURCE_DEFINITION)
    try:
        with factory() as session:
            process_job(session, first_job, "test", 1, definition, client)
            session.commit()
        forced_job = _new_job(factory)
        with factory.begin() as session:
            session.get(Job, forced_job).checkpoint = '{"force":true}'
        with factory() as session:
            process_job(session, forced_job, "test", 1, definition, client)
            session.commit()
        assert len(seen) == 2
        assert "if-none-match" not in seen[1].headers
        import gridlens.ingestion.service as service

        monkeypatch.setattr(service, "_RSS_PARSER_VERSION", "publisher-rss-v3")
        parser_job = _new_job(factory)
        with factory() as session:
            process_job(session, parser_job, "test", 1, definition, client)
            session.commit()
        assert "if-none-match" not in seen[2].headers
        monkeypatch.setattr(service, "EVALUATOR_VERSION", "news-evaluator-next")
        evaluator_job = _new_job(factory)
        with factory() as session:
            process_job(session, evaluator_job, "test", 1, definition, client)
            session.commit()
        assert "if-none-match" not in seen[3].headers
        monkeypatch.setattr(service, "ADMISSION_POLICY_VERSION", "admission-policy-next")
        admission_job = _new_job(factory)
        with factory() as session:
            process_job(session, admission_job, "test", 1, definition, client)
            session.commit()
        assert "if-none-match" not in seen[4].headers
        revised = _new_job(factory)
        changed_definition = deepcopy(definition)
        changed_definition["query"]["max_response_bytes"] += 1
        with factory() as session:
            process_job(session, revised, "test", 1, changed_definition, client)
            session.commit()
        assert len(seen) == 6
        assert "if-none-match" not in seen[5].headers
    finally:
        client.close()


@pytest.mark.parametrize(
    "body",
    [b"<rss><channel></channel></rss>", b"<rss><channel><item>"],
    ids=["empty-200", "malformed-200"],
)
def test_invalid_200_does_not_advance_last_good_validator(db, body):
    _, factory, first_job = db
    calls = 0

    def respond(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200,
                headers={"content-type": "application/rss+xml", "etag": '"good"'},
                content=_feed(),
            )
        if calls == 2:
            assert request.headers["if-none-match"] == '"good"'
            return httpx.Response(
                200,
                headers={"content-type": "application/rss+xml", "etag": '"bad"'},
                content=body,
            )
        raise AssertionError("Invalid refresh must fail without retrying the request")

    client = httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=False)
    definition = deepcopy(SOURCE_DEFINITION)
    try:
        with factory() as session:
            process_job(session, first_job, "test", 1, definition, client)
            session.commit()
        failed_job = _new_job(factory)
        with factory() as session, pytest.raises(SourceParseError):
            process_job(session, failed_job, "test", 1, definition, client)
        with factory() as session:
            source = session.get(Source, definition["id"])
            assert source is not None
            last_good = source.health["publisher_rss_conditional"]
            assert last_good["etag"] == '"good"'
            assert last_good["snapshot_item_count"] == 1
    finally:
        client.close()


def test_interrupted_rss_batch_keeps_cursor_and_retry_is_unconditional(db, monkeypatch):
    _, factory, first_job = db
    calls = 0
    revised_feed = _feed().replace(b"Short publisher", b"Revised publisher")

    def respond(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200,
                headers={"content-type": "application/rss+xml", "etag": '"good"'},
                content=_feed(),
            )
        if calls == 2:
            assert request.headers["if-none-match"] == '"good"'
            return httpx.Response(
                200,
                headers={"content-type": "application/rss+xml", "etag": '"revised"'},
                content=revised_feed,
            )
        assert "if-none-match" not in request.headers
        return httpx.Response(
            200,
            headers={"content-type": "application/rss+xml", "etag": '"revised"'},
            content=revised_feed,
        )

    client = httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=False)
    definition = deepcopy(SOURCE_DEFINITION)
    try:
        with factory() as session:
            process_job(session, first_job, "test", 1, definition, client)
            session.commit()
        retry_job = _new_job(factory)
        import gridlens.ingestion.service as service

        monkeypatch.setattr(
            service,
            "assess_retained_news",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("interrupted batch")),
        )
        with factory() as session, pytest.raises(RuntimeError, match="interrupted batch"):
            process_job(session, retry_job, "test", 1, definition, client)
        with factory() as session:
            source = session.get(Source, definition["id"])
            assert source is not None
            assert source.health["publisher_rss_conditional"]["etag"] == '"good"'
            job = session.get(Job, retry_job)
            assert job is not None and job.checkpoint
            assert not job.checkpoint.startswith("{")

        monkeypatch.undo()
        with factory() as session:
            process_job(session, retry_job, "test", 1, definition, client)
            session.commit()
        assert calls == 3
        with factory() as session:
            source = session.get(Source, definition["id"])
            assert source is not None
            assert source.health["publisher_rss_conditional"]["etag"] == '"revised"'
    finally:
        client.close()
