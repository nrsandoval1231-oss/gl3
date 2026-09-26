import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.api.app import app
from gridlens.ingestion.service import process_job
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    ChangeEvent,
    Evidence,
    Interpretation,
    Job,
    Observation,
    PowerNeed,
    Project,
    Source,
)
from gridlens.security import token_for
from gridlens.settings import settings


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
                id="mjbizdaily-news",
                publisher="MJBizDaily",
                endpoint="https://mjbizdaily.com/feed/",
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
            source_id="mjbizdaily-news",
            status="running",
            lease_owner="test",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        job_id = job.id
    yield engine, factory, job_id
    Base.metadata.drop_all(engine)
    engine.dispose()


def record(summary: str = "A company announces a cultivation facility", guid: str = "first-guid"):
    # Publisher GUID changes do not replace the canonical item URL identity.
    return {
        "document_number": "https://mjbizdaily.com/news/cultivation-facility/",
        "title": "A company announces a cultivation facility",
        "abstract": summary,
        "publication_date": "2026-09-25",
        "html_url": "https://mjbizdaily.com/news/cultivation-facility/",
        "source_hash": hashlib.sha256(summary.encode()).hexdigest(),
        "extraction_location": "RSS item title and description/summary",
    }


def test_collection_replay_and_changed_version_never_create_signals(db, monkeypatch):
    _, factory, job_id = db
    import gridlens.ingestion.service as service

    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [record()])
    with factory() as session:
        first = process_job(
            session,
            job_id,
            "test",
            1,
            {"id": "mjbizdaily-news", "retrieval_method": "publisher-rss"},
        )
    assert first["new"] == 1 and first["signals"] == 0
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [record(guid="corrected-guid")])
    with factory() as session:
        replay = process_job(
            session,
            job_id,
            "test",
            1,
            {"id": "mjbizdaily-news", "retrieval_method": "publisher-rss"},
        )
    assert replay["unchanged"] == 1
    monkeypatch.setattr(
        service,
        "retrieve_source",
        lambda *_args: [record("A company expands its cultivation facility", "revised-guid")],
    )
    with factory() as session:
        changed = process_job(
            session,
            job_id,
            "test",
            1,
            {"id": "mjbizdaily-news", "retrieval_method": "publisher-rss"},
        )
    assert changed["changed"] == 1 and changed["signals"] == 0
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Observation)) == 1
        assert session.scalar(select(func.count()).select_from(Evidence)) == 2
        assert session.scalar(select(func.count()).select_from(Project)) == 0
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 0
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == 0
        interpretation = session.scalar(select(Interpretation))
        assert interpretation and interpretation.status == "collection_only"


def test_authenticated_inbox_filters_and_paginates_retained_versions(db, monkeypatch):
    _, factory, _ = db
    monkeypatch.setattr("gridlens.api.app.SessionLocal", factory)
    with factory.begin() as session:
        session.add(
            Source(
                id="nc-commerce",
                publisher="North Carolina Department of Commerce",
                endpoint="https://www.commerce.nc.gov/news/press-releases",
                family="economic-development-publication",
                geography="North Carolina",
                industries=["manufacturing"],
                retrieval_method="nc-commerce-html",
                cadence_hours=24,
                health={},
            )
        )
        session.flush()
        observation = Observation(
            source_id="mjbizdaily-news",
            external_id="https://mjbizdaily.com/news/cultivation-facility/",
            title="A company announces a cultivation facility",
            abstract="Licensing and construction update",
            published_at=datetime(2026, 9, 25).date(),
            url="https://mjbizdaily.com/news/cultivation-facility/",
            content_hash="a" * 64,
        )
        session.add(observation)
        session.flush()
        session.add_all(
            [
                Evidence(
                    observation_id=observation.id,
                    content_hash=char * 64,
                    title=observation.title,
                    abstract=observation.abstract,
                    url=observation.url,
                    published_at=observation.published_at,
                    extraction_location="RSS item title and description/summary",
                )
                for char in ("a", "b")
            ]
        )
        session.add(
            Interpretation(
                observation_id=observation.id,
                content_hash="a" * 64,
                status="collection_only",
            )
        )
        nc_observation = Observation(
            source_id="nc-commerce",
            external_id="NC-TEST-1",
            title="Synthetic manufacturing announcement",
            abstract="A manufacturing site expansion.",
            published_at=datetime(2026, 9, 20).date(),
            url="https://www.commerce.nc.gov/news/press-releases/synthetic",
            content_hash="c" * 64,
        )
        session.add(nc_observation)
        session.flush()
        session.add(
            Evidence(
                observation_id=nc_observation.id,
                content_hash="c" * 64,
                title=nc_observation.title,
                abstract=nc_observation.abstract,
                url=nc_observation.url,
                published_at=nc_observation.published_at,
                extraction_location="title and abstract",
            )
        )
        session.add(
            Interpretation(
                observation_id=nc_observation.id,
                content_hash="c" * 64,
                status="accepted",
            )
        )
        for index, (title, abstract) in enumerate(
            (
                ("Uncultivated insurance commentary", "No event stated."),
                ("Grow", "facility licensing note."),
            )
        ):
            version = Observation(
                source_id="mjbizdaily-news",
                external_id=f"adversarial-{index}",
                title=title,
                abstract=abstract,
                published_at=datetime(2026, 9, 19).date(),
                url=f"https://mjbizdaily.com/news/adversarial-{index}/",
                content_hash=str(index) * 64,
            )
            session.add(version)
            session.flush()
            session.add(
                Evidence(
                    observation_id=version.id,
                    content_hash=str(index) * 64,
                    title=title,
                    abstract=abstract,
                    url=version.url,
                    published_at=version.published_at,
                    extraction_location="RSS item title and description/summary",
                )
            )
    client = TestClient(app)
    assert client.get("/api/ingestion").status_code == 401
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    page = client.get("/api/ingestion?source_id=mjbizdaily-news&vertical=cannabis&limit=1").json()
    assert page["total"] == 4 and len(page["items"]) == 1
    second = client.get("/api/ingestion?source_id=mjbizdaily-news&limit=1&offset=1").json()
    assert second["items"][0]["content_hash"] != page["items"][0]["content_hash"]
    assert page["items"][0]["qualification_state"] == "Not assessed"
    assert page["items"][0]["topic_label"] == "Topic match - review required"
    all_items = client.get("/api/ingestion?limit=10").json()
    assert all_items["total"] == 5
    assert (
        client.get("/api/ingestion?source_id=nc-commerce").json()["items"][0]["qualification_state"]
        == "Linked to opportunity"
    )
    watched = client.get("/api/ingestion?watch_only=true&limit=2&offset=2").json()
    assert watched["total"] == 4 and len(watched["items"]) == 2
    assert all(item["matched_terms"] for item in watched["items"])
