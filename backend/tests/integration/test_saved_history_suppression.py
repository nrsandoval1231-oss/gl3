"""PostgreSQL regressions for privacy controls on immutable saved snapshots."""

from datetime import UTC, datetime
from importlib import import_module
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.contact_suppressions import (
    company_suppression_key,
    global_method_suppression_key,
    global_person_suppression_key,
    record_contact_suppression,
)
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    BuyingChainClaim,
    BuyingChainEvidence,
    BuyingChainIdentityLink,
    CompanyIdentity,
    PersonIdentity,
    Project,
    Pursuit,
    Source,
)
from gridlens.security import token_for
from gridlens.settings import settings

api = import_module("gridlens.api.app")


@pytest.fixture
def saved_history_db(monkeypatch):
    if not settings.test_database_url:
        pytest.skip("TEST_DATABASE_URL required for saved-history privacy integration")
    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and target.database.endswith("_test")
    assert "corpus" not in target.database.casefold()
    assert (target.host, target.port, target.database) != (
        application.host,
        application.port,
        application.database,
    ), "TEST_DATABASE_URL must differ from the application database"

    schema = "saved_history_privacy_" + uuid4().hex
    admin = create_engine(settings.test_database_url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        settings.test_database_url,
        connect_args={"options": f"-csearch_path={schema}"},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(api, "SessionLocal", factory)
    try:
        yield factory
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def _contact(claim_id: str, name: str, value: str) -> dict:
    return {
        "claim_id": claim_id,
        "company": "Former project member",
        "name": name,
        "title": "Project director",
        "role": "Verified project responsibility",
        "responsibility": "Verified project responsibility",
        "methods": [{"kind": "email", "value": value}],
        "sources": [],
    }


def _saved_card(project_id: str, related_project_ids: list[str], contacts: list[dict]) -> dict:
    return {
        "id": str(uuid4()),
        "project_id": project_id,
        "related_project_ids": related_project_ids,
        "name": "Synthetic grouped project",
        "location": "100 Test Way, Austin, TX",
        "tier": "Signal",
        "activity": "construction",
        "industry": "unknown",
        "disposition": "RESEARCH",
        "reason": "Synthetic saved snapshot",
        "required_mw": None,
        "start_window": None,
        "duration": None,
        "supply": "Unknown",
        "stage": {"stage": "Unknown", "date": None, "source_url": None, "evidence_id": None},
        "organization": "Former project member",
        "organization_role": "owner",
        "contacts": [
            {
                "organization": contact["company"],
                "person": contact["name"],
                "role": contact["role"],
                "kind": method["kind"],
                "value": method["value"],
                "source_url": "https://example.test/source",
            }
            for contact in contacts
            for method in contact["methods"]
        ],
        "hypothesis": None,
        "next_question": "Who owns this project?",
        "next_action": "Verify project contact",
        "conflict_state": None,
        "input_hash": "f" * 64,
        "intelligence_card": {
            "need_id": str(uuid4()),
            "project_id": project_id,
            "input_fingerprint": "a" * 64,
            "qualification": "Signal",
            "disposition": "RESEARCH",
            "fields": [],
            "contacts": contacts,
            "next_contact_path": "Synthetic test",
            "next_action": "Verify contact",
            "research_gaps": [],
            "completeness": {},
            "evidence": [],
            "research_enabled": False,
        },
    }


def test_saved_history_page_and_detail_apply_suppressions_to_historical_group_members(
    saved_history_db,
):
    """Suppressed historical identities disappear while unrelated grouped claims remain."""
    now = datetime.now(UTC)
    with saved_history_db.begin() as session:
        source = Source(
            id="saved-history-privacy-source",
            publisher="Synthetic privacy fixture",
            endpoint="https://example.test/source",
            family="construction-permits",
            geography="Test",
            industries=[],
            retrieval_method="fixture",
            health={},
        )
        session.add(source)
        session.flush()
        project_a = Project(
            identity_key=f"saved-history-a-{uuid4()}",
            name="Synthetic grouped project A",
            location="100 Test Way, Austin, TX",
            source_id=source.id,
            external_id="saved-history-a",
        )
        project_b = Project(
            identity_key=f"saved-history-b-{uuid4()}",
            name="Synthetic former member project B",
            location="200 Test Way, Austin, TX",
            source_id=source.id,
            external_id="saved-history-b",
        )
        project_c = Project(
            identity_key=f"saved-history-c-{uuid4()}",
            name="Synthetic outside-scope project C",
            location="300 Test Way, Austin, TX",
            source_id=source.id,
            external_id="saved-history-c",
        )
        session.add_all([project_a, project_b, project_c])
        session.flush()

        company_suppressed = CompanyIdentity()
        person_suppressed = PersonIdentity()
        method_suppressed = PersonIdentity()
        unrelated_company = CompanyIdentity()
        session.add_all(
            [company_suppressed, person_suppressed, method_suppressed, unrelated_company]
        )
        session.flush()

        specs = [
            (
                "Company hidden",
                "company-hidden@example.test",
                company_suppressed,
                "company",
                project_b,
            ),
            ("Person hidden", "person-hidden@example.test", person_suppressed, "person", project_b),
            ("Method hidden", "method-hidden@example.test", method_suppressed, "person", project_b),
            ("Visible control", "visible@example.test", unrelated_company, "company", project_b),
            # A stale snapshot may contain a forged/out-of-scope claim ID. The
            # matching stable identity is suppressed, but DB project scope must
            # prevent that unrelated project claim from being treated as a
            # former member of this saved group.
            (
                "External scoped contact",
                "external-scope@example.test",
                company_suppressed,
                "company",
                project_c,
            ),
        ]
        contacts = []
        for index, (name, email, identity, entity_type, claim_project) in enumerate(specs):
            claim = BuyingChainClaim(
                project_id=claim_project.id,
                entity_key=f"synthetic-entity-{index}",
                fingerprint=f"{index + 1:064x}",
                policy_version="fixture-v1",
                organization="Former project member",
                person_name=name,
                title="Project director",
                category="owner",
                organization_relationship="owner",
                person_organization_relationship="employee",
                person_project_relationship="project_contact",
                evidence_strength="high",
                reason="Synthetic historical identity-link fixture.",
                citations=[],
                public_contacts=[{"kind": "email", "value": email}],
                observed_at=now,
            )
            session.add(claim)
            session.flush()
            evidence = BuyingChainEvidence(
                project_id=claim_project.id,
                url=f"https://example.test/claim/{claim.id}",
                title="Synthetic historical identity source",
                excerpt="Synthetic identity and contact evidence.",
                content_hash=f"{index + 11:064x}",
                extraction_location="Fixture paragraph 1",
                observed_at=now,
                last_seen_at=now,
                project_match_reason="Synthetic grouped former-member project fixture",
            )
            session.add(evidence)
            session.flush()
            # These are deliberately former links: a saved snapshot must still
            # resolve stable identity after a link stops being current.
            session.add(
                BuyingChainIdentityLink(
                    claim_id=claim.id,
                    entity_type=entity_type,
                    company_identity_id=identity.id if entity_type == "company" else None,
                    person_identity_id=identity.id if entity_type == "person" else None,
                    reason="Synthetic former membership history",
                    basis="strong_identifier",
                    source_evidence_id=evidence.id,
                    source_version_hash="e" * 64,
                    state="superseded",
                    superseded_at=now,
                )
            )
            contacts.append(_contact(str(claim.id), name, email))
        contacts[-1]["company"] = "External scoped company"

        pursuit = Pursuit(
            identity_key=f"commercial-need:{uuid4()}",
            project_id=project_a.id,
            project_ids=[str(project_a.id), str(project_b.id)],
            snapshot={
                "commercial_triage": {
                    "need_id": str(uuid4()),
                    "saved_at": now.isoformat(),
                    "disposition": "RESEARCH",
                    "saved_card": _saved_card(
                        str(project_a.id), [str(project_a.id), str(project_b.id)], contacts
                    ),
                    "versions": [
                        {
                            "version": 1,
                            "disposition": "RESEARCH",
                            "input_hash": "f" * 64,
                            "saved_card": _saved_card(
                                str(project_a.id), [str(project_a.id), str(project_b.id)], contacts
                            ),
                        }
                    ],
                }
            },
            research_status="complete",
        )
        session.add(pursuit)
        record_contact_suppression(
            session,
            scope="company",
            subject_key=company_suppression_key(company_suppressed.id),
            action="suppress",
            expected_version=0,
            reason="Synthetic company privacy request",
            actor="integration-test",
            idempotency_key="saved-history-company",
        )
        record_contact_suppression(
            session,
            scope="person",
            subject_key=global_person_suppression_key(person_suppressed.id),
            action="suppress",
            expected_version=0,
            reason="Synthetic person privacy request",
            actor="integration-test",
            idempotency_key="saved-history-person",
        )
        record_contact_suppression(
            session,
            scope="method",
            subject_key=global_method_suppression_key("email", "method-hidden@example.test"),
            action="suppress",
            expected_version=0,
            reason="Synthetic contact method privacy request",
            actor="integration-test",
            idempotency_key="saved-history-method",
        )
        pursuit_id = pursuit.id
        stored_snapshot = pursuit.snapshot

    with TestClient(api.app, base_url="https://testserver") as client:
        client.cookies.set("gridlens_session", token_for(int(now.timestamp()) + 3600))
        page = client.get("/api/commercial/triage/history")
        detail = client.get(f"/api/commercial/triage/history/{pursuit_id}")

    assert page.status_code == 200, page.text
    assert detail.status_code == 200, detail.text
    page_item = next(item for item in page.json()["items"] if item["pursuit_id"] == str(pursuit_id))
    detail_item = detail.json()
    for item in (page_item, detail_item):
        cards = [item["saved_card"]]
        cards.extend(version["saved_card"] for version in item["versions"])
        for card in cards:
            assert card is not None
            assert "company-hidden@example.test" not in str(card)
            assert "person-hidden@example.test" not in str(card)
            assert "method-hidden@example.test" not in str(card)
            assert "visible@example.test" in str(card)
            # This pointer belongs to project C, outside the authoritative A/B
            # saved group. Fail closed instead of importing its identity or
            # publishing an assertion whose project provenance cannot resolve.
            assert "external-scope@example.test" not in str(card)
            # Redaction is read-time only and must preserve the recorded
            # qualification, disposition and input identity.
            assert card["tier"] == "Signal"
            assert card["disposition"] == "RESEARCH"
            assert card["input_hash"] == "f" * 64

    with saved_history_db() as session:
        assert session.get(Pursuit, pursuit_id).snapshot == stored_snapshot
