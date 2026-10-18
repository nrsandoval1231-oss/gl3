"""Raw publisher href provenance survives evidence persistence and same-version replay."""

from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.ingestion.adapters.ceqanet import parse_document
from gridlens.ingestion.adapters.ceqanet import parse_listing as parse_ceqa_listing
from gridlens.ingestion.adapters.ceqanet import record as ceqanet_record
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.nc_commerce import _listing_rows, _parse_article
from gridlens.ingestion.adapters.tceq_nsr_pending import _record as tceq_record
from gridlens.ingestion.adapters.tceq_nsr_pending import parse_listing as parse_tceq_listing
from gridlens.ingestion.service import process_job
from gridlens.persistence.database import Base
from gridlens.persistence.models import Evidence, Interpretation, Job, Observation, Source
from gridlens.settings import settings

FIXTURES = Path(__file__).parents[1] / "fixtures"
NC_ID = "nc-commerce"
TCEQ_ID = "texas-tceq-nsr-pending"
CEQA_ID = "california-ceqanet-data-centers"


@pytest.fixture
def db():
    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and (target.database == "test" or target.database.endswith("_test")), (
        "Refusing destructive setup without an explicit *_test database"
    )
    assert (target.host, target.port, target.database) != (
        application.host,
        application.port,
        application.database,
    ), "TEST_DATABASE_URL must differ from DATABASE_URL"
    from sqlalchemy import create_engine

    engine = create_engine(settings.test_database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    definitions = {
        NC_ID: (
            "NC Commerce",
            "nc-commerce-html",
            "https://www.commerce.nc.gov/news/press-releases",
        ),
        TCEQ_ID: (
            "Texas Commission on Environmental Quality",
            "tceq-nsr-pending",
            "https://www.tceq.texas.gov/assets/public/permitting/air/reports/applications/nsr-pending-permits.html",
        ),
        CEQA_ID: (
            "California CEQAnet",
            "ceqanet-data-centers",
            "https://ceqanet.lci.ca.gov/Search",
        ),
    }
    with factory.begin() as session:
        for source_id, (publisher, method, endpoint) in definitions.items():
            session.add(
                Source(
                    id=source_id,
                    publisher=publisher,
                    endpoint=endpoint,
                    family="official-records",
                    geography="US",
                    industries=["energy"],
                    retrieval_method=method,
                    health={},
                )
            )
            session.flush()
            session.add(
                Job(
                    source_id=source_id,
                    status="running",
                    lease_owner="provenance-test",
                    fence=1,
                    lease_until=datetime.now(UTC) + timedelta(minutes=10),
                )
            )
        session.flush()
        jobs = {job.source_id: job.id for job in session.scalars(select(Job)).all()}
    yield factory, jobs
    Base.metadata.drop_all(engine)
    engine.dispose()


def _adapter_records():
    nc_canonical = "https://www.commerce.nc.gov/news/press-releases/2026/10/01/example-story"
    nc_rows = _listing_rows(
        BeautifulSoup(
            '<div class="view-content"><div class="views-row">'
            '<div class="views-field-title"><a href="/index%2ephp/news/press-releases/'
            '2026/10/01/example-story">Example Story</a></div>'
            '<div class="views-field-field-release-date"><span property="dc:date" '
            'content="2026-10-01"></span></div></div></div>',
            "html.parser",
        )
    )
    nc_listing = nc_rows[0]
    nc_article = """<html><head>
    <link rel="canonical" href="/news/press-releases/2026/10/01/example-story">
    </head>
    <body><h1 class="node__title">Example Story</h1>
    <div class="first-published"><time datetime="2026-10-01"></time></div>
    <article><div class="field--name-body">
    <p>A dated publisher report about activity.</p></div></article>
    </body></html>"""
    nc = _parse_article(
        nc_article.encode(),
        nc_listing,
        nc_canonical,
    )

    tceq_rows = parse_tceq_listing(
        (FIXTURES / "tceq-nsr-pending-excerpt.html").read_bytes(), date(2026, 10, 14)
    )
    tceq = tceq_record(
        next(row for row in tceq_rows if row["facility"] == "LONGHORN DATA CENTER"), None
    )

    ceqa_rows = parse_ceqa_listing((FIXTURES / "ceqanet-search-excerpt.html").read_bytes())
    ceqa_row = next(row for row in ceqa_rows if row["sch"] == "2026020574")
    ceqa_doc = parse_document((FIXTURES / "ceqanet-document-2026020574-excerpt.html").read_bytes())
    ceqa = ceqanet_record(ceqa_row, ceqa_doc)
    return {NC_ID: nc, TCEQ_ID: tceq, CEQA_ID: ceqa}


def _alias_record(source_id: str, record: dict):
    alias = deepcopy(record)
    if source_id == NC_ID:
        alias["source_url"] = (
            "https://www.commerce.nc.gov/index%2ephp/news/press-releases/2026/10/01/example-story"
        )
    elif source_id == TCEQ_ID:
        alias["permit"]["source_link_hrefs"] = {
            "plain language notice": (
                "/permitting/air/newsourcereview/airpermits-pendingpermit-apps#400428"
            ),
            "application": "/assets/public/permitting/air/reports/applications/400428-tc.pdf",
        }
    else:
        alias["permit"]["source_link_hrefs"]["CEQAnet document"] = "/2026020574"
    return alias


def test_adapter_href_provenance_survives_process_job_reopen_and_alias_replay(db, monkeypatch):
    factory, jobs = db
    records = _adapter_records()
    definitions = {
        NC_ID: {"id": NC_ID, "retrieval_method": "nc-commerce-html"},
        TCEQ_ID: {"id": TCEQ_ID, "retrieval_method": "tceq-nsr-pending"},
        CEQA_ID: {"id": CEQA_ID, "retrieval_method": "ceqanet-data-centers"},
    }

    import gridlens.ingestion.service as service

    monkeypatch.setattr(service, "retrieve_source", lambda source, _client: [records[source["id"]]])

    # This failure occurs after the common evidence commit; the retained provenance
    # must remain available even though the NC interpretation does not complete.
    def unavailable_interpretation(_record):
        raise SourceParseError("synthetic interpretation failure")

    original_observation_hashes = {}
    with monkeypatch.context() as failure_patch:
        failure_patch.setattr(service, "interpret", unavailable_interpretation)
        with factory() as session:
            process_job(session, jobs[NC_ID], "provenance-test", 1, definitions[NC_ID])
    # Keep all later processing offline. NC Commerce is deliberately a
    # context-only source, so the replay exercises that durable interpretation path.
    monkeypatch.setattr(
        service,
        "interpret",
        lambda _record: {
            "name": "Example Story project context",
            "activity_key": "facility-expansion",
            "rationale": "Synthetic deterministic context for provenance testing.",
            "location": "North Carolina",
        },
    )

    for source_id in (TCEQ_ID, CEQA_ID):
        with factory() as session:
            process_job(session, jobs[source_id], "provenance-test", 1, definitions[source_id])

    # Session closure/reopen proves the raw href is stored on the durable evidence
    # row rather than being available only in an adapter result or assessment.
    with factory() as session:
        for source_id, record in records.items():
            observation = session.scalar(
                select(Observation).where(
                    Observation.source_id == source_id,
                    Observation.external_id == record["document_number"],
                )
            )
            assert observation is not None
            evidence = session.scalar(
                select(Evidence).where(Evidence.observation_id == observation.id)
            )
            assert evidence is not None
            assert evidence.url == record["html_url"] == observation.url
            assert evidence.provenance["raw_source_links"]
            original_observation_hashes[source_id] = observation.content_hash
            assert evidence.content_hash == record["source_hash"]
        failed = session.scalar(
            select(Interpretation).join(Observation).where(Observation.source_id == NC_ID)
        )
        assert failed is not None and failed.status == "failed"
        assert (
            session.scalar(
                select(Interpretation.status)
                .join(Observation)
                .where(Observation.source_id == TCEQ_ID)
            )
            == "rejected"
        )
        assert (
            session.scalar(
                select(Interpretation.status)
                .join(Observation)
                .where(Observation.source_id == CEQA_ID)
            )
            == "accepted"
        )
        nc_observation = session.scalar(select(Observation).where(Observation.source_id == NC_ID))
        assert nc_observation is not None
        assert session.scalar(
            select(Evidence.provenance).where(Evidence.observation_id == nc_observation.id)
        )["raw_source_links"]["article"] == [records[NC_ID]["source_url"]]

    aliases = {source_id: _alias_record(source_id, row) for source_id, row in records.items()}
    monkeypatch.setattr(service, "retrieve_source", lambda source, _client: [aliases[source["id"]]])
    for _replay in range(2):
        for source_id in (NC_ID, TCEQ_ID, CEQA_ID):
            with factory() as session:
                result = process_job(
                    session, jobs[source_id], "provenance-test", 1, definitions[source_id]
                )
            assert result["unchanged"] == 1

    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Observation)) == 3
        assert session.scalar(select(func.count()).select_from(Evidence)) == 3
        nc_interpretation = session.scalar(
            select(Interpretation).join(Observation).where(Observation.source_id == NC_ID)
        )
        assert nc_interpretation is not None
        assert nc_interpretation.assessment["decision"] == "context_only"
        for source_id, record in records.items():
            observation = session.scalar(
                select(Observation).where(Observation.source_id == source_id)
            )
            assert observation is not None
            evidence = session.scalar(
                select(Evidence).where(Evidence.observation_id == observation.id)
            )
            assert evidence is not None
            assert observation.url == evidence.url == record["html_url"]
            assert observation.content_hash == original_observation_hashes[source_id]
            assert evidence.content_hash == record["source_hash"]
            raw_links = evidence.provenance["raw_source_links"]
            assert all(len(values) == 2 for values in raw_links.values())
            alias_record = aliases[source_id]
            expected_raw = (
                {"article": {record["source_url"], alias_record["source_url"]}}
                if source_id == NC_ID
                else {
                    label: {
                        record["permit"]["source_link_hrefs"][label],
                        alias_record["permit"]["source_link_hrefs"][label],
                    }
                    for label in record["permit"]["source_link_hrefs"]
                }
            )
            assert {label: set(values) for label, values in raw_links.items()} == expected_raw
