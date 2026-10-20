from collections import Counter
from datetime import UTC, date, datetime, timedelta
from importlib import import_module

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.ingestion.adapters.buying_chain_public import PublicDocument, parse_document
from gridlens.intelligence.buying_chain import (
    buying_chain_view,
    buying_chain_views,
    enrich_buying_chain,
)
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    BuyingChainClaim,
    BuyingChainEvidence,
    BuyingChainRun,
    Evidence,
    Interpretation,
    NeedObservation,
    Observation,
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


def seed(session):
    observation = Observation(
        source_id="test",
        external_id="42",
        title="Orion Data Center",
        url=URL,
        abstract="Orion Data Center in Austin, TX.",
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
        external_id="42",
        name="Orion Data Center",
        location="Austin, TX",
        identity_key="orion",
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
        assert counts(session) == before
        assert session.scalar(select(PowerNeed.tier)) == "Signal"


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
