"""PostgreSQL privacy regressions for retained permit summary facts."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.buying_chain import _apply_permit_summary_privacy
from gridlens.intelligence.contact_suppressions import (
    global_method_suppression_key,
    global_person_suppression_key,
    method_suppression_key,
    record_contact_suppression,
)
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    BuyingChainClaim,
    BuyingChainEvidence,
    BuyingChainIdentityLink,
    CompanyIdentity,
    Evidence,
    Observation,
    PersonIdentity,
    Project,
    Source,
)
from gridlens.settings import settings


@pytest.fixture
def permit_privacy_db():
    if not settings.test_database_url:
        pytest.skip("TEST_DATABASE_URL required for permit-summary privacy integration")
    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and target.database.endswith("_test")
    assert "corpus" not in target.database.casefold()
    assert (target.host, target.port, target.database) != (
        application.host,
        application.port,
        application.database,
    ), "TEST_DATABASE_URL must differ from the application database"

    schema = "permit_privacy_" + uuid4().hex
    admin = create_engine(settings.test_database_url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        settings.test_database_url,
        connect_args={"options": f"-csearch_path={schema}"},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def _seed_retained_source(session, source_id: str, slug: str):
    now = datetime.now(UTC)
    source = Source(
        id=source_id,
        publisher="Synthetic permit fixture",
        endpoint="https://example.test/permits",
        family="construction-permits",
        geography="Test",
        industries=[],
        retrieval_method="fixture",
        health={},
    )
    session.add(source)
    session.flush()
    project = Project(
        identity_key=f"permit-privacy-{slug}-{uuid4()}",
        name=f"Synthetic {slug} project",
        location="100 Test Way, Austin, TX",
        source_id=source_id,
        external_id=slug,
    )
    session.add(project)
    session.flush()
    excerpt = (
        "Owner: Northstar Grid LLC. Owner contact: owner@northstar.example. "
        "Contractor: Trusted Build Co. Contractor contact: bids@trustedbuild.example. "
        "Owner: Jordan Public. Owner contact: jordan@public.example. "
        "Electrical service: 1500 amps."
    )
    observation = Observation(
        source_id=source_id,
        external_id=f"{slug}-permit-1",
        title=f"Synthetic {slug} permit",
        abstract=excerpt,
        url=f"https://example.test/permits/{slug}",
        content_hash=f"observation-{slug}",
    )
    session.add(observation)
    session.flush()
    retained = Evidence(
        observation_id=observation.id,
        content_hash=f"evidence-{slug}",
        title=observation.title,
        abstract=excerpt,
        url=observation.url,
        observed_at=now,
        extraction_location="Synthetic permit row",
    )
    session.add(retained)
    session.flush()
    raw = BuyingChainEvidence(
        project_id=project.id,
        retained_evidence_id=retained.id,
        url=observation.url,
        title=observation.title,
        excerpt=excerpt,
        content_hash=f"raw-{slug}",
        extraction_location="Synthetic permit row",
        observed_at=now,
        last_seen_at=now,
        project_match_reason="Exact synthetic project fixture",
    )
    session.add(raw)
    session.flush()
    return project, retained, raw, excerpt


def _claim(
    session,
    *,
    project_id,
    source_id,
    organization: str,
    quote: str,
    company_id=None,
    person_id=None,
    index: int,
):
    now = datetime.now(UTC)
    claim = BuyingChainClaim(
        project_id=project_id,
        entity_key=f"permit-privacy-{index}",
        fingerprint=f"{index:064x}",
        policy_version="fixture-v1",
        organization=organization,
        person_name=None,
        title="Project organization",
        category="owner" if index == 1 else "contractor",
        organization_relationship="owner" if index == 1 else "contractor",
        person_organization_relationship="unknown",
        person_project_relationship="unknown",
        evidence_strength="high",
        reason="Synthetic historical source claim.",
        citations=[
            {
                "evidence_id": str(source_id),
                "quote": quote,
                "supports": "project_organization",
            }
        ],
        # These historical claims intentionally contain no copied contacts.
        public_contacts=[],
        observed_at=now,
    )
    session.add(claim)
    session.flush()
    if company_id is not None or person_id is not None:
        session.add(
            BuyingChainIdentityLink(
                claim_id=claim.id,
                entity_type="company" if company_id is not None else "person",
                company_identity_id=company_id,
                person_identity_id=person_id,
                reason="Synthetic historical identity link",
                basis="strong_identifier",
                source_evidence_id=source_id,
                source_version_hash="e" * 64,
                state="superseded",
                superseded_at=now,
            )
        )
    return claim


def _summary(evidence_id, owner="Northstar Grid LLC", contractor="Trusted Build Co"):
    return {
        "evidence_id": str(evidence_id),
        "source_id": "synthetic-permit-source",
        "title": "Synthetic retained permit summary",
        "url": "https://example.test/permits/summary",
        "facts": [
            {
                "label": "Owner",
                "value": owner,
                "quote": f"Owner: {owner}.",
            },
            {
                "label": "Owner email",
                "value": "owner@northstar.example",
                "quote": "Owner contact: owner@northstar.example.",
            },
            {
                "label": "Contractor",
                "value": contractor,
                "quote": f"Contractor: {contractor}.",
            },
            {
                "label": "Contractor email",
                "value": "bids@trustedbuild.example",
                "quote": "Contractor contact: bids@trustedbuild.example.",
            },
            {
                "label": "Electrical service",
                "value": "1500 amps",
                "quote": "Electrical service: 1500 amps.",
            },
        ],
    }


def test_shared_retained_permit_source_redacts_only_suppressed_owner_contact(permit_privacy_db):
    with permit_privacy_db.begin() as session:
        project, retained, raw, excerpt = _seed_retained_source(
            session, "synthetic-permit-source", "shared-claims"
        )
        owner_company, contractor_company = CompanyIdentity(), CompanyIdentity()
        session.add_all([owner_company, contractor_company])
        session.flush()
        owner_claim = _claim(
            session,
            project_id=project.id,
            source_id=raw.id,
            organization="Northstar Grid LLC",
            quote="Owner: Northstar Grid LLC.",
            company_id=owner_company.id,
            index=1,
        )
        contractor_claim = _claim(
            session,
            project_id=project.id,
            source_id=raw.id,
            organization="Trusted Build Co",
            quote="Contractor: Trusted Build Co.",
            company_id=contractor_company.id,
            index=2,
        )
        assert (
            owner_claim.citations[0]["evidence_id"] == contractor_claim.citations[0]["evidence_id"]
        )
        assert owner_claim.public_contacts == contractor_claim.public_contacts == []
        assert raw.retained_evidence_id == retained.id
        record_contact_suppression(
            session,
            scope="method",
            subject_key=method_suppression_key(
                owner_company.id, None, "email", "owner@northstar.example"
            ),
            action="suppress",
            expected_version=0,
            reason="Synthetic owner contact privacy request",
            actor="integration-test",
            idempotency_key="permit-summary-owner-email",
        )
        owner_summary = _summary(retained.id)
        view = {
            "project_id": str(project.id),
            "candidates": [],
            "permit_summaries": [owner_summary],
        }

        _apply_permit_summary_privacy(session, view)

        result = str(view["permit_summaries"])
        assert "owner@northstar.example" not in result
        assert "bids@trustedbuild.example" in result
        assert "Northstar Grid LLC" in result
        assert "Trusted Build Co" in result
        assert "1500 amps" in result
        assert session.get(BuyingChainEvidence, raw.id).excerpt == excerpt
        assert session.get(Evidence, retained.id).abstract == excerpt


def test_global_email_and_person_suppression_apply_without_visible_candidates_or_company_link(
    permit_privacy_db,
):
    with permit_privacy_db.begin() as session:
        project, retained, raw, excerpt = _seed_retained_source(
            session, "synthetic-permit-person-source", "person-only"
        )
        person = PersonIdentity()
        session.add(person)
        session.flush()
        claim = _claim(
            session,
            project_id=project.id,
            source_id=raw.id,
            organization="Unknown Organization",
            quote="Owner: Jordan Public.",
            person_id=person.id,
            index=3,
        )
        claim.person_name = "Jordan Public"
        assert claim.public_contacts == []
        record_contact_suppression(
            session,
            scope="person",
            subject_key=global_person_suppression_key(person.id),
            action="suppress",
            expected_version=0,
            reason="Synthetic whole-person privacy request",
            actor="integration-test",
            idempotency_key="permit-summary-person",
        )
        record_contact_suppression(
            session,
            scope="method",
            subject_key=global_method_suppression_key("email", "jordan@public.example"),
            action="suppress",
            expected_version=0,
            reason="Synthetic global email privacy request",
            actor="integration-test",
            idempotency_key="permit-summary-global-email",
        )
        summary = {
            "evidence_id": str(retained.id),
            "source_id": "synthetic-permit-person-source",
            "facts": [
                {"label": "Owner", "value": "Jordan Public", "quote": "Owner: Jordan Public."},
                {
                    "label": "Owner email",
                    "value": "jordan@public.example",
                    "quote": "Owner contact: jordan@public.example.",
                },
                {
                    "label": "Electrical service",
                    "value": "1500 amps",
                    "quote": "Electrical service: 1500 amps.",
                },
            ],
        }
        view = {"project_id": str(project.id), "candidates": [], "permit_summaries": [summary]}

        _apply_permit_summary_privacy(session, view)

        result = str(view["permit_summaries"])
        assert "Jordan Public" not in result
        assert "jordan@public.example" not in result
        assert "1500 amps" in result
        link = session.query(BuyingChainIdentityLink).filter_by(claim_id=claim.id).one()
        assert link.company_identity_id is None
        assert link.person_identity_id == person.id
        assert session.get(BuyingChainEvidence, raw.id).excerpt == excerpt
