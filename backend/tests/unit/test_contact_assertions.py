import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

import gridlens.intelligence.contact_assertions as contact_assertions
from gridlens.domain.opportunity_intelligence import contact_projection
from gridlens.intelligence.buying_chain import buying_chain_view
from gridlens.intelligence.company_contacts import company_contacts
from gridlens.intelligence.contact_suppressions import (
    SuppressionConflict,
    global_method_suppression_key,
    global_person_suppression_key,
    method_suppression_key,
    record_contact_suppression,
)
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
    PersonIdentity,
    PowerNeed,
    Project,
    Source,
)
from gridlens.persistence.suppression_models import ContactSuppression
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


def test_contact_suppression_is_versioned_idempotent_and_reversible(contact_db):
    from types import SimpleNamespace

    from gridlens.intelligence.contact_suppressions import (
        apply_contact_suppressions,
        method_suppression_key,
        record_contact_suppression,
    )

    with contact_db() as session:
        company = CompanyIdentity()
        session.add(company)
        session.flush()
        key = method_suppression_key(
            company.id, "Avery Example", "email", "mailto:Avery@Example.test"
        )
        event = record_contact_suppression(
            session,
            scope="method",
            subject_key=key,
            action="suppress",
            expected_version=0,
            reason="privacy request",
            actor="privacy-ops",
            idempotency_key="privacy-req-1",
        )
        session.flush()
        assert (
            record_contact_suppression(
                session,
                scope="method",
                subject_key=key,
                action="suppress",
                expected_version=0,
                reason="privacy request",
                actor="privacy-ops",
                idempotency_key="privacy-req-1",
            ).id
            == event.id
        )
        contact = SimpleNamespace(
            name="Avery Example", methods=[{"kind": "email", "href": "Avery@Example.test"}]
        )
        assert apply_contact_suppressions(session, company.id, [contact])[0].methods == []
        with pytest.raises(SuppressionConflict):
            record_contact_suppression(
                session,
                scope="method",
                subject_key=key,
                action="reinstate",
                expected_version=0,
                reason="stale",
                actor="privacy-ops",
                idempotency_key="privacy-req-2",
            )
        record_contact_suppression(
            session,
            scope="method",
            subject_key=key,
            action="reinstate",
            expected_version=1,
            reason="request withdrawn",
            actor="privacy-ops",
            idempotency_key="privacy-req-3",
        )
        refreshed_contact = SimpleNamespace(
            name="Avery Example", methods=[{"kind": "email", "href": "Avery@Example.test"}]
        )
        assert apply_contact_suppressions(session, company.id, [refreshed_contact])[0].methods


def test_contact_suppression_keys_canonicalize_raw_values_and_hrefs():
    company_id = uuid4()
    assert method_suppression_key(
        company_id, "Avery", "email", "Avery@Example.test"
    ) == method_suppression_key(company_id, "Avery", "email", "mailto:avery@example.test")
    assert method_suppression_key(
        company_id, "Avery", "phone", "+1 (555) 123-4567"
    ) == method_suppression_key(company_id, "Avery", "tel", "tel:+15551234567")
    assert method_suppression_key(
        company_id, "Avery", "phone", "555-123-4567"
    ) == method_suppression_key(company_id, "Avery", "tel", "tel:+1 (555) 123-4567")


def test_conflicted_suppression_history_fails_closed_and_cannot_be_reinstated(contact_db):
    from types import SimpleNamespace

    from gridlens.intelligence.contact_suppressions import (
        apply_contact_suppressions,
        method_suppression_key,
        record_contact_suppression,
    )

    with contact_db() as session:
        company = CompanyIdentity()
        session.add(company)
        session.flush()
        key = method_suppression_key(company.id, "Avery", "email", "avery@example.test")
        session.add(
            ContactSuppression(
                scope="method",
                subject_key=key,
                expected_version=8,
                version=9,
                action="reinstate",
                reason="forked",
                actor="reviewer",
                idempotency_key="fork",
            )
        )
        session.flush()
        contact = SimpleNamespace(
            name="Avery", methods=[{"kind": "email", "href": "mailto:avery@example.test"}]
        )
        assert apply_contact_suppressions(session, company.id, [contact])[0].methods == []
        with pytest.raises(SuppressionConflict):
            record_contact_suppression(
                session,
                scope="method",
                subject_key=key,
                action="reinstate",
                expected_version=9,
                reason="retry",
                actor="reviewer",
                idempotency_key="retry",
            )
        invalid_key = method_suppression_key(company.id, "Casey", "email", "casey@example.test")
        session.add(
            ContactSuppression(
                scope="method",
                subject_key=invalid_key,
                expected_version=0,
                version=1,
                action="reinstate",
                reason="invalid first transition",
                actor="reviewer",
                idempotency_key="invalid-first-reinstate",
            )
        )
        session.flush()
        casey = SimpleNamespace(
            name="Casey", methods=[{"kind": "email", "href": "mailto:casey@example.test"}]
        )
        assert apply_contact_suppressions(session, company.id, [casey])[0].methods == []


def test_suppression_migration_refuses_populated_rollback(contact_db):
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "migrations"
        / "versions"
        / "0045_contact_suppressions.py"
    )
    spec = importlib.util.spec_from_file_location("contact_suppressions_migration", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with contact_db() as session:
        connection = session.connection()
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
            migration.upgrade()
        session.add(
            ContactSuppression(
                scope="company",
                subject_key="1" * 64,
                expected_version=0,
                version=1,
                action="suppress",
                reason="privacy request",
                actor="privacy-ops",
                idempotency_key="migration-rollback-guard",
            )
        )
        session.flush()
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(RuntimeError, match="retained privacy history"):
                migration.downgrade()
        assert session.query(ContactSuppression).count() == 1


def test_correction_writer_rejects_forged_role_and_wrong_project_replay(contact_db):
    from gridlens.intelligence.internal_corrections import correct_buying_chain_claim

    with contact_db() as session:
        _company, project, claim, source = _seed_published_contact(session)
        with pytest.raises(ValueError, match="positive person_name edits"):
            correct_buying_chain_claim(
                session,
                project_id=project.id,
                claim_id=claim.id,
                expected_version=claim.fingerprint,
                action="correct",
                values={"person_project_relationship": "DIRECT", "person_name": "Made Up Person"},
                reason="bad input",
                actor="privacy-ops",
                idempotency_key="forged-direct",
                source_evidence_id=source.id,
                source_version_hash=source.content_hash,
            )
        with pytest.raises(ValueError, match="bounded string"):
            correct_buying_chain_claim(
                session,
                project_id=project.id,
                claim_id=claim.id,
                expected_version=claim.fingerprint,
                action="correct",
                values={"public_contact_value": 12345},
                reason="bad type",
                actor="privacy-ops",
                idempotency_key="numeric-method",
                source_evidence_id=source.id,
                source_version_hash=source.content_hash,
            )
        correction = correct_buying_chain_claim(
            session,
            project_id=project.id,
            claim_id=claim.id,
            expected_version=claim.fingerprint,
            action="retract",
            values={},
            reason="incorrect link",
            actor="privacy-ops",
            idempotency_key="scoped-retract",
        )
        assert correction.project_id == project.id
        with pytest.raises(LookupError):
            correct_buying_chain_claim(
                session,
                project_id=uuid4(),
                claim_id=claim.id,
                expected_version=claim.fingerprint,
                action="retract",
                values={},
                reason="incorrect link",
                actor="privacy-ops",
                idempotency_key="scoped-retract",
            )


def test_method_suppression_redacts_current_and_history_buying_chain_reads(contact_db):
    with contact_db() as session:
        company, project, claim, _source = _seed_published_contact(session)
        refreshed_claim = BuyingChainClaim(
            project_id=claim.project_id,
            entity_key=claim.entity_key,
            fingerprint=uuid4().hex,
            policy_version=claim.policy_version,
            organization=claim.organization,
            person_name=claim.person_name,
            title=claim.title,
            category=claim.category,
            organization_relationship=claim.organization_relationship,
            person_organization_relationship=claim.person_organization_relationship,
            person_project_relationship=claim.person_project_relationship,
            evidence_strength=claim.evidence_strength,
            reason=claim.reason,
            citations=claim.citations,
            public_contacts=claim.public_contacts,
            observed_at=claim.observed_at + timedelta(minutes=2),
        )
        session.add(refreshed_claim)
        session.flush()
        session.add(
            BuyingChainIdentityLink(
                claim_id=refreshed_claim.id,
                entity_type="company",
                company_identity_id=company.id,
                person_identity_id=None,
                reason="Synthetic refreshed company link.",
                basis="project_scoped",
                source_evidence_id=_source.id,
                source_version_hash=_source.content_hash,
                state="current",
            )
        )
        run = session.query(BuyingChainRun).filter_by(project_id=project.id).one()
        run.claim_ids = [str(claim.id), str(refreshed_claim.id)]
        key = method_suppression_key(
            company.id, claim.person_name, "email", "mailto:avery@example.test"
        )
        record_contact_suppression(
            session,
            scope="method",
            subject_key=key,
            action="suppress",
            expected_version=0,
            reason="privacy request",
            actor="privacy-ops",
            idempotency_key="method-hide-current-history",
        )
        session.flush()
        current = buying_chain_view(session, project.id)
        historical = buying_chain_view(session, project.id, history=True)
        assert any(row["id"] == refreshed_claim.id for row in current["candidates"])
        for view in (current, historical):
            item = next(
                row for row in view["candidates"] if row["id"] in {claim.id, refreshed_claim.id}
            )
            assert item["public_contacts"] == []
            assert not any(
                "avery@example.test" in str(e.get("quote", "")) for e in item["evidence"]
            )
            assert all(not contact.methods for contact in contact_projection(view))


def test_contact_privacy_key_budget_is_per_project_and_preserves_suppression(contact_db):
    from gridlens.intelligence.buying_chain import _apply_contact_privacy
    from gridlens.intelligence.saved_history_privacy import MAX_HISTORY_KEYS

    with contact_db() as session:
        company, project, seed, source = _seed_published_contact(session)
        # Each project stays under the cap, while their aggregate exceeds it.
        candidates = []
        projects = [project]
        for index in range(10):
            other = Project(
                identity_key=f"privacy-budget-{uuid4()}",
                name=f"Privacy project {index}",
                location="Dallas, TX",
                source_id=project.source_id,
                external_id=f"privacy-budget-{uuid4()}",
            )
            session.add(other)
            session.flush()
            projects.append(other)
        for project_index, target_project in enumerate(projects):
            for index in range(MAX_HISTORY_KEYS // 10 + 1):
                claim = BuyingChainClaim(
                    project_id=target_project.id,
                    entity_key=f"privacy-{project_index}-{index}",
                    fingerprint=uuid4().hex,
                    policy_version=seed.policy_version,
                    organization=seed.organization,
                    person_name=f"Subject {project_index}-{index}",
                    title="Project Operations",
                    category=seed.category,
                    organization_relationship=seed.organization_relationship,
                    person_organization_relationship=seed.person_organization_relationship,
                    person_project_relationship=seed.person_project_relationship,
                    evidence_strength=seed.evidence_strength,
                    reason=seed.reason,
                    citations=[],
                    public_contacts=[
                        {"kind": "email", "value": f"person{project_index}-{index}@example.test"}
                    ],
                    observed_at=seed.observed_at + timedelta(seconds=index + project_index),
                )
                session.add(claim)
                session.flush()
                candidate_company = CompanyIdentity()
                session.add(candidate_company)
                session.flush()
                session.add(
                    BuyingChainIdentityLink(
                        claim_id=claim.id,
                        entity_type="company",
                        company_identity_id=candidate_company.id,
                        person_identity_id=None,
                        reason="Test lineage",
                        basis="project_scoped",
                        source_evidence_id=source.id,
                        source_version_hash=source.content_hash,
                        state="current",
                    )
                )
                candidates.append(
                    {
                        "id": claim.id,
                        "person_name": claim.person_name,
                        "title": claim.title,
                        "reason": "Project contact",
                        "public_contacts": claim.public_contacts,
                        "reported_contacts": [],
                        "correction_history": [],
                        "evidence": [],
                    }
                )
        target = candidates[0]
        target_email = target["public_contacts"][0]["value"]
        record_contact_suppression(
            session,
            scope="method",
            subject_key=global_method_suppression_key("email", target_email),
            action="suppress",
            expected_version=0,
            reason="project privacy budget regression",
            actor="privacy-ops",
            idempotency_key="project-privacy-budget-method",
        )
        session.flush()
        statements = []
        from sqlalchemy import event

        event.listen(session.bind, "before_cursor_execute", lambda *_args: statements.append(1))
        _apply_contact_privacy(session, candidates)
        assert target["public_contacts"] == []
        assert all(candidate.get("suppressed") is not True for candidate in candidates)
        assert len(statements) < 20


def test_contact_privacy_overflow_fails_closed_only_for_oversized_project(contact_db, monkeypatch):
    import gridlens.intelligence.buying_chain as buying_chain_module
    import gridlens.intelligence.saved_history_privacy as saved_privacy
    from gridlens.intelligence.buying_chain import _apply_contact_privacy

    monkeypatch.setattr(saved_privacy, "MAX_HISTORY_KEYS", 4)
    monkeypatch.setattr(buying_chain_module, "MAX_HISTORY_KEYS", 4)
    with contact_db() as session:
        _company, project, seed, source = _seed_published_contact(session)
        oversized_project = Project(
            identity_key=f"privacy-overflow-{uuid4()}",
            name="Oversized privacy project",
            location="Dallas, TX",
            source_id=project.source_id,
            external_id=f"privacy-overflow-{uuid4()}",
        )
        session.add(oversized_project)
        session.flush()
        candidates = []
        target_projects = [project]
        for project_index in range(3):
            separate_project = Project(
                identity_key=f"privacy-overflow-small-{uuid4()}",
                name=f"Small privacy project {project_index}",
                location="Dallas, TX",
                source_id=project.source_id,
                external_id=f"privacy-overflow-small-{uuid4()}",
            )
            session.add(separate_project)
            session.flush()
            target_projects.append(separate_project)
        for target_project, count in ((project, 1), (oversized_project, 3)):
            for index in range(count):
                claim = BuyingChainClaim(
                    project_id=target_project.id,
                    entity_key=f"overflow-{index}-{uuid4()}",
                    fingerprint=uuid4().hex,
                    policy_version=seed.policy_version,
                    organization=seed.organization,
                    person_name=f"Overflow {target_project.id}-{index}",
                    title="Project Operations",
                    category=seed.category,
                    organization_relationship=seed.organization_relationship,
                    person_organization_relationship=seed.person_organization_relationship,
                    person_project_relationship=seed.person_project_relationship,
                    evidence_strength=seed.evidence_strength,
                    reason=seed.reason,
                    citations=[],
                    public_contacts=[{"kind": "email", "value": f"p{index}@example.test"}],
                    observed_at=seed.observed_at + timedelta(seconds=index),
                )
                session.add(claim)
                session.flush()
                candidate_company = CompanyIdentity()
                session.add(candidate_company)
                session.flush()
                session.add(
                    BuyingChainIdentityLink(
                        claim_id=claim.id,
                        entity_type="company",
                        company_identity_id=candidate_company.id,
                        person_identity_id=None,
                        reason="Test lineage",
                        basis="project_scoped",
                        source_evidence_id=source.id,
                        source_version_hash=source.content_hash,
                        state="current",
                    )
                )
                candidates.append(
                    {
                        "id": claim.id,
                        "person_name": claim.person_name,
                        "title": claim.title,
                        "reason": "Project contact",
                        "public_contacts": claim.public_contacts,
                        "reported_contacts": [],
                        "correction_history": [],
                        "evidence": [],
                    }
                )
        small_claim = BuyingChainClaim(
            project_id=target_projects[1].id,
            entity_key="small-independent-subject",
            fingerprint=uuid4().hex,
            policy_version=seed.policy_version,
            organization=seed.organization,
            person_name="Independent Small Subject",
            title="Project Operations",
            category=seed.category,
            organization_relationship=seed.organization_relationship,
            person_organization_relationship=seed.person_organization_relationship,
            person_project_relationship=seed.person_project_relationship,
            evidence_strength=seed.evidence_strength,
            reason=seed.reason,
            citations=[],
            public_contacts=[{"kind": "email", "value": "small@example.test"}],
            observed_at=seed.observed_at,
        )
        session.add(small_claim)
        session.flush()
        candidates.insert(
            0,
            {
                "id": small_claim.id,
                "person_name": small_claim.person_name,
                "title": small_claim.title,
                "reason": "Project contact",
                "public_contacts": small_claim.public_contacts,
                "reported_contacts": [],
                "correction_history": [],
                "evidence": [],
            },
        )
        _apply_contact_privacy(session, candidates)
        small_candidate = candidates[0]
        oversized_candidates = candidates[1:]
        assert small_candidate.get("suppressed") is not True
        assert all(candidate.get("suppressed") is True for candidate in oversized_candidates)


def test_missing_entity_scope_recursively_redacts_display_fields(contact_db):
    from gridlens.intelligence.buying_chain import _apply_contact_privacy

    with contact_db() as session:
        _company, _project, claim, _source = _seed_published_contact(session)
        claim.entity_key = ""
        session.flush()
        candidate = {
            "id": claim.id,
            "person_name": "Avery Example",
            "title": "Project Operations",
            "organization": "Hidden Person <hidden@example.test>",
            "reason": "Call 512-555-0100 about Avery Example",
            "public_contacts": [],
            "reported_contacts": [],
            "correction_history": [],
            "evidence": [],
            "future_extension": {"text": "Avery Example, hidden@example.test"},
        }
        _apply_contact_privacy(session, [candidate])
        assert candidate["suppressed"] is True
        assert "hidden@example.test" not in str(candidate).casefold()
        assert "Avery Example" not in str(candidate)
        assert "512-555-0100" not in str(candidate)


def test_global_method_suppression_applies_without_company_identity_link(contact_db):
    with contact_db() as session:
        _company, project, claim, _source = _seed_published_contact(session)
        link = (
            session.query(BuyingChainIdentityLink)
            .filter_by(claim_id=claim.id, entity_type="company")
            .one()
        )
        session.delete(link)
        key = global_method_suppression_key("email", "avery@example.test")
        record_contact_suppression(
            session,
            scope="method",
            subject_key=key,
            action="suppress",
            expected_version=0,
            reason="global privacy request",
            actor="privacy-ops",
            idempotency_key="global-method-no-company-link",
        )
        session.flush()
        view = buying_chain_view(session, project.id)
        item = next(row for row in view["candidates"] if row["id"] == claim.id)
        assert item["public_contacts"] == []


def test_global_person_suppression_survives_new_claim_and_source_version(contact_db, monkeypatch):
    from gridlens.api import app as api_app

    with contact_db() as session:
        company, project, old_claim, old_source = _seed_published_contact(session)
        project.region_status = "ELIGIBLE"
        project.region_state = "TX"
        person = PersonIdentity()
        session.add(person)
        session.flush()
        session.add(
            BuyingChainIdentityLink(
                claim_id=old_claim.id,
                entity_type="person",
                company_identity_id=None,
                person_identity_id=person.id,
                reason="Synthetic original linked person.",
                basis="project_scoped",
                source_evidence_id=old_source.id,
                source_version_hash=old_source.content_hash,
                state="current",
            )
        )
        refreshed_source = BuyingChainEvidence(
            project_id=project.id,
            retained_evidence_id=None,
            url=old_source.url,
            title=old_source.title,
            excerpt=old_source.excerpt + " Updated listing.",
            content_hash="9" * 64,
            extraction_location="updated fixture",
            published_at=old_source.published_at,
            observed_at=old_source.observed_at + timedelta(minutes=5),
            last_seen_at=old_source.last_seen_at + timedelta(minutes=5),
            project_match_reason=old_source.project_match_reason,
        )
        session.add(refreshed_source)
        session.flush()
        refreshed_claim = BuyingChainClaim(
            project_id=old_claim.project_id,
            entity_key=old_claim.entity_key,
            fingerprint=uuid4().hex,
            policy_version=old_claim.policy_version,
            organization=old_claim.organization,
            person_name=old_claim.person_name,
            title=old_claim.title,
            category=old_claim.category,
            organization_relationship=old_claim.organization_relationship,
            person_organization_relationship=old_claim.person_organization_relationship,
            person_project_relationship=old_claim.person_project_relationship,
            evidence_strength=old_claim.evidence_strength,
            reason=old_claim.reason,
            citations=[
                {**citation, "evidence_id": str(refreshed_source.id)}
                for citation in old_claim.citations
            ],
            public_contacts=old_claim.public_contacts,
            observed_at=old_claim.observed_at + timedelta(minutes=5),
        )
        session.add(refreshed_claim)
        session.flush()
        session.add(
            BuyingChainIdentityLink(
                claim_id=refreshed_claim.id,
                entity_type="company",
                company_identity_id=company.id,
                person_identity_id=None,
                reason="Synthetic refreshed company-only link.",
                basis="project_scoped",
                source_evidence_id=refreshed_source.id,
                source_version_hash=refreshed_source.content_hash,
                state="current",
            )
        )
        run = session.query(BuyingChainRun).filter_by(project_id=project.id).one()
        run.evidence_ids = [str(old_source.id), str(refreshed_source.id)]
        run.claim_ids = [str(refreshed_claim.id)]
        record_contact_suppression(
            session,
            scope="person",
            subject_key=global_person_suppression_key(person.id),
            action="suppress",
            expected_version=0,
            reason="global privacy request",
            actor="privacy-ops",
            idempotency_key="hide-refreshed-person",
        )
        session.flush()
        for view in (
            buying_chain_view(session, project.id),
            buying_chain_view(session, project.id, history=True),
        ):
            hidden = [row for row in view["candidates"] if row.get("suppressed") is True]
            assert hidden
            assert not any("Avery Example" in str(row) for row in hidden)
            assert all(not contact.methods for contact in contact_projection(view))
        session.commit()
        project_id = project.id
    monkeypatch.setattr(api_app, "SessionLocal", contact_db)
    search = api_app.unified_search("Avery Example")
    assert search["contacts"] == []
    assert project_id not in {item["project_id"] for item in search["projects"]}
    with contact_db() as session:
        event = session.query(ContactSuppression).filter_by(scope="person").one()
        record_contact_suppression(
            session,
            scope="person",
            subject_key=event.subject_key,
            action="reinstate",
            expected_version=1,
            reason="explicit privacy review restored visibility",
            actor="privacy-ops",
            idempotency_key="reinstate-refreshed-person",
        )
        session.flush()
        visible = buying_chain_view(session, project_id)
        assert any(
            row["id"] == refreshed_claim.id and row["person_name"] == "Avery Example"
            for row in visible["candidates"]
        )


def test_person_privacy_lineage_limit_is_per_exact_entity_and_fail_closed(contact_db):
    from gridlens.intelligence.buying_chain import (
        MAX_PERSON_PRIVACY_LINEAGE_LINKS,
        _apply_contact_privacy,
    )

    with contact_db() as session:
        _company, project, seed_claim, source = _seed_published_contact(session)
        candidates = []

        def add_linked_claim(entity_key: str, name: str, index: int):
            person = PersonIdentity()
            claim = BuyingChainClaim(
                project_id=project.id,
                entity_key=entity_key,
                fingerprint=uuid4().hex,
                policy_version=seed_claim.policy_version,
                organization=seed_claim.organization,
                person_name=name,
                title="Project Operations",
                category=seed_claim.category,
                organization_relationship=seed_claim.organization_relationship,
                person_organization_relationship=seed_claim.person_organization_relationship,
                person_project_relationship=seed_claim.person_project_relationship,
                evidence_strength=seed_claim.evidence_strength,
                reason=seed_claim.reason,
                citations=[],
                public_contacts=[],
                observed_at=seed_claim.observed_at + timedelta(seconds=index + 1),
            )
            session.add_all([person, claim])
            session.flush()
            session.add(
                BuyingChainIdentityLink(
                    claim_id=claim.id,
                    entity_type="person",
                    company_identity_id=None,
                    person_identity_id=person.id,
                    reason="Synthetic historical identity link.",
                    basis="project_scoped",
                    source_evidence_id=source.id,
                    source_version_hash=source.content_hash,
                    state="current",
                )
            )
            candidates.append(
                {
                    "id": claim.id,
                    "person_name": name,
                    "title": "Project Operations",
                    "public_contacts": [],
                    "reported_contacts": [],
                    "correction_history": [],
                    "evidence": [],
                }
            )
            return claim

        overflow_claims = [seed_claim]
        for index in range(MAX_PERSON_PRIVACY_LINEAGE_LINKS):
            overflow_claims.append(
                add_linked_claim(seed_claim.entity_key, "Overflow Subject", index)
            )
        overflow_person = PersonIdentity()
        session.add(overflow_person)
        session.flush()
        session.add(
            BuyingChainIdentityLink(
                claim_id=seed_claim.id,
                entity_type="person",
                company_identity_id=None,
                person_identity_id=overflow_person.id,
                reason="Synthetic original identity link.",
                basis="project_scoped",
                source_evidence_id=source.id,
                source_version_hash=source.content_hash,
                state="current",
            )
        )
        overflow_candidate = {
            "id": seed_claim.id,
            "person_name": "Overflow Subject",
            "title": "Project Operations",
            "public_contacts": [],
            "reported_contacts": [],
            "correction_history": [],
            "evidence": [],
        }
        candidates.append(overflow_candidate)
        clean_candidates = [
            add_linked_claim(f"separate-{index}", f"Separate Subject {index}", index + 200)
            for index in range(MAX_PERSON_PRIVACY_LINEAGE_LINKS + 1)
        ]
        _apply_contact_privacy(session, candidates)
        assert overflow_candidate.get("suppressed") is True
        clean_ids = {claim.id for claim in clean_candidates}
        assert all(
            candidate.get("suppressed") is not True
            for candidate in candidates
            if candidate["id"] in clean_ids
        )


def test_global_search_does_not_return_suppressed_contact_method(contact_db, monkeypatch):
    from gridlens.api import app as api_app
    from gridlens.intelligence.internal_corrections import correct_buying_chain_claim

    with contact_db() as session:
        company, project, claim, _source = _seed_published_contact(session)
        project.region_status = "ELIGIBLE"
        project.region_state = "TX"
        session.flush()
        correct_buying_chain_claim(
            session,
            project_id=project.id,
            claim_id=claim.id,
            expected_version=claim.fingerprint,
            action="correct",
            values={"public_contact_kind": "email", "public_contact_value": None},
            reason="privacy removal",
            actor="privacy-ops",
            idempotency_key="clear-before-global-search-suppress",
            source_evidence_id=_source.id,
            source_version_hash=_source.content_hash,
        )
        key = global_method_suppression_key("email", "mailto:avery@example.test")
        record_contact_suppression(
            session,
            scope="method",
            subject_key=key,
            action="suppress",
            expected_version=0,
            reason="global privacy request",
            actor="privacy-ops",
            idempotency_key="search-method-redaction",
        )
        session.commit()
        project_id = project.id
    monkeypatch.setattr(api_app, "SessionLocal", contact_db)
    payload = api_app.unified_search("avery@example.test")
    assert payload["contacts"] == []
    assert project_id not in {item["project_id"] for item in payload["projects"]}


def test_contact_kind_reuses_exact_method_and_null_clears(contact_db):
    from gridlens.intelligence.internal_corrections import correct_buying_chain_claim

    with contact_db() as session:
        _company, project, claim, source = _seed_published_contact(session)
        asserted = correct_buying_chain_claim(
            session,
            project_id=project.id,
            claim_id=claim.id,
            expected_version=claim.fingerprint,
            action="correct",
            values={"public_contact_kind": "email", "public_contact_value": "avery@example.test"},
            reason="retain exact extracted method",
            actor="privacy-ops",
            idempotency_key="exact-method-reuse",
            source_evidence_id=source.id,
            source_version_hash=source.content_hash,
        )
        session.flush()
        cleared = correct_buying_chain_claim(
            session,
            project_id=project.id,
            claim_id=claim.id,
            expected_version=str(asserted.id),
            action="correct",
            values={"public_contact_kind": "email", "public_contact_value": None},
            reason="clear exact email method",
            actor="privacy-ops",
            idempotency_key="null-method-clear",
            source_evidence_id=source.id,
            source_version_hash=source.content_hash,
        )
        session.flush()
        view = buying_chain_view(session, project.id)
        item = next(row for row in view["candidates"] if row["id"] == claim.id)
        assert item["public_contacts"] == []
        assert cleared.expected_version == str(asserted.id)


def test_suppression_redacts_methods_removed_before_suppression(contact_db):
    from gridlens.intelligence.internal_corrections import correct_buying_chain_claim

    with contact_db() as session:
        company, project, claim, source = _seed_published_contact(session)
        cleared = correct_buying_chain_claim(
            session,
            project_id=project.id,
            claim_id=claim.id,
            expected_version=claim.fingerprint,
            action="correct",
            values={"public_contact_kind": "email", "public_contact_value": None},
            reason="privacy removal",
            actor="privacy-ops",
            idempotency_key="clear-before-suppress",
            source_evidence_id=source.id,
            source_version_hash=source.content_hash,
        )
        session.flush()
        before = buying_chain_view(session, project.id)
        before_item = next(row for row in before["candidates"] if row["id"] == claim.id)
        assert before_item["public_contacts"] == []
        key = method_suppression_key(company.id, claim.person_name, "email", "avery@example.test")
        record_contact_suppression(
            session,
            scope="method",
            subject_key=key,
            action="suppress",
            expected_version=0,
            reason="privacy request",
            actor="privacy-ops",
            idempotency_key="suppress-after-clear",
        )
        session.flush()
        for view in (
            buying_chain_view(session, project.id),
            buying_chain_view(session, project.id, history=True),
        ):
            item = next(row for row in view["candidates"] if row["id"] == claim.id)
            assert "avery@example.test" not in str(item.get("evidence", [])).casefold()
            assert "avery@example.test" not in str(item.get("correction_history", [])).casefold()
        assert "avery@example.test" in source.excerpt
        assert (
            "avery@example.test"
            in session.get(BuyingChainClaim, claim.id).public_contacts[0]["value"]
        )
        assert cleared.id


def test_phone_suppression_does_not_join_neighboring_evidence_quotes(contact_db, monkeypatch):
    from gridlens.api import app as api_app
    from gridlens.intelligence.internal_corrections import correct_buying_chain_claim

    with contact_db() as session:
        _company, project, claim, source = _seed_published_contact(session)
        project.region_status = "ELIGIBLE"
        project.region_state = "TX"
        first_quote = "Call Avery at 512-555-0100 for project operations."
        second_quote = "Alternate office line: 512-555-0200."
        source.excerpt = f"{source.excerpt}\n{first_quote}\n{second_quote}"
        claim.citations = [
            citation for citation in claim.citations if citation["supports"] != "public_contact"
        ] + [
            {
                "evidence_id": str(source.id),
                "quote": first_quote,
                "supports": "public_contact",
                "url": source.url,
            },
            {
                "evidence_id": str(source.id),
                "quote": second_quote,
                "supports": "public_contact",
                "url": source.url,
            },
        ]
        claim.public_contacts = [
            {
                "kind": "phone",
                "value": "512-555-0100",
                "source_url": source.url,
                "quote": first_quote,
                "observed_at": source.observed_at.isoformat(),
            }
        ]
        session.flush()
        correct_buying_chain_claim(
            session,
            project_id=project.id,
            claim_id=claim.id,
            expected_version=claim.fingerprint,
            action="correct",
            values={"public_contact_kind": "phone", "public_contact_value": None},
            reason="privacy removal",
            actor="privacy-ops",
            idempotency_key="clear-phone-before-suppress",
            source_evidence_id=source.id,
            source_version_hash=source.content_hash,
        )
        key = global_method_suppression_key("phone", "+1 (512) 555-0100")
        record_contact_suppression(
            session,
            scope="method",
            subject_key=key,
            action="suppress",
            expected_version=0,
            reason="global phone privacy request",
            actor="privacy-ops",
            idempotency_key="suppress-cleared-phone",
        )
        session.flush()
        for view in (
            buying_chain_view(session, project.id),
            buying_chain_view(session, project.id, history=True),
        ):
            item = next(row for row in view["candidates"] if row["id"] == claim.id)
            rendered = str(item.get("evidence", [])).casefold()
            assert "512-555-0100" not in rendered
            assert "512-555-0200" in rendered
        assert "512-555-0100" in source.excerpt
        session.commit()
        project_id = project.id
    monkeypatch.setattr(api_app, "SessionLocal", contact_db)
    search = api_app.unified_search("512-555-0100")
    assert search["contacts"] == []
    assert project_id not in {item["project_id"] for item in search["projects"]}


def test_suppressed_email_is_redacted_from_surviving_phone_quote(contact_db, monkeypatch):
    from gridlens.api import app as api_app

    with contact_db() as session:
        _company, project, claim, source = _seed_published_contact(session)
        project.region_status = "ELIGIBLE"
        project.region_state = "TX"
        shared_quote = (
            "Contact Avery at hidden@example.test or call 512-555-0100 for project operations."
        )
        source.excerpt = f"{source.excerpt}\n{shared_quote}"
        claim.citations = [
            citation for citation in claim.citations if citation["supports"] != "public_contact"
        ] + [
            {
                "evidence_id": str(source.id),
                "quote": shared_quote,
                "supports": "public_contact",
                "url": source.url,
            }
        ]
        claim.public_contacts = [
            {
                "kind": "email",
                "value": "hidden@example.test",
                "source_url": source.url,
                "quote": shared_quote,
                "observed_at": source.observed_at.isoformat(),
            },
            {
                "kind": "phone",
                "value": "512-555-0100",
                "source_url": source.url,
                "quote": shared_quote,
                "observed_at": source.observed_at.isoformat(),
            },
        ]
        record_contact_suppression(
            session,
            scope="method",
            subject_key=global_method_suppression_key("email", "hidden@example.test"),
            action="suppress",
            expected_version=0,
            reason="email privacy request",
            actor="privacy-ops",
            idempotency_key="suppress-email-shared-quote",
        )
        session.flush()
        for view in (
            buying_chain_view(session, project.id),
            buying_chain_view(session, project.id, history=True),
        ):
            item = next(row for row in view["candidates"] if row["id"] == claim.id)
            assert len(item["public_contacts"]) == 1
            phone = item["public_contacts"][0]
            assert phone["kind"] == "phone"
            assert "hidden@example.test" not in phone["quote"]
            assert "512-555-0100" in phone["quote"]
            cited = next(
                evidence
                for evidence in item["evidence"]
                if evidence["supports"] == "public_contact"
                and evidence["url"] == phone["source_url"]
            )
            assert cited["quote"] == phone["quote"]
        assert "hidden@example.test" in source.excerpt
        session.commit()
        project_id = project.id
    monkeypatch.setattr(api_app, "SessionLocal", contact_db)
    result = api_app.unified_search("hidden@example.test")
    assert result["contacts"] == []
    assert project_id not in {item["project_id"] for item in result["projects"]}


def test_extracted_title_email_is_redacted_across_candidate_display_fields(contact_db, monkeypatch):
    from copy import deepcopy

    from gridlens.api import app as api_app
    from gridlens.domain.opportunity_intelligence import contact_projection
    from gridlens.ingestion.adapters.buying_chain_public import parse_document
    from gridlens.intelligence.buying_chain import _apply_contact_privacy
    from gridlens.intelligence.buying_chain_extraction import Extracted, extract_people

    with contact_db() as session:
        _company, project, claim, source = _seed_published_contact(session)
        project.region_status = "ELIGIBLE"
        project.region_state = "TX"
        html = (
            "<html><title>Team</title><body>"
            "<h2>Avery Example, Procurement Manager hidden@example.test</h2>"
            "</body></html>"
        )
        parsed = parse_document(
            "https://example.test/team", html.encode(), "text/html; charset=utf-8"
        )
        extracted = extract_people(
            parsed,
            [Extracted("Synthetic Operator LLC", "asset_operator")],
            project,
            project_scoped=True,
            today=source.observed_at.date(),
            verified_official_roster=True,
        )
        assert extracted and extracted[0].title == "Procurement Manager hidden@example.test"
        claim.title = extracted[0].title
        claim.person_name = extracted[0].person_name
        claim.public_contacts = []
        claim.citations = [
            citation for citation in claim.citations if citation["supports"] != "public_contact"
        ]
        source.excerpt = "\n".join(
            line for line in source.excerpt.splitlines() if "avery@example.test" not in line
        )
        record_contact_suppression(
            session,
            scope="method",
            subject_key=global_method_suppression_key("email", "hidden@example.test"),
            action="suppress",
            expected_version=0,
            reason="privacy request",
            actor="privacy-ops",
            idempotency_key="suppress-title-embedded-email",
        )
        session.flush()
        for view in (
            buying_chain_view(session, project.id),
            buying_chain_view(session, project.id, history=True),
        ):
            item = next(row for row in view["candidates"] if row["id"] == claim.id)
            assert "hidden@example.test" not in str(item).casefold()
            assert "[redacted]" in item["title"]
            assert all("hidden@example.test" not in str(c) for c in contact_projection(view))
            extended = deepcopy(item)
            extended["future_display_extension"] = {"label": "hidden@example.test"}
            _apply_contact_privacy(session, [extended])
            assert "hidden@example.test" not in str(extended).casefold()
        assert session.get(BuyingChainClaim, claim.id).title == extracted[0].title
        session.commit()
        project_id = project.id
    monkeypatch.setattr(api_app, "SessionLocal", contact_db)
    result = api_app.unified_search("hidden@example.test")
    assert result["contacts"] == []
    assert project_id not in {item["project_id"] for item in result["projects"]}


def test_excessive_retained_contact_values_fail_closed(contact_db):
    from gridlens.intelligence.buying_chain import (
        MAX_CONTACT_VALUES_PER_CANDIDATE,
        _apply_contact_privacy,
    )

    with contact_db() as session:
        _company, project, claim, _source = _seed_published_contact(session)
        claim.entity_key = "oversized-values"
        claim.citations = []
        session.flush()
        candidate = {
            "id": claim.id,
            "person_name": "Synthetic Person",
            "title": "Synthetic Role",
            "reason": "Synthetic reason",
            "category": "asset_operator",
            "future_display_extension": {"label": "hidden@example.test"},
            "public_contacts": [],
            "reported_contacts": [],
            "correction_history": [],
            "evidence": [
                {
                    "quote": " ".join(
                        f"person{index}@example.test"
                        for index in range(MAX_CONTACT_VALUES_PER_CANDIDATE + 1)
                    )
                }
            ],
        }
        _apply_contact_privacy(session, [candidate])
        assert candidate["suppressed"] is True
        assert candidate["person_name"] is None
        assert candidate["evidence"] == []
        assert candidate["category"] == "asset_operator"
        assert "hidden@example.test" not in str(candidate).casefold()


def test_privacy_metadata_does_not_consume_candidate_contact_budget(contact_db):
    from gridlens.intelligence.buying_chain import (
        MAX_CONTACT_VALUES_PER_CANDIDATE,
        _apply_contact_privacy,
    )

    with contact_db() as session:
        candidate = {
            "id": uuid4(),
            "person_name": "Synthetic Person",
            "title": "Synthetic Role",
            "public_contacts": [],
            "reported_contacts": [],
            "correction_history": [],
            "evidence": [],
            "metadata": {
                "observed_at": [
                    f"512-555-{index:04d}" for index in range(MAX_CONTACT_VALUES_PER_CANDIDATE + 1)
                ],
                "content_hash": "7" * 64,
                "version": "512-555-0199",
            },
        }
        _apply_contact_privacy(session, [candidate])
        assert candidate.get("suppressed") is True


def test_extraction_location_is_scanned_and_redacted(contact_db):
    from gridlens.intelligence.buying_chain import _apply_contact_privacy

    with contact_db() as session:
        _company, project, claim, source = _seed_published_contact(session)
        claim.entity_key = "privacy-location"
        claim.title = "Project Operations"
        claim.citations = []
        session.flush()
        key = global_method_suppression_key("email", "hidden@example.test")
        record_contact_suppression(
            session,
            scope="method",
            subject_key=key,
            action="suppress",
            expected_version=0,
            reason="privacy request",
            actor="privacy-ops",
            idempotency_key="provenance-email-hide",
        )
        candidate = {
            "id": claim.id,
            "person_name": "Avery Example",
            "title": "Project Operations",
            "public_contacts": [],
            "reported_contacts": [],
            "correction_history": [],
            "evidence": [{"extraction_location": "Heading: hidden@example.test"}],
        }
        _apply_contact_privacy(session, [candidate])
        assert "hidden@example.test" not in str(candidate).casefold()
        assert "[redacted]" in candidate["evidence"][0]["extraction_location"]


def test_phone_scanner_keeps_international_and_nanp_matches_on_same_line(contact_db):
    from gridlens.intelligence.buying_chain import _apply_contact_privacy

    with contact_db() as session:
        _company, project, claim, _source = _seed_published_contact(session)
        claim.entity_key = "privacy-phone"
        claim.citations = []
        session.flush()
        key = global_method_suppression_key("phone", "+44 20 7946 0958")
        record_contact_suppression(
            session,
            scope="method",
            subject_key=key,
            action="suppress",
            expected_version=0,
            reason="privacy request",
            actor="privacy-ops",
            idempotency_key="uk-phone-hide",
        )
        candidate = {
            "id": claim.id,
            "person_name": "Avery Example",
            "title": "Project Operations",
            "public_contacts": [],
            "reported_contacts": [],
            "correction_history": [],
            "evidence": [{"quote": "UK +44 20 7946 0958; US 512-555-0100"}],
        }
        _apply_contact_privacy(session, [candidate])
        quote = candidate["evidence"][0]["quote"]
        assert "+44 20 7946 0958" not in quote
        assert "512-555-0100" in quote


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
