"""Retained syndicated context cannot become independent qualification authority."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
from gridlens.ingestion.adapters.socrata_permits import render_record
from gridlens.ingestion.registry import load_registry
from gridlens.ingestion.service import process_records
from gridlens.intelligence.research_evidence import retain_research_document
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    Evidence,
    Interpretation,
    Job,
    Observation,
    PowerNeed,
    Project,
)
from gridlens.settings import settings


@pytest.fixture
def authority_db():
    test_url = make_url(settings.test_database_url)
    assert test_url.database and test_url.database.endswith("_test")
    assert test_url != make_url(settings.database_url)
    schema = "authority_boundary_" + uuid4().hex
    admin = create_engine(settings.test_database_url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        settings.test_database_url, connect_args={"options": f"-csearch_path={schema}"}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    source = next(item for item in load_registry() if item["id"] == "austin-building-permits")
    try:
        with factory.begin() as session:
            from gridlens.persistence.models import Source

            session.add(
                Source(
                    **{
                        key: value
                        for key, value in source.items()
                        if key in Source.__table__.columns
                    }
                )
            )
            session.flush()
            job = Job(
                source_id=source["id"],
                status="running",
                lease_owner="authority-test",
                fence=1,
                lease_until=datetime.now(UTC) + timedelta(minutes=10),
            )
            session.add(job)
            session.flush()
            job_id = job.id
        yield factory, source, job_id
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_syndicated_copies_cannot_corroborate_or_promote_lead(authority_db):
    factory, source, job_id = authority_db
    record = render_record(
        source,
        {
            "permit_number": "AUTHORITY-TEST-1",
            "issue_date": "2026-09-01",
            "description": "Construct new data center.",
            "permit_type_desc": "Building Permit",
            "permit_class_mapped": "Commercial",
            "status_current": "Active",
            "original_address1": "811 Clayton Ln",
            "original_city": "Austin",
            "original_state": "TX",
            "project_id": "9001",
            "link": {"url": "https://abc.austintexas.gov/permit/9001"},
        },
    )
    with factory.begin() as session:
        process_records(
            session, job_id, "authority-test", 1, source, [record], commit=False, allow_model=False
        )
        need = session.scalar(select(PowerNeed))
        assert need is not None
        project = session.get(Project, need.project_id)
        assert project is not None
        project.name = "Orion Data Center"
        project.location = "811 Clayton Ln, Austin, TX"
        project.identity_facts = {
            **(project.identity_facts or {}),
            "site": "811 Clayton Ln, Austin, TX",
            "project_aliases": ["Orion Data Center"],
        }
        copies = [
            PublicDocument(
                "https://www.datacenterdynamics.com/news/orion-copy",
                "Orion Data Center construction update",
                "Orion Data Center at 811 Clayton Ln, Austin, TX construction is underway. "
                "A 40 MW temporary construction power requirement is reported.",
                datetime(2026, 9, 2, tzinfo=UTC).date(),
                datetime(2026, 10, 18, tzinfo=UTC),
            ),
            PublicDocument(
                "https://www.utilitydive.com/news/orion-syndicated-copy",
                "Orion Data Center construction update",
                "Orion Data Center at 811 Clayton Ln, Austin, TX construction is underway. "
                "A 40 MW temporary construction power requirement is reported.",
                datetime(2026, 9, 2, tzinfo=UTC).date(),
                datetime(2026, 10, 18, tzinfo=UTC),
            ),
        ]
        results = [retain_research_document(session, project, need, copy) for copy in copies]
        assert all(result["disposition"] == "ACCEPTED" for result in results), [
            (result["disposition"], result.get("reason"), result.get("match_basis"))
            for result in results
        ]
        assert results[1]["duplicate"] is True
        assert results[0]["evidence_id"] == results[1]["evidence_id"]
        assert session.scalar(select(func.count()).select_from(Observation)) == 2
        assert session.scalar(select(func.count()).select_from(Evidence)) == 2
        assert need.tier == "Signal"
        assert need.required_mw is None
        assert need.start_window is None
        assert need.duration is None
        accepted_reports = session.scalars(
            select(Interpretation).where(Interpretation.status == "accepted")
        ).all()
        assert len(accepted_reports) == 2  # one native permit and one de-duplicated report
