"""Accepted retained project organizations traverse ingestion and buying-chain identity."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

pytest_plugins = ["test_customer_accounts"]


def test_process_records_native_organization_claim_is_linked_and_replay_is_stable(customer_db):
    from gridlens.ingestion.adapters.retained_company_projects import (
        FAMILY,
        RETRIEVAL_METHOD,
        SOURCE_ID,
        retained_records,
    )
    from gridlens.ingestion.service import process_records
    from gridlens.intelligence.buying_chain import enrich_buying_chain
    from gridlens.persistence.browse_invalidation import install
    from gridlens.persistence.models import (
        BuyingChainClaim,
        BuyingChainIdentityLink,
        Evidence,
        Job,
        Observation,
        Project,
        Source,
    )

    root = Path(__file__).resolve().parents[3]
    records, _held = retained_records(root / "eval/customer-commercial-v1")
    databank = next(
        record
        for record in records
        if "sources/databank.json" in record["retained_company_project"]["source_files"]
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
    worker = "project-org-enrichment-test"
    with customer_db.begin() as session:
        install(session.connection())
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
        result = process_records(
            session,
            job_id,
            worker,
            1,
            source_definition,
            [databank],
            allow_model=False,
        )
    assert result["retrieved_records"] == 1

    with customer_db.begin() as session:
        project = session.scalar(
            select(Project).where(
                Project.source_id == SOURCE_ID,
                Project.external_id == databank["document_number"],
            )
        )
        assert project is not None
        evidence = session.scalar(
            select(Evidence)
            .join(Observation, Observation.id == Evidence.observation_id)
            .where(
                Observation.source_id == SOURCE_ID,
                Observation.external_id == databank["document_number"],
            )
        )
        assert evidence is not None
        now = datetime.now(UTC)
        first = enrich_buying_chain(
            session,
            project.id,
            retained_only=True,
            retained_target_evidence_id=evidence.id,
            now=now,
        )
        claim = session.scalar(
            select(BuyingChainClaim).where(
                BuyingChainClaim.project_id == project.id,
                BuyingChainClaim.organization == "DataBank",
                BuyingChainClaim.category == "owner_developer",
            )
        )
        assert claim is not None
        assert any(citation["supports"] == "project_organization" for citation in claim.citations)
        link = session.scalar(
            select(BuyingChainIdentityLink).where(
                BuyingChainIdentityLink.claim_id == claim.id,
                BuyingChainIdentityLink.entity_type == "company",
                BuyingChainIdentityLink.state == "current",
            )
        )
        assert link is not None and link.basis == "project_scoped"

        second = enrich_buying_chain(
            session,
            project.id,
            retained_only=True,
            retained_target_evidence_id=evidence.id,
            now=now + timedelta(seconds=1),
        )
        current_claims = session.scalars(
            select(BuyingChainClaim).where(
                BuyingChainClaim.project_id == project.id,
                BuyingChainClaim.entity_key == claim.entity_key,
            )
        ).all()
        current_links = session.scalars(
            select(BuyingChainIdentityLink).where(
                BuyingChainIdentityLink.claim_id == claim.id,
                BuyingChainIdentityLink.entity_type == "company",
                BuyingChainIdentityLink.state == "current",
            )
        ).all()
        assert len(current_claims) == 1
        assert len(current_links) == 1
        assert first["candidates"] == second["candidates"]
