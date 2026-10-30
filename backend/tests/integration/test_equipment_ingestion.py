"""Synthetic end-to-end evidence binding through the ordinary ingestion path."""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.ingestion.registry import load_registry
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    EvidencePackage,
    Job,
    Observation,
    PowerNeed,
    Source,
)
from gridlens.settings import settings


@pytest.fixture
def equipment_ingestion_db():
    target = make_url(settings.test_database_url)
    assert target.database and target.database.endswith("_test")
    assert target != make_url(settings.database_url)
    schema = "equipment_ingestion_" + uuid4().hex
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


def test_equipment_schedule_is_materialized_and_accepted_permit_replay_is_idempotent(
    equipment_ingestion_db,
):
    from gridlens.ingestion.service import process_records

    factory = equipment_ingestion_db
    definition = next(row for row in load_registry() if row["id"] == "oklahoma-deq-public-review")
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
            lease_owner="synthetic-equipment-worker",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        job_id = job.id

    schedule = (
        "Company: Prairie Example LLC\n"
        "Facility: Prairie Compression Station\n"
        f"As of: {date.today().isoformat()}\n"
        "Equipment ID: C-101 | Type: compressor | Drive: electric | "
        "Rating: 1000 hp mechanical output | Count: 2 | Operating: 1 | "
        "State: proposed | Role: duty | Efficiency: 0.90"
    )
    record = {
        "document_number": "SYN-EQUIP-1",
        "title": "Prairie Compression Station public review",
        "abstract": schedule,
        "publication_date": date.today().isoformat(),
        "event_date": date.today().isoformat(),
        "event_date_label": "Public review date",
        "html_url": "https://example.test/ok-deq/SYN-EQUIP-1",
        "extraction_location": "Synthetic equipment schedule",
        "permit": {
            "source_type": "oklahoma-deq-public-review",
            "row_id": "SYN-EQUIP-1",
            "facility": "Prairie Compression Station",
            "applicant": "Prairie Example LLC",
            "location": "1 Sample Road, Tulsa, OK",
            "description": (
                "Natural gas compression station and proposed electric pump expansion."
            ),
            "power_signals": [],
        },
    }

    def run(record_value):
        with factory() as session:
            return process_records(
                session,
                job_id,
                "synthetic-equipment-worker",
                1,
                definition,
                [record_value],
                allow_model=False,
            )

    first = run(record)
    assert first["permit_accepted"] == 1
    with factory() as session:
        need = session.scalar(select(PowerNeed))
        assert need is not None
        need_id, project_id = need.id, need.project_id
        assert need.tier == "Signal"
        assert need.required_mw is None and need.supply == "Unknown"
        assert session.scalar(select(func.count()).select_from(EvidencePackage)) == 1
        observation = session.scalar(select(Observation))
        assert observation is not None and "Equipment ID: C-101" in observation.abstract
        from gridlens.api.app import opportunity_projection
        from gridlens.intelligence.equipment_intelligence import current_equipment_investigation
        from gridlens.intelligence.opportunity_intelligence import attach_cards

        investigation = current_equipment_investigation(session, need_id, project_id)
        assert investigation is not None and investigation["status"] == "SUPPORTED", (
            investigation.get("unresolved_questions") if investigation else None
        )
        assert investigation["company"] == "Prairie Example LLC"
        assert investigation["facility"] == "Prairie Compression Station"
        assert investigation["demand"]["coincident_kw"].startswith("828.555")
        assert investigation["demand"]["connected_kw"].startswith("1657.110")
        assert investigation["demand"]["incremental_kw"].startswith("1657.110")
        assert investigation["residual_gap_kw"] is None
        assert investigation["supply_constraint_evidence"] == []
        assert investigation["decision_maker"] is None
        assert investigation["next_action"]
        items = opportunity_projection(
            session,
            selected_need_ids={need_id},
            include_operator_fact_refs=True,
        )
        assert len(items) == 1
        attach_cards(session, items, {})
        card = items[0]["intelligence_card"]
        demand_field = next(
            field for field in card["fields"] if field["key"] == "calculatedEquipmentDemand"
        )
        assert card["equipment_demand"]["status"] == "SUPPORTED"
        assert demand_field["status"] == "Calculated"
        assert demand_field["sources"][0]["reference"].startswith("equipment-evidence:")
        assert card["qualification"] == "Signal" and card["power_gap"] is None
        assert "Unknown" == items[0]["supply"]

    replay = run(record)
    with factory() as session:
        need = session.get(PowerNeed, need_id)
        assert need is not None and need.project_id == project_id
        assert need.tier == "Signal"
        assert need.required_mw is None and need.supply == "Unknown"
        assert session.scalar(select(func.count()).select_from(EvidencePackage)) == 1
    assert replay["permit_accepted"] == 1

    partial_schedule = (
        "Company: Prairie Example LLC\n"
        "Facility: Prairie Compression Station\n"
        f"As of: {date.today().isoformat()}\n"
        "Equipment ID: C-101 | Type: compressor | Drive: electric | "
        "Rating: 1000 hp mechanical output | Count: 2 | Operating: 1 | "
        "State: proposed | Role: duty"
    )
    partial_record = {**record, "abstract": partial_schedule}
    refreshed = run(partial_record)
    assert refreshed["permit_accepted"] == 1
    with factory() as session:
        need = session.get(PowerNeed, need_id)
        assert need is not None and need.tier == "Signal"
        assert need.required_mw is None and need.supply == "Unknown"
        assert session.scalar(select(func.count()).select_from(EvidencePackage)) == 2
        investigation = current_equipment_investigation(session, need_id, project_id)
        assert investigation is not None and investigation["status"] == "PARTIAL"
        assert investigation["demand"]["coincident_kw"] is None
        assert investigation["residual_gap_kw"] is None


def test_real_ok_deq_discovery_rows_retain_evidence_without_inventing_demand(
    equipment_ingestion_db,
):
    from pathlib import Path

    from gridlens.ingestion.adapters.ok_deq_public_review import _record, parse_listing
    from gridlens.ingestion.service import process_records
    from gridlens.persistence.models import Evidence, Interpretation

    factory = equipment_ingestion_db
    definition = next(row for row in load_registry() if row["id"] == "oklahoma-deq-public-review")
    body = (
        Path(__file__).parents[1] / "fixtures" / "ok-deq-oil-gas-discovery-excerpt.html"
    ).read_bytes()
    records = [_record(row) for row in parse_listing(body)]
    assert len(records) == 3
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
            lease_owner="discovery-test-worker",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        job_id = job.id

    for _ in range(2):
        with factory() as session:
            result = process_records(
                session,
                job_id,
                "discovery-test-worker",
                1,
                definition,
                records,
                allow_model=False,
            )
            assert result["permit_accepted"] == 0
        with factory() as session:
            assert session.scalar(select(func.count()).select_from(Observation)) == 3
            assert session.scalar(select(func.count()).select_from(Evidence)) == 3
            assert session.scalar(select(func.count()).select_from(PowerNeed)) == 0
            assert session.scalar(select(func.count()).select_from(EvidencePackage)) == 0
            interpretations = session.scalars(select(Interpretation)).all()
            assert len(interpretations) == 3
            assert all(row.status == "rejected" for row in interpretations)
            evidence = session.scalars(select(Evidence)).all()
            assert all(row.event_date is not None for row in evidence)
            assert all(row.url.startswith("https://applications.deq.ok.gov/") for row in evidence)
            assert all("Power signal tags: none" in row.abstract for row in evidence)
