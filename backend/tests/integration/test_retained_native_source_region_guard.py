"""New retained-source rows preserve existing project and Need geography rules."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

pytest_plugins = ["test_customer_accounts"]


def test_aligned_project_is_retained_outside_need_region(customer_db):
    from gridlens.ingestion.adapters.retained_company_projects import (
        FAMILY,
        RETRIEVAL_METHOD,
        SOURCE_ID,
        retained_records,
    )
    from gridlens.ingestion.service import process_records
    from gridlens.persistence.browse_invalidation import install
    from gridlens.persistence.models import Job, PowerNeed, Project, Source

    corpus = Path(__file__).resolve().parents[3] / "eval" / "customer-commercial-v1"
    retained, _held = retained_records(corpus)
    aligned_record = next(
        row
        for row in retained
        if "sources/aligned.json" in row["retained_company_project"]["source_files"]
    )
    switch_record = next(
        row
        for row in retained
        if "sources/switch.json" in row["retained_company_project"]["source_files"]
    )
    source_definition = {
        "id": SOURCE_ID,
        "publisher": "retained offline public documents",
        "endpoint": "https://offline.invalid/retained",
        "family": FAMILY,
        "geography": "United States",
        "industries": ["data centers"],
        "retrieval_method": RETRIEVAL_METHOD,
        "cadence_hours": 24,
        "enabled": False,
        "registry_enabled": False,
    }
    worker = "retained-native-region-test"
    with customer_db.kw["bind"].begin() as connection:
        install(connection)
    with customer_db.begin() as session:
        session.add(Source(**source_definition))
        session.flush()
        job = Job(
            source_id=SOURCE_ID,
            status="running",
            lease_owner=worker,
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        job_id = job.id

    with customer_db() as session:
        process_records(
            session,
            job_id,
            worker,
            1,
            source_definition,
            [aligned_record, switch_record],
            allow_model=False,
        )

    with customer_db() as session:
        aligned = session.scalar(
            select(Project).where(Project.location == "Conesville Industrial Park")
        )
        switch = session.scalar(select(Project).where(Project.location == "Round Rock, TX"))
        assert aligned is not None
        assert aligned.region_status != "ELIGIBLE"
        assert aligned.region_state is None
        assert not session.scalar(select(PowerNeed.id).where(PowerNeed.project_id == aligned.id))
        assert switch is not None and switch.region_status == "ELIGIBLE"
