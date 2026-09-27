import hashlib
import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.api.app import app
from gridlens.ingestion.service import _reported_mw, news_power_activity, process_job
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    ChangeEvent,
    Evidence,
    Interpretation,
    Job,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Source,
)
from gridlens.security import token_for
from gridlens.settings import settings


def test_reported_mw_uses_structured_domain_match_not_first_quote_number():
    assessment = {
        "demand_quote": "Campus capacity is 200 MW, but construction requires about 42 MW.",
        "demand_mw": "about 42 MW",
    }
    assert _reported_mw(assessment) == "about 42 MW"


def test_signal_activity_is_derived_from_the_validated_event_action():
    assert news_power_activity({"tier": "Signal", "action": "opens"}) == "operations"
    assert news_power_activity({"tier": "Signal", "action": "builds"}) == "construction"
    assert news_power_activity({"tier": "Signal", "action": "will be built"}) == "construction"
    assert news_power_activity({"tier": "Signal", "action": "announces"}) is None


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
        assert interpretation and interpretation.status == "rejected"
        assert interpretation.assessment and interpretation.assessment["decision"] == "rejected"
        assert interpretation.evaluator_version


def _project_record(
    summary: str = "", title: str = "Atlas begins construction at Atlas Mesa data center in Texas"
):
    url = "https://dcd.example/news/atlas-mesa/"
    return {
        "document_number": url,
        "title": title,
        "abstract": summary,
        "publication_date": "2026-09-25",
        "html_url": url,
        "source_hash": hashlib.sha256(f"{title}|{summary}".encode()).hexdigest(),
        "extraction_location": "RSS item title and description/summary",
    }


def test_applied_digital_will_be_built_signal_persists_with_construction_activity(db, monkeypatch):
    _, factory, _ = db
    job_id = _rss_source_job(factory, "applied-digital-news", "Applied Digital News")
    import gridlens.ingestion.service as service

    title = "Applied Digital reveals $3.2bn Delta Forge 2 AI data center will be built in Alabama"
    monkeypatch.setattr(
        service,
        "retrieve_source",
        lambda *_args: [_project_record("Operations could start by 2028", title)],
    )
    with factory() as session:
        service.process_job(
            session,
            job_id,
            "test",
            1,
            {"id": "applied-digital-news", "retrieval_method": "publisher-rss"},
        )
    with factory() as session:
        interpretation = session.scalar(select(Interpretation))
        need = session.scalar(select(PowerNeed))
        assert interpretation and interpretation.status == "accepted"
        assert interpretation.assessment["action"] == "will be built"
        assert interpretation.assessment["power_activity"] == "construction"
        assert need and need.activity_key == "construction"


def test_news_identity_does_not_merge_distinct_sites_for_same_company_and_state():
    from gridlens.ingestion.service import _news_identity_key

    assessment = {"subject": "Atlas", "location": "Texas", "action": "construction"}
    north = _news_identity_key(
        "Atlas starts construction at North Yard data center in Texas",
        "",
        "dcd-news",
        "north",
        assessment,
    )
    south = _news_identity_key(
        "Atlas starts construction at South Yard data center in Texas",
        "",
        "utility-dive-news",
        "south",
        assessment,
    )
    assert north != south


def _rss_source_job(factory, source_id: str, publisher: str):
    with factory.begin() as session:
        session.add(
            Source(
                id=source_id,
                publisher=publisher,
                endpoint=f"https://{source_id}.example/feed/",
                family="news",
                geography="United States",
                industries=["data centers"],
                retrieval_method="publisher-rss",
                cadence_hours=1,
                health={},
            )
        )
        session.flush()
        job = Job(
            source_id=source_id,
            status="running",
            lease_owner="test",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        return job.id


def test_prospect_persists_exact_requirement_not_campus_capacity(db, monkeypatch):
    _, factory, _ = db
    job_id = _rss_source_job(factory, "mixed-mw-news", "Mixed MW News")
    import gridlens.ingestion.service as service

    summary = (
        "Atlas Mesa data center campus capacity is 200 MW, but Atlas Mesa data center "
        "construction requires about 42 MW. Power supply for Atlas Mesa data center "
        "construction is delayed."
    )
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [_project_record(summary)])
    with factory() as session:
        service.process_job(
            session,
            job_id,
            "test",
            1,
            {"id": "mixed-mw-news", "retrieval_method": "publisher-rss"},
        )
    with factory() as session:
        need = session.scalar(select(PowerNeed))
        interpretation = session.scalar(select(Interpretation))
        assert need and need.tier == "Prospect"
        assert need.required_mw == "about 42 MW"
        assert interpretation and interpretation.assessment["demand_mw"] == "about 42 MW"


def test_rss_future_path_exact_duplicate_correction_and_replay(db, monkeypatch):
    _, factory, _ = db
    dcd_job = _rss_source_job(factory, "dcd-news", "Data Center Dynamics")
    utility_job = _rss_source_job(factory, "utility-dive-news", "Utility Dive")
    import gridlens.ingestion.service as service

    first = _project_record()
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [first])
    with factory() as session:
        initial = service.process_job(
            session, dcd_job, "test", 1, {"id": "dcd-news", "retrieval_method": "publisher-rss"}
        )
    assert initial["signals"] == 1
    with factory() as session:
        replay = service.process_job(
            session, dcd_job, "test", 1, {"id": "dcd-news", "retrieval_method": "publisher-rss"}
        )
    assert replay["signals"] == 1

    # Exact title/summary duplicate from another configured feed links to the same event.
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [first])
    with factory() as session:
        service.process_job(
            session,
            utility_job,
            "test",
            1,
            {"id": "utility-dive-news", "retrieval_method": "publisher-rss"},
        )
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Project)) == 1
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 1
        assert session.scalar(select(func.count()).select_from(NeedObservation)) == 2
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == 1
        need = session.scalar(select(PowerNeed))
        assert need and need.active and need.tier == "Signal" and need.required_mw is None

    # A current correction supersedes the exact syndicated old version and closes its need.
    corrected = _project_record(
        "Atlas canceled construction at the Atlas Mesa data center in Texas."
    )
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [corrected])
    with factory() as session:
        service.process_job(
            session, dcd_job, "test", 1, {"id": "dcd-news", "retrieval_method": "publisher-rss"}
        )
    with factory() as session:
        need = session.scalar(select(PowerNeed))
        assert need and not need.active
        assert session.scalar(select(func.count()).select_from(Project)) == 1
        assert session.scalar(select(func.count()).select_from(Evidence)) == 3
        interpretation = session.scalar(
            select(Interpretation).join(Observation).where(Observation.source_id == "dcd-news")
        )
        assert interpretation and interpretation.status == "rejected"
        assert interpretation.assessment and interpretation.assessment["decision"] == "rejected"
        assert len(interpretation.assessment["previous_decisions"]) == 1
        event_count = session.scalar(select(func.count()).select_from(ChangeEvent))

    with factory() as session:
        service.process_job(
            session, dcd_job, "test", 1, {"id": "dcd-news", "retrieval_method": "publisher-rss"}
        )
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == event_count
        assert session.scalar(select(func.count()).select_from(Evidence)) == 3


def test_rss_fence_loss_after_durable_evidence_is_retryable(db, monkeypatch):
    _, factory, _ = db
    job_id = _rss_source_job(factory, "dcd-news", "Data Center Dynamics")
    import gridlens.ingestion.service as service

    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [_project_record()])
    original_fence = service.assert_fence
    calls = 0

    def lose_after_evidence(session, current_job_id, worker_id, fence):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("Worker lease fence lost")
        return original_fence(session, current_job_id, worker_id, fence)

    monkeypatch.setattr(service, "assert_fence", lose_after_evidence)
    with factory() as session, pytest.raises(RuntimeError, match="fence"):
        service.process_job(
            session, job_id, "test", 1, {"id": "dcd-news", "retrieval_method": "publisher-rss"}
        )
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Observation)) == 1
        assert session.scalar(select(func.count()).select_from(Evidence)) == 1
        assert session.scalar(select(func.count()).select_from(Project)) == 0
        pending = session.scalar(select(Interpretation))
        assert pending and pending.status == "pending"

    monkeypatch.setattr(service, "assert_fence", original_fence)
    with factory() as session:
        service.process_job(
            session, job_id, "test", 1, {"id": "dcd-news", "retrieval_method": "publisher-rss"}
        )
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Project)) == 1
        assert session.scalar(select(Interpretation)).status == "accepted"


def test_apply_reports_interpretation_failure_and_retries(db, monkeypatch, tmp_path):
    _, factory, _ = db
    job_id = _rss_source_job(factory, "dcd-news", "Data Center Dynamics")
    import gridlens.ingestion.service as service

    script_path = Path(__file__).parents[3] / "scripts" / "reinterpret_news.py"
    spec = importlib.util.spec_from_file_location("reinterpret_news", script_path)
    assert spec and spec.loader
    reinterpret_news = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reinterpret_news)

    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [_project_record()])
    with factory() as session:
        service.process_job(
            session, job_id, "test", 1, {"id": "dcd-news", "retrieval_method": "publisher-rss"}
        )
    with factory.begin() as session:
        interpretation = session.scalar(select(Interpretation))
        interpretation.evaluator_version = "old-evaluator"
    original_assess = service.assess_news
    monkeypatch.setattr(
        service, "assess_news", lambda *_args: (_ for _ in ()).throw(RuntimeError())
    )
    monkeypatch.setattr("gridlens.persistence.database.SessionLocal", factory)
    output = tmp_path / "apply.json"
    monkeypatch.setattr(
        sys, "argv", ["reinterpret_news.py", "--apply", "--limit", "1", "--output", str(output)]
    )
    with pytest.raises(SystemExit) as failed:
        reinterpret_news.main()
    assert failed.value.code == 1
    failure_report = json.loads(output.read_text(encoding="utf-8"))
    assert failure_report["failed_or_pending"] == 1
    assert failure_report["decisions"][0]["status"] == "failed"
    assert failure_report["decisions"][0]["assessment"]["decision"] == "accepted"
    with factory() as session:
        interpretation = session.scalar(select(Interpretation))
        assert interpretation and interpretation.status == "failed"
        assert interpretation.assessment["decision"] == "accepted"

    monkeypatch.setattr(service, "assess_news", original_assess)
    reinterpret_news.main()
    retry_report = json.loads(output.read_text(encoding="utf-8"))
    assert retry_report["failed_or_pending"] == 0
    assert retry_report["decisions"][0]["status"] == "accepted"


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
                status="collection_only",
            )
        )
        session.add(
            Project(
                identity_key="legacy-nc-commerce-test",
                name="Synthetic manufacturing announcement",
                location="North Carolina",
                source_id=nc_observation.source_id,
                external_id=nc_observation.external_id,
            )
        )
        session.flush()
        nc_project = session.scalar(
            select(Project).where(Project.identity_key == "legacy-nc-commerce-test")
        )
        session.add(
            PowerNeed(
                project_id=nc_project.id,
                activity_key="manufacturing",
                tier="Signal",
                rationale="Existing linked record",
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
        == "Not assessed"
    )
    watched = client.get("/api/ingestion?watch_only=true&limit=2&offset=2").json()
    assert watched["total"] == 4 and len(watched["items"]) == 2
    assert all(item["matched_terms"] for item in watched["items"])
