from collections import Counter
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from importlib import import_module
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.domain.opportunity_intelligence import contact_projection
from gridlens.ingestion.adapters.buying_chain_public import PublicDocument, parse_document
from gridlens.intelligence.buying_chain import (
    _attach_identity_ids,
    buying_chain_view,
    buying_chain_views,
    enrich_buying_chain,
)
from gridlens.intelligence.buying_chain_corrections import (
    _has_current_semantic_support,
    _ordered_correction_chain,
    correct_buying_chain_claim,
    overlay_corrections,
)
from gridlens.intelligence.identity_reconciliation import (
    current_claim_identity_links,
    ensure_project_scoped_identity_links,
    link_claim_to_identity,
    reconcile_claim_identity,
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
    IdentityIdentifier,
    Interpretation,
    NeedObservation,
    Observation,
    PersonIdentity,
    PowerNeed,
    Project,
    Source,
)
from gridlens.security import token_for
from gridlens.settings import settings

NOW = datetime(2026, 9, 30, 12, tzinfo=UTC)
URL = "https://news.example/orion"


@pytest.fixture
def db():
    target, application = make_url(settings.test_database_url), make_url(settings.database_url)
    assert target.database.endswith("_test")
    assert target != application
    engine = create_engine(settings.test_database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(
            Source(
                id="test",
                publisher="Synthetic tests",
                endpoint=URL,
                family="news",
                geography="US",
                industries=[],
                retrieval_method="test",
                health={},
            )
        )
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


def seed(session, external_id="42", identity_key="orion", name="Orion Data Center"):
    observation = Observation(
        source_id="test",
        external_id=external_id,
        title=name,
        url=URL,
        abstract=f"{name} in Austin, TX.",
        published_at=date(2026, 9, 20),
        content_hash="a",
    )
    session.add(observation)
    session.flush()
    evidence = Evidence(
        observation_id=observation.id,
        title=observation.title,
        abstract=observation.abstract,
        url=URL,
        content_hash="a",
        published_at=observation.published_at,
        observed_at=NOW,
    )
    session.add(evidence)
    session.add(
        Interpretation(
            observation_id=observation.id,
            content_hash="a",
            status="accepted",
            assessment={
                "evidence_hash": "a",
                "decision": "accepted",
                "project_identity_key": "orion",
                "admission_status": "supplemental",
            },
        )
    )
    project = Project(
        source_id="test",
        external_id=external_id,
        name=name,
        location="Austin, TX",
        identity_key=identity_key,
        identity_facts={},
    )
    session.add(project)
    session.flush()
    session.add(
        PowerNeed(
            project_id=project.id,
            activity_key="construction",
            tier="Signal",
            rationale="Synthetic fixture",
        )
    )
    session.flush()
    return project


def source(text, *, url=URL, observed=NOW):
    return PublicDocument(url, "Orion Data Center, Austin, TX", text, date(2026, 9, 20), observed)


def counts(session):
    return [
        session.scalar(select(func.count()).select_from(model))
        for model in (BuyingChainClaim, BuyingChainEvidence, BuyingChainRun, PowerNeed, Project)
    ]


def test_replay_is_idempotent_and_never_changes_tier(db):
    with db.begin() as session:
        p = seed(session)

        def fetch(url):
            return source("Acme is the general contractor for Orion Data Center in Austin, TX.")

        first = enrich_buying_chain(session, p.id, fetcher=fetch, now=NOW)
        before = counts(session)
        second = enrich_buying_chain(session, p.id, fetcher=fetch, now=NOW + timedelta(minutes=2))
        assert first["candidates"][0]["id"] == second["candidates"][0]["id"]
        assert first["candidates"][0]["company_identity_id"]
        assert (
            first["candidates"][0]["company_identity_id"]
            == second["candidates"][0]["company_identity_id"]
        )
        assert counts(session) == before
        assert session.scalar(select(PowerNeed.tier)) == "Signal"


def test_project_scoped_identity_refresh_reuses_batched_candidate_views(db, monkeypatch):
    import gridlens.intelligence.identity_reconciliation as identity_reconciliation

    with db.begin() as session:
        project = seed(session, external_id="identity-batched")
        result = enrich_buying_chain(
            session,
            project.id,
            fetcher=lambda url: source(
                "Acme is the general contractor for Orion Data Center in Austin, TX. "
                "Alice Smith is Project Director at Acme."
            ),
            now=NOW,
        )
        claim_ids = [str(item["id"]) for item in result["candidates"]]
        assert claim_ids
        single_view_calls = []
        monkeypatch.setattr(
            identity_reconciliation,
            "buying_chain_view",
            lambda *args, **kwargs: single_view_calls.append((args, kwargs)),
        )
        ensure_project_scoped_identity_links(session, claim_ids)
        assert single_view_calls == []


def test_replay_preserves_reviewed_identity_link_on_second_current_citation(db):
    first_url = "https://acme.example/company"
    second_url = "https://acme.example/projects"
    text = "Acme is the general contractor for Orion Data Center in Austin, TX."
    documents = {
        first_url: source(text, url=first_url),
        second_url: source(text, url=second_url),
    }
    with db.begin() as session:
        project = seed(session, external_id="reviewed-second", identity_key="reviewed-second")
        result = enrich_buying_chain(
            session,
            project.id,
            source_urls=[first_url, second_url],
            fetcher=documents.__getitem__,
            now=NOW,
        )
        candidate = next(item for item in result["candidates"] if item["organization"] == "Acme")
        claim = session.get(BuyingChainClaim, candidate["id"])
        assert claim is not None
        cited_versions = [
            session.get(BuyingChainEvidence, item["id"])
            for item in candidate["evidence"]
            if item["url"] in {first_url, second_url}
        ]
        assert len(cited_versions) == 2
        auto_link = session.scalar(
            select(BuyingChainIdentityLink).where(
                BuyingChainIdentityLink.claim_id == claim.id,
                BuyingChainIdentityLink.entity_type == "company",
                BuyingChainIdentityLink.state == "current",
            )
        )
        assert auto_link is not None
        second_citation = next(item for item in cited_versions if item.url == second_url)
        assert auto_link.source_evidence_id != second_citation.id

        reviewed_identity = CompanyIdentity()
        session.add(reviewed_identity)
        session.flush()
        reviewed_identity_id = reviewed_identity.id
        reviewed_link = link_claim_to_identity(
            session,
            claim,
            "company",
            reviewed_identity.id,
            second_citation,
            "Operator reviewed the second current citation.",
            reviewed_by="operator",
        )
        claim_id = claim.id
        reviewed_link_id = reviewed_link.id
        identities_before = sorted(str(row.id) for row in session.scalars(select(CompanyIdentity)))
        links_before = [
            (
                row.id,
                row.company_identity_id,
                row.source_evidence_id,
                row.source_version_hash,
                row.state,
                row.basis,
                row.reviewed_by,
                row.reason,
                row.created_at,
                row.superseded_at,
            )
            for row in session.scalars(
                select(BuyingChainIdentityLink)
                .where(BuyingChainIdentityLink.claim_id == claim_id)
                .order_by(BuyingChainIdentityLink.created_at, BuyingChainIdentityLink.id)
            )
        ]

        replay = enrich_buying_chain(
            session,
            project.id,
            source_urls=[first_url, second_url],
            fetcher=documents.__getitem__,
            now=NOW + timedelta(minutes=2),
        )
        replayed = next(item for item in replay["candidates"] if item["id"] == claim_id)
        assert replayed["company_identity_id"] == str(reviewed_identity_id)
        assert current_claim_identity_links(session, {claim_id})[claim_id][
            "company_identity_id"
        ] == str(reviewed_identity_id)
        assert replayed["evidence"]
        identities_after = sorted(str(row.id) for row in session.scalars(select(CompanyIdentity)))
        links_after = [
            (
                row.id,
                row.company_identity_id,
                row.source_evidence_id,
                row.source_version_hash,
                row.state,
                row.basis,
                row.reviewed_by,
                row.reason,
                row.created_at,
                row.superseded_at,
            )
            for row in session.scalars(
                select(BuyingChainIdentityLink)
                .where(BuyingChainIdentityLink.claim_id == claim_id)
                .order_by(BuyingChainIdentityLink.created_at, BuyingChainIdentityLink.id)
            )
        ]
        assert identities_after == identities_before
        assert links_after == links_before
        assert any(row[0] == reviewed_link_id and row[4] == "current" for row in links_after)


def test_global_company_identity_requires_current_cited_strong_identifier_and_keeps_claims(db):
    with db.begin() as session:
        project_a = seed(session)
        view = enrich_buying_chain(
            session,
            project_a.id,
            fetcher=lambda url: source(
                "Acme is the general contractor for Orion Data Center in Austin, TX."
            ),
            now=NOW,
        )
        claim_a = session.get(BuyingChainClaim, view["candidates"][0]["id"])
        evidence_a_id = next(
            UUID(citation["evidence_id"])
            for citation in claim_a.citations
            if citation["supports"] == "project_organization"
        )
        evidence_a = session.get(BuyingChainEvidence, evidence_a_id)
        evidence_a.excerpt += (
            " Acme legal entity, LEI: 5493001KJTIIGC8Y1R12, US EIN: 12-3456789."
            " Acme subsidiary record, US EIN: 98-7654321."
            " Acme registry record, US EIN: 11-1111111."
            " Beta legal entity, US EIN: 12-3456789."
            " Sam Lee is engineer at Acme; professional license: LIC-111."
        )
        identity_a = BuyingChainEvidence(
            project_id=project_a.id,
            url="https://registry.example/acme",
            title="Acme legal entity record",
            excerpt=(
                "Acme legal entity record, LEI: 5493001KJTIIGC8Y1R12, US EIN: 12-3456789. "
                "Acme subsidiary record, US EIN: 98-7654321. "
                "Acme registry record, US EIN: 11-1111111."
            ),
            content_hash="a" * 64,
            extraction_location="legal entity identifier field",
            published_at=date(2026, 9, 20),
            observed_at=NOW,
            last_seen_at=NOW,
            project_match_reason="Exact legal entity record linked for the project claim",
        )
        session.add(identity_a)
        session.flush()
        claim_a.citations.append(
            {
                "evidence_id": str(identity_a.id),
                "supports": "project_organization",
                "url": identity_a.url,
                "quote": identity_a.excerpt,
            }
        )
        claim_a.person_name = "Sam Lee"
        claim_a.title = "Project Engineer"
        claim_a.person_organization_relationship = "DIRECT"
        claim_a.person_project_relationship = "UNKNOWN"
        claim_a.citations.extend(
            [
                {
                    "evidence_id": str(evidence_a_id),
                    "supports": "organization_person_role",
                    "url": URL,
                    "quote": "Sam Lee is engineer at Acme; professional license: LIC-111.",
                },
                {
                    "evidence_id": str(evidence_a_id),
                    "supports": "organization_person_role",
                    "url": URL,
                    "quote": "Sam Lee is engineer at Beta; professional license: LIC-222.",
                },
            ]
        )
        project_b = seed(session, "43", "orion-other")
        evidence_b = BuyingChainEvidence(
            project_id=project_b.id,
            retained_evidence_id=evidence_a.retained_evidence_id,
            url=evidence_a.url,
            title=evidence_a.title,
            excerpt=evidence_a.excerpt,
            content_hash=evidence_a.content_hash,
            extraction_location=evidence_a.extraction_location,
            published_at=evidence_a.published_at,
            observed_at=evidence_a.observed_at,
            last_seen_at=evidence_a.last_seen_at,
            project_match_reason="Independent project-specific retained claim fixture",
        )
        identity_b = BuyingChainEvidence(
            project_id=project_b.id,
            url=identity_a.url,
            title=identity_a.title,
            excerpt=identity_a.excerpt,
            content_hash=identity_a.content_hash,
            extraction_location=identity_a.extraction_location,
            published_at=identity_a.published_at,
            observed_at=identity_a.observed_at,
            last_seen_at=identity_a.last_seen_at,
            project_match_reason="Independent project-specific registry citation",
        )
        session.add(evidence_b)
        session.add(identity_b)
        session.flush()
        claim_b = BuyingChainClaim(
            project_id=project_b.id,
            entity_key=claim_a.entity_key,
            fingerprint=claim_a.fingerprint,
            policy_version=claim_a.policy_version,
            organization=claim_a.organization,
            person_name=claim_a.person_name,
            title=claim_a.title,
            category=claim_a.category,
            organization_relationship=claim_a.organization_relationship,
            person_organization_relationship=claim_a.person_organization_relationship,
            person_project_relationship=claim_a.person_project_relationship,
            evidence_strength=claim_a.evidence_strength,
            reason=claim_a.reason,
            citations=[
                {
                    **citation,
                    "evidence_id": str(
                        evidence_b.id
                        if citation["evidence_id"] == str(evidence_a.id)
                        else identity_b.id
                    ),
                    "url": evidence_b.url
                    if citation["evidence_id"] == str(evidence_a.id)
                    else identity_b.url,
                }
                for citation in claim_a.citations
            ],
            public_contacts=claim_a.public_contacts,
            observed_at=claim_a.observed_at,
            verified_at=claim_a.verified_at,
        )
        claim_b.title = "Electrical Lead"
        session.add(claim_b)
        session.flush()
        run_a = session.scalar(
            select(BuyingChainRun).where(BuyingChainRun.project_id == project_a.id)
        )
        session.add(
            BuyingChainRun(
                project_id=project_b.id,
                input_hash=run_a.input_hash,
                evidence_ids=[str(evidence_b.id), str(identity_b.id)],
                claim_ids=[str(claim_b.id)],
                policy_version=run_a.policy_version,
                status=run_a.status,
                documents_checked=run_a.documents_checked,
                candidates_added=1,
                unresolved=[],
            )
        )
        claims = [claim_a, claim_b]
        cited = [evidence_a_id, evidence_b.id]
        identity_sources = [identity_a.id, identity_b.id]

        first = reconcile_claim_identity(
            session,
            claims[0].id,
            "company",
            "lei",
            "5493001KJTIIGC8Y1R12",
            identity_sources[0],
            "Official registry identifier in cited source",
        )
        replay = reconcile_claim_identity(
            session,
            claims[0].id,
            "company",
            "lei",
            "5493001KJTIIGC8Y1R12",
            identity_sources[0],
            "Official registry identifier in cited source",
        )
        second = reconcile_claim_identity(
            session,
            claims[1].id,
            "company",
            "lei",
            "5493001KJTIIGC8Y1R12",
            identity_sources[1],
            "Official registry identifier in cited source",
        )
        assert first.id == replay.id
        assert first.company_identity_id == second.company_identity_id
        assert session.scalar(select(func.count()).select_from(BuyingChainClaim)) == 2
        assert session.scalar(select(func.count()).select_from(CompanyIdentity)) == 2
        ein_a = reconcile_claim_identity(
            session,
            claims[0].id,
            "company",
            "ein",
            "12-3456789",
            identity_sources[0],
            "Typed US EIN in cited legal entity record",
        )
        ein_b = reconcile_claim_identity(
            session,
            claims[1].id,
            "company",
            "ein",
            "123456789",
            identity_sources[1],
            "Typed US EIN in cited legal entity record",
        )
        assert ein_a.company_identity_id == ein_b.company_identity_id
        assert (
            session.scalar(
                select(IdentityIdentifier).where(
                    IdentityIdentifier.identifier_type == "ein",
                    IdentityIdentifier.normalized_value == "123456789",
                )
            )
            is not None
        )

        legacy_identity = CompanyIdentity()
        session.add(legacy_identity)
        session.flush()
        legacy_identifier = IdentityIdentifier(
            entity_type="company",
            company_identity_id=legacy_identity.id,
            person_identity_id=None,
            identifier_type="ein",
            normalized_value="98-7654321",
            source_evidence_id=identity_sources[0],
            source_version_hash=session.get(BuyingChainEvidence, identity_sources[0]).content_hash,
            reason="Existing legacy EIN spelling",
        )
        session.add(legacy_identifier)
        session.flush()
        legacy_a = reconcile_claim_identity(
            session,
            claims[0].id,
            "company",
            "ein",
            "987654321",
            identity_sources[0],
            "Cited EIN without punctuation",
        )
        legacy_b = reconcile_claim_identity(
            session,
            claims[1].id,
            "company",
            "ein",
            "98-7654321",
            identity_sources[1],
            "Same cited EIN with punctuation",
        )
        assert legacy_a.company_identity_id == legacy_b.company_identity_id == legacy_identity.id
        assert legacy_identifier.normalized_value == "98-7654321"

        conflict_a, conflict_b = CompanyIdentity(), CompanyIdentity()
        session.add_all([conflict_a, conflict_b])
        session.flush()
        conflict_rows = [
            IdentityIdentifier(
                entity_type="company",
                company_identity_id=identity.id,
                person_identity_id=None,
                identifier_type="ein",
                normalized_value=value,
                source_evidence_id=identity_sources[0],
                source_version_hash=session.get(
                    BuyingChainEvidence, identity_sources[0]
                ).content_hash,
                reason="Conflicting historical spelling",
            )
            for value, identity in (("111111111", conflict_a), ("11-1111111", conflict_b))
        ]
        session.add_all(conflict_rows)
        session.flush()
        identity_count_before = session.scalar(select(func.count()).select_from(CompanyIdentity))
        identifier_count_before = session.scalar(
            select(func.count()).select_from(IdentityIdentifier)
        )
        links_before_conflict = [
            (row.id, row.company_identity_id, row.source_evidence_id, row.state)
            for row in session.scalars(
                select(BuyingChainIdentityLink)
                .where(BuyingChainIdentityLink.claim_id == claims[0].id)
                .order_by(BuyingChainIdentityLink.id)
            )
        ]
        with pytest.raises(ValueError, match="conflict"):
            reconcile_claim_identity(
                session,
                claims[0].id,
                "company",
                "ein",
                "11-1111111",
                identity_sources[0],
                "Conflicting identifier spellings must not merge identities",
            )
        assert (
            session.scalar(select(func.count()).select_from(CompanyIdentity))
            == identity_count_before
        )
        assert (
            session.scalar(select(func.count()).select_from(IdentityIdentifier))
            == identifier_count_before
        )
        assert [
            (row.id, row.company_identity_id, row.source_evidence_id, row.state)
            for row in session.scalars(
                select(BuyingChainIdentityLink)
                .where(BuyingChainIdentityLink.claim_id == claims[0].id)
                .order_by(BuyingChainIdentityLink.id)
            )
        ] == links_before_conflict
        with pytest.raises(ValueError, match="EIN must be an exact nine-digit"):
            reconcile_claim_identity(
                session,
                claims[0].id,
                "company",
                "ein",
                "12345678",
                identity_sources[0],
                "Malformed EIN must be rejected",
            )
        ensure_project_scoped_identity_links(session, [str(claim.id) for claim in claims])
        person_links = current_claim_identity_links(session, {claim.id for claim in claims})
        person_a_id = person_links[claims[0].id]["person_identity_id"]
        person_b_id = person_links[claims[1].id]["person_identity_id"]
        assert person_a_id != person_b_id
        claims[1].organization = "Beta"
        with pytest.raises(ValueError, match="unambiguously bound"):
            reconcile_claim_identity(
                session,
                claims[1].id,
                "company",
                "lei",
                "5493001KJTIIGC8Y1R12",
                identity_sources[1],
                "Identifier belongs to another entity",
            )
        assert claims[0].person_name == claims[1].person_name == "Sam Lee"
        claims[0].title = "Project Director"
        assert (
            current_claim_identity_links(session, {claims[0].id})[claims[0].id][
                "person_identity_id"
            ]
            == person_a_id
        )
        assert claims[0].person_project_relationship == "UNKNOWN"
        with pytest.raises(ValueError, match="approved strong identifier"):
            reconcile_claim_identity(
                session,
                claims[0].id,
                "person",
                "professional_license",
                "LIC-111",
                cited[0],
                "Unscoped license",
            )
        with pytest.raises(ValueError, match="approved strong identifier"):
            reconcile_claim_identity(
                session,
                claims[0].id,
                "company",
                "registry_number",
                "12345",
                identity_sources[0],
                "Unscoped registry number",
            )
        with pytest.raises(ValueError, match="strong identifier"):
            reconcile_claim_identity(
                session,
                claims[1].id,
                "company",
                "name",
                "Acme",
                identity_sources[1],
                "Same name",
            )
        with pytest.raises(ValueError, match="checksum-valid"):
            reconcile_claim_identity(
                session,
                claims[1].id,
                "company",
                "lei",
                "5493001KJTIIGC8Y1R13",
                identity_sources[1],
                "Uncited identifier",
            )
        with pytest.raises(ValueError, match="unambiguously bound"):
            reconcile_claim_identity(
                session,
                claims[1].id,
                "company",
                "lei",
                "5493001KJTIIGC8Y1R12",
                identity_sources[1],
                "Wrong entity passage",
            )
        with pytest.raises(ValueError, match="unambiguously bound"):
            reconcile_claim_identity(
                session,
                claims[0].id,
                "company",
                "ein",
                "12-3456789",
                cited[0],
                "Number without typed field",
            )

        separate = CompanyIdentity()
        session.add(separate)
        session.flush()
        corrected = link_claim_to_identity(
            session,
            claims[0],
            "company",
            separate.id,
            session.get(BuyingChainEvidence, identity_sources[0]),
            "Operator corrected prior link",
            reviewed_by="operator:nick",
        )
        history = session.scalars(
            select(BuyingChainIdentityLink).where(
                BuyingChainIdentityLink.claim_id == claims[0].id,
                BuyingChainIdentityLink.entity_type == "company",
            )
        ).all()
        assert corrected.state == "current"
        assert sorted(link.state for link in history) == [
            "current",
            "superseded",
            "superseded",
            "superseded",
            "superseded",
            "superseded",
        ]
        assert {link.source_evidence_id for link in history} == {
            cited[0],
            identity_sources[0],
        }
        visible = current_claim_identity_links(session, {claims[0].id})
        assert visible[claims[0].id]["company_identity_id"] == str(separate.id)

        replacement = BuyingChainEvidence(
            project_id=project_a.id,
            url=identity_a.url,
            title=identity_a.title,
            excerpt=(
                "Acme legal entity record, LEI: 5493001KJTIIGC8Y1R12, "
                "US EIN: 12-3456789. "
                "Registry record refreshed."
            ),
            content_hash="b" * 64,
            extraction_location="replacement version",
            published_at=date(2026, 10, 1),
            observed_at=NOW + timedelta(days=1),
            last_seen_at=NOW + timedelta(days=1),
            project_match_reason="New source version",
        )
        session.add(replacement)
        session.flush()
        session.add(
            BuyingChainRun(
                project_id=project_a.id,
                input_hash="c" * 64,
                evidence_ids=[str(evidence_a.id), str(replacement.id)],
                claim_ids=[str(claims[0].id)],
                policy_version="identity-test",
                status="complete",
                documents_checked=1,
                candidates_added=0,
                unresolved=[],
                created_at=NOW + timedelta(days=1),
            )
        )
        assert current_claim_identity_links(session, {claims[0].id})[claims[0].id] == {
            "person_identity_id": person_a_id
        }
        candidate = next(
            item
            for item in buying_chain_view(session, project_a.id)["candidates"]
            if item["id"] == claims[0].id
        )
        assert not candidate["stale"]
        assert "company_identity_id" not in candidate
        assert candidate["person_identity_id"] == person_a_id


def test_batched_buying_chain_view_matches_single_project_projection(db):
    with db.begin() as session:
        project = seed(session)
        enrich_buying_chain(
            session,
            project.id,
            fetcher=lambda url: source(
                "Acme is the general contractor for Orion Data Center in Austin, TX."
            ),
            now=NOW,
        )

        expected = buying_chain_view(session, project.id, now=NOW)
        actual = buying_chain_views(session, {project.id}, now=NOW)[str(project.id)]

        assert actual == expected


def test_batched_retained_query_deduplicates_pairs_and_keeps_all_versions(db, monkeypatch):
    with db.begin() as session:
        project = seed(session)
        linked_need = session.scalar(select(PowerNeed).where(PowerNeed.project_id == project.id))
        direct_observation = session.scalar(
            select(Observation).where(Observation.external_id == project.external_id)
        )
        direct_evidence = session.scalar(
            select(Evidence).where(Evidence.observation_id == direct_observation.id)
        )
        assert (
            linked_need is not None
            and direct_observation is not None
            and direct_evidence is not None
        )

        shared_observation = Observation(
            source_id="test",
            external_id="shared-record",
            title="Shared project evidence",
            url="https://news.example/shared-record",
            abstract="A shared retained observation.",
            published_at=date(2026, 9, 20),
            content_hash="shared-v5",
        )
        other_project = Project(
            source_id="test",
            external_id="99",
            name="Other Data Center",
            location="Dallas, TX",
            identity_key="other-project",
            identity_facts={},
        )
        session.add_all([shared_observation, other_project])
        session.flush()
        second_need = PowerNeed(
            project_id=project.id,
            activity_key="commissioning",
            tier="Signal",
            rationale="Synthetic second need",
        )
        other_need = PowerNeed(
            project_id=other_project.id,
            activity_key="construction",
            tier="Signal",
            rationale="Synthetic other-project need",
        )
        session.add_all([second_need, other_need])
        session.flush()
        # The direct project match also appears through multiple need links;
        # the shared observation is linked through multiple needs and projects.
        session.add_all(
            [
                NeedObservation(need_id=linked_need.id, observation_id=direct_observation.id),
                NeedObservation(need_id=second_need.id, observation_id=direct_observation.id),
                NeedObservation(need_id=linked_need.id, observation_id=shared_observation.id),
                NeedObservation(need_id=second_need.id, observation_id=shared_observation.id),
                NeedObservation(need_id=other_need.id, observation_id=shared_observation.id),
            ]
        )
        session.add(
            Interpretation(
                observation_id=shared_observation.id,
                content_hash=shared_observation.content_hash,
                status="accepted",
                assessment={
                    "evidence_hash": shared_observation.content_hash,
                    "decision": "accepted",
                    "project_identity_key": project.identity_key,
                    "admission_status": "supplemental",
                },
            )
        )
        shared_evidence = []
        for index in range(6):
            evidence = Evidence(
                observation_id=shared_observation.id,
                title=shared_observation.title,
                abstract=shared_observation.abstract,
                url=shared_observation.url,
                content_hash=f"shared-v{index}",
                observed_at=NOW + timedelta(minutes=index),
            )
            session.add(evidence)
            shared_evidence.append(evidence)
        session.flush()
        shared_evidence_ids = [evidence.id for evidence in shared_evidence]

        other_direct_observation = Observation(
            source_id="test",
            external_id=other_project.external_id,
            title=other_project.name,
            url="https://news.example/other-direct",
            abstract="Other project's direct evidence.",
            published_at=date(2026, 9, 21),
            content_hash="other-direct-v1",
        )
        session.add(other_direct_observation)
        session.flush()
        other_direct_evidence = Evidence(
            observation_id=other_direct_observation.id,
            title=other_direct_observation.title,
            abstract=other_direct_observation.abstract,
            url=other_direct_observation.url,
            content_hash=other_direct_observation.content_hash,
            observed_at=NOW + timedelta(minutes=8),
        )
        session.add_all(
            [
                other_direct_evidence,
                Interpretation(
                    observation_id=other_direct_observation.id,
                    content_hash=other_direct_observation.content_hash,
                    status="accepted",
                    assessment={
                        "evidence_hash": other_direct_observation.content_hash,
                        "decision": "accepted",
                        "project_identity_key": other_project.identity_key,
                        "admission_status": "supplemental",
                    },
                ),
            ]
        )
        session.flush()

        project_ids = {project.id, other_project.id}
        expected = {
            str(project_id): buying_chain_view(session, project_id, now=NOW)
            for project_id in project_ids
        }

        from gridlens.intelligence import buying_chain as service

        original_current_check = service._retained_evidence_current_for_project
        visited_pairs = []
        visited_current = []

        def record_current_check(*args, **kwargs):
            project_id, evidence_id = args[1].id, args[2].id
            current = original_current_check(*args, **kwargs)
            visited_pairs.append((project_id, evidence_id))
            visited_current.append((project_id, evidence_id, current))
            return current

        monkeypatch.setattr(service, "_retained_evidence_current_for_project", record_current_check)
        actual = buying_chain_views(session, project_ids, now=NOW)

        expected_pairs = Counter(
            [
                (project.id, direct_evidence.id),
                *((project.id, evidence_id) for evidence_id in shared_evidence_ids),
                *((other_project.id, evidence_id) for evidence_id in shared_evidence_ids),
                (other_project.id, other_direct_evidence.id),
            ]
        )
        expected_current = Counter(
            [
                (project.id, direct_evidence.id, True),
                *(
                    (project.id, evidence_id, evidence_id == shared_evidence_ids[-1])
                    for evidence_id in shared_evidence_ids
                ),
                *((other_project.id, evidence_id, False) for evidence_id in shared_evidence_ids),
                (other_project.id, other_direct_evidence.id, True),
            ]
        )
        evidence_by_id = {
            evidence.id: evidence
            for evidence in [direct_evidence, *shared_evidence, other_direct_evidence]
        }
        expected_order = []
        for project_id in sorted(project_ids):
            project_evidence_ids = [
                evidence_id
                for candidate_project_id, evidence_id in expected_pairs
                if candidate_project_id == project_id
            ]
            expected_order.extend(
                (project_id, evidence_id)
                for evidence_id in sorted(
                    project_evidence_ids,
                    key=lambda evidence_id: (
                        -evidence_by_id[evidence_id].observed_at.timestamp(),
                        evidence_id,
                    ),
                )
            )
        assert actual == expected
        assert Counter(visited_pairs) == expected_pairs
        assert Counter(visited_current) == expected_current
        assert visited_pairs == expected_order
        assert len(visited_pairs) == 14


def test_same_url_retained_and_full_page_quotes_bind_exact_versions(db):
    with db.begin() as session:
        p = seed(session)
        retained = session.scalar(select(Evidence))
        retained.abstract = "Acme is the general contractor for Orion Data Center."
        fetched = source(
            "BuildCo is the electrical contractor for Orion Data Center in Austin, TX."
        )
        output = enrich_buying_chain(session, p.id, fetcher=lambda url: fetched, now=NOW)
        assert {row["organization"] for row in output["candidates"]} == {"Acme", "BuildCo"}
        for row in output["candidates"]:
            for quote in row["evidence"]:
                stored = session.get(BuyingChainEvidence, quote["id"])
                assert quote["quote"] in stored.excerpt


def test_source_a_b_a_restores_current_snapshot_and_preserves_history(db):
    with db.begin() as session:
        p = seed(session)
        for index, contractor in enumerate(["Acme", "BuildCo", "Acme"]):
            now = NOW + timedelta(minutes=index)
            result = enrich_buying_chain(
                session,
                p.id,
                now=now,
                fetcher=lambda url, contractor=contractor, now=now: source(
                    f"{contractor} is the general contractor for Orion Data Center in Austin, TX.",
                    observed=now,
                ),
            )
            assert [c["organization"] for c in result["candidates"]] == [contractor]
            assert result["candidates"][0]["organization_relationship"] == "DIRECT"
        assert session.scalar(select(func.count()).select_from(BuyingChainClaim)) == 2
        assert session.scalar(select(func.count()).select_from(BuyingChainRun)) == 3
        assert len(buying_chain_view(session, p.id, history=True)["candidates"]) == 2


def test_independent_role_conflict_across_runs_remains_unknown(db):
    with db.begin() as session:
        p = seed(session)
        org_text = "Acme is the general contractor for Orion Data Center in Austin, TX."
        first_url = "https://news.example/one"
        second_url = "https://news.example/two"
        documents = {
            URL: source(org_text),
            first_url: source(
                org_text + "\nAlice Smith is Project Director at Acme.", url=first_url
            ),
            second_url: source(
                org_text + "\nAlice Smith is Construction Director at Acme.", url=second_url
            ),
        }
        enrich_buying_chain(
            session, p.id, source_urls=[first_url], fetcher=documents.__getitem__, now=NOW
        )
        output = enrich_buying_chain(
            session,
            p.id,
            source_urls=[second_url],
            fetcher=documents.__getitem__,
            now=NOW + timedelta(minutes=1),
        )
        person = next(c for c in output["candidates"] if c["person_name"])
        assert person["person_project_relationship"] == "UNKNOWN"
        assert person["person_organization_relationship"] == "UNKNOWN"
        assert {e["url"] for e in person["evidence"]} >= {first_url, second_url}


def test_reassigned_retained_role_cannot_conflict_with_current_independent_role(db):
    with db.begin() as session:
        project = seed(session)
        retained = session.scalar(select(Evidence))
        interpretation = session.scalar(select(Interpretation))
        assert retained is not None and interpretation is not None
        old_quote = "Alice Smith is Project Director at Acme."
        current_quote = "Alice Smith is Construction Director at Acme."
        retained.abstract = old_quote
        other_project = Project(
            source_id="test",
            external_id="reassigned",
            name="Other project",
            location="Dallas, TX",
            identity_key="other-project",
            identity_facts={},
        )
        session.add(other_project)
        session.flush()
        old_source = BuyingChainEvidence(
            project_id=project.id,
            retained_evidence_id=retained.id,
            url=retained.url,
            title=retained.title,
            excerpt=old_quote,
            content_hash=retained.content_hash,
            extraction_location="retained fixture",
            published_at=retained.published_at,
            observed_at=NOW,
            last_seen_at=NOW,
            project_match_reason="Prior selected project.",
        )
        current_url = "https://acme.example/current-team"
        current_source = BuyingChainEvidence(
            project_id=project.id,
            url=current_url,
            title="Acme team",
            excerpt=current_quote,
            content_hash="current-independent-role",
            extraction_location="public team page",
            observed_at=NOW,
            last_seen_at=NOW,
            project_match_reason="Public company roster.",
        )
        session.add_all([old_source, current_source])
        session.flush()

        def role_claim(title, source, quote, fingerprint):
            row = BuyingChainClaim(
                project_id=project.id,
                entity_key="acme-alice-smith",
                fingerprint=fingerprint,
                policy_version="test",
                organization="Acme",
                person_name="Alice Smith",
                title=title,
                category="general_contractor",
                organization_relationship="DIRECT",
                person_organization_relationship="CURRENT",
                person_project_relationship="ROLE_SUPPORTED",
                evidence_strength="High",
                reason="Cited public role.",
                citations=[
                    {
                        "evidence_id": str(source.id),
                        "url": source.url,
                        "quote": quote,
                        "supports": "organization_person_role",
                    }
                ],
                public_contacts=[],
                observed_at=NOW,
            )
            session.add(row)
            session.flush()
            return row

        old_claim = role_claim("Project Director", old_source, old_quote, "old-role")
        current_claim = role_claim(
            "Construction Director", current_source, current_quote, "current-role"
        )
        session.add(
            BuyingChainRun(
                project_id=project.id,
                input_hash="current-role-run",
                evidence_ids=[str(current_source.id)],
                claim_ids=[str(current_claim.id)],
                policy_version="test",
                status="complete",
                documents_checked=1,
                candidates_added=1,
                unresolved=[],
            )
        )
        session.flush()
        prior = buying_chain_view(session, project.id, now=NOW)["candidates"]
        assert len(prior) == 1
        assert prior[0]["person_organization_relationship"] == "UNKNOWN"
        assert prior[0]["stale"] is True

        # An accepted evaluator correction rebinds the same immutable version.
        interpretation.assessment = {
            **interpretation.assessment,
            "project_identity_key": other_project.identity_key,
        }
        session.flush()
        view = buying_chain_view(session, project.id, now=NOW)
        assert [row["id"] for row in view["candidates"]] == [current_claim.id]
        assert view["candidates"][0]["person_organization_relationship"] == "CURRENT"
        assert view["candidates"][0]["person_project_relationship"] == "ROLE_SUPPORTED"
        assert view["candidates"][0]["stale"] is False
        assert all(quote["id"] != old_source.id for quote in view["candidates"][0]["evidence"])
        history = buying_chain_view(session, project.id, history=True)["candidates"]
        assert {row["id"] for row in history} == {
            old_claim.id,
            current_claim.id,
        }


def test_fetch_failure_preserves_accepted_chain_and_records_blocker(db):
    with db.begin() as session:
        p = seed(session)
        enrich_buying_chain(
            session,
            p.id,
            fetcher=lambda url: source(
                "Acme is the general contractor for Orion Data Center in Austin, TX."
            ),
            now=NOW,
        )

        def unavailable(url):
            raise TimeoutError("must not leak secret response text")

        result = enrich_buying_chain(
            session, p.id, fetcher=unavailable, now=NOW + timedelta(minutes=1)
        )
        assert result["candidates"][0]["organization"] == "Acme"
        assert any("TimeoutError" in value for value in result["unresolved"])
        assert "must not leak" not in str(result)


def test_stale_role_does_not_erase_direct_organization_relationship(db):
    with db.begin() as session:
        p = seed(session)
        enrich_buying_chain(
            session,
            p.id,
            fetcher=lambda url: source(
                "Acme is the general contractor for Orion Data Center in Austin, TX.\n"
                "Alice Smith is Project Director at Acme."
            ),
            now=NOW,
        )
        aged = buying_chain_view(session, p.id, now=NOW + timedelta(days=370))
        person = next(c for c in aged["candidates"] if c["person_name"])
        assert person["person_project_relationship"] == "UNKNOWN"
        assert person["organization_relationship"] == "DIRECT"
        assert person["stale"]


def test_api_auth_origin_unknown_project_and_url_bound(db, monkeypatch):
    api = import_module("gridlens.api.app")
    monkeypatch.setattr(api, "SessionLocal", db)
    with db.begin() as session:
        p = seed(session)
    client = TestClient(api.app)
    path = f"/api/projects/{p.id}/buying-chain"
    assert client.get(path).status_code == 401
    assert client.post(path + "/enrich").status_code == 401
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    assert client.get(path).json()["status"] == "not_researched"
    assert (
        client.post(path + "/enrich", headers={"origin": "https://evil.example"}).status_code == 403
    )
    assert (
        client.post(path + "/enrich", json={"source_urls": ["https://127.0.0.1"]}).status_code
        == 422
    )
    assert client.post(path + "/enrich", json={"source_urls": [URL] * 5}).status_code == 422
    assert (
        client.get("/api/projects/00000000-0000-0000-0000-000000000000/buying-chain").status_code
        == 404
    )


def test_authenticated_correction_is_append_only_versioned_and_overlays_only_one_project(
    db, monkeypatch
):
    api = import_module("gridlens.api.app")
    monkeypatch.setattr(api, "SessionLocal", db)
    with db.begin() as session:
        project_a = seed(session, external_id="correction-a", identity_key="correction-a")
        project_b = seed(session, external_id="correction-b", identity_key="correction-b")
        for project, external_id in ((project_a, "correction-a"), (project_b, "correction-b")):
            observation = session.scalar(
                select(Observation).where(Observation.external_id == external_id)
            )
            interpretation = session.scalar(
                select(Interpretation).where(Interpretation.observation_id == observation.id)
            )
            interpretation.assessment = {
                **interpretation.assessment,
                "project_identity_key": project.identity_key,
            }
        a = enrich_buying_chain(
            session,
            project_a.id,
            fetcher=lambda url: source(
                "Acme is the general contractor for Orion Data Center in Austin, TX."
            ),
            now=NOW,
        )
        b = enrich_buying_chain(
            session,
            project_b.id,
            fetcher=lambda url: source(
                "Acme is the general contractor for Orion Data Center in Austin, TX."
            ),
            now=NOW,
        )
        candidate = a["candidates"][0]
        claim_id, project_id = candidate["id"], project_a.id
        evidence = candidate["evidence"][0]
        payload = {
            "expected_version": candidate["fingerprint"],
            "idempotency_key": "correction-test-001",
            "action": "correct",
            "values": {"category": "general_contractor"},
            "source_evidence_id": str(evidence["id"]),
            "source_hash": evidence["content_hash"],
            "reason": "Operator verified title in cited source.",
        }
    client = TestClient(api.app)
    path = f"/api/projects/{project_id}/buying-chain/{claim_id}/corrections"
    import gridlens.intelligence.buying_chain_corrections as corrections

    class SameTimestamp(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setattr(corrections, "datetime", SameTimestamp)
    assert client.post(path, json=payload).status_code == 401
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    assert (
        client.post(path, headers={"origin": "https://evil.example"}, json=payload).status_code
        == 403
    )
    response = client.post(path, headers={"origin": "http://testserver"}, json=payload)
    assert response.status_code == 200, response.text
    replay = client.post(path, headers={"origin": "http://testserver"}, json=payload)
    assert replay.json()["id"] == response.json()["id"]
    sequential = {
        **payload,
        "expected_version": response.json()["id"],
        "idempotency_key": "correction-test-002",
        "values": {"organization_relationship": "UNKNOWN"},
    }
    second = client.post(path, headers={"origin": "http://testserver"}, json=sequential)
    assert second.status_code == 200, second.text
    second_replay = client.post(path, headers={"origin": "http://testserver"}, json=sequential)
    assert second_replay.status_code == 200, second_replay.text
    assert second_replay.json()["id"] == second.json()["id"]
    stale = {**payload, "idempotency_key": "correction-test-008"}
    assert client.post(path, headers={"origin": "http://testserver"}, json=stale).status_code == 409
    current = client.get(f"/api/projects/{project_id}/buying-chain").json()
    edited = next(item for item in current["candidates"] if item["id"] == str(claim_id))
    assert edited["category"] == "general_contractor"
    assert edited["correction_version"] == second.json()["id"]
    unsupported_contact = {
        "expected_version": second.json()["id"],
        "idempotency_key": "correction-test-005",
        "action": "correct",
        "values": {"public_contact_kind": "phone", "public_contact_value": "+1-512-555-0100"},
        "source_evidence_id": str(evidence["id"]),
        "source_hash": evidence["content_hash"],
        "reason": "Attempted contact correction without a contact citation.",
    }
    assert (
        client.post(
            path, headers={"origin": "http://testserver"}, json=unsupported_contact
        ).status_code
        == 422
    )
    changed_hash = {
        **unsupported_contact,
        "idempotency_key": "correction-test-006",
        "source_hash": "f" * 64,
    }
    assert (
        client.post(path, headers={"origin": "http://testserver"}, json=changed_hash).status_code
        == 422
    )
    arbitrary_identity = {
        "expected_version": second.json()["id"],
        "idempotency_key": "correction-test-007",
        "action": "correct",
        "values": {},
        "source_evidence_id": str(evidence["id"]),
        "source_hash": evidence["content_hash"],
        "identity_type": "company",
        "identity_id": "00000000-0000-0000-0000-000000000001",
        "reason": "Attempted identity reference without an existing reviewed identity.",
    }
    assert (
        client.post(
            path, headers={"origin": "http://testserver"}, json=arbitrary_identity
        ).status_code
        == 422
    )
    unsupported_readback = client.get(f"/api/projects/{project_id}/buying-chain")
    assert unsupported_readback.status_code == 200, unsupported_readback.text
    unsupported_candidate = next(
        item for item in unsupported_readback.json()["candidates"] if item["id"] == str(claim_id)
    )
    assert unsupported_candidate["company_identity_id"] == str(candidate["company_identity_id"])
    with db.begin() as session:
        session.add(
            BuyingChainEvidence(
                project_id=project_id,
                url=evidence["url"],
                title="Updated article",
                excerpt="Updated article with no current buyer or contact claim.",
                content_hash="b" * 64,
                extraction_location="article body",
                published_at=date(2026, 9, 21),
                observed_at=NOW + timedelta(days=1),
                last_seen_at=NOW + timedelta(days=1),
                project_match_reason="same test project",
            )
        )
    stale_history = client.get(f"/api/projects/{project_id}/buying-chain?history=true").json()
    stale_item = next(item for item in stale_history["candidates"] if item["id"] == str(claim_id))
    assert stale_item["correction_stale"] is True
    assert stale_item["category"] == "general_contractor"
    assert len(stale_item["correction_history"]) == 2
    replay_after_stale = client.post(path, headers={"origin": "http://testserver"}, json=payload)
    assert replay_after_stale.status_code == 200, replay_after_stale.text
    assert replay_after_stale.json()["id"] == response.json()["id"]
    stale_current = client.get(f"/api/projects/{project_id}/buying-chain").json()
    assert all(item["id"] != str(claim_id) for item in stale_current["candidates"])
    report = {
        "expected_version": second.json()["id"],
        "idempotency_key": "correction-test-003",
        "action": "correct",
        "values": {"public_contact_kind": "phone", "public_contact_value": "+1-512-555-0100"},
        "reason": "Operator reported a contact during a call.",
        "reported_contact": True,
    }
    reported = client.post(path, headers={"origin": "http://testserver"}, json=report)
    assert reported.status_code == 409, reported.text
    retract = {
        "expected_version": second.json()["id"],
        "idempotency_key": "correction-test-004",
        "action": "retract",
        "reason": "Operator withdrew the relationship.",
        "reported_contact": True,
    }
    retracted = client.post(path, headers={"origin": "http://testserver"}, json=retract)
    assert retracted.status_code == 409, retracted.text
    assert all(
        item["id"] != str(claim_id)
        for item in client.get(f"/api/projects/{project_id}/buying-chain").json()["candidates"]
    )
    history = client.get(f"/api/projects/{project_id}/buying-chain?history=true").json()
    edited_history = next(item for item in history["candidates"] if item["id"] == str(claim_id))
    assert edited_history["category"] == "general_contractor"
    assert edited_history["correction_version"] == second.json()["id"]
    assert len(edited_history["correction_history"]) == 2
    assert [row["id"] for row in edited_history["correction_history"]] == [
        response.json()["id"],
        second.json()["id"],
    ]
    assert (
        edited_history["correction_history"][0]["created_at"]
        == edited_history["correction_history"][1]["created_at"]
    )

    original_view = corrections.buying_chain_view

    def stale_chain_with_current_citation(session, selected_project_id, **kwargs):
        result = original_view(session, selected_project_id, **kwargs)
        item = next(
            (
                candidate
                for candidate in result["candidates"]
                if str(candidate["id"]) == str(claim_id)
            ),
            None,
        )
        if item is None:
            return result
        item["correction_stale"] = True
        item["stale"] = False
        current_citation = next(
            item for item in item["evidence"] if str(item["id"]) == str(evidence["id"])
        )
        current_citation.update(
            current_source_version_id=evidence["id"],
            content_hash=evidence["content_hash"],
            current_support=True,
        )
        return result

    monkeypatch.setattr(corrections, "buying_chain_view", stale_chain_with_current_citation)
    current_cited = {
        "expected_version": second.json()["id"],
        "idempotency_key": "correction-after-stale-chain",
        "action": "correct",
        "values": {"category": "electrical_contractor"},
        "source_evidence_id": str(evidence["id"]),
        "source_hash": evidence["content_hash"],
        "reason": "Attempted a current-cited correction after stale history.",
    }
    blocked_current_cited = client.post(
        path, headers={"origin": "http://testserver"}, json=current_cited
    )
    assert blocked_current_cited.status_code == 409, blocked_current_cited.text
    with db() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(BuyingChainCorrection)
                .where(BuyingChainCorrection.claim_id == claim_id)
            )
            == 2
        )
    other = client.get(f"/api/projects/{project_b.id}/buying-chain").json()
    other_candidate = next(
        item for item in other["candidates"] if item["id"] == str(b["candidates"][0]["id"])
    )
    assert other_candidate["category"] == "general_contractor"


def test_semantic_corrections_require_current_subject_and_project_evidence(db, monkeypatch):
    api = import_module("gridlens.api.app")
    monkeypatch.setattr(api, "SessionLocal", db)
    with db.begin() as session:
        project = seed(
            session, external_id="semantic-correction", identity_key="semantic-correction"
        )
        observation = session.scalar(
            select(Observation).where(Observation.external_id == "semantic-correction")
        )
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == observation.id)
        )
        interpretation.assessment = {
            **interpretation.assessment,
            "project_identity_key": project.identity_key,
        }
        result = enrich_buying_chain(
            session,
            project.id,
            fetcher=lambda url: source(
                "Acme is the general contractor for Orion Data Center in Austin, TX."
            ),
            now=NOW,
        )
        candidate = result["candidates"][0]
        claim_id, project_id = candidate["id"], project.id
        claim = session.get(BuyingChainClaim, claim_id)
        assert claim is not None
        # Exercise a positive relationship promotion while retaining the source's
        # explicit organization/project statement as the only valid proof.
        claim.organization_relationship = "UNKNOWN"

        def cite_document(url: str, text: str, evidence_id: UUID) -> BuyingChainEvidence:
            row = BuyingChainEvidence(
                id=evidence_id,
                project_id=project.id,
                url=url,
                title="Project role update",
                excerpt=text,
                content_hash=("d" if "electrical contractor" in text else "e") * 64,
                extraction_location="article body",
                published_at=date(2026, 9, 25),
                observed_at=NOW,
                last_seen_at=NOW,
                project_match_reason="same named project",
            )
            session.add(row)
            session.flush()
            quote = text
            claim.citations = [
                *claim.citations,
                {
                    "evidence_id": str(row.id),
                    "url": row.url,
                    "quote": quote,
                    "supports": "project_organization",
                },
            ]
            session.flush()
            return row

        electrical = cite_document(
            "https://news.example/orion-electrical",
            "Acme is the electrical contractor for Orion Data Center in Austin, TX.",
            UUID("00000000-0000-0000-0000-000000000101"),
        )
        unrelated = cite_document(
            "https://news.example/vega-electrical",
            "Acme is the electrical contractor for Vega Data Center in Austin, TX.",
            UUID("00000000-0000-0000-0000-000000000102"),
        )
        contact_only = cite_document(
            "https://news.example/orion-contact",
            "Contact Acme about Orion Data Center in Austin, TX.",
            UUID("00000000-0000-0000-0000-000000000103"),
        )
        initial_version = candidate["fingerprint"]

    client = TestClient(api.app)
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    path = f"/api/projects/{project_id}/buying-chain/{claim_id}/corrections"
    import gridlens.intelligence.buying_chain_corrections as corrections

    original_view = corrections.buying_chain_view

    def with_unrelated_stale_contact(session, selected_project_id, **kwargs):
        view = original_view(session, selected_project_id, **kwargs)
        candidate = next(item for item in view["candidates"] if str(item["id"]) == str(claim_id))
        candidate["stale"] = True
        return view

    monkeypatch.setattr(corrections, "buying_chain_view", with_unrelated_stale_contact)
    with db.begin() as session:
        before_edit = with_unrelated_stale_contact(
            session, project_id, history=False, include_identity_ids=False
        )
        stale_contact_candidate = next(
            item for item in before_edit["candidates"] if str(item["id"]) == str(claim_id)
        )
        assert stale_contact_candidate["stale"] is True

    def payload(
        key: str,
        evidence: BuyingChainEvidence,
        field: str,
        value: str,
        expected_version: str = initial_version,
    ) -> dict:
        return {
            "expected_version": expected_version,
            "idempotency_key": key,
            "action": "correct",
            "values": {field: value},
            "source_evidence_id": str(evidence.id),
            "source_hash": evidence.content_hash,
            "reason": "Checked the cited role statement.",
        }

    unsupported = client.post(
        path,
        headers={"origin": "http://testserver"},
        json=payload("semantic-contact-only", contact_only, "organization_relationship", "DIRECT"),
    )
    assert unsupported.status_code == 422, unsupported.text
    unrelated_result = client.post(
        path,
        headers={"origin": "http://testserver"},
        json=payload("semantic-other-project", unrelated, "category", "electrical_contractor"),
    )
    assert unrelated_result.status_code == 422, unrelated_result.text
    with db.begin() as session:
        assert session.scalar(select(func.count()).select_from(BuyingChainCorrection)) == 0

    matching_values = payload(
        "semantic-matching-role-and-category",
        electrical,
        "category",
        "electrical_contractor",
    )
    matching_values["values"]["organization_relationship"] = "DIRECT"
    matched = client.post(
        path,
        headers={"origin": "http://testserver"},
        json=matching_values,
    )
    assert matched.status_code == 200, matched.text
    unsupported_person_relationship = client.post(
        path,
        headers={"origin": "http://testserver"},
        json=payload(
            "semantic-person-organization-direct",
            electrical,
            "person_organization_relationship",
            "DIRECT",
            matched.json()["id"],
        ),
    )
    assert unsupported_person_relationship.status_code == 422, unsupported_person_relationship.text
    unsupported_assignment = client.post(
        path,
        headers={"origin": "http://testserver"},
        json=payload(
            "semantic-person-project-role",
            electrical,
            "person_project_relationship",
            "ROLE_SUPPORTED",
            matched.json()["id"],
        ),
    )
    assert unsupported_assignment.status_code == 422, unsupported_assignment.text
    readback = client.get(f"/api/projects/{project_id}/buying-chain").json()
    corrected = next(item for item in readback["candidates"] if item["id"] == str(claim_id))
    assert corrected["category"] == "electrical_contractor"
    assert corrected["organization_relationship"] == "DIRECT"
    with db.begin() as session:
        assert session.scalar(select(func.count()).select_from(BuyingChainCorrection)) == 1


def test_correction_rejects_null_required_organization_without_persisted_effects(db, monkeypatch):
    api = import_module("gridlens.api.app")
    monkeypatch.setattr(api, "SessionLocal", db)
    with db.begin() as session:
        project = seed(session, external_id="correction-null-organization")
        observation = session.scalar(
            select(Observation).where(Observation.external_id == "correction-null-organization")
        )
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == observation.id)
        )
        interpretation.assessment = {
            **interpretation.assessment,
            "project_identity_key": project.identity_key,
        }
        result = enrich_buying_chain(
            session,
            project.id,
            fetcher=lambda url: source(
                "Acme is the general contractor for Orion Data Center in Austin, TX."
            ),
            now=NOW,
        )
        candidate = result["candidates"][0]
        evidence = candidate["evidence"][0]
        project_id, claim_id = project.id, candidate["id"]
        correction_count = session.scalar(select(func.count()).select_from(BuyingChainCorrection))
    client = TestClient(api.app)
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    path = f"/api/projects/{project_id}/buying-chain/{claim_id}/corrections"
    headers = {"origin": "http://testserver"}
    for index, organization in enumerate((None, "   ")):
        invalid = {
            "expected_version": candidate["fingerprint"],
            "idempotency_key": f"organization-null-{index:04d}",
            "action": "correct",
            "values": {"organization": organization},
            "source_evidence_id": str(evidence["id"]),
            "source_hash": evidence["content_hash"],
            "reason": "Attempted to clear the required organization.",
        }
        response = client.post(path, headers=headers, json=invalid)
        assert response.status_code == 422, response.text
    readback = client.get(f"/api/projects/{project_id}/buying-chain")
    assert readback.status_code == 200, readback.text
    unchanged = next(item for item in readback.json()["candidates"] if item["id"] == str(claim_id))
    assert unchanged["organization"] == "Acme"
    assert unchanged["correction_version"] == candidate["fingerprint"]
    with db.begin() as session:
        assert (
            session.scalar(select(func.count()).select_from(BuyingChainCorrection))
            == correction_count
        )


def test_source_free_contact_report_cannot_smuggle_other_corrections(db, monkeypatch):
    api = import_module("gridlens.api.app")
    monkeypatch.setattr(api, "SessionLocal", db)
    with db.begin() as session:
        project = seed(session, external_id="contact-report-boundary")
        observation = session.scalar(
            select(Observation).where(Observation.external_id == "contact-report-boundary")
        )
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == observation.id)
        )
        interpretation.assessment = {
            **interpretation.assessment,
            "project_identity_key": project.identity_key,
        }
        result = enrich_buying_chain(
            session,
            project.id,
            fetcher=lambda url: source(
                "Acme is the general contractor for Orion Data Center in Austin, TX."
            ),
            now=NOW,
        )
        candidate = result["candidates"][0]
        project_id, claim_id = project.id, candidate["id"]
        correction_count = session.scalar(select(func.count()).select_from(BuyingChainCorrection))
    client = TestClient(api.app)
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    path = f"/api/projects/{project_id}/buying-chain/{claim_id}/corrections"
    headers = {"origin": "http://testserver"}
    invalid_values = [
        {"category": "electrical_contractor"},
        {"title": "New buyer title"},
        {"organization_relationship": "DIRECT"},
        {"person_project_relationship": "ROLE_SUPPORTED"},
        {
            "public_contact_kind": "phone",
            "public_contact_value": "+1-512-555-0100",
            "title": "Buyer",
        },
    ]
    for index, values in enumerate(invalid_values):
        response = client.post(
            path,
            headers=headers,
            json={
                "expected_version": candidate["fingerprint"],
                "idempotency_key": f"contact-report-boundary-{index}",
                "action": "correct",
                "values": values,
                "reason": "Operator reported a contact during a call.",
                "reported_contact": True,
            },
        )
        assert response.status_code == 422, response.text
    readback = client.get(f"/api/projects/{project_id}/buying-chain")
    assert readback.status_code == 200, readback.text
    unchanged = next(item for item in readback.json()["candidates"] if item["id"] == str(claim_id))
    assert unchanged["correction_version"] == candidate["fingerprint"]
    assert unchanged["organization"] == "Acme"
    assert unchanged["title"] == candidate["title"]
    with db() as session:
        assert (
            session.scalar(select(func.count()).select_from(BuyingChainCorrection))
            == correction_count
        )

    reported = client.post(
        path,
        headers=headers,
        json={
            "expected_version": candidate["fingerprint"],
            "idempotency_key": "contact-report-boundary-replacement",
            "action": "correct",
            "values": {"public_contact_kind": "phone", "public_contact_value": "+1-512-555-0100"},
            "reason": "Operator reported a contact during a call.",
            "reported_contact": True,
        },
    )
    assert reported.status_code == 200, reported.text
    replayed_report = client.post(
        path,
        headers=headers,
        json={
            "expected_version": candidate["fingerprint"],
            "idempotency_key": "contact-report-boundary-replacement",
            "action": "correct",
            "values": {
                "public_contact_kind": "phone",
                "public_contact_value": "+1-512-555-0100",
            },
            "reason": "Operator reported a contact during a call.",
            "reported_contact": True,
        },
    )
    assert replayed_report.status_code == 200, replayed_report.text
    assert replayed_report.json()["id"] == reported.json()["id"]
    changed_report_flag = client.post(
        path,
        headers=headers,
        json={
            "expected_version": candidate["fingerprint"],
            "idempotency_key": "contact-report-boundary-replacement",
            "action": "correct",
            "values": {
                "public_contact_kind": "phone",
                "public_contact_value": "+1-512-555-0100",
            },
            "reason": "Operator reported a contact during a call.",
            "reported_contact": False,
        },
    )
    assert changed_report_flag.status_code == 422, changed_report_flag.text
    after_report = next(
        item
        for item in client.get(f"/api/projects/{project_id}/buying-chain?history=true").json()[
            "candidates"
        ]
        if item["id"] == str(claim_id)
    )
    assert after_report["reported_contacts"][0]["operator_report"] is True
    assert all(contact["operator_report"] is False for contact in after_report["public_contacts"])
    cleared = client.post(
        path,
        headers=headers,
        json={
            "expected_version": reported.json()["id"],
            "idempotency_key": "contact-report-boundary-clear",
            "action": "correct",
            "values": {"public_contact_kind": "phone", "public_contact_value": "   "},
            "reason": "Operator cleared the reported phone number.",
            "reported_contact": True,
        },
    )
    assert cleared.status_code == 200, cleared.text
    after_clear = next(
        item
        for item in client.get(f"/api/projects/{project_id}/buying-chain?history=true").json()[
            "candidates"
        ]
        if item["id"] == str(claim_id)
    )
    assert after_clear["reported_contacts"] == []
    assert after_clear["correction_history"][-1]["reported_contact"] is True
    assert after_clear["correction_history"][-1]["values"]["contact_status"] == ("operator_report")
    null_clear = client.post(
        path,
        headers=headers,
        json={
            "expected_version": cleared.json()["id"],
            "idempotency_key": "contact-report-boundary-null-clear",
            "action": "correct",
            "values": {"public_contact_kind": "phone", "public_contact_value": None},
            "reason": "Operator explicitly cleared the reported phone number.",
            "reported_contact": True,
        },
    )
    assert null_clear.status_code == 200, null_clear.text
    assert null_clear.json()["reported_contact"] is True
    retraction = client.post(
        path,
        headers=headers,
        json={
            "expected_version": null_clear.json()["id"],
            "idempotency_key": "contact-report-boundary-retract",
            "action": "retract",
            "reason": "Operator reported withdrawal of the relationship.",
            "reported_contact": True,
        },
    )
    assert retraction.status_code == 200, retraction.text
    assert retraction.json()["reported_contact"] is True
    history_after_retraction = next(
        item
        for item in client.get(f"/api/projects/{project_id}/buying-chain?history=true").json()[
            "candidates"
        ]
        if item["id"] == str(claim_id)
    )
    retract_decision = history_after_retraction["correction_history"][-1]
    assert retract_decision["reported_contact"] is True
    assert retract_decision["values"]["contact_status"] == "operator_report"
    reported_after_retraction = client.post(
        path,
        headers=headers,
        json={
            "expected_version": retraction.json()["id"],
            "idempotency_key": "contact-report-boundary-after-retract",
            "action": "correct",
            "values": {"public_contact_kind": "phone", "public_contact_value": "+1-512-555-0199"},
            "reason": "Operator reported a contact after the relationship was withdrawn.",
            "reported_contact": True,
        },
    )
    assert reported_after_retraction.status_code == 200, reported_after_retraction.text
    after_contact_on_retracted_claim = next(
        item
        for item in client.get(f"/api/projects/{project_id}/buying-chain?history=true").json()[
            "candidates"
        ]
        if item["id"] == str(claim_id)
    )
    assert after_contact_on_retracted_claim["retracted"] is True
    assert after_contact_on_retracted_claim["reported_contacts"][0]["value"] == "+1-512-555-0199"
    current_after_contact_on_retracted_claim = client.get(
        f"/api/projects/{project_id}/buying-chain"
    )
    assert current_after_contact_on_retracted_claim.status_code == 200
    assert all(
        item["id"] != str(claim_id)
        for item in current_after_contact_on_retracted_claim.json()["candidates"]
    )


def test_mixed_case_public_contact_correction_survives_current_cited_readback(db, monkeypatch):
    api = import_module("gridlens.api.app")
    monkeypatch.setattr(api, "SessionLocal", db)
    with db.begin() as session:
        project = seed(session, external_id="correction-casefold-contact")
        observation = session.scalar(
            select(Observation).where(Observation.external_id == "correction-casefold-contact")
        )
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == observation.id)
        )
        interpretation.assessment = {
            **interpretation.assessment,
            "project_identity_key": project.identity_key,
        }
        result = enrich_buying_chain(
            session,
            project.id,
            fetcher=lambda url: source(
                "Acme is the general contractor for Orion Data Center in Austin, TX. "
                "Alice Smith is Project Director at Acme; "
                "Alice Smith email: Alice.Smith@Example.com."
            ),
            now=NOW,
        )
        candidate = next(
            item for item in result["candidates"] if item["person_name"] == "Alice Smith"
        )
        evidence = next(
            item for item in candidate["evidence"] if item.get("supports") == "public_contact"
        )
        assert evidence["current_support"] is True
        assert evidence["public_research_provenance"] is True
        project_id, claim_id = project.id, candidate["id"]
    client = TestClient(api.app)
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    path = f"/api/projects/{project_id}/buying-chain/{claim_id}/corrections"
    corrected = client.post(
        path,
        headers={"origin": "http://testserver"},
        json={
            "expected_version": candidate["fingerprint"],
            "idempotency_key": "contact-casefold-0001",
            "action": "correct",
            "values": {
                "title": None,
                "public_contact_kind": "email",
                "public_contact_value": "ALICE.SMITH@EXAMPLE.COM",
            },
            "source_evidence_id": str(evidence["id"]),
            "source_hash": evidence["content_hash"],
            "reason": "Corrected the case of the cited current public email.",
        },
    )
    assert corrected.status_code == 200, corrected.text
    readback = client.get(f"/api/projects/{project_id}/buying-chain")
    assert readback.status_code == 200, readback.text
    current = next(item for item in readback.json()["candidates"] if item["id"] == str(claim_id))
    assert current["title"] is None
    assert len(current["public_contacts"]) == 1
    contact = current["public_contacts"][0]
    assert contact["kind"] == "email"
    assert contact["value"] == "ALICE.SMITH@EXAMPLE.COM"
    assert contact["source_url"] == URL
    assert contact["quote"] == "Alice Smith email: Alice.Smith@Example.com."
    assert datetime.fromisoformat(contact["observed_at"]) == evidence["observed_at"]
    assert current["organization_relationship"] == "DIRECT", current
    with db() as session:
        live_chain = buying_chain_view(session, project_id)
    projected = next(
        contact for contact in contact_projection(live_chain) if contact.claim_id == str(claim_id)
    )
    methods = projected.methods
    assert methods[0]["href"] == "mailto:ALICE.SMITH@EXAMPLE.COM"
    mixed_report = client.post(
        path,
        headers={"origin": "http://testserver"},
        json={
            "expected_version": corrected.json()["id"],
            "idempotency_key": "contact-casefold-mixed-report",
            "action": "correct",
            "values": {
                "title": None,
                "public_contact_kind": "phone",
                "public_contact_value": "555-0100",
            },
            "source_evidence_id": str(evidence["id"]),
            "source_hash": evidence["content_hash"],
            "reason": "Cleared a stale title and recorded a phone from the operator.",
            "reported_contact": True,
        },
    )
    assert mixed_report.status_code == 200, mixed_report.text


def test_identity_link_correction_api_returns_typed_reference_and_replays(db, monkeypatch):
    api = import_module("gridlens.api.app")
    monkeypatch.setattr(api, "SessionLocal", db)
    with db.begin() as session:
        projects = [
            seed(session, external_id="identity-api-a", identity_key="identity-api-a"),
            seed(session, external_id="identity-api-b", identity_key="identity-api-b"),
        ]
        candidates = []
        for project, external_id in zip(
            projects, ("identity-api-a", "identity-api-b"), strict=True
        ):
            observed = session.scalar(
                select(Observation).where(Observation.external_id == external_id)
            )
            interpretation = session.scalar(
                select(Interpretation).where(Interpretation.observation_id == observed.id)
            )
            interpretation.assessment = {
                **interpretation.assessment,
                "project_identity_key": project.identity_key,
            }
            result = enrich_buying_chain(
                session,
                project.id,
                fetcher=lambda url: source(
                    "Acme is the general contractor for Orion Data Center in Austin, TX."
                ),
                now=NOW,
            )
            candidates.append(result["candidates"][0])
        candidate = candidates[0]
        evidence = candidate["evidence"][0]
        payload = {
            "expected_version": candidate["fingerprint"],
            "idempotency_key": "identity-api-link-001",
            "action": "correct",
            "values": {},
            "source_evidence_id": str(evidence["id"]),
            "source_hash": evidence["content_hash"],
            "reason": "Reviewed the company identity against current evidence.",
            "identity_type": "company",
        }
    client = TestClient(api.app)
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    project_id, other_project_id = (project.id for project in projects)
    claim_id, other_claim_id = candidates[0]["id"], candidates[1]["id"]
    path = f"/api/projects/{project_id}/buying-chain/{claim_id}/corrections"
    source_readback = client.get(f"/api/projects/{other_project_id}/buying-chain")
    assert source_readback.status_code == 200, source_readback.text
    source_candidate = next(
        item for item in source_readback.json()["candidates"] if item["id"] == str(other_claim_id)
    )
    identity_id = source_candidate["company_identity_id"]
    assert identity_id is not None
    assert identity_id != str(candidates[0]["company_identity_id"])
    payload["identity_id"] = identity_id
    source_evidence = next(
        item for item in candidates[0]["evidence"] if item.get("supports") == "project_organization"
    )
    payload["source_evidence_id"] = str(source_evidence["id"])
    payload["source_hash"] = source_evidence["content_hash"]
    original = client.get(f"/api/projects/{project_id}/buying-chain")
    assert original.status_code == 200, original.text
    original_candidate = next(
        item for item in original.json()["candidates"] if item["id"] == str(claim_id)
    )
    assert original_candidate["company_identity_id"] == str(candidates[0]["company_identity_id"])
    response = client.post(path, headers={"origin": "http://testserver"}, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["values"]["identity_reference"] == {
        "type": "company",
        "id": str(identity_id),
    }
    replay = client.post(path, headers={"origin": "http://testserver"}, json=payload)
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == response.json()["id"]
    rebound_readback = client.get(f"/api/projects/{project_id}/buying-chain")
    assert rebound_readback.status_code == 200, rebound_readback.text
    rebound_candidate = next(
        item for item in rebound_readback.json()["candidates"] if item["id"] == str(claim_id)
    )
    assert rebound_candidate["company_identity_id"] == identity_id
    assert rebound_candidate["person_identity_id"] is None
    history = client.get(f"/api/projects/{project_id}/buying-chain?history=true").json()[
        "candidates"
    ]
    corrected = next(item for item in history if item["id"] == str(claim_id))
    assert corrected["correction_history"][-1]["values"]["identity_reference"] == {
        "type": "company",
        "id": str(identity_id),
    }
    with db.begin() as session:
        links = list(
            session.scalars(
                select(BuyingChainIdentityLink).where(
                    BuyingChainIdentityLink.claim_id == claim_id,
                    BuyingChainIdentityLink.company_identity_id == identity_id,
                    BuyingChainIdentityLink.state == "current",
                )
            )
        )
        assert len(links) == 1
        corrections = list(
            session.scalars(
                select(BuyingChainCorrection).where(
                    BuyingChainCorrection.claim_id == claim_id,
                    BuyingChainCorrection.idempotency_key == "identity-api-link-001",
                )
            )
        )
        assert len(corrections) == 1


def test_retraction_rejects_identity_fields_without_changing_any_state(db, monkeypatch):
    api = import_module("gridlens.api.app")
    monkeypatch.setattr(api, "SessionLocal", db)
    with db.begin() as session:
        project = seed(session, external_id="retract-identity")
        observation = session.scalar(
            select(Observation).where(Observation.external_id == "retract-identity")
        )
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == observation.id)
        )
        interpretation.assessment = {
            **interpretation.assessment,
            "project_identity_key": project.identity_key,
        }
        result = enrich_buying_chain(
            session,
            project.id,
            fetcher=lambda url: source(
                "Acme is the general contractor for Orion Data Center in Austin, TX. "
                "Alice Smith is Project Director at Acme."
            ),
            now=NOW,
        )
        company_candidate = next(item for item in result["candidates"] if not item["person_name"])
        claim_id = company_candidate["id"]
        company_identity = CompanyIdentity()
        person_identity = PersonIdentity()
        session.add_all([company_identity, person_identity])
        session.flush()
        correction_count = session.scalar(select(func.count()).select_from(BuyingChainCorrection))
        before_links = [
            (
                link.id,
                link.claim_id,
                link.entity_type,
                link.company_identity_id,
                link.person_identity_id,
                link.source_evidence_id,
                link.source_version_hash,
                link.state,
                link.basis,
                link.reviewed_by,
                link.superseded_at,
            )
            for link in session.scalars(
                select(BuyingChainIdentityLink).order_by(BuyingChainIdentityLink.id)
            )
        ]
        company_identity_ids = sorted(
            str(item.id) for item in session.scalars(select(CompanyIdentity))
        )
        person_identity_ids = sorted(
            str(item.id) for item in session.scalars(select(PersonIdentity))
        )
        project_id = project.id
    client = TestClient(api.app)
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    path = f"/api/projects/{project_id}/buying-chain/{claim_id}/corrections"
    invalid_identity_fields = [
        {"identity_type": "company", "identity_id": str(company_identity.id)},
        {"identity_type": "person", "identity_id": str(person_identity.id)},
        {"identity_type": "company"},
        {"identity_id": str(company_identity.id)},
    ]
    for index, identity_fields in enumerate(invalid_identity_fields):
        response = client.post(
            path,
            headers={"origin": "http://testserver"},
            json={
                "expected_version": company_candidate["fingerprint"],
                "idempotency_key": f"retract-identity-{index:03d}",
                "action": "retract",
                "reason": "Withdraw the relationship without changing its identity.",
                "reported_contact": True,
                **identity_fields,
            },
        )
        assert response.status_code == 422, response.text
    current = client.get(f"/api/projects/{project_id}/buying-chain")
    assert current.status_code == 200, current.text
    still_present = next(
        item for item in current.json()["candidates"] if item["id"] == str(claim_id)
    )
    assert still_present["retracted"] is False
    assert still_present["company_identity_id"] == str(company_candidate["company_identity_id"])
    with db.begin() as session:
        assert (
            session.scalar(select(func.count()).select_from(BuyingChainCorrection))
            == correction_count
        )
        after_links = [
            (
                link.id,
                link.claim_id,
                link.entity_type,
                link.company_identity_id,
                link.person_identity_id,
                link.source_evidence_id,
                link.source_version_hash,
                link.state,
                link.basis,
                link.reviewed_by,
                link.superseded_at,
            )
            for link in session.scalars(
                select(BuyingChainIdentityLink).order_by(BuyingChainIdentityLink.id)
            )
        ]
        assert after_links == before_links
        assert (
            sorted(str(item.id) for item in session.scalars(select(CompanyIdentity)))
            == company_identity_ids
        )
        assert (
            sorted(str(item.id) for item in session.scalars(select(PersonIdentity)))
            == person_identity_ids
        )


def test_buying_chain_api_hides_identity_link_with_unsupported_citation(db, monkeypatch):
    api = import_module("gridlens.api.app")
    monkeypatch.setattr(api, "SessionLocal", db)
    with db.begin() as session:
        project = seed(session, external_id="unsupported-identity-readback")
        observation = session.scalar(
            select(Observation).where(Observation.external_id == "unsupported-identity-readback")
        )
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == observation.id)
        )
        interpretation.assessment = {
            **interpretation.assessment,
            "project_identity_key": project.identity_key,
        }
        result = enrich_buying_chain(
            session,
            project.id,
            fetcher=lambda url: source(
                "Acme is the general contractor for Orion Data Center in Austin, TX."
            ),
            now=NOW,
        )
        candidate = result["candidates"][0]
        claim = session.get(BuyingChainClaim, candidate["id"])
        assert claim is not None
        assert candidate["company_identity_id"]
        claim.citations = [
            {
                **citation,
                "supports": (
                    "organization_category"
                    if citation["supports"] == "project_organization"
                    else citation["supports"]
                ),
            }
            for citation in claim.citations
        ]
        project_id, claim_id = project.id, claim.id
    client = TestClient(api.app)
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    response = client.get(f"/api/projects/{project_id}/buying-chain")
    assert response.status_code == 200, response.text
    readback = next(item for item in response.json()["candidates"] if item["id"] == str(claim_id))
    assert readback["stale"] is False
    assert readback["company_identity_id"] is None
    assert readback["person_identity_id"] is None


def test_sparse_corrections_compose_and_corrected_contact_replaces_actionable_method():
    claim_id = UUID("00000000-0000-0000-0000-000000000010")
    first_source = UUID("00000000-0000-0000-0000-000000000011")
    second_source = UUID("00000000-0000-0000-0000-000000000012")
    first_quote = "Acme is the prior company; call 512-555-0100."
    second_quote = "Call Beta at 512-555-0199."
    corrections = [
        SimpleNamespace(
            id=UUID("00000000-0000-0000-0000-000000000021"),
            claim_id=claim_id,
            project_id=UUID("00000000-0000-0000-0000-000000000030"),
            action="correct",
            values={"organization": "Beta"},
            source_evidence_id=first_source,
            source_version_hash="a" * 64,
            created_at=NOW,
            expected_version="initial",
            idempotency_key="first",
            reason="Correction one",
            actor="operator",
        ),
        SimpleNamespace(
            id=UUID("00000000-0000-0000-0000-000000000022"),
            claim_id=claim_id,
            project_id=UUID("00000000-0000-0000-0000-000000000030"),
            action="correct",
            values={"public_contact_kind": "phone", "public_contact_value": "512-555-0199"},
            source_evidence_id=second_source,
            source_version_hash="b" * 64,
            created_at=NOW + timedelta(seconds=1),
            expected_version="00000000-0000-0000-0000-000000000021",
            idempotency_key="second",
            reason="Correction two",
            actor="operator",
        ),
        SimpleNamespace(
            id=UUID("00000000-0000-0000-0000-000000000023"),
            claim_id=claim_id,
            project_id=UUID("00000000-0000-0000-0000-000000000030"),
            action="correct",
            values={"title": "Unsupported stale title"},
            source_evidence_id=UUID("00000000-0000-0000-0000-000000000013"),
            source_version_hash="c" * 64,
            created_at=NOW + timedelta(seconds=2),
            expected_version="00000000-0000-0000-0000-000000000022",
            idempotency_key="stale-third",
            reason="Stale correction source",
            actor="operator",
        ),
    ]
    candidate = {
        "id": claim_id,
        "fingerprint": "initial",
        "organization": "Acme",
        "person_name": None,
        "title": None,
        "category": "general_contractor",
        "organization_relationship": "DIRECT",
        "reason": "Current source supports the company.",
        "public_contacts": [
            {
                "kind": "phone",
                "value": "512-555-0100",
                "source_url": "https://news.example/old",
                "quote": first_quote,
            }
        ],
        "evidence": [
            {
                "id": first_source,
                "current_source_version_id": first_source,
                "content_hash": "a" * 64,
                "current_support": True,
                "supports": "public_contact",
                "public_research_provenance": True,
                "url": "https://news.example/old",
                "quote": first_quote,
            },
            {
                "id": second_source,
                "current_source_version_id": second_source,
                "content_hash": "b" * 64,
                "current_support": True,
                "supports": "public_contact",
                "public_research_provenance": True,
                "url": "https://news.example/new",
                "quote": second_quote,
            },
        ],
        "stale": False,
    }
    base_candidate = deepcopy(candidate)
    changed_subject = deepcopy(candidate)
    overlay_corrections(
        None,
        UUID("00000000-0000-0000-0000-000000000030"),
        [changed_subject],
        False,
        decisions=corrections[:1],
    )
    assert changed_subject["organization"] == "Beta"
    assert contact_projection({"candidates": [changed_subject]})[0].methods == []
    overlay_corrections(
        None, UUID("00000000-0000-0000-0000-000000000030"), [candidate], True, decisions=corrections
    )
    assert candidate["organization"] == "Beta"
    assert candidate["category"] == "general_contractor"
    assert candidate["correction_stale"] is True
    assert candidate["correction_version"] == str(corrections[-1].id)
    assert candidate["title"] is None
    assert candidate["public_contacts"] == [
        {
            "kind": "phone",
            "value": "512-555-0199",
            "source_url": "https://news.example/new",
            "quote": second_quote,
            "observed_at": None,
            "operator_report": False,
        }
    ]
    methods = contact_projection({"candidates": [candidate]})[0].methods
    assert [method["href"] for method in methods] == ["tel:5125550199"]

    stale_subject_to_contact = deepcopy(base_candidate)
    stale_subject_to_contact["evidence"][0]["current_support"] = False
    stale_subject_to_contact["evidence"][0]["current_source_version_id"] = UUID(
        "00000000-0000-0000-0000-000000000099"
    )
    overlay_corrections(
        None,
        UUID("00000000-0000-0000-0000-000000000030"),
        [stale_subject_to_contact],
        True,
        decisions=corrections[:2],
    )
    assert stale_subject_to_contact["organization"] == "Acme"
    assert stale_subject_to_contact["correction_stale"] is True
    assert stale_subject_to_contact["correction_version"] == str(corrections[1].id)
    assert [item["value"] for item in stale_subject_to_contact["public_contacts"]] == [
        "512-555-0100"
    ]
    assert len(stale_subject_to_contact["correction_history"]) == 2

    stale_retraction = SimpleNamespace(**vars(corrections[1]))
    stale_retraction.id = UUID("00000000-0000-0000-0000-000000000025")
    stale_retraction.action = "retract"
    stale_retraction.values = {"contact_status": "operator_report"}
    stale_retraction.expected_version = str(corrections[0].id)
    stale_subject_to_retraction = deepcopy(base_candidate)
    stale_subject_to_retraction["evidence"][0]["current_support"] = False
    overlay_corrections(
        None,
        UUID("00000000-0000-0000-0000-000000000030"),
        [stale_subject_to_retraction],
        True,
        decisions=[corrections[0], stale_retraction],
    )
    assert stale_subject_to_retraction["organization"] == "Acme"
    assert stale_subject_to_retraction.get("retracted", False) is False
    assert stale_subject_to_retraction["correction_stale"] is True
    assert stale_subject_to_retraction["correction_version"] == str(stale_retraction.id)
    assert len(stale_subject_to_retraction["correction_history"]) == 2

    unsupported = deepcopy(candidate)
    unsupported["public_contacts"] = [
        {
            "kind": "phone",
            "value": "512-555-0100",
            "source_url": "https://news.example/old",
            "quote": first_quote,
        }
    ]
    unsupported["evidence"][-1]["supports"] = "project_organization"
    unsupported_row = SimpleNamespace(**vars(corrections[1]))
    unsupported_row.id = UUID("00000000-0000-0000-0000-000000000024")
    unsupported_row.expected_version = "initial"
    unsupported_row.values = {
        "public_contact_kind": "phone",
        "public_contact_value": "512-555-0177",
    }
    overlay_corrections(
        None,
        UUID("00000000-0000-0000-0000-000000000030"),
        [unsupported],
        False,
        decisions=[unsupported_row],
    )
    assert unsupported["public_contacts"] == []
    assert contact_projection({"candidates": [unsupported]})[0].methods == []


def test_contact_only_decision_does_not_clear_retraction():
    claim_id = UUID("00000000-0000-0000-0000-000000000050")
    project_id = UUID("00000000-0000-0000-0000-000000000051")
    retract_id = UUID("00000000-0000-0000-0000-000000000052")
    report_id = UUID("00000000-0000-0000-0000-000000000053")
    retract = SimpleNamespace(
        id=retract_id,
        claim_id=claim_id,
        project_id=project_id,
        action="retract",
        values={},
        source_evidence_id=None,
        source_version_hash=None,
        expected_version="initial",
        created_at=NOW,
        idempotency_key="retract",
        reason="Relationship withdrawn",
        actor="operator",
    )
    report = SimpleNamespace(
        id=report_id,
        claim_id=claim_id,
        project_id=project_id,
        action="correct",
        values={
            "public_contact_kind": "phone",
            "public_contact_value": "512-555-0199",
            "contact_status": "operator_report",
        },
        source_evidence_id=None,
        source_version_hash=None,
        expected_version=str(retract_id),
        created_at=NOW + timedelta(seconds=1),
        idempotency_key="contact-after-retract",
        reason="Contact supplied after withdrawal",
        actor="operator",
    )
    candidate = {
        "id": claim_id,
        "fingerprint": "initial",
        "organization": "Acme",
        "public_contacts": [],
        "reported_contacts": [],
        "evidence": [],
    }

    overlay_corrections(None, project_id, [candidate], False, decisions=[retract, report])

    assert candidate["retracted"] is True
    assert candidate["reported_contacts"][0]["value"] == "512-555-0199"


def test_operator_report_replaces_same_kind_current_report_without_action():
    claim_id = UUID("00000000-0000-0000-0000-000000000040")
    row = SimpleNamespace(
        id=UUID("00000000-0000-0000-0000-000000000041"),
        claim_id=claim_id,
        project_id=UUID("00000000-0000-0000-0000-000000000042"),
        action="correct",
        values={
            "public_contact_kind": "phone",
            "public_contact_value": "512-555-0199",
            "contact_status": "operator_report",
        },
        source_evidence_id=None,
        source_version_hash=None,
        created_at=NOW,
        expected_version="initial",
        idempotency_key="new-report",
        reason="Operator confirmed a new number.",
        actor="operator",
    )
    candidate = {
        "id": claim_id,
        "fingerprint": "initial",
        "organization": "Acme",
        "person_name": None,
        "title": None,
        "category": "general_contractor",
        "organization_relationship": "DIRECT",
        "reason": "Current source supports the company.",
        "public_contacts": [
            {
                "kind": "phone",
                "value": "512-555-0100",
                "source_url": URL,
                "quote": "Call 512-555-0100 and email ops@example.com.",
            },
            {
                "kind": "email",
                "value": "ops@example.com",
                "source_url": URL,
                "quote": "Call 512-555-0100 and email ops@example.com.",
            },
        ],
        "reported_contacts": [{"kind": "phone", "value": "512-555-0100"}],
        "evidence": [
            {
                "id": UUID("00000000-0000-0000-0000-000000000043"),
                "current_support": True,
                "supports": "public_contact",
                "public_research_provenance": True,
                "url": URL,
                "quote": "Call 512-555-0100 and email ops@example.com.",
            }
        ],
        "stale": False,
    }
    overlay_corrections(None, row.project_id, [candidate], False, decisions=[row])
    assert candidate["reported_contacts"] == [
        {
            "kind": "phone",
            "value": "512-555-0199",
            "source_url": "",
            "quote": "",
            "operator_report": True,
        }
    ]
    assert [contact["value"] for contact in candidate["public_contacts"]] == ["ops@example.com"]
    assert [
        method["href"] for method in contact_projection({"candidates": [candidate]})[0].methods
    ] == ["mailto:ops@example.com"]


def test_null_contact_clear_is_scoped_by_kind_and_unscoped_clear_removes_all():
    claim_id = UUID("00000000-0000-0000-0000-000000000050")
    evidence_id = UUID("00000000-0000-0000-0000-000000000051")
    row = SimpleNamespace(
        id=UUID("00000000-0000-0000-0000-000000000052"),
        claim_id=claim_id,
        project_id=UUID("00000000-0000-0000-0000-000000000053"),
        action="correct",
        values={"public_contact_kind": "phone", "public_contact_value": None},
        source_evidence_id=evidence_id,
        source_version_hash="a" * 64,
        created_at=NOW,
        expected_version="initial",
        idempotency_key="clear-phone",
        reason="Operator cleared an obsolete phone action.",
        actor="operator",
    )
    base = {
        "id": claim_id,
        "fingerprint": "initial",
        "organization": "Acme",
        "organization_relationship": "DIRECT",
        "public_contacts": [
            {
                "kind": "phone",
                "value": "512-555-0100",
                "source_url": URL,
                "quote": "Call 512-555-0100 and email ops@example.com.",
            },
            {
                "kind": "email",
                "value": "ops@example.com",
                "source_url": URL,
                "quote": "Call 512-555-0100 and email ops@example.com.",
            },
        ],
        "reported_contacts": [],
        "evidence": [
            {
                "id": evidence_id,
                "current_source_version_id": evidence_id,
                "content_hash": "a" * 64,
                "current_support": True,
                "supports": "public_contact",
                "public_research_provenance": True,
                "url": URL,
                "quote": "Call 512-555-0100 and email ops@example.com.",
            }
        ],
        "stale": False,
    }
    scoped = deepcopy(base)
    overlay_corrections(None, row.project_id, [scoped], False, decisions=[row])
    assert [item["kind"] for item in scoped["public_contacts"]] == ["email"]
    assert [
        method["href"] for method in contact_projection({"candidates": [scoped]})[0].methods
    ] == ["mailto:ops@example.com"]

    unscoped = deepcopy(base)
    unscoped_clear = SimpleNamespace(**vars(row))
    unscoped_clear.id = UUID("00000000-0000-0000-0000-000000000054")
    unscoped_clear.values = {"public_contact_value": None}
    overlay_corrections(None, row.project_id, [unscoped], False, decisions=[unscoped_clear])
    assert unscoped["public_contacts"] == []
    assert contact_projection({"candidates": [unscoped]})[0].methods == []

    blank = deepcopy(base)
    blank_clear = SimpleNamespace(**vars(row))
    blank_clear.id = UUID("00000000-0000-0000-0000-000000000055")
    blank_clear.values = {"public_contact_kind": "phone", "public_contact_value": " "}
    overlay_corrections(None, row.project_id, [blank], False, decisions=[blank_clear])
    assert [item["kind"] for item in blank["public_contacts"]] == ["email"]


def test_stale_correction_chain_hides_later_company_and_person_rebinds(db):
    with db.begin() as session:
        project = seed(session, external_id="stale-identity-chain")
        old_source = BuyingChainEvidence(
            project_id=project.id,
            url="https://news.example/old-role",
            title="Old role statement",
            excerpt="Acme is the general contractor for Orion Data Center in Austin, TX.",
            content_hash="a" * 64,
            extraction_location="article body",
            published_at=date(2026, 9, 20),
            observed_at=NOW,
            last_seen_at=NOW + timedelta(days=1),
            project_match_reason="named project",
        )
        changed_source = BuyingChainEvidence(
            project_id=project.id,
            url="https://news.example/old-role",
            title="Updated role statement",
            excerpt="Acme is no longer the general contractor for Orion Data Center in Austin, TX.",
            content_hash="b" * 64,
            extraction_location="article body",
            published_at=date(2026, 9, 21),
            observed_at=NOW + timedelta(days=1),
            last_seen_at=NOW + timedelta(days=3),
            project_match_reason="named project",
        )
        current_source = BuyingChainEvidence(
            project_id=project.id,
            url="https://news.example/current-role",
            title="Current role statement",
            excerpt=(
                "Acme is the general contractor for Orion Data Center in Austin, TX. "
                "Alice Smith is Project Director at Acme for Orion Data Center in Austin, TX."
            ),
            content_hash="c" * 64,
            extraction_location="article body",
            published_at=date(2026, 9, 22),
            observed_at=NOW + timedelta(days=2),
            last_seen_at=NOW + timedelta(days=2),
            project_match_reason="named project",
        )
        session.add_all([old_source, changed_source, current_source])
        company = CompanyIdentity()
        person = PersonIdentity()
        session.add_all([company, person])
        session.flush()
        claim = BuyingChainClaim(
            project_id=project.id,
            entity_key="stale-identity-claim",
            fingerprint="f" * 64,
            policy_version="test",
            organization="Acme",
            person_name="Alice Smith",
            title="Project Director",
            category="general_contractor",
            organization_relationship="DIRECT",
            person_organization_relationship="CURRENT",
            person_project_relationship="ROLE_SUPPORTED",
            evidence_strength="Medium",
            reason="Current cited project role.",
            citations=[
                {
                    "evidence_id": str(old_source.id),
                    "url": old_source.url,
                    "quote": "Acme is the general contractor for Orion Data Center in Austin, TX.",
                    "supports": "project_organization",
                },
                {
                    "evidence_id": str(current_source.id),
                    "url": current_source.url,
                    "quote": "Acme is the general contractor for Orion Data Center in Austin, TX.",
                    "supports": "project_organization",
                },
                {
                    "evidence_id": str(current_source.id),
                    "url": current_source.url,
                    "quote": (
                        "Alice Smith is Project Director at Acme for Orion Data Center "
                        "in Austin, TX."
                    ),
                    "supports": "organization_person_role",
                },
            ],
            public_contacts=[],
            observed_at=NOW,
        )
        session.add(claim)
        session.flush()
        session.add_all(
            [
                BuyingChainIdentityLink(
                    claim_id=claim.id,
                    entity_type="company",
                    company_identity_id=company.id,
                    reason="reviewed company",
                    basis="reviewed_alias",
                    reviewed_by="operator",
                    source_evidence_id=current_source.id,
                    source_version_hash=current_source.content_hash,
                    state="current",
                ),
                BuyingChainIdentityLink(
                    claim_id=claim.id,
                    entity_type="person",
                    person_identity_id=person.id,
                    reason="reviewed person",
                    basis="reviewed_alias",
                    reviewed_by="operator",
                    source_evidence_id=current_source.id,
                    source_version_hash=current_source.content_hash,
                    state="current",
                ),
            ]
        )
        session.add_all(
            [
                BuyingChainCorrection(
                    project_id=project.id,
                    claim_id=claim.id,
                    expected_version=claim.fingerprint,
                    idempotency_key="stale-first",
                    action="correct",
                    values={"category": "electrical_contractor"},
                    source_evidence_id=old_source.id,
                    source_version_hash=old_source.content_hash,
                    reason="Older cited role is stale.",
                    actor="operator",
                    created_at=NOW,
                ),
                BuyingChainCorrection(
                    project_id=project.id,
                    claim_id=claim.id,
                    expected_version="stale-first",
                    idempotency_key="late-company-rebind",
                    action="correct",
                    values={
                        "organization": "Beta",
                        "identity_reference": {"type": "company", "id": str(company.id)},
                    },
                    source_evidence_id=current_source.id,
                    source_version_hash=current_source.content_hash,
                    reason="Later company rebind.",
                    actor="operator",
                    created_at=NOW + timedelta(seconds=1),
                ),
                BuyingChainCorrection(
                    project_id=project.id,
                    claim_id=claim.id,
                    expected_version="late-company-rebind",
                    idempotency_key="late-person-rebind",
                    action="correct",
                    values={
                        "person_name": "Bob Jones",
                        "identity_reference": {"type": "person", "id": str(person.id)},
                    },
                    source_evidence_id=current_source.id,
                    source_version_hash=current_source.content_hash,
                    reason="Later person rebind.",
                    actor="operator",
                    created_at=NOW + timedelta(seconds=2),
                ),
            ]
        )
        session.add(
            BuyingChainRun(
                project_id=project.id,
                input_hash="d" * 64,
                evidence_ids=[str(old_source.id), str(current_source.id)],
                claim_ids=[str(claim.id)],
                policy_version="test",
                status="completed",
                documents_checked=2,
                candidates_added=1,
                unresolved=[],
                created_at=NOW + timedelta(days=2),
            )
        )
        project_id, claim_id = project.id, claim.id

    with db.begin() as session:
        normal = buying_chain_view(session, project_id)
        normal_item = next(item for item in normal["candidates"] if item["id"] == claim_id)
        assert normal_item["correction_stale"] is True
        assert normal_item.get("company_identity_id") is None
        assert normal_item.get("person_identity_id") is None
        batch = buying_chain_views(session, {project_id})[str(project_id)]
        batch_item = next(item for item in batch["candidates"] if item["id"] == claim_id)
        assert batch_item["correction_stale"] is True
        assert batch_item.get("company_identity_id") is None
        assert batch_item.get("person_identity_id") is None


def test_correction_order_follows_expected_version_links_and_rejects_forks():
    first_id = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
    second_id = UUID("00000000-0000-0000-0000-000000000001")
    first = SimpleNamespace(id=first_id, expected_version="initial", created_at=NOW)
    second = SimpleNamespace(id=second_id, expected_version=str(first_id), created_at=NOW)
    assert _ordered_correction_chain("initial", [second, first]) == [first, second]

    fork = SimpleNamespace(
        id=UUID("00000000-0000-0000-0000-000000000002"),
        expected_version="initial",
        created_at=NOW,
    )
    assert _ordered_correction_chain("initial", [first, fork]) is None
    disconnected = SimpleNamespace(
        id=UUID("00000000-0000-0000-0000-000000000003"),
        expected_version="missing-version",
        created_at=NOW,
    )
    assert _ordered_correction_chain("initial", [disconnected]) is None


@pytest.mark.parametrize("sparse", [False, True])
@pytest.mark.parametrize("person_name", [None, "Jordan Lee"])
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Acme is the owner for Orion Data Center in Austin, TX. "
            "Beta delivered a chair to Orion Data Center in Austin, TX.",
            False,
        ),
        ("Beta is the owner for Orion Data Center in Austin, TX.", True),
    ],
)
def test_company_subject_change_revalidates_inherited_semantics(
    sparse, person_name, text, expected
):
    project_id = UUID("00000000-0000-0000-0000-000000000010")
    source_id = UUID("00000000-0000-0000-0000-000000000011")
    quote = text.split(". ")[0]
    project = SimpleNamespace(
        id=project_id,
        name="Orion Data Center",
        location="Austin, TX",
        identity_facts={},
        source_id="news",
    )
    source = SimpleNamespace(
        id=source_id,
        retained_evidence_id=None,
        url="https://news.example/orion",
        title="Orion update",
        excerpt=text,
        published_at=None,
        observed_at=NOW,
        extraction_location="article body",
        content_hash="a" * 64,
    )
    candidate = {
        "organization": "Acme",
        "person_name": person_name,
        "category": "owner_developer",
        "organization_relationship": "DIRECT",
        "person_organization_relationship": "DIRECT" if person_name else "UNKNOWN",
        "person_project_relationship": "DIRECT" if person_name else "UNKNOWN",
        "evidence": [
            {
                "id": source_id,
                "current_source_version_id": source_id,
                "content_hash": source.content_hash,
                "current_support": True,
                "quote": quote,
                "supports": "project_organization",
            }
        ],
    }

    class Session:
        def get(self, _model, key):
            return project if key == project_id else None

    values = {"organization": "Beta"}
    if not sparse:
        values.update(category="owner_developer", organization_relationship="DIRECT")
    assert _has_current_semantic_support(
        session=Session(),
        project_id=project_id,
        candidate=candidate,
        source=source,
        values=values,
    ) is (expected and person_name is None)


@pytest.mark.parametrize("cleared_name", [None, "   "])
def test_optional_person_clear_is_a_downgrade(cleared_name):
    project_id = UUID("00000000-0000-0000-0000-000000000020")
    source_id = UUID("00000000-0000-0000-0000-000000000021")
    project = SimpleNamespace(
        id=project_id,
        name="Orion Data Center",
        location="Austin, TX",
        identity_facts={},
        source_id="news",
    )
    source = SimpleNamespace(
        id=source_id,
        retained_evidence_id=None,
        url="https://news.example/orion",
        title="Orion update",
        excerpt="Acme owns Orion Data Center in Austin, TX.",
        published_at=None,
        observed_at=NOW,
        extraction_location="article body",
        content_hash="b" * 64,
    )
    candidate = {
        "organization": "Acme",
        "person_name": "Jordan Lee",
        "category": "owner_developer",
        "organization_relationship": "DIRECT",
        "person_organization_relationship": "UNKNOWN",
        "person_project_relationship": "UNKNOWN",
        "evidence": [
            {
                "id": source_id,
                "current_source_version_id": source_id,
                "content_hash": source.content_hash,
                "current_support": True,
                "quote": source.excerpt,
                "supports": "project_organization",
            }
        ],
    }

    class Session:
        def get(self, _model, key):
            return project if key == project_id else None

    assert _has_current_semantic_support(
        session=Session(),
        project_id=project_id,
        candidate=candidate,
        source=source,
        values={"person_name": cleared_name},
    )


@pytest.mark.parametrize(
    ("requested_title", "cite_person_title", "expected"),
    [
        ("Construction Director", True, False),
        ("Project Manager", True, True),
        ("Project Manager", False, False),
        (None, False, True),
        ("", False, True),
        ("   ", False, True),
    ],
)
def test_title_correction_binds_current_title_to_the_cited_person(
    requested_title, cite_person_title, expected
):
    project_id = UUID("00000000-0000-0000-0000-000000000030")
    source_id = UUID("00000000-0000-0000-0000-000000000031")
    organization_quote = "Acme is the general contractor for Orion Data Center in Austin, TX."
    alice_quote = "Alice Smith is Project Manager at Acme for Orion Data Center in Austin, TX."
    text = organization_quote + " " + alice_quote + " Bob Jones is Construction Director at Acme."
    project = SimpleNamespace(
        id=project_id,
        name="Orion Data Center",
        location="Austin, TX",
        identity_facts={},
        source_id="news",
    )
    source = SimpleNamespace(
        id=source_id,
        retained_evidence_id=None,
        url="https://news.example/team",
        title="Acme team",
        excerpt=text,
        published_at=date(2026, 10, 20),
        observed_at=NOW,
        extraction_location="team page",
        content_hash="c" * 64,
    )
    candidate_evidence = [
        {
            "id": source_id,
            "current_source_version_id": source_id,
            "content_hash": source.content_hash,
            "current_support": True,
            "quote": organization_quote,
            "supports": "project_organization",
        }
    ]
    if cite_person_title:
        candidate_evidence.append(
            {
                "id": source_id,
                "current_source_version_id": source_id,
                "content_hash": source.content_hash,
                "current_support": True,
                "quote": alice_quote,
                "supports": "organization_person_role",
            }
        )
    candidate = {
        "organization": "Acme",
        "person_name": "Alice Smith",
        "title": "Assistant Project Manager",
        "evidence": candidate_evidence,
    }

    class Session:
        def get(self, _model, key):
            return project if key == project_id else None

    assert (
        _has_current_semantic_support(
            session=Session(),
            project_id=project_id,
            candidate=candidate,
            source=source,
            values={"title": requested_title},
        )
        is expected
    )


@pytest.mark.parametrize(
    (
        "organization_excerpt",
        "cited_organization_quote",
        "organization_project_id",
        "organization_current",
        "expected",
    ),
    [
        (
            "Acme is the general contractor for Orion Data Center in Austin, TX.",
            "Acme is the general contractor for Orion Data Center in Austin, TX.",
            UUID("00000000-0000-0000-0000-000000000030"),
            True,
            True,
        ),
        (
            "Acme is the general contractor for Orion Data Center in Austin, TX.",
            "Acme is the general contractor for Orion Data Center in Austin, TX.",
            UUID("00000000-0000-0000-0000-000000000099"),
            True,
            False,
        ),
        (
            "Beta is the general contractor for Orion Data Center in Austin, TX.",
            "Beta is the general contractor for Orion Data Center in Austin, TX.",
            UUID("00000000-0000-0000-0000-000000000030"),
            True,
            False,
        ),
        (
            "Acme is the general contractor for Orion Data Center in Austin, TX.",
            "Acme is the general contractor for Orion Data Center in Austin, TX.",
            UUID("00000000-0000-0000-0000-000000000030"),
            False,
            False,
        ),
        (
            "Beta is the general contractor for Orion Data Center in Austin, TX. "
            "Acme is the general contractor for Orion Data Center in Austin, TX.",
            "Beta is the general contractor for Orion Data Center in Austin, TX.",
            UUID("00000000-0000-0000-0000-000000000030"),
            True,
            False,
        ),
    ],
)
def test_title_correction_reuses_only_current_same_project_organization_support(
    organization_excerpt,
    cited_organization_quote,
    organization_project_id,
    organization_current,
    expected,
):
    project_id = UUID("00000000-0000-0000-0000-000000000030")
    roster_source_id = UUID("00000000-0000-0000-0000-000000000031")
    organization_source_id = UUID("00000000-0000-0000-0000-000000000032")
    roster_quote = "Alice Smith, President"
    project = SimpleNamespace(
        id=project_id,
        name="Orion Data Center",
        location="Austin, TX",
        identity_facts={},
        source_id="news",
    )
    roster_source = SimpleNamespace(
        id=roster_source_id,
        retained_evidence_id=None,
        url="https://acme.com/team",
        title="Acme team",
        excerpt=roster_quote,
        published_at=None,
        observed_at=NOW,
        extraction_location="team page",
        content_hash="c" * 64,
    )
    organization_source = SimpleNamespace(
        id=organization_source_id,
        project_id=organization_project_id,
        retained_evidence_id=None,
        url="https://news.example/orion",
        title="Orion Data Center project team",
        excerpt=organization_excerpt,
        published_at=date(2026, 10, 20),
        observed_at=NOW,
        extraction_location="project team",
        content_hash="d" * 64,
    )
    candidate = {
        "organization": "Acme",
        "person_name": "Alice Smith",
        "title": None,
        "evidence": [
            {
                "id": roster_source_id,
                "current_source_version_id": roster_source_id,
                "content_hash": roster_source.content_hash,
                "current_support": True,
                "url": roster_source.url,
                "quote": roster_quote,
                "supports": "organization_person_role",
            },
            {
                "id": organization_source_id,
                "current_source_version_id": organization_source_id,
                "content_hash": organization_source.content_hash,
                "current_support": organization_current,
                "url": organization_source.url,
                "quote": cited_organization_quote,
                "supports": "project_organization",
            },
        ],
    }

    class Session:
        def get(self, _model, key):
            if key == project_id:
                return project
            if key == organization_source_id:
                return organization_source
            return None

    assert (
        _has_current_semantic_support(
            session=Session(),
            project_id=project_id,
            candidate=candidate,
            source=roster_source,
            values={"title": "President"},
        )
        is expected
    )


@pytest.mark.parametrize(
    ("entity_type", "subject_field", "support"),
    [
        ("company", "organization", "project_organization"),
        ("person", "person_name", "organization_person_role"),
    ],
)
def test_identity_attachment_uses_expected_version_order_for_equal_timestamps(
    entity_type, subject_field, support
):
    claim_id = UUID("00000000-0000-0000-0000-000000000010")
    source_id = UUID("00000000-0000-0000-0000-000000000011")
    identity_id = UUID("00000000-0000-0000-0000-000000000012")
    first_id = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
    second_id = UUID("00000000-0000-0000-0000-000000000001")
    first = SimpleNamespace(
        id=first_id,
        claim_id=claim_id,
        expected_version="initial",
        created_at=NOW,
        source_evidence_id=source_id,
        source_version_hash="a" * 64,
        values={subject_field: "Updated subject"},
    )
    second = SimpleNamespace(
        id=second_id,
        claim_id=claim_id,
        expected_version=str(first_id),
        created_at=NOW,
        source_evidence_id=source_id,
        source_version_hash="a" * 64,
        values={"identity_reference": {"type": entity_type, "id": str(identity_id)}},
    )
    link = SimpleNamespace(
        id=UUID("00000000-0000-0000-0000-000000000013"),
        claim_id=claim_id,
        entity_type=entity_type,
        company_identity_id=identity_id if entity_type == "company" else None,
        person_identity_id=identity_id if entity_type == "person" else None,
        source_evidence_id=source_id,
        source_version_hash="a" * 64,
        created_at=NOW,
    )
    candidate = {
        "id": claim_id,
        "fingerprint": "initial",
        "stale": False,
        "evidence": [
            {
                "id": source_id,
                "current_source_version_id": source_id,
                "content_hash": "a" * 64,
                "current_support": True,
                "supports": support,
            }
        ],
    }

    class Result:
        def __init__(self, rows):
            self.rows = rows

        def all(self):
            return self.rows

    class Session:
        calls = 0

        def scalars(self, _query):
            self.calls += 1
            # This is the actual SQL secondary order: it reverses the valid
            # API chain when the UUIDs share a timestamp.
            rows = (
                [link]
                if self.calls == 1
                else sorted([first, second], key=lambda row: (row.created_at, row.id))
            )
            return Result(rows)

    _attach_identity_ids(Session(), [{"candidates": [candidate]}])
    assert candidate[f"{entity_type}_identity_id"] == str(identity_id)


def test_corrected_company_hides_old_identity_until_reviewed_rebind_and_keeps_rebind(db):
    with db.begin() as session:
        project = seed(
            session, external_id="identity-correction", identity_key="identity-correction"
        )
        interpretation = session.scalar(
            select(Interpretation).where(
                Interpretation.observation_id
                == session.scalar(
                    select(Observation.id).where(Observation.external_id == "identity-correction")
                )
            )
        )
        interpretation.assessment = {
            **interpretation.assessment,
            "project_identity_key": project.identity_key,
        }
        result = enrich_buying_chain(
            session,
            project.id,
            fetcher=lambda url: source(
                "Acme is the general contractor for Orion Data Center in Austin, TX."
            ),
            now=NOW,
        )
        candidate = result["candidates"][0]
        claim = session.get(BuyingChainClaim, candidate["id"])
        evidence = session.get(BuyingChainEvidence, candidate["evidence"][0]["id"])
        replacement_quote = "Beta is the general contractor for Orion Data Center in Austin, TX."
        evidence.excerpt += " " + replacement_quote
        claim.citations = [
            *claim.citations,
            {
                "evidence_id": str(evidence.id),
                "url": evidence.url,
                "quote": replacement_quote,
                "supports": "project_organization",
            },
        ]
        old_identity = CompanyIdentity()
        new_identity = CompanyIdentity()
        session.add_all([old_identity, new_identity])
        session.flush()
        link_claim_to_identity(
            session,
            claim,
            "company",
            old_identity.id,
            evidence,
            "Previously reviewed company identity.",
            reviewed_by="operator",
        )
        first = correct_buying_chain_claim(
            session,
            project_id=project.id,
            claim_id=claim.id,
            expected_version=candidate["fingerprint"],
            idempotency_key="subject-change",
            action="correct",
            values={"organization": "Beta"},
            source_evidence_id=evidence.id,
            source_hash=evidence.content_hash,
            reason="Corrected organization from current source.",
            actor="operator",
        )
        changed = buying_chain_view(session, project.id)["candidates"][0]
        assert changed["organization"] == "Beta"
        assert "company_identity_id" not in changed
        old_link = session.scalar(
            select(BuyingChainIdentityLink).where(
                BuyingChainIdentityLink.claim_id == claim.id,
                BuyingChainIdentityLink.entity_type == "company",
                BuyingChainIdentityLink.company_identity_id == old_identity.id,
            )
        )
        assert old_link.state == "superseded"
        assert old_link.superseded_at is not None

        rebound = correct_buying_chain_claim(
            session,
            project_id=project.id,
            claim_id=claim.id,
            expected_version=str(first.id),
            idempotency_key="reviewed-rebind",
            action="correct",
            values={},
            source_evidence_id=evidence.id,
            source_hash=evidence.content_hash,
            reason="Reviewed the corrected company identity.",
            actor="operator",
            identity_type="company",
            identity_id=new_identity.id,
        )
        correct_buying_chain_claim(
            session,
            project_id=project.id,
            claim_id=claim.id,
            expected_version=str(rebound.id),
            idempotency_key="later-contact-report",
            action="correct",
            values={"public_contact_kind": "phone", "public_contact_value": "512-555-0199"},
            source_evidence_id=None,
            source_hash=None,
            reason="Operator reported a current contact.",
            actor="operator",
            reported_contact=True,
        )
        current = buying_chain_view(session, project.id)["candidates"][0]
        assert current["company_identity_id"] == str(new_identity.id)


def test_chicago_default_exact_id_fetch_and_contractors_without_supplied_url(db):
    with db.begin() as session:
        session.add(
            Source(
                id="chicago-building-permits",
                publisher="City of Chicago",
                endpoint="https://data.cityofchicago.org/resource/ydr8-5enu.json",
                family="permit",
                geography="Chicago",
                industries=[],
                retrieval_method="socrata",
                health={},
            )
        )
        session.flush()
        p = Project(
            source_id="chicago-building-permits",
            external_id="42",
            name="Chicago permit 42",
            location="333 E HURON ST, Chicago, IL",
            identity_key="chicago42",
            identity_facts={},
        )
        session.add(p)
        session.flush()
        seen = []

        def fetch(url):
            seen.append(url)
            return parse_document(
                url,
                b'[{"id":"42","street_number":"333","street_direction":"E",'
                b'"street_name":"HURON ST","contact_2_type":"CONTRACTOR-ELECTRICAL",'
                b'"contact_2_name":"ACME"}]',
                "application/json",
            )

        result = enrich_buying_chain(session, p.id, fetcher=fetch)
        assert len(seen) == 1 and "%2742%27" in seen[0]
        assert result["candidates"][0]["category"] == "electrical_contractor"
        assert result["candidates"][0]["evidence"][0]["published_at"] is None


def test_unchanged_recheck_updates_last_seen_without_rewriting_evidence(db):
    with db.begin() as session:
        p = seed(session)
        text = "Acme is the general contractor for Orion Data Center in Austin, TX."
        enrich_buying_chain(session, p.id, fetcher=lambda url: source(text), now=NOW)
        retained = session.scalar(
            select(BuyingChainEvidence).where(BuyingChainEvidence.excerpt == text)
        )
        identity = retained.id, retained.content_hash, retained.observed_at, retained.published_at
        before = counts(session)
        later = NOW + timedelta(days=2)
        enrich_buying_chain(
            session, p.id, fetcher=lambda url: source(text, observed=later), now=later
        )
        assert counts(session) == before
        assert identity == (
            retained.id,
            retained.content_hash,
            retained.observed_at,
            retained.published_at,
        )
        assert retained.last_seen_at == later


def test_conflict_from_unavailable_independent_source_remains_then_retraction_resolves(db):
    with db.begin() as session:
        p = seed(session)
        org_text = "Acme is the general contractor for Orion Data Center in Austin, TX."
        first_url, second_url = "https://acme.com/team", "https://acme.com/leadership"
        documents = {
            URL: source(org_text),
            first_url: PublicDocument(
                first_url,
                "Acme team",
                "Alice Smith is Project Director at Acme.",
                date(2026, 9, 20),
                NOW,
            ),
            second_url: PublicDocument(
                second_url,
                "Acme leadership",
                "Alice Smith is Construction Director at Acme.",
                date(2026, 9, 20),
                NOW,
            ),
        }
        enrich_buying_chain(
            session, p.id, source_urls=[first_url], fetcher=documents.__getitem__, now=NOW
        )

        def second_fetch(url):
            if url == first_url:
                raise TimeoutError("Synthetic source outage does not retract prior evidence")
            return documents[url]

        result = enrich_buying_chain(
            session,
            p.id,
            source_urls=[second_url],
            fetcher=second_fetch,
            now=NOW + timedelta(minutes=1),
        )
        person = next(c for c in result["candidates"] if c["person_name"])
        assert person["person_organization_relationship"] == "UNKNOWN"
        assert person["person_project_relationship"] == "UNKNOWN"
        assert "Conflicting independent role evidence" in person["reason"]
        assert {e["url"] for e in person["evidence"]} >= {first_url, second_url}
        assert person["organization_relationship"] == "DIRECT"
        documents[first_url] = PublicDocument(
            first_url,
            "Acme team",
            "This public team page no longer lists any relevant role.",
            None,
            NOW + timedelta(minutes=2),
        )
        resolved = enrich_buying_chain(
            session,
            p.id,
            source_urls=[second_url, first_url],
            fetcher=documents.__getitem__,
            now=NOW + timedelta(minutes=2),
        )
        person = next(c for c in resolved["candidates"] if c["person_name"])
        assert person["person_organization_relationship"] == "CURRENT"
        assert person["person_project_relationship"] == "ROLE_SUPPORTED"
        assert not person["stale"]
        assert (
            session.scalar(
                select(func.count())
                .select_from(BuyingChainEvidence)
                .where(BuyingChainEvidence.url == first_url)
            )
            == 2
        )
        old_person = next(
            c
            for c in buying_chain_view(session, p.id, history=True)["candidates"]
            if c["person_name"] and c["title"] == "Project Director"
        )
        assert old_person["person_organization_relationship"] == "UNKNOWN"
        assert old_person["stale"]


def test_official_undated_roster_recheck_refreshes_role_without_new_claims(db):
    with db.begin() as session:
        p = seed(session)
        org_text = "Acme is the general contractor for Orion Data Center in Austin, TX."
        team_url = "https://acme.com/team"
        role_text = "Alice Smith, President"
        documents = {
            URL: source(org_text),
            team_url: PublicDocument(team_url, "Acme team", role_text, None, NOW),
        }
        enrich_buying_chain(
            session, p.id, source_urls=[team_url], fetcher=documents.__getitem__, now=NOW
        )
        later = NOW + timedelta(days=370)
        documents[team_url] = PublicDocument(team_url, "Acme team", role_text, None, later)
        result = enrich_buying_chain(
            session, p.id, source_urls=[team_url], fetcher=documents.__getitem__, now=later
        )
        person = next(c for c in result["candidates"] if c["person_name"])
        assert person["person_organization_relationship"] == "CURRENT"
        assert person["person_project_relationship"] == "ROLE_SUPPORTED"
        source_version = session.scalar(
            select(BuyingChainEvidence).where(BuyingChainEvidence.url == team_url)
        )
        assert source_version.published_at is None
        assert source_version.observed_at == NOW
        assert source_version.last_seen_at == later
        assert session.scalar(select(func.count()).select_from(BuyingChainClaim)) == 2


def test_dated_news_retrieval_does_not_rejuvenate_historical_role(db):
    with db.begin() as session:
        p = seed(session)
        text = (
            "Acme is the general contractor for Orion Data Center in Austin, TX.\n"
            "Alice Smith is Project Director at Acme."
        )
        enrich_buying_chain(session, p.id, fetcher=lambda url: source(text), now=NOW)
        later = NOW + timedelta(days=370)
        result = enrich_buying_chain(
            session, p.id, fetcher=lambda url: source(text, observed=later), now=later
        )
        person = next(c for c in result["candidates"] if c["person_name"])
        assert person["person_organization_relationship"] == "UNKNOWN"
        assert person["person_project_relationship"] == "UNKNOWN"
        assert person["stale"]
        assert {e["published_at"] for e in person["evidence"]} == {date(2026, 9, 20)}


def test_identical_text_distinct_publication_metadata_keeps_exact_citation_versions(db):
    with db.begin() as session:
        p = seed(session)
        retained = session.scalar(select(Evidence))
        retained.abstract = "Acme is the general contractor for Orion Data Center in Austin, TX."
        fetched = PublicDocument(
            URL,
            retained.title,
            f"{retained.title}\n{retained.abstract}",
            date(2026, 9, 21),
            NOW + timedelta(minutes=1),
        )
        result = enrich_buying_chain(
            session, p.id, fetcher=lambda url: fetched, now=NOW + timedelta(minutes=1)
        )
        organization = next(c for c in result["candidates"] if c["organization"] == "Acme")
        assert {e["published_at"] for e in organization["evidence"]} == {
            date(2026, 9, 20),
            date(2026, 9, 21),
        }
        assert len({e["id"] for e in organization["evidence"]}) == 2


@pytest.mark.parametrize("invalidation", ["reassigned", "rejected"])
@pytest.mark.parametrize("public_role_phrase", ["general contractor", "construction manager"])
def test_deduplicated_claim_keeps_independent_category_after_retained_reassignment(
    db, invalidation, public_role_phrase
):
    from gridlens.intelligence.change_detection import record_material_diff, seed_material_state

    with db.begin() as session:
        project = seed(session)
        retained = session.scalar(select(Evidence))
        interpretation = session.scalar(select(Interpretation))
        assert retained is not None and interpretation is not None
        retained.abstract = "Acme is the general contractor for Orion Data Center in Austin, TX."
        contact_quote = "Call Acme at 512-555-0100."
        public_org_quote = f"Acme is the {public_role_phrase} for Orion Data Center in Austin, TX."
        fetched = PublicDocument(
            URL,
            retained.title,
            f"{retained.title}\n{public_org_quote}\n{contact_quote}",
            date(2026, 9, 21),
            NOW + timedelta(minutes=1),
        )
        first = enrich_buying_chain(
            session,
            project.id,
            fetcher=lambda _url: fetched,
            now=NOW + timedelta(minutes=1),
        )
        contractor = next(c for c in first["candidates"] if c["organization"] == "Acme")
        assert contractor["organization_relationship"] == "DIRECT"
        assert len({row["id"] for row in contractor["evidence"]}) == 2
        claim_id = contractor["id"]
        stored_claim = session.get(BuyingChainClaim, claim_id)
        assert stored_claim is not None
        public_citation = next(
            citation
            for citation in stored_claim.citations
            if (
                session.get(BuyingChainEvidence, citation["evidence_id"]).retained_evidence_id
                is None
            )
        )
        stored_claim.citations = [
            *stored_claim.citations,
            {
                "evidence_id": public_citation["evidence_id"],
                "url": URL,
                "quote": contact_quote,
                "supports": "public_contact",
            },
        ]
        stored_claim.public_contacts = [
            {
                "kind": "phone",
                "value": "512-555-0100",
                "source_url": URL,
                "quote": contact_quote,
                "observed_at": NOW.isoformat(),
            }
        ]
        session.flush()
        baseline = seed_material_state(session, project)
        unrelated = Project(
            source_id="test",
            external_id="other",
            name="Other Data Center",
            location="Dallas, TX",
            identity_key="other-data-center",
            identity_facts={},
        )
        session.add(unrelated)
        session.flush()
        if invalidation == "reassigned":
            interpretation.assessment = {
                **interpretation.assessment,
                "project_identity_key": unrelated.identity_key,
            }
        else:
            interpretation.status = "rejected"
            interpretation.assessment = {
                **interpretation.assessment,
                "decision": "rejected",
            }
        session.flush()
        current = buying_chain_view(session, project.id, now=NOW + timedelta(minutes=1))
        assert [row["id"] for row in current["candidates"]] == [claim_id]
        survivor = current["candidates"][0]
        assert survivor["organization_relationship"] == "DIRECT"
        assert survivor["category"] == "general_contractor"
        assert survivor["stale"] is False
        assert len(survivor["evidence"]) == 2
        assert {row["supports"] for row in survivor["evidence"]} >= {
            "public_contact",
            "project_organization",
        }
        assert survivor["public_contacts"] == stored_claim.public_contacts
        survivor_source = session.get(BuyingChainEvidence, survivor["evidence"][0]["id"])
        assert survivor_source is not None and survivor_source.retained_evidence_id is None
        assert record_material_diff(session, project, retained, baseline) == []
        history = buying_chain_view(session, project.id, now=NOW, history=True)["candidates"]
        assert any(row["id"] == claim_id for row in history)


def test_partial_citation_survival_downgrades_role_and_excludes_all_invalid_claim(db):
    with db.begin() as session:
        project = seed(session)
        retained = session.scalar(select(Evidence))
        interpretation = session.scalar(select(Interpretation))
        assert retained is not None and interpretation is not None
        role_quote = "Alice Smith is Project Director at Acme for Orion Data Center."
        org_quote = "Acme is the general contractor for Orion Data Center."
        retained.abstract = f"{org_quote} {role_quote}"
        old_source = BuyingChainEvidence(
            project_id=project.id,
            retained_evidence_id=retained.id,
            url=retained.url,
            title=retained.title,
            excerpt=retained.abstract,
            content_hash=retained.content_hash,
            extraction_location="retained role",
            published_at=retained.published_at,
            observed_at=NOW,
            last_seen_at=NOW,
            project_match_reason="Earlier project binding.",
        )
        public_source = BuyingChainEvidence(
            project_id=project.id,
            url="https://acme.example/orion",
            title="Acme project page",
            excerpt=f"{org_quote} {role_quote}",
            content_hash="independent-org",
            extraction_location="public page",
            published_at=retained.published_at,
            observed_at=NOW,
            last_seen_at=NOW,
            project_match_reason="Exact named project.",
        )
        session.add_all([old_source, public_source])
        session.flush()

        def citation(source, quote, support):
            return {
                "evidence_id": str(source.id),
                "url": source.url,
                "quote": quote,
                "supports": support,
            }

        person = BuyingChainClaim(
            project_id=project.id,
            entity_key="acme-alice-partial",
            fingerprint="partial-person",
            policy_version="test",
            organization="Acme",
            person_name="Alice Smith",
            title="Project Director",
            category="general_contractor",
            organization_relationship="DIRECT",
            person_organization_relationship="CURRENT",
            person_project_relationship="ROLE_SUPPORTED",
            evidence_strength="High",
            reason="Earlier deduplicated claim.",
            citations=[
                citation(public_source, org_quote, "project_organization"),
                citation(public_source, org_quote, "organization_category"),
                citation(old_source, role_quote, "organization_person_role"),
                citation(old_source, role_quote, "public_contact"),
            ],
            public_contacts=[
                {
                    "kind": "email",
                    "value": "alice@example.test",
                    "source_url": old_source.url,
                    "quote": role_quote,
                    "observed_at": NOW.isoformat(),
                }
            ],
            observed_at=NOW,
        )
        invalid_only = BuyingChainClaim(
            project_id=project.id,
            entity_key="old-only",
            fingerprint="old-only",
            policy_version="test",
            organization="Old Only",
            person_name=None,
            title=None,
            category="general_contractor",
            organization_relationship="DIRECT",
            person_organization_relationship="UNKNOWN",
            person_project_relationship="UNKNOWN",
            evidence_strength="High",
            reason="Only the rebound retained record.",
            citations=[citation(old_source, role_quote, "organization_category")],
            public_contacts=[],
            observed_at=NOW,
        )
        role_only = BuyingChainClaim(
            project_id=project.id,
            entity_key="role-only",
            fingerprint="role-only",
            policy_version="test",
            organization="Role Only Co",
            person_name="Alice Smith",
            title="Project Director",
            category="general_contractor",
            organization_relationship="DIRECT",
            person_organization_relationship="CURRENT",
            person_project_relationship="ROLE_SUPPORTED",
            evidence_strength="High",
            reason="Historical project organization, independent current role.",
            citations=[
                citation(old_source, org_quote, "project_organization"),
                citation(public_source, role_quote, "organization_person_role"),
            ],
            public_contacts=[],
            observed_at=NOW,
        )
        assignment_loss = BuyingChainClaim(
            project_id=project.id,
            entity_key="assignment-loss",
            fingerprint="assignment-loss",
            policy_version="test",
            organization="Assignment Co",
            person_name="Alice Smith",
            title="Project Director",
            category="general_contractor",
            organization_relationship="DIRECT",
            person_organization_relationship="CURRENT",
            person_project_relationship="DIRECT",
            evidence_strength="High",
            reason="Independent role with prior direct assignment.",
            citations=[
                citation(public_source, org_quote, "project_organization"),
                citation(public_source, org_quote, "organization_category"),
                citation(public_source, role_quote, "organization_person_role"),
                citation(old_source, role_quote, "person_project_assignment"),
            ],
            public_contacts=[],
            observed_at=NOW,
        )
        session.add_all([person, invalid_only, role_only, assignment_loss])
        session.flush()
        session.add(
            BuyingChainRun(
                project_id=project.id,
                input_hash="partial-run",
                evidence_ids=[str(old_source.id), str(public_source.id)],
                claim_ids=[
                    str(person.id),
                    str(invalid_only.id),
                    str(role_only.id),
                    str(assignment_loss.id),
                ],
                policy_version="test",
                status="complete",
                documents_checked=2,
                candidates_added=4,
                unresolved=[],
            )
        )
        session.flush()
        interpretation.assessment = {
            **interpretation.assessment,
            "project_identity_key": "another-project",
        }
        session.flush()
        current = buying_chain_view(session, project.id, now=NOW)["candidates"]
        by_claim = {row["id"]: row for row in current}
        assert set(by_claim) == {person.id, role_only.id, assignment_loss.id}
        partial = by_claim[person.id]
        assert partial["organization_relationship"] == "DIRECT"
        assert partial["category"] == "general_contractor"
        assert partial["person_organization_relationship"] == "UNKNOWN"
        assert partial["person_project_relationship"] == "UNKNOWN"
        assert partial["public_contacts"] == []
        assert {row["id"] for row in partial["evidence"]} == {public_source.id}
        only_role = by_claim[role_only.id]
        assert only_role["organization_relationship"] == "UNKNOWN"
        assert only_role["category"] == "unknown"
        assert only_role["person_organization_relationship"] == "CURRENT"
        assert only_role["person_project_relationship"] == "UNKNOWN"
        downgraded = by_claim[assignment_loss.id]
        assert downgraded["organization_relationship"] == "DIRECT"
        assert downgraded["person_organization_relationship"] == "CURRENT"
        assert downgraded["person_project_relationship"] == "ROLE_SUPPORTED"
        history = buying_chain_view(session, project.id, now=NOW, history=True)["candidates"]
        assert {row["id"] for row in history} == {
            person.id,
            invalid_only.id,
            role_only.id,
            assignment_loss.id,
        }


def test_retained_scan_reaches_older_current_version_after_invalid_prefix(db):
    from gridlens.intelligence.buying_chain import _retained

    with db.begin() as session:
        project = seed(session)
        accepted = session.scalar(select(Evidence))
        assert accepted is not None
        accepted.abstract = "Acme is the general contractor for Orion Data Center in Austin, TX."
        for number in range(50):
            session.add(
                Evidence(
                    observation_id=accepted.observation_id,
                    title=f"Invalid historical version {number}",
                    abstract="No current relationship.",
                    url=f"https://news.example/invalid/{number}",
                    content_hash=f"invalid-version-{number}",
                    published_at=accepted.published_at,
                    observed_at=NOW + timedelta(minutes=number + 1) if number < 25 else NOW,
                )
            )
        session.flush()
        assert [row.id for row in _retained(session, project)] == [accepted.id]

        def bounded_fetch(url):
            return PublicDocument(url, "No new facts", "No relationship here.", None, NOW)

        result = enrich_buying_chain(session, project.id, fetcher=bounded_fetch, now=NOW)
        assert any(row["organization"] == "Acme" for row in result["candidates"])
        assert all(
            row.retained_evidence_id == accepted.id
            for row in session.scalars(
                select(BuyingChainEvidence).where(
                    BuyingChainEvidence.retained_evidence_id.is_not(None)
                )
            ).all()
        )


def test_document_budget_preserves_unvisited_accepted_role(db, monkeypatch):
    with db.begin() as session:
        p = seed(session)
        org_text = "Acme is the general contractor for Orion Data Center in Austin, TX."
        team_url, other_url = "https://acme.com/team", "https://news.example/new"
        documents = {
            URL: source(org_text),
            team_url: PublicDocument(team_url, "Acme team", "Alice Smith, President", None, NOW),
            other_url: source(org_text, url=other_url),
        }
        enrich_buying_chain(
            session, p.id, source_urls=[team_url], fetcher=documents.__getitem__, now=NOW
        )
        monkeypatch.setattr("gridlens.intelligence.buying_chain.MAX_DOCUMENTS", 3)
        seen = []

        def fetch(url):
            seen.append(url)
            return documents[url]

        result = enrich_buying_chain(
            session,
            p.id,
            source_urls=[other_url],
            fetcher=fetch,
            now=NOW + timedelta(minutes=1),
        )
        assert team_url not in seen
        person = next(c for c in result["candidates"] if c["person_name"])
        assert person["person_organization_relationship"] == "CURRENT"
        assert person["person_project_relationship"] == "ROLE_SUPPORTED"
        assert result["status"] == "partial"
        assert any("sources remain unchecked" in message for message in result["unresolved"])


@pytest.mark.parametrize("processing_status", ["failed", "pending"])
def test_processing_outage_preserves_last_accepted_evidence_bound_relationship(
    db, processing_status
):
    with db.begin() as session:
        p = seed(session)
        retained = session.scalar(select(Evidence))
        retained.abstract = (
            "Acme is the general contractor for Orion Data Center in Austin, TX.\n"
            "Alice Smith is Project Director at Acme, on Orion Data Center."
        )

        def unavailable(url):
            raise TimeoutError("Synthetic research outage")

        enrich_buying_chain(session, p.id, fetcher=unavailable, now=NOW)
        interpretation = session.scalar(select(Interpretation))
        interpretation.status = processing_status
        session.flush()
        result = buying_chain_view(session, p.id, now=NOW + timedelta(minutes=1))
        person = next(c for c in result["candidates"] if c["person_name"])
        assert person["organization_relationship"] == "DIRECT"
        assert person["person_project_relationship"] == "DIRECT"
        assert not person["stale"]
        rechecked = enrich_buying_chain(
            session, p.id, fetcher=unavailable, now=NOW + timedelta(minutes=2)
        )
        assert any(c["person_project_relationship"] == "DIRECT" for c in rechecked["candidates"])
        interpretation.status = "rejected"
        interpretation.assessment = {"evidence_hash": "a", "decision": "rejected"}
        session.flush()
        rejected = buying_chain_view(session, p.id, now=NOW + timedelta(minutes=3))
        assert all(c["organization_relationship"] == "UNKNOWN" for c in rejected["candidates"])


@pytest.mark.parametrize(
    ("current_title", "expected"),
    [("Project Director", "DIRECT"), ("Construction Director", "UNKNOWN")],
)
def test_unavailable_assignment_source_preserves_same_current_role_not_changed_title(
    db, current_title, expected
):
    with db.begin() as session:
        p = seed(session)
        organization = "Acme is the general contractor for Orion Data Center in Austin, TX."
        assignment = "Alice Smith is Project Director at Acme, on Orion Data Center."
        enrich_buying_chain(
            session, p.id, fetcher=lambda url: source(organization + "\n" + assignment), now=NOW
        )
        current_url = "https://news.example/current-role"

        def fetch(url):
            if url == URL:
                raise TimeoutError("Synthetic assignment source outage")
            return source(
                organization + f"\nAlice Smith is {current_title} at Acme.", url=current_url
            )

        result = enrich_buying_chain(
            session,
            p.id,
            source_urls=[current_url],
            fetcher=fetch,
            now=NOW + timedelta(minutes=1),
        )
        person = next(c for c in result["candidates"] if c["person_name"])
        assert person["person_project_relationship"] == expected
        if expected == "DIRECT":
            assert any(
                e["supports"] == "person_project_assignment" and e["quote"] == assignment
                for e in person["evidence"]
            )
            assert {e["url"] for e in person["evidence"]} >= {URL, current_url}
            before = counts(session)
            replay = enrich_buying_chain(
                session,
                p.id,
                source_urls=[current_url],
                fetcher=fetch,
                now=NOW + timedelta(minutes=2),
            )
            assert counts(session) == before
            assert (
                next(c for c in replay["candidates"] if c["person_name"])[
                    "person_project_relationship"
                ]
                == "DIRECT"
            )
        assert result["status"] == "partial"


def test_carried_assignment_ages_independently_of_fresh_official_role(db):
    with db.begin() as session:
        p = seed(session)
        organization = "Acme is the general contractor for Orion Data Center in Austin, TX."
        assignment = "Alice Smith is Project Director at Acme, on Orion Data Center."
        enrich_buying_chain(
            session, p.id, fetcher=lambda url: source(organization + "\n" + assignment), now=NOW
        )
        org_url, team_url = "https://news.example/organization", "https://acme.com/team"
        for current_time, expected in [
            (NOW + timedelta(minutes=1), "DIRECT"),
            (NOW + timedelta(days=370), "ROLE_SUPPORTED"),
        ]:

            def fetch(url, current_time=current_time):
                if url == URL:
                    raise TimeoutError("Synthetic assignment source outage")
                if url == org_url:
                    return source(organization, url=org_url)
                return PublicDocument(
                    team_url,
                    "Acme team",
                    "Alice Smith is Project Director at Acme.",
                    None,
                    current_time,
                )

            result = enrich_buying_chain(
                session, p.id, source_urls=[org_url, team_url], fetcher=fetch, now=current_time
            )
            person = next(c for c in result["candidates"] if c["person_name"])
            assert person["person_project_relationship"] == expected
            assert person["person_organization_relationship"] == "CURRENT"
        historical = buying_chain_view(session, p.id, now=current_time, history=True)
        carried = next(
            c
            for c in historical["candidates"]
            if "Previously explicit assignment retained" in c["reason"]
        )
        assert carried["person_project_relationship"] == "UNKNOWN"
        assert carried["person_organization_relationship"] == "CURRENT"


@pytest.mark.parametrize("old_invalid", ["aged", "superseded"])
def test_fresh_independent_role_citation_survives_invalid_old_role(db, old_invalid):
    with db.begin() as session:
        project = seed(session)
        org_quote = "Acme is the general contractor for Orion Data Center in Austin, TX."
        role_quote = "Alice Smith is Project Director at Acme."
        enrich_buying_chain(
            session,
            project.id,
            fetcher=lambda _url: source(f"{org_quote}\n{role_quote}"),
            now=NOW,
        )
        current = buying_chain_view(session, project.id, now=NOW)
        person = next(row for row in current["candidates"] if row["person_name"])
        claim = session.get(BuyingChainClaim, person["id"])
        assert claim is not None
        original_role = next(
            citation
            for citation in claim.citations
            if citation["supports"] == "organization_person_role"
        )
        old_source = session.get(BuyingChainEvidence, original_role["evidence_id"])
        assert old_source is not None
        later = NOW + timedelta(days=370)
        independent = BuyingChainEvidence(
            project_id=project.id,
            url="https://acme.example/current-team",
            title="Acme current team",
            excerpt=role_quote,
            content_hash="current-independent-role",
            extraction_location="public team page",
            published_at=None,
            observed_at=later,
            last_seen_at=later,
            project_match_reason="Current named role.",
        )
        session.add(independent)
        session.flush()
        claim.citations = [
            *claim.citations,
            {
                "evidence_id": str(independent.id),
                "url": independent.url,
                "quote": role_quote,
                "supports": "organization_person_role",
            },
        ]
        if old_invalid == "superseded":
            replacement = BuyingChainEvidence(
                project_id=project.id,
                url=old_source.url,
                title="Old page correction",
                excerpt=org_quote,
                content_hash="old-role-withdrawn",
                extraction_location="public page revision",
                published_at=later.date(),
                observed_at=later,
                last_seen_at=later,
                project_match_reason="Same URL checked again.",
            )
            session.add(replacement)
        session.flush()
        survivor = next(
            row
            for row in buying_chain_view(session, project.id, now=later)["candidates"]
            if row["id"] == claim.id
        )
        assert survivor["person_organization_relationship"] == "CURRENT"
        assert survivor["stale"] is False
        assert {item["id"] for item in survivor["evidence"]} >= {old_source.id, independent.id}

        # If the independent page also withdraws the role, no current role
        # citation remains. The person relationship must become UNKNOWN.
        session.add(
            BuyingChainEvidence(
                project_id=project.id,
                url=independent.url,
                title="Acme team correction",
                excerpt="Current Acme team list no longer names Alice Smith.",
                content_hash="independent-role-withdrawn",
                extraction_location="public team page revision",
                published_at=later.date(),
                observed_at=later + timedelta(minutes=1),
                last_seen_at=later + timedelta(minutes=1),
                project_match_reason="Same URL checked again.",
            )
        )
        session.flush()
        withdrawn = next(
            row
            for row in buying_chain_view(session, project.id, now=later)["candidates"]
            if row["id"] == claim.id
        )
        assert withdrawn["person_organization_relationship"] == "UNKNOWN"
        assert withdrawn["stale"] is True


def test_boston_retained_applicant_facts_are_cited_without_creating_buyer(db):
    from gridlens.domain.pursuits import SOURCES

    text = (
        "Permit number: ETS1895395\nWork type: Generators\nPermit type: Electrical\n"
        "Description: Generators Installation of (2) 375KW temporary generator\n"
        "Applicant (buying role unknown): Acme Services\nStatus: Open\n"
        "Occupancy: Commercial\nAddress: 1 Main Street\nCity: Boston\nState: MA"
    )
    url = (
        "https://data.boston.gov/api/3/action/datastore_search?"
        "resource_id=6ddcd912-32a0-43df-9908-63574f8c7e77&filters=%7B%22permitnumber%22%3A%22ETS1895395%22%7D&limit=1"
    )
    with db.begin() as session:
        project = seed(session)
        source_row = Source(
            id="boston-building-permits",
            publisher="City of Boston",
            endpoint="https://data.boston.gov/api/3/action/datastore_search",
            family="construction-permits",
            geography="Boston, Massachusetts",
            industries=["commercial-construction"],
            retrieval_method="boston-ckan-permits",
            health={},
        )
        session.add(source_row)
        session.flush()
        project.source_id = source_row.id
        observation = session.scalar(select(Observation).where(Observation.external_id == "42"))
        assert observation
        observation.source_id = source_row.id
        evidence = session.scalar(select(Evidence).where(Evidence.observation_id == observation.id))
        assert evidence
        evidence.url = url
        evidence.title = "Boston permit ETS1895395"
        evidence.abstract = text
        evidence.content_hash = "boston-source-hash"
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == observation.id)
        )
        assert interpretation
        interpretation.content_hash = evidence.content_hash
        interpretation.assessment = {
            "evidence_hash": evidence.content_hash,
            "decision": "accepted",
            "project_identity_key": project.identity_key,
        }
        assert source_row.id in SOURCES

        def no_network(_url):
            pytest.fail("Retained Boston permit facts must not require provider research")

        result = enrich_buying_chain(session, project.id, fetcher=no_network, now=NOW)
        assert result["permit_summaries"]
        summary = next(
            row for row in result["permit_summaries"] if row["source_id"] == source_row.id
        )
        applicant = next(fact for fact in summary["facts"] if fact["value"] == "Acme Services")
        assert applicant["label"] == "Applicant (role as applicant; buyer authority unknown)"
        assert applicant["quote"] in evidence.abstract
        assert result["candidates"] == []
        assert any("buyer remains UNKNOWN" in item for item in result["unresolved"])


def test_retained_permit_enrichment_without_network_preserves_exact_fields_and_replay(db):
    """Regression: GL3-018 field pairs were inert unless a second fetch succeeded."""
    with db.begin() as session:
        project = seed(session)
        source_id = "chicago-building-permits"
        session.add(
            Source(
                id=source_id,
                publisher="Chicago",
                endpoint="https://data.cityofchicago.org/resource/ydr8-5enu.json",
                family="construction-permits",
                geography="US",
                industries=[],
                retrieval_method="socrata-permits",
                health={},
            )
        )
        session.flush()
        project.source_id = source_id
        observation = session.scalar(select(Observation))
        observation.source_id = source_id
        evidence = session.scalar(select(Evidence))
        evidence.abstract = (
            "row: 42\naddress: 400 S LA SALLE ST\ntype: Renovation\n"
            "date: 2026-09-16T00:00:00.000\napplication_start: 2026-06-17T00:00:00.000\n"
            "description: Data center conversion with MEP upgrades\n"
            "contact_1_type: OWNER OCCUPIED\ncontact_1_name: Example Owner LLC\n"
            "contact_2_type: CONTRACTOR-ELECTRICAL\ncontact_2_name: Example Electric LLC\n"
            "contact_3_type: ARCHITECT\ncontact_3_name: DOE, JANE A\n"
        )

        session.add(
            BuyingChainEvidence(
                project_id=project.id,
                url=evidence.url,
                title="Earlier live JSON",
                excerpt='[{"contact_2_name": "Example Electric LLC"}]',
                content_hash="legacy-json",
                extraction_location="JSON",
                observed_at=NOW,
                last_seen_at=NOW,
                project_match_reason="Earlier GL3-017 exact permit fetch",
            )
        )

        def no_network(url):
            pytest.fail("Retained permit fields must not require another request")

        first = enrich_buying_chain(session, project.id, fetcher=no_network, now=NOW)
        before = counts(session)
        again = enrich_buying_chain(
            session, project.id, fetcher=no_network, now=NOW + timedelta(minutes=1)
        )
        assert counts(session) == before
        assert len(first["candidates"]) == 2
        assert all(c["organization_relationship"] == "DIRECT" for c in again["candidates"])
        assert all(
            c["person_name"] is None
            and c["person_project_relationship"] == "UNKNOWN"
            and not c["public_contacts"]
            for c in again["candidates"]
        )
        facts = again["permit_summaries"][0]["facts"]
        assert any(f["value"] == "DOE, JANE A" for f in facts)
        assert any(f["label"] == "Application start date" for f in facts)
        assert all(f["quote"] in evidence.abstract for f in facts)
        for c in again["candidates"]:
            assert all(e["quote"] in evidence.abstract for e in c["evidence"])
        # A failed interpretation with the last accepted hash keeps the facts;
        # an actual rejected replacement makes the older facts unavailable.
        interpretation = session.scalar(select(Interpretation))
        interpretation.status = "failed"
        session.flush()
        assert buying_chain_view(session, project.id, now=NOW)["permit_summaries"]
        interpretation.status = "rejected"
        session.flush()
        changed = buying_chain_view(session, project.id, now=NOW)
        assert changed["permit_summaries"] == []
        assert all(c["organization_relationship"] == "UNKNOWN" for c in changed["candidates"])

        # Same excerpt, new accepted source hash: never reuse an enrichment row
        # bound to the superseded Evidence ID (real GA PDF-version regression).
        replacement = Evidence(
            observation_id=observation.id,
            title=evidence.title,
            abstract=evidence.abstract,
            url=evidence.url,
            content_hash="new-source-version",
            published_at=evidence.published_at,
            observed_at=NOW + timedelta(minutes=2),
        )
        session.add(replacement)
        observation.content_hash = "new-source-version"
        interpretation.status = "accepted"
        interpretation.assessment = {
            "decision": "accepted",
            "evidence_hash": "new-source-version",
            "project_identity_key": project.identity_key,
        }
        session.flush()
        fresh = enrich_buying_chain(
            session, project.id, fetcher=no_network, now=NOW + timedelta(minutes=3)
        )
        assert all(c["organization_relationship"] == "DIRECT" for c in fresh["candidates"])
        assert all(not c["stale"] for c in fresh["candidates"])
        before = counts(session)
        enrich_buying_chain(session, project.id, fetcher=no_network, now=NOW + timedelta(minutes=4))
        assert counts(session) == before


def test_houston_exact_detail_uses_source_record_key_and_attaches_to_matching_project(
    db, monkeypatch
):
    """Exact detail evidence is keyed to Houston's actual retained permit-row label."""
    from gridlens.intelligence import buying_chain as service

    detail_url = (
        "https://cohtora.houstontx.gov/ibi_apps/WFServlet.ibfs"
        "?IBIF_webapp=%2Fibi_apps&IBIC_server=EDASERVE&IBIWF_msgviewer=OFF"
        "&IBIAPP_app=soldpermits&IBIF_ex=sold_permit_d&CLICKED_ON="
        "&PN=26051624&PT=13"
    )
    calls = []
    response_type = ["13"]
    should_fail = [False]

    def detail(project_number, permit_type, *, event_date, site_address):
        calls.append((project_number, permit_type, event_date, site_address))
        if should_fail[0]:
            raise RuntimeError("simulated detail lookup failure")
        return PublicDocument(
            detail_url,
            "Houston sold permit detail 26051624 — Building Pmt",
            "detail_project: 26051624\n"
            "detail_date: 2026-09-02\n"
            "detail_site_address: 8930 GULF FWY A 77017\n"
            f"detail_permit_type: {response_type[0]}\n"
            "detail_owner_occupant: *MERICHEM TECHNOLOGIES LLC\n"
            "detail_buyer: *ACME LLC\n"
            "detail_buyer_address: 100 BUSINESS ST 77001\n"
            "detail_buyer_phone: (713) 555-0100",
            None,
            NOW,
            "Official Houston Online Sold Permit Search; Project Details fields",
        )

    monkeypatch.setattr(service, "retrieve_detail", detail)
    with db.begin() as session:
        project = seed(session)
        source_id = "houston-weekly-permits"
        session.add(
            Source(
                id=source_id,
                publisher="Houston",
                endpoint="https://www.houstonpermittingcenter.org/sold-permits-search",
                family="construction-permits",
                geography="Houston, Texas",
                industries=["construction"],
                retrieval_method="houston-weekly-permits",
                health={},
            )
        )
        session.flush()
        project.source_id = source_id
        project.external_id = "26051624:Building Pmt:2026-09-02"
        project.location = "8930 GULF FWY A, Houston, TX"
        observation = session.scalar(select(Observation))
        observation.source_id = source_id
        observation.external_id = project.external_id
        evidence = session.scalar(select(Evidence))
        evidence.abstract = (
            "row: 26051624\nevent: Sold (weekly report; issued permit event)\n"
            "date: 2026-09-02\nreport_start: 2026-08-31\nreport_end: 2026-09-07\n"
            "status: Unknown\ntype: Building Pmt\naddress: 8930 GULF FWY A\n"
            "description: 2,765 SQ. FT. CONVERT TO LABORATORY"
        )
        observation.abstract = evidence.abstract
        result = enrich_buying_chain(session, project.id, now=NOW)
        assert calls == [("26051624", "Building Pmt", "2026-09-02", "8930 GULF FWY A")]
        candidate = next(
            item for item in result["candidates"] if item["organization"] == "ACME LLC"
        )
        assert candidate["organization_relationship"] == "ROLE_SUPPORTED"
        assert candidate["person_project_relationship"] == "UNKNOWN"
        assert candidate["public_contacts"][0]["value"] == "(713) 555-0100"
        summaries = result["permit_summaries"]
        assert len(summaries) == 2
        detail_summary = next(item for item in summaries if item["url"] == detail_url)
        detail_facts = {item["label"]: item["value"] for item in detail_summary["facts"]}
        assert detail_facts["Houston exact permit project number"] == "26051624"
        assert detail_facts["Permit-listed owner / occupant"] == "*MERICHEM TECHNOLOGIES LLC"
        assert detail_facts["Permit-listed Buyer (entity type unknown)"] == "*ACME LLC"
        assert detail_facts["Permit-listed buyer phone"] == "(713) 555-0100"

        retained_before = set(
            session.scalars(
                select(BuyingChainEvidence.id).where(BuyingChainEvidence.project_id == project.id)
            )
        )
        claims_before = set(
            session.scalars(
                select(BuyingChainClaim.id).where(BuyingChainClaim.project_id == project.id)
            )
        )
        response_type[0] = "Demolition"
        rejected = enrich_buying_chain(session, project.id, now=NOW + timedelta(minutes=1))
        assert len(rejected["permit_summaries"]) == 2
        assert (
            set(
                session.scalars(
                    select(BuyingChainEvidence.id).where(
                        BuyingChainEvidence.project_id == project.id
                    )
                )
            )
            == retained_before
        )
        assert (
            set(
                session.scalars(
                    select(BuyingChainClaim.id).where(BuyingChainClaim.project_id == project.id)
                )
            )
            == claims_before
        )

        should_fail[0] = True
        failed = enrich_buying_chain(session, project.id, now=NOW + timedelta(minutes=2))
        assert len(failed["permit_summaries"]) == 2
        assert (
            set(
                session.scalars(
                    select(BuyingChainEvidence.id).where(
                        BuyingChainEvidence.project_id == project.id
                    )
                )
            )
            == retained_before
        )
