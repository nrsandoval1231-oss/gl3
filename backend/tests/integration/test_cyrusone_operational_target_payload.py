"""The bounded CyrusOne operational deadline survives saved results projection."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

pytest_plugins = ["test_customer_accounts"]


def test_cyrusone_operational_target_survives_native_fact_and_browse_path(customer_db):
    from gridlens.ingestion.adapters.retained_company_projects import (
        FAMILY,
        RETRIEVAL_METHOD,
        SOURCE_ID,
        retained_records,
    )
    from gridlens.ingestion.service import process_records
    from gridlens.intelligence.buying_chain import enrich_buying_chain
    from gridlens.intelligence.customer_results import group_metadata, groups
    from gridlens.intelligence.saved_browse import current_generation, rebuild
    from gridlens.persistence.browse_invalidation import install
    from gridlens.persistence.models import (
        BrowseRow,
        Evidence,
        EvidencePackage,
        Job,
        Project,
        Source,
    )

    root = Path(__file__).resolve().parents[3]
    fixture = root / "eval/customer-commercial-v1"
    retained, _held = retained_records(fixture)
    cyrus_records = [
        item
        for item in retained
        if "sources/cyrusone.json" in item["retained_company_project"]["source_files"]
    ]
    assert len(cyrus_records) == 1
    project_name = "new data center adjacent to the Thad Hill Energy Center"
    expected_quote = (
        "The deal secures power, grid connection, and land to support a new state of the art "
        "facility that is currently under construction and expected to be operational by the "
        "fourth quarter of 2026."
    )

    with customer_db.kw["bind"].begin() as connection:
        install(connection)
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
    worker = "cyrusone-target-payload-test"
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
        counts = process_records(
            session,
            job_id,
            worker,
            1,
            source_definition,
            cyrus_records,
            allow_model=False,
        )
    assert counts["retrieved_records"] == 1

    with customer_db.begin() as session:
        project = session.scalar(select(Project).where(Project.name == project_name))
        evidence = session.scalar(select(Evidence).where(Evidence.url.contains("cyrusone.com")))
        assert project is not None and evidence is not None
        packages = session.scalars(
            select(EvidencePackage).where(
                EvidencePackage.project_id == project.id,
                EvidencePackage.evidence_id == evidence.id,
            )
        ).all()
        package = next(
            (
                row.payload
                for row in packages
                if isinstance(row.payload, dict) and row.payload.get("timeline_claims")
            ),
            None,
        )
        assert package is not None, packages
        claim = next(item for item in package["timeline_claims"] if item["quote"] == expected_quote)
        assert (
            claim["event_type"],
            claim["label"],
            claim["precision"],
            claim["qualifier"],
        ) == ("operational_target", "fourth quarter of 2026", "quarter", "deadline")

        enriched = enrich_buying_chain(
            session,
            project.id,
            retained_only=True,
            retained_target_evidence_id=evidence.id,
        )
        assert isinstance(enriched, dict)

    generation_result = rebuild(customer_db)
    assert generation_result["status"] == "published"
    with customer_db() as session:
        generation = current_generation(session)
        browse_row = session.scalar(
            select(BrowseRow).where(
                BrowseRow.generation_id == generation.id,
                BrowseRow.project_id == project.id,
            )
        )
        assert browse_row is not None
        saved_facts = browse_row.compact.get("customer_facts", [])
        saved_claims = [
            claim
            for fact_package in saved_facts
            for claim in fact_package.get("timeline_claims", [])
        ]
        saved_claim = next(item for item in saved_claims if item["quote"] == expected_quote)
        assert saved_claim["event_type"] == "operational_target"

        response = groups(session)
        cyrus = next(item for item in response["items"] if item["name"] == "CyrusOne")
        timelines = cyrus["commercial_intelligence"]["timelines"]
        assert timelines["expected_energization"] is None
        assert timelines["reported_target"] == {
            "event_type": "operational_target",
            "label": "by fourth quarter of 2026",
        }
        detail = group_metadata(session, cyrus["id"])["commercial_intelligence"]
        assert any(
            item["event_type"] == "operational_target"
            and item["label"] == "fourth quarter of 2026"
            and item["precision"] == "quarter"
            and item["qualifier"] == "deadline"
            for item in detail["timelines"]["claims"]
        )


def test_cyrusone_operational_target_does_not_bind_to_foreign_facility():
    from gridlens.domain.customer_intelligence import extract_customer_facts
    from gridlens.intelligence.customer_intelligence import scope_customer_facts

    source = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "eval/customer-commercial-v1/sources/cyrusone.json"
        ).read_text()
    )
    introduction = source["excerpts"][0].split(" The deal secures", maxsplit=1)[0]
    foreign_quote = (
        "The deal secures power, grid connection, and land to support a new state-of-the-art "
        "facility at Beta Campus that is currently under construction and expected to be "
        "operational by the fourth quarter of 2026."
    )
    text = introduction + " " + foreign_quote
    raw = extract_customer_facts(
        text,
        project_id="foreign-site-control",
        source={
            "url": source["url"],
            "evidence_id": "foreign-site-control",
            "content_hash": "a" * 64,
            "published_at": "2025-07-30",
            "observed_at": "2026-11-13T00:00:00Z",
            "authority": "unknown",
            "verification_status": "reported",
        },
    )

    scoped = scope_customer_facts(
        raw,
        "new data center adjacent to the Thad Hill Energy Center",
        "Bosque County, TX",
        source_text=text,
    )

    assert scoped["timeline_claims"] == []
