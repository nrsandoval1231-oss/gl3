from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from test_buying_chain import seed

from gridlens.domain.evaluation_clock import evaluate_at
from gridlens.domain.pursuit_research import fingerprint
from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
from gridlens.intelligence.buying_chain import (
    _buying_chain_current_view,
    _store_document,
    buying_chain_view,
)
from gridlens.intelligence.buying_chain_extraction import (
    Extracted,
    document_content_hash,
    exact_native_company_roster_page,
    extract_people,
)
from gridlens.intelligence.company_contact_discovery import _discover_anchor
from gridlens.intelligence.company_contacts import company_contacts
from gridlens.intelligence.contact_suppressions import (
    company_suppression_key,
    global_person_suppression_key,
    person_suppression_key,
    record_contact_suppression,
)
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    BuyingChainClaim,
    BuyingChainEvidence,
    BuyingChainIdentityLink,
    BuyingChainRun,
    CompanyIdentity,
    PersonIdentity,
    Project,
    Source,
)
from gridlens.settings import settings

NOW = datetime(2026, 11, 13, 12, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[3]
CONTACT_ROOT = ROOT / "eval" / "customer-commercial-v1" / "contact-refresh"
PROJECT_URL = "https://www.databank.com/resources/press-releases/orion-data-center"


@pytest.fixture
def role_db():
    target, application = make_url(settings.test_database_url), make_url(settings.database_url)
    assert target.database and target.database.endswith("_test")
    assert target != application
    schema = "published_roles_" + uuid4().hex
    admin = create_engine(settings.test_database_url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        settings.test_database_url,
        connect_args={"options": f"-csearch_path={schema}"},
    )
    Base.metadata.create_all(engine)
    from gridlens.persistence.browse_invalidation import install

    with engine.begin() as connection:
        install(connection)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(
            Source(
                id="test",
                publisher="Synthetic first-party project evidence",
                endpoint=PROJECT_URL,
                family="news",
                geography="US",
                industries=[],
                retrieval_method="test",
                health={},
            )
        )
    with evaluate_at(NOW):
        yield factory
    engine.dispose()
    with admin.begin() as connection:
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    admin.dispose()


def _retained_databank_roster(*, text: str | None = None, observed_at: datetime = NOW):
    raw_path = CONTACT_ROOT / "raw" / "databank-leadership.json"
    raw = json.loads(raw_path.read_text())
    manifest = json.loads((CONTACT_ROOT / "source-manifest.json").read_text())
    entry = next(row for row in manifest["sources"] if row["source_id"] == "databank-leadership")
    page_text = raw["markdown"] if text is None else text
    assert sha256(raw["markdown"].encode()).hexdigest() == entry["source_text_sha256_utf8"]
    assert entry["publication_date"] is None
    return PublicDocument(
        url=entry["url"],
        title=entry["page_title"],
        text=page_text,
        published_at=None,
        observed_at=observed_at,
        extraction_location="retained first-party leadership-page Markdown",
    )


def test_role_parser_requires_current_leadership_section_and_native_publisher_host():
    document = PublicDocument(
        url="https://www.databank.com/about/leadership/",
        title="DataBank Leadership",
        text=(
            "# Leadership\n\nJane Doe\n\nVP, Engineering\n\n"
            "## Former Leadership\n\nJohn Former\n\nVP, Engineering\n\n"
            "## Board of Directors\n\nRuth Board\n\nDirector, Engineering\n\n"
            "## External Contractors\n\nAlex Contractor\n\nVP, Construction"
        ),
        published_at=None,
        observed_at=NOW,
    )
    native_urls = ["https://www.databank.com/resources/press-releases/project/"]
    assert exact_native_company_roster_page(
        document, "DataBank", native_company_source_urls=native_urls
    )
    assert not exact_native_company_roster_page(
        document,
        "DataBank",
        native_company_source_urls=["https://www.calpine.com/projects/project/"],
    )
    for heading in (
        "Leadership Alumni",
        "Leadership of Beta LLC",
        "Not Current Leadership",
        "Former Leadership",
        "Board of Directors",
        "External Contractors",
    ):
        rejected = PublicDocument(
            url=document.url,
            title=document.title,
            text=f"# {heading}\n\nJohn Smith\n\nVP, Engineering",
            published_at=None,
            observed_at=NOW,
        )
        assert not exact_native_company_roster_page(
            rejected, "DataBank", native_company_source_urls=native_urls
        )
    for parent in ("Former Leadership", "External Contractors", "Beta LLC"):
        nested = PublicDocument(
            url=document.url,
            title=document.title,
            text=f"# {parent}\n\n## Leadership Team\n\nJohn Smith\n\nVP, Engineering",
            published_at=None,
            observed_at=NOW,
        )
        assert not exact_native_company_roster_page(
            nested, "DataBank", native_company_source_urls=native_urls
        )
    roles = extract_people(
        document,
        [Extracted("DataBank", "owner_developer", organization_relationship="DIRECT")],
        None,
        project_scoped=False,
        today=NOW.date(),
        verified_official_roster=True,
        company_only_role=True,
    )
    assert [(role.person_name, role.title) for role in roles] == [("Jane Doe", "VP, Engineering")]
    assert roles[0].person_project_relationship == "UNKNOWN"
    assert roles[0].public_contacts == []


def _seed_native_company_anchor(
    session, company: str = "Calpine", *, native_host: str = "calpine.com"
):
    project_suffix = uuid4().hex
    project = seed(
        session,
        external_id=f"published-role-{company.casefold()}-{project_suffix}",
        identity_key=f"published-role:{company.casefold()}:{project_suffix}",
        name="Orion Data Center",
    )
    native_url = f"https://www.{native_host}/projects/orion"
    native_title = f"{company} Orion Data Center"
    native_text = f"{company} is the owner of Orion Data Center in Austin, TX."
    native_doc = PublicDocument(
        url=native_url,
        title=native_title,
        text=native_text,
        published_at=None,
        observed_at=NOW,
        extraction_location="retained first-party project-company assertion fixture",
    )
    identity = CompanyIdentity()
    session.add(identity)
    session.flush()
    source = _store_document(
        session,
        project,
        native_doc,
        "Current accepted first-party project-company assertion fixture.",
        seen_at=native_doc.observed_at,
    )
    quote = native_doc.text
    state = {
        "policy_version": "test-native-project-company-v1",
        "organization": company,
        "person_name": None,
        "title": None,
        "category": "owner_developer",
        "organization_relationship": "DIRECT",
        "person_organization_relationship": "UNKNOWN",
        "person_project_relationship": "UNKNOWN",
        "evidence_strength": "High",
        "reason": "Current source-backed project-company claim; buying authority unknown.",
        "citations": [
            {
                "evidence_id": str(source.id),
                "url": source.url,
                "quote": quote,
                "supports": "project_organization",
            }
        ],
        "public_contacts": [],
    }
    parent = BuyingChainClaim(
        project_id=project.id,
        entity_key=f"test-company:{company.casefold()}",
        fingerprint=fingerprint(state),
        observed_at=native_doc.observed_at,
        verified_at=native_doc.observed_at,
        **state,
    )
    session.add(parent)
    session.flush()
    link = BuyingChainIdentityLink(
        claim_id=parent.id,
        entity_type="company",
        company_identity_id=identity.id,
        reason="Current project-scoped company identity in synthetic retained-source fixture.",
        basis="project_scoped",
        source_evidence_id=source.id,
        source_version_hash=source.content_hash,
        state="current",
    )
    session.add(link)
    session.flush()
    session.add(
        BuyingChainRun(
            project_id=project.id,
            input_hash=fingerprint({"project": str(project.id), "source": str(source.id)}),
            evidence_ids=[str(source.id)],
            claim_ids=[str(parent.id)],
            policy_version="test-native-project-company-v1",
            status="complete",
            documents_checked=1,
            candidates_added=1,
            unresolved=[],
            created_at=NOW,
        )
    )
    session.flush()
    return project, identity.id, parent


def _seed_retained_databank_anchor(factory):
    from gridlens.ingestion.adapters.retained_company_projects import (
        FAMILY,
        RETRIEVAL_METHOD,
        SOURCE_ID,
        retained_records,
    )
    from gridlens.ingestion.service import process_records
    from gridlens.intelligence.buying_chain import enrich_buying_chain
    from gridlens.persistence.models import Evidence, Job, Observation

    records, _held = retained_records(ROOT / "eval/customer-commercial-v1")
    databank = next(
        record
        for record in records
        if "sources/databank.json" in record["retained_company_project"]["source_files"]
    )
    source_definition = {
        "id": SOURCE_ID,
        "publisher": "retained offline public documents",
        "endpoint": "https://offline.invalid/retained",
        "family": FAMILY,
        "geography": "United States",
        "industries": ["data centers"],
        "retrieval_method": RETRIEVAL_METHOD,
        "cadence_hours": 24,
        "enabled": False,
        "registry_enabled": False,
    }
    worker = "published-company-role-test"
    with factory.begin() as session:
        session.add(Source(**source_definition))
        session.flush()
        job = Job(
            source_id=SOURCE_ID,
            status="running",
            lease_owner=worker,
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        job_id = job.id
    with factory() as session:
        counts = process_records(
            session,
            job_id,
            worker,
            1,
            source_definition,
            [databank],
            allow_model=False,
            commit=False,
        )
        session.commit()
    assert counts["retrieved_records"] == 1
    with factory.begin() as session:
        project = session.scalar(
            select(Project).where(
                Project.source_id == SOURCE_ID,
                Project.external_id == databank["document_number"],
            )
        )
        assert project is not None
        evidence = session.scalar(
            select(Evidence)
            .join(Observation, Observation.id == Evidence.observation_id)
            .where(
                Observation.source_id == SOURCE_ID,
                Observation.external_id == databank["document_number"],
            )
        )
        assert evidence is not None
        enriched = enrich_buying_chain(
            session,
            project.id,
            retained_only=True,
            retained_target_evidence_id=evidence.id,
            now=NOW,
        )
        assert enriched["status"] in {"complete", "partial"}
        claim = session.scalar(
            select(BuyingChainClaim).where(
                BuyingChainClaim.project_id == project.id,
                BuyingChainClaim.organization == "DataBank",
                BuyingChainClaim.category == "owner_developer",
            )
        )
        assert claim is not None
        assert any(item["supports"] == "project_organization" for item in claim.citations)
        link = session.scalar(
            select(BuyingChainIdentityLink).where(
                BuyingChainIdentityLink.claim_id == claim.id,
                BuyingChainIdentityLink.entity_type == "company",
                BuyingChainIdentityLink.state == "current",
            )
        )
        assert link is not None and link.basis == "project_scoped"
        return project.id, link.company_identity_id


def test_retained_databank_roster_persists_company_only_role_without_methods(role_db):
    expected = {
        "Joe Minarik": ("Chief Operating Officer", "owner construction"),
        "Eric Swartz": ("VP, Operations Engineering", "owner construction"),
        "Danny Allen": ("VP, Engineering", "owner construction"),
        "David Maldonado": ("Director, Colo Engineering", "owner construction"),
        "Tony Qorri": ("VP, Construction", "owner construction"),
        "John Solensky": ("VP, Solutions Engineering", "owner construction"),
        "Vlad Friedman": ("Chief Technology Officer", "owner construction"),
        "Nick Long": ("SVP, Engineering, Operations and Service Delivery", "owner construction"),
    }
    roster = _retained_databank_roster()
    project_id, company_id = _seed_retained_databank_anchor(role_db)
    with role_db.begin() as session:
        project = session.get(Project, project_id)
        assert project is not None
        parent = session.scalar(
            select(BuyingChainClaim).where(
                BuyingChainClaim.project_id == project_id,
                BuyingChainClaim.organization == "DataBank",
                BuyingChainClaim.person_name.is_(None),
            )
        )
        assert parent is not None
        parent_link = session.scalar(
            select(BuyingChainIdentityLink).where(
                BuyingChainIdentityLink.claim_id == parent.id,
                BuyingChainIdentityLink.entity_type == "company",
                BuyingChainIdentityLink.state == "current",
            )
        )
        assert parent_link is not None
        assert parent_link.company_identity_id == company_id

        before = buying_chain_view(session, project.id, now=NOW)
        parent_before = next(
            candidate for candidate in before["candidates"] if not candidate.get("person_name")
        )
        parent_published = next(
            evidence["published_at"]
            for evidence in parent_before["evidence"]
            if evidence["supports"] == "project_organization"
        )
        assert parent_published == date(2024, 9, 10)
        latest_run_before = session.scalar(
            select(BuyingChainRun)
            .where(BuyingChainRun.project_id == project_id)
            .order_by(BuyingChainRun.created_at.desc(), BuyingChainRun.id.desc())
        )
        assert latest_run_before is not None

        result = _discover_anchor(
            session,
            session.get(Project, project.id),
            company_id,
            {roster.url: roster},
            NOW,
        )
        assert result["status"] == "complete"
        assert result["contacts"] == 0
        assert result["named_professionals"] == 8
        latest_run_after = session.scalar(
            select(BuyingChainRun)
            .where(BuyingChainRun.project_id == project_id)
            .order_by(BuyingChainRun.created_at.desc(), BuyingChainRun.id.desc())
        )
        assert latest_run_after is not None
        assert latest_run_after.id == latest_run_before.id
        assert latest_run_after.created_at == latest_run_before.created_at

        view = buying_chain_view(session, project.id, now=NOW)
        assert not any(candidate.get("person_name") for candidate in view["candidates"])
        parent_after = next(
            candidate for candidate in view["candidates"] if not candidate.get("person_name")
        )
        assert (
            next(
                evidence["published_at"]
                for evidence in parent_after["evidence"]
                if evidence["supports"] == "project_organization"
            )
            == parent_published
        )
        company_view = company_contacts(session, company_id)
        candidates = {role.name: role for role in company_view.published_company_roles}
        assert set(candidates) == set(expected)
        assert company_view.contacts == []
        for name, (title, category) in expected.items():
            role = candidates[name]
            assert role.title == title
            assert role.role.replace("_", " ") == category
            assert role.company_identity_id == str(company_id)
            assert role.responsibility == "Published company role; project involvement unverified"
            assert role.person_project_relationship == "UNKNOWN"
            assert role.methods == []
            assert role.project_ids == []
            assert role.published_at is None
            assert "leadership-team" in role.source_url
            assert role.source_quote
            assert role.source_quote in roster.text
            assert role.source_hash == document_content_hash(roster)
            assert role.observed_at == NOW.isoformat()
            assert role.valid_until == (NOW + timedelta(days=30)).isoformat()


def test_cyrusone_roster_does_not_bind_to_calpine_project_actor(role_db):
    raw = json.loads((CONTACT_ROOT / "raw" / "cyrusone-leadership.json").read_text())
    manifest = json.loads((CONTACT_ROOT / "source-manifest.json").read_text())
    entry = next(row for row in manifest["sources"] if row["source_id"] == "cyrusone-leadership")
    roster = PublicDocument(
        url=entry["url"],
        title=entry["page_title"],
        text=raw["markdown"],
        published_at=None,
        observed_at=NOW,
        extraction_location="retained first-party leadership-page Markdown",
    )
    with role_db.begin() as session:
        project, company_id, _parent = _seed_native_company_anchor(session, "Calpine")
        result = _discover_anchor(
            session,
            session.get(Project, project.id),
            company_id,
            {roster.url: roster},
            NOW,
        )
        assert result == {"status": "unresolved", "reason": "official_identity_unverified"}
        assert not session.scalars(
            select(BuyingChainClaim).where(
                BuyingChainClaim.project_id == project.id,
                BuyingChainClaim.person_name.is_not(None),
            )
        ).all()


def test_newer_company_roster_snapshot_withdraws_across_projects_and_old_replay(role_db):
    roster = _retained_databank_roster()
    withdrawn = _retained_databank_roster(
        text=roster.text.replace("Joe Minarik\n\nChief Operating Officer", ""),
        observed_at=NOW + timedelta(days=1),
    )
    tied_positive = _retained_databank_roster(observed_at=NOW + timedelta(days=1))
    with role_db.begin() as session:
        first_project, company_id, _ = _seed_native_company_anchor(
            session, "DataBank", native_host="databank.com"
        )
        second_project, second_company_id, _ = _seed_native_company_anchor(
            session, "DataBank", native_host="databank.com"
        )
        second_link = session.scalar(
            select(BuyingChainIdentityLink)
            .join(BuyingChainClaim)
            .where(
                BuyingChainClaim.project_id == second_project.id,
                BuyingChainIdentityLink.entity_type == "company",
                BuyingChainIdentityLink.state == "current",
            )
        )
        assert second_link is not None
        second_link.company_identity_id = company_id
        session.flush()
        assert second_company_id != company_id
        assert (
            _discover_anchor(
                session,
                first_project,
                company_id,
                {roster.url: roster},
                NOW,
            )["status"]
            == "complete"
        )
        with evaluate_at(NOW + timedelta(days=1)):
            assert (
                _discover_anchor(
                    session,
                    second_project,
                    company_id,
                    {withdrawn.url: withdrawn},
                    NOW + timedelta(days=1),
                )["status"]
                == "complete"
            )
            assert "Joe Minarik" not in {
                item.name for item in company_contacts(session, company_id).published_company_roles
            }
            _discover_anchor(
                session,
                first_project,
                company_id,
                {roster.url: roster},
                NOW + timedelta(days=1),
            )
            current = company_contacts(session, company_id).published_company_roles
        assert "Joe Minarik" not in {item.name for item in current}
        with evaluate_at(NOW + timedelta(days=1)):
            _discover_anchor(
                session,
                first_project,
                company_id,
                {tied_positive.url: tied_positive},
                NOW + timedelta(days=1),
            )
            assert company_contacts(session, company_id).published_company_roles == []
        with evaluate_at(NOW + timedelta(days=2)):
            positive_day_two = _retained_databank_roster(observed_at=NOW + timedelta(days=2))
            _discover_anchor(
                session,
                first_project,
                company_id,
                {positive_day_two.url: positive_day_two},
                NOW + timedelta(days=2),
            )
            assert "Joe Minarik" in {
                item.name for item in company_contacts(session, company_id).published_company_roles
            }
            competing_source = PublicDocument(
                url=roster.url,
                title=roster.title,
                text="Different evidence consumer captured this URL at the same time.",
                published_at=None,
                observed_at=NOW + timedelta(days=2),
                extraction_location="synthetic same-time source conflict",
            )
            _store_document(
                session,
                second_project,
                competing_source,
                "Self-identified official organization contact page.",
                seen_at=NOW + timedelta(days=2),
            )
            assert company_contacts(session, company_id).published_company_roles == []


def test_roster_withdrawal_survives_loss_of_project_company_link(role_db):
    roster = _retained_databank_roster()
    withdrawn = _retained_databank_roster(
        text=roster.text.replace("Joe Minarik\n\nChief Operating Officer", ""),
        observed_at=NOW + timedelta(days=1),
    )
    with role_db.begin() as session:
        first_project, company_id, _ = _seed_native_company_anchor(
            session, "DataBank", native_host="databank.com"
        )
        second_project, second_company_id, _ = _seed_native_company_anchor(
            session, "DataBank", native_host="databank.com"
        )
        second_link = session.scalar(
            select(BuyingChainIdentityLink)
            .join(BuyingChainClaim)
            .where(
                BuyingChainClaim.project_id == second_project.id,
                BuyingChainIdentityLink.entity_type == "company",
                BuyingChainIdentityLink.state == "current",
            )
        )
        assert second_link is not None
        second_link.company_identity_id = company_id
        session.flush()
        assert second_company_id != company_id
        _discover_anchor(session, first_project, company_id, {roster.url: roster}, NOW)
        with evaluate_at(NOW + timedelta(days=1)):
            _discover_anchor(
                session,
                second_project,
                company_id,
                {withdrawn.url: withdrawn},
                NOW + timedelta(days=1),
            )
            assert "Joe Minarik" not in {
                item.name for item in company_contacts(session, company_id).published_company_roles
            }

        # This project no longer contributes a current company anchor, but its
        # newer same-URL roster snapshot must still prevent an older project
        # capture from restoring the withdrawn role.
        second_link.state = "superseded"
        session.flush()
        with evaluate_at(NOW + timedelta(days=1)):
            visible = company_contacts(session, company_id).published_company_roles
        assert "Joe Minarik" not in {item.name for item in visible}


def test_methodless_roster_roles_obey_person_suppression_and_source_withdrawal(role_db):
    roster = _retained_databank_roster()
    project_id, company_id = _seed_retained_databank_anchor(role_db)
    with role_db.begin() as session:
        project = session.get(Project, project_id)
        assert project is not None
        _discover_anchor(session, project, company_id, {roster.url: roster}, NOW)
        record_contact_suppression(
            session,
            scope="person",
            subject_key=person_suppression_key(company_id, "Eric Swartz"),
            action="suppress",
            expected_version=0,
            reason="Synthetic privacy regression test",
            actor="synthetic-test",
            idempotency_key="published-role-person-suppression",
        )
        visible = company_contacts(session, company_id).published_company_roles
        assert "Eric Swartz" not in {item.name for item in visible}
        assert not any(item.methods for item in visible)
        _discover_anchor(session, project, company_id, {roster.url: roster}, NOW)
        replayed = company_contacts(session, company_id).published_company_roles
        assert "Eric Swartz" not in {item.name for item in replayed}
        assert all(item.valid_until == (NOW + timedelta(days=30)).isoformat() for item in replayed)

        withdrawn_text = roster.text.replace("Joe Minarik\n\nChief Operating Officer", "")
        assert withdrawn_text != roster.text
        withdrawn = _retained_databank_roster(
            text=withdrawn_text,
            observed_at=NOW + timedelta(days=1),
        )
        with evaluate_at(NOW + timedelta(days=1)):
            result = _discover_anchor(
                session,
                project,
                company_id,
                {withdrawn.url: withdrawn},
                NOW + timedelta(days=1),
            )
            assert result["named_professionals"] == 7
            current = company_contacts(session, company_id).published_company_roles
        assert "Joe Minarik" not in {item.name for item in current}
        assert "Eric Swartz" not in {item.name for item in current}
        assert {item.name for item in current} == {
            "Danny Allen",
            "David Maldonado",
            "Tony Qorri",
            "John Solensky",
            "Vlad Friedman",
            "Nick Long",
        }
        assert not any(item.methods for item in current)
        record_contact_suppression(
            session,
            scope="company",
            subject_key=company_suppression_key(company_id),
            action="suppress",
            expected_version=0,
            reason="Synthetic company suppression regression test",
            actor="synthetic-test",
            idempotency_key="published-role-company-suppression",
        )
        assert company_contacts(session, company_id).published_company_roles == []
        with evaluate_at(NOW + timedelta(days=32)):
            expired = company_contacts(session, company_id).published_company_roles
        assert expired == []


def test_global_person_suppression_hides_linked_roster_role(role_db):
    roster = _retained_databank_roster()
    project_id, company_id = _seed_retained_databank_anchor(role_db)
    with role_db.begin() as session:
        project = session.get(Project, project_id)
        assert project is not None
        _discover_anchor(session, project, company_id, {roster.url: roster}, NOW)
        role_source = session.scalar(
            select(BuyingChainEvidence).where(
                BuyingChainEvidence.project_id == project_id,
                BuyingChainEvidence.url == roster.url,
                BuyingChainEvidence.project_match_reason
                == "Exact actor-name company-domain roster; roles only.",
            )
        )
        assert role_source is not None
        company_claim = session.scalar(
            select(BuyingChainClaim).where(
                BuyingChainClaim.project_id == project_id,
                BuyingChainClaim.person_name.is_(None),
            )
        )
        assert company_claim is not None
        company_source_id = next(
            UUID(citation["evidence_id"])
            for citation in company_claim.citations
            if citation.get("supports") == "project_organization"
        )
        company_source = session.get(BuyingChainEvidence, company_source_id)
        assert company_source is not None
        person = PersonIdentity()
        session.add(person)
        session.flush()
        quote = "Eric Swartz\n\nVP, Operations Engineering"
        claim_state = {
            "policy_version": "test-linked-roster-person-v1",
            "organization": "DataBank",
            "person_name": "Eric Swartz",
            "title": "VP, Operations Engineering",
            "category": "owner_construction",
            "organization_relationship": "DIRECT",
            "person_organization_relationship": "CURRENT",
            "person_project_relationship": "ROLE_SUPPORTED",
            "evidence_strength": "Medium",
            "reason": "Current source-linked person identity for suppression regression.",
            "citations": [
                {
                    "evidence_id": str(company_source.id),
                    "url": company_source.url,
                    "quote": company_source.excerpt,
                    "supports": "project_organization",
                },
                {
                    "evidence_id": str(role_source.id),
                    "url": role_source.url,
                    "quote": quote,
                    "supports": "organization_person_role",
                },
            ],
            "public_contacts": [],
        }
        person_claim = BuyingChainClaim(
            project_id=project_id,
            entity_key=f"test-person:{person.id}",
            fingerprint=fingerprint(claim_state),
            observed_at=NOW,
            verified_at=NOW,
            **claim_state,
        )
        session.add(person_claim)
        session.flush()
        session.add_all(
            [
                BuyingChainIdentityLink(
                    claim_id=person_claim.id,
                    entity_type="person",
                    person_identity_id=person.id,
                    reason="Exact retained roster role claim in privacy regression fixture.",
                    basis="reviewed_alias",
                    reviewed_by="synthetic-test",
                    source_evidence_id=role_source.id,
                    source_version_hash=role_source.content_hash,
                    state="current",
                ),
                BuyingChainIdentityLink(
                    claim_id=person_claim.id,
                    entity_type="company",
                    company_identity_id=company_id,
                    reason="Current project-company link for privacy regression fixture.",
                    basis="project_scoped",
                    source_evidence_id=company_source.id,
                    source_version_hash=company_source.content_hash,
                    state="current",
                ),
            ]
        )
        session.flush()
        current_run = session.scalar(
            select(BuyingChainRun)
            .where(BuyingChainRun.project_id == project.id)
            .order_by(BuyingChainRun.created_at.desc(), BuyingChainRun.id.desc())
        )
        assert current_run is not None
        current_run.evidence_ids = list(
            dict.fromkeys([*current_run.evidence_ids, str(role_source.id)])
        )
        current_run.claim_ids = [*current_run.claim_ids, str(person_claim.id)]
        session.flush()

        current_person = next(
            candidate
            for candidate in _buying_chain_current_view(session, project_id, now=NOW)["candidates"]
            if candidate.get("person_name") == "Eric Swartz"
        )
        assert current_person["person_identity_id"] == str(person.id)
        before = company_contacts(session, company_id)
        before_role = next(
            role for role in before.published_company_roles if role.name == "Eric Swartz"
        )
        assert before_role.name == "Eric Swartz"

        record_contact_suppression(
            session,
            scope="person",
            subject_key=global_person_suppression_key(person.id),
            action="suppress",
            expected_version=0,
            reason="Synthetic global person privacy regression test",
            actor="synthetic-test",
            idempotency_key="published-role-global-person-suppression",
        )
        after = company_contacts(session, company_id)
        suppressed_person = next(
            candidate
            for candidate in buying_chain_view(session, project_id, now=NOW)["candidates"]
            if candidate.get("suppressed")
        )
        assert suppressed_person["person_name"] is None
        assert not any(role.name == "Eric Swartz" for role in after.published_company_roles)


def test_ambiguous_historical_person_links_withhold_company_roster_role(role_db):
    roster = _retained_databank_roster()
    project_id, company_id = _seed_retained_databank_anchor(role_db)
    with role_db.begin() as session:
        project = session.get(Project, project_id)
        assert project is not None
        _discover_anchor(session, project, company_id, {roster.url: roster}, NOW)
        role_source = session.scalar(
            select(BuyingChainEvidence).where(
                BuyingChainEvidence.project_id == project_id,
                BuyingChainEvidence.url == roster.url,
                BuyingChainEvidence.project_match_reason
                == "Exact actor-name company-domain roster; roles only.",
            )
        )
        company_claim = session.scalar(
            select(BuyingChainClaim).where(
                BuyingChainClaim.project_id == project_id,
                BuyingChainClaim.person_name.is_(None),
            )
        )
        assert role_source is not None and company_claim is not None
        company_source_id = next(
            UUID(citation["evidence_id"])
            for citation in company_claim.citations
            if citation.get("supports") == "project_organization"
        )
        company_source = session.get(BuyingChainEvidence, company_source_id)
        assert company_source is not None
        for suffix in ("one", "two"):
            person = PersonIdentity()
            session.add(person)
            session.flush()
            claim_state = {
                "policy_version": f"test-ambiguous-roster-person-{suffix}",
                "organization": "DataBank",
                "person_name": "Eric Swartz",
                "title": "VP, Operations Engineering",
                "category": "owner_construction",
                "organization_relationship": "DIRECT",
                "person_organization_relationship": "CURRENT",
                "person_project_relationship": "ROLE_SUPPORTED",
                "evidence_strength": "Medium",
                "reason": "Historical source-linked person identity for ambiguity regression.",
                "citations": [
                    {
                        "evidence_id": str(company_source.id),
                        "url": company_source.url,
                        "quote": company_source.excerpt,
                        "supports": "project_organization",
                    },
                    {
                        "evidence_id": str(role_source.id),
                        "url": role_source.url,
                        "quote": "Eric Swartz\n\nVP, Operations Engineering",
                        "supports": "organization_person_role",
                    },
                ],
                "public_contacts": [],
            }
            claim = BuyingChainClaim(
                project_id=project_id,
                entity_key=f"test-ambiguous-person:{suffix}",
                fingerprint=fingerprint(claim_state),
                observed_at=NOW,
                verified_at=NOW,
                **claim_state,
            )
            session.add(claim)
            session.flush()
            session.add_all(
                [
                    BuyingChainIdentityLink(
                        claim_id=claim.id,
                        entity_type="person",
                        person_identity_id=person.id,
                        reason="Historical linked person identity for ambiguity regression.",
                        basis="reviewed_alias",
                        reviewed_by="synthetic-test",
                        source_evidence_id=role_source.id,
                        source_version_hash=role_source.content_hash,
                        state="superseded",
                    ),
                    BuyingChainIdentityLink(
                        claim_id=claim.id,
                        entity_type="company",
                        company_identity_id=company_id,
                        reason="Historical company link for ambiguity regression.",
                        basis="project_scoped",
                        source_evidence_id=company_source.id,
                        source_version_hash=company_source.content_hash,
                        state="superseded",
                    ),
                ]
            )
        session.flush()

        roles = company_contacts(session, company_id).published_company_roles
        assert not any(role.name == "Eric Swartz" for role in roles)
