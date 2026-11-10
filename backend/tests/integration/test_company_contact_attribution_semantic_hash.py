"""Retained native contact facts bind semantic and raw evidence versions separately."""

from datetime import UTC, date, datetime
from hashlib import sha256
from uuid import UUID

import pytest
from db_reset import reset_test_database
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.buying_chain import buying_chain_view, enrich_buying_chain
from gridlens.persistence.models import (
    BuyingChainClaim,
    BuyingChainEvidence,
    BuyingChainIdentityLink,
    BuyingChainRun,
    Evidence,
    Interpretation,
    Observation,
    PersonIdentity,
    PowerNeed,
    Project,
    Source,
)
from gridlens.settings import settings

NOW = datetime(2026, 11, 8, 12, tzinfo=UTC)
TDLR_SOURCE = "texas-tdlr-tabs-data-centers"
TABS = "TABS2026026955"
NAME = "PECOS COUNTY DATA CENTER"
LOCATION = "6000 TX-18, Fort Stockton, TX 79735 (Pecos County)"
OWNER = "AMAZON DATA SERVICES, INC"
TEXT = f"""Project: {NAME} (Building B)
Location: {LOCATION}
Registered: 2026-08-04
Developer-reported start: 2026-08-01; completion: 2026-12-01
Estimated cost: $300,000,000
Type of work: New Construction
Scope: New data center building
Owner: {OWNER}
Owner contact: Jordan Smith
Owner phone: (713) 555-0100
Owner contact phone: (713) 555-0101
Owner email: not stated
Owner contact email: not stated
Unreviewed contact note: Casey Unverified can be reached at casey@acme.example or (713) 555-0198.
Design firm: M. ARTHUR GENSLER & ASSOCIATES, INC.
TABS status: Project Registered"""


@pytest.fixture
def session_factory():
    engine = create_engine(settings.test_database_url)
    reset_test_database(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


def _seed_tdlr(session, *, raw_hash_matches: bool):
    session.add(
        Source(
            id=TDLR_SOURCE,
            publisher="Texas Department of Licensing and Regulation",
            endpoint="https://www.tdlr.texas.gov/TABS/Search/SearchProjects",
            family="construction-permits",
            geography="Texas",
            industries=["data center"],
            retrieval_method="tdlr-tabs",
            health={},
        )
    )
    session.flush()
    project = Project(
        source_id=TDLR_SOURCE,
        external_id=f"TABS-{TABS}",
        name=NAME,
        location=LOCATION,
        identity_key="tdlr-split-hash-fixture",
        identity_facts={"site": LOCATION},
    )
    session.add(project)
    session.flush()
    semantic_hash = sha256(TEXT.encode()).hexdigest()
    raw_hash = sha256(b"raw retained capture differs from interpretation").hexdigest()
    url = f"https://www.tdlr.texas.gov/TABS/Search/Project/{TABS}"
    observation = Observation(
        source_id=TDLR_SOURCE,
        external_id=project.external_id,
        title=f"{NAME} — TDLR TABS {TABS}",
        url=url,
        abstract=TEXT,
        published_at=None,
        content_hash=semantic_hash,
    )
    session.add(observation)
    session.flush()
    evidence = Evidence(
        observation_id=observation.id,
        title=observation.title,
        abstract=TEXT,
        url=url,
        content_hash=raw_hash,
        published_at=None,
        observed_at=NOW,
        event_date=date(2026, 8, 4),
        event_date_label="Registered with TDLR (Architectural Barriers)",
        extraction_location="TDLR TABS project details page",
    )
    assessed_evidence_hash = (
        raw_hash if raw_hash_matches else sha256(b"changed raw source").hexdigest()
    )
    assessment = {
        "semantic_hash": semantic_hash,
        "evidence_hash": assessed_evidence_hash,
        "decision": "accepted",
        "project_identity_key": project.identity_key,
        "subject": project.name,
        "location": project.location,
        "power_activity": "construction",
        "admission_status": "admitted",
    }
    session.add_all(
        [
            evidence,
            Interpretation(
                observation_id=observation.id,
                content_hash=semantic_hash,
                evaluator_version="tdlr-tabs-data-center-v1",
                status="accepted",
                assessment=assessment,
            ),
            PowerNeed(
                project_id=project.id,
                activity_key="construction",
                tier="Signal",
                rationale="Current accepted TDLR registration fixture.",
            ),
        ]
    )
    session.flush()
    return project


@pytest.mark.parametrize("raw_hash_matches", [True, False])
def test_retained_tdlr_contact_requires_split_semantic_and_raw_hash_bindings(
    session_factory, raw_hash_matches
):
    with session_factory.begin() as session:
        project = _seed_tdlr(session, raw_hash_matches=raw_hash_matches)
        view = enrich_buying_chain(session, project.id, retained_only=True, now=NOW)

        owner = next(
            (
                item
                for item in view["candidates"]
                if item["organization"] == OWNER and item["person_name"] is None
            ),
            None,
        )
        if raw_hash_matches:
            assert owner is not None
            assert any(
                contact["kind"] == "phone" and contact["value"] == "(713) 555-0100"
                for contact in owner["public_contacts"]
            )
            no_identity_ids = buying_chain_view(
                session, project.id, now=NOW, include_identity_ids=False
            )
            no_id_owner = next(
                item
                for item in no_identity_ids["candidates"]
                if item["organization"] == OWNER and item["person_name"] is None
            )
            assert "company_identity_id" not in no_id_owner
            assert any(
                contact["kind"] == "phone" and contact["value"] == "(713) 555-0100"
                for contact in no_id_owner["public_contacts"]
            )

            claim = session.get(BuyingChainClaim, no_id_owner["id"])
            assert claim is not None
            claim.public_contacts = [{**claim.public_contacts[0], "value": "(713) 999-0100"}]
            session.flush()
            mismatched = buying_chain_view(session, project.id, now=NOW, include_identity_ids=False)
            mismatched_owner = next(
                item
                for item in mismatched["candidates"]
                if item["organization"] == OWNER and item["person_name"] is None
            )
            assert mismatched_owner["public_contacts"] == []
        else:
            assert owner is None


def test_project_state_redacts_rejected_mixed_contact_text_and_keeps_native_phone(
    session_factory,
):
    from copy import deepcopy

    from gridlens.intelligence.project_state import project_state

    with session_factory.begin() as session:
        project = _seed_tdlr(session, raw_hash_matches=True)
        view = enrich_buying_chain(session, project.id, retained_only=True, now=NOW)
        owner = next(
            item
            for item in view["candidates"]
            if item["organization"] == OWNER and item["person_name"] is None
        )
        owner_claim = session.get(BuyingChainClaim, UUID(str(owner["id"])))
        assert owner_claim is not None
        source = session.get(BuyingChainEvidence, UUID(str(owner["evidence"][0]["id"])))
        assert source is not None and "casey@acme.example" in source.excerpt
        note = next(line for line in source.excerpt.splitlines() if line.startswith("Unreviewed"))
        owner_claim.citations = [
            *owner_claim.citations,
            {
                "evidence_id": str(source.id),
                "url": source.url,
                "quote": note,
                "supports": "organization_category",
            },
        ]
        raw_owner_citations = deepcopy(owner_claim.citations)
        raw_source_excerpt = source.excerpt

        company_id = UUID(str(owner["company_identity_id"]))
        person = PersonIdentity()
        session.add(person)
        session.flush()
        fake_claim = BuyingChainClaim(
            project_id=project.id,
            entity_key="unreviewed-casey-contact",
            fingerprint=sha256(b"unreviewed-casey-contact").hexdigest(),
            policy_version="synthetic-unreviewed-contact-v1",
            organization=OWNER,
            person_name="Casey Unverified",
            title="Project Director",
            category="owner",
            organization_relationship="DIRECT",
            person_organization_relationship="EMPLOYEE",
            person_project_relationship="PROJECT_CONTACT",
            evidence_strength="high",
            reason="Unreviewed source note; this contact must not be published.",
            citations=[
                {
                    "evidence_id": str(source.id),
                    "url": source.url,
                    "quote": note,
                    "supports": support,
                }
                for support in (
                    "organization_person_role",
                    "person_project_assignment",
                    "public_contact",
                    "permit_listed_contact",
                )
            ],
            public_contacts=[
                {
                    "kind": "email",
                    "value": "casey@acme.example",
                    "source_url": source.url,
                    "quote": note,
                },
                {
                    "kind": "phone",
                    "value": "(713) 555-0198",
                    "source_url": source.url,
                    "quote": note,
                },
            ],
            observed_at=NOW,
        )
        session.add(fake_claim)
        session.flush()
        session.add_all(
            [
                BuyingChainIdentityLink(
                    claim_id=fake_claim.id,
                    entity_type="company",
                    company_identity_id=company_id,
                    reason="Same source company, unverified contact claim.",
                    basis="attributed_review",
                    reviewed_by="test fixture",
                    source_evidence_id=source.id,
                    source_version_hash=source.content_hash,
                    state="current",
                ),
                BuyingChainIdentityLink(
                    claim_id=fake_claim.id,
                    entity_type="person",
                    person_identity_id=person.id,
                    reason="Unreviewed identity for the privacy regression.",
                    basis="attributed_review",
                    reviewed_by="test fixture",
                    source_evidence_id=source.id,
                    source_version_hash=source.content_hash,
                    state="current",
                ),
            ]
        )
        active_run = session.scalar(
            select(BuyingChainRun)
            .where(BuyingChainRun.project_id == project.id)
            .order_by(BuyingChainRun.created_at.desc(), BuyingChainRun.id.desc())
        )
        assert active_run is not None
        active_run.claim_ids = [*active_run.claim_ids, str(fake_claim.id)]
        session.flush()

        public_state = project_state(session, project.id, today=NOW.date())
        assert public_state is not None
        public_owner = next(
            role
            for role in public_state["organizations_and_roles"]
            if role["organization"] == OWNER and role["person"] is None
        )
        serialized = repr(public_state["organizations_and_roles"])
        for token in (
            "Casey Unverified",
            "Project Director",
            "casey@acme.example",
            "(713) 555-0198",
        ):
            assert token not in serialized
        assert any(
            contact["kind"] == "phone" and contact["value"] == "(713) 555-0100"
            for contact in public_owner["public_contacts"]
        )
        assert any(
            citation["supports"] == "public_contact"
            and citation["quote"] == "Owner phone: (713) 555-0100"
            for citation in public_owner["citations"]
        )
        assert any(
            citation["supports"] == "organization_category" and "[redacted]" in citation["quote"]
            for citation in public_owner["citations"]
        )
        assert owner_claim.citations == raw_owner_citations
        assert source.excerpt == raw_source_excerpt
        assert fake_claim.public_contacts[0]["value"] == "casey@acme.example"
