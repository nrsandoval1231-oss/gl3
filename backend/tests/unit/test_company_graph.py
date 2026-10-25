from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.company_graph import (
    RELATIONSHIP_TYPES,
    assert_company_relationship,
    company_graph,
    correct_company_relationship,
)
from gridlens.persistence.contact_models import (
    CompanyRelationshipAssertion,
    CompanyRelationshipCorrection,
)
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    BuyingChainClaim,
    BuyingChainCorrection,
    BuyingChainEvidence,
    BuyingChainIdentityLink,
    BuyingChainRun,
    CompanyIdentity,
    CompanyProjectMembership,
    Evidence,
    IdentityIdentifier,
    Interpretation,
    Observation,
    PowerNeed,
    Project,
    Source,
)
from gridlens.settings import settings


@pytest.fixture
def graph_db():
    if not settings.test_database_url:
        pytest.skip("TEST_DATABASE_URL required for company graph database checks")
    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and target.database.endswith("_test") and target != application
    schema = "company_graph_test_" + uuid4().hex
    admin = create_engine(settings.test_database_url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        settings.test_database_url, connect_args={"options": f"-csearch_path={schema}"}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    yield factory
    engine.dispose()
    with admin.begin() as connection:
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    admin.dispose()


def _seed_graph(
    session,
    *,
    with_membership=True,
    with_claim_link=True,
    legacy_public_source=False,
):
    source_id = "research-public-synthetic" if legacy_public_source else "dallas-monthly-permits"
    source = Source(
        id=source_id,
        publisher="Synthetic source",
        endpoint="https://example.test/graph",
        family="news" if legacy_public_source else "construction-permits",
        geography="Texas",
        industries=[],
        retrieval_method="publisher-rss" if legacy_public_source else "dallas-monthly-permits",
    )
    session.add(source)
    session.flush()
    project = Project(
        identity_key=f"graph-{uuid4()}",
        name="Synthetic project",
        location="Dallas, TX",
        source_id=source.id,
        external_id=f"project-{uuid4()}",
    )
    session.add(project)
    session.flush()
    session.add(
        PowerNeed(
            project_id=project.id,
            activity_key="construction",
            tier="Signal",
            rationale="Synthetic active work scope.",
            active=True,
        )
    )
    observation = Observation(
        source_id=source.id,
        external_id=f"evidence-{uuid4()}",
        title="Synthetic project operator",
        abstract="Synthetic source excerpt",
        url="https://example.test/evidence",
        content_hash="a" * 64,
    )
    session.add(observation)
    session.flush()
    evidence = Evidence(
        observation_id=observation.id,
        content_hash=observation.content_hash,
        title=observation.title,
        abstract=observation.abstract,
        url=observation.url,
        extraction_location="fixture",
    )
    session.add(evidence)
    session.flush()
    session.add(
        Interpretation(
            observation_id=observation.id,
            content_hash=observation.content_hash,
            assessment={
                "decision": "accepted",
                "evidence_hash": evidence.content_hash,
                "project_identity_key": project.identity_key,
            },
            status="accepted",
        )
    )
    session.flush()
    company = CompanyIdentity()
    related = CompanyIdentity()
    session.add_all([company, related])
    session.flush()
    if with_membership:
        membership = CompanyProjectMembership(
            company_identity_id=company.id,
            project_id=project.id,
            role="operator",
            organization_name="Synthetic Operator LLC",
            source_id=source.id,
            source_evidence_id=evidence.id,
            source_version_hash=evidence.content_hash,
            decision_basis="fixture",
            operator_number="123456",
            state="current",
            version=1,
        )
        session.add(membership)
    linked = BuyingChainEvidence(
        project_id=project.id,
        url="https://example.test/relationship",
        title="Parent relationship",
        excerpt="Synthetic Parent owns Synthetic Operator LLC.",
        content_hash="b" * 64,
        extraction_location="fixture",
        project_match_reason="explicit fixture relationship",
        observed_at=datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
    )
    session.add(linked)
    session.flush()
    claim = BuyingChainClaim(
        project_id=project.id,
        entity_key=f"operator-{uuid4()}",
        fingerprint=f"fingerprint-{uuid4()}",
        policy_version="fixture",
        organization="Synthetic Operator LLC",
        person_name=None,
        title=None,
        category="asset_operator",
        organization_relationship="DIRECT",
        person_organization_relationship="UNKNOWN",
        person_project_relationship="UNKNOWN",
        evidence_strength="High",
        reason="Synthetic source-backed operator.",
        citations=[
            {
                "evidence_id": str(linked.id),
                "quote": "Synthetic Parent owns Synthetic Operator LLC.",
                "supports": "project_organization",
                "url": linked.url,
            }
        ],
        public_contacts=[],
        observed_at=datetime.now(UTC),
    )
    session.add(claim)
    session.flush()
    session.add(
        BuyingChainRun(
            project_id=project.id,
            input_hash="c" * 64,
            evidence_ids=[str(linked.id)],
            claim_ids=[str(claim.id)],
            policy_version="fixture",
            status="complete",
            documents_checked=1,
            candidates_added=1,
            unresolved=[],
        )
    )
    session.flush()
    if with_claim_link:
        session.add(
            BuyingChainIdentityLink(
                claim_id=claim.id,
                entity_type="company",
                company_identity_id=company.id,
                person_identity_id=None,
                reason="Current synthetic company identity link.",
                basis="project_scoped",
                source_evidence_id=linked.id,
                source_version_hash=linked.content_hash,
                state="current",
            )
        )
        session.flush()
    session.add(
        IdentityIdentifier(
            entity_type="company",
            company_identity_id=company.id,
            identifier_type="alias",
            normalized_value="Synthetic Operator",
            source_evidence_id=linked.id,
            source_version_hash=linked.content_hash,
            reason="synthetic alias fixture",
        )
    )
    session.flush()
    return company, related, project, evidence, linked


def test_company_graph_reads_only_current_regional_membership_evidence(graph_db):
    with graph_db() as session:
        company, _, project, evidence, _ = _seed_graph(session)
        graph = company_graph(session, company.id)
        assert graph["company"]["display_name"] == "Synthetic Operator LLC"
        assert graph["company"]["aliases"][0]["value"] == "Synthetic Operator"
        assert graph["projects"] == [
            {
                "id": str(project.id),
                "name": project.name,
                "location": project.location,
                "roles": [
                    {
                        "role": "operator",
                        "organization_name": "Synthetic Operator LLC",
                        "state": "current",
                        "evidence": graph["projects"][0]["roles"][0]["evidence"],
                    }
                ],
            }
        ]
        assert graph["projects"][0]["roles"][0]["evidence"]["id"] == str(evidence.id)
        assert graph["relationships"] == []


def test_company_graph_excludes_legacy_research_public_evidence_without_capture_version(
    graph_db,
):
    with graph_db() as session:
        company, _, _, _, _ = _seed_graph(
            session,
            with_claim_link=False,
            legacy_public_source=True,
        )
        graph = company_graph(session, company.id)
        assert graph["projects"] == []
        assert graph["evidence"] == []


def test_company_graph_includes_claim_linked_companies_without_memberships(graph_db):
    with graph_db() as session:
        company, _, project, _, _ = _seed_graph(session, with_membership=False)
        graph = company_graph(session, company.id)
        assert graph["company"]["display_name"] == "Synthetic Operator LLC"
        assert len(graph["projects"]) == 1
        assert graph["projects"][0]["id"] == str(project.id)
        assert graph["projects"][0]["roles"] == [
            {
                "role": "operator",
                "organization_name": "Synthetic Operator LLC",
                "state": "current",
                "evidence": graph["projects"][0]["roles"][0]["evidence"],
            }
        ]
        assert graph["projects"][0]["roles"][0]["evidence"]["url"] == (
            "https://example.test/relationship"
        )


def test_claim_only_graph_obeys_existing_claim_retractions(graph_db):
    with graph_db() as session:
        company, _, project, _, _ = _seed_graph(session, with_membership=False)
        claim = session.scalar(
            select(BuyingChainClaim).where(BuyingChainClaim.project_id == project.id)
        )
        assert claim is not None
        session.add(
            BuyingChainCorrection(
                project_id=project.id,
                claim_id=claim.id,
                expected_version=claim.fingerprint,
                idempotency_key="retract-claim-for-company-graph-test",
                action="retract",
                values={},
                reason="Synthetic correction retracts this claim.",
                actor="reviewer",
            )
        )
        session.flush()
        graph = company_graph(session, company.id)
        assert graph["projects"] == []
        assert graph["company"]["display_name"] is None
        assert graph["company"]["aliases"] == []


def test_company_relationship_is_versioned_and_reversible(graph_db):
    assert RELATIONSHIP_TYPES == {
        "parent",
        "subsidiary",
        "developer",
        "operator",
        "epc",
        "gc",
        "utility",
    }
    with graph_db() as session:
        company, related, _, _, source = _seed_graph(session)
        session.add(
            IdentityIdentifier(
                entity_type="company",
                company_identity_id=related.id,
                identifier_type="legal_name",
                normalized_value="Synthetic Parent",
                source_evidence_id=source.id,
                source_version_hash=source.content_hash,
                reason="Current source-bound parent name.",
            )
        )
        session.flush()
        assertion = assert_company_relationship(
            session,
            source_company_id=company.id,
            target_company_id=related.id,
            relationship_type="parent",
            source_evidence_id=source.id,
            source_version_hash=source.content_hash,
            reason="Source explicitly identifies parent company.",
            actor="reviewer",
            idempotency_key="graph-parent-assertion",
        )
        assert isinstance(assertion, CompanyRelationshipAssertion)
        corrected = correct_company_relationship(
            session,
            assertion.id,
            expected_version=1,
            action="suppress",
            reason="Relationship needs review.",
            actor="reviewer",
            idempotency_key="graph-parent-suppress",
        )
        assert isinstance(corrected, CompanyRelationshipCorrection)
        suppressed = company_graph(session, company.id)["relationships"][0]
        assert suppressed["status"] == "suppressed"
        assert suppressed["version"] == 2
        assert suppressed["support_status"] == "operator_assertion_unverified"
        assert suppressed["source_quote"] == source.excerpt
        correct_company_relationship(
            session,
            assertion.id,
            expected_version=2,
            action="reinstate",
            reason="Review confirmed the source.",
            actor="reviewer",
            idempotency_key="graph-parent-reinstate",
        )
        reinstated = company_graph(session, company.id)["relationships"][0]
        assert reinstated["status"] == "current"
        assert reinstated["version"] == 3

        retracted = correct_company_relationship(
            session,
            assertion.id,
            expected_version=3,
            action="retract",
            reason="The relationship was withdrawn.",
            actor="reviewer",
            idempotency_key="graph-parent-retract",
        )
        assert retracted.version == 4
        retracted_view = company_graph(session, company.id)["relationships"][0]
        assert retracted_view["status"] == "retracted"
        assert retracted_view["version"] == 4

        with pytest.raises(RuntimeError, match="correction version is stale"):
            correct_company_relationship(
                session,
                assertion.id,
                expected_version=3,
                action="reinstate",
                reason="Stale retraction version.",
                actor="reviewer",
                idempotency_key="graph-parent-stale-reinstate",
            )

        reinstated_after_retract = correct_company_relationship(
            session,
            assertion.id,
            expected_version=4,
            action="reinstate",
            reason="The source-backed relationship is restored.",
            actor="reviewer",
            idempotency_key="graph-parent-reinstate-after-retract",
        )
        replayed_reinstate = correct_company_relationship(
            session,
            assertion.id,
            expected_version=4,
            action="reinstate",
            reason="The source-backed relationship is restored.",
            actor="reviewer",
            idempotency_key="graph-parent-reinstate-after-retract",
        )
        assert replayed_reinstate.id == reinstated_after_retract.id
        current = company_graph(session, company.id)["relationships"][0]
        assert current["status"] == "current"
        assert current["version"] == 5


def test_relationship_assertion_rejects_unbound_companies_or_missing_terms(graph_db):
    with graph_db() as session:
        company, related, _, _, source = _seed_graph(session)
        common = {
            "source_company_id": company.id,
            "target_company_id": related.id,
            "source_evidence_id": source.id,
            "source_version_hash": source.content_hash,
            "reason": "Manually attribute a relationship for validation.",
            "actor": "reviewer",
        }
        with pytest.raises(ValueError, match="Both companies must have current source-bound names"):
            assert_company_relationship(
                session,
                relationship_type="parent",
                idempotency_key="unbound-target-relationship",
                **common,
            )

        session.add(
            IdentityIdentifier(
                entity_type="company",
                company_identity_id=related.id,
                identifier_type="alias",
                normalized_value="Unrelated Organization",
                source_evidence_id=source.id,
                source_version_hash=source.content_hash,
                reason="Deliberately nonmatching identifier.",
            )
        )
        session.flush()
        with pytest.raises(ValueError, match="Both companies must have current source-bound names"):
            assert_company_relationship(
                session,
                relationship_type="parent",
                idempotency_key="unrelated-target-relationship",
                **common,
            )

        session.add(
            IdentityIdentifier(
                entity_type="company",
                company_identity_id=related.id,
                identifier_type="legal_name",
                normalized_value="Synthetic Parent",
                source_evidence_id=source.id,
                source_version_hash=source.content_hash,
                reason="Source-bound parent name.",
            )
        )
        session.flush()
        with pytest.raises(ValueError, match="Both companies must have current source-bound names"):
            assert_company_relationship(
                session,
                relationship_type="utility",
                idempotency_key="missing-utility-term-relationship",
                **common,
            )
