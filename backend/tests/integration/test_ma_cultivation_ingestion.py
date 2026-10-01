from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.domain.permit_interpretation import assess_permit
from gridlens.ingestion.adapters.ma_cultivation import retrieve
from gridlens.ingestion.registry import load_registry
from gridlens.ingestion.service import process_job
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    Evidence,
    Interpretation,
    Job,
    Observation,
    PowerNeed,
    Project,
    Source,
)
from gridlens.settings import settings

TODAY = date(2026, 10, 1)


def _row(*, number: str, status: str, license_status: str, company: str, address: str) -> dict:
    return {
        "LICENSE_NUMBER": f"L{number}",
        "APPLICATION_NUMBER": number,
        "LICENSE_TYPE": "Marijuana Cultivator",
        "APPLICATION_STATUS": status,
        "APPROVED_LICENSE_STAGE": "IN PROCESS",
        "SUBMITTED_DATE": "Thu Sep 03 2026 13:29:32 GMT-0400 (Eastern Daylight Time)",
        "ORIGINAL_SUBMITTED_DATE": "Mon Jun 15 2026 18:22:28 GMT-0400 (Eastern Daylight Time)",
        "APPLICATION_CREATED_DATE": "",
        "APPLICATION_APPROVED_DATE": "",
        "APPLICATION_DENIED_DATE": "",
        "BUSINESS_NAME": company,
        "BUSINESS_EMAIL": "licensing@rhythm.example",
        "BUSINESS_PHONE": "508-555-0100",
        "ESTABLISHMENT_ADDRESS_1": address,
        "ESTABLISHMENT_ADDRESS_2": "",
        "ESTABLISHMENT_CITY": "Uxbridge",
        "ESTABLISHMENT_STATE": "MA",
        "ESTABLISHMENT_ZIP": "01569",
        "LICENSE_STATUS": license_status,
        "COMMENCE_OPERATIONS_DATE": "",
        "CNB_DATE_OF_FINAL_LICENSURE": "",
        "LIC_START_DATE": "",
        "LIC_ORIGINAL_START_DATE": "",
        "LIC_EXPIRATION_DATE": "",
        "LIC_REVOCATION_DATE": "",
        "LIC_REVOKE_DATE": "",
        "LIC_SURRENDERED_DATE": "",
        "LIC_SURRENDER_DATE": "",
        "LIC_SUSPENDED_START_DATE": "",
        "LIC_SUSPENDED_END_DATE": "",
        "LIC_SUSPENSION_START_DATE": "",
        "LIC_SUSPENSION_END_DATE": "",
        "CCCLastUpdated": "2026-09-22",
        "EIN_TIN": "excluded",
    }


def _mock(rows: list[dict]) -> httpx.Client:
    body = json.dumps(rows).encode()
    return httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200, headers={"content-type": "application/json"}, content=body
            )
        )
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
    ), "Refusing destructive setup against the application database"
    engine = create_engine(settings.test_database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    definition = next(
        item for item in load_registry() if item["id"] == "ma-ccc-cultivation-applications"
    )
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
            lease_owner="test",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        job_id = job.id
    yield factory, job_id, definition
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_pending_application_signal_replay_and_source_failure_preserve_last_good(
    db, monkeypatch
) -> None:
    factory, job_id, definition = db
    import gridlens.ingestion.service as service

    pending = _row(
        number="MCN100001",
        status="PENDING",
        license_status="Incomplete",
        company="Rhythm of Life Cannabis LLC",
        address="616 Douglas Street",
    )
    approved = _row(
        number="MCN100002",
        status="APPROVED",
        license_status="Active",
        company="Historical Approved Cultivator LLC",
        address="1 Old Mill Road",
    )
    records = retrieve(definition, _mock([pending, approved]), today=TODAY)
    assert len(records) == 2
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: records)

    with factory() as session:
        first = process_job(session, job_id, "test", 1, definition)
    assert first["signals"] == 1
    with factory() as session:
        replay = process_job(session, job_id, "test", 1, definition)
        assert replay["unchanged"] == 2
        assert session.scalar(select(func.count()).select_from(Observation)) == 2
        assert session.scalar(select(func.count()).select_from(Evidence)) == 2
        assert session.scalar(select(func.count()).select_from(Project)) == 1
        need = session.scalar(select(PowerNeed))
        assert need is not None and need.activity_key == "cultivation-license-application"
        assert need.required_mw is None and need.supply == "Unknown"
        pending_assessment = session.scalar(
            select(Interpretation).where(Interpretation.content_hash == records[0]["source_hash"])
        ).assessment
        assert pending_assessment["decision"] == "accepted"
        assert pending_assessment["subject"] == "Rhythm of Life Cannabis LLC"
        assert pending_assessment["event_date_label"] == "Application resubmitted date"
        pending_observation = session.scalar(
            select(Observation).where(Observation.external_id == "MCN100001")
        )
        assert pending_observation is not None
        assert "business_email: licensing@rhythm.example" in pending_observation.abstract
        assert "EIN_TIN" not in (pending_observation.abstract or "")
        rejected = next(
            record for record in records if record["permit"]["application_status"] == "APPROVED"
        )
        assert assess_permit(rejected, as_of=TODAY)["decision"] == "rejected"
        assert "BUSINESS_EMAIL" in pending_assessment["source_field_citations"]

    def fail_snapshot(*_args):
        raise ValueError("simulated source snapshot failure")

    monkeypatch.setattr(service, "retrieve_source", fail_snapshot)
    with pytest.raises(ValueError, match="snapshot failure"):
        with factory() as session:
            process_job(session, job_id, "test", 1, definition)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Observation)) == 2
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 1
