"""Switch's planned role uses the current project-scoped BuyingChain path."""

import hashlib
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

pytest_plugins = ["test_customer_accounts"]


def _adverse_revision(record):
    revised = deepcopy(record)
    revised["abstract"] += " The Fifth Prime campus has been canceled."
    revised["source_body_hash"] = hashlib.sha256(revised["abstract"].encode()).hexdigest()
    context = revised["retained_company_project"]
    context["body_hash"] = revised["source_body_hash"]
    context["section_ranges"][-1]["end"] = len(revised["abstract"])
    for section in context["section_ranges"]:
        section_text = revised["abstract"][section["start"] : section["end"]]
        section["sha256"] = hashlib.sha256(section_text.encode()).hexdigest()
    from gridlens.ingestion.adapters.retained_company_projects import retained_record_hash

    revised["source_hash"] = retained_record_hash(revised)
    context["content_hash"] = revised["source_hash"]
    return revised


def test_switch_planned_developer_gets_project_card_and_adverse_revision_retires_it(
    customer_db,
):
    from gridlens.ingestion.adapters.retained_company_projects import (
        FAMILY,
        RETRIEVAL_METHOD,
        SOURCE_ID,
        retained_records,
    )
    from gridlens.ingestion.service import process_records
    from gridlens.intelligence.buying_chain import enrich_buying_chain
    from gridlens.intelligence.customer_results import group_projects, groups
    from gridlens.intelligence.saved_browse import current_generation, rebuild
    from gridlens.persistence.browse_invalidation import install
    from gridlens.persistence.models import (
        BrowseCustomerMembership,
        BuyingChainClaim,
        BuyingChainIdentityLink,
        Evidence,
        Interpretation,
        Job,
        Observation,
        PowerNeed,
        Project,
        Source,
    )

    root = Path(__file__).resolve().parents[3]
    records, _held = retained_records(root / "eval/customer-commercial-v1")
    switch_record = next(
        record
        for record in records
        if "sources/switch.json" in record["retained_company_project"]["source_files"]
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
    worker = "retained-switch-role-test"
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
        first_ingestion = process_records(
            session,
            job_id,
            worker,
            1,
            source_definition,
            [switch_record],
            allow_model=False,
        )
    assert first_ingestion["retrieved_records"] == 1

    with customer_db.begin() as session:
        project = session.scalar(
            select(Project).where(
                Project.source_id == SOURCE_ID,
                Project.external_id == switch_record["document_number"],
            )
        )
        assert project is not None
        evidence = session.scalar(
            select(Evidence)
            .join(Observation, Observation.id == Evidence.observation_id)
            .where(
                Observation.source_id == SOURCE_ID,
                Observation.external_id == switch_record["document_number"],
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
                BuyingChainClaim.organization == "Switch",
                BuyingChainClaim.category == "owner_developer",
            )
        )
        assert claim is not None
        assert any(
            "will allow Switch to construct" in citation["quote"] for citation in claim.citations
        )
        assert not any("Dell" == candidate.get("organization") for candidate in first["candidates"])
        link = session.scalar(
            select(BuyingChainIdentityLink).where(
                BuyingChainIdentityLink.claim_id == claim.id,
                BuyingChainIdentityLink.entity_type == "company",
                BuyingChainIdentityLink.state == "current",
            )
        )
        assert link is not None and link.basis == "project_scoped"

        replay = enrich_buying_chain(
            session,
            project.id,
            retained_only=True,
            retained_target_evidence_id=evidence.id,
            now=now + timedelta(seconds=1),
        )
        current_candidates = [
            candidate
            for candidate in replay["candidates"]
            if candidate.get("organization") == "Switch"
            and candidate.get("category") == "owner_developer"
        ]
        assert len(current_candidates) == 1
        assert current_candidates[0]["id"] == claim.id
        assert current_candidates[0]["company_identity_id"] == str(link.company_identity_id)
        assert first["candidates"] == replay["candidates"]

    positive_generation = rebuild(customer_db)
    assert positive_generation["status"] == "published"
    with customer_db.begin() as session:
        generation = current_generation(session)
        canonical_groups = groups(
            session,
            sector="data_centers",
            limit=100,
            selected_generation=generation,
            canonical_only=True,
        )
        switch_group = next(
            (item for item in canonical_groups["items"] if item["name"] == "Switch"),
            None,
        )
        assert switch_group is not None, canonical_groups
        assert switch_group["group_kind"] == "resolved_identity"
        customer_membership = session.scalar(
            select(BrowseCustomerMembership).where(
                BrowseCustomerMembership.generation_id == generation.id,
                BrowseCustomerMembership.project_id == project.id,
                BrowseCustomerMembership.company_identity_id == link.company_identity_id,
            )
        )
        assert customer_membership is not None
        assert customer_membership.role == "owner_developer"
        assert customer_membership.organization_name == "Switch"
        project_cards = group_projects(
            session,
            switch_group["id"],
            sector="data_centers",
            canonical_only=True,
            parent_token=canonical_groups["cohort_token"],
        )
        assert any(item["project_id"] == str(project.id) for item in project_cards["items"])
        switch_needs = session.scalars(
            select(PowerNeed).where(PowerNeed.project_id == project.id)
        ).all()
        assert switch_needs
        assert all(need.required_mw is None for need in switch_needs)

    adverse = _adverse_revision(switch_record)
    with customer_db() as session:
        revised_ingestion = process_records(
            session,
            job_id,
            worker,
            1,
            source_definition,
            [adverse],
            allow_model=False,
        )
    assert revised_ingestion["changed"] == 1

    with customer_db.begin() as session:
        project = session.scalar(
            select(Project).where(
                Project.source_id == SOURCE_ID,
                Project.external_id == switch_record["document_number"],
            )
        )
        observation = session.scalar(
            select(Observation).where(
                Observation.source_id == SOURCE_ID,
                Observation.external_id == switch_record["document_number"],
            )
        )
        assert project is not None and observation is not None
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == observation.id)
        )
        assert interpretation is not None and interpretation.status == "rejected"
        retired = enrich_buying_chain(
            session,
            project.id,
            retained_only=True,
            now=now + timedelta(seconds=2),
        )
        assert not any(
            candidate.get("organization") == "Switch"
            and candidate.get("category") == "owner_developer"
            for candidate in retired["candidates"]
        )
        link = session.scalar(
            select(BuyingChainIdentityLink).where(
                BuyingChainIdentityLink.claim_id == claim.id,
                BuyingChainIdentityLink.entity_type == "company",
            )
        )
        assert link is not None and link.basis == "project_scoped"
        assert link.source_version_hash != adverse["source_hash"]

    withdrawn_generation = rebuild(customer_db)
    assert withdrawn_generation["status"] == "published"
    with customer_db.begin() as session:
        generation = current_generation(session)
        canonical_groups = groups(
            session,
            sector="data_centers",
            limit=100,
            selected_generation=generation,
            canonical_only=True,
        )
        assert not any(item["name"] == "Switch" for item in canonical_groups["items"])
