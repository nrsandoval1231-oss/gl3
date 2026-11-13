from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from db_reset import reset_test_database
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
from gridlens.intelligence.buying_chain import document_content_hash
from gridlens.intelligence.company_contact_attribution import (
    document_matches_company_identity,
    supported_contact_facts,
)
from gridlens.intelligence.identity_reconciliation import ensure_project_scoped_identity_links
from gridlens.intelligence.regulatory_company_identity import (
    SEC_DOMAIN_IDENTIFIER,
    bind_sec_domain_proofs_to_current_claims,
)
from gridlens.persistence.models import (
    BuyingChainClaim,
    BuyingChainEvidence,
    BuyingChainIdentityLink,
    BuyingChainRun,
    CompanyIdentity,
    IdentityIdentifier,
    Observation,
    Project,
    Source,
)
from gridlens.persistence.suppression_models import ContactSuppression
from gridlens.settings import settings

NOW = datetime(2026, 11, 13, 12, tzinfo=UTC)
ISSUER = "Example Compute, Inc."
EIN = "12-3456789"
SEC_URL = "https://www.sec.gov/Archives/edgar/data/123456/000012345624000001/example-2024.htm"
SITE_URL = "https://www.examplecompute.com/campus/east"
SEC_TEXT = """Commission File Number 001-00001

EXAMPLE COMPUTE, INC.
(Exact name of registrant as specified in its charter)
| Nevada | 12-3456789 |
| (STATE OF INCORPORATION) | (I.R.S. Employer Identification No.) |
Our Internet address is www.examplecompute.com.
"""


@pytest.fixture
def db():
    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database.endswith("_test") or target.database == "contact_p0_c28_tests"
    assert target != application
    engine = create_engine(settings.test_database_url)
    reset_test_database(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(
            Source(
                id="domain-proof-test",
                publisher="Synthetic test",
                endpoint=SITE_URL,
                family="construction",
                geography="US",
                industries=[],
                retrieval_method="fixture",
                health={},
            )
        )
    yield factory
    engine.dispose()


def setup_current_claim(
    session,
    *,
    site_url=SITE_URL,
    organization="Example Compute Incorporated",
    sec_text=SEC_TEXT,
):
    source_row = session.get(Source, "domain-proof-test")
    observation = Observation(
        source_id=source_row.id,
        external_id="synthetic-east-campus",
        title="Synthetic East Campus",
        url=site_url,
        abstract=f"{organization} is the developer of Synthetic East Campus in Austin, Texas.",
        published_at=date(2026, 11, 1),
        content_hash="observation-hash",
    )
    session.add(observation)
    session.flush()
    project = Project(
        source_id=source_row.id,
        external_id=observation.external_id,
        name="Synthetic East Campus",
        location="Austin, TX",
        identity_key=f"synthetic-{uuid4()}",
        identity_facts={},
    )
    session.add(project)
    session.flush()
    project_source = BuyingChainEvidence(
        project_id=project.id,
        url=site_url,
        title="Synthetic project page",
        excerpt=observation.abstract,
        content_hash="project-source-hash",
        extraction_location="public page text",
        published_at=observation.published_at,
        observed_at=NOW,
        last_seen_at=NOW,
        project_match_reason="Exact named project fixture.",
    )
    sec_doc = PublicDocument(
        SEC_URL,
        "Example Compute 2024 Form 10-K",
        sec_text,
        date(2026, 10, 1),
        NOW,
        extraction_location="SEC filing text",
    )
    sec_source = BuyingChainEvidence(
        project_id=project.id,
        url=sec_doc.url,
        title=sec_doc.title,
        excerpt=sec_doc.text,
        content_hash=document_content_hash(sec_doc),
        extraction_location=sec_doc.extraction_location,
        published_at=sec_doc.published_at,
        observed_at=sec_doc.observed_at,
        last_seen_at=NOW,
        project_match_reason="SEC issuer identity evidence; no project relationship inferred.",
    )
    session.add_all([project_source, sec_source])
    session.flush()
    claim = BuyingChainClaim(
        project_id=project.id,
        entity_key="synthetic-example-compute",
        fingerprint=f"{uuid4().hex}{uuid4().hex}",
        policy_version="test",
        organization=organization,
        person_name=None,
        title=None,
        category="owner",
        organization_relationship="DIRECT",
        person_organization_relationship="UNKNOWN",
        person_project_relationship="UNKNOWN",
        evidence_strength="High",
        reason="Synthetic exact project relationship.",
        citations=[
            {
                "evidence_id": str(project_source.id),
                "url": project_source.url,
                "quote": project_source.excerpt,
                "supports": "project_organization",
            }
        ],
        public_contacts=[],
        observed_at=NOW,
        verified_at=NOW,
    )
    session.add(claim)
    session.flush()
    session.add(
        BuyingChainRun(
            project_id=project.id,
            input_hash=f"{uuid4().hex}{uuid4().hex}",
            policy_version="test",
            evidence_ids=[str(project_source.id), str(sec_source.id)],
            claim_ids=[str(claim.id)],
            status="complete",
            documents_checked=2,
            candidates_added=1,
            unresolved=[],
            created_at=NOW,
        )
    )
    session.flush()
    return project, claim, project_source, sec_source


def test_sec_domain_links_only_current_project_claim_using_original_project_source(db):
    with db.begin() as session:
        project, claim, project_source, sec_source = setup_current_claim(session)
        assert (
            bind_sec_domain_proofs_to_current_claims(
                session,
                project_id=project.id,
                claim_ids=[str(claim.id)],
                sec_evidence_ids=[sec_source.id],
                now=NOW,
            )
            == 1
        )
        identity = session.scalar(select(CompanyIdentity))
        assert identity is not None
        identifiers = session.scalars(
            select(IdentityIdentifier).where(IdentityIdentifier.company_identity_id == identity.id)
        ).all()
        assert {(row.identifier_type, row.normalized_value) for row in identifiers} == {
            ("ein", "123456789"),
            (SEC_DOMAIN_IDENTIFIER, "examplecompute.com"),
        }
        assert all(row.source_evidence_id == sec_source.id for row in identifiers)
        assert all(row.source_version_hash == sec_source.content_hash for row in identifiers)
        link = session.scalar(
            select(BuyingChainIdentityLink).where(
                BuyingChainIdentityLink.claim_id == claim.id,
                BuyingChainIdentityLink.state == "current",
            )
        )
        assert link is not None
        assert link.basis == "strong_identifier"
        assert link.company_identity_id == identity.id
        assert link.source_evidence_id == project_source.id
        assert link.source_version_hash == project_source.content_hash

        ensure_project_scoped_identity_links(session, [str(claim.id)])
        links = session.scalars(
            select(BuyingChainIdentityLink).where(
                BuyingChainIdentityLink.claim_id == claim.id,
                BuyingChainIdentityLink.state == "current",
            )
        ).all()
        assert len(links) == 1
        assert links[0].basis == "strong_identifier"


def test_sec_proof_validates_official_site_and_reextracts_only_supported_roster_facts(
    db, monkeypatch
):
    from gridlens.domain import evaluation_clock

    monkeypatch.setattr(evaluation_clock, "evaluation_now", lambda _now=None: NOW)
    with db.begin() as session:
        project, claim, _, sec_source = setup_current_claim(session)
        assert (
            bind_sec_domain_proofs_to_current_claims(
                session,
                project_id=project.id,
                claim_ids=[str(claim.id)],
                sec_evidence_ids=[sec_source.id],
                now=NOW,
            )
            == 1
        )
        identity = session.scalar(select(CompanyIdentity))
        assert identity is not None
        official = PublicDocument(
            "https://www.examplecompute.com/about/leadership",
            "Example Compute leadership",
            "Avery Example\nProject Director",
            date(2026, 11, 1),
            NOW,
            extraction_location="public page text",
        )
        page_source = BuyingChainEvidence(
            project_id=project.id,
            url=official.url,
            title=official.title,
            excerpt=official.text,
            content_hash=document_content_hash(official),
            extraction_location=official.extraction_location,
            published_at=official.published_at,
            observed_at=official.observed_at,
            last_seen_at=NOW,
            project_match_reason="Organization-role source only.",
        )
        session.add(page_source)
        session.flush()
        from gridlens.intelligence.company_contact_attribution import _source_hash_is_current

        assert _source_hash_is_current(page_source)

        assert document_matches_company_identity(
            session,
            official,
            company_id=identity.id,
            organization="Example Compute Incorporated",
            now=NOW,
        )
        assert document_matches_company_identity(
            session,
            page_source,
            company_id=identity.id,
            organization="Example Compute Incorporated",
            now=NOW,
        )
        assert document_matches_company_identity(
            session,
            PublicDocument(
                "https://careers.examplecompute.com/team",
                official.title,
                official.text,
                official.published_at,
                official.observed_at,
            ),
            company_id=identity.id,
            organization="Example Compute Incorporated",
            now=NOW,
        )
        assert not document_matches_company_identity(
            session,
            PublicDocument(
                "https://examplecompute.com.attacker.example/team",
                official.title,
                official.text,
                official.published_at,
                official.observed_at,
            ),
            company_id=identity.id,
            organization="Example Compute Incorporated",
            now=NOW,
        )
        candidate = {
            "company_identity_id": str(identity.id),
            "organization": "Example Compute Incorporated",
            "person_name": "Avery Example",
            "title": "Project Director",
            "category": "owner_construction",
            "organization_relationship": "DIRECT",
            "person_organization_relationship": "CURRENT",
            "person_project_relationship": "ROLE_SUPPORTED",
        }
        facts = supported_contact_facts(
            session,
            page_source,
            organization="Example Compute Incorporated",
            identity=identity,
            project=project,
            retained_context=None,
            candidate=candidate,
        )
        role = next(fact for fact in facts if fact.support == "organization_person_role")
        assert role.quote == "Avery Example\nProject Director"
        assert role.person_name == candidate["person_name"]
        assert role.title == candidate["title"]
        assert role.person_project_relationship == "ROLE_SUPPORTED"
        assert role.person_project_relationship != "DIRECT"

        replacement_doc = PublicDocument(
            SEC_URL,
            "Updated filing",
            SEC_TEXT.replace("examplecompute.com", "new-examplecompute.com"),
            date(2026, 11, 2),
            NOW,
            extraction_location="SEC filing text",
        )
        session.add(
            BuyingChainEvidence(
                project_id=project.id,
                url=SEC_URL,
                title=replacement_doc.title,
                excerpt=replacement_doc.text,
                content_hash=document_content_hash(replacement_doc),
                extraction_location=replacement_doc.extraction_location,
                published_at=replacement_doc.published_at,
                observed_at=replacement_doc.observed_at,
                last_seen_at=NOW.replace(minute=1),
                project_match_reason="Updated SEC filing fixture.",
            )
        )
        session.flush()
        assert not document_matches_company_identity(
            session,
            official,
            company_id=identity.id,
            organization="Example Compute Incorporated",
            now=NOW,
        )


def test_identical_sec_recheck_refreshes_last_seen_but_unvisited_proof_expires(db):
    with db.begin() as session:
        project, claim, _, sec_source = setup_current_claim(session)
        assert (
            bind_sec_domain_proofs_to_current_claims(
                session,
                project_id=project.id,
                claim_ids=[str(claim.id)],
                sec_evidence_ids=[sec_source.id],
                now=NOW,
            )
            == 1
        )
        identity = session.scalar(select(CompanyIdentity))
        assert identity is not None
        official = PublicDocument(
            "https://www.examplecompute.com/campus",
            "Current project page",
            "fixture",
            date(2026, 11, 1),
            NOW,
        )
        later = NOW + timedelta(days=31)
        assert not document_matches_company_identity(
            session,
            official,
            company_id=identity.id,
            organization="Example Compute Incorporated",
            now=later,
        )
        # Rechecking identical bytes refreshes only last_seen_at; the original
        # observed_at and immutable content hash remain intact.
        sec_source.last_seen_at = later
        session.flush()
        assert document_matches_company_identity(
            session,
            official,
            company_id=identity.id,
            organization="Example Compute Incorporated",
            now=later,
        )
        assert sec_source.observed_at == NOW


def test_method_suppression_blocks_automatic_company_identity_rekey(db):
    with db.begin() as session:
        project, claim, _, sec_source = setup_current_claim(session)
        session.add(
            ContactSuppression(
                scope="method",
                subject_key="b" * 64,
                expected_version=0,
                version=1,
                action="suppress",
                reason="Synthetic method suppression control.",
                actor="test",
                idempotency_key="method-control-test",
            )
        )
        session.flush()
        assert (
            bind_sec_domain_proofs_to_current_claims(
                session,
                project_id=project.id,
                claim_ids=[str(claim.id)],
                sec_evidence_ids=[sec_source.id],
                now=NOW,
            )
            == 0
        )
        assert session.scalar(select(IdentityIdentifier)) is None
        assert session.scalar(select(CompanyIdentity)) is None


def test_conflicting_current_sec_eins_do_not_choose_an_arbitrary_issuer_identity(db):
    with db.begin() as session:
        project, claim, _, first_source = setup_current_claim(session)
        other_url = SEC_URL.replace("example-2024.htm", "example-amended-2024.htm")
        other_document = PublicDocument(
            other_url,
            "Example Compute amended Form 10-K",
            SEC_TEXT.replace("12-3456789", "98-7654321"),
            date(2026, 10, 2),
            NOW,
            extraction_location="SEC filing text",
        )
        other_source = BuyingChainEvidence(
            project_id=project.id,
            url=other_document.url,
            title=other_document.title,
            excerpt=other_document.text,
            content_hash=document_content_hash(other_document),
            extraction_location=other_document.extraction_location,
            published_at=other_document.published_at,
            observed_at=other_document.observed_at,
            last_seen_at=NOW,
            project_match_reason="Second SEC filing identity proof fixture.",
        )
        session.add(other_source)
        session.flush()
        assert (
            bind_sec_domain_proofs_to_current_claims(
                session,
                project_id=project.id,
                claim_ids=[str(claim.id)],
                sec_evidence_ids=[first_source.id, other_source.id],
                now=NOW,
            )
            == 0
        )
        assert session.scalar(select(IdentityIdentifier)) is None
        assert session.scalar(select(CompanyIdentity)) is None


@pytest.mark.parametrize(
    ("site_url", "organization", "sec_text"),
    [
        ("https://unrelated.example/project", "Example Compute Incorporated", SEC_TEXT),
        (SITE_URL, "Example Compute Incorporated Customer", SEC_TEXT),
        (SITE_URL, "Example Compute LLC", SEC_TEXT),
        (
            SITE_URL,
            "Example Compute Incorporated",
            SEC_TEXT + "IRS NUMBER: 98-7654321\n",
        ),
        (
            SITE_URL,
            "Example Compute Incorporated",
            SEC_TEXT.replace(
                "Our Internet address is www.examplecompute.com.",
                "Our Internet address is www.other.example.",
            ),
        ),
    ],
)
def test_foreign_host_name_ein_or_domain_does_not_link_claim(db, site_url, organization, sec_text):
    with db.begin() as session:
        project, claim, _, sec_source = setup_current_claim(
            session, site_url=site_url, organization=organization, sec_text=sec_text
        )
        assert (
            bind_sec_domain_proofs_to_current_claims(
                session,
                project_id=project.id,
                claim_ids=[str(claim.id)],
                sec_evidence_ids=[sec_source.id],
                now=NOW,
            )
            == 0
        )
        assert session.scalar(select(IdentityIdentifier)) is None
        assert session.scalar(select(CompanyIdentity)) is None
