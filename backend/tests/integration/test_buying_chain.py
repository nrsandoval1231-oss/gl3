import time
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
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
    _ordered_correction_chain,
    overlay_corrections,
)
from gridlens.intelligence.buying_chain_extraction import extract_retained_permit_organizations
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
    CompanyProjectMembership,
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


def test_membership_only_company_contact_job_persists_canonical_method(db, monkeypatch):
    """The actual job, claim, run and account projection share one PostgreSQL transaction."""
    import json

    import gridlens.intelligence.company_contact_discovery as discovery
    from gridlens.domain.evaluation_clock import evaluate_at
    from gridlens.intelligence.company_contacts import company_contacts
    from gridlens.persistence.models import CompanyProjectMembership, Job

    with db.begin() as session:
        project = seed(session, external_id="operator-contact")
        project.region_status = "ELIGIBLE"
        evidence = session.scalar(
            select(Evidence).join(Observation).where(Observation.external_id == "operator-contact")
        )
        assert evidence is not None
        evidence.abstract = "EOG Resources is the operator, RRC operator number 123456."
        evidence.title = "EOG Resources drilling permit"
        identity = CompanyIdentity(rrc_operator_number="123456")
        session.add(identity)
        session.flush()
        session.add(
            CompanyProjectMembership(
                company_identity_id=identity.id,
                project_id=project.id,
                role="asset_operator",
                organization_name="EOG Resources",
                source_id="test",
                source_evidence_id=evidence.id,
                source_version_hash=evidence.content_hash,
                decision_basis="typed_rrc_operator_number_v1",
                operator_number="123456",
                state="current",
            )
        )
        queued = discovery.discover_company_contacts(
            session,
            identity.id,
            candidate_urls=[
                "https://www.eogresources.com/",
                "https://www.eogresources.com/news/",
                "https://www.eogresources.com/investors/",
                "https://www.eogresources.com/careers/",
            ],
        )
        job = session.get(Job, UUID(queued["job_id"]))
        job.status = "running"
        job.lease_owner = "contact-test"
        job.fence = 1
        job.lease_until = datetime.now(UTC) + timedelta(minutes=5)
        job.created_at = NOW
        job_id, company_id = job.id, identity.id

    monkeypatch.setattr(discovery, "SessionLocal", db)
    inherited_deadline = time.monotonic() + 5
    seen_deadlines = []

    def public_page(url, **_kwargs):
        seen_deadlines.append(_kwargs["deadline"])
        if url.endswith("/leadership/"):
            return PublicDocument(
                url,
                "Executive Leadership EOG Resources",
                "EOG Resources executive leadership\nGregory T. Miller\nVP, Supply Chain\n"
                "\ufffd 2018-2026 EOG Resources, Inc. All rights reserved.",
                observed_at=NOW,
                links=(
                    "https://www.eogresources.com/team/detail-one/",
                    "https://www.eogresources.com/team/detail-two/",
                ),
            )
        if url.endswith("/news/"):
            return PublicDocument(
                url,
                "News article",
                "A story that does not identify EOG Resources as its own organization.",
                observed_at=NOW,
                links=("https://www.eogresources.com/unverified-contact/",),
            )
        if url == "https://www.eogresources.com/":
            return PublicDocument(
                url,
                "EOG Resources",
                "EOG Resources\n\ufffd 2018-2026 EOG Resources, Inc. All rights reserved.",
                observed_at=NOW,
                links=(
                    "https://www.eogresources.com/company/leadership/",
                    "https://www.eogresources.com/company/contacts/",
                    "https://other.example/contact/",
                ),
            )
        return PublicDocument(
            url,
            "EOG Resources Contact",
            "EOG Resources corporate headquarters\n"
            "Phone: (713) 651-7000\n"
            "Toll Free: (877) 363-3647\n"
            "Fax: (713) 651-6995\n"
            "Email: info@eogresources.com.\n"
            "\ufffd 2018-2026 EOG Resources, Inc. All rights reserved.",
            observed_at=NOW,
        )

    monkeypatch.setattr(discovery, "retrieve", public_page)
    result = discovery.process_company_contact_discovery(
        job_id, "contact-test", 1, now=NOW, deadline=inherited_deadline
    )
    assert result["status"] == "complete", result
    assert seen_deadlines and all(value == inherited_deadline for value in seen_deadlines)
    with db.begin() as session:
        projected = company_contacts(session, company_id)
        assert projected.contacts
        assert any(m["kind"] == "email" for c in projected.contacts for m in c.methods)
        assert any(m["kind"] == "phone" for c in projected.contacts for m in c.methods)
        values = {m["value"] for c in projected.contacts for m in c.methods}
        assert "(713) 651-7000" in values
        assert "(877) 363-3647" in values
        assert "(713) 651-6995" not in values
        assert any(c.name == "Gregory T. Miller" and not c.methods for c in projected.contacts)
        assert any(
            c.name == "Gregory T. Miller"
            and c.confidence == "Published role; no verified direct contact method"
            for c in projected.contacts
        )
        assert session.scalar(select(func.count()).select_from(CompanyIdentity)) == 1
        current_run = session.scalar(
            select(BuyingChainRun)
            .where(BuyingChainRun.project_id == project.id)
            .order_by(BuyingChainRun.created_at.desc(), BuyingChainRun.id.desc())
        )
        assert current_run and current_run.claim_ids
        checkpoint = json.loads(session.get(Job, job_id).checkpoint)
        assert len(checkpoint["checked_urls"]) == 4
        assert checkpoint["research_required"] is True  # generic method is not a named buyer
        assert "https://www.eogresources.com/company/contacts/" in checkpoint["checked_urls"]
        assert checkpoint["checked_urls"].index(
            "https://www.eogresources.com/company/contacts/"
        ) < checkpoint["checked_urls"].index("https://www.eogresources.com/company/leadership/")
        assert "https://other.example/contact/" not in checkpoint["checked_urls"]
        assert "https://www.eogresources.com/unverified-contact/" not in checkpoint["checked_urls"]
        assert not any(
            path in url
            for url in checkpoint["checked_urls"]
            for path in ("/investors/", "/careers/")
        )

        contact_page_url = "https://www.eogresources.com/company/contacts/"
        refresh_at = NOW + timedelta(days=30)
        with evaluate_at(refresh_at):
            due_projection = company_contacts(session, company_id)
            assert any(contact.methods for contact in due_projection.contacts)
            assert contact_page_url in discovery._known_contact_urls(session, company_id, [project])
            assert discovery.plan_company_contact_jobs(session, limit=1, now=refresh_at) == 1
        refresh_job = session.scalar(
            select(Job)
            .where(
                Job.kind == discovery.JOB_KIND,
                Job.target_id == company_id,
                Job.status == "queued",
            )
            .order_by(Job.created_at.desc(), Job.id.desc())
        )
        assert refresh_job is not None
        refresh_payload = json.loads(refresh_job.checkpoint)["payload"]
        assert refresh_payload["refresh_due"] is True
        first_refresh_digest = json.loads(refresh_job.checkpoint)["request_digest"]
        first_refresh_generation = json.loads(refresh_job.checkpoint)["refresh_generation"]
        # Simulate the worker process failing before it can write a terminal
        # receipt. The planner retries this generation after its one-hour
        # failure backoff.
        refresh_checkpoint = json.loads(refresh_job.checkpoint)
        refresh_checkpoint["status"] = "failed"
        refresh_job.checkpoint = json.dumps(refresh_checkpoint, separators=(",", ":"))
        refresh_job.status = "failed"
        refresh_job.error = "Synthetic worker failure before refresh receipt"
        retry_at = refresh_at + timedelta(hours=1)
        with evaluate_at(retry_at):
            assert discovery.plan_company_contact_jobs(session, limit=1, now=retry_at) == 1
        retry_job = session.scalar(
            select(Job)
            .where(
                Job.kind == discovery.JOB_KIND,
                Job.target_id == company_id,
                Job.status == "queued",
            )
            .order_by(Job.created_at.desc(), Job.id.desc())
        )
        assert retry_job is not None and retry_job.id != refresh_job.id
        retry_checkpoint = json.loads(retry_job.checkpoint)
        assert retry_checkpoint["request_digest"] == first_refresh_digest
        assert retry_checkpoint["refresh_generation"] == first_refresh_generation
        assert retry_checkpoint["payload"]["refresh_due"] is True
        retry_job.status, retry_job.lease_owner, retry_job.fence = (
            "running",
            "contact-test",
            1,
        )
        retry_job.lease_until = datetime.now(UTC) + timedelta(minutes=5)
        refresh_job_id = retry_job.id
        before_counts = (
            session.scalar(select(func.count()).select_from(BuyingChainClaim)),
            session.scalar(select(func.count()).select_from(BuyingChainEvidence)),
            session.scalar(select(func.count()).select_from(CompanyIdentity)),
        )
        assert before_counts == (
            session.scalar(select(func.count()).select_from(BuyingChainClaim)),
            session.scalar(select(func.count()).select_from(BuyingChainEvidence)),
            session.scalar(select(func.count()).select_from(CompanyIdentity)),
        )

    refreshed_urls = []

    def refreshed_contact_page(url, **_kwargs):
        refreshed_urls.append(url)
        return PublicDocument(
            url,
            "EOG Resources Contact",
            "EOG Resources corporate headquarters\n"
            "Phone: (713) 651-7000\n"
            "Email: info@eogresources.com.\n"
            "\ufffd 2018-2026 EOG Resources, Inc. All rights reserved.",
            observed_at=retry_at,
        )

    monkeypatch.setattr(discovery, "retrieve", refreshed_contact_page)
    monkeypatch.setattr(
        discovery,
        "_search_official_urls",
        lambda *_args, **_kwargs: pytest.fail("stale cited URL should bypass paid discovery"),
    )
    with evaluate_at(retry_at):
        refreshed = discovery.process_company_contact_discovery(
            refresh_job_id,
            "contact-test",
            1,
            now=retry_at,
            deadline=time.monotonic() + 10,
        )
    assert refreshed["status"] == "complete"
    assert contact_page_url in refreshed_urls
    assert all("eogresources.com" in url for url in refreshed_urls)
    with evaluate_at(retry_at), db() as session:
        current_projection = company_contacts(session, company_id)
        assert any(
            method["value"] == "info@eogresources.com"
            for contact in current_projection.contacts
            for method in contact.methods
        )
    with evaluate_at(refresh_at + timedelta(days=1)), db() as session:
        day_31_projection = company_contacts(session, company_id)
        assert any(
            method["value"] == "info@eogresources.com"
            for contact in day_31_projection.contacts
            for method in contact.methods
        )
    # A new checkpoint opens a new transaction and must reuse the same job.
    with db.begin() as session:
        replay = discovery.discover_company_contacts(
            session,
            company_id,
            candidate_urls=[
                "https://www.eogresources.com/",
                "https://www.eogresources.com/news/",
                "https://www.eogresources.com/investors/",
                "https://www.eogresources.com/careers/",
            ],
        )
        assert replay["job_id"] == str(job_id)
        assert replay["deduplicated"] is True
    with db.begin() as session:
        membership = session.scalar(
            select(CompanyProjectMembership).where(
                CompanyProjectMembership.company_identity_id == company_id
            )
        )
        membership.state = "retracted"
        membership.version += 1
    with db.begin() as session:
        assert company_contacts(session, company_id).contacts == []


def test_unverified_company_page_links_are_never_followed(db, monkeypatch):
    import json

    import gridlens.intelligence.company_contact_discovery as discovery
    from gridlens.persistence.models import CompanyProjectMembership, Job

    urls = [
        "https://www.eogresources.com/",
        "https://www.eogresources.com/news/unverified/",
        "https://www.eogresources.com/investors/",
        "https://www.eogresources.com/careers/",
    ]
    with db.begin() as session:
        project = seed(session, external_id="unverified-contact-navigation")
        project.region_status = "ELIGIBLE"
        evidence = session.scalar(
            select(Evidence)
            .join(Observation)
            .where(Observation.external_id == "unverified-contact-navigation")
        )
        assert evidence is not None
        evidence.abstract = "EOG Resources is the operator, RRC operator number 123456."
        identity = CompanyIdentity(rrc_operator_number="123456")
        session.add(identity)
        session.flush()
        session.add(
            CompanyProjectMembership(
                company_identity_id=identity.id,
                project_id=project.id,
                role="asset_operator",
                organization_name="EOG Resources",
                source_id="test",
                source_evidence_id=evidence.id,
                source_version_hash=evidence.content_hash,
                decision_basis="typed_rrc_operator_number_v1",
                operator_number="123456",
                state="current",
            )
        )
        queued = discovery.discover_company_contacts(session, identity.id, candidate_urls=urls)
        job = session.get(Job, UUID(queued["job_id"]))
        job.status, job.lease_owner, job.fence = "running", "contact-test", 1
        job.lease_until = datetime.now(UTC) + timedelta(minutes=5)
        job_id = job.id

    monkeypatch.setattr(discovery, "SessionLocal", db)
    fetched = []

    def public_page(url, **_kwargs):
        fetched.append(url)
        if url == urls[0]:
            return PublicDocument(
                url,
                "EOG Resources",
                "EOG Resources\n© EOG Resources, Inc.",
                observed_at=NOW,
                links=("https://other.example/contact/",),
            )
        if url == urls[1]:
            return PublicDocument(
                url,
                "Unrelated news",
                "A third-party article that does not identify its own organization "
                "as EOG Resources.",
                observed_at=NOW,
                links=(
                    "https://www.eogresources.com/unverified-contact/",
                    "https://other.example/unverified-contact/",
                ),
            )
        return PublicDocument(url, "EOG Resources", "EOG Resources", observed_at=NOW)

    monkeypatch.setattr(discovery, "retrieve", public_page)
    discovery.process_company_contact_discovery(
        job_id, "contact-test", 1, now=NOW, deadline=time.monotonic() + 10
    )
    with db.begin() as session:
        checkpoint = json.loads(session.get(Job, job_id).checkpoint)
    assert urls[1] in fetched  # The negative navigation assertions are exercised.
    assert len(fetched) <= 4
    assert "https://www.eogresources.com/unverified-contact/" not in fetched
    assert "https://other.example/unverified-contact/" not in fetched
    assert "https://other.example/contact/" not in fetched
    assert len(checkpoint["checked_urls"]) <= 4


def test_directory_profile_never_persists_publisher_method_for_listed_company(db, monkeypatch):
    import json

    import gridlens.intelligence.company_contact_discovery as discovery
    from gridlens.persistence.models import CompanyProjectMembership, Job

    target = "DE Central Operating LLC"
    url = "https://www.buckheadenergy.com/operators/de-central-operating-llc"
    html = """<html><head><title>DE Central Operating LLC | Buckhead Energy</title>
    <script type="application/ld+json">{"@graph":[
      {"@context":"https://schema.org","@type":"Organization",
       "@id":"https://www.buckheadenergy.com/#organization",
       "name":"Buckhead Energy","url":"https://www.buckheadenergy.com/",
       "email":"land@buckheadenergy.com"},
      {"@context":"https://schema.org","@type":"Organization",
       "name":"DE Central Operating LLC",
       "url":"https://www.buckheadenergy.com/operators/de-central-operating-llc"}
    ]}</script></head><body><main><h1>DE Central Operating LLC</h1>
    <p>Listed operator profile. Email: land@buckheadenergy.com.</p>
    <p>Phone: (817) 555-0144</p><a href="/contact/">Contact</a></main>
    <footer>© 2026 Buckhead Energy</footer></body></html>"""
    with db.begin() as session:
        project = seed(session, external_id="directory-profile-publisher")
        project.region_status = "ELIGIBLE"
        retained = session.scalar(
            select(Evidence)
            .join(Observation)
            .where(Observation.external_id == "directory-profile-publisher")
        )
        assert retained is not None
        retained.title = f"RRC permit for {target}"
        retained.abstract = f"{target} is the asset operator on this physical project."
        identity = CompanyIdentity()
        session.add(identity)
        session.flush()
        session.add(
            CompanyProjectMembership(
                company_identity_id=identity.id,
                project_id=project.id,
                role="asset_operator",
                organization_name=target,
                source_id="test",
                source_evidence_id=retained.id,
                source_version_hash=retained.content_hash,
                decision_basis="typed_source_v1",
                operator_number="000000",
                state="current",
            )
        )
        queued = discovery.discover_company_contacts(session, identity.id, candidate_urls=[url])
        job = session.get(Job, UUID(queued["job_id"]))
        job.status, job.lease_owner, job.fence = "running", "directory-test", 1
        job.lease_until = datetime.now(UTC) + timedelta(minutes=5)
        job_id, company_id = job.id, identity.id

    monkeypatch.setattr(discovery, "SessionLocal", db)
    fetched = []

    def public_page(address, **_kwargs):
        fetched.append(address)
        assert address == url  # A directory cannot authorize same-host navigation.
        return parse_document(address, html.encode(), "text/html")

    monkeypatch.setattr(discovery, "retrieve", public_page)
    result = discovery.process_company_contact_discovery(job_id, "directory-test", 1, now=NOW)
    assert result["status"] == "unresolved"
    assert fetched == [url]
    with db.begin() as session:
        checkpoint = json.loads(session.get(Job, job_id).checkpoint)
        assert checkpoint["results"][0]["reason"] == "official_identity_unverified"
        assert (
            session.scalar(
                select(func.count())
                .select_from(BuyingChainEvidence)
                .where(
                    BuyingChainEvidence.project_id == project.id,
                    BuyingChainEvidence.url == url,
                )
            )
            == 0
        )

    api = import_module("gridlens.api.app")
    monkeypatch.setattr(api, "SessionLocal", db)
    client = TestClient(api.app)
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    response = client.get(f"/api/customer-accounts/{company_id}/contacts")
    assert response.status_code == 200
    assert response.json()["contacts"] == []
    assert response.json()["research_required"] is True


def test_contact_refresh_keeps_existing_buying_chain_claims(db, monkeypatch):
    import gridlens.intelligence.company_contact_discovery as discovery
    from gridlens.intelligence.company_contacts import company_contacts
    from gridlens.persistence.models import Job

    with db.begin() as session:
        project = seed(session, external_id="existing-contact")
        project.region_status = "ELIGIBLE"
        view = enrich_buying_chain(
            session,
            project.id,
            fetcher=lambda url: source(
                "Acme is the general contractor for Orion Data Center in Austin, TX. "
                "Beta is the electrical contractor for Orion Data Center in Austin, TX."
            ),
            now=NOW,
        )
        acme = next(c for c in view["candidates"] if c["organization"] == "Acme")
        before = {str(c["id"]) for c in view["candidates"]}
        company_id = UUID(acme["company_identity_id"])
        queued = discovery.discover_company_contacts(
            session,
            company_id,
            candidate_urls=["https://acme.example/contact", "https://acme.example/team"],
        )
        job = session.get(Job, UUID(queued["job_id"]))
        job.status, job.lease_owner, job.fence = "running", "contact-test", 1
        job.lease_until = datetime.now(UTC) + timedelta(minutes=5)
        job_id = job.id

    monkeypatch.setattr(discovery, "SessionLocal", db)
    requests = []

    inherited_deadline = time.monotonic() + 1000
    local_start = time.monotonic()
    seen_deadlines = []

    def public_page(url, **_kwargs):
        seen_deadlines.append(_kwargs["deadline"])
        requests.append(url)
        if url.endswith("/team"):
            return PublicDocument(
                url,
                "Acme Team",
                "Alex Smith\nPower Procurement Manager\n© 2026 Acme. All rights reserved.",
                observed_at=NOW,
            )
        return PublicDocument(
            url,
            "Acme Contact",
            "Acme company contact. Email: office@acme.example.\n© 2026 Acme. All rights reserved.",
            observed_at=NOW,
        )

    monkeypatch.setattr(discovery, "retrieve", public_page)
    result = discovery.process_company_contact_discovery(
        job_id, "contact-test", 1, now=NOW, deadline=inherited_deadline
    )
    assert result["status"] == "complete"
    assert seen_deadlines and all(
        local_start < value <= local_start + 35.1 for value in seen_deadlines
    )
    with db.begin() as session:
        after = buying_chain_view(session, project.id)
        assert len(after["candidates"]) >= len(before)
        assert any(c["organization"] == "Beta" for c in after["candidates"])
        assert any(
            m["value"] == "office@acme.example"
            for c in company_contacts(session, company_id).contacts
            for m in c.methods
        )
        assert session.scalar(select(func.count()).select_from(CompanyIdentity)) == 2
        assert any(c["person_name"] == "Alex Smith" for c in after["candidates"])
    with db.begin() as session:
        replay = discovery.discover_company_contacts(
            session,
            company_id,
            candidate_urls=["https://acme.example/contact", "https://acme.example/team"],
        )
        assert replay["job_id"] == str(job_id)
        assert replay["deduplicated"] is True
    assert requests == ["https://acme.example/contact", "https://acme.example/team"]


def test_membership_link_never_binds_other_company_in_same_retained_article(db):
    from gridlens.intelligence.company_contacts import company_contacts
    from gridlens.persistence.models import CompanyProjectMembership

    article = (
        "Owner A is the developer for Orion Data Center in Austin, TX. "
        "Contractor B is the general contractor for Orion Data Center in Austin, TX. "
        "Morgan Lee is Project Manager at Owner A. "
        "Contractor B email: bids@contractorb.example."
    )
    with db.begin() as session:
        project = seed(session, external_id="mixed-membership-article")
        project.region_status = "ELIGIBLE"
        retained = session.scalar(
            select(Evidence)
            .join(Observation)
            .where(Observation.external_id == "mixed-membership-article")
        )
        assert retained is not None
        retained.abstract = article
        owner = CompanyIdentity()
        session.add(owner)
        session.flush()
        membership = CompanyProjectMembership(
            company_identity_id=owner.id,
            project_id=project.id,
            role="owner_developer",
            organization_name="Owner A",
            source_id="test",
            source_evidence_id=retained.id,
            source_version_hash=retained.content_hash,
            decision_basis="typed_source_v1",
            operator_number="000000",
            state="current",
        )
        session.add(membership)
        view = enrich_buying_chain(
            session,
            project.id,
            fetcher=lambda _url: source(article),
            now=NOW,
            retained_only=True,
        )
        owner_claims = [c for c in view["candidates"] if c["organization"] == "Owner A"]
        contractor_claims = [c for c in view["candidates"] if c["organization"] == "Contractor B"]
        assert owner_claims and contractor_claims
        assert all(c["company_identity_id"] == str(owner.id) for c in owner_claims)
        assert all(c["company_identity_id"] != str(owner.id) for c in contractor_claims)
        assert any(c["person_name"] == "Morgan Lee" for c in owner_claims)
        owner_company = next(c for c in owner_claims if not c["person_name"])
        protected_link = session.scalar(
            select(BuyingChainIdentityLink).where(
                BuyingChainIdentityLink.claim_id == owner_company["id"],
                BuyingChainIdentityLink.entity_type == "company",
                BuyingChainIdentityLink.state == "current",
            )
        )
        assert protected_link is not None
        protected_link.basis = "strong_identifier"
        protected_id = protected_link.id
        ensure_project_scoped_identity_links(session, [str(owner_company["id"])])
        protected_link = session.get(BuyingChainIdentityLink, protected_id)
        assert protected_link.state == "current" and protected_link.basis == "strong_identifier"
        protected_link.basis = "current_membership"
        assert all(
            m["value"] != "bids@contractorb.example"
            for contact in company_contacts(session, owner.id).contacts
            for m in contact.methods
        )
        contractor = next(c for c in contractor_claims if not c["person_name"])
        contractor_source = next(
            c for c in contractor["evidence"] if c["supports"] == "project_organization"
        )
        old_link = session.scalar(
            select(BuyingChainIdentityLink).where(
                BuyingChainIdentityLink.claim_id == contractor["id"],
                BuyingChainIdentityLink.entity_type == "company",
                BuyingChainIdentityLink.state == "current",
            )
        )
        assert old_link is not None
        # Simulate an already persisted link from the rejected implementation.
        # Read paths must fail closed without waiting for a new reconciliation.
        old_link.company_identity_id = owner.id
        old_link.basis = "current_membership"
        old_link.source_evidence_id = contractor_source["id"]
        old_link.source_version_hash = contractor_source["content_hash"]
        session.flush()
        assert all(
            c.get("company_identity_id") != str(owner.id)
            for c in buying_chain_view(session, project.id)["candidates"]
            if c["organization"] == "Contractor B"
        )
        assert all(
            m["value"] != "bids@contractorb.example"
            for contact in company_contacts(session, owner.id).contacts
            for m in contact.methods
        )
        owner_id, membership_id, project_id = owner.id, membership.id, project.id
    with db.begin() as session:
        membership = session.get(CompanyProjectMembership, membership_id)
        membership.source_version_hash = "changed"
        assert all(
            c.get("company_identity_id") != str(owner_id)
            for c in buying_chain_view(session, project_id)["candidates"]
        )
    with db.begin() as session:
        membership = session.get(CompanyProjectMembership, membership_id)
        membership.source_version_hash = "a"
        membership.state = "retracted"
        membership.version += 1
        assert all(
            c.get("company_identity_id") != str(owner_id)
            for c in buying_chain_view(session, project_id)["candidates"]
        )


def test_failed_contact_enqueue_sql_does_not_abort_primary_enrichment(db, monkeypatch):
    import gridlens.intelligence.company_contact_discovery as discovery

    monkeypatch.setattr(settings, "company_contact_discovery_enabled", True)

    def failed_enqueue(session, _company_id):
        # PostgreSQL aborts the transaction on this real SQL error unless the
        # best-effort hook has a savepoint around the entire enqueue.
        session.execute(text("SELECT 1 / 0"))

    monkeypatch.setattr(discovery, "discover_company_contacts", failed_enqueue)
    with db.begin() as session:
        project = seed(session, external_id="failed-contact-enqueue")
        project.region_status = "ELIGIBLE"
        project_id = project.id
        result = enrich_buying_chain(
            session,
            project_id,
            fetcher=lambda _url: source(
                "Acme is the general contractor for Orion Data Center in Austin, TX."
            ),
            now=NOW,
        )
        assert any(c["organization"] == "Acme" for c in result["candidates"])
    with db.begin() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(BuyingChainClaim)
                .where(BuyingChainClaim.project_id == project_id)
            )
            >= 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(BuyingChainRun)
                .where(BuyingChainRun.project_id == project_id)
            )
            == 1
        )


@pytest.mark.parametrize(
    ("title", "category", "expected"),
    [
        ("Operations Manager", "asset_operator", "field_operations"),
        ("Project Executive", "general_contractor", "general_contractor"),
        ("Distributed Generation Director", "owner_developer", "owner_energy"),
        ("Infrastructure Development Manager", "owner_developer", "owner_construction"),
        ("Facilities Engineering Manager", "asset_operator", "field_operations"),
        ("Electrical Construction Manager", "electrical_contractor", "electrical_contractor"),
        ("Power Procurement Manager", "owner_developer", "procurement"),
        ("HR Operations Manager", "asset_operator", None),
        ("Operations Manager", "unknown", None),
    ],
)
def test_published_relevant_role_vocabulary(title, category, expected):
    from gridlens.intelligence.buying_chain_extraction import (
        _published_roster_title,
        _role_category,
    )

    assert _role_category(title, category) == expected
    if expected is not None:
        assert _published_roster_title(title)


def test_exact_rrc_registry_phone_is_company_scoped(db, monkeypatch):
    import gridlens.intelligence.company_contact_discovery as discovery
    from gridlens.intelligence.company_contacts import company_contacts
    from gridlens.persistence.models import CompanyProjectMembership, Job

    with db.begin() as session:
        project = seed(session, external_id="rrc-registry-contact")
        project.region_status = "ELIGIBLE"
        evidence = session.scalar(
            select(Evidence)
            .join(Observation)
            .where(Observation.external_id == "rrc-registry-contact")
        )
        assert evidence is not None
        evidence.title = "RRC permit EOG Resources"
        evidence.abstract = "EOG Resources is the operator, RRC operator number 123456."
        identity = CompanyIdentity(rrc_operator_number="123456")
        session.add(identity)
        session.flush()
        session.add(
            CompanyProjectMembership(
                company_identity_id=identity.id,
                project_id=project.id,
                role="asset_operator",
                organization_name="EOG Resources",
                source_id="test",
                source_evidence_id=evidence.id,
                source_version_hash=evidence.content_hash,
                decision_basis="typed_rrc_operator_number_v1",
                operator_number="123456",
                state="current",
            )
        )
        queued = discovery.discover_company_contacts(session, identity.id)
        job = session.get(Job, UUID(queued["job_id"]))
        job.status, job.lease_owner, job.fence = "running", "contact-test", 1
        job.lease_until = datetime.now(UTC) + timedelta(minutes=5)
        job_id, company_id = job.id, identity.id

    registry_url = discovery._rrc_url("123456")
    assert registry_url is not None
    registry_text = (
        "Organization Operator Query Results\nOperator Number: 123456\n"
        "Operator Name: EOG Resources\n"
        "Organization Phone No: (713) 651-7000\n"
        "Agency Phone: (512) 000-0000\nEmergency Phone: (713) 555-1212"
    )
    monkeypatch.setattr(discovery, "SessionLocal", db)
    monkeypatch.setattr(
        discovery,
        "retrieve",
        lambda url, **_kwargs: PublicDocument(
            url,
            "RRC Operator Registry",
            registry_text,
            observed_at=NOW,
        ),
    )
    result = discovery.process_company_contact_discovery(job_id, "contact-test", 1, now=NOW)
    assert result["status"] == "partial"  # paid search was policy-blocked
    assert result["results"][0]["source_class"] == "public_registry"
    with db.begin() as session:
        contacts = company_contacts(session, company_id).contacts
        values = {method["value"] for item in contacts for method in item.methods}
        assert values == {"(713) 651-7000"}
        assert session.scalar(select(func.count()).select_from(CompanyIdentity)) == 1

    wrong = PublicDocument(
        registry_url,
        "RRC Operator Registry",
        registry_text.replace("123456", "999999"),
        observed_at=NOW,
    )
    assert discovery._rrc_public_method(wrong, "123456", "EOG Resources") is None
    wrong_company = PublicDocument(
        registry_url,
        "RRC Operator Registry",
        registry_text.replace("EOG Resources", "Other Energy"),
        observed_at=NOW,
    )
    assert discovery._rrc_public_method(wrong_company, "123456", "EOG Resources") is None


def test_contact_planner_pages_past_recent_companies(db, monkeypatch):
    import gridlens.intelligence.company_contact_discovery as discovery
    from gridlens.persistence.models import Job
    from gridlens.settings import settings

    monkeypatch.setattr(settings, "company_contact_discovery_enabled", False)

    with db.begin() as session:
        project = seed(session, external_id="contact-planner-page")
        project.region_status = "ELIGIBLE"
        enrich_buying_chain(
            session,
            project.id,
            fetcher=lambda url: source(
                "Acme is the general contractor for Orion Data Center in Austin, TX. "
                "Beta is the electrical contractor for Orion Data Center in Austin, TX."
            ),
            now=NOW,
        )
        assert discovery.plan_company_contact_jobs(session, limit=1) == 1
        assert discovery.plan_company_contact_jobs(session, limit=1) == 1
        assert discovery.plan_company_contact_jobs(session, limit=1) == 0
        jobs = session.scalars(select(Job).where(Job.kind == discovery.JOB_KIND)).all()
        assert len(jobs) == 2
        assert len({job.target_id for job in jobs}) == 2


def test_contact_planner_skips_unresolvable_company_and_reaches_later_anchor(db):
    import json

    import gridlens.intelligence.company_contact_discovery as discovery
    from gridlens.persistence.models import CompanyIdentity, CompanyProjectMembership, Job

    with db.begin() as session:
        unresolvable = seed(session, external_id="contact-unresolvable-first")
        resolvable = seed(
            session,
            external_id="contact-resolvable-second",
            identity_key="contact-resolvable-second",
        )
        unresolvable.region_status = resolvable.region_status = "ELIGIBLE"
        identities = [CompanyIdentity(id=UUID(int=1)), CompanyIdentity(id=UUID(int=2))]
        session.add_all(identities)
        session.flush()
        for project, identity, version_hash in (
            (unresolvable, identities[0], "missing-source-version"),
            (resolvable, identities[1], "a"),
        ):
            evidence = session.scalar(
                select(Evidence)
                .join(Observation)
                .where(Observation.external_id == project.external_id)
            )
            assert evidence is not None
            if project is resolvable:
                evidence.abstract = (
                    "Beta is the owner developer for Orion Data Center in Austin, TX."
                )
                interpretation = session.scalar(
                    select(Interpretation).where(
                        Interpretation.observation_id == evidence.observation_id
                    )
                )
                assert interpretation is not None
                interpretation.assessment = {
                    **interpretation.assessment,
                    "project_identity_key": project.identity_key,
                }
            session.add(
                CompanyProjectMembership(
                    company_identity_id=identity.id,
                    project_id=project.id,
                    role="owner_developer",
                    organization_name="Beta" if project is resolvable else "Missing Source Co",
                    source_id="test",
                    source_evidence_id=evidence.id,
                    source_version_hash=version_hash,
                    decision_basis="typed_owner_membership_v1",
                    operator_number="000000",
                    state="current",
                )
            )
        queued = discovery.plan_company_contact_jobs(session, limit=1, now=NOW)
        assert queued == 1
        jobs = session.scalars(select(Job).where(Job.kind == discovery.JOB_KIND)).all()
        by_company = {job.target_id: job for job in jobs}
        assert by_company[identities[0].id].status == "succeeded"
        assert json.loads(by_company[identities[0].id].checkpoint)["planner_receipt"] is True
        assert by_company[identities[1].id].status == "queued"


def test_due_unresolved_contact_search_can_be_enqueued_again_in_same_epoch(db):
    import json

    import gridlens.intelligence.company_contact_discovery as discovery
    from gridlens.persistence.models import CompanyIdentity, CompanyProjectMembership, Job

    with db.begin() as session:
        project = seed(session, external_id="contact-unresolved-retry")
        project.region_status = "ELIGIBLE"
        evidence = session.scalar(
            select(Evidence).join(Observation).where(Observation.external_id == project.external_id)
        )
        assert evidence is not None
        identity = CompanyIdentity(id=UUID(int=77))
        session.add(identity)
        session.flush()
        session.add(
            CompanyProjectMembership(
                company_identity_id=identity.id,
                project_id=project.id,
                role="owner_developer",
                organization_name="Orion Development",
                source_id="test",
                source_evidence_id=evidence.id,
                source_version_hash=evidence.content_hash,
                decision_basis="typed_owner_membership_v1",
                operator_number="000077",
                state="current",
            )
        )
        session.flush()
        start_day = date.fromordinal((NOW.date().toordinal() // 30 + 1) * 30 + 1)
        start = datetime.combine(start_day, datetime.min.time(), tzinfo=UTC)
        initial = discovery.discover_company_contacts(session, identity.id, now=start)
        assert initial["status"] == "queued"
        first = session.get(Job, UUID(initial["job_id"]))
        assert first is not None
        first.status = "succeeded"
        checkpoint = json.loads(first.checkpoint)
        checkpoint.update(
            status="unresolved",
            completed_at=start.isoformat(),
            retry_after=(start + timedelta(days=7)).isoformat(),
        )
        first.checkpoint = json.dumps(checkpoint)
        retry_at = start + timedelta(days=8)
        assert retry_at.date().toordinal() // 30 == start.date().toordinal() // 30
        retried = discovery.discover_company_contacts(session, identity.id, now=retry_at)
        assert retried["status"] == "queued"
        assert retried["deduplicated"] is False
        assert retried["job_id"] != initial["job_id"]


def test_expired_public_contact_method_is_hidden_but_company_relationship_survives(db):
    from gridlens.domain.evaluation_clock import evaluate_at
    from gridlens.intelligence.company_contact_discovery import _known_contact_urls
    from gridlens.intelligence.company_contacts import company_contacts

    with db.begin() as session:
        project = seed(session, external_id="aging-contact-method")
        retained = session.scalar(select(Evidence))
        assert retained is not None
        retained.abstract = "Acme is the general contractor for Orion Data Center in Austin, TX."
        contact_quote = "Acme email: contact@acme.example"
        fetched = PublicDocument(
            URL,
            retained.title,
            f"{retained.title}\n{retained.abstract}\n{contact_quote}",
            date(2026, 9, 21),
            NOW,
        )
        initial = enrich_buying_chain(session, project.id, fetcher=lambda _url: fetched, now=NOW)
        acme = next(item for item in initial["candidates"] if item["organization"] == "Acme")
        assert [row["value"] for row in acme["public_contacts"]] == ["contact@acme.example"]
        old = NOW + timedelta(days=366)
        current = buying_chain_view(session, project.id, now=old)
        acme = next(item for item in current["candidates"] if item["organization"] == "Acme")
        assert acme["organization_relationship"] == "DIRECT"
        assert acme["stale"] is False
        assert acme["public_contacts"] == []
        source = next(
            row
            for row in session.scalars(
                select(BuyingChainEvidence).where(
                    BuyingChainEvidence.project_id == project.id,
                    BuyingChainEvidence.retained_evidence_id.is_(None),
                )
            )
            if contact_quote in row.excerpt
        )
        evidence_row = next(
            row
            for row in acme["evidence"]
            if str(row["id"]) == str(source.id) and row["supports"] == "public_contact"
        )
        assert evidence_row["contact_stale"] is True
        link = session.scalar(
            select(BuyingChainIdentityLink).where(
                BuyingChainIdentityLink.claim_id == UUID(str(acme["id"])),
                BuyingChainIdentityLink.entity_type == "company",
                BuyingChainIdentityLink.state == "current",
            )
        )
        assert link is not None and link.company_identity_id is not None
        with evaluate_at(old):
            refreshed_projection = company_contacts(session, link.company_identity_id)
            assert refreshed_projection.research_required is True
            assert all(not contact.methods for contact in refreshed_projection.contacts)
            discovery_urls = _known_contact_urls(session, link.company_identity_id, [project])
        assert URL in discovery_urls


def test_contact_anchor_skips_stale_member_project_for_current_later_source(db):
    import gridlens.intelligence.company_contact_discovery as discovery
    from gridlens.persistence.models import CompanyProjectMembership, Job

    with db.begin() as session:
        projects = [
            seed(session, external_id="anchor-first", identity_key="anchor-first"),
            seed(session, external_id="anchor-second", identity_key="anchor-second"),
        ]
        identity = CompanyIdentity(rrc_operator_number="123456")
        session.add(identity)
        session.flush()
        sorted_projects = sorted(projects, key=lambda item: item.id)
        stale_project, fresh_project = sorted_projects
        for project in sorted_projects:
            project.region_status = "ELIGIBLE"
            evidence = session.scalar(
                select(Evidence)
                .join(Observation)
                .where(Observation.external_id == project.external_id)
            )
            interpretation = session.scalar(
                select(Interpretation)
                .join(Observation)
                .where(Observation.external_id == project.external_id)
            )
            assert evidence is not None and interpretation is not None
            evidence.title = "Acme operator filing"
            evidence.abstract = "Acme is the operator, RRC operator number 123456."
            assessment = dict(interpretation.assessment)
            assessment["project_identity_key"] = project.identity_key
            interpretation.assessment = assessment
            if project.id == stale_project.id:
                evidence.content_hash = "b"  # interpretation still accepted old hash a
            session.add(
                CompanyProjectMembership(
                    company_identity_id=identity.id,
                    project_id=project.id,
                    role="asset_operator",
                    organization_name="Acme",
                    source_id="test",
                    source_evidence_id=evidence.id,
                    source_version_hash=evidence.content_hash,
                    decision_basis="typed_rrc_operator_number_v1",
                    operator_number="123456",
                    state="current",
                )
            )
        selected = discovery._select_anchor_project(
            session, discovery._projects(session, identity.id), identity.id
        )
        assert selected is not None and selected.id == fresh_project.id
        queued = discovery.discover_company_contacts(
            session, identity.id, candidate_urls=["https://acme.example/contact"]
        )
        assert queued["status"] == "queued"
        assert session.get(Job, UUID(queued["job_id"])).target_id == identity.id


def test_contact_fetch_discarded_when_membership_changes(db, monkeypatch):
    import gridlens.intelligence.company_contact_discovery as discovery
    from gridlens.intelligence.company_contacts import company_contacts
    from gridlens.persistence.models import CompanyProjectMembership, Job

    with db.begin() as session:
        project = seed(session, external_id="contact-source-fence")
        project.region_status = "ELIGIBLE"
        evidence = session.scalar(
            select(Evidence)
            .join(Observation)
            .where(Observation.external_id == "contact-source-fence")
        )
        assert evidence is not None
        evidence.title = "Acme owner filing"
        evidence.abstract = "Acme is the project owner."
        identity = CompanyIdentity()
        session.add(identity)
        session.flush()
        membership = CompanyProjectMembership(
            company_identity_id=identity.id,
            project_id=project.id,
            role="owner_developer",
            organization_name="Acme",
            source_id="test",
            source_evidence_id=evidence.id,
            source_version_hash=evidence.content_hash,
            decision_basis="typed_source_v1",
            operator_number="000000",
            state="current",
        )
        session.add(membership)
        queued = discovery.discover_company_contacts(
            session, identity.id, candidate_urls=["https://acme.example/contact"]
        )
        job = session.get(Job, UUID(queued["job_id"]))
        job.status, job.lease_owner, job.fence = "running", "contact-test", 1
        job.lease_until = datetime.now(UTC) + timedelta(minutes=5)
        job_id, company_id, membership_id = job.id, identity.id, membership.id

    monkeypatch.setattr(discovery, "SessionLocal", db)

    def changed_source(url, **_kwargs):
        with db.begin() as session:
            row = session.get(CompanyProjectMembership, membership_id)
            row.version += 1
        return PublicDocument(
            url,
            "Acme Contact",
            "Email: office@acme.example\n© 2026 Acme. All rights reserved.",
            observed_at=NOW,
        )

    monkeypatch.setattr(discovery, "retrieve", changed_source)
    result = discovery.process_company_contact_discovery(job_id, "contact-test", 1, now=NOW)
    assert result["status"] == "unresolved"
    assert result["results"] == [{"status": "unresolved", "reason": "source_context_changed"}]
    with db.begin() as session:
        assert company_contacts(session, company_id).contacts == []
        assert session.scalar(select(func.count()).select_from(BuyingChainClaim)) == 0


@pytest.mark.parametrize("uncertain", [False, True])
def test_contact_search_uses_one_accounted_logical_call(db, monkeypatch, uncertain):
    import json
    from decimal import Decimal

    from pydantic import SecretStr

    import gridlens.ingestion.adapters.pursuit_acquisition as acquisition
    import gridlens.integrations.legacy_calls as legacy_calls
    import gridlens.intelligence.company_contact_discovery as discovery
    from gridlens.persistence.models import CompanyProjectMembership, Job, LogicalCall

    with db.begin() as session:
        project = seed(session, external_id="contact-accounted-search")
        project.region_status = "ELIGIBLE"
        evidence = session.scalar(
            select(Evidence)
            .join(Observation)
            .where(Observation.external_id == "contact-accounted-search")
        )
        assert evidence is not None
        evidence.title, evidence.abstract = "Acme owner filing", "Acme is the project owner."
        identity = CompanyIdentity()
        session.add(identity)
        session.flush()
        session.add(
            CompanyProjectMembership(
                company_identity_id=identity.id,
                project_id=project.id,
                role="owner_developer",
                organization_name="Acme",
                source_id="test",
                source_evidence_id=evidence.id,
                source_version_hash=evidence.content_hash,
                decision_basis="typed_source_v1",
                operator_number="000000",
                state="current",
            )
        )
        queued = discovery.discover_company_contacts(session, identity.id, now=NOW)
        job = session.get(Job, UUID(queued["job_id"]))
        job.status, job.lease_owner, job.fence = "running", "contact-test", 1
        job.lease_until = datetime.now(UTC) + timedelta(minutes=5)
        job_id, company_id = job.id, identity.id

    monkeypatch.setattr(discovery, "SessionLocal", db)
    monkeypatch.setattr(legacy_calls, "SessionLocal", db)
    for name, value in {
        "intelligence_enabled": True,
        "intelligence_mode": "evaluation",
        "intelligence_enabled_contracts": "FIRECRAWL_SEARCH_V2",
        "intelligence_research_enabled": True,
        "intelligence_max_active_calls": 2,
        "intelligence_max_call_usd": Decimal("0.1"),
        "firecrawl_api_key": SecretStr("fixture-key"),
        "firecrawl_search_cost_usd": Decimal("0.01"),
    }.items():
        monkeypatch.setattr(settings, name, value)
    for scope in ("global", "provider", "model", "source", "project"):
        for period in ("daily", "monthly"):
            monkeypatch.setattr(settings, f"intelligence_{scope}_{period}_calls", 10)
            monkeypatch.setattr(settings, f"intelligence_{scope}_{period}_usd", Decimal("1"))
    calls = []

    def search(_query, **_kwargs):
        calls.append(1)
        if uncertain:
            raise TimeoutError("simulated transport interruption")
        return []

    monkeypatch.setattr(acquisition, "discover_urls", search)
    monkeypatch.setattr(
        discovery,
        "retrieve",
        lambda *_args, **_kwargs: pytest.fail(
            "An empty or uncertain search cannot fetch an invented URL"
        ),
    )
    result = discovery.process_company_contact_discovery(job_id, "contact-test", 1, now=NOW)
    assert result["status"] == "unresolved"
    with db.begin() as session:
        checkpoint = json.loads(session.get(Job, job_id).checkpoint)
        logical = session.scalar(select(LogicalCall))
        assert logical is not None
        assert checkpoint["search_logical_call_id"] == str(logical.id)
        assert logical.status == ("SENT_OUTCOME_UNKNOWN" if uncertain else "COMPLETED")
        # The worker outcome uses the synthetic NOW clock, so replay it against
        # that same instant; a real-time retry after the 7-day unresolved delay
        # is a different scenario and must not be mistaken for immediate dedupe.
        replay = discovery.discover_company_contacts(session, company_id, now=NOW)
        assert replay["job_id"] == str(job_id)
        assert replay["deduplicated"] is True
    assert len(calls) == 1


def test_no_hint_contact_job_identity_survives_discovery_and_refresh_epoch(db, monkeypatch):
    import json

    import gridlens.intelligence.company_contact_discovery as discovery
    from gridlens.intelligence.company_contacts import company_contacts
    from gridlens.persistence.models import CompanyProjectMembership, Job

    with db.begin() as session:
        project = seed(session, external_id="contact-no-hint-replay")
        project.region_status = "ELIGIBLE"
        evidence = session.scalar(
            select(Evidence)
            .join(Observation)
            .where(Observation.external_id == "contact-no-hint-replay")
        )
        assert evidence is not None
        evidence.title, evidence.abstract = "Acme owner filing", "Acme is the project owner."
        identity = CompanyIdentity()
        session.add(identity)
        session.flush()
        session.add(
            CompanyProjectMembership(
                company_identity_id=identity.id,
                project_id=project.id,
                role="owner_developer",
                organization_name="Acme",
                source_id="test",
                source_evidence_id=evidence.id,
                source_version_hash=evidence.content_hash,
                decision_basis="typed_source_v1",
                operator_number="000000",
                state="current",
            )
        )
        queued = discovery.discover_company_contacts(session, identity.id, now=NOW)
        job = session.get(Job, UUID(queued["job_id"]))
        job.status, job.lease_owner, job.fence = "running", "contact-test", 1
        job.lease_until = datetime.now(UTC) + timedelta(minutes=5)
        job_id, company_id = job.id, identity.id

    monkeypatch.setattr(discovery, "SessionLocal", db)
    search_calls = []
    contact_url = "https://acme.example/contact"
    monkeypatch.setattr(
        discovery,
        "_search_official_urls",
        lambda *_args, **_kwargs: search_calls.append(True) or [contact_url],
    )
    monkeypatch.setattr(
        discovery,
        "retrieve",
        lambda url, **_kwargs: PublicDocument(
            url,
            "Acme Contact" if url == contact_url else "Acme owner filing",
            (
                "Acme company contact. Email: info@acme.example.\n© 2026 Acme. All rights reserved."
                if url == contact_url
                else "Acme is the project owner."
            ),
            observed_at=NOW,
        ),
    )
    first = discovery.process_company_contact_discovery(job_id, "contact-test", 1, now=NOW)
    assert first["status"] == "complete"
    with db.begin() as session:
        first_job = session.get(Job, job_id)
        first_checkpoint = json.loads(first_job.checkpoint)
        assert first_checkpoint["payload"]["candidate_urls"] == []
        assert first_checkpoint["checked_urls"] == [contact_url]
        replay = discovery.discover_company_contacts(session, company_id, now=NOW)
        assert replay["job_id"] == str(job_id)
        assert replay["deduplicated"] is True
        assert json.loads(session.get(Job, job_id).checkpoint)["payload"]["candidate_urls"] == []

    next_epoch = NOW + timedelta(days=30)
    with db.begin() as session:
        fresh = discovery.discover_company_contacts(session, company_id, now=next_epoch)
        assert fresh["job_id"] != str(job_id)
        fresh_job = session.get(Job, UUID(fresh["job_id"]))
        assert json.loads(fresh_job.checkpoint)["payload"]["candidate_urls"] == []
        fresh_job.status, fresh_job.lease_owner, fresh_job.fence = "running", "contact-test", 1
        fresh_job.lease_until = datetime.now(UTC) + timedelta(minutes=5)
        fresh_id = fresh_job.id
    second = discovery.process_company_contact_discovery(
        fresh_id, "contact-test", 1, now=next_epoch
    )
    assert second["status"] == "complete"
    assert len(search_calls) == 1  # The new epoch reused the verified checked URL.
    with db.begin() as session:
        assert json.loads(session.get(Job, fresh_id).checkpoint)["checked_urls"] == [
            contact_url,
            URL,
        ]
        contacts = company_contacts(session, company_id).contacts
        assert any(
            method["value"] == "info@acme.example"
            for contact in contacts
            for method in contact.methods
        ), repr(contacts)


def test_company_site_gate_rejects_government_and_third_party_mentions():
    from gridlens.intelligence.company_contact_discovery import _self_identified_company_site

    assert not _self_identified_company_site(
        PublicDocument(
            "https://state.example.gov/permits/egai",
            "Permit applicant EG AI Corp",
            "EG AI Corp. Agency phone: 555-555-0101. © 2026 State Agency.",
        ),
        "EG AI Corp",
    )
    assert not _self_identified_company_site(
        PublicDocument(
            "https://directory.example.com/egai",
            "EG AI Corp listing",
            "EG AI Corp. Contact 555-555-0101. © 2026 Directory Inc.",
        ),
        "EG AI Corp",
    )
    assert _self_identified_company_site(
        PublicDocument(
            "https://egai.us/contact/",
            "Contact EG AI Corp",
            "info@egai.us\n© 2026 EG AI Corp. All rights reserved.",
        ),
        "EG AI Corp",
    )
    assert _self_identified_company_site(
        PublicDocument(
            "https://www.cogc.com/contact-us/",
            "Contact Citation",
            "Phone: 432.262.7600\n© 2026 Citation Oil & Gas Corp.\nHome\nContact Us",
        ),
        "CITATION OIL & GAS CORP.",
    )
    assert _self_identified_company_site(
        PublicDocument(
            "https://flatlandoilandgas.com/",
            "Flatland Oil & Gas, LLC",
            "Flat Land Oil & Gas, LLC is focused on opportunities. We pursue oil and gas assets.",
        ),
        "FLAT LAND OIL & GAS, LLC",
    )
    assert not _self_identified_company_site(
        PublicDocument(
            "https://directory.example.com/eg-ai",
            "EG AI Corp listing",
            "© 2026 Directory Inc.\nEG AI Corp article.",
        ),
        "EG AI CORP",
    )


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
    assert client.post(path + "/enrich").status_code == 404
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    assert client.get(path).json()["status"] == "not_researched"
    assert (
        client.post(path + "/enrich", headers={"origin": "https://evil.example"}).status_code == 404
    )
    assert (
        client.get("/api/projects/00000000-0000-0000-0000-000000000000/buying-chain").status_code
        == 404
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


TDLR_SOURCE = "texas-tdlr-tabs-data-centers"
TDLR_CASES = [
    (
        "TABS2027002672",
        "DAL130 - Data Center",
        "13572 N. Main Street, Westlake, TX 76262 (Tarrant County)",
        "Circle T Owner LP",
        """Project: DAL130 - Data Center (Circle T Ranch DAL130 Campus)
Location: 13572 N. Main Street, Westlake, TX 76262 (Tarrant County)
Registered: 2026-10-02
Developer-reported start: 2026-12-01; completion: 2027-06-01
Estimated cost: $83,000,000
Type of work: New Construction
Scope: New construction of a data center - 224,152 square feet +/-
Owner: Circle T Owner LP
Design firm: Ci Design
TABS status: Project Registered""",
    ),
    (
        "TABS2026026955",
        "PECOS COUNTY DATA CENTER",
        "6000 TX-18, Fort Stockton, TX 79735 (Pecos County)",
        "AMAZON DATA SERVICES, INC",
        """Project: PECOS COUNTY DATA CENTER (Building B)
Location: 6000 TX-18, Fort Stockton, TX 79735 (Pecos County)
Registered: 2026-08-04
Developer-reported start: 2026-08-01; completion: 2026-12-01
Estimated cost: $300,000,000
Type of work: New Construction
Scope: New data center building
Owner: AMAZON DATA SERVICES, INC
Design firm: M. ARTHUR GENSLER & ASSOCIATES, INC.
TABS status: Project Registered""",
    ),
    (
        "TABS2027002808",
        "EG AI RICE CAMPUS DATA CENTER",
        "800 NW MCKINNEY ST, Rice, TX 75155 (Navarro County)",
        "EG AI CORP",
        """Project: EG AI RICE CAMPUS DATA CENTER (EG AI RICE CAMPUS)
Location: 800 NW MCKINNEY ST, Rice, TX 75155 (Navarro County)
Registered: 2026-10-05
Developer-reported start: 2026-11-06; completion: 2028-04-30
Estimated cost: $5,000,000
Type of work: New Construction
Scope: NEW BUILDING FOR DATA CENTER, INCLUDING FOUNDATION, SLAB, FRAMING, WALLS AND ROOF
Owner: EG AI CORP
Design firm: not stated
TABS status: Project Registered""",
    ),
    (
        "TABS2027000611",
        "Beacon Point Data Center Project",
        "4650 FM 1694, ROBSTOWN, TX 78380, Corpus Christi, TX 78380 (Nueces County)",
        "Beacon Point DC LLC aka Lon Hill Infrastructure LLC",
        """Project: Beacon Point Data Center Project (Beacon Point Data Center)
Location: 4650 FM 1694, ROBSTOWN, TX 78380, Corpus Christi, TX 78380 (Nueces County)
Registered: 2026-09-09
Developer-reported start: 2026-09-28; completion: 2027-11-05
Estimated cost: $398,985,153
Type of work: New Construction
Scope: Type IIB construction of a fully sprinklered, 657,130 square foot, mixed use occupancy \
(primarily B) data center building and associated guardhouse, fire water tank and pump, and \
exterior mechanical and electrical support structures.
Owner: Beacon Point DC LLC aka Lon Hill Infrastructure LLC
Design firm: Jacobs Project Management Co.
TABS status: Project Registered""",
    ),
    (
        "TABS2026026959",
        "PECOS COUNTY DATA CENTER",
        "6000 TX-18, Fort Stockton, TX 79735 (Pecos County)",
        "AMAZON DATA SERVICES, INC",
        """Project: PECOS COUNTY DATA CENTER (Building C)
Location: 6000 TX-18, Fort Stockton, TX 79735 (Pecos County)
Registered: 2026-08-04
Developer-reported start: 2026-08-01; completion: 2026-12-01
Estimated cost: $300,000,000
Type of work: New Construction
Scope: New data center building
Owner: AMAZON DATA SERVICES, INC
Design firm: M. ARTHUR GENSLER & ASSOCIATES, INC.
TABS status: Project Registered""",
    ),
    (
        "TABS2026026954",
        "PECOS COUNTY DATA CENTER",
        "6000 TX-18, Fort Stockton, TX 79735 (Pecos County)",
        "AMAZON DATA SERVICES, INC",
        """Project: PECOS COUNTY DATA CENTER (Building A)
Location: 6000 TX-18, Fort Stockton, TX 79735 (Pecos County)
Registered: 2026-08-04
Developer-reported start: 2026-08-01; completion: 2026-12-01
Estimated cost: $300,000,000
Type of work: New Construction
Scope: New data center building.
Owner: AMAZON DATA SERVICES, INC
Design firm: M. ARTHUR GENSLER & ASSOCIATES, INC.
TABS status: Project Registered""",
    ),
]


def _tdlr_document(number, name, location, owner, excerpt, *, url_number=None, extra=""):
    url_number = url_number or number
    text = excerpt + (f"\n{extra}" if extra else "")
    return PublicDocument(
        f"https://www.tdlr.texas.gov/TABS/Search/Project/{url_number}",
        f"{name} — TDLR TABS {number}",
        text,
        None,
        NOW,
        "TDLR TABS project details page",
        retained_version="a" * 64,
    )


@pytest.mark.parametrize(("number", "name", "location", "owner", "excerpt"), TDLR_CASES)
def test_tdlr_retained_owner_is_bound_to_exact_current_project(
    number, name, location, owner, excerpt
):
    project = SimpleNamespace(
        source_id=TDLR_SOURCE,
        external_id=f"TABS-{number}",
        name=name,
        location=location,
        identity_facts={"site": location},
    )
    doc = _tdlr_document(number, name, location, owner, excerpt)
    claims = extract_retained_permit_organizations(doc, TDLR_SOURCE, project=project)

    assert len(claims) == 1
    claim = claims[0]
    assert claim.organization == owner
    assert claim.category == "owner_developer"
    assert claim.organization_relationship == "DIRECT"
    assert claim.citations[0]["url"] == doc.url
    assert claim.citations[0]["quote"] == f"Owner: {owner}"
    assert claim.citations[0]["supports"] == "project_organization"
    assert "purchasing authority" in claim.reason
    assert "temporary-power demand" in claim.reason


def test_tdlr_owner_contact_name_does_not_inherit_generic_owner_phone():
    number, name, location, owner, excerpt = TDLR_CASES[1]
    excerpt += (
        "\nOwner contact: Jordan Smith"
        "\nOwner phone: (713) 555-0100"
        "\nOwner contact phone: not stated"
        "\nOwner email: not stated"
        "\nOwner contact email: not stated"
    )
    project = SimpleNamespace(
        source_id=TDLR_SOURCE,
        external_id=f"TABS-{number}",
        name=name,
        location=location,
        identity_facts={"site": location},
    )
    doc = _tdlr_document(number, name, location, owner, excerpt)
    claims = extract_retained_permit_organizations(doc, TDLR_SOURCE, project=project)
    organization = next(item for item in claims if item.person_name is None)
    person = next(item for item in claims if item.person_name)

    assert organization.public_contacts[0]["value"] == "(713) 555-0100"
    assert organization.public_contacts[0]["quote"] == "Owner phone: (713) 555-0100"
    assert organization.public_contacts[0]["source_url"] == doc.url
    assert any(
        citation["supports"] == "public_contact"
        and citation["quote"] == "Owner phone: (713) 555-0100"
        for citation in organization.citations
    )
    assert "Owner phone: (713) 555-0100" in doc.text
    assert person.person_name == "Jordan Smith"
    assert person.public_contacts == []
    assert all(citation["supports"] != "public_contact" for citation in person.citations)

    explicit = excerpt.replace(
        "Owner contact phone: not stated", "Owner contact phone: (713) 555-0101"
    )
    direct = extract_retained_permit_organizations(
        _tdlr_document(number, name, location, owner, explicit), TDLR_SOURCE, project=project
    )
    person_with_method = next(item for item in direct if item.person_name)
    assert person_with_method.public_contacts[0]["value"] == "(713) 555-0101"
    assert person_with_method.public_contacts[0]["quote"] == ("Owner contact phone: (713) 555-0101")
    assert person_with_method.public_contacts[0]["source_url"] == doc.url
    assert any(
        citation["supports"] == "public_contact"
        and citation["quote"] == "Owner contact phone: (713) 555-0101"
        for citation in person_with_method.citations
    )


def test_tdlr_named_owner_reuses_exact_project_company_link_without_duplicate_contact_job(db):
    from gridlens.intelligence.identity_reconciliation import (
        _same_current_project_organization_source,
        ensure_project_scoped_identity_links,
    )
    from gridlens.persistence.models import Job

    number, name, location, owner, excerpt = TDLR_CASES[1]
    excerpt += "\nOwner contact: Jordan Smith\nOwner phone: (713) 555-0100"
    case = (number, name, location, owner, excerpt)
    with db.begin() as session:
        project, _retained, _owner = _seed_tdlr_retained_project(session, case)
        project.region_status = "ELIGIBLE"
        result = enrich_buying_chain(session, project.id, retained_only=True, now=NOW)
        organization = next(
            item
            for item in result["candidates"]
            if item["organization"] == owner and not item["person_name"]
        )
        person = next(
            item
            for item in result["candidates"]
            if item["organization"] == owner and item["person_name"] == "Jordan Smith"
        )
        assert (
            _same_current_project_organization_source(
                person,
                organization,
                person_project_id=project.id,
                company_project_id=project.id,
            )
            is not None
        )
        assert person["company_identity_id"] == organization["company_identity_id"]
        assert person["person_identity_id"] != person["company_identity_id"]
        person_claim_id = UUID(str(person["id"]))
        company_identity_id = UUID(str(organization["company_identity_id"]))

        person_company_links = session.scalars(
            select(BuyingChainIdentityLink)
            .where(
                BuyingChainIdentityLink.claim_id == person_claim_id,
                BuyingChainIdentityLink.entity_type == "company",
            )
            .order_by(BuyingChainIdentityLink.created_at, BuyingChainIdentityLink.id)
        ).all()
        assert len(person_company_links) == 2
        assert [link.state for link in person_company_links].count("superseded") == 1
        current_person_company = next(
            link for link in person_company_links if link.state == "current"
        )
        assert current_person_company.company_identity_id == company_identity_id

        company_jobs = session.scalars(
            select(Job).where(
                Job.kind == "company_contact_discovery",
                Job.target_id == company_identity_id,
            )
        ).all()
        assert len(company_jobs) == 1
        ensure_project_scoped_identity_links(session, [str(organization["id"]), str(person["id"])])
        assert (
            len(
                session.scalars(
                    select(Job).where(
                        Job.kind == "company_contact_discovery",
                        Job.target_id == company_identity_id,
                    )
                ).all()
            )
            == 1
        )
        assert (
            len(
                session.scalars(
                    select(BuyingChainIdentityLink).where(
                        BuyingChainIdentityLink.claim_id == person_claim_id,
                        BuyingChainIdentityLink.entity_type == "company",
                    )
                ).all()
            )
            == 2
        )


@pytest.mark.parametrize("suppressed_link", ["person_company", "organization_company"])
def test_tdlr_exact_company_identity_reuse_preserves_company_suppressions(
    db, monkeypatch, suppressed_link
):
    import json

    from gridlens.intelligence import identity_reconciliation
    from gridlens.intelligence.contact_suppressions import (
        company_suppression_key,
        record_contact_suppression,
    )
    from gridlens.persistence.models import Job

    real_reconcile = identity_reconciliation._reuse_exact_project_company_for_named_people
    monkeypatch.setattr(
        identity_reconciliation,
        "_reuse_exact_project_company_for_named_people",
        lambda *_args: None,
    )
    number, name, location, owner, excerpt = TDLR_CASES[1]
    excerpt += "\nOwner contact: Jordan Smith\nOwner phone: (713) 555-0100"
    with db.begin() as session:
        project, _retained, _owner = _seed_tdlr_retained_project(
            session, (number, name, location, owner, excerpt)
        )
        project.region_status = "ELIGIBLE"
        result = enrich_buying_chain(session, project.id, retained_only=True, now=NOW)
        organization = next(
            item
            for item in result["candidates"]
            if item["organization"] == owner and not item["person_name"]
        )
        person = next(
            item
            for item in result["candidates"]
            if item["organization"] == owner and item["person_name"] == "Jordan Smith"
        )
        person_company_id = UUID(str(person["company_identity_id"]))
        organization_company_id = UUID(str(organization["company_identity_id"]))
        assert person_company_id != organization_company_id
        suppressed_id = (
            person_company_id if suppressed_link == "person_company" else organization_company_id
        )
        record_contact_suppression(
            session,
            scope="company",
            subject_key=company_suppression_key(suppressed_id),
            action="suppress",
            expected_version=0,
            reason="Privacy fixture: preserve company-scoped suppression across identity refresh.",
            actor="test",
            idempotency_key=f"identity-reuse-{suppressed_link}",
        )

        monkeypatch.setattr(
            identity_reconciliation,
            "_reuse_exact_project_company_for_named_people",
            real_reconcile,
        )
        person_claim_id = UUID(str(person["id"]))
        identity_reconciliation.ensure_project_scoped_identity_links(
            session, [str(organization["id"]), str(person["id"])]
        )
        current_person_link = session.scalar(
            select(BuyingChainIdentityLink).where(
                BuyingChainIdentityLink.claim_id == person_claim_id,
                BuyingChainIdentityLink.entity_type == "company",
                BuyingChainIdentityLink.state == "current",
            )
        )
        assert current_person_link is not None
        assert current_person_link.company_identity_id == person_company_id

        current_view = buying_chain_view(session, project.id)
        history_view = buying_chain_view(session, project.id, history=True)
        search_view = buying_chain_views(session, {project.id})[str(project.id)]
        for view in (current_view, history_view, search_view):
            suppressed = [
                candidate for candidate in view["candidates"] if candidate.get("suppressed")
            ]
            assert suppressed
            assert all(
                "Jordan Smith" not in json.dumps(candidate, default=str)
                and "(713) 555-0100" not in json.dumps(candidate, default=str)
                for candidate in suppressed
            )
        expected_suppressed_claim = person if suppressed_link == "person_company" else organization
        assert any(
            candidate.get("suppressed")
            for candidate in current_view["candidates"]
            if str(candidate.get("id")) == str(expected_suppressed_claim["id"])
        )

        contact_jobs = session.scalars(
            select(Job).where(
                Job.kind == "company_contact_discovery",
                Job.target_id.in_([person_company_id, organization_company_id]),
            )
        ).all()
        assert len(contact_jobs) == 2


def test_tdlr_company_alignment_preserves_scoped_method_suppression(db, monkeypatch):
    from gridlens.intelligence import identity_reconciliation
    from gridlens.intelligence.contact_suppressions import (
        method_suppression_key,
        record_contact_suppression,
    )

    real_reconcile = identity_reconciliation._reuse_exact_project_company_for_named_people
    monkeypatch.setattr(
        identity_reconciliation,
        "_reuse_exact_project_company_for_named_people",
        lambda *_args: None,
    )
    number, name, location, owner, excerpt = TDLR_CASES[1]
    excerpt += "\nOwner contact: Jordan Smith\nOwner contact phone: (713) 555-0100"
    with db.begin() as session:
        project, _retained, _owner = _seed_tdlr_retained_project(
            session, (number, name, location, owner, excerpt)
        )
        result = enrich_buying_chain(session, project.id, retained_only=True, now=NOW)
        organization = next(
            candidate
            for candidate in result["candidates"]
            if candidate["organization"] == owner and not candidate["person_name"]
        )
        person = next(
            candidate
            for candidate in result["candidates"]
            if candidate["person_name"] == "Jordan Smith"
        )
        old_company_id = UUID(str(person["company_identity_id"]))
        assert person["company_identity_id"] != organization["company_identity_id"]
        assert person["public_contacts"]
        record_contact_suppression(
            session,
            scope="method",
            subject_key=method_suppression_key(
                old_company_id, "Jordan Smith", "phone", "(713) 555-0100"
            ),
            action="suppress",
            expected_version=0,
            reason="Keep a company-scoped method private across identity refresh.",
            actor="test",
            idempotency_key="tdlr-method-suppression-before-company-alignment",
        )
        person_claim_id = UUID(str(person["id"]))
        monkeypatch.setattr(
            identity_reconciliation,
            "_reuse_exact_project_company_for_named_people",
            real_reconcile,
        )
        identity_reconciliation.ensure_project_scoped_identity_links(
            session, [str(organization["id"]), str(person["id"])]
        )
        current_person_link = session.scalar(
            select(BuyingChainIdentityLink).where(
                BuyingChainIdentityLink.claim_id == person_claim_id,
                BuyingChainIdentityLink.entity_type == "company",
                BuyingChainIdentityLink.state == "current",
            )
        )
        assert current_person_link is not None
        assert current_person_link.company_identity_id == old_company_id
        for view in (
            buying_chain_view(session, project.id),
            buying_chain_view(session, project.id, history=True),
            buying_chain_views(session, {project.id})[str(project.id)],
        ):
            person_view = next(
                candidate
                for candidate in view["candidates"]
                if candidate.get("person_name") == "Jordan Smith"
            )
            assert not person_view["public_contacts"]


def test_same_project_company_identity_alignment_rejects_other_project_source_or_name():
    from gridlens.intelligence.identity_reconciliation import (
        _same_current_project_organization_source,
    )

    person_candidate = {
        "organization": "Acme Energy",
        "organization_relationship": "DIRECT",
        "person_name": "Jordan Smith",
        "evidence": [
            {
                "id": "source-a",
                "current_source_version_id": "source-a",
                "content_hash": "a" * 64,
                "current_support": True,
                "supports": "project_organization",
                "quote": "Owner: Acme Energy",
            },
            {
                "id": "source-a",
                "current_source_version_id": "source-a",
                "content_hash": "a" * 64,
                "current_support": True,
                "supports": "organization_person_role",
                "quote": "Owner contact: Jordan Smith",
            },
        ],
    }
    company_candidate = {
        "organization": "Acme Energy",
        "organization_relationship": "DIRECT",
        "person_name": None,
        "evidence": [
            {
                "id": "source-a",
                "current_source_version_id": "source-a",
                "content_hash": "a" * 64,
                "current_support": True,
                "supports": "project_organization",
                "quote": "Owner: Acme Energy",
            }
        ],
    }
    assert _same_current_project_organization_source(
        person_candidate,
        company_candidate,
        person_project_id=UUID(int=1),
        company_project_id=UUID(int=1),
    ) == ("source-a", "a" * 64)
    assert (
        _same_current_project_organization_source(
            person_candidate,
            company_candidate,
            person_project_id=UUID(int=1),
            company_project_id=UUID(int=2),
        )
        is None
    )

    other_source = {**company_candidate, "evidence": [dict(company_candidate["evidence"][0])]}
    other_source["evidence"][0]["id"] = "source-b"
    other_source["evidence"][0]["current_source_version_id"] = "source-b"
    assert (
        _same_current_project_organization_source(
            person_candidate,
            other_source,
            person_project_id=UUID(int=1),
            company_project_id=UUID(int=1),
        )
        is None
    )

    refreshed_source = {
        **company_candidate,
        "evidence": [
            {
                **company_candidate["evidence"][0],
                "content_hash": "b" * 64,
            }
        ],
    }
    assert (
        _same_current_project_organization_source(
            person_candidate,
            refreshed_source,
            person_project_id=UUID(int=1),
            company_project_id=UUID(int=1),
        )
        is None
    )

    other_name = {**company_candidate, "organization": "Acme Energy, Inc."}
    assert (
        _same_current_project_organization_source(
            person_candidate,
            other_name,
            person_project_id=UUID(int=1),
            company_project_id=UUID(int=1),
        )
        is None
    )
    assert (
        _same_current_project_organization_source(
            {**person_candidate, "correction_stale": True},
            company_candidate,
            person_project_id=UUID(int=1),
            company_project_id=UUID(int=1),
        )
        is None
    )
    assert (
        _same_current_project_organization_source(
            {**person_candidate, "suppressed": True},
            company_candidate,
            person_project_id=UUID(int=1),
            company_project_id=UUID(int=1),
        )
        is None
    )


@pytest.mark.parametrize(
    ("case", "url_number", "project_name", "location", "owner", "extra"),
    [
        (
            "wrong-url",
            "TABS2026000000",
            "PECOS COUNTY DATA CENTER",
            "6000 TX-18, Fort Stockton, TX 79735 (Pecos County)",
            "Amazon Data Services, Inc",
            "",
        ),
        (
            "missing-owner",
            "TABS2026026955",
            "PECOS COUNTY DATA CENTER",
            "6000 TX-18, Fort Stockton, TX 79735 (Pecos County)",
            "",
            "",
        ),
        (
            "conflicting-owner",
            "TABS2026026955",
            "PECOS COUNTY DATA CENTER",
            "6000 TX-18, Fort Stockton, TX 79735 (Pecos County)",
            "Amazon Data Services, Inc",
            "Owner: Other Company LLC\n",
        ),
        (
            "not-stated",
            "TABS2026026955",
            "PECOS COUNTY DATA CENTER",
            "6000 TX-18, Fort Stockton, TX 79735 (Pecos County)",
            "not stated",
            "",
        ),
        (
            "applicant-only",
            "TABS2026026955",
            "PECOS COUNTY DATA CENTER",
            "6000 TX-18, Fort Stockton, TX 79735 (Pecos County)",
            "",
            "Applicant: Amazon Data Services, Inc\n",
        ),
        (
            "wrong-project",
            "TABS2026026955",
            "OTHER DATA CENTER",
            "6000 TX-18, Fort Stockton, TX 79735 (Pecos County)",
            "Amazon Data Services, Inc",
            "",
        ),
        (
            "wrong-site",
            "TABS2026026955",
            "PECOS COUNTY DATA CENTER",
            "800 NW McKinney St, Rice, TX 75155 (Navarro County)",
            "Amazon Data Services, Inc",
            "",
        ),
    ],
)
def test_tdlr_owner_parser_rejects_unbound_or_ambiguous_evidence(
    case, url_number, project_name, location, owner, extra
):
    del case
    project = SimpleNamespace(
        source_id=TDLR_SOURCE,
        external_id="TABS-TABS2026026955",
        name="PECOS COUNTY DATA CENTER",
        location="6000 TX-18, Fort Stockton, TX 79735 (Pecos County)",
        identity_facts={"site": "6000 TX-18, Fort Stockton, TX 79735 (Pecos County)"},
    )
    excerpt = TDLR_CASES[1][4]
    excerpt = (
        excerpt.replace("PECOS COUNTY DATA CENTER (Building B)", project_name, 1)
        .replace(TDLR_CASES[1][2], location, 1)
        .replace("Owner: AMAZON DATA SERVICES, INC", f"Owner: {owner}", 1)
    )
    doc = _tdlr_document(
        "TABS2026026955", project_name, location, owner, excerpt, url_number=url_number, extra=extra
    )
    assert extract_retained_permit_organizations(doc, TDLR_SOURCE, project=project) == []


def _seed_tdlr_retained_project(session, case, *, bound_project_key=None):
    number, name, location, owner, excerpt = case
    if session.get(Source, TDLR_SOURCE) is None:
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
        external_id=f"TABS-{number}",
        name=name,
        location=location,
        identity_key=f"tdlr-{number}",
        identity_facts={"site": location},
    )
    session.add(project)
    session.flush()
    observation_hash = sha256(excerpt.encode()).hexdigest()
    registered = date.fromisoformat(
        next(
            line.removeprefix("Registered: ")
            for line in excerpt.splitlines()
            if line.startswith("Registered:")
        )
    )
    url = f"https://www.tdlr.texas.gov/TABS/Search/Project/{number}"
    title = f"{name} — TDLR TABS {number}"
    observation = Observation(
        source_id=TDLR_SOURCE,
        external_id=project.external_id,
        title=title,
        url=url,
        abstract=excerpt,
        published_at=None,
        content_hash=observation_hash,
    )
    session.add(observation)
    session.flush()
    evidence = Evidence(
        observation_id=observation.id,
        title=title,
        abstract=excerpt,
        url=url,
        content_hash=observation_hash,
        published_at=None,
        observed_at=NOW,
        event_date=registered,
        event_date_label="Registered with TDLR (Architectural Barriers)",
        extraction_location="TDLR TABS project details page",
    )
    session.add_all(
        [
            evidence,
            Interpretation(
                observation_id=observation.id,
                content_hash=observation_hash,
                evaluator_version="tdlr-tabs-data-center-v1",
                status="accepted",
                assessment={
                    "evidence_hash": observation_hash,
                    "decision": "accepted",
                    "project_identity_key": bound_project_key or project.identity_key,
                    "subject": project.name,
                    "location": project.location,
                    "power_activity": "construction",
                    "admission_status": "admitted",
                },
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
    return project, evidence, owner


def test_tdlr_retained_job_links_each_pecos_project_without_name_merging(db):
    with db.begin() as session:
        pecos_cases = [TDLR_CASES[index] for index in (1, 4, 5)]
        projects = [_seed_tdlr_retained_project(session, case) for case in pecos_cases]
        linked_identities = []
        for project, retained, owner in projects:
            result = enrich_buying_chain(session, project.id, retained_only=True, now=NOW)
            candidate = next(item for item in result["candidates"] if item["organization"] == owner)
            cited_owner = next(
                item for item in candidate["evidence"] if item["supports"] == "project_organization"
            )
            assert cited_owner["quote"] == f"Owner: {owner}"
            assert cited_owner["current_support"] is True
            assert cited_owner["current_source_version_id"] == cited_owner["id"]
            stored_source = session.get(BuyingChainEvidence, cited_owner["id"])
            assert stored_source is not None
            assert stored_source.retained_evidence_id == retained.id
            link = session.scalar(
                select(BuyingChainIdentityLink).where(
                    BuyingChainIdentityLink.claim_id == UUID(str(candidate["id"])),
                    BuyingChainIdentityLink.entity_type == "company",
                    BuyingChainIdentityLink.state == "current",
                )
            )
            assert link is not None
            assert link.basis == "project_scoped"
            linked_identities.append(link.company_identity_id)

        assert len({project.id for project, _, _ in projects}) == 3
        assert len(set(linked_identities)) == 3

        wrong_case = TDLR_CASES[0]
        wrong_project, _, _ = _seed_tdlr_retained_project(
            session, wrong_case, bound_project_key="another-project-key"
        )
        rejected = enrich_buying_chain(session, wrong_project.id, retained_only=True, now=NOW)
        assert rejected["candidates"] == []


def test_company_contact_survives_retained_refresh_commit_and_api(db, monkeypatch):
    from gridlens.intelligence.company_contacts import company_contacts

    contact_url = "https://acme.example/contact"
    organization = "Acme is the owner for Orion Data Center in Austin, TX."
    with db.begin() as session:
        project = seed(session)
        project.region_status = "ELIGIBLE"
        evidence = session.scalar(select(Evidence))
        evidence.abstract = organization
        session.add(
            NeedObservation(
                need_id=session.scalar(select(PowerNeed.id)), observation_id=evidence.observation_id
            )
        )
        result = enrich_buying_chain(
            session,
            project.id,
            source_urls=[contact_url],
            now=NOW,
            fetcher=lambda url: source(
                "Acme email: office@acme.example" if url == contact_url else organization, url=url
            ),
        )
        candidate = next(c for c in result["candidates"] if c["public_contacts"])
        company_id = UUID(str(candidate["company_identity_id"]))
        project_id = project.id
        assert (
            company_contacts(session, company_id).contacts[0].methods[0]["value"]
            == "office@acme.example"
        )
        replay = enrich_buying_chain(
            session, project.id, retained_only=True, now=NOW + timedelta(minutes=1)
        )
        assert str(replay["candidates"][0]["company_identity_id"]) == str(company_id)
        assert (
            company_contacts(session, company_id).contacts[0].methods[0]["value"]
            == "office@acme.example"
        )
    with db() as session:
        result = company_contacts(session, company_id)
        assert result.research_required  # a generic inbox never counts as a buyer
        assert result.contacts[0].project_ids == [project_id]
    app_module = import_module("gridlens.api.app")
    monkeypatch.setattr(app_module, "SessionLocal", db)
    client = TestClient(app_module.app)
    assert client.get(f"/api/customer-accounts/{company_id}/contacts").status_code == 401
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    response = client.get(f"/api/customer-accounts/{company_id}/contacts")
    assert response.status_code == 200
    assert response.json()["contacts"][0]["methods"][0]["href"] == "mailto:office@acme.example"


def test_contact_recovery_requeues_legacy_success_once(db, monkeypatch):
    import json

    import gridlens.intelligence.buying_chain as service

    with db.begin() as session:
        project = seed(session)
        evidence = session.scalar(select(Evidence))
        session.add(
            NeedObservation(
                need_id=session.scalar(select(PowerNeed.id)), observation_id=evidence.observation_id
            )
        )
        interpretation = session.scalar(select(Interpretation))
        interpretation.assessment = {
            **interpretation.assessment,
            "admission_policy_version": "test-policy",
        }
        original_hash = service._hash

        def legacy_hash(value):
            return original_hash(
                {k: v for k, v in value.items() if k != "contact_extraction_policy"}
            )

        monkeypatch.setattr(service, "_hash", legacy_hash)
        legacy = service.enqueue_retained_buying_chain_research(
            session, project.id, evidence.id, evidence.content_hash
        )
        assert legacy is not None
        legacy.status = "succeeded"
        session.flush()
        monkeypatch.setattr(service, "_hash", original_hash)
        new = service.enqueue_retained_buying_chain_research(
            session, project.id, evidence.id, evidence.content_hash
        )
        assert new is not None and new.id != legacy.id
        assert (
            json.loads(new.checkpoint)["request_digest"]
            != json.loads(legacy.checkpoint)["request_digest"]
        )
        repeat = service.enqueue_retained_buying_chain_research(
            session, project.id, evidence.id, evidence.content_hash
        )
        assert repeat.id == new.id


def test_contact_recovery_plan_prioritizes_tiers_and_resumes_without_writes(db, monkeypatch):
    from pathlib import Path

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "scripts"))
    from company_contact_recovery import recover

    from gridlens.persistence.models import Job

    with db.begin() as session:
        for index, tier in enumerate(("Signal", "Lead", "Prospect")):
            project = seed(session, external_id=str(index), identity_key=f"company-{index}")
            project.region_status = "ELIGIBLE"
            need = session.scalar(select(PowerNeed).where(PowerNeed.project_id == project.id))
            need.tier = tier
        first = recover(session, limit=1)
        assert first["outcomes"][0]["priority"] == 0
        second = recover(session, limit=1, cursor=first["next_cursor"])
        assert second["outcomes"][0]["priority"] == 1
        third = recover(session, limit=1, cursor=second["next_cursor"])
        assert third["outcomes"][0]["priority"] == 2
        assert session.scalar(select(func.count()).select_from(Job)) == 0


@pytest.mark.parametrize(
    "team_path",
    ("contact", "our-people", "team/jane-doe", "team.html"),
    ids=("contact-page", "people-page", "person-subpage", "html-suffix"),
)
def test_official_team_card_methods_remain_named_and_are_not_promoted_to_company_route(
    db, monkeypatch, team_path
):
    import gridlens.intelligence.company_contact_discovery as discovery
    from gridlens.intelligence.company_contacts import company_contacts
    from gridlens.persistence.models import Job

    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "mes_team_person_cards.html"
    html = fixture.read_bytes()
    team_url = f"https://www.mesltdtx.com/{team_path}"
    with db.begin() as session:
        project = seed(session, external_id="mes-team-person-methods")
        project.region_status = "ELIGIBLE"
        view = enrich_buying_chain(
            session,
            project.id,
            fetcher=lambda _url: source(
                "Masters Electrical Services is the electrical contractor for "
                "Orion Data Center in Austin, TX."
            ),
            now=NOW,
        )
        company = next(
            item
            for item in view["candidates"]
            if item["organization"] == "Masters Electrical Services"
        )
        company_id = UUID(company["company_identity_id"])
        queued = discovery.discover_company_contacts(
            session,
            company_id,
            candidate_urls=[team_url],
            now=NOW,
        )
        job = session.get(Job, UUID(queued["job_id"]))
        job.status, job.lease_owner, job.fence = "running", "contact-test", 1
        job.lease_until = datetime.now(UTC) + timedelta(minutes=5)
        job_id = job.id

    monkeypatch.setattr(discovery, "SessionLocal", db)
    monkeypatch.setattr(
        discovery,
        "retrieve",
        lambda url, **_kwargs: replace(parse_document(url, html, "text/html"), observed_at=NOW),
    )
    result = discovery.process_company_contact_discovery(job_id, "contact-test", 1, now=NOW)
    assert result["status"] == "complete"
    assert result["results"][0]["named_professionals"] == 3
    assert result["results"][0]["contacts"] == 4
    with db.begin() as session:
        view = buying_chain_view(session, project.id)
        people = {
            item["person_name"]: item
            for item in view["candidates"]
            if item.get("company_identity_id") == str(company_id) and item.get("person_name")
        }
        assert set(people) == {"Josh Spaw", "Justin Flippin", "Christopher Brannon"}
        assert [method["value"] for method in people["Josh Spaw"]["public_contacts"]] == [
            "jspaw@mesltdtx.com"
        ]
        assert [method["value"] for method in people["Christopher Brannon"]["public_contacts"]] == [
            "cbrannon@mesltdtx.com"
        ]
        assert people["Christopher Brannon"]["category"] == "procurement"
        assert people["Christopher Brannon"]["person_project_relationship"] == "ROLE_SUPPORTED"
        assert "buying authority are UNKNOWN" in people["Christopher Brannon"]["reason"]
        for person_name, email in (
            ("Josh Spaw", "jspaw@mesltdtx.com"),
            ("Justin Flippin", "jflippin@mesltdtx.com"),
            ("Christopher Brannon", "cbrannon@mesltdtx.com"),
        ):
            method_evidence = [
                item
                for item in people[person_name]["evidence"]
                if item["supports"] == "public_contact" and item["url"] == team_url
            ]
            assert len(method_evidence) == 1
            assert email in method_evidence[0]["quote"]
        projected = company_contacts(session, company_id).contacts
        named_methods = [
            (contact.name, method["value"])
            for contact in projected
            if contact.name
            for method in contact.methods
        ]
        assert len(named_methods) == 3
        assert {value for _name, value in named_methods} == {
            "jspaw@mesltdtx.com",
            "jflippin@mesltdtx.com",
            "cbrannon@mesltdtx.com",
        }
        generic_methods = [
            method["value"]
            for contact in projected
            if contact.name is None
            for method in contact.methods
        ]
        assert generic_methods == ["info@mesltdtx.com"]


def test_contact_discovery_stops_after_two_official_low_yield_pages(db, monkeypatch):
    import json

    import gridlens.intelligence.company_contact_discovery as discovery
    from gridlens.persistence.models import Job

    urls = [
        "https://acme.example/contact",
        "https://acme.example/team",
        "https://acme.example/leadership",
        "https://acme.example/about",
    ]
    with db.begin() as session:
        project = seed(session, external_id="low-yield-contact")
        project.region_status = "ELIGIBLE"
        view = enrich_buying_chain(
            session,
            project.id,
            fetcher=lambda _url: source(
                "Acme Energy is the electrical contractor for Orion Data Center in Austin, TX."
            ),
            now=NOW,
        )
        company = next(item for item in view["candidates"] if item["organization"] == "Acme Energy")
        queued = discovery.discover_company_contacts(
            session, UUID(company["company_identity_id"]), candidate_urls=urls, now=NOW
        )
        job = session.get(Job, UUID(queued["job_id"]))
        job.status, job.lease_owner, job.fence = "running", "contact-test", 1
        job.lease_until = datetime.now(UTC) + timedelta(minutes=5)
        job_id = job.id

    monkeypatch.setattr(discovery, "SessionLocal", db)
    fetched = []

    def empty_official_page(url, **_kwargs):
        fetched.append(url)
        return PublicDocument(
            url,
            "Acme Energy",
            "Acme Energy official information.\nEmail: info@acme.example.\n© 2026 Acme Energy.",
            observed_at=NOW,
        )

    monkeypatch.setattr(discovery, "retrieve", empty_official_page)
    result = discovery.process_company_contact_discovery(job_id, "contact-test", 1, now=NOW)
    assert result["status"] == "complete"
    assert result["research_required"] is True
    assert len(fetched) == 3
    with db.begin() as session:
        checkpoint = json.loads(session.get(Job, job_id).checkpoint)
        assert checkpoint["depth_stop_reason"] == "two_official_pages_without_contact_yield"
        assert checkpoint["fetched_count"] == 3
        assert checkpoint["new_contact_yield_count"] == 1
        assert checkpoint["contact_gaps"]["missing_buyer_relevant_contact_method"] is True


def test_unresolved_contact_attempt_retains_checked_sources_for_next_retry(db, monkeypatch):
    import json

    import gridlens.intelligence.company_contact_discovery as discovery
    from gridlens.persistence.models import Job

    urls = [
        "https://acme.example/contact",
        "https://acme.example/team",
        "https://acme.example/leadership",
        "https://acme.example/about",
    ]
    with db.begin() as session:
        project = seed(session, external_id="unresolved-source-reuse")
        project.region_status = "ELIGIBLE"
        view = enrich_buying_chain(
            session,
            project.id,
            fetcher=lambda _url: source(
                "Acme Energy is the electrical contractor for Orion Data Center in Austin, TX."
            ),
            now=NOW,
        )
        company_id = UUID(
            next(item for item in view["candidates"] if item["organization"] == "Acme Energy")[
                "company_identity_id"
            ]
        )
        queued = discovery.discover_company_contacts(
            session, company_id, candidate_urls=urls, now=NOW
        )
        job = session.get(Job, UUID(queued["job_id"]))
        job.status, job.lease_owner, job.fence = "running", "contact-test", 1
        job.lease_until = datetime.now(UTC) + timedelta(minutes=5)
        job_id = job.id

    monkeypatch.setattr(discovery, "SessionLocal", db)
    monkeypatch.setattr(
        discovery,
        "retrieve",
        lambda url, **_kwargs: PublicDocument(
            url,
            "Acme Energy",
            "Acme Energy official information.\n© 2026 Acme Energy.",
            observed_at=NOW,
        ),
    )
    result = discovery.process_company_contact_discovery(job_id, "contact-test", 1, now=NOW)
    assert result["status"] == "unresolved"
    with db.begin() as session:
        checkpoint = json.loads(session.get(Job, job_id).checkpoint)
        assert checkpoint["checked_urls"] == urls[:2]

    organization_urls = [f"https://acme.example/source-{index}" for index in range(5)]
    next_attempt = NOW + timedelta(days=30)
    with db.begin() as session:
        retry = discovery.discover_company_contacts(session, company_id, now=next_attempt)
        retry_job = session.get(Job, UUID(retry["job_id"]))
        assert retry_job is not None
        retry_job.status, retry_job.lease_owner, retry_job.fence = "running", "contact-test", 1
        retry_job.lease_until = datetime.now(UTC) + timedelta(minutes=5)
        retry_id = retry_job.id
    monkeypatch.setattr(
        discovery,
        "buying_chain_view",
        lambda _session, _project_id: {
            "candidates": [
                {
                    "company_identity_id": str(company_id),
                    "organization": "Acme Energy",
                    "category": "contractor",
                    "organization_relationship": "DIRECT",
                    "evidence": [
                        {
                            "supports": "project_organization",
                            "current_support": True,
                            "url": url,
                            "quote": "Acme Energy is the electrical contractor.",
                            "content_hash": f"organization-source-{index}",
                        }
                        for index, url in enumerate(organization_urls)
                    ],
                }
            ]
        },
    )
    monkeypatch.setattr(
        discovery,
        "retrieve",
        lambda url, **_kwargs: PublicDocument(
            url, "Acme Energy", "Company information only.", observed_at=next_attempt
        ),
    )
    retried = discovery.process_company_contact_discovery(
        retry_id, "contact-test", 1, now=next_attempt
    )
    assert retried["status"] == "unresolved"
    with db.begin() as session:
        reused = discovery._known_contact_urls(
            session, company_id, discovery._projects(session, company_id)
        )
        assert reused[:4] == [*urls[:2], *organization_urls[:2]]
        retry_checkpoint = json.loads(session.get(Job, retry_id).checkpoint)
        assert retry_checkpoint["checked_urls"] == [*urls[:2], *organization_urls[:2]]


def test_high_priority_missing_buyer_uses_bounded_six_page_depth(db, monkeypatch):
    import json

    import gridlens.intelligence.company_contact_discovery as discovery
    from gridlens.intelligence.enrichment_planner import (
        DEEP_RESEARCH_PROFILE,
        STANDARD_RESEARCH_PROFILE,
    )
    from gridlens.persistence.models import Job

    urls = [f"https://acme.example/p{index}" for index in range(4)]
    expanded = ["https://acme.example/p4", "https://acme.example/p5"]
    with db.begin() as session:
        project = seed(session, external_id="adaptive-contact-depth")
        project.region_status = "ELIGIBLE"
        view = enrich_buying_chain(
            session,
            project.id,
            fetcher=lambda _url: source(
                "Acme Energy is the electrical contractor for Orion Data Center in Austin, TX."
            ),
            now=NOW,
        )
        company = next(item for item in view["candidates"] if item["organization"] == "Acme Energy")
        company_id = UUID(company["company_identity_id"])
        queued = discovery.discover_company_contacts(
            session,
            company_id,
            candidate_urls=urls,
            now=NOW,
            research_profile=STANDARD_RESEARCH_PROFILE,
        )
        job = session.get(Job, UUID(queued["job_id"]))
        job.status, job.lease_owner, job.fence = "running", "contact-test", 1
        job.lease_until = datetime.now(UTC) + timedelta(minutes=5)
        job_id = job.id

    monkeypatch.setattr(discovery, "SessionLocal", db)
    fetched = []

    def page(url, **_kwargs):
        fetched.append(url)
        return PublicDocument(
            url,
            "Acme Energy",
            "Acme Energy official information.\n© 2026 Acme Energy.",
            observed_at=NOW,
            links=tuple(expanded) if url == urls[0] else (),
        )

    monkeypatch.setattr(discovery, "retrieve", page)
    shallow_result = discovery.process_company_contact_discovery(job_id, "contact-test", 1, now=NOW)
    assert shallow_result["status"] == "unresolved"
    assert len(fetched) == discovery.MAX_CANDIDATE_URLS
    with db.begin() as session:
        checkpoint = json.loads(session.get(Job, job_id).checkpoint)
        assert checkpoint["research_profile"] == STANDARD_RESEARCH_PROFILE
        assert checkpoint["fetch_budget"] == discovery.MAX_CANDIDATE_URLS
        assert checkpoint["fetched_count"] == discovery.MAX_CANDIDATE_URLS
        assert checkpoint["contact_gaps"]["missing_buyer_relevant_contact_method"] is True
        deep = discovery.discover_company_contacts(
            session,
            company_id,
            candidate_urls=urls,
            now=NOW,
            research_profile=DEEP_RESEARCH_PROFILE,
        )
        assert deep["job_id"] != str(job_id)
        deep_job = session.get(Job, UUID(deep["job_id"]))
        deep_job.status, deep_job.lease_owner, deep_job.fence = "running", "contact-test", 1
        deep_job.lease_until = datetime.now(UTC) + timedelta(minutes=5)
        deep_job_id = deep_job.id
    fetched.clear()
    result = discovery.process_company_contact_discovery(deep_job_id, "contact-test", 1, now=NOW)
    assert result["status"] == "unresolved"
    assert len(fetched) == discovery.MAX_ADAPTIVE_FETCHES
    with db.begin() as session:
        checkpoint = json.loads(session.get(Job, deep_job_id).checkpoint)
        assert checkpoint["research_profile"] == DEEP_RESEARCH_PROFILE
        assert checkpoint["payload"]["research_profile"] == DEEP_RESEARCH_PROFILE
        assert checkpoint["fetch_budget"] == discovery.MAX_ADAPTIVE_FETCHES
        assert checkpoint["fetched_count"] == discovery.MAX_ADAPTIVE_FETCHES
        assert checkpoint["contact_gaps"]["missing_buyer_relevant_contact_method"] is True


def test_named_nonbuyer_contact_does_not_suppress_missing_buyer_search(db, monkeypatch):
    import json

    import gridlens.intelligence.company_contact_discovery as discovery
    from gridlens.persistence.models import Job

    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "mes_team_person_cards.html"
    html = fixture.read_bytes().replace(
        b"      <div>\n"
        b"        <h3>Christopher Brannon, Purchasing Manager</h3>\n"
        b'        <p><a href="mailto:cbrannon@mesltdtx.com">Contact Chris by Email</a></p>\n'
        b"      </div>\n",
        b"",
    )
    with db.begin() as session:
        project = seed(session, external_id="named-nonbuyer-search")
        project.region_status = "ELIGIBLE"
        view = enrich_buying_chain(
            session,
            project.id,
            fetcher=lambda _url: source(
                "Masters Electrical Services is the electrical contractor for "
                "Orion Data Center in Austin, TX."
            ),
            now=NOW,
        )
        company_id = UUID(
            next(
                item
                for item in view["candidates"]
                if item["organization"] == "Masters Electrical Services"
            )["company_identity_id"]
        )
        queued = discovery.discover_company_contacts(
            session,
            company_id,
            candidate_urls=["https://www.mesltdtx.com/team"],
            now=NOW,
        )
        job = session.get(Job, UUID(queued["job_id"]))
        job.status, job.lease_owner, job.fence = "running", "contact-test", 1
        job.lease_until = datetime.now(UTC) + timedelta(minutes=5)
        first_job_id = job.id

    monkeypatch.setattr(discovery, "SessionLocal", db)
    monkeypatch.setattr(
        discovery,
        "retrieve",
        lambda url, **_kwargs: replace(parse_document(url, html, "text/html"), observed_at=NOW),
    )
    first = discovery.process_company_contact_discovery(first_job_id, "contact-test", 1, now=NOW)
    assert first["status"] == "complete"
    with db.begin() as session:
        from gridlens.intelligence.company_contacts import company_contacts

        projection = company_contacts(session, company_id)
        assert any(
            contact.name == "Josh Spaw" and contact.role == "electrical contractor"
            for contact in projection.contacts
        )
        assert all(contact.role != "procurement" for contact in projection.contacts if contact.name)
        queued = discovery.discover_company_contacts(
            session,
            company_id,
            now=NOW,
            refresh_generation="buyer-role-recovery",
        )
        job = session.get(Job, UUID(queued["job_id"]))
        assert json.loads(job.checkpoint)["payload"]["candidate_urls"] == []
        job.status, job.lease_owner, job.fence = "running", "contact-test", 1
        job.lease_until = datetime.now(UTC) + timedelta(minutes=5)
        second_job_id = job.id

    monkeypatch.setattr(discovery, "_known_contact_urls", lambda *_args, **_kwargs: [])
    searches = []
    monkeypatch.setattr(
        discovery,
        "_search_official_urls",
        lambda *_args, **_kwargs: searches.append("bounded-search") or [],
    )
    second = discovery.process_company_contact_discovery(second_job_id, "contact-test", 1, now=NOW)
    assert searches == ["bounded-search"]
    assert second["status"] == "unresolved"
    assert second["results"][0]["reason"] == "no_verified_refresh_source"


def test_projected_owner_role_method_clears_buyer_relevant_gap_without_authority_claim(db):
    from gridlens.intelligence.company_contact_discovery import _contact_research_gaps
    from gridlens.intelligence.company_contacts import company_contacts

    with db.begin() as session:
        project = seed(session, external_id="projected-owner-role-method")
        project.region_status = "ELIGIBLE"
        view = enrich_buying_chain(
            session,
            project.id,
            fetcher=lambda _url: source(
                "Acme Energy is the developer for Orion Data Center in Austin, TX."
            ),
            now=NOW,
        )
        company = next(item for item in view["candidates"] if item["organization"] == "Acme Energy")
        company_id = UUID(company["company_identity_id"])
        project_support = next(
            item
            for item in company["evidence"]
            if item["supports"] == "project_organization" and item["current_support"]
        )
        organization_source = session.get(BuyingChainEvidence, project_support["id"])
        assert organization_source is not None

        role_quote = "Jordan Smith is Vice President of Development at Acme Energy."
        method_quote = "Jordan Smith email: jordan@acme.example."
        roster_source = BuyingChainEvidence(
            project_id=project.id,
            url="https://acme.example/leadership",
            title="Acme Energy Leadership",
            excerpt=f"{role_quote}\n{method_quote}",
            content_hash="a" * 64,
            extraction_location="official roster fixture",
            observed_at=NOW,
            last_seen_at=NOW,
            project_match_reason="Official organization roster.",
        )
        session.add(roster_source)
        session.flush()
        person = BuyingChainClaim(
            project_id=project.id,
            entity_key="owner-role-method-fixture",
            fingerprint="b" * 64,
            policy_version="test",
            organization="Acme Energy",
            person_name="Jordan Smith",
            title="Vice President of Development",
            category="owner_developer",
            organization_relationship="DIRECT",
            person_organization_relationship="CURRENT",
            person_project_relationship="ROLE_SUPPORTED",
            evidence_strength="High",
            reason="Current organizational role; buying authority is UNKNOWN.",
            citations=[
                {
                    "evidence_id": str(organization_source.id),
                    "url": organization_source.url,
                    "quote": project_support["quote"],
                    "supports": "project_organization",
                },
                {
                    "evidence_id": str(roster_source.id),
                    "url": roster_source.url,
                    "quote": role_quote,
                    "supports": "organization_person_role",
                },
                {
                    "evidence_id": str(roster_source.id),
                    "url": roster_source.url,
                    "quote": method_quote,
                    "supports": "public_contact",
                },
            ],
            public_contacts=[
                {
                    "kind": "email",
                    "value": "jordan@acme.example",
                    "source_url": roster_source.url,
                    "quote": method_quote,
                    "observed_at": NOW.isoformat(),
                }
            ],
            observed_at=NOW,
        )
        session.add(person)
        session.flush()
        session.add(
            BuyingChainIdentityLink(
                claim_id=person.id,
                entity_type="company",
                company_identity_id=company_id,
                reason="Same current source-cited owner organization.",
                basis="reviewed_alias",
                source_evidence_id=organization_source.id,
                source_version_hash=organization_source.content_hash,
                state="current",
            )
        )
        current_run = session.scalar(
            select(BuyingChainRun)
            .where(BuyingChainRun.project_id == project.id)
            .order_by(BuyingChainRun.created_at.desc(), BuyingChainRun.id.desc())
            .limit(1)
        )
        assert current_run is not None
        current_run.claim_ids = [*current_run.claim_ids, str(person.id)]
        current_run.evidence_ids = [*current_run.evidence_ids, str(roster_source.id)]
        session.flush()

        projection = company_contacts(session, company_id)
        jordan = next(contact for contact in projection.contacts if contact.name == "Jordan Smith")
        assert jordan.role == "owner developer"
        assert jordan.methods[0]["value"] == "jordan@acme.example"
        assert jordan.purchasing_authority == "Requires confirmation for this power package"
        assert _contact_research_gaps(session, company_id) == (False, False)


@pytest.mark.parametrize(
    ("page_text", "expected_status", "expected_projected_method"),
    [
        (
            "Acme Energy\nAcme Energy is the developer for Orion Data Center in Austin, TX.\n"
            "Email: info@acme-energy.example\n"
            "© 2026 Acme Energy, Inc. All rights reserved.",
            "complete",
            True,
        ),
        (
            "Unrelated Company\nEmail: contact@unrelated.example\n"
            "© 2026 Unrelated Company. All rights reserved.",
            "unresolved",
            False,
        ),
        (
            "Acme Energy\nEmail: info@acme-energy.example\n"
            "© 2026 Acme Energy, Inc. All rights reserved.",
            "complete",
            False,
        ),
    ],
)
def test_current_company_source_is_untrusted_but_useful_cold_start_seed(
    db, monkeypatch, page_text, expected_status, expected_projected_method
):
    """Planner-to-worker reuse fetches a cited company page, then verifies its publisher."""
    import json

    import gridlens.intelligence.company_contact_discovery as discovery
    from gridlens.intelligence.company_contacts import company_contacts
    from gridlens.persistence.models import Job, Observation

    company_url = "https://acme-energy.example/about/"
    with db.begin() as session:
        project = seed(session, external_id="company-source-contact-cold-start")
        project.region_status = "ELIGIBLE"
        evidence = session.scalar(
            select(Evidence)
            .join(Observation)
            .where(Observation.external_id == "company-source-contact-cold-start")
        )
        assert evidence is not None
        evidence.url = company_url
        evidence.abstract = "Acme Energy is the developer for Orion Data Center in Austin, TX."
        observation = session.get(Observation, evidence.observation_id)
        assert observation is not None
        observation.url = company_url
        chain = enrich_buying_chain(session, project.id, now=NOW, retained_only=True)
        candidate = next(row for row in chain["candidates"] if row["organization"] == "Acme Energy")
        company_id = UUID(candidate["company_identity_id"])
        historical_claim_id = candidate["id"]
        historical_claim = session.get(BuyingChainClaim, historical_claim_id)
        assert historical_claim is not None
        historical_citations = json.loads(json.dumps(historical_claim.citations))
        session.add(
            CompanyProjectMembership(
                company_identity_id=company_id,
                project_id=project.id,
                role="owner_developer",
                organization_name="Acme Energy",
                source_id="test",
                source_evidence_id=evidence.id,
                source_version_hash=evidence.content_hash,
                decision_basis="typed_owner_membership_v1",
                operator_number="123456",
                state="current",
            )
        )
        session.flush()
        assert discovery._known_contact_urls(session, company_id, [project]) == [company_url]
        assert discovery._projects(session, company_id) == [project]
        assert discovery._select_anchor_project(session, [project], company_id) is project
        assert discovery._contact_research_gaps(session, company_id) == (True, True)
        prior_job_ids = list(
            session.scalars(
                select(Job.id).where(Job.kind == discovery.JOB_KIND, Job.target_id == company_id)
            )
        )
        assert discovery.plan_company_contact_jobs(session, limit=1, now=NOW) == 1
        # Retained enrichment may already have queued a job in this transaction.
        # Select the planner's new job rather than ordering equal timestamps by UUID.
        job = session.scalars(
            select(Job).where(
                Job.kind == discovery.JOB_KIND,
                Job.target_id == company_id,
                Job.id.not_in(prior_job_ids),
            )
        ).one()
        checkpoint = json.loads(job.checkpoint)
        # The source citation is an untrusted cold-start fetch anchor. It must
        # reach the worker as a candidate URL without becoming a verified
        # contact or an authority-bearing company claim by itself.
        assert checkpoint["payload"]["candidate_urls"] == [company_url]
        job.status = "running"
        job.lease_owner = "contact-cold-start-test"
        job.fence = 1
        job.lease_until = datetime.now(UTC) + timedelta(minutes=5)
        job.created_at = NOW
        job_id = job.id

    monkeypatch.setattr(discovery, "SessionLocal", db)
    monkeypatch.setattr(
        discovery,
        "retrieve",
        lambda url, **_kwargs: PublicDocument(url, "Company page", page_text, observed_at=NOW),
    )
    result = discovery.process_company_contact_discovery(
        job_id, "contact-cold-start-test", 1, now=NOW
    )
    assert result["status"] == expected_status
    with db.begin() as session:
        projected = company_contacts(session, company_id)
        methods = [method for contact in projected.contacts for method in contact.methods]
        checkpoint = json.loads(session.get(Job, job_id).checkpoint)
        assert bool(methods) is expected_projected_method
        assert session.get(BuyingChainClaim, historical_claim_id).citations == historical_citations
        assert checkpoint["checked_urls"] == [company_url]
        if expected_status == "unresolved":
            assert result["results"][0]["reason"] == "official_identity_unverified"


def test_current_contact_refresh_seed_precedes_organization_discovery_seeds(db, monkeypatch):
    import json
    from uuid import uuid4

    import gridlens.intelligence.company_contact_discovery as discovery
    from gridlens.persistence.models import Job

    with db.begin() as session:
        project = seed(session, external_id="contact-refresh-seed-priority")
        company_id = uuid4()
        org_sources = [
            {
                "supports": "project_organization",
                "current_support": True,
                "url": f"https://source-{index}.example/record",
            }
            for index in range(5)
        ]
        contact_source = {
            "supports": "public_contact",
            "current_support": True,
            "url": "https://acme.example/contact",
        }
        previously_checked = ["https://acme.example/checked/contact"]
        session.add(
            Job(
                source_id=project.source_id,
                kind=discovery.JOB_KIND,
                target_id=company_id,
                status="succeeded",
                checkpoint=json.dumps({"status": "unresolved", "checked_urls": previously_checked}),
            )
        )
        monkeypatch.setattr(
            discovery,
            "_company_hyperlink_hints",
            lambda *_args: {
                "urls": ["https://acme.com/imported-citation"],
                "fingerprint": "metadata-hints-fingerprint",
            },
        )
        monkeypatch.setattr(
            discovery,
            "buying_chain_view",
            lambda *_args, **_kwargs: {
                "candidates": [
                    {
                        "company_identity_id": str(company_id),
                        "evidence": [*org_sources, contact_source],
                    }
                ]
            },
        )
        urls = discovery._known_contact_urls(session, company_id, [project])
        assert urls[:4] == [
            "https://acme.example/contact",
            *previously_checked,
            "https://acme.com/imported-citation",
            "https://source-0.example/record",
        ]
        assert len(urls[: discovery.MAX_CANDIDATE_URLS]) == discovery.MAX_CANDIDATE_URLS
        assert "https://acme.example/contact" in urls[: discovery.MAX_CANDIDATE_URLS]
        assert "https://acme.com/imported-citation" in urls[: discovery.MAX_CANDIDATE_URLS]
        assert "https://source-0.example/record" in urls[: discovery.MAX_CANDIDATE_URLS]


def test_organization_discovery_seeds_require_current_company_and_public_url(db, monkeypatch):
    from uuid import uuid4

    import gridlens.intelligence.company_contact_discovery as discovery

    with db.begin() as session:
        project = seed(session, external_id="contact-org-seed-scope")
        company_id, other_company_id = uuid4(), uuid4()
        monkeypatch.setattr(
            discovery,
            "buying_chain_view",
            lambda *_args, **_kwargs: {
                "candidates": [
                    {
                        "company_identity_id": str(company_id),
                        "evidence": [
                            {
                                "supports": "project_organization",
                                "current_support": False,
                                "url": "https://stale.example/company",
                            },
                            {
                                "supports": "project_organization",
                                "current_support": True,
                                "url": "http://127.0.0.1/admin",
                            },
                        ],
                    },
                    {
                        "company_identity_id": str(other_company_id),
                        "evidence": [
                            {
                                "supports": "project_organization",
                                "current_support": True,
                                "url": "https://other.example/company",
                            }
                        ],
                    },
                ]
            },
        )
        assert discovery._known_contact_urls(session, company_id, [project]) == []
