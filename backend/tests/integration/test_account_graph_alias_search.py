from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from gridlens.intelligence.contact_suppressions import company_suppression_key
from gridlens.intelligence.customer_results import groups
from gridlens.intelligence.saved_browse import current_generation, rebuild
from gridlens.persistence.models import (
    BrowseCustomerMembership,
    BrowseRow,
    BuyingChainClaim,
    BuyingChainEvidence,
    BuyingChainIdentityLink,
    BuyingChainRun,
    CompanyIdentity,
    IdentityIdentifier,
    PowerNeed,
)
from gridlens.persistence.suppression_models import ContactSuppression

pytest_plugins = ["test_saved_browse"]


def test_company_graph_alias_search_requires_current_source_link_and_privacy(saved_db):
    from test_saved_browse import seed

    need_ids = seed(saved_db, count=4, histories=1)
    assert rebuild(saved_db)["status"] == "published"
    now = datetime.now(UTC)
    with saved_db() as session:
        generation = current_generation(session)
    with saved_db.begin() as session:
        generation = session.get(type(generation), generation.id)
        rows = session.scalars(
            select(BrowseRow).where(BrowseRow.generation_id == generation.id)
        ).all()
        projects = [session.get(PowerNeed, need_id).project_id for need_id in need_ids]
        company_ids = []
        for index, (row, project_id) in enumerate(zip(rows, projects, strict=True)):
            operator_number = f"1234{index}"
            row.compact = {
                **row.compact,
                "project_metadata": {
                    **row.compact.get("project_metadata", {}),
                    "sector": "oil_gas",
                    "operator": f"Synthetic Operator {index}",
                    "oil_gas": {"operator_number": operator_number},
                },
            }
            company = CompanyIdentity(rrc_operator_number=operator_number)
            session.add(company)
            session.flush()
            company_ids.append(company.id)
            session.add(
                BrowseCustomerMembership(
                    generation_id=generation.id,
                    company_identity_id=company.id,
                    project_id=project_id,
                    organization_name=f"Synthetic Operator {index}",
                    role="asset_operator",
                )
            )
            source = BuyingChainEvidence(
                project_id=project_id,
                url=f"https://example.test/company-alias/{index}",
                title=f"Synthetic alias citation {index}",
                excerpt=f"Synthetic Operator {index} is also known as Verified Alias {index}.",
                content_hash=f"{index + 1:064x}",
                extraction_location="synthetic fixture",
                observed_at=now,
                last_seen_at=now,
                project_match_reason="synthetic current project binding",
            )
            session.add(source)
            session.flush()
            claim = BuyingChainClaim(
                project_id=project_id,
                entity_key=f"company-alias-{index}",
                fingerprint=f"{index + 1:064x}",
                policy_version="test-current-view",
                organization=f"Synthetic Operator {index}",
                person_name=None,
                title="Operator",
                category="operator",
                organization_relationship="operator",
                person_organization_relationship="unknown",
                person_project_relationship="unknown",
                evidence_strength="high",
                reason="Synthetic graph alias fixture",
                citations=[
                    {
                        "evidence_id": str(source.id),
                        "url": source.url,
                        "quote": source.excerpt,
                        "supports": "project_organization",
                    }
                ],
                public_contacts=[],
                observed_at=now,
            )
            session.add(claim)
            session.flush()
            link = BuyingChainIdentityLink(
                claim_id=claim.id,
                entity_type="company",
                company_identity_id=company.id,
                person_identity_id=None,
                reason="Synthetic current identity binding",
                source_evidence_id=source.id,
                source_version_hash=source.content_hash,
                state="current" if index != 2 else "superseded",
            )
            session.add(link)
            session.add(
                IdentityIdentifier(
                    entity_type="company",
                    company_identity_id=company.id,
                    person_identity_id=None,
                    identifier_type="alias",
                    normalized_value=f"verified alias {index}",
                    source_evidence_id=source.id,
                    source_version_hash=source.content_hash,
                    reason="Current cited synthetic alias",
                )
            )
            run_evidence_id = source.id
            if index == 1:
                newer = BuyingChainEvidence(
                    project_id=project_id,
                    url=source.url,
                    title="Synthetic replacement source version",
                    excerpt="Replacement no longer supports the alias.",
                    content_hash="f" * 64,
                    extraction_location="synthetic fixture",
                    observed_at=now + timedelta(microseconds=1),
                    last_seen_at=now,
                    project_match_reason="synthetic replacement source",
                )
                session.add(newer)
            session.add(
                BuyingChainRun(
                    project_id=project_id,
                    input_hash=f"{index + 1:064x}",
                    evidence_ids=[str(run_evidence_id)],
                    claim_ids=[str(claim.id)],
                    policy_version="test-current-view",
                    status="complete",
                    documents_checked=1,
                    candidates_added=1,
                    unresolved=[],
                    created_at=now,
                )
            )
        session.add(
            ContactSuppression(
                scope="company",
                subject_key=company_suppression_key(company_ids[3]),
                expected_version=0,
                version=1,
                action="suppress",
                reason="synthetic privacy regression",
                actor="test",
                idempotency_key="alias-search-company-suppression",
            )
        )

    with saved_db() as session:
        assert (
            groups(
                session,
                search="Verified Alias 0",
                sector="oil_gas",
                selected_generation=generation,
            )["total"]
            == 1
        )
        for index in (1, 2, 3):
            assert (
                groups(
                    session,
                    search=f"Verified Alias {index}",
                    sector="oil_gas",
                    selected_generation=generation,
                )["total"]
                == 0
            )
