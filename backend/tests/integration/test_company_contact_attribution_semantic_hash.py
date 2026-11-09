"""Retained native contact facts bind semantic and raw evidence versions separately."""

from datetime import UTC, date, datetime
from hashlib import sha256

import pytest
from db_reset import reset_test_database
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.buying_chain import buying_chain_view, enrich_buying_chain
from gridlens.persistence.models import (
    BuyingChainClaim,
    Evidence,
    Interpretation,
    Observation,
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
