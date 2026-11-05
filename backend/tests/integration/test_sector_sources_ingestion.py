"""Workstream 5 records -> ingestion service -> Observation/Evidence on a disposable database.

Disposable test database only (TEST_DATABASE_URL must end in _test). No network.
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.ingestion.adapters import (
    msha_mines,
    nevi_awards,
    regulatory_events,
    sec_edgar_site_mw,
    tceq_aggregate,
)
from gridlens.ingestion.registry import load_registry
from gridlens.persistence.database import Base
from gridlens.persistence.models import Evidence, Job, Observation, PowerNeed, Project, Source
from gridlens.settings import settings

FIX = Path(__file__).parents[1] / "fixtures" / "ws5"
WORKER = "ws5-worker"


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    from gridlens.ingestion.adapters import sector_common

    monkeypatch.setattr(sector_common, "resolve_public", lambda _host: "8.8.8.8")


@pytest.fixture
def stage_db():
    target = make_url(settings.test_database_url)
    assert target.database and target.database.endswith("_test")
    assert target != make_url(settings.database_url)
    schema = "ws5_sources_" + uuid4().hex
    admin = create_engine(target)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(target, connect_args={"options": f"-csearch_path={schema}"})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def setup_source(factory, source_id: str):
    definition = copy.deepcopy(next(row for row in load_registry() if row["id"] == source_id))
    assert definition["enabled"] is False  # ships off; the test drives process_records directly
    with factory.begin() as session:
        session.add(
            Source(
                id=definition["id"],
                publisher=definition["publisher"],
                endpoint=definition["endpoint"],
                family=definition["family"],
                geography=definition["geography"],
                industries=definition["industries"],
                retrieval_method=definition["retrieval_method"],
                cadence_hours=definition["cadence_hours"],
                health={},
            )
        )
        session.flush()
        job = Job(
            source_id=definition["id"],
            status="running",
            lease_owner=WORKER,
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        return definition, job.id


def ingest(factory, definition, job_id, records) -> dict:
    from gridlens.ingestion.service import process_records

    with factory() as session:
        return process_records(
            session, job_id, WORKER, 1, definition, copy.deepcopy(records), allow_model=False
        )


def mines(statuses_override: dict[str, str] | None = None, extra_rows: int = 0):
    data = (FIX / "msha-mines.txt").read_bytes()
    rows = msha_mines.parse_mines(
        data,
        states=["TX", "OK", "NM"],
        statuses=["Active", "New Mine", "Intermittent", "Temporarily Idled", "NonProducing"],
        max_records=100,
    )
    for row in rows:
        if statuses_override and row["MINE_ID"] in statuses_override:
            row["CURRENT_MINE_STATUS"] = statuses_override[row["MINE_ID"]]
    if extra_rows:
        clone = dict(rows[0])
        clone["MINE_ID"] = "4100999"
        clone["CURRENT_MINE_NAME"] = "New Test Quarry"
        rows.append(clone)
    return [msha_mines.build_record(row, "Fri, 30 Oct 2026 12:31:40 GMT") for row in rows]


def test_msha_weekly_diff_creates_new_and_changed_mines_only(stage_db):
    definition, job_id = setup_source(stage_db, "msha-mines")
    week1 = mines()
    first = ingest(stage_db, definition, job_id, week1)
    assert first["new"] == len(week1) == 6

    same = ingest(stage_db, definition, job_id, mines())
    assert same["new"] == 0 and same["changed"] == 0 and same["unchanged"] == 6

    target = week1[0]["document_number"].removeprefix("MSHA-")
    with stage_db() as session:
        first_seen = {
            o.external_id: o.first_seen_at for o in session.scalars(select(Observation)).all()
        }
    week2 = ingest(
        stage_db,
        definition,
        job_id,
        mines(statuses_override={target: "Temporarily Idled"}, extra_rows=1),
    )
    assert week2["new"] == 1 and week2["changed"] == 1 and week2["unchanged"] == 5

    with stage_db() as session:
        observations = session.scalars(select(Observation)).all()
        assert len(observations) == 7
        for observation in observations:
            if observation.external_id in first_seen:  # first_seen_at is never rewritten
                assert observation.first_seen_at == first_seen[observation.external_id]
        evidence = session.scalars(select(Evidence)).all()
        assert len(evidence) == 8  # six first versions, one changed version, one new mine
        assert all(e.observed_at is not None for e in evidence)
        assert all(o.first_seen_at is not None for o in observations)
        # Evidence only: nothing became a need or a project.
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 0
        assert session.scalar(select(func.count()).select_from(Project)) == 0


def test_dates_provenance_and_no_demand_for_every_record_kind(stage_db):
    rows = json.loads((FIX / "tceq-aggregate.json").read_text(encoding="utf-8"))
    features = json.loads((FIX / "nevi-features.json").read_text(encoding="utf-8"))["features"]
    sec_text = sec_edgar_site_mw.filing_text((FIX / "sec-10k-excerpt.htm").read_bytes())
    sec_records = [
        sec_edgar_site_mw.build_record(
            statement,
            company="Riot Platforms, Inc.",
            cik="0001167419",
            filing={
                "accessionNumber": "0001104659-26-022322",
                "filingDate": "2026-03-02",
                "reportDate": "2025-12-31",
                "form": "10-K",
            },
            url="https://www.sec.gov/Archives/edgar/data/1167419/000110465926022322/x.htm",
        )
        for statement in sec_edgar_site_mw.extract_statements(sec_text, limit=50)
    ]
    batches = {
        "texas-tceq-aggregate-production": [
            tceq_aggregate.build_record(tceq_aggregate.normalize(row)) for row in rows
        ],
        "texas-txdot-nevi-awards": [
            nevi_awards.build_record(nevi_awards.normalize(f["attributes"])) for f in features
        ],
        "sec-edgar-site-mw": sec_records,
        "regulatory-event-feed": [
            regulatory_events.build_record(e) for e in regulatory_events.load_events()
        ],
    }
    for source_id, records in batches.items():
        definition, job_id = setup_source(stage_db, source_id)
        first = ingest(stage_db, definition, job_id, records)
        assert first["new"] == len(records) > 0, source_id
        replay = ingest(stage_db, definition, job_id, records)
        assert replay["new"] == 0 and replay["unchanged"] == len(records), source_id

    with stage_db() as session:
        total = sum(len(v) for v in batches.values())
        assert session.scalar(select(func.count()).select_from(Observation)) == total
        assert session.scalar(select(func.count()).select_from(Evidence)) == total
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 0
        assert session.scalar(select(func.count()).select_from(Project)) == 0
        for observation in session.scalars(select(Observation)).all():
            assert observation.first_seen_at is not None
        events = session.scalars(
            select(Evidence)
            .join(Observation)
            .where(Observation.source_id == "regulatory-event-feed")
        ).all()
        assert {str(e.published_at) for e in events} == {
            "2026-08-03",
            "2026-09-14",
            "2026-09-21",
            "2026-10-19",
        }
        sec = session.scalars(
            select(Evidence).join(Observation).where(Observation.source_id == "sec-edgar-site-mw")
        ).all()
        assert sec and all("accession" in e.abstract for e in sec)
        assert all(str(e.published_at) == "2026-03-02" for e in sec)


def test_a_changed_award_adds_a_version_and_keeps_first_seen(stage_db):
    features = json.loads((FIX / "nevi-features.json").read_text(encoding="utf-8"))["features"]
    definition, job_id = setup_source(stage_db, "texas-txdot-nevi-awards")
    first = [nevi_awards.build_record(nevi_awards.normalize(f["attributes"])) for f in features]
    ingest(stage_db, definition, job_id, first)
    with stage_db() as session:
        seen = {o.external_id: o.first_seen_at for o in session.scalars(select(Observation))}
    moved = copy.deepcopy(features)
    moved[0]["attributes"]["STATUS"] = "Pre-Construction"
    second = [nevi_awards.build_record(nevi_awards.normalize(f["attributes"])) for f in moved]
    counts = ingest(stage_db, definition, job_id, second)
    assert counts["changed"] == 1 and counts["new"] == 0
    with stage_db() as session:
        assert session.scalar(select(func.count()).select_from(Observation)) == len(features)
        assert {
            o.external_id: o.first_seen_at for o in session.scalars(select(Observation))
        } == seen
        assert session.scalar(select(func.count()).select_from(Evidence)) == len(features) + 1


def test_a_rate_limited_origin_ingests_nothing_and_keeps_prior_evidence(stage_db):
    rows = json.loads((FIX / "tceq-aggregate.json").read_text(encoding="utf-8"))
    definition, job_id = setup_source(stage_db, "texas-tceq-aggregate-production")
    ingest(
        stage_db,
        definition,
        job_id,
        [tceq_aggregate.build_record(tceq_aggregate.normalize(row)) for row in rows],
    )
    client = httpx.Client(
        follow_redirects=False,
        transport=httpx.MockTransport(
            lambda r: httpx.Response(429, headers={"retry-after": "7200"})
        ),
    )
    from gridlens.ingestion.adapters.sector_common import Pacer

    with pytest.raises(httpx.HTTPStatusError):
        tceq_aggregate.retrieve(
            definition, client, pacer=Pacer(clock=lambda: 0.0, sleep=lambda _s: None)
        )
    with stage_db() as session:
        assert session.scalar(select(func.count()).select_from(Evidence)) == len(rows)


def test_published_at_null_where_unstated_and_sec_accessions_are_remembered(stage_db):
    rows = json.loads((FIX / "tceq-aggregate.json").read_text(encoding="utf-8"))
    definition, job_id = setup_source(stage_db, "texas-tceq-aggregate-production")
    ingest(
        stage_db,
        definition,
        job_id,
        [tceq_aggregate.build_record(tceq_aggregate.normalize(row)) for row in rows],
    )
    sec_text = sec_edgar_site_mw.filing_text((FIX / "sec-10k-excerpt.htm").read_bytes())
    sec_definition, sec_job = setup_source(stage_db, "sec-edgar-site-mw")
    filing = {
        "accessionNumber": "0001104659-26-022322",
        "filingDate": "2026-03-02",
        "reportDate": "2025-12-31",
        "form": "10-K",
    }
    ingest(
        stage_db,
        sec_definition,
        sec_job,
        [
            sec_edgar_site_mw.build_record(
                st, company="Riot", cik="0001167419", filing=filing, url="https://www.sec.gov/x.htm"
            )
            for st in sec_edgar_site_mw.extract_statements(sec_text, limit=50)
        ],
    )
    with stage_db() as session:
        tceq = session.scalars(
            select(Evidence).join(Observation).where(Observation.source_id == definition["id"])
        ).all()
        assert tceq and all(e.published_at is None for e in tceq)
        assert all(e.observed_at is not None for e in tceq)
        sec_ids = session.scalars(
            select(Observation.external_id).where(Observation.source_id == "sec-edgar-site-mw")
        ).all()
        assert sec_ids and all("0001104659-26-022322" in row for row in sec_ids)


def test_sec_retrieval_does_not_suppress_filing_after_first_statement(stage_db, monkeypatch):
    """One committed statement must not mark the entire SEC filing complete."""
    from gridlens.ingestion import service

    sec_text = sec_edgar_site_mw.filing_text((FIX / "sec-10k-excerpt.htm").read_bytes())
    definition, job_id = setup_source(stage_db, "sec-edgar-site-mw")
    statements = sec_edgar_site_mw.extract_statements(sec_text, limit=50)
    assert len(statements) > 1
    filing = {
        "accessionNumber": "0001104659-26-022322",
        "filingDate": "2026-03-02",
        "reportDate": "2025-12-31",
        "form": "10-K",
    }
    first = sec_edgar_site_mw.build_record(
        statements[0],
        company="Riot",
        cik="0001167419",
        filing=filing,
        url="https://www.sec.gov/x.htm",
    )
    ingest(stage_db, definition, job_id, [first])

    seen: dict[str, object] = {}
    monkeypatch.setattr(service, "_prepare_acquisition_network", lambda *_args: None)
    monkeypatch.setattr(service, "_lock_current_acquisition_source", lambda *_args: None)

    complete_filing = [
        sec_edgar_site_mw.build_record(
            statement,
            company="Riot",
            cik="0001167419",
            filing=filing,
            url="https://www.sec.gov/x.htm",
        )
        for statement in statements
    ]

    def retrieve(source, _client):
        seen.update(source)
        return complete_filing

    monkeypatch.setattr(service, "retrieve_source", retrieve)
    with stage_db() as session:
        result = service._retrieve_source_outside_transaction(
            session, job_id, WORKER, 1, definition, None
        )

    assert isinstance(result, list) and len(result) == len(statements)
    assert "known_accessions" not in seen
    counts = ingest(stage_db, definition, job_id, result)
    assert counts["new"] == len(statements) - 1
    assert counts["unchanged"] == 1
