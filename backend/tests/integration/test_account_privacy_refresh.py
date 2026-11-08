from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from gridlens.intelligence.contact_suppressions import (
    method_suppression_key,
    person_suppression_key,
)
from gridlens.intelligence.customer_results import group_open, groups
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

ALIAS = "Verified Privacy Refresh Alias"
METHOD = "mailto:private@example.invalid"
PERSON = "Private Person"


def _attach_test_contacts(row, company_id, person_id):
    row.compact = {
        **row.compact,
        "project_metadata": {
            **row.compact.get("project_metadata", {}),
            "sector": "oil_gas",
            "operator": "Synthetic Primary Operator",
            "oil_gas": {"operator_number": "912345"},
        },
        "contact_actions": [
            {
                "kind": "email",
                "href": METHOD,
                "company": "Synthetic Primary Operator",
                "name": PERSON,
                "company_identity_id": str(company_id),
                "person_identity_id": str(person_id),
                "claim_id": "synthetic-private-claim",
            }
        ],
        "contact_people": [
            {
                "record_type": "contact_person",
                "company_identity_id": str(company_id),
                "person_identity_id": str(person_id),
                "company": "Synthetic Primary Operator",
                "name": PERSON,
                "role": "operations",
            }
        ],
    }


def _public_contact_records(project):
    records = [*project["contact"], *project["contact_people"]]
    for need in project["needs"]:
        records.extend(need.get("contact_actions", []))
        records.extend(need.get("contact_people", []))
    for record in records:
        assert "company_identity_id" not in record
        assert "person_identity_id" not in record
        assert "claim_id" not in record
    return records


def _shortlist_assessor(session, generation):
    rows = (
        session.execute(
            select(
                BrowseRow.need_id, BrowseRow.project_id, BrowseRow.summary, BrowseRow.compact
            ).where(BrowseRow.generation_id == generation.id)
        )
        .mappings()
        .all()
    )
    need_ids = [row["need_id"] for row in rows]
    return {
        "rows": rows,
        "assessments": {
            str(need_id): {
                "eligible": True,
                "priority": 97,
                "duplicate_key": None,
                "reasons": ["synthetic integration fixture"],
                "evidence_refs": [],
            }
            for need_id in need_ids
        },
        "eligible_need_ids": need_ids,
        "priority_by_need": {need_id: 97 for need_id in need_ids},
        "duplicate_project_map": {},
        "jev_map_digest": "synthetic-privacy-refresh-digest",
    }


def _add_snapshot_membership(session, generation_id, project_id, company_id):
    existing = session.scalar(
        select(BrowseCustomerMembership.company_identity_id).where(
            BrowseCustomerMembership.generation_id == generation_id,
            BrowseCustomerMembership.project_id == project_id,
        )
    )
    if existing is not None:
        assert existing == company_id
        return
    session.add(
        BrowseCustomerMembership(
            generation_id=generation_id,
            company_identity_id=company_id,
            project_id=project_id,
            organization_name="Synthetic Primary Operator",
            role="asset_operator",
        )
    )


def test_alias_contact_suppressions_survive_rebuild_and_shortlist_featured_read(
    saved_db, monkeypatch
):
    from test_saved_browse import seed

    need_id = seed(saved_db, count=1, histories=1)[0]
    now = datetime.now(UTC)
    company_id, person_id = uuid4(), uuid4()
    with saved_db.begin() as session:
        project_id = session.get(PowerNeed, need_id).project_id
        session.add(CompanyIdentity(id=company_id, rrc_operator_number="912345"))
        evidence = BuyingChainEvidence(
            project_id=project_id,
            url="https://example.test/operator/privacy-refresh",
            title="Synthetic operator alias citation",
            excerpt=f"Synthetic Primary Operator is also known as {ALIAS}.",
            content_hash="a" * 64,
            extraction_location="synthetic account privacy fixture",
            observed_at=now,
            last_seen_at=now,
            project_match_reason="synthetic current project binding",
        )
        session.add(evidence)
        session.flush()
        claim = BuyingChainClaim(
            project_id=project_id,
            entity_key="synthetic-primary-operator",
            fingerprint="b" * 64,
            policy_version="test-current-view",
            organization="Synthetic Primary Operator",
            person_name=None,
            title="Operator",
            category="asset_operator",
            organization_relationship="DIRECT",
            person_organization_relationship="unknown",
            person_project_relationship="unknown",
            evidence_strength="high",
            reason="Synthetic current primary operator",
            citations=[
                {
                    "evidence_id": str(evidence.id),
                    "url": evidence.url,
                    "quote": evidence.excerpt,
                    "supports": "project_organization",
                }
            ],
            public_contacts=[],
            observed_at=now,
        )
        session.add(claim)
        session.flush()
        session.add(
            BuyingChainIdentityLink(
                claim_id=claim.id,
                entity_type="company",
                company_identity_id=company_id,
                person_identity_id=None,
                reason="Synthetic current primary identity",
                source_evidence_id=evidence.id,
                source_version_hash=evidence.content_hash,
                state="current",
            )
        )
        session.add(
            IdentityIdentifier(
                entity_type="company",
                company_identity_id=company_id,
                person_identity_id=None,
                identifier_type="alias",
                normalized_value=ALIAS.casefold(),
                source_evidence_id=evidence.id,
                source_version_hash=evidence.content_hash,
                reason="Current cited synthetic alias",
            )
        )
        session.add(
            BuyingChainRun(
                project_id=project_id,
                input_hash="c" * 64,
                evidence_ids=[str(evidence.id)],
                claim_ids=[str(claim.id)],
                policy_version="test-current-view",
                status="complete",
                documents_checked=1,
                candidates_added=1,
                unresolved=[],
                created_at=now,
            )
        )

    assert rebuild(saved_db)["status"] == "published"
    with saved_db.begin() as session:
        generation = current_generation(session)
        row = session.scalar(
            select(BrowseRow).where(
                BrowseRow.generation_id == generation.id,
                BrowseRow.project_id == project_id,
            )
        )
        _attach_test_contacts(row, company_id, person_id)
        _add_snapshot_membership(session, generation.id, project_id, company_id)
    from gridlens.intelligence import account_shortlist

    monkeypatch.setattr(account_shortlist, "assess_generation", _shortlist_assessor)

    def alias_open(session):
        page = groups(session, search=ALIAS, sector="all", shortlist=True)
        assert page["total"] == 1
        opened = group_open(
            session,
            page["items"][0]["id"],
            search=ALIAS,
            sector="all",
            shortlist=True,
        )
        assert opened["group"]["featured_project"] is not None
        assert opened["projects"]["items"]
        return opened

    with saved_db() as session:
        opened = alias_open(session)
        featured = opened["group"]["featured_project"]
        assert any(record.get("href") == METHOD for record in _public_contact_records(featured))
        assert any(record.get("name") == PERSON for record in _public_contact_records(featured))
        child = opened["projects"]["items"][0]
        assert any(record.get("href") == METHOD for record in _public_contact_records(child))

    with saved_db.begin() as session:
        session.add(
            ContactSuppression(
                scope="method",
                subject_key=method_suppression_key(company_id, PERSON, "email", METHOD),
                expected_version=0,
                version=1,
                action="suppress",
                reason="synthetic alias method privacy refresh",
                actor="test",
                idempotency_key="account-privacy-refresh-method",
            )
        )
    with saved_db() as session:
        opened = alias_open(session)
        featured = opened["group"]["featured_project"]
        featured_records = _public_contact_records(featured)
        assert not any(record.get("href") == METHOD for record in featured_records)
        assert any(record.get("name") == PERSON for record in featured_records)

    with saved_db.begin() as session:
        session.add(
            ContactSuppression(
                scope="person",
                subject_key=person_suppression_key(company_id, PERSON),
                expected_version=0,
                version=1,
                action="suppress",
                reason="synthetic alias person privacy refresh",
                actor="test",
                idempotency_key="account-privacy-refresh-person",
            )
        )
    with saved_db() as session:
        opened = alias_open(session)
        assert not _public_contact_records(opened["group"]["featured_project"])

    previous_generation_id = opened["generation"]
    assert rebuild(saved_db)["status"] == "published"
    with saved_db.begin() as session:
        generation = current_generation(session)
        assert str(generation.id) != previous_generation_id
        row = session.scalar(
            select(BrowseRow).where(
                BrowseRow.generation_id == generation.id,
                BrowseRow.project_id == project_id,
            )
        )
        _attach_test_contacts(row, company_id, person_id)
        _add_snapshot_membership(session, generation.id, project_id, company_id)
    with saved_db() as session:
        opened = alias_open(session)
        assert not _public_contact_records(opened["group"]["featured_project"])
        assert not _public_contact_records(opened["projects"]["items"][0])
