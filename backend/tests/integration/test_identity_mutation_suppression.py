"""Automatic identity mutation must preserve every contact suppression alias."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from db_reset import reset_test_database
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.contact_suppressions import (
    company_suppression_key,
    global_method_suppression_key,
    global_person_suppression_key,
    person_suppression_key,
    record_contact_suppression,
)
from gridlens.intelligence.identity_reconciliation import _automatic_identity_mutation_allowed
from gridlens.persistence.models import (
    BuyingChainClaim,
    BuyingChainEvidence,
    BuyingChainIdentityLink,
    CompanyIdentity,
    PersonIdentity,
    Project,
    Source,
)
from gridlens.persistence.suppression_models import ContactSuppression
from gridlens.settings import settings

NOW = datetime(2026, 11, 8, 12, tzinfo=UTC)


@pytest.fixture
def factory():
    engine = create_engine(settings.test_database_url)
    reset_test_database(engine)
    maker = sessionmaker(engine, expire_on_commit=False)
    with maker.begin() as session:
        session.add(
            Source(
                id="identity-mutation-suppression-test",
                publisher="Synthetic test source",
                endpoint="https://example.test/identity",
                family="news",
                geography="US",
                industries=[],
                retrieval_method="test",
                health={},
            )
        )
    try:
        yield maker
    finally:
        engine.dispose()


def _seed_lineage(session, suffix: str):
    project = Project(
        source_id="identity-mutation-suppression-test",
        external_id=suffix,
        name=f"{suffix} Data Center",
        location="Austin, TX",
        identity_key=suffix,
        identity_facts={},
    )
    session.add(project)
    session.flush()
    evidence = BuyingChainEvidence(
        project_id=project.id,
        url=f"https://example.test/{suffix}",
        title="Synthetic current evidence",
        excerpt="Acme is named on the project.",
        content_hash=uuid4().hex,
        extraction_location="Synthetic fixture",
        observed_at=NOW,
        last_seen_at=NOW,
        project_match_reason="Synthetic isolated identity fixture.",
    )
    session.add(evidence)
    session.flush()
    claim = BuyingChainClaim(
        project_id=project.id,
        entity_key=f"{suffix}:acme:jordan",
        fingerprint=uuid4().hex,
        policy_version="identity-mutation-test-v1",
        organization="Acme LLC",
        person_name="Jordan Smith",
        title="Project Director",
        category="owner_developer",
        organization_relationship="DIRECT",
        person_organization_relationship="DIRECT",
        person_project_relationship="DIRECT",
        evidence_strength="High",
        reason="Synthetic current identity test claim.",
        citations=[],
        public_contacts=[],
        observed_at=NOW,
    )
    session.add(claim)
    old_company, historical_alias, target_company, person = (
        CompanyIdentity(),
        CompanyIdentity(),
        CompanyIdentity(),
        PersonIdentity(),
    )
    session.add_all([old_company, historical_alias, target_company, person])
    session.flush()
    session.add_all(
        [
            BuyingChainIdentityLink(
                claim_id=claim.id,
                entity_type="company",
                company_identity_id=old_company.id,
                reason="Synthetic current company link.",
                basis="project_scoped",
                source_evidence_id=evidence.id,
                source_version_hash=evidence.content_hash,
                state="current",
            ),
            BuyingChainIdentityLink(
                claim_id=claim.id,
                entity_type="company",
                company_identity_id=historical_alias.id,
                reason="Synthetic historical company alias.",
                basis="project_scoped",
                source_evidence_id=evidence.id,
                source_version_hash=evidence.content_hash,
                state="superseded",
            ),
            BuyingChainIdentityLink(
                claim_id=claim.id,
                entity_type="person",
                person_identity_id=person.id,
                reason="Synthetic current person link.",
                basis="project_scoped",
                source_evidence_id=evidence.id,
                source_version_hash=evidence.content_hash,
                state="current",
            ),
        ]
    )
    session.flush()
    return claim, old_company.id, historical_alias.id, target_company.id, person.id


def _suppress(session, scope: str, key: str, idem: str):
    return record_contact_suppression(
        session,
        scope=scope,
        subject_key=key,
        action="suppress",
        expected_version=0,
        reason="Synthetic alias preservation regression.",
        actor="test",
        idempotency_key=idem,
    )


@pytest.mark.parametrize(
    "suppression_scope",
    [
        "company_old",
        "company_history",
        "company_target",
        "person_old_company",
        "person_target_company",
        "global_person",
        "corrupt_global_person",
    ],
)
def test_automatic_identity_mutation_vetoes_old_target_and_historical_controls(
    factory, suppression_scope
):
    with factory.begin() as session:
        claim, old_id, historical_id, target_id, person_id = _seed_lineage(session, "alpha")
        keys = {
            "company_old": ("company", company_suppression_key(old_id)),
            "company_history": ("company", company_suppression_key(historical_id)),
            "company_target": ("company", company_suppression_key(target_id)),
            "person_old_company": ("person", person_suppression_key(old_id, "Jordan Smith")),
            "person_target_company": (
                "person",
                person_suppression_key(target_id, "Jordan Smith"),
            ),
            "global_person": ("person", global_person_suppression_key(person_id)),
            "corrupt_global_person": ("person", global_person_suppression_key(person_id)),
        }
        scope, key = keys[suppression_scope]
        if suppression_scope == "corrupt_global_person":
            session.add(
                ContactSuppression(
                    scope=scope,
                    subject_key=key,
                    expected_version=1,
                    version=2,
                    action="suppress",
                    reason="Synthetic malformed sequence.",
                    actor="test",
                    idempotency_key="corrupt-ledger-sequence",
                )
            )
        else:
            _suppress(session, scope, key, suppression_scope)
        session.flush()

        assert not _automatic_identity_mutation_allowed(
            session, [claim], proposed_company_ids={target_id}
        )


def test_unrelated_account_method_control_does_not_block_new_identity_lineage(factory):
    with factory.begin() as session:
        claim, _old_id, _historical_id, target_id, _person_id = _seed_lineage(session, "alpha")
        _other_claim, _other_old, _other_history, unrelated_id, _other_person = _seed_lineage(
            session, "unrelated"
        )
        _suppress(
            session,
            "method",
            global_method_suppression_key("phone", "+1 512 555 0100"),
            "unrelated-method-control",
        )
        _suppress(
            session,
            "company",
            company_suppression_key(unrelated_id),
            "unrelated-company-control",
        )

        assert _automatic_identity_mutation_allowed(
            session, [claim], proposed_company_ids={target_id}
        )
