from datetime import UTC, date, datetime, timedelta
from importlib import import_module

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.ingestion.adapters.buying_chain_public import PublicDocument, parse_document
from gridlens.intelligence.buying_chain import buying_chain_view, enrich_buying_chain
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    BuyingChainClaim,
    BuyingChainEvidence,
    BuyingChainRun,
    Evidence,
    Interpretation,
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
            assessment={"evidence_hash": "a", "decision": "accepted"},
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
