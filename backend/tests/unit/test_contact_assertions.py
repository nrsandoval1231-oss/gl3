from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

import gridlens.intelligence.contact_assertions as contact_assertions
from gridlens.intelligence.company_contacts import company_contacts
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    BuyingChainClaim,
    BuyingChainCorrection,
    BuyingChainEvidence,
    BuyingChainIdentityLink,
    BuyingChainRun,
    CompanyIdentity,
    Evidence,
    ExternalImportActivation,
    ExternalImportBatch,
    ExternalImportRow,
    Interpretation,
    Observation,
    PowerNeed,
    Project,
    Source,
)
from gridlens.settings import settings


def _seed_published_contact(session):
    source = Source(
        id="synthetic-contact-source",
        publisher="Synthetic source",
        endpoint="https://example.test/contact-records",
        family="manual",
        geography="Texas",
        industries=[],
        retrieval_method="fixture",
    )
    session.add(source)
    session.flush()
    project = Project(
        identity_key=f"contact-{uuid4()}",
        name="Synthetic contact project",
        location="Dallas, TX",
        source_id=source.id,
        external_id=f"contact-project-{uuid4()}",
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
        external_id=f"contact-evidence-{uuid4()}",
        title="Synthetic contact project",
        abstract="Synthetic contact source evidence.",
        url="https://example.test/contact-records",
        content_hash="e" * 64,
    )
    session.add(observation)
    session.flush()
    retained = Evidence(
        observation_id=observation.id,
        content_hash=observation.content_hash,
        title=observation.title,
        abstract=observation.abstract,
        url=observation.url,
        extraction_location="fixture",
    )
    session.add(retained)
    session.flush()
    session.add(
        Interpretation(
            observation_id=observation.id,
            content_hash=observation.content_hash,
            assessment={
                "decision": "accepted",
                "evidence_hash": retained.content_hash,
                "project_identity_key": project.identity_key,
            },
            status="accepted",
        )
    )
    text_quote = "Synthetic Operator LLC operates the Synthetic contact project."
    role_quote = "Avery Example is Project Operations at Synthetic Operator LLC."
    assignment_quote = "Avery Example manages site operations for the Synthetic contact project."
    contact_quote = "Contact Avery Example at avery@example.test for project operations."
    url = "https://example.test/contact-claim"
    observed_at = datetime.now(UTC)
    linked_source = BuyingChainEvidence(
        project_id=project.id,
        retained_evidence_id=None,
        url=url,
        title="Synthetic contact directory",
        excerpt="\n".join([text_quote, role_quote, assignment_quote, contact_quote]),
        content_hash="f" * 64,
        extraction_location="fixture",
        published_at=observed_at.date(),
        observed_at=observed_at,
        last_seen_at=observed_at,
        project_match_reason="Synthetic direct project relationship fixture.",
    )
    session.add(linked_source)
    session.flush()
    citations = [
        {
            "evidence_id": str(linked_source.id),
            "quote": text_quote,
            "supports": "project_organization",
            "url": url,
        },
        {
            "evidence_id": str(linked_source.id),
            "quote": role_quote,
            "supports": "organization_person_role",
            "url": url,
        },
        {
            "evidence_id": str(linked_source.id),
            "quote": assignment_quote,
            "supports": "person_project_assignment",
            "url": url,
        },
        {
            "evidence_id": str(linked_source.id),
            "quote": contact_quote,
            "supports": "public_contact",
            "url": url,
        },
    ]
    company = CompanyIdentity()
    session.add(company)
    session.flush()
    claim = BuyingChainClaim(
        project_id=project.id,
        entity_key=f"contact-{uuid4()}",
        fingerprint=f"fingerprint-{uuid4()}",
        policy_version="fixture",
        organization="Synthetic Operator LLC",
        person_name="Avery Example",
        title="Project Operations",
        category="asset_operator",
        organization_relationship="DIRECT",
        person_organization_relationship="DIRECT",
        person_project_relationship="DIRECT",
        evidence_strength="High",
        reason="Synthetic source-backed company contact.",
        citations=citations,
        public_contacts=[
            {
                "kind": "email",
                "value": "avery@example.test",
                "source_url": url,
                "quote": contact_quote,
                "observed_at": observed_at.isoformat(),
            }
        ],
        observed_at=observed_at,
    )
    session.add(claim)
    session.flush()
    session.add(
        BuyingChainRun(
            project_id=project.id,
            input_hash="a" * 64,
            evidence_ids=[str(linked_source.id)],
            claim_ids=[str(claim.id)],
            policy_version="fixture",
            status="complete",
            documents_checked=1,
            candidates_added=1,
            unresolved=[],
        )
    )
    session.add(
        BuyingChainIdentityLink(
            claim_id=claim.id,
            entity_type="company",
            company_identity_id=company.id,
            person_identity_id=None,
            reason="Synthetic current company identity link.",
            basis="project_scoped",
            source_evidence_id=linked_source.id,
            source_version_hash=linked_source.content_hash,
            state="current",
        )
    )
    session.flush()
    return company, project, claim, linked_source


@pytest.fixture
def contact_db():
    if not settings.test_database_url:
        pytest.skip("TEST_DATABASE_URL required for contact assertion database checks")
    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and target.database.endswith("_test") and target != application
    schema = "contact_assertion_test_" + uuid4().hex
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


def test_imported_contact_never_becomes_verified_from_submitted_status():
    result = contact_assertions.contact_assertion_status(
        imported=True,
        verification_basis="direct_confirmation",
        mailbox_confirmed=True,
    )
    assert result == {
        "assertion_status": "imported_unverified",
        "mailbox_verified": False,
        "verification_basis": None,
        "independent_verification": "UNKNOWN_UNSUPPORTED",
    }


def test_inferred_contact_stays_inferred_and_mx_is_not_a_verification_basis():
    inferred = contact_assertions.contact_assertion_status(
        inferred=True,
        published=True,
        verification_basis="direct_confirmation",
        mailbox_confirmed=True,
    )
    assert inferred["assertion_status"] == "inferred"
    assert inferred["mailbox_verified"] is False


def test_published_contact_never_claims_independent_verification():
    published = contact_assertions.contact_assertion_status(published=True)
    assert published["assertion_status"] == "published"
    assert published["mailbox_verified"] is False
    assert published["independent_verification"] == "UNKNOWN_UNSUPPORTED"


def test_imported_contacts_remain_separate_and_unverified(contact_db):
    with contact_db() as session:
        company = CompanyIdentity()
        batch = ExternalImportBatch(
            filename="contacts.xlsx",
            content_hash="d" * 64,
            report={},
            metrics={},
            actor="reviewer",
        )
        session.add_all([company, batch])
        session.flush()
        row = ExternalImportRow(
            batch_id=batch.id,
            sheet="Contacts",
            row_number=2,
            row_kind="contact",
            raw={"Email": "person@example.test"},
            normalized={
                "company_name": "Synthetic Operator",
                "contact_name": "Avery Example",
                "email": "person@example.test",
            },
            errors=[],
            match_status="matched",
            company_match={"status": "matched", "candidate_id": str(company.id)},
            project_match={"status": "unmatched"},
        )
        session.add(row)
        session.flush()
        session.add(ExternalImportActivation(row_id=row.id, active=True, changed_by="reviewer"))
        view = contact_assertions.project_contact_assertions(session, company.id)
        assert view["contacts"] == []
        assert len(view["imported_unverified"]) == 1
        assert view["imported_unverified"][0]["assertion_status"] == "imported_unverified"
        assert view["imported_unverified"][0]["mailbox_verified"] is False


def test_contact_assertion_projection_preserves_historical_corrections(contact_db):
    with contact_db() as session:
        company, project, claim, source = _seed_published_contact(session)
        before = company_contacts(session, company.id)
        assert any(
            method["value"] == "avery@example.test"
            for contact in before.contacts
            for method in contact.methods
        )

        suppression = BuyingChainCorrection(
            project_id=project.id,
            claim_id=claim.id,
            expected_version=claim.fingerprint,
            idempotency_key="historical-contact-suppression",
            action="correct",
            values={"public_contact_kind": "email", "public_contact_value": ""},
            source_evidence_id=None,
            source_version_hash=None,
            reason="Historical published address was reported invalid.",
            actor="historical-reviewer",
        )
        session.add(suppression)
        session.flush()
        after_suppression = company_contacts(session, company.id)
        assert not any(
            method["value"] == "avery@example.test"
            for contact in after_suppression.contacts
            for method in contact.methods
        )

        # Preserve a historical source-free report in the same immutable log;
        # it remains excluded from current source-published contact methods.
        report = BuyingChainCorrection(
            project_id=project.id,
            claim_id=claim.id,
            expected_version=str(suppression.id),
            idempotency_key="historical-contact-report",
            action="correct",
            values={
                "contact_status": "operator_report",
                "public_contact_kind": "email",
                "public_contact_value": "reported@example.test",
            },
            source_evidence_id=None,
            source_version_hash=None,
            reason="Historical operator report; not independently verified.",
            actor="historical-reviewer",
        )
        session.add(report)
        session.flush()
        view = contact_assertions.project_contact_assertions(session, company.id)
        assert all(contact["mailbox_verified"] is False for contact in view["contacts"])
        assert all(
            contact["independent_verification"] == "UNKNOWN_UNSUPPORTED"
            for contact in view["contacts"]
        )
        assert all(
            method["value"] != "reported@example.test"
            for contact in view["contacts"]
            for method in contact["methods"]
        )
        assert (
            session.get(BuyingChainCorrection, suppression.id).values["public_contact_value"] == ""
        )
        assert (
            session.get(BuyingChainCorrection, report.id).values["contact_status"]
            == "operator_report"
        )
